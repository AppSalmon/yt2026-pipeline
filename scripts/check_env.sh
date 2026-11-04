#!/usr/bin/env bash
# ============================================================================
# check_env.sh — kiểm tra môi trường trước khi crawl (READ-ONLY, không ghi gì).
# Mỗi dòng in OK / WARN / FAIL. Exit code 1 nếu có FAIL.
# ============================================================================
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fails=0
warns=0
ok()   { printf '  OK    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; warns=$((warns+1)); }
bad()  { printf '  FAIL  %s\n' "$*"; fails=$((fails+1)); }
head_() { printf '\n=== %s\n' "$*"; }

head_ "1. Tool hệ thống"
for b in ffmpeg ffprobe sox yt-dlp perl python3; do
  if command -v "$b" >/dev/null 2>&1; then
    ok "$b -> $(command -v "$b")"
  else
    bad "$b KHÔNG có trong PATH (chạy ./scripts/install_system_deps.sh)"
  fi
done
command -v rclone >/dev/null 2>&1 && ok "rclone -> $(rclone version | head -1)" \
  || warn "rclone chưa có (chỉ cần cho bước upload Drive)"

head_ "2. Python packages"
python3 - <<'PY'
import importlib
mods = [("yt_dlp", True), ("fasttext", False), ("numpy", False), ("tqdm", False),
        ("faster_whisper", False), ("torch", False), ("torchaudio", False),
        ("huggingface_hub", False)]
for name, required in mods:
    try:
        m = importlib.import_module(name)
        v = getattr(m, "__version__", "?")
        print(f"  OK    {name} {v}")
    except Exception:
        tag = "FAIL" if required else "WARN"
        print(f"  {tag}  {name} chưa cài (pip install -r requirements.txt)")
PY
python3 - <<'PY'
try:
    import numpy
    if int(numpy.__version__.split(".")[0]) >= 2:
        print("  WARN  numpy>=2 — fasttext 0.9.3 cần numpy<2 (pip install 'numpy<2')")
    else:
        print(f"  OK    numpy<2 ({numpy.__version__}) — tương thích fasttext")
except Exception:
    pass
PY

head_ "3. Model + uroman"
[ -s "$REPO/models/lid.176.ftz" ] && ok "models/lid.176.ftz ($(du -h "$REPO/models/lid.176.ftz" | cut -f1))" \
  || bad "models/lid.176.ftz thiếu (./scripts/download_models.sh)"
[ -f "$REPO/utils/uroman/bin/uroman.pl" ] && ok "uroman có sẵn (utils/uroman/bin/uroman.pl)" \
  || warn "uroman thiếu (cần cho forced alignment)"
perl -e 'print ""' 2>/dev/null && ok "perl chạy được (uroman cần perl)" || bad "perl không chạy được"

head_ "4. Cấu hình (config.env)"
# shellcheck source=../config.env
. "$REPO/config.env"
printf '  LANG_CODE      = %s\n' "$LANG_CODE"
printf '  ACCEPT_LANGS   = %s\n' "$ACCEPT_LANGS"
printf '  ISO_639_2      = %s\n' "$ISO_639_2"
printf '  MIN_UPLOAD_DATE= %s\n' "$MIN_UPLOAD_DATE"
printf '  DOWNLOAD_DIR   = %s\n' "$DOWNLOAD_DIR"
printf '  DATASET_DIR    = %s\n' "$DATASET_DIR"
case "$DOWNLOAD_DIR" in
  "$REPO"*) [ "$ALLOW_IN_REPO_DOWNLOAD" = "1" ] \
      && warn "DOWNLOAD_DIR nằm TRONG repo (đã cho phép bằng ALLOW_IN_REPO_DOWNLOAD=1)" \
      || bad "DOWNLOAD_DIR nằm TRONG repo — script sẽ từ chối chạy" ;;
  *) ok "DOWNLOAD_DIR nằm ngoài repo" ;;
esac
[ -f "$REPO/crawler/channels.txt" ] && ok "crawler/channels.txt có $(grep -vc '^#\|^$' "$REPO/crawler/channels.txt" 2>/dev/null || echo 0) kênh" \
  || warn "crawler/channels.txt chưa có (cp crawler/channels.example.txt crawler/channels.txt)"

head_ "5. Dung lượng đĩa"
root="$(dirname "$DATA_ROOT")"; [ -d "$root" ] || root="$HOME"
free_gb=$(df -BG --output=avail "$root" 2>/dev/null | tail -1 | tr -dc '0-9')
if [ -n "${free_gb:-}" ]; then
  if [ "$free_gb" -lt "$MIN_FREE_HARD_GB" ]; then
    bad "chỉ còn ${free_gb} GB free tại $root (< MIN_FREE_HARD_GB=$MIN_FREE_HARD_GB)"
  elif [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    warn "còn ${free_gb} GB free tại $root (< MIN_FREE_GB=$MIN_FREE_GB)"
  else
    ok "${free_gb} GB free tại $root"
  fi
fi
printf '  ghi chú: audio-only medium opus ≈ 42 MB/giờ ⇒ 1.000 h ≈ 42 GB\n'

head_ "6. Python side (metadata/paths.py)"
( cd "$REPO" && python3 metadata/paths.py ) || bad "metadata/paths.py lỗi"

printf '\n=== KẾT LUẬN: %d FAIL, %d WARN\n' "$fails" "$warns"
[ "$fails" -eq 0 ] || exit 1
