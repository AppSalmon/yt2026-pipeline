# cron/ — W7: chạy định kỳ không giám sát

## Cài crontab (thứ Hai 03:00)

```shell
crontab -e
```

```cron
# PATH: cron KHÔNG có PATH của shell tương tác -> phải tự set (yt-dlp/ffmpeg nằm ở ~/.local/bin)
0 3 * * 1 cd <repo-dir>/cron \
  && PATH="$HOME/.local/bin:$PATH" ./crawl_weekly.sh --with-upload \
  >> ../crawler/log/cron.log 2>&1
```

Kiểm tra: `tail -f crawler/log/cron.log` và `crawler/log/cron_<timestamp>.log`.

## `crawl_weekly.sh` làm gì

| Bước | Lệnh | Ghi chú |
|---|---|---|
| 0 | preflight | `channels.txt` phải có ≥1 kênh dùng được; `df` staging (warn < `MIN_FREE_GB`, abort < `MIN_FREE_HARD_GB`) |
| 1 | `crawler/crawl_all.sh` | `JOBS` kênh song song, `BATCH_LABEL=cron_<ngày>` |
| 2 | `metadata/build_index.py --strict` | **hard gate**: có video ngoài 2026 → KHÔNG đóng gói |
| 3 | `metadata/audio_qc.py` | language guard + file hỏng → `exclude.txt` |
| 4 | `metadata/make_batch.py --limit-gb … --verify [--hardlink]` | tự bỏ qua khi "candidates: 0 files" |
| 5 | `metadata/corpus_ledger.py append` | ghi sổ cái (batch mới ở trạng thái `verified=false`) |
| 6 | upload → verify → cleanup | **chỉ khi `--with-upload`**: `upload_batch.sh` → `verify_remote.sh` (PASS mới `mark-verified`) → `cleanup_local.sh --yes` |

Kết thúc: in `corpus_ledger.py report` (tiến độ tới `TARGET_HOURS`, audit trùng lặp) và
**exit 1 nếu có bước nào FAIL** (để cron/monitoring phát hiện).

## Tuỳ chọn

| Flag / env | Mặc định | Ý nghĩa |
|---|---|---|
| `--with-upload` | tắt | bật chuỗi upload/verify/cleanup (cần rclone đã authorize) |
| `--limit-gb N` / `LIMIT_GB` | 350 | trần dung lượng mỗi batch |
| `--max-upload N` / `MAX_UPLOAD_PER_RUN` | 1 | số batch upload mỗi lần chạy (giới hạn ~750GB/ngày của Google) |
| `--jobs N` / `JOBS` | 2 | số kênh crawl song song |
| `HARDLINK=1\|0` | 1 | dựng mirror hardlink (0 byte) trong `$DATASET_DIR/audio/` |
| `--dry-run` | | in kế hoạch, không thực thi gì |

## Cảnh báo vận hành

- **Staging chỉ 774GB**: cứ ~2 batch (350GB) là phải upload rồi cleanup; script tự abort khi
  free < `MIN_FREE_HARD_GB` (mặc định 20GB).
- **Chưa có rclone/Drive** → chạy `./crawl_weekly.sh` (không `--with-upload`): vẫn crawl + QC +
  đóng gói + ghi ledger, an toàn.
- Nếu 429/bot-check: giảm `JOBS=1`, tăng `SLEEP_INTERVAL` 8–15s — **không xoay account cookies**
  (xem `PROJECT_STATUS.md` §15).
- Cron chạy trùng lặp (job trước chưa xong): `--download-archive` + `used_ids.txt` chống tải/đóng
  gói trùng, nhưng nên dùng `flock` nếu muốn chắc:
  `flock -n /tmp/yt_pipeline.lock ./crawl_weekly.sh --with-upload`.

## `watch_crawl.sh` — watchdog cho crawl trong tmux (thêm 2026-10-07)

Job crawl trong `tmux` **không tự báo khi chết** (reboot / OOM / bị kill). `watch_crawl.sh` kiểm tra
session tmux còn sống không; nếu chết thì khởi động lại **đúng lệnh cũ** (resume an toàn nhờ
`--download-archive`).

```shell
crontab -e
```
```cron
# PATH: cron không có PATH của shell tương tác -> watch_crawl.sh tự export ~/.local/bin
@reboot      <repo-dir>/cron/watch_crawl.sh >> <repo-dir>/crawler/log/watch_crawl.log 2>&1
*/15 * * * * <repo-dir>/cron/watch_crawl.sh >> <repo-dir>/crawler/log/watch_crawl.log 2>&1
```

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `SESSION` | `ytb-2511` | tên tmux session cần canh |
| `CHANNELS` | `crawler/channels_2509.txt` | file kênh |
| `JOBS` | `2` | số kênh crawl song song |
| `LABEL` | `crawl2511` | nhãn `BATCH_LABEL` + tên log |
| `FORCE` | `0` | `1` = kill session cũ rồi tạo lại |

Chạy tay để kiểm tra: `cron/watch_crawl.sh` (in `… đang chạy — OK` nếu session còn sống).
Khi chuyển sang đợt crawl mới: `SESSION=ytb-XXXX CHANNELS=… LABEL=crawlXXXX cron/watch_crawl.sh`.

