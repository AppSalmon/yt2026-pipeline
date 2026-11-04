# OPERATIONS — runbook vận hành

Quy ước đọc: mọi lệnh chạy từ **gốc repo**; `$DATASET_DIR` = `$HOME/data/dataset`.

## 0. Chu kỳ một đợt (W1 → W8)

```
W1 crawl  →  W2 audit ngày đăng  →  W3 QC audio  →  W4 đóng gói (batch/unit)
   →  W5 ghi ledger  →  W6 upload Drive + HF  →  W7 verify cả 2 nơi
   →  W8 báo người vận hành xoá local  →  crawl tiếp
```

**Quy tắc thép**: chưa verify xong **cả hai** nơi thì **chưa xoá local**; script
không tự xoá dữ liệu, người vận hành tự chạy lệnh xoá.

## 1. Crawl một đợt

```shell
# trong tmux (đợt dài, tránh mất session)
tmux new -s crawl
PATH="$HOME/.local/bin:$PATH" JOBS=2 SLEEP_REQUESTS=1 SLEEP_INTERVAL=6 \
MAX_SLEEP_INTERVAL=15 MAX_VIDEOS=50 SKIP_AFTER_ERRORS=30 BATCH_LABEL=crawl01 \
  ./crawler/crawl_all.sh crawler/channels.txt "" 2 | tee crawler/log/crawl01_$(date +%Y%m%d).log
```

- `JOBS=2` là mức an toàn với YouTube; tăng chỉ khi IP sạch.
- Pilot nhanh: thêm `EXTRA_OPTS="--playlist-items 1:3"`.
- Kết quả tổng hợp: `crawler/log/run_<label>_summary.csv`
  (`channel,status,rc,new_audio,new_hours,new_bytes`); `status=fail` khi kênh
  404/bị chặn (exit 1 từ `download_from_youtube.sh`).
- Chạy lại **luôn an toàn**: `--download-archive crawler/log/audios_<channel>_<tab>.txt`
  chỉ tải video MỚI.

Theo dõi tiến độ (READ-ONLY, chạy được khi đang crawl):

```shell
python3 metadata/stats.py                # file / giờ / GB / per-channel (≈0,7 s)
tail -f crawler/log/<label>_*.log
```

## 2. Audit + QC

```shell
# audit: exit 1 nếu có video ngoài cửa sổ thời gian
python3 metadata/build_index.py --min-upload-date "$MIN_UPLOAD_DATE" --strict

# QC audio + language guard (loại file hỏng, sai ngôn ngữ)
python3 metadata/audio_qc.py                     # nhanh
python3 metadata/audio_qc.py --silence-check     # chậm: decode toàn bộ file
```

Kết quả: `$DATASET_DIR/{index.jsonl,qc_flags.jsonl,exclude.txt}`.
Ý nghĩa từng cờ: [`CONFIGURATION.md`](CONFIGURATION.md) §⓻.

## 3. Đóng gói

Hai kiểu, chọn theo cách bạn muốn lưu trữ:

| Cách | Script | Khi nào dùng |
|---|---|---|
| **batch** (tar 20 G/part) | `metadata/make_batch.py` | lưu trữ dài hạn, ít file, upload thô |
| **unit** (danh sách file + manifest) | `metadata/make_unit.py` | upload theo từng nhóm kênh, resume tốt, HF ổn định hơn |

```shell
# kiểu batch
python3 metadata/make_batch.py --limit-gb 400 --verify --hardlink

# kiểu unit (khuyến nghị cho upload HF)
python3 metadata/make_unit.py --target-hours 10000          # -> units/<unit>/
```

Sản phẩm mỗi unit: `manifest.jsonl`, `files.txt`, `UNIT.json`, `stats.json`,
`SHA256SUMS`, và card `README.md` (sinh bằng `make_hf_card.py`).

## 4. Upload

