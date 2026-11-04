#!/usr/bin/env python3
"""W4 — package a reproducible upload batch from the crawled audio (no re-encode).

Input : <DOWNLOAD_DIR>            (medium-opus vi audio + *.info.json per video)
        <DATASET_DIR>/qc_flags.jsonl , <DATASET_DIR>/exclude.txt   (from audio_qc.py)
Output: <DATASET_DIR>/<batch_name>/
          manifest.jsonl                    one row per video (utt_id, sha256, codec...)
          stats.json                        files/hours/bytes, per channel, per month
          qc_flags.jsonl                    QC rows of THIS batch only (self-contained)
          used_ids.txt                      video_ids consumed by this batch (dedup guard)
          README.md                         human-readable batch description
          <batch>_audio.tar.part-aa, -ab...  raw audio, UNCOMPRESSED tar, size-split
          <batch>_meta.tar.gz               info.json (hardlinked staging) + batch meta
          SHA256SUMS                        every part + meta + the assembled tar stream

Design decisions (see PROJECT_STATUS.md §12.3 / §16):
  * No re-encoding and no compression of audio: the opus files are already compressed,
    so the audio is stored as a plain tar split into --max-part-size pieces
    (`cat part-* | tar -x` restores it; naming matches the handover spec exactly).
  * info.json is NEVER deleted here; it is archived into meta.tar.gz first (it is the
    only proof of upload_date/language/channel).
  * Cookies are never packaged: meta.tar.gz content is an explicit WHITELIST.
  * Hard exclusion: every video_id in exclude.txt, every row carrying a HARD QC flag,
    and (by default) every video_id already consumed by a previous batch.
  * Data must live outside the repo: refusing an in-repo batch dir unless
    ALLOW_IN_REPO_DOWNLOAD=1 (see config.env).

Usage:
  python3 metadata/make_batch.py --batch-name batch_001 --dry-run         # plan only
  python3 metadata/make_batch.py --batch-name batch_001 --limit-gb 350
  python3 metadata/make_batch.py --batch-name batch_001 --hardlink --verify
"""
import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# metadata/paths.py: single source of truth for DATA locations (mirrors ../config.env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
from audio_qc import AUDIO_EXTS, parse_filename  # noqa: E402  (reuse the exact same parsing)

HARD_FLAGS = {"corrupt", "zero_size", "wrong_language", "out_of_window"}
SIZE_UNITS = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


