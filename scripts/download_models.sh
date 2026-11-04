#!/usr/bin/env bash
# ============================================================================
# download_models.sh — tải các model nhị phân KHÔNG nằm trong repo.
#   * models/lid.176.ftz   fastText LID 938 KB (CC-BY-SA 3.0) — bắt buộc cho
#                          codeswitch/detect_codeswitch.py
#   * models/lid.176.bin   (tuỳ chọn, ~126 MB) chính xác hơn nhưng chậm hơn
#
# Model Whisper / MMS được tải tự động ở lần chạy đầu ($HOME/.cache) — không cần
# script này.
# ============================================================================
set -euo pipefail
MODELS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models"
FTZ_URL="https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
BIN_URL="https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
mkdir -p "$MODELS_DIR"

if [ -s "$MODELS_DIR/lid.176.ftz" ]; then
  echo "OK  models/lid.176.ftz đã có ($(du -h "$MODELS_DIR/lid.176.ftz" | cut -f1))"
else
  echo "Tải lid.176.ftz (~938 KB)..."
  curl -fsSL "$FTZ_URL" -o "$MODELS_DIR/lid.176.ftz"
  echo "OK  models/lid.176.ftz ($(du -h "$MODELS_DIR/lid.176.ftz" | cut -f1))"
fi

if [ "${1:-}" = "--full" ]; then
  if [ -s "$MODELS_DIR/lid.176.bin" ]; then
    echo "OK  models/lid.176.bin đã có"
  else
    echo "Tải lid.176.bin (~126 MB)..."
    curl -fsSL "$BIN_URL" -o "$MODELS_DIR/lid.176.bin"
    echo "OK  models/lid.176.bin — trỏ LID_MODEL=models/lid.176.bin để dùng"
  fi
fi

cat <<'NOTE'

Lưu ý license: fastText lid.176.* là CC-BY-SA 3.0 (Facebook AI Research).
Vì vậy model KHÔNG được commit vào repo (xem NOTICE + models/README.md).

Dùng: LID_MODEL=models/lid.176.ftz  (mặc định trong run_pipeline.sh)
NOTE
