# ARCHITECTURE — kiến trúc & vai trò từng file

## 1. Nguyên tắc

1. **Một nguồn sự thật cho dữ liệu**: `config.env` (shell) + `metadata/paths.py`
   (Python) đọc cùng file. Env ngoài luôn override.
2. **Repo = code.** Audio + mọi output nằm ngoài (`$DATA_ROOT`).
3. **Chống trùng 3 tầng**: `crawler/log/audios_*` (yt-dlp archive) →
   `$DATASET_DIR/used_ids.txt` → `corpus_ledger.jsonl`.
4. **Chỉ xoá local sau khi verify 2 nơi** (`ledger.verified = true`).
5. **Ngôn ngữ là tham số**, không phải hằng số (xem `docs/ADD_LANGUAGE.md`).

## 2. Các giai đoạn (W1–W8)

```
                 ┌──────────────────────────────────────────────────────────┐
 LANG_CODE  ────►│ W1 crawler/download_from_youtube.sh (yt-dlp, audio-only)  │
 MIN_UPLOAD_DATE │    ├─ /videos + /shorts + /streams, lọc is_live            │
                 │    ├─ --download-archive crawler/log/audios_<ch>_<tab>.txt│
                 │    └─ --write-info-json  (kiểm toán ngày đăng)            │
                 └───────────────┬──────────────────────────────────────────┘
                                 ▼  $DOWNLOAD_DIR/<channel>/…
                 ┌──────────────────────────────────────────────────────────┐
        W2       │ metadata/build_index.py   → index.jsonl  (+ audit 2026)   │
        W3       │ metadata/audio_qc.py      → qc_flags.jsonl, exclude.txt  │
                 │ metadata/stats.py         → thống kê READ-ONLY            │
                 └───────────────┬──────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────┐
        W4       │ metadata/make_unit.py   → units/<unit>/{manifest,files,   │
                 │                            UNIT.json,stats,SHA256SUMS}    │
                 │ metadata/make_batch.py  → batch_NNN/ tar 20G (tuỳ chọn)   │
                 │ metadata/make_hf_card.py→ README.md (dataset card)        │
                 └───────────────┬──────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────┐
        W5       │ metadata/corpus_ledger.py → corpus_ledger.jsonl           │
                 └───────────────┬──────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────┐
        W6       │ sync/upload_unit.sh (rclone → Drive)                      │
                 │ sync/upload_hf_retry.sh → upload_unit_hf.py (HF, chunk)   │
        W7       │ sync/verify_unit.sh + verify_unit_hf.sh  ← BẮT BUỘC       │
        W8       │ sync/cleanup_local.sh / metadata/cleanup_local.py         │
                 └──────────────────────────────────────────────────────────┘
```

Nhánh **transcribe → align → segment** (tuỳ chọn, thường chạy sau, cần GPU):

```
convert_transcribe/convert_and_transcribe.py  → $SAVE_DIR/corpus/*.wav + *.txt
force_alignment/force_align.sh (+ utils/force_alignment/, utils/uroman/)
                                              → *_manifest.jsonl
codeswitch/detect_codeswitch.py               → manifest + languages/is_codeswitch
segmentation/filter_manifest.py               → output_filter/{all,codeswitch}/*.jsonl
segmentation/segment.sh                       → segment WAV theo manifest
```

## 3. Naming convention

| Đối tượng | Dạng | Ghi chú |
|---|---|---|
| File audio thô | `<upload_date>#<title>#<channel_id>#<video_id>_<duration>.{webm,m4a}` | sinh bởi yt-dlp `-o` trong `download_from_youtube.sh` |
| Info JSON | cùng tên + `.info.json` | nguồn kiểm toán `upload_date`, `duration` |
| Thư mục kênh | tên kênh (đã sanitize) hoặc `UCxxxx` | **đừng đổi** giữa các lần chạy: archive `audios_*` gắn với tên thư mục |
| Unit | `yt2026_batch01_10kh` (ví dụ) | `<prefix>_batch<NN>_<số-giờ>kh`, do bạn đặt |
| Segment id | `<video_id>-<i>` | ổn định, dùng để truy vết & takedown |
| Record JSONL | 1 dòng JSON | `ensure_ascii=False`, UTF-8 |

Truy vết ngược: `video_id` → `https://www.youtube.com/watch?v=<video_id>`
(mọi manifest/batch đều giữ `video_id`, `channel_id`, `upload_date`).

## 4. Hai chế độ đóng gói

| | `make_batch.py` | `make_unit.py` |
|---|---|---|
| Đơn vị | tar không nén, split 20 G | danh sách file (`files.txt`) + manifest |
| Ưu điểm | ít object, upload thô nhanh, archive gọn | resume tốt, HF không bị 429 vì chia chunk, verify theo file |
| Nhược điểm | verify theo file phải mở tar | nhiều object (hàng chục nghìn file) |

## 5. Vai trò từng file

### Gốc repo

