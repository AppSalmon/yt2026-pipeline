# models/ — model nhị phân KHÔNG commit vào repo

Thư mục này để trống trong git (chỉ giữ `.gitkeep`). Tải model bằng script:

```shell
./scripts/download_models.sh
```

| File | Dùng cho | Nguồn | License |
|---|---|---|---|
| `lid.176.ftz` (938 KB) | `codeswitch/detect_codeswitch.py` — LID cấp token | https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz | CC-BY-SA 3.0 (fastText) |

Vì sao không commit: license CC-BY-SA (không hợp với Apache-2.0 của repo) và
model là artifact nhị phân tải lại được. Bản đầy đủ `lid.176.bin` (~126 MB)
cho kết quả tốt hơn nhưng chậm hơn — đặt tên `models/lid.176.bin` và trỏ
`--lid-model models/lid.176.bin` nếu cần.

Model khác được tải tự động ở lần chạy đầu (không đặt trong repo):
- Whisper (`faster-whisper`): `$HOME/.cache/huggingface/hub`
- MMS CTC forced alignment (~1.2 GB): `$HOME/.cache/torch`
- uroman: đã vendor sẵn tại `utils/uroman/` (MIT)
