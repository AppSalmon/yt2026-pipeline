#! /usr/bin/bash
#
# upload_batch.sh — đẩy 1 batch đã đóng gói lên Google Drive bằng rclone.
#
# Usage:
#   ./upload_batch.sh <batch_name|batch_dir> [--remote gdrive:corpus] [--dry-run]
#                     [--transfers 2] [--check-local] [--with-ledger]
#
# Đặc điểm:
#   * resumable: chạy lại cùng lệnh sẽ chỉ copy phần còn thiếu (rclone --checksum)
#   * retry:     --retries 5 --low-level-retries 20 (mạng datacenter hay chập chờn)
#   * log:       <DATASET_DIR>/_logs/upload_<batch>_<ts>.log
#   * KHÔNG xoá gì ở local (cleanup là bước riêng, chỉ sau khi verify PASS)
#
# Lưu ý Drive: giới hạn ~750GB/ngày/tài khoản → batch 300–400GB là hợp lý.
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
  echo "Usage: $0 <batch_name|batch_dir> [--remote REMOTE] [--dry-run] [--transfers N] [--check-local] [--with-ledger]"
  exit 1
fi
BATCH_ARG=$1; shift
REMOTE=$GDRIVE_REMOTE
TRANSFERS=2
DRY_RUN=0
CHECK_LOCAL=0
WITH_LEDGER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE=$2; shift 2 ;;
    --transfers) TRANSFERS=$2; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --check-local) CHECK_LOCAL=1; shift ;;
    --with-ledger) WITH_LEDGER=1; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

BATCH_DIR=$BATCH_ARG
[ -d "$BATCH_DIR" ] || BATCH_DIR="$DATASET_DIR/$BATCH_ARG"
BATCH_NAME=$(basename "$BATCH_DIR")
[ -d "$BATCH_DIR" ] || { echo "ERROR: batch dir not found: $BATCH_ARG"; exit 1; }
[ -f "$BATCH_DIR/SHA256SUMS" ] || { echo "ERROR: $BATCH_DIR/SHA256SUMS missing — run metadata/make_batch.py first"; exit 1; }
[ -f "$BATCH_DIR/manifest.jsonl" ] || { echo "ERROR: $BATCH_DIR/manifest.jsonl missing"; exit 1; }

command -v rclone >/dev/null 2>&1 || { echo "ERROR: rclone chưa cài — chạy sync/install_rclone.sh"; exit 1; }

# --- safety: never upload secrets -------------------------------------------------
if find "$BATCH_DIR" -maxdepth 1 -name 'cookie*' | grep -q .; then
  echo "ERROR: phát hiện file cookie trong batch — dừng để tránh rò rỉ."
  exit 1
fi

LOG_DIR="$DATASET_DIR/_logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/upload_${BATCH_NAME}_$(date +%Y%m%d_%H%M%S).log"

DEST="$REMOTE/$BATCH_NAME"
files=$(find "$BATCH_DIR" -maxdepth 1 -type f | wc -l)
bytes=$(find "$BATCH_DIR" -maxdepth 1 -type f -printf '%s\n' | awk '{s+=$1} END {printf "%d", s+0}')

echo "=== upload_batch ==="
echo "batch      : $BATCH_NAME"
echo "local      : $BATCH_DIR  ($files file(s), $(awk -v b="$bytes" 'BEGIN{printf "%.2f GiB", b/1073741824}'))"
echo "remote     : $DEST"
echo "log        : $LOG"

echo "--- kiểm tra remote có tồn tại ---"
if ! rclone lsd "$(echo "$REMOTE" | cut -d: -f1):" >/dev/null 2>&1; then
  echo "ERROR: rclone remote chưa cấu hình/authorize được ($REMOTE)."
  echo "       Chạy: rclone config --auth-no-open-browser"
  exit 1
fi

if [ "$CHECK_LOCAL" = "1" ]; then
  echo "--- verify local SHA256SUMS trước khi upload (đọc toàn bộ batch) ---"
  if ! (cd "$BATCH_DIR" && sha256sum -c SHA256SUMS --quiet); then
    echo "ERROR: checksum local không khớp — KHÔNG upload. Chạy lại make_batch --verify."
    exit 1
  fi
  echo "local checksums OK"
fi

rclone_args=(
  copy "$BATCH_DIR" "$DEST"
  --checksum
  --transfers "$TRANSFERS"
  --retries 5
  --low-level-retries 20
  --drive-chunk-size 64M
  --stats 30s
  --stats-one-line
  --log-file "$LOG"
  --log-level INFO
)
if [ "$DRY_RUN" = "1" ]; then
  rclone_args+=(--dry-run)
  echo "--- DRY RUN (không copy thật) ---"
fi

echo "--- rclone copy ---"
rclone "${rclone_args[@]}"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "ERROR: rclone exit $rc — xem $LOG. Chạy lại chính lệnh này để resume."
  exit "$rc"
fi

echo "--- remote sau upload ---"
remote_files=$(rclone lsjson "$DEST" --files-only 2>/dev/null | grep -c '"Path"')
echo "remote files: ${remote_files:-0} (local top-level: $files)"
echo
echo "Xong. Bước tiếp theo BẮT BUỘC (để mở khoá cleanup):"
echo "  ./verify_remote.sh $BATCH_NAME"
if [ "$WITH_LEDGER" = "1" ]; then
  echo "--- push ledger lên Drive ---"
  python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" push || echo "WARNING: push ledger thất bại (không ảnh hưởng batch)"
fi