```shell
# Google Drive (rclone, resumable)
./sync/upload_unit.sh <unit>              # -> $GDRIVE_PARENT/<unit>/

# HuggingFace (chia chunk theo kênh + supervisor chống 429)
./sync/upload_hf_retry.sh <unit> --workers 2
```

Trước lần đầu: `rclone config` (remote `gdrive`) và `hf auth login`.
Venv HF riêng: `export HF_PYTHON=~/.venvs/hf1/bin/python` (tránh xung đột numpy<2).

## 5. Verify (BẮT BUỘC trước khi xoá)

```shell
./sync/verify_unit.sh <unit>        # rclone check --checksum (Drive)
./sync/verify_unit_hf.sh <unit>     # so size qua API HF + sha256 mẫu
```

Tiêu chí PASS: **thiếu 0 · thừa 0 · sai size 0**, byte audio khớp tuyệt đối.
Báo cáo ghi vào `$DATASET_DIR/_logs/`.

## 6. Sổ cái

```shell
python3 metadata/corpus_ledger.py report                 # tiến độ tới TARGET_HOURS
python3 metadata/corpus_ledger.py mark-verified <unit> --remote-files <N>
python3 metadata/corpus_ledger.py push                   # backup ledger lên Drive
```

`ledger.verified=true` là điều kiện duy nhất cho phép xoá local.

## 7. Xoá local (người vận hành tự chạy)

```shell
# sau khi verify PASS cả 2 nơi
df -h "$DATA_ROOT"                       # ghi lại dung lượng trước
find "$DOWNLOAD_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
df -h "$DATA_ROOT"
```

Hoặc dùng `python3 metadata/cleanup_local.py` nếu muốn xoá theo
`ledger.verified` (an toàn hơn, có log).

## 8. Cron định kỳ

```cron
# thứ Hai 03:00 — driver tự động (crawl → audit → QC → đóng gói → [upload → verify → ledger])
0 3 * * 1  cd <repo>/cron && PATH="$HOME/.local/bin:$PATH" ./crawl_weekly.sh --with-upload >> ../crawler/log/cron.log 2>&1

# watchdog crawl (tự khởi động lại nếu tmux chết)
@reboot     <repo>/cron/watch_crawl.sh >> <repo>/crawler/log/watch_crawl.log 2>&1
*/15 * * * * <repo>/cron/watch_crawl.sh >> <repo>/crawler/log/watch_crawl.log 2>&1
```

Chưa có Drive/rclone? Chạy `./crawl_weekly.sh` **không** `--with-upload` (vẫn
crawl + QC + đóng gói + ghi ledger).

## 9. "Crawl tiếp" — mở rộng danh sách kênh

```shell
# 1) comment các kênh đã crawl xong trong channels.txt (dấu # ở đầu dòng)
# 2) discovery kênh mới
python3 crawler/discover_channels.py --num-per-keyword 40 \
    --output crawler/candidates_new.tsv
# 3) lọc trùng channel_id với các danh sách đã có, kiểm kênh còn sống
./crawler/check_channels.sh crawler/channels.txt
# 4) nối kênh OK vào crawler/channels.txt rồi chạy lại bước 1
```

## 10. Checklist một đợt (in ra dán vào log đợt)

- [ ] `./scripts/check_env.sh` → 0 FAIL
- [ ] danh sách kênh đã cập nhật, `channels.txt` không còn kênh đã xong
- [ ] crawl xong, `summary.csv` có `fail=0` (hoặc đã xử lý kênh fail)
- [ ] `build_index.py --strict` → không vi phạm cửa sổ thời gian
- [ ] `audio_qc.py` → 0 hard-flag
- [ ] đóng gói unit/batch + `SHA256SUMS`
- [ ] upload Drive + HF, `verify` PASS cả 2
- [ ] `corpus_ledger.py mark-verified` + `push`
- [ ] báo người vận hành xoá local → xoá → kiểm `df -h`
