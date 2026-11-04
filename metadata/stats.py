#!/usr/bin/env python3
"""W3b — corpus-stats for the crawl STAGING dir: "đã tải bao nhiêu video / giờ / GB?".

Fast (≈1 s), READ-ONLY and safe to run *while a crawl is running*. It deliberately
avoids parsing the ~2 GB of *.info.json that metadata/build_index.py reads (that one
stays the "official" index: it validates the 2026 window and audits per channel name).

Where each number comes from — do NOT confuse these sources (see HANDOVER.md §2c/mục 20):
  * audio files    -> *.webm/.m4a/... under $DOWNLOAD_DIR (AUDIO_EXTS below)
  * hours          -> the duration embedded in the filename
                      <upload_date>#<title>#<channel_id>#<video_id>_<duration>.<ext>
                      (exactly what crawler/crawl_all.sh sums for `new_hours`)
  * size           -> st_size of the audio files (+ *.info.json separately).
                      NOT `du`: du counts disk blocks and would double count the
                      hardlinks made by `make_batch --hardlink` (run du ONCE on $DATA_ROOT).
  * videos/shorts/streams -> line counts of crawler/log/audios_<channel>_{videos,shorts,streams}.txt
  * channel name   -> ONE *.info.json per channel dir (channel/uploader), fallback: dir name
  * "last 24h"     -> file mtime (download time) => stateless, this script never writes

Known caveats this tool reports:
  * *.info.json can OUTNUMBER audio files (audio removed / QC-excluded) -> we count audio
  * *.part (download in flight) is ignored
  * index.jsonl / corpus_ledger.jsonl are SNAPSHOTS — re-run build_index.py / `append`
  * sizes are decimal SI (GB = 10^9 B) to match "MB/giờ" and Drive capacity;
    `du -sh` prints GiB (≈7% smaller) — both can be right, just different units

Usage:
    python3 metadata/stats.py                 # totals + per-channel top 10 + last 24h
    python3 metadata/stats.py --top 0         # every channel
    python3 metadata/stats.py --json          # machine-readable (schema stats/1)
    python3 metadata/stats.py --since 7d --disk
Exit codes: 0 ok · 1 nothing to measure (missing dir / no audio) · 2 path inside repo
"""
import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# metadata/paths.py: single source of truth for DATA locations (mirrors ../config.env)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

SCHEMA = "stats/1"

# Keep in sync with metadata/build_index.py (AUDIO_EXTS) — every container yt-dlp may
# produce for the audio-only stage; crawler/crawl_all.sh uses a narrower subset for
# `find -newer` counters, so numbers may differ by a few legacy files.
AUDIO_EXTS = (".webm", ".m4a", ".mp3", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".flv", ".mov")

_SINCE_RE = re.compile(r"^(\d+)([mhdw])$")
_SINCE_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def si_bytes(num):
    """Decimal SI size (GB = 10^9 B): matches MB/giờ and Drive/vendor capacities."""
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1000 or unit == "TB":
            return f"{num:.2f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1000
    return f"{num:.2f} TB"


def parse_duration(stem):
    """Duration (seconds) = last '_'-separated component of a yt-dlp filename."""
    tail = stem.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else None


def parse_since(text):
    """'24h' | '7d' | '30m' | '2w' | ISO-8601 | 'off' -> epoch seconds or None."""
    text = (text or "").strip()
    if text.lower() in {"off", "none", "no", "0", "-"}:
        return None
    match = _SINCE_RE.match(text.lower())
    if match:
        return datetime.now(timezone.utc).timestamp() - int(match.group(1)) * _SINCE_UNITS[match.group(2)]
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"--since: cannot parse '{text}' "
                         "(use 24h / 7d / 30m / 2w / ISO-8601 / 'off')")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def channel_name(channel_dir):
    """Display name from ONE info.json in the channel dir (dirs are named by channel id)."""
    for info_path in sorted(channel_dir.glob("*.info.json")):
        try:
            meta = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("_type") == "playlist" or "entries" in meta:
            continue
        name = meta.get("channel") or meta.get("uploader")
        if name:
            return name
    return channel_dir.name


