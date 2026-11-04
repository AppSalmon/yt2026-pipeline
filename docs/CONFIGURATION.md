# CONFIGURATION — toàn bộ biến cấu hình

Thứ tự ưu tiên (cao → thấp):

```
biến môi trường đã export  >  config.env  >  giá trị mặc định trong script
```

- Shell đọc qua `source config.env` (mọi biến viết dạng `${VAR:-default}`).
- Python đọc qua `metadata/paths.py` (env > `config.env` > `_FALLBACK`).
- Cần override riêng của máy: tạo `config.local.env` (đã gitignore) rồi
  `set -a; . ./config.local.env; set +a` trước khi chạy.

## ⓵ Ngôn ngữ

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LANG_CODE` | `vi` | ISO 639-1 ngôn ngữ **chính**; dùng cho format selector `[language^=xx]`, LID, HF card |
| `ACCEPT_LANGS` | `$LANG_CODE,en` | Danh sách ngôn ngữ Whisper **giữ lại** (phần còn lại bị skip) |
| `ISO_639_2` | `vie` | Mã 3 ký tự cho forced alignment + uroman (`tha`, `ind`, `mya`, `khm`…) |
| `LANG_NAME` / `LANG_NAME_EN` | `Vietnamese` | Tên hiển thị trong HF card (chỉ `make_hf_card.py`) |

## ⓶ Đường dẫn dữ liệu (ngoài repo)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DATA_ROOT` | `$HOME/data` | gốc mọi dữ liệu |
| `DOWNLOAD_DIR` | `$DATA_ROOT/download_from_youtube` | audio thô + `*.info.json`, mỗi kênh 1 thư mục |
| `DATASET_DIR` | `$DATA_ROOT/dataset` | index, QC flags, batch/unit, hardlink, `_logs/` |
| `LEDGER_FILE` | `$DATA_ROOT/corpus_ledger.jsonl` | sổ cái corpus (chống trùng + trạng thái verify) |
| `SAVE_DIR` | `$DATA_ROOT/output_trans` | output convert+transcribe (`run_pipeline.sh`) |
| `ALIGN_DIR` / `ANNOT_DIR` / `FILTER_DIR` | `./output_*` trong repo | output align / detect / filter (**nên** trỏ ra ngoài) |
| `INDEX_FILE` | `$DATASET_DIR/index.jsonl` | index kiểm toán ngày đăng |
| `LID_MODEL` | `models/lid.176.ftz` | model fastText LID |

> `download_from_youtube.sh` **từ chối** chạy nếu `DOWNLOAD_DIR` resolve vào trong
> repo (exit code `2`), trừ khi `ALLOW_IN_REPO_DOWNLOAD=1`.

## ⓷ Crawl

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MIN_UPLOAD_DATE` | `20260101` | chỉ nhận video đăng từ ngày này (`YYYYMMDD`) |
| `DATE_AFTER` | `$MIN_UPLOAD_DATE` | override riêng cho yt-dlp |
| `AUDIO_FORMAT` | `ba[language^=$LANG_CODE][acodec=opus][abr>=60]/…/ba` | format selector 4 tầng (xem dưới) |
| `MAX_VIDEOS` | `50` | video MỚI tối đa mỗi **tab** mỗi lượt (`--max-downloads`) ⇒ ×3 tab |
| `TABS` | `videos shorts streams` | tab sẽ crawl (`/streams` = past live) |
| `MIN_DURATION` / `MAX_DURATION` | `0` / (trống) | lọc theo độ dài (giây) |
| `WALK_LIMIT` / `WALK_SLACK` | `1` / `MAX_VIDEOS+20` | số mục playlist quét tới; `WALK_LIMIT=0` để tắt |
| `RETRIES` / `FRAGMENT_RETRIES` | `10` / `10` | chịu mạng chập chờn |
| `SLEEP_REQUESTS` / `SLEEP_INTERVAL` / `MAX_SLEEP_INTERVAL` | `1` / `3` / `6` | giãn request giảm 429 |
| `SKIP_AFTER_ERRORS` | `5` | bỏ phần còn lại của tab sau N lỗi liên tiếp |
| `COOKIES_FILE` | (trống) | Netscape cookies — mặc định **không dùng**, xem lưu ý bên dưới |
| `EXTRA_OPTS` | (trống) | args yt-dlp thêm (`--playlist-items 1:3`, `--simulate`…) |
| `JOBS` | `2` | số kênh crawl song song (`crawl_all.sh`) |
| `RETRY_CHANNEL` | `2` | số lần chạy lại 1 kênh lỗi |
| `BATCH_LABEL` | `crawl` | nhãn cho `crawler/log/run_<label>_summary.csv` |

**`AUDIO_FORMAT`** — chuỗi ưu tiên giảm dần:
1. `opus` + `language^=<LANG_CODE>` + `abr>=60` (medium tier)
2. `opus` + `language^=<LANG_CODE>` (bitrate bất kỳ)
3. audio track bất kỳ của ngôn ngữ đó (`m4a` khi không có opus)
4. `ba` — best audio (video cũ không có metadata ngôn ngữ → QC xử lý sau)

**Cookies**: đã kiểm chứng là **cookie hợp lệ vẫn bị YouTube chặn request media từ
IP datacenter**. Chỉ bật sau khi `crawler/check_cookies.sh <file>` trả verdict
`ok (usable)`. Xem `crawler/cookies/README.md`.

## ⓸ Đóng gói / sổ cái

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TARGET_HOURS` | `50000` | mục tiêu corpus (giờ) cho `corpus_ledger.py report`, `make_unit.py` |
| `MIN_FREE_GB` / `MIN_FREE_HARD_GB` | `50` / `20` | cảnh báo / dừng khi dung lượng staging thấp |

