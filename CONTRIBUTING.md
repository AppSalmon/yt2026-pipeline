# CONTRIBUTING — convention & quy trình

## Nguyên tắc bất di bất dịch

1. **Code only.** Không commit audio, log crawl, danh sách kênh đang khai thác,
   cookie, token, model nhị phân. Xem [`SECURITY.md`](SECURITY.md).
2. **Dữ liệu luôn ngoài repo.** Mọi đường dẫn đi qua `config.env`
   (`$DATA_ROOT`, `$DOWNLOAD_DIR`, `$DATASET_DIR`, `$LEDGER_FILE`) hoặc
   `metadata/paths.py`. Không hard-code path tuyệt đối của máy mình.
3. **Không phá tính đa ngôn ngữ.** Mọi thứ phụ thuộc ngôn ngữ phải lấy từ
   `LANG_CODE` / `ACCEPT_LANGS` / `ISO_639_2` — xem [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md).
4. **Idempotent + chống trùng.** Crawl/đóng gói phải chạy lại an toàn
   (`--download-archive`, `used_ids.txt`, `corpus_ledger.jsonl`).
5. **Không tự xoá dữ liệu.** Upload → verify **cả 2 nơi** → báo người vận hành
   lệnh xoá; script chỉ xoá khi `ledger.verified = true`.

## Convention code

| Loại | Quy ước |
|---|---|
| Shell | `#!/usr/bin/env bash` + `set -euo pipefail`; `source` `config.env`; comment tiếng Việt; đường dẫn tính từ `$(dirname "${BASH_SOURCE[0]}")` |
| Python | Python 3.10+; `argparse` với `--help` rõ ràng; import `paths` để đọc config; không hard-code path |
| Tên file | snake_case; script chạy được đặt quyền `chmod +x` |
| Log | ghi vào `$DATASET_DIR/_logs/` hoặc `crawler/log/` (đều nằm ngoài git) |
| Output | JSONL (1 record/dòng), UTF-8, `ensure_ascii=False` |

## Trước khi mở PR

```shell
make check        # bash -n + py_compile + quét secret
make smoke        # paths.py + resolve config.env
```

Với thay đổi ảnh hưởng crawl/upload, ghi rõ trong PR:

- đã chạy **pilot** bao nhiêu kênh/video và kết quả (`crawler/log/run_*_summary.csv`);
- có đổi **hành vi mặc định** không (nếu có, cập nhật `CHANGELOG.md` và
  `docs/CONFIGURATION.md`);
- đã kiểm với ngôn ngữ nào (`LANG_CODE`), vì đó là điểm dễ vỡ nhất.

## Thêm ngôn ngữ mới

Không cần PR vào code nếu chỉ đổi ngôn ngữ: export biến môi trường là đủ. Nếu
charset filter / HF card chưa phù hợp ngôn ngữ của bạn, PR nên:

1. sửa `segmentation/filter_manifest.py` (thêm Unicode range, **giữ** filter cũ);
2. thêm `crawler/langs/<code>/keywords.txt` (+ `channels_sample.txt` nếu muốn);
3. cập nhật bảng trong `docs/ADD_LANGUAGE.md`;
4. ghi `CHANGELOG.md`.

## Commit message

```
<area>: <mô tả ngắn ở thể mệnh lệnh>

Ví dụ:
crawler: thêm --keywords-file cho discover_channels.py
docs: bổ sung bảng Unicode range theo ngôn ngữ
sync: tách GDRIVE_PARENT khỏi GDRIVE_REMOTE
```
