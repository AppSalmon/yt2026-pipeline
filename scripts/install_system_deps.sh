#!/usr/bin/env bash
# ============================================================================
# install_system_deps.sh — cài tool hệ thống KHÔNG cần sudo (giống môi trường
# mà pipeline đã chạy thật):
#   ffmpeg + ffprobe + sox  (qua micromamba, conda-forge)
#   rclone                  (binary zip -> ~/.local/bin)
#   yt-dlp                  (không có thì pip install --user)
#
# Idempotent: chạy lại nhiều lần không sao. Kiểm tra sau khi cài: scripts/check_env.sh
# ============================================================================
set -euo pipefail

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
MM_ROOT="${MM_ROOT:-$HOME/micromamba}"
MM_ENV="${MM_ENV:-$MM_ROOT/envs/avtools}"
mkdir -p "$BIN_DIR"

say() { printf '\n=== %s\n' "$*"; }

# --- 1) ffmpeg / ffprobe / sox / soxi qua micromamba -------------------------
need_av=""
for b in ffmpeg ffprobe sox soxi; do
  command -v "$b" >/dev/null 2>&1 || need_av=1
done

if [ -n "$need_av" ]; then
  say "Cài ffmpeg + sox qua micromamba (không cần root)"
  if [ ! -x "$MM_ROOT/bin/micromamba" ]; then
    mkdir -p "$MM_ROOT"
    ( cd "$MM_ROOT"
      curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest -o mm.tar.bz2
      tar -xj -f mm.tar.bz2 bin/micromamba
      rm -f mm.tar.bz2 )
  fi
  "$MM_ROOT/bin/micromamba" create -y -p "$MM_ENV" -c conda-forge ffmpeg sox
  for b in ffmpeg ffprobe sox soxi; do
    [ -x "$MM_ENV/bin/$b" ] && ln -sf "$MM_ENV/bin/$b" "$BIN_DIR/$b"
  done
else
  say "ffmpeg/ffprobe/sox đã có — bỏ qua"
fi

# --- 2) rclone ---------------------------------------------------------------
if command -v rclone >/dev/null 2>&1; then
  say "rclone đã có: $(rclone version | head -1)"
elif [ -x "$(dirname "${BASH_SOURCE[0]}")/../sync/install_rclone.sh" ]; then
  say "Cài rclone qua sync/install_rclone.sh"
  ( cd "$(dirname "${BASH_SOURCE[0]}")/../sync" && ./install_rclone.sh )
else
  say "Tải rclone trực tiếp"
  arch="$(uname -m)"; case "$arch" in x86_64) rarch=amd64;; aarch64) rarch=arm64;; *) rarch=amd64;; esac
  tmp="$(mktemp -d)"
  curl -fsSL "https://downloads.rclone.org/rclone-current-linux-${rarch}.zip" -o "$tmp/rclone.zip"
  unzip -q -o "$tmp/rclone.zip" -d "$tmp"
  install -m755 "$(find "$tmp" -type f -name rclone | head -1)" "$BIN_DIR/rclone"
  rm -rf "$tmp"
fi

# --- 3) yt-dlp ---------------------------------------------------------------
if command -v yt-dlp >/dev/null 2>&1; then
  say "yt-dlp đã có: $(yt-dlp --version)"
else
  say "Cài yt-dlp (pip --user)"
  python3 -m pip install --user -U yt-dlp
fi

# --- 4) perl (bắt buộc cho uroman / forced alignment) ------------------------
command -v perl >/dev/null 2>&1 && say "perl đã có: $(perl -v | sed -n '2p')" \
  || say "THIẾU perl — cài bằng gói hệ thống (sudo apt install perl), cần cho uroman"

say "Xong. Thêm vào ~/.bashrc nếu chưa có:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
say "Kiểm tra: ./scripts/check_env.sh"
