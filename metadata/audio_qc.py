#!/usr/bin/env python3
"""Audio QC for the audio-only acquisition stage.

Cheap by default (ffprobe only, ~10 ms/file); optional silence scan is opt-in.
Includes the LANGUAGE GUARD: videos whose info.json `language` is present but is
not an accepted language (e.g. YouTube AI-dubbed `en-US` tracks) are flagged and
excluded, so the corpus cannot silently fill up with dubbed audio.

Outputs (defaults resolve from ../config.env — use $DATASET_DIR for derived data):
  <DATASET_DIR>/qc_flags.jsonl   one JSON row per audio file (measurements + flags)
  <DATASET_DIR>/exclude.txt      video_ids flagged corrupt / wrong_language / zero-size

Usage:
  python3 metadata/audio_qc.py [--download-dir PATH] [--silence-check]
  (paths default to config.env: DOWNLOAD_DIR / DATASET_DIR — CWD-independent)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# metadata/paths.py: single source of truth for DATA locations (mirrors ../config.env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

AUDIO_EXTS = [".webm", ".m4a", ".mp3", ".opus", ".ogg", ".wav"]


def parse_filename(path):
    """Parse yt-dlp output name: {upload_date}#{title20}#{channel_id}#{video_id}_{dur}.{ext}"""
    name = os.path.basename(path)
    base, ext = os.path.splitext(name)
    if ext.lower() not in AUDIO_EXTS:
        return None
    parts = base.split("#")
    if len(parts) < 2:
        return None
    upload_date = parts[0] if re.fullmatch(r"\d{8}", parts[0]) else None
    tail = parts[-1]
    if "_" not in tail:
        return None
    video_id, dur = tail.rsplit("_", 1)
    if not dur.isdigit():
        return None
    return {
        "upload_date": upload_date,
        "video_id": video_id,
        "channel_id": parts[-2] if len(parts) >= 3 else None,
        "name_duration": int(dur),
        "ext": ext.lstrip(".").lower(),
    }


def ffprobe_audio(path):
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate:format=duration,size",
        "-of", "json", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return None, f"ffprobe exception: {exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or "ffprobe failed").strip()[:200]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None, "ffprobe returned invalid json"
    streams = data.get("streams") or []
    if not streams:
        return None, "no audio stream"
    stream = streams[0]
    fmt = data.get("format") or {}

    def _num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "codec": stream.get("codec_name"),
        "sample_rate": _num(stream.get("sample_rate")),
        "channels": _num(stream.get("channels")),
        "stream_bitrate": _num(stream.get("bit_rate")),
        "duration": _num(fmt.get("duration")),
        "size_bytes": _num(fmt.get("size")),
    }, None


