#! /usr/bin/bash
#
# Download audio-only (medium opus, ORIGINAL Vietnamese track) from YouTube channels.
# Stage in use: AUDIO-ONLY ACQUISITION (no transcription, no alignment, no segment cutting).
#
# Based on GigaSpeech2's pipeline/crawler/download_from_youtube_channels.sh with:
#   0. language-locked format selector  -> medium opus of the ORIGINAL Vietnamese track
#                                          (avoids YouTube AI-dubbed [en-US] tracks)
#   1. --dateafter 20260101             -> ONLY videos published on/after 2026-01-01
#   2. --match-filters "!is_live ..."   -> skip live/upcoming streams (+ optional duration cap)
#   3. crawl /videos + /shorts + /streams (past live) tabs — override with TABS="videos shorts"
#   4. --write-info-json                -> keep upload_date/channel metadata for the 2026 audit
#   5. filename embeds %(upload_date)s  -> e.g. 20260315#Title#UCxxx#dQw4w9WgXcQ_213.m4a
#
# Usage:
#   ./download_from_youtube.sh [channels list file] [download directory (optional)] [max_duration_sec (optional)]
#
# Exit codes:
#   0  ran (ok, or partial failures of individual videos)
#   1  EVERY yt-dlp invocation failed (channel unreachable/blocked) -> crawl_all marks 'fail'
#   2  refused: download dir resolves inside the repo
#   3  refused: staging free space below MIN_FREE_HARD_GB
#
# Channels list format (one per line, TAB separated):
#   [channel name]<TAB>@handle            (e.g. VTV24	@VTV24)
#   [channel name]<TAB>channel/UCxxxx     (also accepted)
# Lines starting with '#' and empty lines are ignored.
#
# NOTE: put your YouTube cookies in `cookies.txt` (Netscape format) next to this
# script to avoid bot checks; strongly recommended at scale (>5 channels).
#
# Environment variables (all optional):
#   DOWNLOAD_DIR      crawl root (default: ../config.env value, outside the repo)
#   AUDIO_FORMAT      yt-dlp -f selector       (default: medium opus of the vi track)
#   COOKIES_FILE      Netscape cookies path    (default: <script dir>/cookies.txt)
#   MIN_DURATION      skip videos shorter (s)  (default: 0 -> keep, e.g. keep Shorts)
#   MAX_DURATION      skip videos longer (s)   (default: empty -> no cap)
#   MAX_VIDEOS        max downloads per tab    (default: 50 via config.env; empty -> all)
#   TABS              tabs to crawl            (default: "videos shorts streams";
#                     /streams = past live broadcasts, ongoing live is filtered out)
#   WALK_LIMIT        1 = chan "di dao" danh sach cu: chi quet toi
#                     (so video da tai cua tab + WALK_SLACK) muc dau   (default 1)
#   WALK_SLACK        so muc du phong khi chan di dao
#                     (default: MAX_VIDEOS + 20, hoac 200 khi khong dat MAX_VIDEOS)
#   RETRIES           retries per video        (default: 10)
#   FRAGMENT_RETRIES  retries per fragment     (default: 10)
#   SKIP_AFTER_ERRORS give up on playlist after N errors (default: 5)
#   SLEEP_REQUESTS    seconds between requests (default: 1)
#   SLEEP_INTERVAL    min seconds between downloads (default: 3)
#   MAX_SLEEP_INTERVAL max seconds between downloads (default: 6)
#   EXTRA_OPTS        extra raw yt-dlp args    (e.g. "--playlist-items 1:3" for a pilot)
#
# Data location (single source of truth: ../config.env):
#   The download ROOT must live OUTSIDE the repo. The 2nd positional arg still wins,
#   DOWNLOAD_DIR (env/config.env) is the default, and a repo-inside path is REFUSED
#   unless ALLOW_IN_REPO_DOWNLOAD=1.
set -u

# Resolve our own directory first: logs/cookies/archives must never depend on the
# caller's CWD (bug log #12 — log_dir used to create a stray log/ at the repo root).
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

