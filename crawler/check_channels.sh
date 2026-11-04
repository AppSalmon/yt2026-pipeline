#! /usr/bin/bash
#
# check_channels.sh — pre-flight: kiểm tra từng kênh trong danh sách có TỒN TẠI
# và có video công khai hay không, TRƯỚC khi chạy crawl lớn.
#
# Vì sao cần: danh sách sinh bằng discover_channels.py có thể chứa kênh đã xoá/đổi tên
# (đã gặp thật: UChyaqT2aCXMCjpk163PUpLg → "This channel does not exist"). Nếu để tới lúc
# crawl, mỗi kênh chết sẽ tốn retry + backoff 30/60s một cách vô ích.
#
# Usage:
#   ./check_channels.sh [channels file] [output TSV] [sleep giữa các kênh]
#   ./check_channels.sh channels.txt /tmp/check.tsv 0.7
#
# Đặc điểm:
#   * chỉ 1 request/kênh (--flat-playlist --playlist-items 1) — KHÔNG tải media
#   * TSV: status<TAB>handle<TAB>detail<TAB>name
#   * in tổng kết + exit 1 nếu có kênh FAIL
set -uo pipefail
export LC_ALL=C
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHANNELS_FILE=${1:-$SCRIPT_DIR/channels.txt}
OUT=${2:-/tmp/check_channels_$(date +%Y%m%d_%H%M%S).tsv}
SLEEP=${3:-0.7}

yt_dlp() { command -v yt-dlp >/dev/null 2>&1 && command yt-dlp "$@" || "$HOME/.local/bin/yt-dlp" "$@"; }

[ -s "$CHANNELS_FILE" ] || { echo "ERROR: không đọc được $CHANNELS_FILE"; exit 1; }

total=0; ok=0; fail=0
: > "$OUT"
out=$(mktemp); err=$(mktemp)
while IFS=$'\t' read -r name handle || [ -n "$name" ]; do
  case "$name" in ""|\#*) continue;; esac
  [ -n "${handle:-}" ] || continue
  total=$((total + 1))
  tabs_ok=""; last_reason=""
  for tab in videos shorts streams; do
    yt_dlp --flat-playlist --playlist-items 1 --no-warnings --ignore-config \
      --print "%(id)s" "https://www.youtube.com/${handle}/${tab}" >"$out" 2>"$err"
    rc=$?
    first=$(head -1 "$out")
    if [ "$rc" -eq 0 ] && [ -n "$first" ]; then
      tabs_ok="${tabs_ok}${tabs_ok:+,}${tab}"
    else
      last_reason=$(grep -m1 -oE 'This channel does not exist|does not have a videos tab|HTTP Error [0-9]+|This video is unavailable|Sign in to confirm|Private video|terminated|not available' "$err" || true)
      [ -n "$last_reason" ] || last_reason="rc=$rc"
    fi
    sleep 0.3
  done
  if [ -n "$tabs_ok" ]; then
    ok=$((ok + 1))
    printf 'OK\t%s\ttabs=%s\t%s\n' "$handle" "$tabs_ok" "$name" >> "$OUT"
    echo "OK   ${handle}  (tabs: ${tabs_ok})"
  else
    fail=$((fail + 1))
    printf 'FAIL\t%s\t%s\t%s\n' "$handle" "$last_reason" "$name" >> "$OUT"
    echo "FAIL ${handle}  -> ${last_reason}"
  fi
  sleep "$SLEEP"
done < "$CHANNELS_FILE"
rm -f "$out" "$err"

echo
echo "=== check_channels: $total kênh — OK=$ok FAIL=$fail ==="
echo "chi tiết: $OUT"
if [ "$fail" -gt 0 ]; then
  echo "kênh lỗi (nên loại khỏi channels.txt trước khi crawl lớn):"
  awk -F'\t' '$1=="FAIL" {printf "  %-34s %-40s %s\n", $2, $3, $4}' "$OUT"
  exit 1
fi