def silence_seconds(path, noise_db=-35, min_silence=1.0, timeout=3600):
    """Total silencedetect duration (decodes the whole file -> opt-in only)."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None
    total = 0.0
    for match in re.finditer(r"silence_duration:\s*([0-9.]+)", proc.stderr or ""):
        total += float(match.group(1))
    return total


def analyze_file(task):
    path_str, cfg = task
    path = Path(path_str)
    flags = []
    row = {"audio_path": str(path), "video_id": None}

    parsed = parse_filename(path)
    if parsed is None:
        flags.append("bad_filename")
        parsed = {}
    row.update({k: parsed.get(k) for k in ("video_id", "upload_date", "channel_id", "ext")})

    # ---- video metadata (yt-dlp info.json) ---------------------------------
    # yt-dlp names it by replacing the audio extension: '{base}.info.json'
    info_path = path.with_name(path.stem + ".info.json")
    info = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            flags.append("bad_info_json")
    else:
        flags.append("no_info_json")

    row["title"] = info.get("title")
    row["channel"] = info.get("channel") or info.get("uploader")
    row["info_language"] = info.get("language")
    row["info_format_id"] = info.get("format_id")
    row["info_abr"] = info.get("abr")
    row["info_duration"] = info.get("duration")
    row["webpage_url"] = info.get("webpage_url")
    if parsed.get("video_id") is None and info.get("id"):
        row["video_id"] = info["id"]

    # ---- language guard ----------------------------------------------------
    accept = cfg["accept_langs"]
    if row["info_language"] is None:
        flags.append("language_unverified")   # legacy videos without the field
    elif row["info_language"] not in accept:
        flags.append("wrong_language")        # e.g. YouTube AI-dubbed en-US track

    # ---- 2026 window (defensive layer) ------------------------------------
    if row["upload_date"] is None:
        flags.append("date_missing")
    elif row["upload_date"] < cfg["min_upload_date"]:
        flags.append("out_of_window")

    # ---- audio measurements ----------------------------------------------
    measured, err = ffprobe_audio(path)
    if measured is None:
        flags.append("corrupt")
        row["error"] = err
    else:
        row.update(measured)
        duration = measured.get("duration")
        size = measured.get("size_bytes") or 0
        if size <= 0:
            flags.append("zero_size")
        if duration is None or duration <= 0:
            flags.append("no_duration")
        else:
            if duration < cfg["min_duration"]:
                flags.append("too_short")
            if duration > cfg["max_duration"]:
                flags.append("too_long")
            if cfg["duration_mismatch_tol"] is not None and row.get("info_duration"):
                if abs(duration - float(row["info_duration"])) > cfg["duration_mismatch_tol"]:
                    flags.append("duration_mismatch")
        stream_br = measured.get("stream_bitrate")
        total_br = stream_br or (size * 8 / duration if duration else None)
        row["effective_bitrate"] = total_br
        if total_br is not None and total_br < cfg["min_bitrate"]:
            flags.append("low_bitrate")
        if cfg["silence_check"] and duration:
            silence = silence_seconds(path, cfg["silence_db"])
            if silence is not None:
                ratio = silence / duration
                row["silence_ratio"] = round(ratio, 4)
                if ratio > cfg["silence_ratio"]:
                    flags.append("silent_heavy")

    row["flags"] = flags
    return row


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", type=Path, default=None,
                        help="crawl root (default: $DOWNLOAD_DIR from config.env)")
    parser.add_argument("--output", type=Path, default=None,
                        help="QC jsonl path (default: $DATASET_DIR/qc_flags.jsonl)")
    parser.add_argument("--exclude-file", type=Path, default=None,
                        help="exclude list path (default: $DATASET_DIR/exclude.txt)")
    parser.add_argument("--min-duration", type=float, default=20.0)
    parser.add_argument("--max-duration", type=float, default=10800.0)
    parser.add_argument("--min-bitrate", type=float, default=32000.0)
    parser.add_argument("--duration-mismatch-tol", type=float, default=5.0)
    parser.add_argument("--accept-langs", type=str, default="vi",
                        help="Comma-separated accepted info.json language values")
    parser.add_argument("--min-upload-date", type=str, default=None,
                        help="YYYYMMDD window start (default: $MIN_UPLOAD_DATE)")
    parser.add_argument("--silence-check", action="store_true",
                        help="Also decode each file for the silence ratio (slow)")
    parser.add_argument("--silence-db", type=float, default=-35.0)
    parser.add_argument("--silence-ratio", type=float, default=0.6)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    # Resolve CWD-independent defaults (config.env / env vars), then report them.
    args.download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    args.output = Path(args.output) if args.output else paths.dataset_dir() / "qc_flags.jsonl"
    args.exclude_file = Path(args.exclude_file) if args.exclude_file else paths.dataset_dir() / "exclude.txt"
    args.min_upload_date = args.min_upload_date or paths.min_upload_date()
    if paths.in_repo(args.download_dir) or paths.in_repo(args.output):
        print("WARNING: working on paths inside the repo — crawl data should live outside "
              f"(see {paths.CONFIG_ENV})", file=sys.stderr)
    print(f"download-dir: {args.download_dir}")
    print(f"qc output   : {args.output}\nexclude file: {args.exclude_file}")
    accept_langs = {x.strip() for x in args.accept_langs.split(",") if x.strip()}
    cfg = {
        "accept_langs": accept_langs,
        "min_upload_date": args.min_upload_date,
        "min_duration": args.min_duration,
        "max_duration": args.max_duration,
        "min_bitrate": args.min_bitrate,
        "duration_mismatch_tol": args.duration_mismatch_tol,
        "silence_check": args.silence_check,
        "silence_db": args.silence_db,
        "silence_ratio": args.silence_ratio,
    }

    files = sorted(
        str(p) for p in args.download_dir.rglob("*") if p.suffix.lower() in AUDIO_EXTS
    )
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"No audio files found under {args.download_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"QC on {len(files)} audio files (workers={args.workers}, "
          f"silence_check={args.silence_check})")

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, row in enumerate(pool.map(analyze_file, [(f, cfg) for f in files]), 1):
            rows.append(row)
            if i % 200 == 0:
                print(f"  ... {i}/{len(files)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # hard flags = must not enter the corpus
    hard_flags = {"corrupt", "zero_size", "wrong_language", "out_of_window"}
    excludes = [
        r["video_id"] for r in rows
        if r.get("video_id") and hard_flags.intersection(r["flags"])
    ]
    if excludes:
        args.exclude_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.exclude_file, "w", encoding="utf-8") as fh:
            for vid in sorted(set(excludes)):
                fh.write(f"{vid}\n")

    total_hours = sum((r.get("duration") or 0) for r in rows) / 3600.0
    total_bytes = sum((r.get("size_bytes") or 0) for r in rows)
    flag_counts = {}
    for row in rows:
        for flag in row["flags"]:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

    print(f"\n=== audio QC summary ({len(rows)} files) ===")
    print(f"total: {total_hours:.2f} hours, {total_bytes / 1073741824:.2f} GB")
    print("flag counts:")
    for flag, count in sorted(flag_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {flag}: {count}")
    print(f"clean files: {sum(1 for r in rows if not r['flags'])}")
    print(f"excluded (hard flags): {len(set(excludes))} -> {args.exclude_file}")
    print(f"details: {args.output}")


if __name__ == "__main__":
    main()