| File | Vai trò |
|---|---|
| `config.env` | nguồn sự thật cho đường dẫn + ngôn ngữ (shell source) |
| `run_pipeline.sh` | driver 1 lệnh: `crawl/convert/align/detect/filter/segment/index/all` |
| `requirements.txt` | Python packages |
| `Makefile` | `make check` (bash -n, py_compile, secrets), `make smoke`, `make deps`, `make models` |
| `scripts/install_system_deps.sh` | ffmpeg/ffprobe/sox (micromamba) + rclone + yt-dlp, không sudo |
| `scripts/download_models.sh` | tải `models/lid.176.ftz` (+ `.bin` tuỳ chọn) |
| `scripts/check_env.sh` | kiểm tra READ-ONLY toàn bộ môi trường, exit 1 nếu FAIL |

### `crawler/`

| File | Vai trò |
|---|---|
| `download_from_youtube.sh` | tải audio 1 danh sách kênh; format selector theo `LANG_CODE`; từ chối path trong repo (exit 2), dừng khi hết đĩa (exit 3) |
| `crawl_all.sh` | chạy song song `JOBS` kênh, retry, ghi `log/run_<label>_summary.csv` |
| `discover_channels.py` | search YouTube theo từ khoá → `candidates*.tsv` (không tải media) |
| `check_channels.sh` | kiểm kênh còn sống + có video trong cửa sổ thời gian (không tải media) |
| `estimate_channels.sh` | ước lượng số video/giờ của danh sách kênh |
| `backlog.sh` | đo backlog (video chưa tải) per kênh, sinh danh sách ưu tiên |
| `check_cookies.sh` | test **tải thật** với file cookie, verdict `ok (usable)` |
| `cookies/README.md` | chính sách cookie (mặc định KHÔNG dùng) |
| `channels.example.txt` | mẫu danh sách kênh (copy → `channels.txt`) |
| `langs/<code>/keywords.txt` | từ khoá discovery theo ngôn ngữ |
| `langs/vi/channels_sample.txt` | 12 kênh tiếng Việt thật, để hình dung format |

### `convert_transcribe/`, `force_alignment/`, `codeswitch/`, `segmentation/`

| File | Vai trò |
|---|---|
| `convert_transcribe/convert_and_transcribe.py` | ffmpeg → 16 kHz mono WAV + Whisper; `--accept-langs` giữ nhiều ngôn ngữ |
| `force_alignment/force_align.sh` | wrapper MMS CTC alignment; tham số 3 = `ISO_639_2` |
| `force_alignment/force_align_from_list.sh` | chạy align cho danh sách file |
| `force_alignment/calculate_precision.py` | đo precision/recall của alignment so với transcript |
| `utils/force_alignment/{align,align_utils,text_normalization,norm_config}.py` | code align gốc (copy từ GigaSpeech2) |
| `codeswitch/detect_codeswitch.py` | LID cấp token → `languages`, `is_codeswitch`, `upload_date` |
| `segmentation/filter_manifest.py` | charset + duration + upload-date + code-switch filter (**sửa khi đổi ngôn ngữ**) |
| `segmentation/segment.sh` | cắt WAV theo manifest (1 dir) |
| `segmentation/segment_from_list.sh`, `segment_from_manifests.py` | cắt theo danh sách manifest |

### `metadata/`

| File | Vai trò |
|---|---|
| `paths.py` | đọc `config.env` + fallback `$HOME`, guard "data ngoài repo" |
| `stats.py` | thống kê nhanh file/giờ/GB/per-channel (READ-ONLY, chạy được khi đang crawl) |
| `build_index.py` | `index.jsonl` + audit ngày đăng (`--strict`) |
| `audio_qc.py` | QC: corrupt, zero size, sai ngôn ngữ, bitrate, silence → `qc_flags.jsonl` |
| `make_unit.py` | đóng gói unit (files.txt + manifest + stats + SHA256SUMS) |
| `make_batch.py` | đóng gói batch tar split 20 G + meta.tar.gz + SHA256SUMS |
| `make_hf_card.py` | sinh dataset card (front matter theo `LANG_CODE`) |
| `corpus_ledger.py` | sổ cái: `append/mark-verified/report/list/pending/push` |
| `cleanup_local.py` | xoá local **chỉ** khi `ledger.verified = true` |

### `sync/`, `cron/`, `examples/`, `utils/uroman/`, `models/`

| File | Vai trò |
|---|---|
| `sync/upload_unit.sh` | rclone copy theo `files.txt` → `$GDRIVE_PARENT/<unit>/` |
| `sync/verify_unit.sh` | `rclone check --checksum` (Drive) |
| `sync/upload_unit_hf.sh` + `upload_unit_hf.py` | upload HF theo chunk kênh (resume) |
| `sync/upload_hf_retry.sh` | supervisor: tự thử lại + backoff khi 429 |
| `sync/upload_batch.sh`, `verify_remote.sh` | chuỗi batch kiểu tar (cũ hơn) |
| `sync/cleanup_local.sh` | xoá local sau verify |
| `sync/install_rclone.sh` | cài rclone không cần sudo |
| `cron/crawl_weekly.sh` | driver định kỳ cả chuỗi W1→W8 |
| `cron/watch_crawl.sh` | watchdog tmux (tự restart nếu session chết) |
| `examples/whisper_segment/*` | demo độc lập: Whisper chia segment + dump token thô |
| `utils/uroman/` | uroman (MIT, vendored) — romanize text cho alignment |
| `models/` | chỗ đặt `lid.176.ftz` (không commit) |

| Dùng khi | lưu trữ dài hạn / Drive | phát hành HF / nhiều đợt nhỏ |
