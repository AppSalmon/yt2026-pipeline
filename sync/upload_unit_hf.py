#!/usr/bin/env python3
"""upload_unit_hf.py — đẩy 1 "unit" lên HuggingFace theo từng CHUNK (commit dần).

Vì sao chia chunk (thay vì 1 lệnh `hf upload . .` cho 42k file):
  * thấy tiến độ thật: mỗi chunk commit xong là dữ liệu ĐÃ NẰM TRÊN HF (không phải
    "hash hàng giờ rồi mới bắt đầu gửi")
  * lỗi 1 chunk không làm hỏng cả lần upload; chạy lại chỉ chạy chunk còn thiếu
  * mỗi chunk vài chục kênh -> commit vừa phải, dễ audit
Chunk = nhóm THƯ MỤC KÊNH; pattern `UCxxxx/*` -> allow_patterns, luôn loại `*.part`.

Chạy lại được (resumable): state file .hf_upload_state.json ghi chunk đã xong; dù mất
state, upload_folder vẫn tự bỏ qua file không đổi.

Usage:
    sync/upload_unit_hf.sh <unit> --repo <hf-user>/<unit>
    sync/upload_unit_hf.sh <unit> --list
    sync/upload_unit_hf.sh <unit> --channels-per-chunk 20
    sync/upload_unit_hf.sh <unit> --only-channel UCxxxx      # test 1 chunk
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "metadata"))
import paths  # noqa: E402

IGNORE = ["*.part", "*.ytdl", "*.temp", ".cache/*", "**/.cache/*"]
STATE_SCHEMA = "hf_upload_state/1"
RUBBISH = (".part", ".ytdl", ".temp")


def human_bytes(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1000 or unit == "TB":
            return f"{num:.2f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1000
    return f"{num:.2f} TB"


def unit_dir(dataset_dir, name):
    return Path(dataset_dir) / "units" / name


def list_channels(download_dir, only=None):
    """kênh -> (số file, số byte), bỏ qua file rác (.part/.ytdl/.temp)."""
    out = {}
    for ch in sorted(p for p in Path(download_dir).iterdir() if p.is_dir()):
        files = [f for f in ch.iterdir() if f.is_file() and not f.name.endswith(RUBBISH)]
        if not files or (only and ch.name != only):
            continue
        out[ch.name] = (len(files), sum(f.stat().st_size for f in files))
    return out


def make_chunks(channels, per_chunk):
    names = sorted(channels)
    return [names[i:i + per_chunk] for i in range(0, len(names), per_chunk)]


def load_state(path):
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"schema": STATE_SCHEMA, "chunks_done": []}


def save_state(path, state):
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit", help="tên unit (vd yt2026_batch01_10kh)")
    ap.add_argument("--repo", default=None, help="repo_id HF (mặc định <user>/<unit>)")
    ap.add_argument("--channels-per-chunk", type=int, default=30)
    ap.add_argument("--only-channel", default=None, help="chỉ chạy 1 kênh (để test)")
    ap.add_argument("--list", action="store_true", help="chỉ liệt kê chunk rồi thoát")
    ap.add_argument("--num-workers", type=int, default=8,
                    help="số worker cho upload_large_folder (v1.x)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--download-dir", type=Path, default=None)
    ap.add_argument("--dataset-dir", type=Path, default=None)
    args = ap.parse_args()

    download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else paths.dataset_dir()
    udir = unit_dir(dataset_dir, args.unit)
    if not (udir / "manifest.jsonl").exists():
        raise SystemExit(f"{udir}/manifest.jsonl không có — chạy metadata/make_unit.py trước")

    channels = list_channels(download_dir, only=args.only_channel)
    if not channels:
        raise SystemExit(f"không thấy kênh nào (only={args.only_channel})")
    chunks = make_chunks(channels, args.channels_per_chunk)
    total_files = sum(n for n, _ in channels.values())
    total_bytes = sum(b for _, b in channels.values())

    print("=== upload_unit_hf ===")
    print(f"unit         : {args.unit}")
    print(f"download dir : {download_dir}")
    print(f"kênh         : {len(channels)} · file: {total_files} · {human_bytes(total_bytes)}")
    print(f"chunk        : {len(chunks)} (mỗi chunk {args.channels_per_chunk} kênh)")
    repo = args.repo
    if not repo:
        try:
            from huggingface_hub import HfApi
            repo = f"{HfApi().whoami()['name']}/{args.unit}"
        except Exception as exc:                       # noqa: BLE001
            raise SystemExit(f"không xác định được --repo (cần token HF): {exc}")
    print(f"repo         : {repo} (dataset)")
    if args.list:
        for idx, chunk in enumerate(chunks, 1):
            size = sum(channels[c][1] for c in chunk)
            print(f"  chunk {idx:02d}/{len(chunks)}: {len(chunk)} kênh · {human_bytes(size)}"
                  f" · {chunk[0]} … {chunk[-1]}")
        return 0

    from huggingface_hub import HfApi
    api = HfApi()
    state_path = udir / ".hf_upload_state.json"
    state = load_state(state_path)
    state["repo"] = repo
    if not args.dry_run:
        api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True, private=False)

    t_all = time.time()
    for idx, chunk in enumerate(chunks, 1):
        if idx in state["chunks_done"]:
            print(f"chunk {idx:02d}/{len(chunks)}: đã xong (bỏ qua)")
            continue
        patterns = [f"{c}/*" for c in chunk]
        size = sum(channels[c][1] for c in chunk)
        nfiles = sum(channels[c][0] for c in chunk)
        print(f"\n--- chunk {idx:02d}/{len(chunks)}: {len(chunk)} kênh · {nfiles} file ·"
              f" {human_bytes(size)} ---", flush=True)
        if args.dry_run:
            print(f"    (dry-run) allow_patterns={patterns[:3]}… ignore={IGNORE}")
            continue
        t0 = time.time()
        try:
            if hasattr(api, "upload_large_folder"):
                # v1.x: đa luồng + cache hash -> resume; NHANH HƠN NHIỀU cho 42k file nhỏ
                api.upload_large_folder(
                    repo_id=repo, folder_path=str(download_dir), repo_type="dataset",
                    allow_patterns=patterns, ignore_patterns=IGNORE,
                    num_workers=args.num_workers, print_report=False)
                info = None
            else:
                info = api.upload_folder(
                    repo_id=repo, repo_type="dataset",
                    folder_path=str(download_dir), path_in_repo=".",
                    allow_patterns=patterns, ignore_patterns=IGNORE,
                    commit_message=(f"{args.unit}: chunk {idx}/{len(chunks)} "
                                    f"({len(chunk)} channels, {human_bytes(size)})"))
        except Exception as exc:                       # noqa: BLE001
            print(f"    LỖI chunk {idx}: {exc}\n    -> chạy lại lệnh này để tiếp tục")
            save_state(state_path, state)
            return 1
        took = time.time() - t0
        tag = str(getattr(info, "oid", ""))[:12] if info else "upload_large_folder"
        print(f"    OK {took / 60:.1f} phút · {size / max(took, 1e-6) / 1e6:.1f} MB/s ·"
              f" {tag}", flush=True)
        if args.only_channel:
            print("    (--only-channel: KHÔNG ghi state, để không ảnh hưởng chunk thật)")
        else:
            state["chunks_done"].append(idx)
            save_state(state_path, state)

    print(f"\nTONG: {len(state['chunks_done'])}/{len(chunks)} chunk trong"
          f" {(time.time() - t_all) / 3600:.2f} h")
    print(f"state: {state_path}")
    return 0 if len(state["chunks_done"]) >= len(chunks) else 1


if __name__ == "__main__":
    sys.exit(main())
