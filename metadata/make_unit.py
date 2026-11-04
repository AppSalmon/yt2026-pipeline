#!/usr/bin/env python3
"""make_unit.py — W9: đóng gói một "unit" corpus để upload lên cloud (Drive / HuggingFace).

Unit KHÔNG phải tar: unit = DANH SÁCH FILE + metadata sidecar.
Audio ở nguyên chỗ (0 byte phát sinh); thư mục unit chỉ chứa:

    files.txt        đường dẫn tương đối -> dùng cho `rclone copy --files-from`
    manifest.jsonl   mỗi dòng 1 file: rel_path, size, mtime, video_id, duration,
                     channel_id, upload_date, info_json_path (+ sha256 khi có --hash)
    SHA256SUMS       sha256 từng file (GNU format: `sha256sum -c SHA256SUMS`)  [--hash]
    used_ids.txt     video_id của unit — ĐÓNG BĂNG; unit sau KHÔNG lấy lại (append-only)
    UNIT.json        metadata đơn vị (tên, số giờ/file/byte, rule, nguồn crawl)
    stats.json       schema khớp metadata/corpus_ledger.py (totals/per_channel/date_range)
    README.md        dataset card (YAML front-matter cho HuggingFace + cách restore)

Quy tắc chia (tất định — sort theo video_id, id không bao giờ đổi):
    --all (mặc định)          mọi file CHƯA thuộc unit nào trước đó
    --target-hours N          cắt khi luỹ kế >= N giờ (phần dư để unit sau)

Bất biến đã chọn (đừng đổi):
    * KHÔNG tar, KHÔNG nén, KHÔNG đổi đuôi, KHÔNG hardlink
      -> thư mục unit giống hệt nội dung repo HuggingFace (up 1 lần, dùng cho 2 nơi)
      -> xoá local là giải phóng dung lượng THẬT (hardlink sẽ giữ inode, df không giảm)

Usage:
    python3 metadata/make_unit.py --name yt2026_batch01_10kh                 # list, nhanh (không hash)
    python3 metadata/make_unit.py --name yt2026_batch01_10kh --target-hours 10000
    python3 metadata/make_unit.py --name yt2026_batch01_10kh --hash          # + SHA256SUMS (đọc toàn bộ audio)
    python3 metadata/make_unit.py --name yt2026_batch01_10kh --hash-only     # bổ sung hash cho unit có sẵn
Exit codes: 0 ok · 1 nothing to package · 2 path inside repo
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

# keep in sync with metadata/stats.py + build_index.py
AUDIO_EXTS = (".webm", ".m4a", ".mp3", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".flv", ".mov")
# <upload_date>#<title>#<channel_id>#<video_id>_<duration>.<ext>
# channel_id (UC… ) dài 24 ký tự; video_id dài 11 -> đừng hard-code 11 cho channel.
NAME_RE = re.compile(r"^(?P<date>\d{8})#(?P<title>.*)#(?P<chan>[A-Za-z0-9_-]{20,32})"
                     r"#(?P<vid>[A-Za-z0-9_-]{11})_(?P<dur>\d+)$")
HASH_CHUNK = 1 << 22


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_bytes(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1000 or unit == "TB":
            return f"{num:.2f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1000
    return f"{num:.2f} TB"


def human_gib(num):
    return f"{float(num or 0) / 1024 ** 3:.3f} GiB"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(HASH_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def units_root(dataset_dir):
    return Path(dataset_dir) / "units"


def load_previous_units(root, exclude=None):
    """video_id -> unit name, từ used_ids.txt của các unit ĐÃ có (append-only)."""
    frozen = {}
    if not Path(root).is_dir():
        return frozen
    for used in sorted(Path(root).glob("*/used_ids.txt")):
        if exclude and used.parent.name == exclude:
            continue
        try:
            lines = used.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            vid = line.strip()
            if vid:
                frozen.setdefault(vid, used.parent.name)
    return frozen


def collect(download_dir, frozen):
    """Quét staging -> danh sách record (chỉ đọc tên file, nhanh)."""
    records = []
    for ch_dir in sorted(p for p in Path(download_dir).iterdir() if p.is_dir()):
        for path in sorted(ch_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
                continue
            match = NAME_RE.match(path.stem)
            if not match:
                continue
            vid = match.group("vid")
            if vid in frozen:
                continue
            info = path.with_name(path.stem + ".info.json")
            stat = path.stat()
            records.append({
                "rel_path": f"{ch_dir.name}/{path.name}",
                # audio_path = rel_path — CỐ Ý để metadata/cleanup_local.py (dùng rec["audio_path"])
                # đọc được unit này: cùng 1 công cụ xoá DUY NHẤT của repo.
                "audio_path": f"{ch_dir.name}/{path.name}",
                "file": path.name,
                "channel_id": match.group("chan"),
                "video_id": vid,
                "upload_date": match.group("date"),
                "duration": int(match.group("dur")),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "info_json_path": f"{ch_dir.name}/{info.name}" if info.exists() else None,
            })
    # tất định: sort theo video_id (duy nhất, không đổi), tie-break bằng path
    records.sort(key=lambda r: (r["video_id"], r["rel_path"]))
    return records


def apply_target_hours(records, target_hours):
    if not target_hours:
        return records, []
    acc = 0
    for idx, rec in enumerate(records):
        acc += rec["duration"]
        if acc / 3600.0 >= target_hours:
            return records[: idx + 1], records[idx + 1:]
    return records, []


def write_manifest(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_manifest(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_outputs(out, name, records, download_dir, args, skipped):
    totals_bytes = sum(r["size"] for r in records)
    totals_hours = sum(r["duration"] for r in records) / 3600.0
    per_channel, per_month = {}, {}
    for rec in records:
        row = per_channel.setdefault(rec["channel_id"], {"files": 0, "hours": 0.0, "bytes": 0})
        row["files"] += 1
        row["hours"] += rec["duration"] / 3600.0
        row["bytes"] += rec["size"]
        month = rec["upload_date"][:6]
        mrow = per_month.setdefault(month, {"files": 0, "hours": 0.0, "gib": 0.0})
        mrow["files"] += 1
        mrow["hours"] += rec["duration"] / 3600.0
        mrow["gib"] += rec["size"] / 1024 ** 3

    # files.txt — dùng cho `rclone copy --files-from` PHẢI khớp đúng tập HF upload
    # (audio + MỌI info.json, trừ file rác .part) để Drive ≡ HF ≡ unit.
    info_paths = [r["info_json_path"] for r in records if r["info_json_path"]]
    seen = {r["rel_path"] for r in records} | set(info_paths)
    orphan_info = 0
    for ch_dir in sorted(p for p in Path(download_dir).iterdir() if p.is_dir()):
        for f in ch_dir.glob("*.info.json"):
            rel = f"{ch_dir.name}/{f.name}"
            if rel not in seen:
                info_paths.append(rel)
                seen.add(rel)
                orphan_info += 1          # audio đã bị QC loại — metadata vẫn phải giữ
    all_paths = sorted({r["rel_path"] for r in records} | set(info_paths))
    (out / "files.txt").write_text("".join(p + "\n" for p in all_paths), encoding="utf-8")
    (out / "used_ids.txt").write_text("".join(r["video_id"] + "\n" for r in records), encoding="utf-8")
    write_manifest(out / "manifest.jsonl", records)

    stats = {
        "batch": name,
        "created_utc": utcnow(),
        "source_download_dir": str(download_dir),
        "totals": {"files": len(records), "hours": totals_hours, "bytes": totals_bytes,
                   "channels": len(per_channel)},
        "per_channel": per_channel,
        "per_month": per_month,
        "date_range": {"first": min((r["upload_date"] for r in records), default=None),
                       "last": max((r["upload_date"] for r in records), default=None)},
        "selection": {"target_hours": args.target_hours, "all_new": True,
                      "rule": "sort by video_id asc; membership frozen in used_ids.txt",
                      "skipped": skipped},
        "info_json": {"files": sum(1 for r in records if r["info_json_path"])},
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    unit = {
        "schema": "unit/1", "unit": name, "created_utc": stats["created_utc"],
        "target_hours": args.target_hours, "hours": round(totals_hours, 3),
        "files": len(records), "bytes": totals_bytes, "channels": len(per_channel),
        "upload_date_window": f">= {paths.min_upload_date()}",
        "layout": "<unit>/<channel_id>/<upload_date>#<title>#<channel_id>#<video_id>_<dur>.<ext>",
        "drive_path": None, "hf_repo": None, "verified": False,
    }
    (out / "UNIT.json").write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
    write_readme(out / "README.md", name, stats, args)
    return stats


def write_readme(path, name, stats, args):
    tot = stats["totals"]
    lines = [
        "---",
        "language:",
        "- vi",
        "license: other",
        "task_categories:",
        "- automatic-speech-recognition",
        "tags:",
        "- audio",
        "- speech",
        "- vietnamese",
        "- youtube",
        f"pretty_name: {name}",
        "size_categories:",
        "- 10K<n<100K",
        "---",
        "",
        f"# {name} — Vietnamese YouTube audio corpus (cửa sổ 2026)",
        "",
        f"- created (UTC): {stats['created_utc']}",
        f"- upload_date: **{stats['date_range']['first']} → {stats['date_range']['last']}**"
        f" (yêu cầu cứng >= {paths.min_upload_date()})",
        f"- files: **{tot['files']}** · hours: **{tot['hours']:.3f} h** ·"
        f" size: **{human_bytes(tot['bytes'])}** ({human_gib(tot['bytes'])}) ·"
        f" channels: **{tot['channels']}**",
        f"- metadata: {stats['info_json']['files']} yt-dlp `info.json` (upload_date/language/channel"
        " — bằng chứng duy nhất của cửa sổ 2026)",
        "",
        "Audio là track **opus tiếng Việt gốc** (medium bitrate) của YouTube, lưu **không re-encode**.",
        "",
        "## Layout",
        "```",
        "<channel_id>/<upload_date>#<title>#<channel_id>#<video_id>_<duration>.webm",
        "<channel_id>/<upload_date>#<title>#<channel_id>#<video_id>_<duration>.info.json",
        "manifest.jsonl · SHA256SUMS · files.txt · used_ids.txt · UNIT.json · stats.json",
        "```",
        "",
        "## Verify",
        "```shell",
        "sha256sum -c SHA256SUMS        # toàn vẹn từng file (khi unit có SHA256SUMS)",
        "wc -l files.txt                # số file phải khớp manifest.jsonl",
        "```",
        "",
        "## Terms of access",
        "Dữ liệu thu thập tự động từ YouTube cho **nghiên cứu** (ASR tiếng Việt, có code-switch).",
        "Người dùng tự tuân thủ ToS của YouTube và luật bản quyền hiện hành; **không dùng cho mục đích",
        "thương mại, không phân phối lại như sản phẩm của mình**. Yêu cầu gỡ bỏ: liên hệ chủ repo —",
        "dữ liệu sẽ được xoá khỏi repo.",
        "",
        "## Per channel",
        "",
        "| channel | files | hours | GiB |",
        "|---|---:|---:|---:|",
    ]
    for channel, row in sorted(stats["per_channel"].items(), key=lambda kv: -kv[1]["hours"]):
        lines.append(f"| {channel} | {row['files']} | {row['hours']:.3f} |"
                     f" {row['bytes'] / 1024 ** 3:.3f} |")
    lines += ["", "## Per upload month", "", "| month | files | hours | GiB |", "|---|---:|---:|---:|"]
    for month, row in sorted(stats["per_month"].items()):
        lines.append(f"| {month} | {row['files']} | {row['hours']:.3f} | {row['gib']:.3f} |")
    lines += [
        "",
        "`used_ids.txt` = video_id của unit này; unit kế tiếp **loại trừ** các id này",
        "(append-only — không bao giờ xáo trộn dữ liệu đã phát hành).",
        "",
        "NEVER delete `crawler/log/audios_*.txt` (dedup archive, non-reproducible).",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def hash_records(out, download_dir, records):
    """Tính sha256 từng file -> SHA256SUMS (GNU format) + ghi sha256 vào manifest.jsonl.

    Chạy lại được: dòng đã có trong SHA256SUMS sẽ được bỏ qua (resume).
    """
    out = Path(out)
    sums_path = out / "SHA256SUMS"
    manifest_path = out / "manifest.jsonl"
    done = {}
    if sums_path.exists():
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("  ", 1)
            if len(parts) == 2:
                done[parts[1]] = parts[0]
    for rec in records:
        if rec["rel_path"] in done:
            rec["sha256"] = done[rec["rel_path"]]
    todo = [r for r in records if r["rel_path"] not in done]
    print(f"hash        : {len(todo)} file cần hash (đã có {len(done)})", flush=True)
    t0 = time.time()
    done_bytes = 0
    with open(sums_path, "a", encoding="utf-8") as fh:
        for idx, rec in enumerate(todo, 1):
            path = Path(download_dir) / rec["rel_path"]
            if not path.is_file():
                print(f"WARNING: missing, skipped: {path}", flush=True)
                continue
            digest = sha256_file(path)
            fh.write(f"{digest}  {rec['rel_path']}\n")
            rec["sha256"] = digest
            done_bytes += path.stat().st_size
            if idx % 200 == 0 or idx == len(todo):
                fh.flush()
                rate = done_bytes / max(time.time() - t0, 1e-6)
                print(f"  {idx}/{len(todo)}  {human_bytes(done_bytes)}  {rate / 1e6:.0f} MB/s",
                      flush=True)
    write_manifest(manifest_path, records)
    print(f"SHA256SUMS  : {sums_path} ({len(records)} dòng)", flush=True)


def leftovers(download_dir):
    """File trong staging KHÔNG được đưa vào unit nào (để Drive/HF không lệch nhau)."""
    parts, badname = [], []
    for ch_dir in sorted(p for p in Path(download_dir).iterdir() if p.is_dir()):
        for path in ch_dir.iterdir():
            if not path.is_file():
                continue
            if path.name.endswith((".part", ".ytdl", ".temp")):
                parts.append(path.name)
            elif path.suffix.lower() in AUDIO_EXTS and not NAME_RE.match(path.stem):
                badname.append(path.name)
    return parts, badname


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="tên unit (vd yt2026_batch01_10kh)")
    parser.add_argument("--target-hours", type=float, default=None,
                        help="cắt khi luỹ kế đạt N giờ (mặc định: lấy hết phần chưa thuộc unit nào)")
    parser.add_argument("--hash", action="store_true",
                        help="tính sha256 -> SHA256SUMS (đọc toàn bộ audio, lâu)")
    parser.add_argument("--hash-only", action="store_true",
                        help="chỉ bổ sung/tiếp tục hash cho unit đã có (không quét lại)")
    parser.add_argument("--strict-window", action="store_true",
                        help="DỪNG nếu có file ngoài cửa sổ upload_date")
    parser.add_argument("--download-dir", type=Path, default=None)
    parser.add_argument("--dataset-dir", type=Path, default=None)
    parser.add_argument("--units-dir", type=Path, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else paths.dataset_dir()
    root = Path(args.units_dir) if args.units_dir else units_root(dataset_dir)
    out = root / args.name
    if paths.in_repo(out) and not paths.allow_in_repo_download():
        raise SystemExit(f"refusing to write inside the repo ({out})")
    out.mkdir(parents=True, exist_ok=True)

    print("=== make_unit — đóng gói 1 unit để upload (KHÔNG tar, KHÔNG hardlink) ===")
    print(f"download dir : {download_dir}")
    print(f"unit dir     : {out}")

    if args.hash_only:
        records = read_manifest(out / "manifest.jsonl")
        print(f"hash-only    : {len(records)} file theo manifest.jsonl")
        hash_records(out, download_dir, records)
        return 0

    frozen = load_previous_units(root, exclude=args.name)
    if frozen:
        print(f"đã đóng băng : {len(frozen)} video_id thuộc {len(set(frozen.values()))} unit trước")
    records = collect(download_dir, frozen)
    if not records:
        raise SystemExit("nothing to package — không có file mới nào ngoài các unit đã có")
    records, dropped = apply_target_hours(records, args.target_hours)

    outside = [r for r in records if r["upload_date"] < paths.min_upload_date()]
    if outside:
        print(f"WARNING      : {len(outside)} file NGOÀI cửa sổ >= {paths.min_upload_date()}"
              f" (vd {outside[0]['rel_path']})")
        if args.strict_window:
            raise SystemExit("strict-window: DỪNG — chạy build_index.py để rà soát")

    parts, badname = leftovers(download_dir)
    skipped = {"belongs_to_previous_units": len(frozen), "dropped_by_target_hours": len(dropped)}
    stats = write_outputs(out, args.name, records, download_dir, args, skipped)
    tot = stats["totals"]
    print(f"files        : {tot['files']} (info.json: {stats['info_json']['files']})")
    print(f"hours        : {tot['hours']:.3f} h")
    print(f"bytes        : {human_bytes(tot['bytes'])} ({human_gib(tot['bytes'])})")
    print(f"channels     : {tot['channels']} · window {stats['date_range']['first']}"
          f" → {stats['date_range']['last']}")
    print(f"để lại unit sau: {len(dropped)} file")
    if parts or badname:
        print(f"KHÔNG đưa vào unit: {len(parts)} file .part + {len(badname)} tên lạ"
              "  <-- phải xử lý để Drive/HF không lệch nhau")
    print("wrote        : files.txt · manifest.jsonl · used_ids.txt · UNIT.json · stats.json · README.md")
    if args.hash:
        hash_records(out, download_dir, records)
    else:
        print(f"(chưa hash) chạy:  python3 metadata/make_unit.py --name {args.name} --hash-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())