Cờ CLI hay dùng:

| Script | Cờ |
|---|---|
| `metadata/make_batch.py` | `--limit-gb`, `--max-part-size` (20G), `--verify`, `--hardlink`, `--dry-run`, `--no-hash` |
| `metadata/make_unit.py` | `--target-hours`, `--units-dir`, `--dry-run`, `--allow-duplicate-ids` |
| `metadata/corpus_ledger.py` | `append`, `mark-verified`, `report`, `list`, `pending`, `push` |
| `metadata/audio_qc.py` | `--silence-check`, `--min-bitrate`, `--duration-mismatch-tol` |
| `metadata/build_index.py` | `--min-upload-date`, `--strict`, `--strict-window` |

## ⓹ Upload / sync

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GDRIVE_PARENT` | `gdrive:corpus` | thư mục gốc corpus trên Drive (rclone remote) |
| `GDRIVE_REMOTE` | `$GDRIVE_PARENT` | fallback cho `upload_batch.sh` / `verify_remote.sh` |
| `HF_ORG` | (trống) | tài khoản/tổ chức HF mặc định ⇒ `repo_id = $HF_ORG/<unit>` |
| `HF_TOKEN` | (trống) | ưu tiên `hf auth login` (token trong `~/.cache/huggingface/token`) |
| `HF_HUB_DISABLE_XET` | `1` | `1` = ép LFS (Xet có thể rất chậm); `0` để thử lại Xet |
| `HF_PYTHON` | `~/.venvs/hf1/bin/python` → `~/.hf-cli/venv/bin/python` | venv riêng cho HF (tránh xung đột numpy/torch) |
| `MAX_UPLOAD_PER_RUN` / `NUM_WORKERS` | tuỳ script | giới hạn số file / số worker mỗi lượt |

## ⓺ Exit code của `crawler/download_from_youtube.sh`

| Code | Nghĩa |
|---|---|
| `0` | OK (có thể có lỗi lẻ tẻ ở vài video) |
| `1` | **tất cả** invocation fail (kênh 404/bị chặn/mất mạng) |
| `2` | từ chối vì đường dẫn download nằm trong repo |
| `3` | hết dung lượng staging (`MIN_FREE_HARD_GB`) |

## ⓻ Cờ QC trong `$DATASET_DIR/qc_flags.jsonl`

| Cờ | Xử lý |
|---|---|
| `corrupt`, `zero_size`, `wrong_language`, `out_of_window` | **LOẠI** (ghi vào `exclude.txt`) |
| `language_unverified`, `too_short`, `too_long`, `low_bitrate`, `silent_heavy`, `duration_mismatch`, `date_missing`, `no_info_json` | **CẢNH BÁO** (vẫn giữ, để rà soát) |

`wrong_language` là lớp bảo vệ chống video lồng tiếng/đa ngôn ngữ: LID trên toàn
file phải khớp `LANG_CODE` (hoặc `ACCEPT_LANGS`).
