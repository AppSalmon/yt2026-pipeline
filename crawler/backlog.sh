#!/usr/bin/bash
#
# backlog.sh — đo "kho 2026" còn lại của mỗi kênh MÀ **KHÔNG TẢI MEDIA**.
#
# Vì sao cần: `--max-downloads` (MAX_VIDEOS) dừng giữa dòng, nên "đã tải 20 file" KHÔNG cho
# biết kênh còn bao nhiêu video 2026. Script này dùng `--flat-playlist` +
# `--extractor-args youtubetab:approximate_date` (yt-dlp trả NGÀY UPLOAD GẦN ĐÚNG) để đếm
# số mục trong cửa sổ >= MIN_UPLOAD_DATE trong N mục đầu của tab — chỉ 1-2 request/kênh.
#
# ⚠️ Đã kiểm chứng:
#   * CHỈ dùng cho tab `videos` và `streams`. Tab `shorts` ở chế độ flat thường bị YouTube
#     trả "This channel does not exist" (lỗi phía YouTube) → mặc định bỏ qua shorts.
#   * Ngày là GẦN ĐÚNG (làm tròn theo ngày) — dùng để ước lượng/xếp hạng, không phải số tuyệt đối.
#   * Khi WALK_LIMIT bật, log crawl hiện `Downloading item X of N` với N = BOUND (không phải
#     kích thước kênh) — muốn biết kích thước thật thì dùng script này.
#
# Usage:
#   ./backlog.sh [channels file] [số mục quét mỗi tab] [tab ...]
#   ./backlog.sh crawler/channels.txt 200 videos streams
#
# Output: log/backlog_<ts>.tsv + bảng in ra màn hình:
#   kênh | tab | quét | trong-2026 | đã-tải | còn-lại
set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
# shellcheck source=../config.env
if [ -f "$PIPELINE_DIR/config.env" ]; then . "$PIPELINE_DIR/config.env"; fi
LOG_DIR="$SCRIPT_DIR/log"
mkdir -p "$LOG_DIR"

CHANNELS=${1:-$SCRIPT_DIR/channels.txt}
LIMIT=${2:-120}
if [ "$#" -ge 2 ]; then shift 2; else shift "$#"; fi
TABS=${*:-videos streams}

# MIN_UPLOAD_DATE (YYYYMMDD) -> epoch giây, để so với %(timestamp)s
d=${MIN_UPLOAD_DATE:-20260101}
EPOCH_MIN=$(date -d "${d:0:4}-${d:4:2}-${d:6:2}" +%s 2>/dev/null) || EPOCH_MIN=1767225600

OUT="$LOG_DIR/backlog_$(date +%Y%m%d_%H%M%S).tsv"
printf 'channel\ttab\tscanned\tin_window\thave\tremaining\n' > "$OUT"
echo "channels : $CHANNELS"
echo "tabs     : $TABS   (quét $LIMIT mục đầu mỗi tab)"
echo "window   : >= $d (epoch $EPOCH_MIN)"
echo "output   : $OUT"
echo

tot_rem=0
while IFS=$'\t' read -r name handle || [ -n "${name:-}" ]; do
  case "$name" in ""|\#*) continue;; esac
  [ -n "${handle:-}" ] || continue
  cname=${handle##*/}
  cname=${cname#@}
  for tab in $TABS; do
    data=$(yt-dlp --flat-playlist --playlist-items "1:$LIMIT" \
        --extractor-args 'youtubetab:approximate_date' \
        --no-warnings --ignore-config --print '%(timestamp)s' \
        "https://www.youtube.com/${handle}/${tab}" 2>/dev/null)
    scanned=$(printf '%s\n' "$data" | grep -cE '^[0-9]+$')
    in_window=$(printf '%s\n' "$data" | awk -v c="$EPOCH_MIN" '$1+0 >= c' | wc -l)
    arch="$LOG_DIR/audios_${cname}_${tab}.txt"
    have=0
    [ -f "$arch" ] && have=$(wc -l < "$arch")
    remaining=$(( in_window - have ))
    [ "$remaining" -lt 0 ] && remaining=0
    tot_rem=$((tot_rem + remaining))
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$tab" "$scanned" "$in_window" "$have" "$remaining" >> "$OUT"
    printf '  %-30s %-8s quét=%-4s 2026=%-4s đã-tải=%-4s còn-lại=%s\n' \
      "$name" "$tab" "$scanned" "$in_window" "$have" "$remaining"
    sleep 0.5
  done
done < "$CHANNELS"

echo
echo "TỔNG còn-lại (theo các tab đã quét, trong $LIMIT mục đầu): $tot_rem mục"
echo "Ghi chú: chỉ là GIỚI HẠN DƯỚI — kênh có thể còn nhiều hơn ở các mục sâu hơn."
