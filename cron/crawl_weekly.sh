#! /usr/bin/bash
#
# W7 — crawl_weekly.sh: driver chạy KHÔNG GIÁM SÁT cho 1 chu kỳ.
#
# Chuỗi bước (dừng đúng chỗ khi có lỗi nghiêm trọng):
#   1. crawl_all.sh            (yt-dlp, không cookies — xem PROJECT_STATUS.md §15)
#   2. build_index.py --strict (audit 2026: vi phạm => exit 1, KHÔNG đóng gói)
#   3. audio_qc.py             (language guard + file hỏng -> exclude.txt)
#   4. make_batch.py --verify  (đóng gói batch; tự bỏ qua nếu không có video mới)
#   5. corpus_ledger.py append (ghi sổ cái)
#   6. [--with-upload] upload -> verify -> cleanup (chỉ batch vừa verify PASS)
#
# Usage:
#   ./crawl_weekly.sh                     # crawl + QC + đóng gói (KHÔNG upload)
#   ./crawl_weekly.sh --with-upload       # thêm chuỗi upload (cần rclone đã authorize)
#   ./crawl_weekly.sh --dry-run           # chỉ in kế hoạch, không chạy gì
#   ./crawl_weekly.sh --limit-gb 350 --max-upload 1
#
# Env: mọi biến trong config.env + JOBS (kênh song song), MAX_VIDEOS, RETRY_CHANNEL,
#      HARDLINK=1|0 (dựng hardlink tree), LIMIT_GB, MAX_UPLOAD_PER_RUN.
#
# crontab (thứ Hai 03:00) — cron KHÔNG có PATH của shell tương tác nên phải tự set:
#   0 3 * * 1 cd <repo-dir>/cron \
#     && PATH="$HOME/.local/bin:$PATH" ./crawl_weekly.sh --with-upload >> ../crawler/log/cron.log 2>&1
set -uo pipefail
export LC_ALL=C
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
# shellcheck source=../config.env
[ -f "$PIPELINE_DIR/config.env" ] && . "$PIPELINE_DIR/config.env"
DATA_ROOT=${DATA_ROOT:-$HOME/data}
DOWNLOAD_DIR=${DOWNLOAD_DIR:-$DATA_ROOT/download_from_youtube}
DATASET_DIR=${DATASET_DIR:-$DATA_ROOT/dataset}
LEDGER_FILE=${LEDGER_FILE:-$DATA_ROOT/corpus_ledger.jsonl}
GDRIVE_REMOTE=${GDRIVE_REMOTE:-gdrive:corpus}
MIN_FREE_GB=${MIN_FREE_GB:-50}
MIN_FREE_HARD_GB=${MIN_FREE_HARD_GB:-20}

CHANNELS_FILE=${CHANNELS_FILE:-$PIPELINE_DIR/crawler/channels.txt}
JOBS=${JOBS:-2}
LIMIT_GB=${LIMIT_GB:-350}
MAX_UPLOAD_PER_RUN=${MAX_UPLOAD_PER_RUN:-1}
HARDLINK=${HARDLINK:-1}
WITH_UPLOAD=0
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --with-upload) WITH_UPLOAD=1; shift ;;
    --no-upload) WITH_UPLOAD=0; shift ;;
    --limit-gb) LIMIT_GB=$2; shift 2 ;;
    --max-upload) MAX_UPLOAD_PER_RUN=$2; shift 2 ;;
    --jobs) JOBS=$2; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

LOG_DIR="$PIPELINE_DIR/crawler/log"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$DATASET_DIR"
LOG="$LOG_DIR/cron_$(date +%Y%m%d_%H%M%S).log"
FAILED=()

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
step() {                     # step <name> <cmd...>
  local name=$1; shift
  local rc
  say "STEP $name: $*"
  if [ "$DRY_RUN" = "1" ]; then say "  (dry-run, skipped)"; return 0; fi
  if "$@" >>"$LOG" 2>&1; then
    say "  OK $name"
    return 0
  else
    # NOTE: `rc=$?` AFTER an if/fi is always 0 in bash (the if-statement's own status),
    # which would report FAIL with rc=0 and swallow the real failure code.
    rc=$?
  fi
  say "  FAIL $name (rc=$rc) — xem $LOG"
  FAILED+=("$name")
  return "$rc"
}

say "================ crawl_weekly start (with_upload=$WITH_UPLOAD dry_run=$DRY_RUN) ================"
say "pipeline=$PIPELINE_DIR"
say "download=$DOWNLOAD_DIR  dataset=$DATASET_DIR  ledger=$LEDGER_FILE"
say "channels=$CHANNELS_FILE  jobs=$JOBS  limit_gb=$LIMIT_GB  hardlink=$HARDLINK"

# ---------------------------------------------------------------- preflight checks
if [ ! -s "$CHANNELS_FILE" ]; then
  say "ERROR: channels file rỗng/không tồn tại: $CHANNELS_FILE — dừng."
  exit 1
fi
usable=$(grep -cvE '^\s*(#|$)' "$CHANNELS_FILE" || true)
if [ "${usable:-0}" -eq 0 ]; then
  say "ERROR: $CHANNELS_FILE không có kênh nào dùng được (chỉ có comment/dòng trống) — dừng."
  exit 1
