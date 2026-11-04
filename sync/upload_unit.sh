#! /usr/bin/bash
#
# upload_unit.sh — đẩy 1 unit lên Google Drive bằng rclone (resumable, --checksum, log).
#
# Usage:
#   ./sync/upload_unit.sh <unit> [--remote <dir>] [--transfers N] [--dry-run]
#     <unit>  = tên unit đã tạo bởi metadata/make_unit.py  (vd: yt2026_batch01_10kh)
#     --remote mặc định: $GDRIVE_PARENT/<unit>   (GDRIVE_PARENT = gdrive:corpus)
#
# Đặc điểm:
#   * copy theo ĐÚNG `files.txt` của unit (audio + mọi info.json, LOẠI file .part)
#     => tập file trên Drive ≡ tập HF ≡ nội dung unit
#   * chạy lại là resume (rclone --checksum: file đã đúng md5/md5+size sẽ bị bỏ qua)
#   * log: <DATASET_DIR>/_logs/upload_<unit>_<ts>.log
#   * CHƯA verify — bắt buộc ./sync/verify_unit.sh trước khi báo user xoá local
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
TRANSFERS=4
DRY=0

if [ $# -lt 1 ]; then
  echo "Usage: $0 <unit> [--remote <dir>] [--transfers N] [--dry-run]"
  exit 1
fi
UNIT=$1; shift
REMOTE="$GDRIVE_PARENT/$UNIT"
while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE=$2; shift 2 ;;
    --transfers) TRANSFERS=$2; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

UNIT_DIR="$DATASET_DIR/units/$UNIT"
[ -f "$UNIT_DIR/files.txt" ] || {
  echo "ERROR: không thấy $UNIT_DIR/files.txt — chạy: python3 metadata/make_unit.py --name $UNIT"
  exit 1; }
command -v rclone >/dev/null 2>&1 || {
  echo "ERROR: rclone chưa cài — ./sync/install_rclone.sh"; exit 1; }
if ! rclone lsd "$(echo "$REMOTE" | cut -d: -f1):" >/dev/null 2>&1; then
  echo "ERROR: remote không list được (chưa authorize / token hết hạn?) — xem HANDOVER §6b mục lỗi 1–2"
  exit 1
fi

LOG_DIR="$DATASET_DIR/_logs"; mkdir -p "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M%S); LOG="$LOG_DIR/upload_${UNIT}_${TS}.log"
files=$(wc -l < "$UNIT_DIR/files.txt")
bytes=$(while IFS= read -r f; do stat -c%s "$DOWNLOAD_DIR/$f" 2>/dev/null; done \
        < "$UNIT_DIR/files.txt" | awk '{s+=$1} END {printf "%d", s+0}')

echo "=== upload_unit: $UNIT ==="
echo "src  : $DOWNLOAD_DIR"
echo "files: $files file(s) — $(awk -v b="$bytes" 'BEGIN{printf "%.2f GiB", b/1073741824}') (theo files.txt)"
echo "dest : $REMOTE"
echo "log  : $LOG"

args=(copy "$DOWNLOAD_DIR" "$REMOTE" --files-from "$UNIT_DIR/files.txt"
      --checksum --transfers "$TRANSFERS" --drive-chunk-size 64M
      --retries 5 --low-level-retries 20 --stats 60s --stats-one-line
      --log-level INFO --log-file "$LOG")
[ "$DRY" = "1" ] && { echo "--- DRY RUN ---"; args+=(--dry-run); }

rclone "${args[@]}"; rc=$?
if [ "$rc" -ne 0 ]; then
  echo "ERROR: rclone exit $rc — xem $LOG. Chạy lại lệnh này để resume."
  exit "$rc"
fi

echo "--- upload metadata của unit (MANIFEST/SHA256SUMS/README/...) ---"
rclone copy "$UNIT_DIR" "$REMOTE" --exclude ".hf_upload_state.json" \
  --checksum --retries 5 --low-level-retries 20 \
  --log-level INFO --log-file "$LOG" || { echo "ERROR metadata upload"; exit 1; }

echo
echo "Xong. BƯỚC BẮT BUỘC — verify trước khi báo user xoá local:"
echo "  ./sync/verify_unit.sh $UNIT --remote $REMOTE"
