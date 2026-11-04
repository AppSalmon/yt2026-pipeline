#! /usr/bin/bash
#
# check_cookies.sh — quyết định một file cookies có DÙNG ĐƯỢC để tải MEDIA hay không.
#
# Bối cảnh (PROJECT_STATUS.md §15): cookie hợp lệ + đã login VẪN có thể bị YouTube chặn
# request media khi request đến từ IP datacenter ("The page needs to be reloaded").
# Kiểm tra "login OK" KHÔNG đủ — script này bắt buộc phải test TẢI THẬT vài giây audio.
#
# Usage:
#   ./check_cookies.sh [cookie file]          # mặc định: ./cookies.txt, rồi ./cookies/*.txt
# Env:
#   TEST_URL=<youtube watch url>   video dùng để test (mặc định: video VTV24 đã kiểm chứng)
#   KEEP_TMP=1                     giữ file audio test lại để bạn nghe thử
#
# Verdict (in ra dòng cuối):
#   ok (usable)          -> exit 0  ĐƯỢC PHÉP đặt COOKIES_FILE
#   invalid              -> exit 1  file sai định dạng / thiếu cookie đăng nhập
#   blocked              -> exit 2  media bị chặn (thường do IP datacenter) => KHÔNG dùng cookies
#   video-unusable       -> exit 3  test video/mạng lỗi (kể cả khi KHÔNG cookies) => không kết luận
set -uo pipefail
export LC_ALL=C

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COOKIE_FILE=${1:-}
if [ -z "$COOKIE_FILE" ]; then
  if [ -f "$SCRIPT_DIR/cookies.txt" ]; then
    COOKIE_FILE="$SCRIPT_DIR/cookies.txt"
  elif [ -d "$SCRIPT_DIR/cookies" ]; then
    mapfile -t _ck < <(find "$SCRIPT_DIR/cookies" -maxdepth 1 -type f -name '*.txt' 2>/dev/null | sort)
    [ "${#_ck[@]}" -ge 1 ] && COOKIE_FILE="${_ck[0]}"
  fi
