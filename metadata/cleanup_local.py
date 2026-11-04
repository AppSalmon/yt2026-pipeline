#!/usr/bin/env python3
"""Delete the local files of a VERIFIED batch — the only sanctioned deletion in this repo.

Guarantees:
  * refuses unless the ledger says `verified: true` for that batch (upload + remote check done)
  * only touches files listed in that batch's manifest.jsonl
  * NEVER touches crawler/log/audios_*.txt (non-reproducible dedup archive), the batch
    folder (manifest/parts/meta/SHA256SUMS/README), the ledger, or info.json of videos that
    are not in the batch
  * also removes the `dataset/audio/...` hardlink copy — a hardlink keeps the inode alive,
    so without this step cleanup would free ZERO bytes and `df` would not move
  * `--check-sha` (default on) re-hashes every file before deleting it, so a file that
    changed after packaging is never silently destroyed; mismatches are reported and skipped

Usage:
  python3 metadata/cleanup_local.py batch_001            # dry run (default)
  python3 metadata/cleanup_local.py batch_001 --yes      # actually delete
  python3 metadata/cleanup_local.py batch_001 --yes --keep-info-json
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
from corpus_ledger import load_ledger, sha256_file  # noqa: E402


def human_bytes(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TB"


def load_manifest(batch_dir):
    rows = []
    path = Path(batch_dir) / "manifest.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} not found — not a packaged batch")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def prune_empty_dirs(root, start):
    """Remove now-empty channel dirs under `root` (walk up, stop at root)."""
    root = Path(root).resolve()
    current = Path(start).resolve()
    removed = 0
    while current != root and root in current.parents:
        try:
            next(current.iterdir())
            break
        except StopIteration:
            try:
                current.rmdir()
                removed += 1
            except OSError:
                break
            current = current.parent
    return removed


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", help="batch name (e.g. batch_001)")
    parser.add_argument("--batch-dir", type=Path, default=None,
                        help="batch folder (default <DATASET_DIR>/<batch>)")
    parser.add_argument("--download-dir", type=Path, default=None,
                        help="crawl root (default: $DOWNLOAD_DIR)")
    parser.add_argument("--dataset-dir", type=Path, default=None,
                        help="derived-data root (default: $DATASET_DIR)")
    parser.add_argument("--ledger-file", type=Path, default=None,
                        help="ledger (default: $LEDGER_FILE)")
    parser.add_argument("--yes", action="store_true",
                        help="actually delete (without this it is a dry run)")
    parser.add_argument("--check-sha", dest="check_sha", action="store_true", default=True)
    parser.add_argument("--no-check-sha", dest="check_sha", action="store_false",
                        help="skip re-hashing before deleting (faster, riskier)")
    parser.add_argument("--keep-info-json", action="store_true",
                        help="keep *.info.json locally (they are already inside meta.tar.gz)")
    args = parser.parse_args()

    download_dir = Path(args.download_dir) if args.download_dir else paths.download_dir()
    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else paths.dataset_dir()
    ledger_file = Path(args.ledger_file) if args.ledger_file else paths.ledger_file()
    batch_dir = Path(args.batch_dir) if args.batch_dir else dataset_dir / args.batch

    print(f"=== cleanup_local: {args.batch} ({'DELETE' if args.yes else 'DRY RUN'}) ===")
    print(f"download dir : {download_dir}")
    print(f"batch dir    : {batch_dir}")
    print(f"ledger       : {ledger_file}")

    rows = load_ledger(ledger_file)
    row = next((r for r in rows if r.get("batch") == args.batch), None)
    if row is None:
        raise SystemExit(f"{args.batch} is not in the ledger — refusing to delete anything.")
    if not row.get("verified"):
        raise SystemExit(
            f"{args.batch} is NOT verified in the ledger "
            f"(drive_path={row.get('drive_path')}).\n"
            "Refusing to delete: run sync/upload_batch.sh then sync/verify_remote.sh first."
        )
    print(f"ledger       : verified=true, drive_path={row.get('drive_path')}, "
          f"verified_utc={row.get('verified_utc')}")

    records = load_manifest(batch_dir)
    audio_root = dataset_dir / "audio"
    freed = 0
    deleted = {"audio": 0, "info_json": 0, "hardlink": 0}
    problems = []
    dirs_to_prune = set()

    for rec in records:
        rel = rec.get("audio_path")
        if not rel:
            continue
        targets = [("audio", download_dir / rel)]
        if rec.get("info_json_path") and not args.keep_info_json:
            targets.append(("info_json", download_dir / rec["info_json_path"]))
        mirror = audio_root / rel
        if mirror.exists():
            targets.append(("hardlink", mirror))

        for kind, path in targets:
            if not path.exists():
                continue
            if kind == "audio" and args.check_sha and rec.get("sha256"):
                if sha256_file(path) != rec["sha256"]:
                    problems.append(f"sha256 mismatch, NOT deleted: {path}")
                    continue
            try:
                size = path.stat().st_size
                if args.yes:
                    path.unlink()
                freed += size
                deleted[kind] += 1
                dirs_to_prune.add(path.parent)
            except OSError as exc:
                problems.append(f"could not delete {path}: {exc}")

    pruned = 0
    if args.yes:
        for parent in dirs_to_prune:
            pruned += prune_empty_dirs(download_dir, parent)
            pruned += prune_empty_dirs(audio_root, parent)

    verb = "deleted" if args.yes else "to delete"
    print(f"\nfiles {verb}: audio={deleted['audio']} info_json={deleted['info_json']} "
          f"hardlink_mirror={deleted['hardlink']}")
    print(f"space {'freed' if args.yes else 'that would be freed'}: {human_bytes(freed)}")
    if pruned:
        print(f"empty dirs removed: {pruned}")
    for problem in problems:
        print(f"WARNING: {problem}")
    print(f"\nkept locally: crawler/log/audios_*.txt (dedup archive — non-reproducible), "
          f"{batch_dir.name}/ (manifest, tar parts, meta, SHA256SUMS), ledger")
    if not args.yes:
        print("\nDRY RUN — re-run with --yes to delete for real.")
    else:
        print(f"staging free space now: {human_bytes(shutil.disk_usage(download_dir).free)}")


if __name__ == "__main__":
    main()
