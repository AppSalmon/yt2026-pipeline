#! /usr/bin/bash
#
# estimate_channels.sh — đo quy mô kênh TRƯỚC khi crawl (không tải media).
#
# Dùng --flat-playlist: mỗi kênh CHỈ 1 request, trả về mọi video của tab /videos kèm
# duration (nhưng KHÔNG có upload_date/timestamp → đây là UPPER BOUND mọi năm; tập 2026
# là tập con của con số này).
#
# Usage:
#   ./estimate_channels.sh [channels file] [output TSV] [MB_per_hour]
#   ./estimate_channels.sh channels.txt /tmp/estimate.tsv 50
#
# Output TSV: handle<TAB>n_videos<TAB>hours_upper<TAB>gb_upper<TAB>name
# In tổng kết + ước lượng dung lượng (dùng MB/giờ thực đo từ pilot, mặc định 50).
set -uo pipefail
export LC_ALL=C
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHANNELS_FILE=${1:-$SCRIPT_DIR/channels.txt}
OUT=${2:-/tmp/estimate_channels_$(date +%Y%m%d_%H%M%S).tsv}
MB_PER_HOUR=${3:-50}
MAX_ITEMS=${MAX_ITEMS:-200}     # chỉ đo N video MỚI NHẤT/kênh (2026 ≈ 266 ngày; tránh kênh tin tức hàng nghìn video)
SLEEP=${SLEEP:-0.5}

yt_dlp() { command -v yt-dlp >/dev/null 2>&1 && command yt-dlp "$@" || "$HOME/.local/bin/yt-dlp" "$@"; }
[ -s "$CHANNELS_FILE" ] || { echo "ERROR: không đọc được $CHANNELS_FILE"; exit 1; }

tmp=$(mktemp)
: > "$OUT"
total_videos=0; total_hours=0
while IFS=$'\t' read -r name handle || [ -n "$name" ]; do
  case "$name" in ""|\#*) continue;; esac
  [ -n "${handle:-}" ] || continue
  yt_dlp --flat-playlist --no-warnings --ignore-config --playlist-items "1:${MAX_ITEMS}" \
    --print "%(duration)s" "https://www.youtube.com/${handle}/videos" > "$tmp" 2>/dev/null
  read -r n hours < <(awk '{n++; if ($1 ~ /^[0-9.]+$/) s+=$1} END {printf "%d %.2f", n, s/3600}' "$tmp")
  gb=$(awk -v h="${hours:-0}" -v m="$MB_PER_HOUR" 'BEGIN {printf "%.2f", h*m/1024}')
  printf '%s\t%s\t%s\t%s\t%s\n' "$handle" "${n:-0}" "${hours:-0}" "$gb" "$name" >> "$OUT"
  printf '%-34s videos=%-5s hours=%-9s GB~%-7s %s\n' "$handle" "${n:-0}" "${hours:-0}" "$gb" "$name"
  total_videos=$((total_videos + ${n:-0}))
  total_hours=$(awk -v a="$total_hours" -v b="${hours:-0}" 'BEGIN {print a+b}')
  sleep "$SLEEP"
done < "$CHANNELS_FILE"
rm -f "$tmp"

echo
echo "=== estimate_channels (UPPER BOUND, mọi năm) ==="
echo "kênh: $(wc -l < "$OUT") | video: $total_videos | giờ: $(awk -v h="$total_hours" 'BEGIN{printf "%.1f", h}')"
awk -v m="$MB_PER_HOUR" -v h="$total_hours" 'BEGIN {printf "dung lượng tối đa nếu tải hết: %.1f GB (ở %s MB/giờ)\n", h*m/1024, m}' 
echo "TSV: $OUT"
