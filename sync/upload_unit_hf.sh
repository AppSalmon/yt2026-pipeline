#! /usr/bin/bash
#
# upload_unit_hf.sh — đẩy 1 unit lên HuggingFace (public dataset) theo từng chunk.
#
# Dùng venv riêng ~/.hf-cli (do `https://hf.co/cli/install.sh` tạo) để KHÔNG đụng
# môi trường fasttext/numpy<2 của pipeline. Override: HF_PYTHON=/path/to/python
#
# Usage:
#   ./sync/upload_unit_hf.sh <unit> [--repo <user>/<unit>] [--list]
#                             [--channels-per-chunk N] [--only-channel UCxxxx] [--dry-run]
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
[ -f "$PIPELINE_DIR/config.env" ] && . "$PIPELINE_DIR/config.env"

HF_PYTHON=${HF_PYTHON:-$HOME/.venvs/hf1/bin/python}
if [ ! -x "$HF_PYTHON" ]; then
  HF_PYTHON=$HOME/.hf-cli/venv/bin/python       # fallback: CLI standalone (v2)
fi
# Xet data-plane bị chậm từ mạng này (~0.1 MB/s) -> mặc định dùng LFS (đo được 25+ MB/s).
# Muốn thử lại Xet: HF_HUB_DISABLE_XET=0 ./sync/upload_unit_hf.sh ...
export HF_HUB_DISABLE_XET=${HF_HUB_DISABLE_XET:-1}
if [ ! -x "$HF_PYTHON" ]; then
  echo "ERROR: không thấy python của HF tại $HF_PYTHON"
  echo "       cài:  python3 -m venv ~/.venvs/hf1 && ~/.venvs/hf1/bin/pip install 'huggingface_hub<2' hf_xet"
  exit 1
fi
if ! "$HF_PYTHON" -c 'import huggingface_hub' >/dev/null 2>&1; then
  echo "ERROR: venv chưa có huggingface_hub"
  exit 1
fi
if [ ! -f "$HOME/.cache/huggingface/token" ] && [ -z "${HF_TOKEN:-}" ]; then
  echo "ERROR: chưa có token HF (~/.cache/huggingface/token) — chạy: hf auth login"
  exit 1
fi

# Log vào <DATASET_DIR>/_logs/ (KHÔNG dùng /tmp — mất khi reboot).
# Dùng `| tee` (không phải exec >) để vẫn nhìn thấy tiến độ khi chạy foreground,
# và `set -o pipefail` giữ đúng exit code của python.
# HF_LOG_FILE=<path> cho phép supervisor (sync/upload_hf_retry.sh) dùng chung 1 file log.
DATASET_DIR=${DATASET_DIR:-$DATA_ROOT/dataset}
LOG_DIR="$DATASET_DIR/_logs"; mkdir -p "$LOG_DIR"
LOG="${HF_LOG_FILE:-$LOG_DIR/upload_hf_${1}_$(date +%Y%m%d_%H%M%S).log}"
echo "log: $LOG"

"$HF_PYTHON" "$SCRIPT_DIR/upload_unit_hf.py" "$@" 2>&1 | tee -a "$LOG"
