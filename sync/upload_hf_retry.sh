#! /usr/bin/bash
#
# upload_hf_retry.sh — chạy upload HuggingFace trong VÒNG LẶP có backoff.
#
# Vì sao cần: gói HF FREE chỉ có **1.000 API request / 5 phút** (docs: hub/rate-limits;
# PRO là 2.500). Upload ~42.000 file với num_workers=8 vượt hạn mức hàng nghìn lần
# ⇒ 429 ⇒ `upload_large_folder` dừng sau 8 lỗi liên tiếp. Giải pháp miễn phí:
#   1) giảm --num-workers (ít request/giây hơn)
#   2) lỗi thì ngủ đủ lâu cho cửa sổ 5 phút reset rồi chạy lại
# Mỗi lần chạy đều RESUME: chunk đã xong bị bỏ qua (state <unit>/.hf_upload_state.json
# + cache upload_large_folder của huggingface_hub) ⇒ luôn tiến về phía trước.
#
# Usage:
#   ./sync/upload_hf_retry.sh <unit> [--repo <user>/<unit>] [--workers 2] [--max-try 40] [--sleep 600]
#   NUM_WORKERS=2 MAX_TRY=40 SLEEP_ON_ERROR=600 ./sync/upload_hf_retry.sh <unit>
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
# shellcheck source=../config.env
[ -f "$PIPELINE_DIR/config.env" ] && . "$PIPELINE_DIR/config.env"
DATA_ROOT=${DATA_ROOT:-$HOME/data}
DATASET_DIR=${DATASET_DIR:-$DATA_ROOT/dataset}

UNIT=""
REPO=""
WORKERS=${NUM_WORKERS:-2}
MAX_TRY=${MAX_TRY:-40}
SLEEP=${SLEEP_ON_ERROR:-600}
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=$2; shift 2 ;;
    --workers) WORKERS=$2; shift 2 ;;
    --max-try) MAX_TRY=$2; shift 2 ;;
    --sleep) SLEEP=$2; shift 2 ;;
    -*) echo "unknown option: $1"; exit 1 ;;
    *) UNIT=$1; shift ;;
  esac
done
if [ -z "$UNIT" ]; then
  echo "Usage: $0 <unit> [--repo <user>/<unit>] [--workers N] [--max-try N] [--sleep S]"
  exit 1
fi

LOG_DIR="$DATASET_DIR/_logs"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/upload_hf_${UNIT}_retry_$(date +%Y%m%d_%H%M%S).log"
export HF_LOG_FILE="$LOG"
STATE="$DATASET_DIR/units/$UNIT/.hf_upload_state.json"

echo "log      : $LOG"
echo "unit     : $UNIT   repo=${REPO:-<auto>}"
echo "workers  : $WORKERS  max_try=$MAX_TRY  sleep=${SLEEP}s"
echo

for i in $(seq 1 "$MAX_TRY"); do
  done_chunks=$(python3 -c "
import json,sys
try:
    d=json.load(open('$STATE')); print(len(d.get('chunks_done',[])))
except Exception: print(0)" 2>/dev/null)
  echo "===== attempt $i/$MAX_TRY  $(date -Is)  · chunk đã xong: $done_chunks =====" >> "$LOG"
  echo "attempt $i/$MAX_TRY  $(date -Is)  · chunk xong: $done_chunks"
  args=("$UNIT" --num-workers "$WORKERS")
  [ -n "$REPO" ] && args+=(--repo "$REPO")
  "$SCRIPT_DIR/upload_unit_hf.sh" "${args[@]}" >> "$LOG" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "XONG sau $i lần thử  $(date -Is)" | tee -a "$LOG"
    exit 0
  fi
  echo "attempt $i thất bại (rc=$rc) — ngủ ${SLEEP}s cho cửa sổ 5 phút của HF reset" >> "$LOG"
  echo "  ↳ ngủ ${SLEEP}s rồi thử lại (chunk xong vẫn được giữ)"
  sleep "$SLEEP"
done

echo "HẾT SỐ LẦN THỬ ($MAX_TRY) — xem $LOG" | tee -a "$LOG"
exit 1