fi
say "channels usable: $usable"

free_gb=$(df -Pk "$DOWNLOAD_DIR" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')
if [ -n "$free_gb" ]; then
  say "staging free: ${free_gb}GB (warn<$MIN_FREE_GB abort<$MIN_FREE_HARD_GB)"
  if [ "$free_gb" -lt "$MIN_FREE_HARD_GB" ]; then
    say "ERROR: hết chỗ staging — upload+cleanup batch cũ trước khi crawl tiếp."
    exit 3
  fi
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    say "WARNING: staging sắp đầy — nên upload batch sớm."
  fi
else
  say "WARNING: không đọc được dung lượng trống của $DOWNLOAD_DIR"
fi

# ---------------------------------------------------------------------- 1) crawl
step crawl env BATCH_LABEL="cron_$(date +%Y%m%d)" \
  "$PIPELINE_DIR/crawler/crawl_all.sh" "$CHANNELS_FILE" "$DOWNLOAD_DIR" "$JOBS"

# --------------------------------------------------- 2) audit 2026 (hard gate)
AUDIT_OK=1
if ! step audit python3 "$PIPELINE_DIR/metadata/build_index.py" --strict; then
  AUDIT_OK=0
  say "WARNING: audit 2026 FAIL — KHÔNG đóng gói batch (xử lý vi phạm bằng tay trước)."
fi

# -------------------------------------------------------------------------- 3) QC
step qc python3 "$PIPELINE_DIR/metadata/audio_qc.py"

# ------------------------------------------- 4) package (skip if nothing new)
NEW=1
if [ "$DRY_RUN" = "0" ] && [ "$AUDIT_OK" = "1" ]; then
  probe=$(python3 "$PIPELINE_DIR/metadata/make_batch.py" --dry-run 2>&1 | tee -a "$LOG" \
    | grep -E '^candidates' || true)
  say "  probe: ${probe:-<no output>}"
  case "$probe" in *"0 files"*) NEW=0 ;; esac
fi
if [ "$DRY_RUN" = "1" ]; then
  say "STEP package: make_batch.py --limit-gb $LIMIT_GB --verify (dry-run, skipped)"
elif [ "$AUDIT_OK" = "0" ]; then
  say "STEP package: skipped (audit failed)"
elif [ "$NEW" = "0" ]; then
  say "STEP package: skipped (không có video mới để đóng gói)"
else
  batch_args=(--limit-gb "$LIMIT_GB" --verify)
  [ "$HARDLINK" = "1" ] && batch_args+=(--hardlink)
  step package python3 "$PIPELINE_DIR/metadata/make_batch.py" "${batch_args[@]}"
fi

# ------------------------------------------------------------------ 5) ledger append
step ledger-append python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" append

# --------------------------------------------------- 6) upload chain (opt-in only)
if [ "$WITH_UPLOAD" = "1" ]; then
  if ! command -v rclone >/dev/null 2>&1; then
    say "WARNING: --with-upload nhưng rclone chưa cài → bỏ qua (chạy sync/install_rclone.sh)."
  elif [ "$DRY_RUN" = "1" ]; then
    say "STEP upload chain: (dry-run, skipped)"
  else
    pending=$(python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" pending 2>>"$LOG" || true)
    if [ -z "$pending" ]; then
      say "STEP upload: không có batch nào đang chờ upload."
    fi
    count=0
    for batch in $pending; do
      if [ "$count" -ge "$MAX_UPLOAD_PER_RUN" ]; then
        say "  (đạt MAX_UPLOAD_PER_RUN=$MAX_UPLOAD_PER_RUN — batch còn lại để lần sau, giới hạn ~750GB/ngày)"
        break
      fi
      count=$((count + 1))
      say "--- upload chain: $batch ---"
      if step "upload:$batch" "$SCRIPT_DIR/../sync/upload_batch.sh" "$batch" --remote "$GDRIVE_REMOTE"; then
        if step "verify:$batch" "$SCRIPT_DIR/../sync/verify_remote.sh" "$batch" --remote "$GDRIVE_REMOTE"; then
          step "cleanup:$batch" "$SCRIPT_DIR/../sync/cleanup_local.sh" "$batch" --yes
        fi
      fi
    done
    step ledger-push python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" push \
      --remote "$GDRIVE_REMOTE/_meta"
  fi
fi

# ---------------------------------------------------------------------- summary
say "================ summary ================"
if [ "$DRY_RUN" = "1" ]; then
  say "dry-run: không có gì được thực thi."
else
  python3 "$PIPELINE_DIR/metadata/corpus_ledger.py" report 2>&1 | tee -a "$LOG" | tail -18
  if [ "${#FAILED[@]}" -gt 0 ]; then
    say "FAILED steps: ${FAILED[*]}"
    say "log: $LOG"
    say "================ crawl_weekly end (rc=1) ================"
    exit 1
  fi
  say "all steps OK"
fi
say "log: $LOG"
say "================ crawl_weekly end (rc=0) ================"
