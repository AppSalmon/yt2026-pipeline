# SETUP — cài đặt từ số 0

Mục tiêu: sau tối đa ~15 phút bạn có môi trường chạy được **crawl + QC**; phần
**transcribe/align** (tuỳ chọn) cần thêm torch và nên có GPU.

## 0. Yêu cầu tối thiểu

| Thành phần | Ghi chú |
|---|---|
| Linux (Ubuntu 22.04 đã kiểm chứng) | macOS/WSL cũng chạy được phần crawl |
| Python ≥ 3.10 | `python3 --version` |
| `perl` | bắt buộc cho uroman (forced alignment) |
| Không cần `root` | toàn bộ tool cài vào `~/.local/bin` / micromamba env |
| Đĩa | audio-only medium opus ≈ **42 MB/giờ** ⇒ 1.000 h ≈ 42 GB |

## 1. Tool hệ thống (không cần sudo)

```shell
./scripts/install_system_deps.sh
```

Script làm 4 việc (idempotent):

1. `ffmpeg`, `ffprobe`, `sox`, `soxi` qua **micromamba** (conda-forge) →
   symlink vào `~/.local/bin`;
2. `rclone` (chỉ cần cho bước upload Google Drive);
3. `yt-dlp` (pip `--user` nếu chưa có);
4. kiểm tra `perl`.

Thêm vào `~/.bashrc` nếu chưa có:

```shell
export PATH="$HOME/.local/bin:$PATH"
```

## 2. Python packages

```shell
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip
pip install -r requirements.txt      # crawl + QC + metadata
```

Ghi chú quan trọng:

- `fasttext==0.9.3` **không** chạy với `numpy>=2` ⇒ `requirements.txt` đã ghim `numpy<2`.
- `torch`/`torchaudio` trong requirements là **bản CPU**. Có GPU thì cài theo
  <https://pytorch.org/get-started/locally/> rồi bỏ 2 dòng `torch*`:
  ```shell
  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
  ```
- Bước transcribe dùng `faster-whisper` (nhanh hơn `openai-whisper` cùng model).
  Muốn bản gốc: `pip install git+https://github.com/openai/whisper.git`.

## 3. Model nhị phân

```shell
./scripts/download_models.sh          # models/lid.176.ftz (~938 KB)
./scripts/download_models.sh --full   # tuỳ chọn: models/lid.176.bin (~126 MB)
```

`uroman` đã **vendor sẵn** trong `utils/uroman/` (MIT) — không cần tải.
Model Whisper + MMS alignment tự tải về `~/.cache` ở lần chạy đầu.

## 4. Xác minh môi trường

```shell
./scripts/check_env.sh      # READ-ONLY: tool, python, model, config, dung lượng
python3 metadata/paths.py   # đường dẫn dữ liệu resolve ra đâu
make smoke                  # resolve config.env (LANG_CODE, DOWNLOAD_DIR…)
```

`check_env.sh` in `OK / WARN / FAIL` cho từng mục và exit 1 nếu có `FAIL` —
**đừng crawl** khi còn FAIL.

## 5. Danh sách kênh

```shell
cp crawler/channels.example.txt crawler/channels.txt
$EDITOR crawler/channels.txt
```

Format mỗi dòng: `[tên kênh]<TAB>[@handle hoặc channel/UCxxxx]`.
Dòng `#` và dòng trống bị bỏ qua. Kiểm tra kênh còn sống:

```shell
./crawler/check_channels.sh crawler/channels.txt
```

Tự tìm kênh mới theo từ khoá (không tải media):

```shell
python3 crawler/discover_channels.py \
    --keywords-file crawler/langs/vi/keywords.txt \
    --num-per-keyword 40 --output crawler/candidates.tsv
# hoặc: --keywords "podcast tiếng việt" "talkshow việt nam"
```

## 6. Bước tiếp theo

- Chạy thử 1 kênh: [`OPERATIONS.md`](OPERATIONS.md) §1.
- Đổi ngôn ngữ: [`ADD_LANGUAGE.md`](ADD_LANGUAGE.md).
- Lỗi hay gặp: [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## 7. Cài trên server mới (migration)

1. `git clone <repo>` → `./scripts/install_system_deps.sh` →
   `pip install -r requirements.txt` → `./scripts/download_models.sh`.
2. Copy (hoặc mount) `$DATA_ROOT` từ máy cũ — **bắt buộc giữ**:
   `corpus_ledger.jsonl`, `dataset/used_ids.txt`, `crawler/log/audios_*.txt`
   (3 tầng chống trùng — mất là tải lại từ đầu).
3. `rclone config` lại (Drive) và `hf auth login` (HuggingFace).
4. `./scripts/check_env.sh` → chỉ chạy tiếp khi 0 FAIL.