def tab_counts(repo_root):
    """channel -> {"videos": N, "shorts": N, "streams": N} from the dedup archives.

    The archive files are the only non-reproducible per-tab record, so they are the
    authoritative split; they are counted here, never modified.
    """
    out = defaultdict(lambda: {"videos": 0, "shorts": 0, "streams": 0})
    log_dir = Path(repo_root) / "crawler" / "log"
    if not log_dir.is_dir():
        return out
    for path in sorted(log_dir.glob("audios_*.txt")):
        stem = path.name[: -len(".txt")]
        if not stem.startswith("audios_"):        # e.g. legacy/manual files -> skip
            continue
        stem = stem[len("audios_"):]
        # channel ids may themselves contain '_' (e.g. UC_YlqtZlCE7wUXaxCt2M3-g),
        # so strip the tab suffix instead of splitting on the first '_'.
        if stem.endswith("_videos"):
            channel, tab = stem[: -len("_videos")], "videos"
        elif stem.endswith("_shorts"):
            channel, tab = stem[: -len("_shorts")], "shorts"
        elif stem.endswith("_streams"):
            channel, tab = stem[: -len("_streams")], "streams"
        else:
            continue
        try:
            with open(path, "rb") as fh:
                out[channel][tab] = sum(1 for _ in fh)
        except OSError:
            continue
    return out


def scan(download_dir, since_cutoff):
    """Walk the staging tree once. Returns (per_channel dict, total dict)."""
    keys = ("files", "hours", "bytes", "unparsed", "meta_files", "meta_bytes",
            "since_files", "since_hours", "since_bytes")
    per_channel = {}
    total = dict.fromkeys(keys, 0)
    for channel_dir in sorted(p for p in download_dir.iterdir() if p.is_dir()):
        row = dict.fromkeys(keys, 0)
        for path in channel_dir.rglob("*"):
            name = path.name
            if name.endswith(".info.json"):
                try:
                    row["meta_bytes"] += path.stat().st_size
                except OSError:
                    continue
                row["meta_files"] += 1
                continue
            if name.endswith((".part", ".ytdl", ".temp")):      # download in flight
                continue
            if path.suffix.lower() not in AUDIO_EXTS or not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            seconds = parse_duration(path.stem)
            row["files"] += 1
            row["bytes"] += stat.st_size
            if seconds is None:
                row["unparsed"] += 1                       # kept honest, not silently 0
            else:
                row["hours"] += seconds / 3600.0
            if since_cutoff is not None and stat.st_mtime >= since_cutoff:
                row["since_files"] += 1
                row["since_bytes"] += stat.st_size
                if seconds:
                    row["since_hours"] += seconds / 3600.0
        if row["files"] or row["meta_files"]:
            per_channel[channel_dir.name] = row
            for key in keys:
                total[key] += row[key]
    return per_channel, total


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download-dir", type=Path, default=None,
                        help="crawl root (default: $DOWNLOAD_DIR from config.env)")
    parser.add_argument("--top", type=int, default=1000,
                        help="how many channels to print (0 = all, default 10)")
    parser.add_argument("--json", action="store_true",
                        help="print machine-readable JSON (schema stats/1) and exit")
    parser.add_argument("--since", default="24h", metavar="WINDOW",
                        help="delta window: 24h / 7d / 30m / 2w / ISO-8601 / 'off' (default 24h)")
    parser.add_argument("--no-names", action="store_true",
                        help="do not read info.json for channel names (print channel ids)")
    parser.add_argument("--disk", action="store_true",
                        help="also report free space and how many hours it still fits")
    return parser.parse_args()


