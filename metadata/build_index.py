#!/usr/bin/env python3
"""Build a metadata index of all crawled videos and audit the 2026 constraint.

Scans the crawler's download directory for yt-dlp *.info.json files and writes
index.jsonl with one row per video:
  {video_id, title, channel, channel_id, upload_date, duration,
   audio_downloaded, in_window, webpage_url}

Also prints a summary (total / in-2026 / hours / per-channel) and, with
--strict, exits non-zero when out-of-window videos are found (CI-friendly).

Paths default to ../config.env (DOWNLOAD_DIR / DATASET_DIR) so the script is
CWD-independent and never writes derived data into the repo.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# metadata/paths.py: single source of truth for DATA locations (mirrors ../config.env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

AUDIO_EXTS = [
    ".m4a", ".mp3", ".opus", ".ogg", ".wav", ".webm", ".mp4", ".mkv", ".flv", ".mov",
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", type=Path, default=None,
                        help="crawl root (default: $DOWNLOAD_DIR from config.env)")
    parser.add_argument("--output", type=Path, default=None,
                        help="index.jsonl path (default <DATASET_DIR>/index.jsonl)")
    parser.add_argument("--min-upload-date", type=str, default=None,
                        help="YYYYMMDD window start (default: $MIN_UPLOAD_DATE)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when out-of-window videos exist")
    return parser.parse_args()


def main():
    args = parse_args()
    # Resolve CWD-independent defaults from config.env / env vars.
    args.download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    args.min_upload_date = args.min_upload_date or paths.min_upload_date()
    output = Path(args.output) if args.output else paths.dataset_dir() / "index.jsonl"
    if paths.in_repo(args.download_dir) or paths.in_repo(output):
        print("WARNING: paths inside the repo — crawl/derived data should live outside "
              f"(see {paths.CONFIG_ENV})", file=sys.stderr)
    print(f"download-dir: {args.download_dir}\nindex output: {output}")

    rows = []
    for info_path in sorted(args.download_dir.rglob("*.info.json")):
        try:
            meta = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"skipping unreadable {info_path}: {e}")
            continue
        if meta.get("_type") == "playlist" or "entries" in meta:
            continue
        base = info_path.name[: -len(".info.json")]
        audio_downloaded = any(
            (info_path.parent / f"{base}{ext}").exists() for ext in AUDIO_EXTS
        )
        upload_date = meta.get("upload_date")
        rows.append(
            {
                "video_id": meta.get("id") or base,
                "title": meta.get("title"),
                "channel": meta.get("channel") or meta.get("uploader"),
                "channel_id": meta.get("channel_id"),
                "upload_date": upload_date,
                "duration": meta.get("duration"),
                "audio_downloaded": audio_downloaded,
                "in_window": bool(upload_date and upload_date >= args.min_upload_date),
                "webpage_url": meta.get("webpage_url"),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    in_window = [r for r in rows if r["in_window"]]
    out_window = [r for r in rows if not r["in_window"]]
    unknown_date = [r for r in rows if not r["upload_date"]]

    def hours(rs):
        return sum(r["duration"] or 0 for r in rs) / 3600.0

    print(f"\n=== index summary ({len(rows)} videos) ===")
    print(f"in window (>= {args.min_upload_date}): {len(in_window)} videos, "
          f"{hours(in_window):.1f} hours")
    print(f"out of window: {len(out_window)} videos, {hours(out_window):.1f} hours")
    print(f"upload_date unknown: {len(unknown_date)} videos")
    print(f"audio downloaded: {sum(1 for r in rows if r['audio_downloaded'])}")

    per_channel = defaultdict(lambda: [0, 0.0])
    for r in in_window:
        per_channel[r["channel"] or "?"][0] += 1
        per_channel[r["channel"] or "?"][1] += (r["duration"] or 0) / 3600.0
    print("\nper-channel (in window):")
    for ch, (n, h) in sorted(per_channel.items(), key=lambda kv: -kv[1][0]):
        print(f"  {ch}: {n} videos, {h:.1f} hours")

    if out_window:
        print("\nVIOLATIONS (out of window):")
        for r in out_window[:20]:
            print(f"  {r['upload_date']} {r['video_id']} {r['title']}")
        if len(out_window) > 20:
            print(f"  ... and {len(out_window) - 20} more")
    print(f"\nindex written: {output}")

    if args.strict and out_window:
        sys.exit(1)


if __name__ == "__main__":
    main()