#! /usr/bin/bash
#
# verify_remote.sh — chứng minh batch trên Drive là bản sao đúng của batch local,
# rồi ĐÁNH DẤU verified=true trong corpus_ledger.jsonl (điều kiện DUY NHẤT để cleanup).
#
# Usage:
#   ./verify_remote.sh <batch_name|batch_dir> [--remote gdrive:corpus]
#                      [--no-mark] [--strict-local]
#
# Các lớp kiểm tra:
#   1) rclone check --checksum  : so md5 (Drive md5Checksum) + size từng file
#   2) số file trên remote      : phải >= số file top-level của batch local
#   3) (--strict-local) sha256sum -c SHA256SUMS tại local (đọc toàn bộ batch)
#   4) ledger.update            : verified=true + drive_path + remote_files
set -uo pipefail
export LC_ALL=C

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
# shellcheck source=../config.env
[ -f "$PIPELINE_DIR/config.env" ] && . "$PIPELINE_DIR/config.env"
DATA_ROOT=${DATA_ROOT:-$HOME/data}
DATASET_DIR=${DATASET_DIR:-$DATA_ROOT/dataset}
GDRIVE_REMOTE=${GDRIVE_REMOTE:-gdrive:corpus}

if [ $# -lt 1 ]; then
  echo "Usage: $0 <batch_name|batch_dir> [--remote REMOTE] [--no-mark] [--strict-local]"
  exit 1
fi
BATCH_ARG=$1; shift
REMOTE=$GDRIVE_REMOTE
MARK=1
STRICT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE=$2; shift 2 ;;
    --no-mark) MARK=0; shift ;;
    --strict-local) STRICT=1; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

BATCH_DIR=$BATCH_ARG
[ -d "$BATCH_DIR" ] || BATCH_DIR="$DATASET_DIR/$BATCH_ARG"
BATCH_NAME=$(basename "$BATCH_DIR")
[ -d "$BATCH_DIR" ] || { echo "ERROR: batch dir not found: $BATCH_ARG"; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo "ERROR: rclone chưa cài — chạy sync/install_rclone.sh"; exit 1; }
DEST="$REMOTE/$BATCH_NAME"

LOG_DIR="$DATASET_DIR/_logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/verify_${BATCH_NAME}_$(date +%Y%m%d_%H%M%S).log"

echo "=== verify_remote ==="
echo "batch  : $BATCH_NAME"
echo "local  : $BATCH_DIR"
echo "remote : $DEST"
echo "log    : $LOG"
echo

if [ "$STRICT" = "1" ]; then
  echo "--- (3) sha256sum -c SHA256SUMS tại local ---"
  if ! (cd "$BATCH_DIR" && sha256sum -c SHA256SUMS --ignore-missing --quiet); then
    echo "ERROR: checksum local không khớp — batch local hỏng, verify thất bại."
    exit 1
  fi
  echo "local checksums OK"
fi

echo "--- (1) rclone check --checksum (md5 + size từng file) ---"
rclone check "$BATCH_DIR" "$DEST" --checksum --one-way \
  --log-file "$LOG" --log-level INFO 2>&1 | tail -5
check_rc=${PIPESTATUS[0]}
echo "rclone check exit: $check_rc"

echo "--- (2) đối chiếu số file ---"
local_files=$(find "$BATCH_DIR" -maxdepth 1 -type f | wc -l)
remote_files=$(rclone lsjson "$DEST" --files-only 2>/dev/null | grep -c '"Path"' || true)
echo "local top-level files : $local_files"
echo "remote files          : ${remote_files:-0}"

if [ "$check_rc" -ne 0 ]; then
  echo
  echo "VERDICT: FAIL — remote KHÔNG khớp local. KHÔNG được cleanup."
  echo "         Xem $LOG rồi chạy lại: ./upload_batch.sh $BATCH_NAME"
  exit 1
fi
if [ "${remote_files:-0}" -lt "$local_files" ]; then
  echo
  echo "VERDICT: FAIL — remote thiếu file ($remote_files < $local_files). KHÔNG cleanup."
  exit 1
fi

echo
echo "VERDICT: PASS — remote là bản sao đúng của local"
if [ "$MARK" = "1" ]; then
  python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" mark-verified \
    --batch "$BATCH_NAME" --drive-path "$DEST" --remote-files "${remote_files:-0}" \
    || { echo "WARNING: không cập nhật được ledger — chạy tay:"; \
         echo "  python3 metadata/corpus_ledger.py mark-verified --batch $BATCH_NAME --drive-path $DEST"; }
  echo "Bước tiếp theo (GIỜ mới được xoá local):  ./cleanup_local.sh $BATCH_NAME"
else
  echo "(--no-mark: ledger KHÔNG được cập nhật, cleanup vẫn bị chặn)"
fi
