# DATA_LAYOUT — dữ liệu nằm ở đâu & chống trùng thế nào

## 1. Cây thư mục

```
$DATA_ROOT/                                  # mặc định $HOME/data  (KHÔNG nằm trong repo)
├── download_from_youtube/                   # $DOWNLOAD_DIR — W1..W3
│   └── <channel>/                           # 1 thư mục / kênh
│       ├── <date>#<title>#<chid>#<vid>_<dur>.webm
│       └── … .info.json                     # metadata yt-dlp (upload_date, duration…)
├── dataset/                                 # $DATASET_DIR — W2..W8
│   ├── index.jsonl                          # index + audit ngày đăng
│   ├── qc_flags.jsonl                       # cờ QC từng file
│   ├── exclude.txt                          # file bị loại (hard flag)
│   ├── used_ids.txt                         # lớp chống trùng #2
│   ├── audio/<channel>/…                    # hardlink 0 byte (khi --hardlink)
│   ├── units/<unit>/                        # W4 kiểu unit
│   │   ├── manifest.jsonl · files.txt · UNIT.json
│   │   └── stats.json · SHA256SUMS · README.md (dataset card)
│   ├── batch_NNN/                           # W4 kiểu batch
│   │   ├── manifest.jsonl · part-0001.tar … (split 20 G)
│   │   └── meta.tar.gz · SHA256SUMS · stats.json
│   └── _logs/                               # log upload / verify / hf_verify_report_*.txt
└── corpus_ledger.jsonl                      # $LEDGER_FILE — sổ cái (nguồn sự thật về tiến độ)
```

Output của nhánh transcribe/segment (nếu dùng `run_pipeline.sh`):

```
$SAVE_DIR/corpus/*.wav + *.txt               # convert+transcribe
./output_force_align/                        # *_manifest.jsonl
./output_annotated/                          # manifest + languages/is_codeswitch
./output_filter/{all,codeswitch}/*.jsonl     # sau filter
./output_segment_all/ , ./output_segment_codeswitch/
```

> 4 thư mục `output_*` mặc định nằm trong repo (tiện debug). Muốn sạch, trỏ chúng
> ra ngoài bằng env: `ALIGN_DIR=$DATA_ROOT/output_force_align …`
> (xem `docs/CONFIGURATION.md` §⓶).

## 2. Ba lớp chống trùng (đừng phá)

| Lớp | Nơi lưu | Tác dụng | Mất thì sao |
|---|---|---|---|
| 1 | `crawler/log/audios_<channel>_<tab>.txt` | yt-dlp `--download-archive` | tải lại toàn bộ video cũ |
| 2 | `$DATASET_DIR/used_ids.txt` | chặn 1 `video_id` vào 2 batch/unit | unit trùng file, verify lệch |
| 3 | `$LEDGER_FILE` | trạng thái corpus + `verified` | mất "trí nhớ" tiến độ/verify |

**Bắt buộc** copy cả 3 khi đổi server (xem `docs/SETUP.md` §7).

## 3. Bốn con số khác nhau — đừng lẫn

Khi báo cáo "đã tải bao nhiêu", luôn nói rõ đang đếm cái gì:

| Câu hỏi | Đếm bằng |
|---|---|
| Có bao nhiêu **file trên đĩa**? | `find "$DOWNLOAD_DIR" -type f \| wc -l` (gồm cả `.info.json`) |
| Có bao nhiêu **audio**? | `python3 ../metadata/stats.py` hoặc đếm file không phải `.json` |
| Bao nhiêu **giờ**? | `stats.py` / `corpus_ledger.py report` (tổng duration từ info.json) |
| Bao nhiêu **GB**? | `du -sb` (byte SI) — khác `du -sh` (block/GiB) |

Kinh nghiệm: script shell cộng dung lượng bằng `awk` có thể bị **tràn 32-bit**
(`printf "%d"`) ⇒ số GB bị hụt. Luôn đối chiếu bằng `stats.py` hoặc `du -sb`.

## 4. Ước lượng dung lượng

| Định dạng | Xấp xỉ |
|---|---|
| medium opus (audio-only) | **≈ 42 MB / giờ** |
| `*.info.json` | ≈ 1–2 KB / video |
| 10.000 giờ audio | ≈ 420 GB |
| Tỉ lệ file | 1 audio + 1 `info.json` / video |

⇒ Máy staging 500 GB chỉ chứa được ~11.000 giờ ⇒ phải **upload rồi xoá theo unit**.

## 5. Vòng đời dữ liệu

```
crawl → QC → đóng gói unit → upload Drive + HF → verify → ledger.verified=true
      → (người vận hành) xoá $DOWNLOAD_DIR → crawl tiếp
```

- `$DOWNLOAD_DIR` là **vùng đệm**: xoá được sau khi verify.
- `dataset/units|batch_NNN` giữ lại để tái upload (xoá được nếu đã có bản remote).
- `index.jsonl`, `qc_flags.jsonl`, `used_ids.txt`, `corpus_ledger.jsonl` **giữ mãi** —
  nhỏ nhưng là state không tái tạo được.

## 6. Đặt dữ liệu ngoài repo (guard)

`download_from_youtube.sh` từ chối (exit `2`) nếu `DOWNLOAD_DIR` resolve vào trong
repo. Muốn ghi vào repo (rất không khuyến khích): `ALLOW_IN_REPO_DOWNLOAD=1`.

Cùng guard ở Python: `metadata/paths.py` → `require_outside_repo()`.
