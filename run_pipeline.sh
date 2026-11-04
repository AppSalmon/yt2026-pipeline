#! /usr/bin/bash
#
# End-to-end driver for the YouTube speech crawl pipeline
# (video uploaded on/after $MIN_UPLOAD_DATE, primary language = $LANG_CODE,
#  code-switch corpus = $ACCEPT_LANGS), based on GigaSpeech2.
#
# Usage:
#   ./run_pipeline.sh [step]     # step in: crawl|convert|align|detect|filter|segment|index|all
#   (default: all = convert..index; crawl is usually run separately)
#
# All stages are configurable via environment variables (see docs/CONFIGURATION.md), e.g.:
#   LANG_CODE=th ACCEPT_LANGS=th,en ISO_639_2=tha ./run_pipeline.sh convert
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Single source of truth for DATA locations. Data lives OUTSIDE the repo; caller-exported
# env vars still win (every variable in config.env is written as ${VAR:-default}).
# shellcheck source=config.env
if [ -f "$PIPELINE_DIR/config.env" ]; then
  . "$PIPELINE_DIR/config.env"
fi
DATA_ROOT=${DATA_ROOT:-$HOME/data}

# ======================= Config (override via env) =======================
CHANNELS_FILE=${CHANNELS_FILE:-$PIPELINE_DIR/crawler/channels.txt}
DOWNLOAD_DIR=${DOWNLOAD_DIR:-$DATA_ROOT/download_from_youtube}
DATASET_DIR=${DATASET_DIR:-$DATA_ROOT/dataset}
SAVE_DIR=${SAVE_DIR:-$DATA_ROOT/output_trans}             # convert+transcribe output
ALIGN_DIR=${ALIGN_DIR:-$PIPELINE_DIR/output_force_align}  # alignment manifests
ANNOT_DIR=${ANNOT_DIR:-$PIPELINE_DIR/output_annotated}    # code-switch annotated manifests
FILTER_DIR=${FILTER_DIR:-$PIPELINE_DIR/output_filter}     # filtered manifests
SEGMENT_ALL_DIR=${SEGMENT_ALL_DIR:-$PIPELINE_DIR/output_segment_all}
SEGMENT_CS_DIR=${SEGMENT_CS_DIR:-$PIPELINE_DIR/output_segment_codeswitch}
INDEX_FILE=${INDEX_FILE:-$DATASET_DIR/index.jsonl}        # 2026 audit index (derived data)
LID_MODEL=${LID_MODEL:-$PIPELINE_DIR/models/lid.176.ftz}
MAX_DURATION=${MAX_DURATION:-}          # crawler: optional cap in seconds (empty = unlimited)

LANG_CODE=${LANG_CODE:-vi}              # mã ISO 639-1 của ngôn ngữ chính (xem config.env)
LANG=${LANG:-$LANG_CODE}                # primary Whisper language
ACCEPT_LANGS=${ACCEPT_LANGS:-$LANG_CODE,en}   # languages kept (code-switch: chính + en)
ISO_639_2=${ISO_639_2:-vie}             # for force alignment / normalization
WHISPER_MODEL=${WHISPER_MODEL:-large-v3}
USE_FASTER_WHISPER=${USE_FASTER_WHISPER:-True}
DEVICE=${DEVICE:-cuda}
WORKERS=${WORKERS:-16}
STEP=${1:-all}

yt_dlp() { command -v yt-dlp >/dev/null 2>&1 && command yt-dlp "$@" || "$HOME/.local/bin/yt-dlp" "$@"; }

step_crawl() {
  (cd "$PIPELINE_DIR/crawler" \
    && ./download_from_youtube.sh "$CHANNELS_FILE" "$DOWNLOAD_DIR" $MAX_DURATION_ARG)
}

step_convert() {
  python3 "$PIPELINE_DIR/convert_transcribe/convert_and_transcribe.py" \
    --lang "$LANG" \
    --accept-langs "$ACCEPT_LANGS" \
    --root-dir "$DOWNLOAD_DIR" \
    --save-dir "$SAVE_DIR" \
    --model-size "$WHISPER_MODEL" \
    --use-faster-whisper "$USE_FASTER_WHISPER" \
    --device "$DEVICE" \
    --workers "$WORKERS"
}

step_align() {
  # force_align.sh uses ../utils/... relative paths -> run from its own directory
  (cd "$PIPELINE_DIR/force_alignment" \
    && ./force_align.sh "$SAVE_DIR/corpus" "$ALIGN_DIR" "$ISO_639_2")
}

step_detect() {
  python3 "$PIPELINE_DIR/codeswitch/detect_codeswitch.py" \
    --input-dir "$ALIGN_DIR" \
    --output-dir "$ANNOT_DIR" \
    --lid-model-path "$LID_MODEL" \
    --info-root "$DOWNLOAD_DIR"
}

step_filter() {
  python3 "$PIPELINE_DIR/segmentation/filter_manifest.py" \
    --input-dir "$ANNOT_DIR" \
    --output-dir "$FILTER_DIR" \
    --mode both \
    --min-upload-date "$MIN_UPLOAD_DATE"
}

step_segment() {
  (cd "$PIPELINE_DIR/segmentation" \
    && ./segment.sh "$FILTER_DIR/all" "$SEGMENT_ALL_DIR")
  (cd "$PIPELINE_DIR/segmentation" \
    && ./segment.sh "$FILTER_DIR/codeswitch" "$SEGMENT_CS_DIR")
}

step_index() {
  python3 "$PIPELINE_DIR/metadata/build_index.py" \
    --download-dir "$DOWNLOAD_DIR" \
    --output "$INDEX_FILE" \
    --min-upload-date "$MIN_UPLOAD_DATE"
}

MAX_DURATION_ARG=""
[ -n "$MAX_DURATION" ] && MAX_DURATION_ARG="$MAX_DURATION"

case "$STEP" in
  crawl)   step_crawl ;;
  convert) step_convert ;;
  align)   step_align ;;
  detect)  step_detect ;;
  filter)  step_filter ;;
  segment) step_segment ;;
  index)   step_index ;;
  all)     step_convert; step_align; step_detect; step_filter; step_segment; step_index ;;
  *) echo "Unknown step: $STEP (use crawl|convert|align|detect|filter|segment|index|all)"; exit 1 ;;
esac
echo "Step '$STEP' done."