# --------------------------------------------------------------------------- helpers
def human_bytes(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TB"


def parse_size(text):
    """'20G' / '500M' / '12345678' -> bytes."""
    if text is None:
        return None
    raw = str(text).strip().lower()
    if not raw:
        return None
    mult = 1
    if raw[-1] in SIZE_UNITS:
        mult = SIZE_UNITS[raw[-1]]
        raw = raw[:-1]
    return int(float(raw) * mult)


def sha256_file(path, chunk=1 << 22):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _sha256_task(path_str):
    try:
        return path_str, sha256_file(path_str), None
    except OSError as exc:  # noqa: BLE001
        return path_str, None, str(exc)


def ffprobe_quick(path):
    """Minimal stream/format probe for files that have no QC row yet."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
           "stream=codec_name,sample_rate,channels:format=duration,size", "-of", "json", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        data = json.loads(proc.stdout or "{}")
    except Exception:  # noqa: BLE001
        return {}
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    if not streams:
        return {}
    stream = streams[0]

    def _num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "codec": stream.get("codec_name"),
        "sample_rate": _num(stream.get("sample_rate")),
        "channels": _num(stream.get("channels")),
        "duration": _num(fmt.get("duration")),
        "size_bytes": _num(fmt.get("size")),
    }


def run_cmd(cmd, **kwargs):
    """Run a command, returning (rc, stdout, stderr); never raises on non-zero rc."""
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    return proc.returncode, proc.stdout, proc.stderr


def iter_jsonl(path):
    """Yield parsed JSON rows of a .jsonl file (missing file -> empty)."""
    p = Path(path) if path else None
    if not p or not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ------------------------------------------------------------------ exclusion / dedup
def load_exclude_ids(exclude_file, qc_path):
    """video_ids that must never enter a batch: exclude.txt + any HARD QC flag row."""
    ids = set()
    if exclude_file and Path(exclude_file).exists():
        for line in Path(exclude_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line)
    hard_from_qc = 0
    for row in iter_jsonl(qc_path):
        vid = row.get("video_id")
        if vid and HARD_FLAGS.intersection(row.get("flags") or []):
            ids.add(vid)
            hard_from_qc += 1
    print(f"exclude ids: {len(ids)} ({hard_from_qc} taken from HARD flags in {qc_path})")
    return ids


def load_qc_index(qc_path):
    """QC rows keyed by video_id and by audio basename (measurements, flags)."""
    by_id, by_name = {}, {}
    for row in iter_jsonl(qc_path):
        vid = row.get("video_id")
        if vid:
            by_id[vid] = row
        audio_path = row.get("audio_path")
        if audio_path:
            by_name[os.path.basename(audio_path)] = row
    return by_id, by_name


def load_consumed_ids(dataset_dir, exclude_batch=None):
    """video_id -> batch_name for every video already packaged by a previous batch."""
    consumed = {}
    for used in sorted(Path(dataset_dir).glob("batch_*/used_ids.txt")):
        if exclude_batch and used.parent.name == exclude_batch:
            continue
        try:
            text = used.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            vid = line.strip()
            if vid:
                consumed.setdefault(vid, used.parent.name)
    return consumed


# ----------------------------------------------------------------------- collection
def collect_candidates(args, qc_by_id, qc_by_name, excluded_ids, consumed_ids):
    """Walk the crawl root and build one candidate record per eligible audio file."""
    records = []
    skipped = {"excluded": 0, "already_in_batch": 0, "out_of_window": 0,
               "qc_missing": 0, "no_info_json": 0, "unparsable_name": 0}
    root = args.download_dir
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
            continue
        parsed = parse_filename(path) or {}
        info_path = path.with_name(path.stem + ".info.json")
        info = {}
        if info_path.exists():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                info = {}
        else:
            skipped["no_info_json"] += 1

        video_id = parsed.get("video_id") or info.get("id")
        if not video_id:
            skipped["unparsable_name"] += 1
            continue
        if video_id in excluded_ids:
            skipped["excluded"] += 1
            continue
        if video_id in consumed_ids and not args.allow_duplicate_ids:
            skipped["already_in_batch"] += 1
            continue

        upload_date = info.get("upload_date") or parsed.get("upload_date")
        if upload_date and upload_date < args.min_upload_date:
            skipped["out_of_window"] += 1
            continue

        qc = qc_by_name.get(path.name) or qc_by_id.get(video_id) or {}
        if not qc:
            skipped["qc_missing"] += 1
        measured = {key: qc.get(key) for key in ("codec", "sample_rate", "channels",
                                                 "duration", "size_bytes")}
        if measured.get("duration") is None or measured.get("size_bytes") is None:
            for key, value in ffprobe_quick(path).items():
                if measured.get(key) is None:
                    measured[key] = value

        records.append({
            "utt_id": video_id,
            "video_id": video_id,
            "audio_path": str(path.relative_to(root)),
            "audio_name": path.name,
            "info_json_path": (str(info_path.relative_to(root))
                               if info_path.exists() else None),
            "channel": info.get("channel") or info.get("uploader"),
            "channel_id": info.get("channel_id") or parsed.get("channel_id"),
            "title": info.get("title"),
            "upload_date": upload_date,
            "duration": measured.get("duration"),
            "size_bytes": measured.get("size_bytes"),
            "codec": measured.get("codec"),
            "sample_rate": measured.get("sample_rate"),
            "channels": measured.get("channels"),
            "source_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
            "language": info.get("language"),
            "format_id": info.get("format_id"),
            "format_note": info.get("format_note"),
            "abr": info.get("abr"),
            "qc_flags": qc.get("flags") or [],
            "sha256": None,
        })
    return records, skipped


def apply_limit(records, limit_bytes):
    """Greedy size cut: whole files only; one video is never split across batches."""
    if not limit_bytes:
        return records, 0
    total, kept = 0, []
    for rec in records:
        size = rec.get("size_bytes") or 0
        if kept and total + size > limit_bytes:
            continue
        kept.append(rec)
        total += size
    return kept, len(records) - len(kept)


# ------------------------------------------------------------------- stats / outputs
def build_stats(batch_name, records, args, skipped, limited_out):
    hours = sum((r.get("duration") or 0) for r in records) / 3600.0
    total_bytes = sum((r.get("size_bytes") or 0) for r in records)
    per_channel = defaultdict(lambda: {"files": 0, "hours": 0.0, "bytes": 0})
    per_month = defaultdict(lambda: {"files": 0, "hours": 0.0, "bytes": 0})
    flags = Counter()
    formats = Counter()
    dates = []
    for rec in records:
        channel = rec.get("channel") or rec.get("channel_id") or "?"
        hours_rec = (rec.get("duration") or 0) / 3600.0
        size_rec = rec.get("size_bytes") or 0
        per_channel[channel]["files"] += 1
        per_channel[channel]["hours"] += hours_rec
        per_channel[channel]["bytes"] += size_rec
        if rec.get("upload_date"):
            month = rec["upload_date"][:6]
            per_month[month]["files"] += 1
            per_month[month]["hours"] += hours_rec
            per_month[month]["bytes"] += size_rec
            dates.append(rec["upload_date"])
        for flag in rec.get("qc_flags") or []:
            flags[flag] += 1
        formats[f"{rec.get('codec')}/{rec.get('format_id')}"] += 1
    return {
        "batch": batch_name,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_download_dir": str(args.download_dir),
        "window": {"min_upload_date": args.min_upload_date},
        "totals": {
            "files": len(records),
            "hours": round(hours, 4),
            "bytes": total_bytes,
            "gib": round(total_bytes / 1024**3, 4),
            "channels": len(per_channel),
        },
        "date_range": {"first": min(dates) if dates else None,
                       "last": max(dates) if dates else None},
        "per_channel": {k: {**v, "hours": round(v["hours"], 4),
                            "gib": round(v["bytes"] / 1024**3, 4)}
                        for k, v in sorted(per_channel.items())},
        "per_month": {k: {**v, "hours": round(v["hours"], 4),
                          "gib": round(v["bytes"] / 1024**3, 4)}
                      for k, v in sorted(per_month.items())},
        "format_id_counts": dict(formats.most_common()),
        "qc_flags_counts": dict(flags.most_common()),
        "selection": {
            "limit_gb": args.limit_gb,
            "max_part_size": args.max_part_size,
            "skipped": skipped,
            "dropped_by_limit_gb": limited_out,
            "allow_duplicate_ids": bool(args.allow_duplicate_ids),
        },
    }


def write_manifest(batch_dir, records):
    path = batch_dir / "manifest.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def write_qc_subset(batch_dir, records, qc_by_id):
    """QC rows of THIS batch only (self-contained meta), still no cookies/ids leakage."""
    wanted = {r["video_id"] for r in records}
    path = batch_dir / "qc_flags.jsonl"
    written = 0
    with open(path, "w", encoding="utf-8") as fh:
        for vid in sorted(wanted):
            row = qc_by_id.get(vid)
            if row:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
    return path, written


def write_used_ids(batch_dir, records):
    path = batch_dir / "used_ids.txt"
    with open(path, "w", encoding="utf-8") as fh:
        for vid in sorted({r["video_id"] for r in records}):
            fh.write(f"{vid}\n")
    return path


def compute_hashes(records, download_root, workers, enabled=True):
    """Fill rec['sha256'] for every record (parallel). Returns count of failures."""
    if not enabled:
        return 0
    tasks = [str(download_root / r["audio_path"]) for r in records]
    digest_by_path, failures = {}, 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index, (path_str, digest, err) in enumerate(
                pool.map(_sha256_task, tasks, chunksize=4), 1):
            if digest is None:
                failures += 1
                print(f"  sha256 FAILED for {path_str}: {err}")
            else:
                digest_by_path[path_str] = digest
            if index % 500 == 0:
                print(f"  ... hashed {index}/{len(tasks)}")
    for rec in records:
        rec["sha256"] = digest_by_path.get(str(download_root / rec["audio_path"]))
    return failures


# ----------------------------------------------------------------------- packaging
def build_audio_tar(batch_dir, batch_name, records, download_root, max_part_size):
    """Stream an UNCOMPRESSED tar into size-split parts -> (parts, stream_sha256).

    * Entry order is reproducible (tar --sort=name) so the same selection gives the
      same tar.
    * The stream is hashed on the fly (tee), so we never materialise a 400GB temp tar.
    * Part names: <batch>_audio.tar.part-aa, -ab, ...  (`cat part-* | tar -x` restores).
    """
    filelist = batch_dir / f".{batch_name}_audio_filelist.txt"
    with open(filelist, "w", encoding="utf-8") as fh:
        for rec in sorted(records, key=lambda r: r["audio_path"]):
            fh.write(rec["audio_path"] + "\n")

    part_prefix = batch_dir / f"{batch_name}_audio.tar.part-"
    stream_sha = batch_dir / f".{batch_name}_audio.tar.sha256"
    # -a 2 -> alphabetic suffixes (aa, ab, ...): 676 parts x 20G = 13 PB, so plenty.
    pipeline = (
        f"tar -cf - -C {shlex.quote(str(download_root))} "
        f"-T {shlex.quote(str(filelist))} --sort=name"
        f" | tee >(sha256sum | cut -d' ' -f1 > {shlex.quote(str(stream_sha))})"
        f" | split -b {shlex.quote(str(max_part_size))} -a 2 - {shlex.quote(str(part_prefix))}"
    )
    rc, _out, err = run_cmd(["bash", "-o", "pipefail", "-c", pipeline])
    if rc != 0:
        raise SystemExit(f"audio tar pipeline failed (rc={rc}):\n{err.strip()[:2000]}")

    parts = sorted(p for p in batch_dir.glob(f"{batch_name}_audio.tar.part-*") if p.is_file())
    digest = stream_sha.read_text(encoding="utf-8").strip() if stream_sha.exists() else None
    filelist.unlink(missing_ok=True)
    stream_sha.unlink(missing_ok=True)
    return parts, digest


def build_meta_tar(batch_dir, batch_name, records, download_root, extra_files):
    """meta.tar.gz = every info.json of the batch + the small batch files.

    info.json files are HARD-LINKED into a staging dir (0 extra bytes on the same FS)
    so one .tar.gz can carry them next to the manifest/stats/README. Content is an
    explicit whitelist built from the manifest — cookies and logs can never leak in.
    """
    stage = batch_dir / f".{batch_name}_meta_stage"
    if stage.exists():
        shutil.rmtree(stage)
    linked = copied = 0
    for rec in records:
        rel = rec.get("info_json_path")
        if not rel:
            continue
        src = download_root / rel
        if not src.exists():
            continue
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
            linked += 1
        except OSError:
            shutil.copy2(src, dst)
            copied += 1
    for path in extra_files:
        if Path(path).exists():
            shutil.copy2(path, stage / Path(path).name)

    meta_path = batch_dir / f"{batch_name}_meta.tar.gz"
    rc, _out, err = run_cmd(["tar", "-czf", str(meta_path), "-C", str(stage),
                             "--sort=name", "."])
    shutil.rmtree(stage, ignore_errors=True)
    if rc != 0:
        raise SystemExit(f"meta tar failed (rc={rc}): {err.strip()[:1000]}")
    return meta_path, linked, copied


def build_hardlink_tree(dataset_dir, records, download_root):
    """Optional 0-byte mirror: <DATASET_DIR>/audio/<channel>/<file> as hardlinks."""
    out_root = dataset_dir / "audio"
    made = skipped = 0
    for rec in records:
        src = download_root / rec["audio_path"]
        dst = out_root / rec["audio_path"]
        if dst.exists():
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
            made += 1
        except OSError as exc:
            raise SystemExit(
                f"hardlink failed ({exc}). Is DATASET_DIR on a different filesystem "
                "than DOWNLOAD_DIR? Re-run without --hardlink."
            )
    return made, skipped


def write_sha256sums(batch_dir, batch_name, parts, meta_path, manifest_path, stream_hash):
    """Standard `sha256sum -c` format; the assembled tar is listed as <batch>_audio.tar."""
    lines = []
    if stream_hash:
        lines.append(f"{stream_hash}  {batch_name}_audio.tar")
    for part in parts:
        lines.append(f"{sha256_file(part)}  {part.name}")
    lines.append(f"{sha256_file(meta_path)}  {meta_path.name}")
    lines.append(f"{sha256_file(manifest_path)}  {manifest_path.name}")
    sums = batch_dir / "SHA256SUMS"
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums


def verify_batch(batch_dir, batch_name, records, parts, meta_path, manifest_path, stream_hash):
    """Deep verification: hashes, assembled stream, archive entry names and sizes."""
    print("\n=== verify ===")
    errors = []
    expected_names = sorted(r["audio_path"] for r in records)
    expected_bytes = sum(r.get("size_bytes") or 0 for r in records)
    expected_hours = sum(r.get("duration") or 0 for r in records) / 3600.0

    sums = {}
    for line in (batch_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            sums[name.strip()] = digest.strip()

    # (a) every part + meta + manifest matches SHA256SUMS
    for path in list(parts) + [meta_path, manifest_path]:
        actual = sha256_file(path)
        if sums.get(path.name) != actual:
            errors.append(f"sha256 mismatch: {path.name}")
    print(f"  parts hashed      : {len(parts)} (+meta, +manifest)")

    # (b) reassembled stream hash == recorded stream hash
    digest = hashlib.sha256()
    total = 0
    for part in parts:
        with open(part, "rb") as fh:
            while True:
                block = fh.read(1 << 22)
                if not block:
                    break
                digest.update(block)
                total += len(block)
    if stream_hash and digest.hexdigest() != stream_hash:
        errors.append("assembled parts do not reproduce the recorded tar stream hash")
    print(f"  assembled tar     : {human_bytes(total)} sha256={digest.hexdigest()[:16]}...")

    # (c)+(d) archive listings: entry names and size sum must match the manifest.
    # --quoting-style=literal is REQUIRED: under a non-UTF-8 locale (e.g. cron with
    # LC_ALL=C) GNU tar escapes non-ASCII names (\306\257...) and the comparison would
    # fail on a perfectly good archive.
    cat_parts = " ".join(shlex.quote(str(p)) for p in parts)
    rc, out, err = run_cmd(["bash", "-o", "pipefail", "-c",
                            f"cat {cat_parts} | tar -tvf - --quoting-style=literal"])
    if rc != 0:
        errors.append(f"tar listing failed (rc={rc}): {err.strip()[:300]}")
    else:
        names, size_sum = [], 0
        for line in out.splitlines():
            fields = line.split(None, 5)
            if len(fields) < 6:
                continue
            names.append(fields[5])
            try:
                size_sum += int(fields[2])
            except ValueError:
                pass
        if sorted(names) != expected_names:
            missing = len(set(expected_names) - set(names))
            errors.append(f"archive entries != manifest ({len(names)} vs "
                          f"{len(expected_names)}, missing={missing})")
        if size_sum != expected_bytes:
            errors.append(f"archive size sum {size_sum} != manifest {expected_bytes}")
        print(f"  archive entries   : {len(names)} files, {human_bytes(size_sum)}")

    print(f"  expected          : {len(expected_names)} files, {human_bytes(expected_bytes)}, "
          f"{expected_hours:.2f} hours")
    if errors:
        for err in errors:
            print(f"  ERROR: {err}")
        return False, errors
    print("  RESULT: verify PASS")
    return True, []


def write_readme(batch_dir, batch_name, stats, parts, meta_path):
    """Human-readable batch description (uploaded alongside the tarballs)."""
    totals = stats["totals"]
    part_names = ", ".join(p.name for p in parts) or "(no parts)"
    lines = [
        f"# {batch_name} — Vietnamese YouTube audio corpus batch",
        "",
        f"- created (UTC): {stats['created_utc']}",
        f"- upload_date window: **>= {stats['window']['min_upload_date']}** (hard requirement)",
        f"- source crawl root: `{stats['source_download_dir']}` (staging only; the archive is this"
        " folder + the corpus ledger)",
        "",
        "## Totals",
        f"- files: **{totals['files']}** · hours: **{totals['hours']:.3f}** ·"
        f" size: **{human_bytes(totals['bytes'])}** ({totals['files'] and totals['bytes'] / max(totals['files'], 1) / 1024**2:.1f} MiB/file)",
        f"- channels: {totals['channels']} · upload_date range: {stats['date_range']['first']}"
        f" → {stats['date_range']['last']}",
        f"- audio: {len(parts)} part(s) <= {stats['selection']['max_part_size']} ({part_names})",
        f"- metadata: `{meta_path.name}` = yt-dlp info.json (upload_date/language/channel) +"
        " manifest.jsonl + stats.json + qc_flags.jsonl + README.md",
        "",
        "Audio is the ORIGINAL medium-bitrate opus Vietnamese track, stored without re-encoding"
        " or compression. `info.json` is the only proof of the 2026 window, hence it is archived"
        " here before any local cleanup.",
        "",
        "## Restore",
        "```shell",
        f"cat {batch_name}_audio.tar.part-* | tar -x        # -> <channel>/<upload_date>#...#<id>_<dur>.webm",
        "```",
        "",
        "## Verify",
        "```shell",
        f"cat {batch_name}_audio.tar.part-* > {batch_name}_audio.tar   # reassemble for the full-file check",
        "sha256sum -c SHA256SUMS",
        "```",
        "",
        "## Per channel",
        "",
        "| channel | files | hours | GiB |",
        "|---|---:|---:|---:|",
    ]
    for channel, row in stats["per_channel"].items():
        lines.append(f"| {channel} | {row['files']} | {row['hours']:.3f} | {row['gib']:.3f} |")
    lines += [
        "",
        "## Per upload month",
        "",
        "| month | files | hours | GiB |",
        "|---|---:|---:|---:|",
    ]
    for month, row in stats["per_month"].items():
        lines.append(f"| {month} | {row['files']} | {row['hours']:.3f} | {row['gib']:.3f} |")
    lines += [
        "",
        "## QC flags kept in this batch (soft flags are intentional — review, do not auto-drop)",
        "",
    ]
    if stats["qc_flags_counts"]:
        lines += [f"- `{flag}`: {count}" for flag, count in stats["qc_flags_counts"].items()]
    else:
        lines.append("- none (all files clean)")
    lines += [
        "",
        "## Selection / exclusions",
        "",
        "```json",
        json.dumps(stats["selection"], ensure_ascii=False, indent=2),
        "```",
        "",
        "`excluded` = exclude.txt + HARD QC flags (corrupt / zero_size / wrong_language /"
        " out_of_window); `already_in_batch` = video_id already packaged by a previous batch.",
        "`dropped_by_limit_gb` = left for the NEXT batch.",
        "",
        "## Next steps",
        "",
        "```shell",
        f"# 1) upload:   sync/upload_batch.sh {batch_name}",
        f"# 2) verify:   sync/verify_remote.sh {batch_name}",
        f"# 3) ledger:   python3 metadata/corpus_ledger.py append --batch'{batch_name}'"
        " --manifest ... (or mark-verified after the remote check)",
        f"# 4) cleanup:  sync/cleanup_local.sh {batch_name}   # ONLY after ledger.verified=true",
        "```",
        "",
        "NEVER delete `crawler/log/audios_*.txt` (dedup archive, non-reproducible).",
    ]
    path = batch_dir / "README.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------------- CLI / main
def next_batch_name(dataset_dir):
    used = {p.name for p in Path(dataset_dir).glob("batch_*") if p.is_dir()}
    for i in range(1, 100000):
        name = f"batch_{i:03d}"
        if name not in used:
            return name
    raise SystemExit("no free batch_<NNN> name available")


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-name", default=None,
                        help="batch folder name (default: next free batch_NNN)")
    parser.add_argument("--download-dir", type=Path, default=None,
                        help="crawl root (default: $DOWNLOAD_DIR from config.env)")
    parser.add_argument("--dataset-dir", type=Path, default=None,
                        help="derived-data root (default: $DATASET_DIR from config.env)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="override the batch parent dir (default: <DATASET_DIR>)")
    parser.add_argument("--qc-flags", type=Path, default=None,
                        help="QC rows (default <DATASET_DIR>/qc_flags.jsonl)")
    parser.add_argument("--exclude-file", type=Path, default=None,
                        help="hard-exclusion list (default <DATASET_DIR>/exclude.txt)")
    parser.add_argument("--limit-gb", type=float, default=None,
                        help="stop selecting once this size is reached (rest -> next batch)")
    parser.add_argument("--max-part-size", default="20G",
                        help="split size for the audio tar (default 20G)")
    parser.add_argument("--hardlink", action="store_true",
                        help="also build <DATASET_DIR>/audio/<channel>/ hardlink mirror (0 bytes)")
    parser.add_argument("--verify", action="store_true",
                        help="re-read every artefact and prove hashes/entries/sizes match")
    parser.add_argument("--dry-run", action="store_true",
                        help="select + report only, write nothing")
    parser.add_argument("--no-hash", action="store_true",
                        help="skip per-file sha256 (faster, weaker manifest)")
    parser.add_argument("--hash-workers", type=int, default=4)
    parser.add_argument("--allow-duplicate-ids", action="store_true",
                        help="do NOT skip videos already packaged in a previous batch")
    parser.add_argument("--min-upload-date", default=None,
                        help="YYYYMMDD window start (default $MIN_UPLOAD_DATE)")
    return parser.parse_args()


def main():
    args = parse_args()
    args.download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else paths.dataset_dir()
    args.qc_flags = Path(args.qc_flags) if args.qc_flags else dataset_dir / "qc_flags.jsonl"
    args.exclude_file = (Path(args.exclude_file) if args.exclude_file
                         else dataset_dir / "exclude.txt")
    args.min_upload_date = args.min_upload_date or paths.min_upload_date()

    batch_name = args.batch_name or next_batch_name(dataset_dir)
    out_dir = Path(args.out_dir) if args.out_dir else dataset_dir
    batch_dir = out_dir / batch_name

    print("=== make_batch (W4) — package a reproducible upload batch ===")
    print(f"download dir : {args.download_dir}")
    print(f"dataset dir  : {dataset_dir}")
    print(f"batch        : {batch_name} -> {batch_dir}")
    print(f"qc flags     : {args.qc_flags}\nexclude file : {args.exclude_file}")

    if not args.download_dir.is_dir():
        raise SystemExit(f"download dir does not exist: {args.download_dir}")
    if paths.in_repo(batch_dir) and not paths.allow_in_repo_download():
        raise SystemExit(f"refusing to write the batch inside the repo ({batch_dir}) — "
                         "data must live outside; override with ALLOW_IN_REPO_DOWNLOAD=1")

    excluded_ids = load_exclude_ids(args.exclude_file, args.qc_flags)
    qc_by_id, qc_by_name = load_qc_index(args.qc_flags)
    consumed = load_consumed_ids(dataset_dir, exclude_batch=batch_name)
    if consumed:
        print(f"dedup        : {len(consumed)} video_id(s) already packaged earlier")

    records, skipped = collect_candidates(args, qc_by_id, qc_by_name, excluded_ids, consumed)
    hours = sum(r.get("duration") or 0 for r in records) / 3600.0
    size = sum(r.get("size_bytes") or 0 for r in records)
    print(f"candidates   : {len(records)} files, {hours:.3f} h, {human_bytes(size)}")
    print(f"skipped      : {skipped}")
    if not records:
        raise SystemExit("nothing to package — run the crawler and audio_qc.py first")

    limit_bytes = int(args.limit_gb * 1024**3) if args.limit_gb else None
    records, dropped = apply_limit(records, limit_bytes)
    if dropped:
        print(f"limit-gb     : kept {len(records)} files, left {dropped} for the next batch")

    stats = build_stats(batch_name, records, args, skipped, dropped)

    if args.dry_run:
        for rec in records[:20]:
            print(f"  {rec.get('upload_date')}  {human_bytes(rec.get('size_bytes')):>10}  "
                  f"{rec['video_id']}  {rec['audio_path']}")
        if len(records) > 20:
            print(f"  ... and {len(records) - 20} more")
        print(f"\nDRY RUN — would write {batch_dir}")
        print(f"  totals: {stats['totals']['files']} files, {stats['totals']['hours']:.3f} h, "
              f"{human_bytes(stats['totals']['bytes'])}")
        print("  per channel: " + ", ".join(
            f"{name} {row['files']}f/{row['hours']:.2f}h"
            for name, row in stats["per_channel"].items()))
        print("  (nothing was written; re-run without --dry-run to package)")
        return

    # --- write the batch artefacts -------------------------------------------
    batch_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n--- hashing {len(records)} files (workers={args.hash_workers}) ---")
    failures = compute_hashes(records, args.download_dir, args.hash_workers,
                              enabled=not args.no_hash)
    if failures:
        raise SystemExit(f"{failures} file(s) could not be hashed — aborting before packaging")

    manifest_path = write_manifest(batch_dir, records)
    qc_path, qc_rows = write_qc_subset(batch_dir, records, qc_by_id)
    used_path = write_used_ids(batch_dir, records)
    stats_path = batch_dir / "stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(f"manifest     : {manifest_path.name} ({len(records)} rows)")
    print(f"qc subset    : {qc_path.name} ({qc_rows} rows of this batch)")
    print(f"used ids     : {used_path.name} (dedup guard for later batches)")

    print("\n--- packaging audio (streaming tar + split, no re-encode) ---")
    parts, stream_hash = build_audio_tar(batch_dir, batch_name, records,
                                         args.download_dir, args.max_part_size)
    parts_bytes = sum(p.stat().st_size for p in parts)
    edge_left = parts[0].name if parts else "-"
    edge_right = parts[-1].name if parts else "-"
    print(f"audio parts  : {len(parts)} file(s), {human_bytes(parts_bytes)} "
          f"[{edge_left} ... {edge_right}]")

    # README is written BEFORE the meta tar so it travels inside the archive.
    meta_path = batch_dir / f"{batch_name}_meta.tar.gz"
    readme_path = write_readme(batch_dir, batch_name, stats, parts, meta_path)
    meta_path, linked, copied = build_meta_tar(
        batch_dir, batch_name, records, args.download_dir,
        [manifest_path, stats_path, qc_path, used_path, readme_path])
    print(f"meta tar     : {meta_path.name} ({human_bytes(meta_path.stat().st_size)}, "
          f"{linked} info.json hardlinked + {copied} copied)")

    sums_path = write_sha256sums(batch_dir, batch_name, parts, meta_path, manifest_path,
                                 stream_hash)
    print(f"checksums    : {sums_path.name}")

    if args.hardlink:
        made, already = build_hardlink_tree(dataset_dir, records, args.download_dir)
        print(f"hardlink tree: {made} new link(s), {already} already present "
              f"(-> {dataset_dir / 'audio'}, 0 extra bytes)")

    ok = True
    if args.verify:
        ok, _errors = verify_batch(batch_dir, batch_name, records, parts, meta_path,
                                   manifest_path, stream_hash)

    print("\n=== batch summary ===")
    print(f"batch     : {batch_name}")
    print(f"folder    : {batch_dir}")
    print(f"totals    : {stats['totals']['files']} files, "
          f"{stats['totals']['hours']:.3f} hours, {human_bytes(stats['totals']['bytes'])} "
          f"(tar parts: {human_bytes(parts_bytes)})")
    print(f"channels  : {', '.join(stats['per_channel'])}")
    print(f"date range: {stats['date_range']['first']} → {stats['date_range']['last']}")
    print(f"verify    : {'PASS' if ok else 'FAILED'}")
    print("\nnext steps:")
    print(f"  sync/upload_batch.sh {batch_name}         # rclone -> gdrive:corpus/")
    print(f"  sync/verify_remote.sh {batch_name}        # rclone check + SHA256SUMS")
    print(f"  python3 metadata/corpus_ledger.py append --batch-dir {batch_dir}")
    print(f"  sync/cleanup_local.sh {batch_name}        # ONLY if ledger.verified=true")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
