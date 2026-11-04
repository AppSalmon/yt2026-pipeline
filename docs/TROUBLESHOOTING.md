# TROUBLESHOOTING — lỗi đã gặp thật & cách xử lý

Mỗi mục: **triệu chứng → nguyên nhân → cách xử lý**. Đều là lỗi đã gặp khi vận
hành thật, đừng mò lại từ đầu.

## 1. Crawl

### 1.1 `The page needs to be reloaded` / không tải được media dù cookie hợp lệ
- **Nguyên nhân**: YouTube chặn request media từ **IP datacenter** (VPS/cloud),
  dù cookie còn hạn, đủ cookie đăng nhập và trang xem vẫn mở được.
- **Xử lý**: **đừng dùng cookie** khi crawl hàng loạt (mặc định pipeline tắt).
  Nếu buộc phải dùng (video giới hạn tuổi / member-only): `crawler/check_cookies.sh
  <file>` phải trả verdict `ok (usable)` — verdict này test **tải thật**.

### 1.2 `429 Too Many Requests` / bot-check
- **Xử lý**: `JOBS=1`, `SLEEP_REQUESTS=1 SLEEP_INTERVAL=8..15 MAX_SLEEP_INTERVAL=20`,
  hoãn đợt vài giờ. **Không** xoay nhiều account từ cùng IP (bị đánh dấu nặng hơn).

### 1.3 Kênh nhiều video nhưng chỉ tải được vài cái rồi "hết"
- **Nguyên nhân**: giới hạn quét playlist (`WALK_LIMIT`/`WALK_SLACK`) nhỏ hơn
  `MAX_VIDEOS` ⇒ crawler tưởng kênh chỉ có vậy.
- **Xử lý**: `WALK_SLACK >= MAX_VIDEOS` (crawler tự tính `MAX_VIDEOS+20`);
  `WALK_LIMIT=0` để tắt. Chạy lại an toàn nhờ `--download-archive`.

### 1.4 `ERROR: refusing to store crawl data inside the repo` (exit 2)
- **Nguyên nhân**: `DOWNLOAD_DIR` resolve vào trong repo.
- **Xử lý**: `export DOWNLOAD_DIR=$HOME/data/download_from_youtube` (hoặc sửa
  `config.env`). Chỉ dùng `ALLOW_IN_REPO_DOWNLOAD=1` khi hiểu rõ hậu quả.

### 1.5 Exit code 3 / dừng giữa đợt vì hết đĩa
- Pipeline tự dừng khi free < `MIN_FREE_HARD_GB`. Xử lý: upload + verify rồi xoá
  local, tăng dung lượng, hoặc giảm `MAX_VIDEOS`.

### 1.6 Số GB trong `summary.csv` nhỏ hơn thực tế
- **Nguyên nhân**: `awk 'printf "%d"'` tràn 32-bit khi cộng byte.
- **Xử lý**: tin `python3 metadata/stats.py` hoặc `du -sb`; coi `new_bytes` chỉ
  là tương đối.

## 2. QC / filter

### 2.1 Nhiều file bị `wrong_language`
- Kiểm audio track thật: `ffprobe -show_streams file.webm | grep -i language`.
- Video cũ không có metadata ngôn ngữ ⇒ format selector rơi xuống `ba`, QC là lớp
  chặn cuối; giảm video cũ bằng `MIN_UPLOAD_DATE`.
- Kiểm `ACCEPT_LANGS` có đúng ngôn ngữ (+ `en` nếu code-switch).
- Model LID: `models/lid.176.ftz` (nhanh) vs `lid.176.bin` (chính xác hơn).

### 2.2 `filter_manifest.py` loại gần như toàn bộ segment
- **Nguyên nhân**: charset filter chưa có Unicode range của ngôn ngữ bạn.
- **Xử lý**: `docs/ADD_LANGUAGE.md` §3 (Thái `\u0E00-\u0E7F`, Myanmar
  `\u1000-\u109F`, Khmer `\u1780-\u17FF`…).

### 2.3 `fasttext` lỗi import / kết quả LID vô nghĩa
- **Nguyên nhân**: `numpy>=2` với `fasttext==0.9.3`.
- **Xử lý**: `pip install 'numpy<2'` (đã ghim trong `requirements.txt`).

## 3. Transcribe / alignment

### 3.1 `uroman not found` / lỗi `perl`
- Kiểm `utils/uroman/bin/uroman.pl` tồn tại + `perl -v` chạy được.
- `utils/uroman/bin/uroman-tsv.sh` là file upstream dùng **CRLF** ⇒ `bash -n` báo
  lỗi syntax; bỏ qua file này (`make sh-check` đã loại trừ `utils/uroman/`).

