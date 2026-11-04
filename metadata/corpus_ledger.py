#!/usr/bin/env python3
"""W5 — corpus ledger: the single "memory" of the 50k-hour corpus.

Everything else is disposable (local audio is deleted after upload, YouTube can
disappear), so this file must be able to answer, forever:
  * what has been packaged and uploaded, per batch, with sizes/hours/date range?
  * how far are we from the TARGET_HOURS goal?
  * has any video_id slipped into two batches (double counting)?
  * which batches are verified on Drive (the only ones whose local files may be deleted)?

Subcommands:
  append          add/refresh the row of a packaged batch (reads <batch_dir>/stats.json)
  mark-verified   after upload + remote verify: verified=true + drive_path (unlocks cleanup)
  report          progress to TARGET_HOURS + per-channel totals + duplicate video_id audit
  list            compact table of batches
  push            copy the ledger to Drive (rclone) so it survives local cleanup

Ledger file: $LEDGER_FILE (default <DATA_ROOT>/corpus_ledger.jsonl), one JSON row per batch.
Row schema (stable — later tooling depends on it):
  {schema, batch, batch_dir, date, appended_utc, files, hours, bytes, channels,
   per_channel, date_range, manifest_sha256, audio_parts, drive_path, verified, verified_utc}

  Optional — unit chỉ lên HF, KHÔNG lên Drive (user quyết định):
  {hf_repo, hf_verified, hf_verified_utc, hf_files, storage: "hf-only", note}
  LƯU Ý: `verified` GIỮ false vì nó theo dõi DUY NHẤT Drive; report/list bỏ qua field optional
  (chúng không bị mất khi chạy `append --update`).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# metadata/paths.py: single source of truth for DATA locations (mirrors ../config.env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

SCHEMA = "corpus_ledger/1"


def sha256_file(path, chunk=1 << 22):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_bytes(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TB"


# ------------------------------------------------------------------------ ledger I/O
def load_ledger(ledger_file):
    rows = []
    path = Path(ledger_file)
    if not path.exists():
        return rows
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"WARNING: unreadable ledger line {lineno} — skipped", file=sys.stderr)
    return rows


def write_ledger(ledger_file, rows):
    """Atomic rewrite: a ledger is never left half-written (it is the corpus memory)."""
    path = Path(ledger_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    return path


def batch_summary(batch_dir):
    """Build the ledger row payload from a packaged batch folder."""
    batch_dir = Path(batch_dir)
    stats_path = batch_dir / "stats.json"
    manifest_path = batch_dir / "manifest.jsonl"
    if not stats_path.exists() or not manifest_path.exists():
        raise SystemExit(f"{batch_dir} is not a packaged batch (missing stats.json/manifest.jsonl)")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    totals = stats["totals"]
    channels = list(stats.get("per_channel", {}))
    parts = sorted(p.name for p in batch_dir.glob("*_audio.tar.part-*"))
    return {
        "schema": SCHEMA,
        "batch": stats.get("batch") or batch_dir.name,
        "batch_dir": str(batch_dir),
        "date": (stats.get("created_utc") or utcnow())[:10],
        "appended_utc": utcnow(),
        "files": totals["files"],
        "hours": totals["hours"],
        "bytes": totals["bytes"],
        "channels": channels,
        "per_channel": stats.get("per_channel", {}),
        "date_range": stats.get("date_range", {}),
        "manifest_sha256": sha256_file(manifest_path),
        "audio_parts": parts,
        "drive_path": None,
        "verified": False,
        "verified_utc": None,
    }


def default_batch_dirs(dataset_dir):
    return sorted(p for p in Path(dataset_dir).glob("batch_*") if p.is_dir())


# ------------------------------------------------------------------------- commands
def find_row(rows, batch):
    for row in rows:
        if row.get("batch") == batch:
            return row
    return None


def cmd_append(args, ledger_file):
    """Add (or refresh) the ledger row of a packaged batch."""
    rows = load_ledger(ledger_file)
    if args.batch_dir:
        targets = [Path(args.batch_dir)]
    elif args.batch:
        targets = [args.dataset_dir / args.batch]
    else:
        known = {row.get("batch") for row in rows}
        targets = [p for p in default_batch_dirs(args.dataset_dir) if p.name not in known]
        if not targets:
            print("ledger already up to date (no new batch folder found)")
            return
    added = updated = 0
    for batch_dir in targets:
        payload = batch_summary(batch_dir)
        existing = find_row(rows, payload["batch"])
        if existing is None:
            rows.append(payload)
            added += 1
            print(f"  {payload['batch']}: appended ({payload['files']} files, "
                  f"{payload['hours']:.3f} h, {human_bytes(payload['bytes'])})")
        elif args.update:
            # never lose upload/verify facts when refreshing a row
            for key in ("drive_path", "verified", "verified_utc", "remote_files"):
                payload[key] = existing.get(key)
            existing.update(payload)
            updated += 1
            print(f"  {payload['batch']}: updated ({payload['files']} files, "
                  f"{payload['hours']:.3f} h)")
        else:
            print(f"  {payload['batch']}: already in ledger (use --update to refresh)")
    if added or updated:
        path = write_ledger(ledger_file, rows)
        print(f"ledger written: {path} ({len(rows)} batch row(s), +{added} new, {updated} updated)")


def cmd_mark_verified(args, ledger_file):
    """Record that a batch is on Drive and checksum-verified (unlocks local cleanup)."""
    rows = load_ledger(ledger_file)
    row = find_row(rows, args.batch)
    if row is None:
        raise SystemExit(f"batch {args.batch} is not in the ledger — run `append` first")
    if args.drive_path:
        row["drive_path"] = args.drive_path
    row["verified"] = True
    row["verified_utc"] = utcnow()
    if args.remote_files is not None:
        row["remote_files"] = args.remote_files
    write_ledger(ledger_file, rows)
    print(f"{args.batch}: verified=true drive_path={row.get('drive_path')}")
    print(f"local cleanup is now allowed: sync/cleanup_local.sh {args.batch}")


def find_duplicate_ids(dataset_dir):
    """video_ids listed by more than one batch (double counting / re-packaging bug)."""
    seen = {}
    for used in sorted(Path(dataset_dir).glob("batch_*/used_ids.txt")):
        try:
            text = used.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            vid = line.strip()
            if vid:
                seen.setdefault(vid, []).append(used.parent.name)
    return {vid: batches for vid, batches in seen.items() if len(batches) > 1}


def cmd_report(args, ledger_file):
    rows = load_ledger(ledger_file)
    target = args.target_hours if args.target_hours else paths.target_hours()
    files = sum(row.get("files") or 0 for row in rows)
    hours = sum(row.get("hours") or 0 for row in rows)
    size = sum(row.get("bytes") or 0 for row in rows)
    verified = [row for row in rows if row.get("verified")]
    v_hours = sum(row.get("hours") or 0 for row in verified)

    print("=== corpus ledger report ===")
    print(f"ledger file      : {ledger_file} (last write: "
          f"{datetime.fromtimestamp(Path(ledger_file).stat().st_mtime, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if Path(ledger_file).exists() else 'n/a'})")
    print(f"batches          : {len(rows)} (verified on Drive: {len(verified)})")
    print(f"files / hours    : {files} / {hours:.3f} h")
    print(f"packaged size    : {human_bytes(size)}"
          + (f"  (~{size / 1024**3 / hours * 1000:.1f} GiB per 1000 h)" if hours else ""))
    if target:
        pct = 100.0 * hours / target if target else 0.0
        print(f"target           : {target:,.0f} h -> {pct:.4f}% done, "
              f"{max(target - hours, 0):,.2f} h to go")
        if hours:
            print(f"projection       : {size / 1024**3 / hours * target:,.0f} GiB at target "
                  f"(batches of 300-400 GB -> ~{size / 1024**3 / hours * target / 350:.0f} uploads)")
    if v_hours:
        print(f"verified hours   : {v_hours:.3f} h ({100.0 * v_hours / hours:.1f}% of packaged)")

    unverified = sorted(row.get("batch") for row in rows if not row.get("verified"))
    if unverified:
        print(f"NOT verified     : {', '.join(unverified)}  <- local cleanup is BLOCKED for these")

    known = {row.get("batch") for row in rows}
    on_disk = {p.name for p in default_batch_dirs(args.dataset_dir)}
    missing = sorted(on_disk - known)
    if missing:
        print(f"on disk, not in ledger: {', '.join(missing)}  -> run `append`")

    dupes = find_duplicate_ids(args.dataset_dir)
    if dupes:
        print(f"DUPLICATE video_id: {len(dupes)} id(s) appear in >1 batch (DO NOT double count)")
        for vid, batches in list(dupes.items())[:10]:
            print(f"    {vid}: {', '.join(batches)}")
    else:
        print("duplicate audit  : clean (no video_id in two batches)")

    per_channel = {}
    for row in rows:
        for channel, agg in (row.get("per_channel") or {}).items():
            entry = per_channel.setdefault(channel, {"files": 0, "hours": 0.0, "bytes": 0})
            entry["files"] += agg.get("files", 0)
            entry["hours"] += agg.get("hours", 0.0)
            entry["bytes"] += agg.get("bytes", 0)
    if per_channel:
        print("\nper channel (top 15 by hours):")
        for channel, agg in sorted(per_channel.items(), key=lambda kv: -kv[1]["hours"])[:15]:
            print(f"  {channel[:40]:40s} {agg['files']:6d} files  {agg['hours']:8.3f} h  "
                  f"{human_bytes(agg['bytes'])}")
        print(f"  ({len(per_channel)} channels total)")

    ranges = [row["date_range"] for row in rows if row.get("date_range", {}).get("first")]
    if ranges:
        print(f"\nupload_date span : {min(r['first'] for r in ranges)} → "
              f"{max(r['last'] for r in ranges)}")


def cmd_list(args, ledger_file):
    rows = load_ledger(ledger_file)
    if not rows:
        print("ledger is empty")
        return
    print(f"{'batch':12s} {'date':10s} {'files':>6s} {'hours':>9s} {'size':>10s} "
          f"{'ver':>3s}  channels")
    for row in rows:
        print(f"{row.get('batch', '?'):12s} {str(row.get('date', '?'))[:10]:10s} "
              f"{row.get('files', 0):6d} {row.get('hours', 0):9.3f} "
              f"{human_bytes(row.get('bytes', 0)):>10s} "
              f"{'y' if row.get('verified') else 'n':>3s}  "
              f"{', '.join((row.get('channels') or [])[:3])}")


def cmd_push(args, ledger_file):
    """Copy the ledger to Drive — it is the only thing that must survive cleanup."""
    if not shutil.which("rclone"):
        raise SystemExit("rclone is not installed — run sync/install_rclone.sh first")
    remote = args.remote or os.environ.get("LEDGER_REMOTE", "gdrive:corpus/_meta")
    cmd = ["rclone", "copy", str(ledger_file), remote, "--checksum", "-v"]
    print(" ".join(cmd))
    if args.dry_run:
        return
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"rclone failed (rc={rc})")
    print(f"ledger pushed to {remote}/")


def cmd_pending(args, ledger_file):
    """Batches that are packaged but NOT verified on Drive (one name per line, cron-friendly)."""
    rows = load_ledger(ledger_file)
    pending = [row.get("batch") for row in rows if not row.get("verified")]
    if args.with_errors and pending:
        sys.exit(1)
    for name in pending:
        print(name)


# ------------------------------------------------------------------------------ CLI
def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger-file", type=Path, default=None,
                        help="ledger path (default: $LEDGER_FILE from config.env)")
    parser.add_argument("--dataset-dir", type=Path, default=None,
                        help="batches root (default: $DATASET_DIR from config.env)")
    parser.add_argument("--target-hours", type=float, default=None,
                        help="goal used by `report` (default: $TARGET_HOURS)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append", help="append/refresh batch rows in the ledger")
    p_append.add_argument("--batch-dir", type=Path, default=None,
                          help="packaged batch folder (default: every new batch_* on disk)")
    p_append.add_argument("--batch", default=None, help="batch name under DATASET_DIR")
    p_append.add_argument("--update", action="store_true",
                          help="refresh an existing row (keeps verified/drive_path)")
    p_append.set_defaults(func=cmd_append)

    p_ver = sub.add_parser("mark-verified",
                           help="batch is uploaded AND checksum-verified on Drive")
    p_ver.add_argument("--batch", required=True)
    p_ver.add_argument("--drive-path", default=None,
                       help="e.g. gdrive:corpus/batch_001")
    p_ver.add_argument("--remote-files", type=int, default=None,
                       help="file count seen on the remote (sanity record)")
    p_ver.set_defaults(func=cmd_mark_verified)

    p_rep = sub.add_parser("report", help="progress toward the goal + duplicate audit")
    p_rep.set_defaults(func=cmd_report)

    p_ls = sub.add_parser("list", help="compact table of batches")
    p_ls.set_defaults(func=cmd_list)

    p_pend = sub.add_parser("pending",
                            help="print batches packaged but not verified (cron driver)")
    p_pend.add_argument("--with-errors", action="store_true",
                        help="exit 1 when anything is pending")
    p_pend.set_defaults(func=cmd_pending)

    p_push = sub.add_parser("push", help="copy the ledger to Drive via rclone")
    p_push.add_argument("--remote", default=None,
                        help="default $LEDGER_REMOTE or gdrive:corpus/_meta")
    p_push.add_argument("--dry-run", action="store_true")
    p_push.set_defaults(func=cmd_push)
    return parser.parse_args()


def main():
    args = parse_args()
    args.ledger_file = (Path(args.ledger_file) if args.ledger_file else paths.ledger_file())
    args.dataset_dir = (Path(args.dataset_dir) if args.dataset_dir
                        else paths.dataset_dir())
    args.func(args, args.ledger_file)


if __name__ == "__main__":
    main()