def main():
    args = parse_args()
    download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    if not download_dir.is_dir():
        print(f"ERROR: no such crawl root: {download_dir}", file=sys.stderr)
        print("       set DOWNLOAD_DIR (config.env/env) or pass --download-dir", file=sys.stderr)
        return 1
    if paths.in_repo(download_dir) and not paths.allow_in_repo_download():
        print(f"ERROR: refusing to measure a repo-internal path: {download_dir}", file=sys.stderr)
        return 2

    cutoff = parse_since(args.since)
    per_channel, total = scan(download_dir, cutoff)
    if total["files"] == 0:
        print(f"ERROR: no audio files under {download_dir} (nothing crawled yet?)", file=sys.stderr)
        return 1

    tabs = tab_counts(paths.REPO_ROOT)
    rows = []
    tab_total = {"videos": 0, "shorts": 0, "streams": 0}
    for channel, row in per_channel.items():
        tab = tabs.get(channel) or {"videos": 0, "shorts": 0, "streams": 0}
        row = dict(row)
        row["channel"] = channel
        row["name"] = channel if args.no_names else channel_name(download_dir / channel)
        row["videos"] = tab["videos"]
        row["shorts"] = tab["shorts"]
        row["streams"] = tab["streams"]
        rows.append(row)
        tab_total["videos"] += tab["videos"]
        tab_total["shorts"] += tab["shorts"]
        tab_total["streams"] += tab["streams"]
    rows.sort(key=lambda r: (-r["hours"], -r["files"], r["channel"]))

    hours = total["hours"]
    target = paths.target_hours() or 0.0
    mb_per_hour = (total["bytes"] / 1e6 / hours) if hours else 0.0
    unknown_tab = total["files"] - tab_total["videos"] - tab_total["shorts"] - tab_total["streams"]

    disk = None
    if args.disk:
        usage = shutil.disk_usage(download_dir)
        disk = {
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "hours_fit": (usage.free / (total["bytes"] / hours)) if hours and total["bytes"] else None,
        }

    payload = {
        "schema": SCHEMA,
        "generated_utc": utcnow(),
        "download_dir": str(download_dir),
        "audio": {"files": total["files"], "hours": round(hours, 3), "bytes": total["bytes"],
                  "unparsed_duration": total["unparsed"]},
        "metadata": {"files": total["meta_files"], "bytes": total["meta_bytes"]},
        "by_tab": {"videos": tab_total["videos"], "shorts": tab_total["shorts"],
                   "streams": tab_total["streams"], "unknown": unknown_tab},
        "per_channel": [
            {"dir": r["channel"], "name": r["name"], "files": r["files"],
             "hours": round(r["hours"], 3), "bytes": r["bytes"],
             "videos": r["videos"], "shorts": r["shorts"], "streams": r["streams"]}
            for r in rows
        ],
        "since": {"window": args.since, "cutoff_utc": iso(cutoff) if cutoff else None,
                  "files": total["since_files"], "hours": round(total["since_hours"], 3),
                  "bytes": total["since_bytes"]},
        "goal": {"target_hours": target, "pct": (100.0 * hours / target) if target else None,
                 "mb_per_hour": round(mb_per_hour, 1),
                 "projected_tb": (mb_per_hour * target / 1e6) if target else None},
        "disk": disk,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    tab_note = (f"({tab_total['videos']:,} videos + {tab_total['shorts']:,} shorts"
                f" + {tab_total['streams']:,} streams")
    if unknown_tab > 0:
        tab_note += f" + {unknown_tab:,} chưa rõ tab)"
    elif unknown_tab < 0:
        tab_note += f"; {abs(unknown_tab):,} file đã bị xoá/QC khỏi archive)"
    else:
        tab_note += ")"

    print("=== corpus staging ===")
    print(f"crawl root      : {download_dir}")
    print(f"audio files     : {total['files']:,}   {tab_note}")
    goal_note = f"   ({100.0 * hours / target:.2f}% của {target:,.0f} h)" if target else ""
    print(f"hours           : {hours:,.1f} h{goal_note}")
    print(f"size            : audio {si_bytes(total['bytes'])}  +  metadata "
          f"{si_bytes(total['meta_bytes'])} ({total['meta_files']:,} info.json)")
    if mb_per_hour:
        # MB/giờ × giờ = MB tổng; 1e6 MB = 1 TB (decimal SI, same unit as si_bytes)
        extra = f"   ⇒ {target:,.0f} h ≈ {mb_per_hour * target / 1e6:,.2f} TB" if target else ""
        print(f"efficiency      : {mb_per_hour:,.1f} MB/giờ{extra}")
    if disk:
        fit = f"  ⇒ còn crawl được ~{disk['hours_fit']:,.0f} h (theo {mb_per_hour:,.1f} MB/giờ)" \
            if disk["hours_fit"] else ""
        print(f"free space      : {si_bytes(disk['free_bytes'])} trống / {si_bytes(disk['total_bytes'])}{fit}")
    if cutoff is not None:
        print(f"last {args.since:<10s}  : +{total['since_files']:,} files  "
              f"+{total['since_hours']:,.1f} h  +{si_bytes(total['since_bytes'])}")
    if total["unparsed"]:
        print(f"WARNING         : {total['unparsed']:,} file(s) without a parsable duration in the "
              "name — excluded from hours")
    if total["meta_files"] > total["files"]:
        print(f"note            : info.json ({total['meta_files']:,}) > audio ({total['files']:,}) "
              "⇒ audio removed/QC-excluded; hours/GB count AUDIO only")

    shown = len(rows) if args.top == 0 else min(args.top, len(rows))
    print(f"\nper channel (top {shown} of {len(rows)} by hours):")
    for row in (rows if args.top == 0 else rows[:args.top]):
        if args.no_names:
            label = f"{row['channel']:64s}"
        else:
            label = f"{row['name'][:36]:36s} {row['channel'][:26]:26s}"
        tabs_note = (f" [{row['videos']:,}v/{row['shorts']:,}s/{row['streams']:,}st]"
                     if (row["videos"] or row["shorts"] or row["streams"]) else "")
        print(f"  {label} {row['files']:6,d} files  {row['hours']:8,.1f} h  "
              f"{si_bytes(row['bytes']):>9s}{tabs_note}")

    print("\ntip: these numbers come from filenames (fast, mid-crawl safe). The OFFICIAL index")
    print("     (2026 window + channel names) = python3 metadata/build_index.py --strict")
    print("     batch/upload progress to 50k h = python3 metadata/corpus_ledger.py report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
