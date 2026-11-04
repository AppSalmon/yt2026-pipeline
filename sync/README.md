# sync/ — W6: upload + verify + cleanup (rclone, không cần sudo)

Vòng đời một batch (KHÔNG được đảo thứ tự):

```
metadata/make_batch.py      ->  dataset/batch_NNN/  (audio parts + meta + SHA256SUMS)
        |
        v
sync/upload_batch.sh NNN    ->  rclone copy  ->  gdrive:corpus/batch_NNN/
        |                                          (resumable, retry, log)
        v
sync/verify_remote.sh NNN   ->  rclone check --checksum + số file
        |                          PASS  =>  ledger.verified = true
        v
sync/cleanup_local.sh NNN   ->  CHỈ KHI verified=true  ->  xoá audio + info.json local
                                   (giữ: log/audios_*.txt, batch folder, ledger)
```

## Cài đặt (1 lần, không sudo)

```shell
export PATH="$HOME/.local/bin:$PATH"
./sync/install_rclone.sh                 # tải binary vào ~/.local/bin
rclone config --auth-no-open-browser     # authorize Google Drive (thủ công, có browser)
rclone lsd gdrive:                       # phải liệt kê được thư mục => OK
```

Đặt `GDRIVE_REMOTE` trong `config.env` (mặc định `gdrive:corpus`).

## Yêu cầu dung lượng

| Hạng mục | Số liệu |
|---|---|
| Dung lượng corpus mục tiêu | 50,000 giờ ≈ **2.1 TB** (@ ~42MB/giờ medium opus) |
| Gói Drive tối thiểu | **≥ 5 TB** (gói 2TB KHÔNG đủ) |
| Giới hạn upload Google | ~**750 GB/ngày/tài khoản** → batch **300–400 GB** |
| Staging local | 1 đĩa **774 GB** → chỉ chứa được ~1–2 batch; phải upload rồi cleanup liên tục |

## Script

| Script | Việc | Ghi chú an toàn |
|---|---|---|
| `install_rclone.sh` | cài rclone (binary, ~/.local/bin) | không cần root |
| `upload_batch.sh <batch>` | `rclone copy --checksum` + retry + log | `--dry-run`, `--transfers`, `--with-ledger`; **từ chối** nếu thấy file `cookie*` trong batch |
| `verify_remote.sh <batch>` | `rclone check --checksum` (md5 Drive) + đối chiếu số file | PASS mới `mark-verified`; `--no-mark` để không cập nhật ledger |
| `cleanup_local.sh <batch>` | xoá audio/info.json local | **mặc định DRY RUN**; cần `--yes`; chỉ chạy khi `verified=true`; xoá luôn bản hardlink (nếu không, `df` không giảm) |

## Ví dụ

```shell
cd <repo-dir>
export PATH="$HOME/.local/bin:$PATH"

python3 metadata/make_batch.py --limit-gb 350 --verify --hardlink

./sync/upload_batch.sh batch_001                 # ~vài giờ với 350GB
./sync/verify_remote.sh batch_001                # PASS -> ledger.verified=true

python3 metadata/corpus_ledger.py append --batch-dir "$DATASET_DIR/batch_001"
python3 metadata/corpus_ledger.py push           # copy ledger lên Drive

./sync/cleanup_local.sh batch_001                # xem trước
./sync/cleanup_local.sh batch_001 --yes          # xoá thật
python3 metadata/corpus_ledger.py report          # tiến độ + audit trùng lặp
```

## Không bao giờ được làm

- Xoá `crawler/log/audios_*.txt` (archive chống trùng, không tái tạo được).
- Chạy `cleanup_local.sh --yes` khi `ledger.verified != true`.
- Upload khi chưa có `SHA256SUMS` (make_batch tạo ra).
- Upload thư mục chứa `cookies.txt` / `*.log`.

## Ghi chú vận hành — vòng đời theo **UNIT** (thêm 2026-10-07)

Ngoài vòng **batch tar** ở trên, dự án đang dùng vòng **unit** (không tar, không hardlink — xem
`metadata/make_unit.py` + `PROJECT_STATUS.md` §21/§22):

```
metadata/make_unit.py --name <unit>   ->  $DATASET_DIR/units/<unit>/  (files.txt · manifest.jsonl · SHA256SUMS · UNIT.json · stats.json · README.md)
sync/upload_unit.sh <unit>            ->  rclone copy --files-from  ->  gdrive:corpus/<unit>/
sync/upload_hf_retry.sh <unit> --workers 2  ->  HuggingFace (12 chunk, 0 lần 429 khi workers=2)
sync/verify_unit.sh <unit>            ->  rclone check --checksum   ->  PASS => ledger verified=true
```

### Cách xoá local — 2 lựa chọn

```shell
# (1) CÁCH CHUẨN (kiểm sha256 từng file) — chỉ chạy khi ledger verified=true:
python3 metadata/cleanup_local.py <unit> --batch-dir "$DATASET_DIR/units/<unit>" --yes

# (2) CÁCH USER ĐANG DÙNG (nhanh — khi đã tự xác nhận đủ trên Drive + HF): USER tự chạy
rm -rf "$DOWNLOAD_DIR"/*
```

⚠️ Cách (2) **bỏ qua** kiểm ledger + sha256 ⇒ chỉ dùng khi đã tự xác nhận; **agent KHÔNG tự chạy**.
`manifest.jsonl`/`SHA256SUMS`/`README.md` (ở `$DATASET_DIR/units/<unit>/`), ledger
(`$DATA_ROOT/corpus_ledger.jsonl`) và archive `crawler/log/audios_*.txt` đều **ngoài**
`download_from_youtube` ⇒ **không bị xoá**. Chi tiết: `HANDOVER.md` §6c.

