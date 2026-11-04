#! /usr/bin/bash
#
# verify_unit.sh — chứng minh unit trên Drive là bản sao ĐÚNG của local, rồi in ra
# lệnh xoá để USER TỰ CHẠY (agent KHÔNG được xoá — user chốt 2026-10-01).
#
# Usage:
#   ./sync/verify_unit.sh <unit> [--remote <dir>] [--no-ledger]
#
# Các lớp kiểm tra:
#   1) rclone check --checksum --one-way : md5 (Drive md5Checksum) + size TỪNG file theo files.txt
#   2) đếm file:  remote >= local (local = số dòng files.txt)
#   3) ghi ledger `verified=true` (đi kiện để cleanup_local.py cho phép xoá)
set -uo pipefail
export LC_ALL=C

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
# shellcheck source=../config.env
[ -f "$PIPELINE_DIR/config.env" ] && . "$PIPELINE_DIR/config.env"
DATA_ROOT=${DATA_ROOT:-$HOME/data}
DATASET_DIR=${DATASET_DIR:-$DATA_ROOT/dataset}
DOWNLOAD_DIR=${DOWNLOAD_DIR:-$DATA_ROOT/download_from_youtube}
GDRIVE_PARENT=${GDRIVE_PARENT:-gdrive:corpus}
MARK=1

if [ $# -lt 1 ]; then
  echo "Usage: $0 <unit> [--remote <dir>] [--no-ledger]"
  exit 1
fi
UNIT=$1; shift
REMOTE="$GDRIVE_PARENT/$UNIT"
while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE=$2; shift 2 ;;
    --no-ledger) MARK=0; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

UNIT_DIR="$DATASET_DIR/units/$UNIT"
[ -f "$UNIT_DIR/files.txt" ] || { echo "ERROR: thiếu $UNIT_DIR/files.txt"; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo "ERROR: rclone chưa cài"; exit 1; }

LOG_DIR="$DATASET_DIR/_logs"; mkdir -p "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M%S); LOG="$LOG_DIR/verify_${UNIT}_${TS}.log"
local_files=$(wc -l < "$UNIT_DIR/files.txt")

echo "=== verify_unit: $UNIT ==="
echo "local  : $DOWNLOAD_DIR ($local_files file theo files.txt)"
echo "remote : $REMOTE"
echo "log    : $LOG"
echo
echo "--- (1) rclone check --checksum --one-way (md5 + size TỪNG file) ---"
rclone check "$DOWNLOAD_DIR" "$REMOTE" --files-from "$UNIT_DIR/files.txt" \
  --checksum --one-way --log-level INFO --log-file "$LOG" 2>&1 | tail -6
check_rc=${PIPESTATUS[0]}
echo "rclone check exit: $check_rc"

echo "--- (2) đếm file ---"
remote_files=$(rclone lsf "$REMOTE" -R --files-only 2>/dev/null | wc -l)
echo "local  (files.txt) : $local_files"
echo "remote (recursive) : $remote_files"

if [ "$check_rc" -ne 0 ] || [ "${remote_files:-0}" -lt "$local_files" ]; then
  echo
  echo "VERDICT: 🔴 FAIL — KHÔNG được báo user xoá. Xem $LOG rồi chạy lại ./sync/upload_unit.sh $UNIT"
  exit 1
fi
echo
echo "VERDICT: 🟢 PASS — remote là bản sao đúng của local (md5 + size khớp từng file)"

if [ "$MARK" = "1" ]; then
  python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" append --batch-dir "$UNIT_DIR" >/dev/null 2>&1 || true
  python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" mark-verified --batch "$UNIT" \
    --drive-path "$REMOTE" --remote-files "${remote_files:-0}" 2>&1 | tail -2 \
    || echo "WARNING: không ghi được ledger (chạy tay nếu cần)"
fi

echo
echo ">>> LỆNH XOÁ CHO USER (agent KHÔNG chạy, user tự chạy) <<<"
echo "cd $PIPELINE_DIR"
echo "python3 metadata/cleanup_local.py $UNIT --batch-dir $UNIT_DIR          # DRY-RUN"
echo "python3 metadata/cleanup_local.py $UNIT --batch-dir $UNIT_DIR --yes     # xoá thật"
echo
echo "Lưu ý: tool này kiểm sha256 từng file trước khi xoá (cần $UNIT_DIR/SHA256SUMS"
echo "đã hash -> nếu thiếu thì chạy: nice -n 19 python3 metadata/make_unit.py --name $UNIT --hash-only)"
