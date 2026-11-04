#! /usr/bin/bash
#
# Orchestrator: crawl MANY channels in parallel (stage: audio-only acquisition).
# Wraps download_from_youtube.sh with concurrency, per-channel retry and a run summary.
#
# Usage:
#   ./crawl_all.sh [channels file] [download dir] [jobs]
#
# Data location: the download ROOT is resolved to an absolute path and must live
# OUTSIDE the repo. Order of precedence: 2nd positional arg > $DOWNLOAD_DIR
# (env or ../config.env) > built-in default. A repo-inside path aborts the run
# unless ALLOW_IN_REPO_DOWNLOAD=1.
#
# Env (on top of all download_from_youtube.sh vars: AUDIO_FORMAT, MAX_VIDEOS...):
#   JOBS=2             channels processed concurrently (keep low to avoid 429)
#   RETRY_CHANNEL=2    attempts per channel (30s, 60s, ... backoff)
#   BATCH_LABEL=...    label for log/summary files (default: timestamp)
#   MIN_FREE_GB=50     warn + skip crawl when staging free space drops below this
#   MIN_FREE_HARD_GB=20 abort when staging free space drops below this
#
# Output:
#   log/run_<label>_summary.csv -> channel_name,channel,status,rc,new_audio,new_hours,new_bytes
#   log/<channel>_{videos,shorts,streams}.log -> raw yt-dlp logs
#   (log/ = crawler/log, resolved from THIS script's directory, never from the CWD)
set -uo pipefail
export LC_ALL=C   # keep decimal points in awk/csv output stable

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

# Single source of truth for data paths (caller-exported env vars still win).
# shellcheck source=../config.env
if [ -f "$PIPELINE_DIR/config.env" ]; then
  . "$PIPELINE_DIR/config.env"
fi
ALLOW_IN_REPO_DOWNLOAD="${ALLOW_IN_REPO_DOWNLOAD:-0}"
MIN_FREE_GB="${MIN_FREE_GB:-50}"
MIN_FREE_HARD_GB="${MIN_FREE_HARD_GB:-20}"

CHANNELS_FILE=${1:-$SCRIPT_DIR/channels.txt}
DOWNLOAD_DIR=${2:-${DOWNLOAD_DIR:-$DATA_ROOT/download_from_youtube}}
JOBS=${3:-${JOBS:-2}}
RETRY_CHANNEL=${RETRY_CHANNEL:-2}
BATCH_LABEL=${BATCH_LABEL:-$(date +%Y%m%d_%H%M%S)}

# Resolve to an absolute path ONCE here: run_one() cds into SCRIPT_DIR, so any
# relative path would otherwise be interpreted twice against different bases.
DOWNLOAD_DIR=$(realpath -m "$DOWNLOAD_DIR")

# --- guard: crawl data must NOT live inside the repo --------------------------
case "$(realpath -m --relative-to="$PIPELINE_DIR" "$DOWNLOAD_DIR")" in
  ..*|/*) ;;                                      # outside the repo -> OK
  *)
    if [ "$ALLOW_IN_REPO_DOWNLOAD" = "1" ]; then
      echo "WARNING: download dir is INSIDE the repo ($DOWNLOAD_DIR) — allowed by ALLOW_IN_REPO_DOWNLOAD=1"
    else
      echo "ERROR: refusing to store crawl data inside the repo: $DOWNLOAD_DIR"
      echo "       Fix: export DOWNLOAD_DIR=<path outside the repo> (see $PIPELINE_DIR/config.env)"
      echo "       Or deliberately override with ALLOW_IN_REPO_DOWNLOAD=1."
      exit 2
    fi
    ;;
esac

# --- guard: staging free space (50k hours would never fit on one 774GB disk) --
free_gb=$(df -Pk "$(dirname "$DOWNLOAD_DIR")" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')
if [ -z "$free_gb" ]; then
  echo "WARNING: could not read free space for $DOWNLOAD_DIR (df failed) — continuing"
else
  if [ "$free_gb" -lt "$MIN_FREE_HARD_GB" ]; then
    echo "ERROR: staging free space ${free_gb}GB < MIN_FREE_HARD_GB=${MIN_FREE_HARD_GB}GB — aborting."
    echo "       Upload+verify+cleanup a batch before crawling more (sync/cleanup_local.sh)."
    exit 3
  fi
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "WARNING: staging free space ${free_gb}GB < MIN_FREE_GB=${MIN_FREE_GB}GB — consider uploading a batch soon."
  fi
fi

LOG_DIR="$SCRIPT_DIR/log"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
SUMMARY="$LOG_DIR/run_${BATCH_LABEL}_summary.csv"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

channel_name_of() { local ch=${1##*/}; printf '%s' "${ch#@}"; }

