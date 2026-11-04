#! /usr/bin/bash
#
# cleanup_local.sh — xoá audio/info.json của MỘT batch đã verify trên Drive.
#
# Đây là script DUY NHẤT được phép xoá dữ liệu. Mặc định là DRY RUN.
#
# Usage:
#   ./cleanup_local.sh <batch_name>            # dry run: liệt kê sẽ xoá gì, tốn bao nhiêu
#   ./cleanup_local.sh <batch_name> --yes      # xoá thật
#   ./cleanup_local.sh <batch_name> --yes --keep-info-json
#
# Chốt an toàn (implement trong metadata/cleanup_local.py):
#   * CHỈ chạy khi corpus_ledger.jsonl có verified=true cho batch này
#     (tức đã upload + verify_remote.sh PASS)
#   * chỉ xoá file nằm trong manifest.jsonl của batch
#   * kiểm sha256 trước khi xoá (--no-check-sha để tắt)
#   * xoá luôn bản hardlink trong <DATASET_DIR>/audio/... — nếu không, inode vẫn sống
#     và dung lượng KHÔNG được giải phóng (df không đổi)
#   * KHÔNG BAO GIỜ xoá crawler/log/audios_*.txt, batch folder, hay ledger
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PIPELINE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
exec python3 "$PIPELINE_DIR/metadata/cleanup_local.py" "$@"