### 3.2 Alignment sai / timestamp lệch
- Kiểm tham số 3 của `force_align.sh` = `ISO_639_2` (vi→`vie`, th→`tha`…).
- Ngôn ngữ không được MMS hỗ trợ tốt ⇒ bỏ bước align, dùng timestamp của Whisper
  (`examples/whisper_segment/`).

### 3.3 Hết VRAM / rất chậm khi transcribe
- `WHISPER_MODEL=small` để thử; `DEVICE=cuda` cần GPU thật; giảm `WORKERS` còn 4–8.

## 4. Upload

### 4.1 HuggingFace `429` dồn dập, job abort
- **Nguyên nhân**: gói free giới hạn ~1.000 API request / 5 phút; ~40k file × ~4
  call ⇒ hàng chục nghìn request.
- **Xử lý**: supervisor `sync/upload_hf_retry.sh <unit> --workers 2` (tự backoff +
  resume), chia chunk nhỏ theo kênh (`--channels-per-chunk 20`), hoặc shard thành
  ít file `.tar` (giảm ~1000× số call), hoặc nâng gói.

### 4.2 Upload HF rất chậm (~0,1 MB/s)
- **Nguyên nhân**: Xet data-plane chậm từ một số mạng.
- **Xử lý**: `export HF_HUB_DISABLE_XET=1` (đã mặc định trong `config.env`) → LFS.

### 4.3 `huggingface_hub` v2 không có `upload_large_folder`
- **Xử lý**: `pip install 'huggingface_hub<2'` trong venv **riêng**
  (`HF_PYTHON=~/.venvs/hf1/bin/python`); đừng cài vào venv pipeline (xung đột
  numpy<2 của fasttext).

### 4.4 rclone bị Google rate-limit (`userRateLimitExceeded`)
- **Nguyên nhân**: dùng `client_id` mặc định chia sẻ cho mọi người.
- **Xử lý**: tạo OAuth `client_id` riêng (`rclone config` → *Make your own
  client_id*), giảm `--transfers`/`--tpm`, chạy lại (resumable, không mất dữ liệu).

### 4.5 OAuth `403 access_denied` khi authorize
- **Nguyên nhân**: OAuth consent screen ở trạng thái **Testing**, account chưa nằm
  trong Test users; token ở Testing hết hạn sau 7 ngày.
- **Xử lý**: thêm account vào **Test users** + **Publish app**.

## 5. Verify / ledger

### 5.1 `rclone check` báo thiếu file nhưng thực tế đã upload
- Chạy lại `verify_unit.sh` (lần check trước có thể bị ngắt giữa chừng).
- Chỉ `mark-verified` khi log kết thúc exit 0 **và** không có dòng
  `ERROR`/`missing`.

### 5.2 HF gắn tag `modality:video` / `modality:image` dù chỉ có audio
- HF tự suy modality từ đuôi file (`.webm` là container video). Card có tag
  `audio` để ép; spec card **không có** field để gỡ `video`/`image` — chấp nhận
  và ghi chú trong card.

### 5.3 `corpus_ledger.py report` lệch so với thực tế
- Ledger là **append-only**: nếu từng append trùng unit, dùng `list`/`pending`
  đối chiếu; sửa bằng cách append bản ghi đính chính, **đừng** sửa tay JSONL.

## 6. Môi trường

| Triệu chứng | Xử lý |
|---|---|
| `yt-dlp: command not found` | `./scripts/install_system_deps.sh`, thêm `~/.local/bin` vào `PATH` |
| `ffmpeg`/`sox` not found | như trên (micromamba env + symlink) |
| `ModuleNotFoundError: paths` | chạy từ trong repo, hoặc dùng đường dẫn tuyệt đối tới script |
| `Permission denied` khi chạy `.sh` | `chmod +x <file>` |
| Muốn kiểm tra tổng thể | `./scripts/check_env.sh` · `make check` · `make smoke` |

## 7. Báo lỗi mới

Khi thêm mục mới, ghi theo mẫu: `triệu chứng` (copy nguyên dòng log) →
`nguyên nhân` → `cách xử lý` + `cách phòng ngừa`. Không dán token/cookie/đường
dẫn nhà riêng vào tài liệu (xem `SECURITY.md`).

- `faster-whisper` nhanh hơn `openai-whisper` cùng model.
