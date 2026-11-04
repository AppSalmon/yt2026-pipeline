#! /usr/bin/bash
#
# install_rclone.sh — cài rclone vào ~/.local/bin (1 binary, KHÔNG cần sudo).
#
# Sau khi cài, cần authorize Google Drive MỘT LẦN (thủ công, có browser):
#   rclone config
#     n) new remote -> name: gdrive -> storage: drive
#     client_id/client_secret: để trống (dùng client mặc định của rclone)
#     scope: 2 (drive) hoặc 3 (drive.readonly -> chỉ đọc, KHÔNG upload được)
#     root_folder_id / service_account_file: để trống
#     auto config: n (headless) -> rclone in URL, mở trên máy có browser rồi dán code
#
#   # máy không có browser (headless):
#   rclone config --auth-no-open-browser
#
# Kiểm tra:  rclone lsd gdrive:      (phải liệt kê được thư mục trên Drive)
#
# Yêu cầu: Drive >= 5TB (2.1TB corpus + dư địa). Giới hạn upload ~750GB/ngày/tài khoản.
set -euo pipefail

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"

arch=$(uname -m)
case "$arch" in
  x86_64|amd64) rarch=amd64 ;;
  aarch64|arm64) rarch=arm64 ;;
  *) echo "ERROR: kiến trúc không hỗ trợ: $arch"; exit 1 ;;
esac

url="https://downloads.rclone.org/rclone-current-linux-${rarch}.zip"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $url"
curl -fL --retry 3 --retry-delay 3 -o "$tmp/rclone.zip" "$url"

if command -v unzip >/dev/null 2>&1; then
  unzip -q -o "$tmp/rclone.zip" -d "$tmp"
else
  echo "unzip không có — dùng python3 zipfile"
  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
    "$tmp/rclone.zip" "$tmp"
fi

src=$(find "$tmp" -type f -name rclone | head -1)
[ -n "$src" ] || { echo "ERROR: không tìm thấy binary rclone trong zip"; exit 1; }
install -m 0755 "$src" "$BIN_DIR/rclone"

echo
"$BIN_DIR/rclone" version | head -3
echo
echo "Đã cài: $BIN_DIR/rclone"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "LƯU Ý: thêm vào PATH:  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
echo "Bước tiếp theo (THỦ CÔNG, 1 lần): rclone config --auth-no-open-browser"
echo "Rồi đặt GDRIVE_REMOTE trong config.env (mặc định: gdrive:corpus)"
