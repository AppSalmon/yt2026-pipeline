> Mục lục tài liệu: xem [`docs/`](docs/) · Chạy cho ngôn ngữ khác: [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md) · English: [`README.md`](README.md)

# YouTube Speech Crawl Pipeline — audio-only acquisition cho corpus ASR

Pipeline thu thập **audio nói tự nhiên từ YouTube** để xây corpus ASR theo ngôn ngữ,
dựa trên cấu trúc [GigaSpeech2](https://github.com/SpeechColab/GigaSpeech2).
Bản gốc dùng cho **tiếng Việt (code-switch Việt–Anh)**; toàn bộ phần ngôn ngữ đã
được **parameter hoá** để chạy cho ngôn ngữ khác (Thái, Indonesia, Myanmar, Khmer…)
chỉ bằng vài biến môi trường.

> **Ghi chú:** project cá nhân, viết ngoài giờ làm việc — không liên quan đến
> tổ chức/công ty nào.

> Nguyên tắc cốt lõi: **repo chỉ chứa code**. Audio crawl về và mọi dữ liệu phái
> sinh nằm ngoài repo, điều khiển bởi duy nhất một file: [`config.env`](config.env).

## Pipeline làm gì

```
crawler/download_from_youtube.sh   yt-dlp: audio-only, --dateafter $MIN_UPLOAD_DATE,
                                   lọc livestream, crawl /videos + /shorts + /streams,
                                   --write-info-json (kiểm toán ngày đăng)
        │  $DOWNLOAD_DIR/<channel>/<date>#<title>#<channel_id>#<video_id>_<dur>.{webm,m4a}
        ▼
convert_transcribe/convert_and_transcribe.py
                                   ffmpeg → WAV 16 kHz mono + Whisper transcribe
                                   (--accept-langs giữ nhiều ngôn ngữ: không loại code-switch)
        │  corpus/{<chan>__}{video_id}_{dur}.wav + .txt
        ▼
force_alignment/force_align.sh     MMS CTC forced alignment (torchaudio + uroman,
                                   ISO 639-2 = $ISO_639_2) → *_manifest.jsonl
        ▼
codeswitch/detect_codeswitch.py    LID cấp token (fastText lid.176) → languages /
                                   is_codeswitch / upload_date trong manifest
        ▼
segmentation/filter_manifest.py    lọc: charset ngôn ngữ, duration 2–30 s,
                                   upload_date >= $MIN_UPLOAD_DATE
        │  output_filter/all/*.jsonl   và   output_filter/codeswitch/*.jsonl
        ▼
segmentation/segment.sh            cắt WAV theo manifest → corpus segment cuối
        │
        ▼
metadata/{stats,build_index,audio_qc}.py
                                   thống kê nhanh, index + audit ngày đăng, QC audio
metadata/{make_batch,make_unit,corpus_ledger}.py
                                   đóng gói batch/unit + sổ cái chống trùng
        ▼
sync/{upload_unit,upload_unit_hf,verify_unit,upload_hf_retry}.sh
                                   upload Google Drive + HuggingFace, verify checksum
sync/cleanup_local.sh              chỉ xoá local khi ledger.verified = true
cron/crawl_weekly.sh               driver định kỳ (crawl → audit → QC → đóng gói →
                                   upload → verify → ledger → cleanup)
```

Giai đoạn đang dùng là **AUDIO-ONLY acquisition** (W1–W8): crawl → QC → đóng gói →
upload → verify → sổ cái. Các bước transcribe/align/segment ở trên đã có sẵn code và
chạy được, nhưng tốn GPU/thời gian nên thường tách sang giai đoạn sau.

Sơ đồ chi tiết + vai trò **từng file**: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start (5 phút)

```shell
# 1) tool hệ thống (KHÔNG cần sudo): ffmpeg + ffprobe + sox + rclone
./scripts/install_system_deps.sh

# 2) Python packages + model LID
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./scripts/download_models.sh

# 3) kiểm tra môi trường (READ-ONLY, ~10 lệnh)
./scripts/check_env.sh

# 4) danh sách kênh của bạn
cp crawler/channels.example.txt crawler/channels.txt
$EDITOR crawler/channels.txt            # [tên]<TAB>[@handle | channel/UCxxxx]

# 5) crawl pilot: 3 video + 3 short mỗi kênh (dữ liệu ghi ra $DOWNLOAD_DIR)
EXTRA_OPTS="--playlist-items 1:3" BATCH_LABEL=pilot \
  ./crawler/crawl_all.sh crawler/channels.txt "" 2

# 6) xem đang có gì: file / giờ / GB / từng kênh
python3 metadata/stats.py
```

Chạy tiếp transcribe → align → filter → segment → index:


## Dùng cho NGÔN NGỮ KHÁC (mục đích chính của repo này)

```shell
export LANG_CODE=th            # ISO 639-1 của ngôn ngữ bạn crawl
export ACCEPT_LANGS=th,en      # các ngôn ngữ Whisper sẽ GIỮ (code-switch)
export ISO_639_2=tha           # mã 3 ký tự cho forced alignment / uroman

# 1) từ khoá discovery cho ngôn ngữ đó
cp crawler/langs/vi/keywords.txt crawler/langs/th/keywords.txt   # rồi sửa
python3 crawler/discover_channels.py \
  --keywords-file crawler/langs/th/keywords.txt \
  --num-per-keyword 40 --output crawler/candidates_th.tsv

# 2) duyệt tay candidates_th.tsv → dán vào crawler/channels_th.txt → kiểm kênh
./crawler/check_channels.sh crawler/channels_th.txt

# 3) crawl (format selector tự dùng [language^=th])
./crawler/crawl_all.sh crawler/channels_th.txt "" 2
```

**Checklist 10 điểm cần đổi** (trong đó chỉ **1 điểm phải sửa code**: charset
filter) → [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md).

## Kết quả đã publish (mẫu tham chiếu)

4 unit đầu tiên đã đi hết chuỗi **crawl → QC → đóng gói → upload → verify**. Xem
link + số liệu thật để biết "đích đến" khi chạy pipeline cho ngôn ngữ của bạn.

| Unit | HuggingFace (gated: manual) | Giờ | Audio files | GB (SI) | Kênh |
|---|---|---|---|---|---|
| `yt2026_batch01_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch01_10kh | 11.911,8 | 20.468 | 624,3 | 307 |
| `yt2026_batch02_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch02_10kh | 11.884,0 | 17.754 | 624,7 | 320 |
| `yt2026_batch03_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch03_10kh | 13.204,7 | 36.088 | 683,4 | 702 |
| `yt2026_batch04_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch04_10kh | 12.148,5 | 20.678 | 638,7 | 436 |
| **Tổng** | 4 unit | **49.149,0 h** | **94.988** | **2.571 GB ≈ 2,39 TiB** | — |

- Số liệu lấy từ `corpus_ledger.jsonl` (chốt 2026-10-23) + HF tree API (2026-11-04).
- Chỉ nhận video **đăng từ 2026-01-01** — kiểm được từng clip qua `upload_date`
  trong `manifest.jsonl`; không trùng corpus phát hành trước 2026.
- Dataset đặt **gated = manual** (phải bấm đồng ý trên trang HF mới tải được).
- Mỗi unit gồm `manifest.jsonl`, `files.txt`, `stats.json`, `SHA256SUMS` + dataset
  card do `metadata/make_hf_card.py` sinh — đúng cấu trúc pipeline của bạn sẽ tạo ra.
- Audio giữ nguyên `.webm` (Opus 48 kHz mono, **không re-encode**), có `info.json`
  gốc để truy vết `video_id` → `https://www.youtube.com/watch?v=<video_id>`.


## Cấu hình

Mọi thứ đọc từ [`config.env`](config.env); biến môi trường ngoài **luôn** override.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LANG_CODE` | `vi` | ISO 639-1 ngôn ngữ chính (format selector + LID + HF card) |
| `ACCEPT_LANGS` | `$LANG_CODE,en` | ngôn ngữ Whisper giữ lại (code-switch) |
| `ISO_639_2` | `vie` | mã 3 ký tự cho forced alignment / uroman |
| `DATA_ROOT` | `$HOME/data` | gốc chứa toàn bộ dữ liệu (ngoài repo) |
| `DOWNLOAD_DIR` | `$DATA_ROOT/download_from_youtube` | audio thô + `*.info.json` |
| `DATASET_DIR` | `$DATA_ROOT/dataset` | index, QC flags, batch/unit, hardlink |
| `LEDGER_FILE` | `$DATA_ROOT/corpus_ledger.jsonl` | sổ cái corpus (chống trùng, verify) |
| `MIN_UPLOAD_DATE` | `20260101` | chỉ nhận video đăng từ ngày này (YYYYMMDD) |
| `TARGET_HOURS` | `50000` | mục tiêu corpus (giờ) |
| `MAX_VIDEOS` | `50` | video MỚI tối đa mỗi tab mỗi lượt (`--max-downloads`) |
| `GDRIVE_PARENT` | `gdrive:corpus` | đích rclone trên Google Drive |
| `HF_ORG` | (trống) | tài khoản/tổ chức HuggingFace mặc định |

Bảng **đầy đủ** (30+ biến, exit code, cờ QC): [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## Tài liệu

| File | Nội dung |
|---|---|
| [`docs/SETUP.md`](docs/SETUP.md) | cài từ đầu (tool hệ thống, Python, model) + xác minh môi trường |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | toàn bộ biến cấu hình + thứ tự ưu tiên + exit code |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | runbook: crawl, monitor, QC, đóng gói, upload, verify, xoá local, cron |
| [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md) | **thêm ngôn ngữ mới** — 10 điểm cần đổi |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | kiến trúc, vai trò từng file, naming convention |
| [`docs/DATA_LAYOUT.md`](docs/DATA_LAYOUT.md) | cây dữ liệu + 3 tầng chống trùng + migrate server |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | lỗi đã gặp thật + cách xử lý (429, cookie, HF, rclone, Xet…) |
| [`docs/ETHICS_AND_LICENSE.md`](docs/ETHICS_AND_LICENSE.md) | ToS YouTube, bản quyền, chính sách phát hành |
| [`SECURITY.md`](SECURITY.md) | những gì **tuyệt đối không** commit |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | convention code + quy trình thay đổi |

README riêng từng thư mục: [`crawler/cookies/`](crawler/cookies/README.md),
[`cron/`](cron/README.md), [`sync/`](sync/README.md),
[`force_alignment/`](force_alignment/README.md), [`models/`](models/README.md),
[`examples/whisper_segment/`](examples/whisper_segment/README.md).

## Cảnh báo

- **ToS/bản quyền YouTube**: chỉ dùng cho nghiên cứu; **không redistribute audio
  gốc**. Xem [`docs/ETHICS_AND_LICENSE.md`](docs/ETHICS_AND_LICENSE.md).
- Repo **không chứa** cookie, token, audio hay link dataset riêng — xem
  [`SECURITY.md`](SECURITY.md).
- Whisper trên speech code-switch có thể nhầm phiên âm; rà ~50 segment ngẫu nhiên
  trước khi chạy lớn.
- Dung lượng: audio-only medium opus ≈ **42 MB/giờ** ⇒ 10.000 giờ ≈ 420 GB.
  Staging phải đủ lớn hoặc upload-rồi-xoá theo từng unit.

## Giấy phép

Code: **Apache-2.0** ([`LICENSE`](LICENSE)). Thành phần tái sử dụng + model bên
thứ ba: [`NOTICE`](NOTICE) (GigaSpeech2 Apache-2.0, uroman MIT, fastText lid.176
CC-BY-SA 3.0).

```shell
./run_pipeline.sh all
```

Từng bước riêng lẻ: `./run_pipeline.sh {crawl|convert|align|detect|filter|segment|index}`.
