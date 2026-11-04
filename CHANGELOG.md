# CHANGELOG

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/),
phiên bản theo [SemVer](https://semver.org/lang/vi/).

## [0.1.0] — 2026-11-04

Bản đầu tiên được đóng gói để chia sẻ nội bộ, dùng lại được cho nhiều ngôn ngữ.

### Thêm mới

- **Tài liệu vận hành đầy đủ**: `README.md` + `README.en.md` + `docs/{SETUP,
  CONFIGURATION,OPERATIONS,ADD_LANGUAGE,ARCHITECTURE,DATA_LAYOUT,TROUBLESHOOTING,
  ETHICS_AND_LICENSE}.md`.
- **`LANG_CODE` / `ACCEPT_LANGS` / `ISO_639_2`** trong `config.env`: đổi ngôn ngữ
  không cần sửa code (format selector `[language^=$LANG_CODE]`, Whisper keep-list,
  ISO 639-2 cho alignment).
- `crawler/langs/<code>/keywords.txt` + `crawler/discover_channels.py
  --keywords-file` (mỗi ngôn ngữ một bộ từ khoá).
- `crawler/channels.example.txt`, `crawler/langs/vi/{keywords,channels_sample}.txt`
  thay cho danh sách kênh thật.
- `scripts/{install_system_deps,download_models,check_env}.sh`, `Makefile`,
  `requirements.txt`, `SECURITY.md`, `CONTRIBUTING.md`, `NOTICE`.
- `examples/whisper_segment/`: 2 script demo (đã bỏ path tuyệt đối) minh hoạ
  Whisper tự chia segment + dump token thô.
- `models/README.md`, `crawler/log/.gitkeep`.

### Thay đổi

- Toàn bộ đường dẫn mặc định chuyển sang `$HOME` (`DATA_ROOT=$HOME/data`), không
  còn path tuyệt đối của máy phát triển.
- `metadata/paths.py`: fallback đọc `$HOME`, thêm `LANG_CODE`, `ACCEPT_LANGS`,
  `ISO_639_2`, `GDRIVE_*`, `HF_ORG`.
- `metadata/make_hf_card.py`: front matter (`language`, `pretty_name`, tags) và
  tiêu đề sinh theo `LANG_CODE`/`LANG_NAME`; `--repo` mặc định lấy từ `HF_ORG`;
  cảnh báo rõ khi sinh card cho ngôn ngữ khác tiếng Việt.
- `crawler/download_from_youtube.sh`: `DATE_AFTER` lấy từ `MIN_UPLOAD_DATE`,
  `AUDIO_FORMAT` build từ `LANG_CODE`.
- `run_pipeline.sh`: `LANG`/`ACCEPT_LANGS`/`ISO_639_2` đọc từ env,
  `--min-upload-date` lấy từ `MIN_UPLOAD_DATE`.
- `convert_transcribe/convert_and_transcribe.py`: default `--lang` /
  `--accept-langs` lấy từ `$LANG_CODE` / `$ACCEPT_LANGS`.
- GDRIVE mặc định trung tính hoá: `gdrive:corpus` (thay tên thư mục riêng).

### Loại bỏ

- Không còn đưa vào repo: audio mẫu (`*.wav`), log crawl, archive `audios_*.txt`,
  danh sách kênh/candidates thật, model `lid.176.ftz`, tarball uroman, file
  `*.bak_*`, `__pycache__`.
- Không đưa nhật ký vận hành nội bộ (`PROJECT_STATUS.md`, `HANDOVER.md`) vào repo;
  nội dung kỹ thuật đã được viết lại (đã khử định danh) trong `docs/`.

### Ghi chú

- Hành vi của pipeline tiếng Việt **không đổi**: mọi default vẫn là `vi` /
  `vie` / `vi,en` / `20260101`, chỉ khác là giờ đây đọc từ `config.env`.