fi
TEST_URL=${TEST_URL:-https://www.youtube.com/watch?v=yv3Lh2A9zuU}
KEEP_TMP=${KEEP_TMP:-0}
# medium opus track tiếng Việt với fallback, y như crawler thật
TEST_FORMAT='ba[language^=vi][acodec=opus][abr>=60]/ba[language^=vi][acodec=opus]/ba[language^=vi]/ba'

yt_dlp() { command -v yt-dlp >/dev/null 2>&1 && command yt-dlp "$@" || "$HOME/.local/bin/yt-dlp" "$@"; }

TMP_DIR=$(mktemp -d)
cleanup() { [ "$KEEP_TMP" = "1" ] || rm -rf "$TMP_DIR"; }
trap cleanup EXIT

echo "=== check_cookies.sh ==="
echo "cookie file : ${COOKIE_FILE:-(none)}"
echo "test url    : $TEST_URL"
echo "test format : $TEST_FORMAT"
echo

# ---------------------------------------------------------------- structural checks
if [ -z "$COOKIE_FILE" ] || [ ! -f "$COOKIE_FILE" ]; then
  echo "RESULT: cookie file not found (pass it as \$1, or put it in $SCRIPT_DIR/cookies/)"
  echo "VERDICT: invalid"
  exit 1
fi

head -1 "$COOKIE_FILE" | grep -q 'Netscape HTTP Cookie File' || {
  echo "RESULT: first line is not '# Netscape HTTP Cookie File' -> wrong format"
  echo "VERDICT: invalid"
  exit 1
}

youtube_cookies=$(grep -c 'youtube\.com' "$COOKIE_FILE" || true)
echo "cookies for .youtube.com : $youtube_cookies"
[ "${youtube_cookies:-0}" -ge 5 ] || echo "WARNING: suspiciously few YouTube cookies"

missing=""
for name in SID HSID SSID APISID SAPISID LOGIN_INFO; do
  grep -qE "(^|\t)${name}\t" "$COOKIE_FILE" || missing="$missing $name"
done
if [ -n "$missing" ]; then
  echo "WARNING: missing login cookie(s):$missing (session may be incomplete/logged out)"
else
  echo "login cookie set          : complete (SID/HSID/SSID/APISID/SAPISID/LOGIN_INFO)"
fi

expired=$(awk -F'\t' -v now="$(date +%s)" '$7 ~ /^[0-9]+$/ && $7 != 0 && $7 < now {c++} END {print c+0}' "$COOKIE_FILE")
echo "expired cookie count      : $expired"
echo

# ------------------------------------------------------- baseline (WITHOUT cookies)
echo "--- baseline: extract metadata WITHOUT cookies"
yt_dlp --simulate --no-warnings --print "%(id)s|%(language)s|%(format_id)s" \
  -f "$TEST_FORMAT" "$TEST_URL" >"$TMP_DIR/baseline.out" 2>"$TMP_DIR/baseline.err"
baseline_rc=$?
echo "baseline rc=$baseline_rc $(head -1 "$TMP_DIR/baseline.out" 2>/dev/null)"

# ------------------------------------------------------------- login/metadata check
echo
echo "--- metadata extraction WITH cookies"
yt_dlp --cookies "$COOKIE_FILE" --simulate --no-warnings \
  --print "%(id)s|%(language)s|%(format_id)s|%(duration)s" \
  -f "$TEST_FORMAT" "$TEST_URL" >"$TMP_DIR/with.out" 2>"$TMP_DIR/with.err"
with_rc=$?
echo "with-cookies rc=$with_rc $(head -1 "$TMP_DIR/with.out" 2>/dev/null)"
[ "$with_rc" -ne 0 ] && sed -n '1,3p' "$TMP_DIR/with.err"

# --------------------------------------------------------------- REAL media download
# The datacenter-IP block only shows up on MEDIA requests, so download a few seconds.
echo
echo "--- real media download (first 5s) WITH cookies"
yt_dlp --cookies "$COOKIE_FILE" --no-warnings --no-part \
  --download-sections '*0-5' -f "$TEST_FORMAT" \
  -o "$TMP_DIR/media_test.%(ext)s" "$TEST_URL" >"$TMP_DIR/media.out" 2>"$TMP_DIR/media.err"
media_rc=$?
echo "media rc=$media_rc"
media_file=$(find "$TMP_DIR" -type f -name 'media_test.*' | head -1)
if [ -n "$media_file" ]; then
  echo "downloaded : $(stat -c%s "$media_file") bytes -> $(basename "$media_file")"
else
  echo "downloaded : none"
  grep -iE 'needs to be reloaded|Sign in to confirm|not a bot|HTTP Error (403|429)|Forbidden' \
    "$TMP_DIR/media.err" | head -3
fi

# ------------------------------------------------------------------------ verdict
echo
if [ "$baseline_rc" -ne 0 ] && [ "$with_rc" -ne 0 ]; then
  echo "RESULT: test video unusable BOTH with and without cookies -> cannot judge cookies"
  echo "VERDICT: video-unusable"
  exit 3
fi
if [ -n "$media_file" ] && [ "$media_rc" -eq 0 ] && [ "$(stat -c%s "$media_file")" -gt 0 ]; then
  echo "RESULT: media download SUCCEEDED with cookies — cookies are usable on this host"
  [ "$KEEP_TMP" = "1" ] && echo "kept test audio: $media_file"
  echo "VERDICT: ok (usable)"
  exit 0
fi
echo "RESULT: metadata worked but MEDIA was blocked with cookies (typical datacenter-IP block)."
echo "        Policy: keep crawling WITHOUT cookies (PROJECT_STATUS.md §15.3)."
echo "VERDICT: blocked"
exit 2
