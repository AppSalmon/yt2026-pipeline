#! /usr/bin/bash
#
# watch_crawl.sh — watchdog cho crawl chạy trong tmux (W7).
#
# Vì sao cần: job crawl trong tmux KHÔNG tự báo khi chết (reboot / OOM / bị kill).
# Script này kiểm tra session tmux còn sống không; nếu chết thì khởi động lại ĐÚNG lệnh cũ
# (resume an toàn nhờ yt-dlp `--download-archive` chống trùng — không tải lại video đã có).
#
# Usage:
#   cron/watch_crawl.sh                 # mặc định: session ytb-2511, channels_2509.txt, JOBS=2
#   SESSION=ytb-XXXX CHANNELS=crawler/channels_XXXX.txt JOBS=2 LABEL=crawlXXXX cron/watch_crawl.sh
#
# Cài crontab (xem cron/README.md):
#   @reboot      <repo-dir>/cron/watch_crawl.sh >> <repo-dir>/crawler/log/watch_crawl.log 2>&1
#   */15 * * * * <repo-dir>/cron/watch_crawl.sh >> <repo-dir>/crawler/log/watch_crawl.log 2>&1
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
# shellcheck source=../config.env
[ -f "$PIPELINE_DIR/config.env" ] && . "$PIPELINE_DIR/config.env"

SESSION=${SESSION:-ytb-2511}
CHANNELS=${CHANNELS:-crawler/channels_2509.txt}
JOBS=${JOBS:-2}
LABEL=${LABEL:-crawl2511}
FORCE=${FORCE:-0}

ts() { date -Is; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
  if [ "$FORCE" != "1" ]; then
    echo "[$(ts)] $SESSION đang chạy — OK"
    exit 0
  fi
  echo "[$(ts)] FORCE=1 — kill session $SESSION cũ"
  tmux kill-session -t "$SESSION" 2>/dev/null || true
fi

command -v tmux >/dev/null 2>&1 || { echo "[$(ts)] ERROR: tmux không có trong PATH"; exit 1; }

cd "$PIPELINE_DIR" || exit 1
LOG="crawler/log/${LABEL}_\$(date +%Y%m%d_%H%M%S).log"
CMD='export PATH="$HOME/.local/bin:$PATH"; '
CMD+="JOBS=1 SLEEP_REQUESTS=1 SLEEP_INTERVAL=6 MAX_SLEEP_INTERVAL=15 MAX_VIDEOS=50 SKIP_AFTER_ERRORS=30 "
CMD+="BATCH_LABEL=$LABEL ./crawler/crawl_all.sh $CHANNELS \"\" $JOBS 2>&1 | tee $LOG"

echo "[$(ts)] $SESSION KHÔNG sống — khởi động lại ($CHANNELS · JOBS=$JOBS · label=$LABEL)"
tmux new -d -s "$SESSION" "$CMD"
echo "[$(ts)] đã tạo lại session $SESSION"