run_one() {
  local chfile=$1 idx=$2
  local channel name dir stamp rc=1 attempt
  local new_audio=0 new_hours=0 new_bytes=0 status=fail
  channel=$(awk -F'\t' '{print $2}' "$chfile")
  name=$(channel_name_of "$channel")
  dir="$DOWNLOAD_DIR/$name"
  stamp="$TMP_DIR/stamp_$idx"; : > "$stamp"

  echo "[$(date +%H:%M:%S)] START $name"
  for ((attempt = 1; attempt <= RETRY_CHANNEL; attempt++)); do
    if (cd "$SCRIPT_DIR" && ./download_from_youtube.sh "$chfile" "$DOWNLOAD_DIR"); then
      rc=0; break
    else
      # NOTE: `rc=$?` AFTER an if/fi yields 0 in bash (the if-statement's own status),
      # which silently turned failing channels into status=ok. Capture it inside `else`.
      rc=$?
    fi
    echo "[$(date +%H:%M:%S)] attempt $attempt failed (rc=$rc) for $name; backoff..."
    sleep $((attempt * 30))
  done

  if [ -d "$dir" ]; then
    local newlist="$TMP_DIR/new_$idx.txt"
    find "$dir" -type f -newer "$stamp" \
      \( -name '*.webm' -o -name '*.m4a' -o -name '*.mp3' -o -name '*.opus' -o -name '*.ogg' \) \
      > "$newlist" 2>/dev/null || true
    new_audio=$(wc -l < "$newlist")
    if [ "$new_audio" -gt 0 ]; then
      new_hours=$(sed 's|.*/||' "$newlist" | awk -F'_' \
        '{n=$NF; sub(/\..*$/, "", n); if (n ~ /^[0-9]+$/) s+=n} END {printf "%.2f", (s+0)/3600}')
      # -d '\n' is REQUIRED: YouTube titles contain spaces, and plain xargs would split
      # such a path into several arguments -> stat fails -> new_bytes silently became 0.
      new_bytes=$(xargs -r -d '\n' stat -c%s < "$newlist" | awk '{s+=$1} END {printf "%d", s+0}')
    fi
  fi

  if [ "$rc" -eq 0 ]; then status=ok; elif [ "$new_audio" -gt 0 ]; then status=partial; fi
  printf '%s,%s,%s,%s,%s,%s,%s\n' \
    "$name" "$channel" "$status" "$rc" "$new_audio" "$new_hours" "$new_bytes" \
    > "$TMP_DIR/summary_$idx.csv"
  echo "[$(date +%H:%M:%S)] DONE $name status=$status audio=$new_audio hours=$new_hours rc=$rc"
}

idx=0
while read -r rows || [ -n "$rows" ]; do
  case "$rows" in ""|\#*) continue;; esac
  printf '%s\n' "$rows" > "$TMP_DIR/ch_$idx.txt"
  idx=$((idx + 1))
done < "$CHANNELS_FILE"

if [ "$idx" -eq 0 ]; then
  echo "ERROR: no usable channels found in $CHANNELS_FILE"
  exit 1
fi
echo "Channels: $idx | jobs: $JOBS | retries/channel: $RETRY_CHANNEL | label: $BATCH_LABEL"
echo "Download root: $DOWNLOAD_DIR (free ${free_gb:-?}GB) | logs: $LOG_DIR"

running=0
for ((i = 0; i < idx; i++)); do
  run_one "$TMP_DIR/ch_$i.txt" "$i" &
  running=$((running + 1))
  if [ "$running" -ge "$JOBS" ]; then
    wait -n
    running=$((running - 1))
  fi
done
wait

printf 'channel_name,channel,status,rc,new_audio,new_hours,new_bytes\n' > "$SUMMARY"
for ((i = 0; i < idx; i++)); do
  cat "$TMP_DIR/summary_$i.csv" >> "$SUMMARY" 2>/dev/null || true
done
awk -F, 'NR>1 {a+=$5; h+=$6; b+=$7; if ($3=="ok") ok++; if ($3=="fail") bad++}
         END {printf "TOTAL: %d channels (ok=%d fail=%d), %d new audio files, %.2f hours, %.2f GB\n",
                      NR-1, ok+0, bad+0, a+0, h+0, b/1073741824}' "$SUMMARY"
echo "Summary: $SUMMARY"