# Single source of truth for data paths (env vars exported by the caller still win).
# shellcheck source=../config.env
if [ -f "$PIPELINE_DIR/config.env" ]; then
  . "$PIPELINE_DIR/config.env"
fi
ALLOW_IN_REPO_DOWNLOAD="${ALLOW_IN_REPO_DOWNLOAD:-0}"
DEFAULT_DOWNLOAD_DIR="${DOWNLOAD_DIR:-$DATA_ROOT/download_from_youtube}"

LANG_CODE="${LANG_CODE:-vi}"                       # mã ISO 639-1 (xem config.env)
readonly DATE_AFTER="${DATE_AFTER:-${MIN_UPLOAD_DATE:-20260101}}"

# Medium opus, ORIGINAL <LANG_CODE> track. Preference chain:
#   1) opus + language <LANG_CODE> + abr>=60  (medium tier; excludes the lowest tier)
#   2) opus + language <LANG_CODE>            (any opus bitrate)
#   3) any audio track of language <LANG_CODE> (e.g. m4a when opus is unavailable)
#   4) plain best audio                       (legacy videos without language metadata
#                                               -> audio_qc.py verifies later)
# Đổi ngôn ngữ: export LANG_CODE=th (hoặc sửa config.env). Format selector dùng
# `[language^=xx]` nên KHÔNG cần sửa gì khác cho ngôn ngữ khác.
AUDIO_FORMAT="${AUDIO_FORMAT:-ba[language^=${LANG_CODE}][acodec=opus][abr>=60]/ba[language^=${LANG_CODE}][acodec=opus]/ba[language^=${LANG_CODE}]/ba}"

if [ $# -lt 1 ]; then
  echo "Usage: $0 [channels list file] [download directory (default: \$DOWNLOAD_DIR)] [max_duration_sec (optional)]"
  exit 1
fi

# --- download root: absolute + must be outside the repo -----------------------
save_dir=$(realpath -m "${2:-$DEFAULT_DOWNLOAD_DIR}")
case "$(realpath -m --relative-to="$PIPELINE_DIR" "$save_dir")" in
  ..*|/*) ;;                                      # outside the repo -> OK
  *)
    if [ "$ALLOW_IN_REPO_DOWNLOAD" = "1" ]; then
      echo "WARNING: download dir is INSIDE the repo ($save_dir) — allowed by ALLOW_IN_REPO_DOWNLOAD=1"
    else
      echo "ERROR: refusing to store crawl data inside the repo: $save_dir"
      echo "       Fix: export DOWNLOAD_DIR=<path outside the repo> (see $PIPELINE_DIR/config.env)"
      echo "       Or deliberately override with ALLOW_IN_REPO_DOWNLOAD=1."
      exit 2
    fi
    ;;
esac

echo "Read channels from file: $1, save to: $save_dir"

# Logs live next to this script (repo-side, machine-local) — NOT in the caller's CWD.
log_dir="$SCRIPT_DIR/log"
mkdir -p "$log_dir" "$save_dir"

# 3rd positional arg = max duration (seconds); MAX_DURATION env takes precedence
MAX_DURATION="${MAX_DURATION:-${3:-}}"
MIN_DURATION="${MIN_DURATION:-0}"
MAX_VIDEOS="${MAX_VIDEOS:-}"
RETRIES="${RETRIES:-10}"
FRAGMENT_RETRIES="${FRAGMENT_RETRIES:-10}"
SKIP_AFTER_ERRORS="${SKIP_AFTER_ERRORS:-5}"
SLEEP_REQUESTS="${SLEEP_REQUESTS:-1}"
SLEEP_INTERVAL="${SLEEP_INTERVAL:-3}"
MAX_SLEEP_INTERVAL="${MAX_SLEEP_INTERVAL:-6}"
EXTRA_OPTS="${EXTRA_OPTS:-}"

cookies_opt=""
# Default cookie location is resolved against THIS script's directory (not the caller's
# CWD — same class of bug as log_dir). Convenience: if no COOKIES_FILE is given and
# crawler/cookies.txt is absent, accept exactly ONE *.txt inside crawler/cookies/.
cookies_file="${COOKIES_FILE:-$SCRIPT_DIR/cookies.txt}"
if [ ! -f "$cookies_file" ] && [ -z "${COOKIES_FILE:-}" ] && [ -d "$SCRIPT_DIR/cookies" ]; then
  mapfile -t _cookie_candidates < <(find "$SCRIPT_DIR/cookies" -maxdepth 1 -type f -name '*.txt' 2>/dev/null | sort)
  if [ "${#_cookie_candidates[@]}" -eq 1 ]; then
    cookies_file="${_cookie_candidates[0]}"
    echo "Auto-detected cookie file: $cookies_file (run ./check_cookies.sh first!)"
  elif [ "${#_cookie_candidates[@]}" -gt 1 ]; then
    echo "NOTE: multiple cookie files in $SCRIPT_DIR/cookies/ — set COOKIES_FILE explicitly to pick one"
  fi
fi
if [ -f "$cookies_file" ]; then
  cookies_opt="--cookies $cookies_file"
  echo "Using cookies: $cookies_file"
  echo "WARNING: cookie verdict must be 'ok (usable)' (./check_cookies.sh) — datacenter IPs are usually blocked (see PROJECT_STATUS.md §15)"
else
  echo "NOTE: no cookie file found ($cookies_file) — proceeding without cookies (validated default for this host)"
fi

max_videos_opt=""
[ -n "$MAX_VIDEOS" ] && max_videos_opt="--max-downloads $MAX_VIDEOS"

# WALK_SLACK phai >= MAX_VIDEOS: bound cua walk = (so muc da tai) + walk_slack. Neu bound nho
# hon cap, yt-dlp se het ung vien truoc khi dat cap => ta tuong "kenh chi co vay" (bug #35).
if [ -n "${WALK_SLACK:-}" ]; then
  walk_slack="$WALK_SLACK"; walk_slack_src="env"
elif [ -n "$MAX_VIDEOS" ]; then
  walk_slack=$(( MAX_VIDEOS + 20 )); walk_slack_src="MAX_VIDEOS+20"
else
  walk_slack=200; walk_slack_src="khong dat cap"
fi

echo "Config: AUDIO_FORMAT=$AUDIO_FORMAT"
echo "Config: save_dir=$save_dir  log_dir=$log_dir"
echo "Config: retries=$RETRIES fragment_retries=$FRAGMENT_RETRIES skip_after_errors=$SKIP_AFTER_ERRORS"
echo "Config: min_duration=${MIN_DURATION}s max_duration=${MAX_DURATION:-(none)} max_videos=${MAX_VIDEOS:-(none)}"

# Counters for the final exit code (see the check after the loop).
total_runs=0
failed_runs=0

while read rows || [ -n "$rows" ]; do
  # skip empty lines and comments
  case "$rows" in ""|\#*) continue;; esac
  echo "$rows"
  channel=`echo "$rows" | awk -F"\t" '{print $2}'`
  # keep only the last path segment (strip "@handle" -> "handle", "channel/UCxxx" -> "UCxxx")
  channel_name=`echo "${channel##*/}" | sed 's/^@//'`
  echo "Processing channel: $channel, channel name: $channel_name"

  match_filters="!is_live & !is_upcoming"
  if [ "${MIN_DURATION}" != "0" ]; then
    match_filters="$match_filters & duration>=$MIN_DURATION"
  fi
  if [ -n "$MAX_DURATION" ]; then
    match_filters="$match_filters & duration<=$MAX_DURATION"
  fi
  echo "  Match filters: $match_filters"

  for tab in ${TABS:-videos shorts streams}; do
    echo "  Tab: $tab"
    # CHAN "DI DAO" (WALK_LIMIT): --dateafter la bo loc SAU extract nen yt-dlp phai extract
    # tung video cu chi de doc upload_date (~4 request/item). Kenh da tai gan het ma playlist
    # con hang tram muc cu => 60-90 phut ma 0 file. Playlist xep moi->cu nen moi video 2026
    # CHUA tai deu nam ngay sau phan da tai => chi quet toi (so muc da tai + WALK_SLACK).
    # WALK_LIMIT=0 de tat (hanh vi cu).
    archive_file="$log_dir/audios_${channel_name}_${tab}.txt"
    archived=0
    if [ -f "$archive_file" ]; then
      archived=$(wc -l < "$archive_file")
    fi
    playlist_opt=""
    if [ "${WALK_LIMIT:-1}" = "1" ]; then
      playlist_opt="--playlist-items 1:$(( archived + walk_slack ))"
      echo "  Walk bound: $playlist_opt (da tai $archived + slack $walk_slack [$walk_slack_src])"
    fi
    # EXTRA_OPTS: optional extra yt-dlp args via env (e.g. --playlist-items 1:3 for a pilot run)
    # shellcheck disable=SC2086
    total_runs=$((total_runs + 1))
    if yt-dlp \
      -f "$AUDIO_FORMAT" \
      --dateafter "$DATE_AFTER" \
      --match-filters "$match_filters" \
      $playlist_opt \
      --download-archive "$archive_file" \
      $cookies_opt \
      --retries "$RETRIES" \
      --fragment-retries "$FRAGMENT_RETRIES" \
      --skip-playlist-after-errors "$SKIP_AFTER_ERRORS" \
      --no-abort-on-error \
      --sleep-requests "$SLEEP_REQUESTS" \
      --sleep-interval "$SLEEP_INTERVAL" \
      --max-sleep-interval "$MAX_SLEEP_INTERVAL" \
      $max_videos_opt \
      --write-info-json \
      --no-write-playlist-metafiles \
      --newline \
      $EXTRA_OPTS \
      "https://www.youtube.com/${channel}/${tab}" \
      -o "${save_dir}/${channel_name}/%(upload_date)s#%(title).20s#%(channel_id)s#%(id)s_%(duration)s.%(ext)s" \
      >> "$log_dir/${channel_name}_${tab}.log" 2>&1
    then
      echo "  Tab $tab: yt-dlp finished OK"
    else
      ytdlp_rc=$?
      # rc=101 is DownloadCancelled: --max-downloads / --break-on-existing stopped the
      # queue ON PURPOSE after a successful download. Treat it as OK, otherwise the
      # whole channel is reported as failed and crawl_all retries it with backoff.
      case "$ytdlp_rc" in
        101)
          echo "  Tab $tab: queue stopped on purpose (rc=101 max-downloads/break-on-existing) — OK"
          ;;
        *)
          # A channel that simply has no such tab ("This channel does not have a shorts tab")
          # is not a failure either — there is nothing to crawl there.
          if tail -n 40 "$log_dir/${channel_name}_${tab}.log" 2>/dev/null | grep -q 'does not have a .* tab'; then
            echo "  Tab $tab: kênh không có tab này (bình thường) — OK"
          else
            failed_runs=$((failed_runs + 1))
            echo "  WARNING: yt-dlp exit code $ytdlp_rc for $channel_name/$tab (details: $log_dir/${channel_name}_${tab}.log)"
          fi
          ;;
      esac
    fi
  done
done < "$1"

# Exit non-zero ONLY when every invocation failed: an unreachable/blocked channel must be
# reported as 'fail' in crawl_all.sh's summary, while partial failures (a few unavailable
# videos under --no-abort-on-error) must NOT fail the whole run.
if [ "$total_runs" -gt 0 ] && [ "$failed_runs" -eq "$total_runs" ]; then
  echo "ERROR: all $total_runs yt-dlp invocation(s) failed — channel unreachable/blocked?"
  exit 1
fi
echo "Finished."