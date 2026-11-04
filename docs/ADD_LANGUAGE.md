# ADD_LANGUAGE — chạy pipeline cho một ngôn ngữ mới

Pipeline viết cho tiếng Việt nhưng **mọi thứ phụ thuộc ngôn ngữ đã được tham số
hoá**. Đổi ngôn ngữ = đổi biến môi trường; chỉ **một chỗ** cần sửa code là
charset filter (§3).

## 1. TL;DR

```shell
export LANG_CODE=th            # ISO 639-1
export ACCEPT_LANGS=th,en      # ngôn ngữ Whisper giữ lại (code-switch)
export ISO_639_2=tha           # ISO 639-2 cho forced alignment / uroman
export DATA_ROOT=$HOME/data_th # (tuỳ chọn) tách dữ liệu riêng theo ngôn ngữ

./scripts/check_env.sh                              # phải 0 FAIL
./crawler/crawl_all.sh crawler/channels_th.txt "" 2
python3 metadata/stats.py
```

Dữ liệu của 2 ngôn ngữ **nên** để `DATA_ROOT` khác nhau — dùng chung ledger/
batch/unit sẽ rối.

## 2. Mười điểm cần đổi

| # | Nơi | Cần làm | Bắt buộc? |
|---|---|---|---|
| 1 | `config.env` | `LANG_CODE`, `ACCEPT_LANGS`, `ISO_639_2` | ✅ |
| 2 | `crawler/download_from_youtube.sh` | format selector tự dùng `[language^=$LANG_CODE]` | tự động |
| 3 | `crawler/channels.txt` | danh sách kênh của ngôn ngữ đó (`crawler/channels_<code>.txt`) | ✅ |
| 4 | `crawler/langs/<code>/keywords.txt` | bộ từ khoá discovery (copy `langs/vi/` rồi sửa) | ✅ |
| 5 | `segmentation/filter_manifest.py` | **charset filter** — thêm Unicode range (§3) | ✅ sửa code |
| 6 | `codeswitch/detect_codeswitch.py` | danh sách token tiếng Anh thường gặp + ngưỡng LID | nên xem |
| 7 | `convert_transcribe/convert_and_transcribe.py` | `--lang`/`--accept-langs` lấy từ env | tự động |
| 8 | `force_alignment/force_align.sh` | nhận `$ISO_639_2` làm tham số thứ 3 | tự động |
| 9 | `metadata/audio_qc.py` | `wrong_language` dựa trên `LANG_CODE`/`ACCEPT_LANGS` | tự động |
| 10 | `metadata/make_hf_card.py` | front matter/tags theo `LANG_CODE`; **prose** vẫn tiếng Việt → sửa nếu publish | nên sửa |

Ngoài ra `MIN_UPLOAD_DATE`, `TARGET_HOURS` là quyết định của bạn, không phải của
ngôn ngữ.

## 3. Charset filter — chỗ duy nhất phải sửa code

`segmentation/filter_manifest.py` → class `VietnameseCharsetFilter`:

```python
LATIN = "a-zA-Z"
EXTRA = (r"\u00C0-\u024F" r"\u1E00-\u1EFF" ...)   # dấu tiếng Việt + Latin mở rộng
```

Thêm block Unicode của ngôn ngữ bạn vào `EXTRA` (giữ block cũ để vẫn dùng được
cho tiếng Việt):

| Ngôn ngữ | `LANG_CODE` | `ISO_639_2` | Unicode range cần thêm |
|---|---|---|---|
| Việt | `vi` | `vie` | `\u00C0-\u024F`, `\u1E00-\u1EFF` (đã có) |
| Thái | `th` | `tha` | `\u0E00-\u0E7F` |
| Lào | `lo` | `lao` | `\u0E80-\u0EFF` |
| Miến (Myanmar) | `my` | `mya` | `\u1000-\u109F`, `\uAA60-\uAA7F` |
| Khmer | `km` | `khm` | `\u1780-\u17FF`, `\u19E0-\u19FF` |
| Indonesia / Malaysia | `id` / `ms` | `ind` / `msa` | chỉ Latin — giữ nguyên |
| Hindi (Devanagari) | `hi` | `hin` | `\u0900-\u097F` |
| Trung / Nhật / Hàn | `zh`/`ja`/`ko` | `zho`/`jpn`/`kor` | `\u4E00-\u9FFF` / `\u3040-\u30FF` / `\uAC00-\uD7AF` |

Ví dụ thêm tiếng Thái:

```python
    EXTRA = (
        r"\u00C0-\u024F"
        r"\u1E00-\u1EFF"
        r"\u0E00-\u0E7F"      # Thai  <-- THÊM DÒNG NÀY
        r"\u2013-\u2014"
        r"\u2018-\u201D"
        r"\u2026"
        r"\u00AB\u00BB"
    )
```

Kiểm tra sau khi sửa: chạy `filter_manifest.py` trên manifest nhỏ, xem số segment

## 4. Mã ngôn ngữ

| ISO 639-1 (`LANG_CODE`) | ISO 639-2 (`ISO_639_2`) | Ghi chú |
|---|---|---|
| `vi` | `vie` | Vietnamese |
| `th` | `tha` | Thai |
| `id` | `ind` | Indonesian |
| `ms` | `msa` | Malay |
| `my` | `mya` | Burmese |
| `km` | `khm` | Khmer |
| `lo` | `lao` | Lao |
| `tl` / `fil` | `tgl` / `fil` | Filipino |

Danh sách đầy đủ: <https://en.wikipedia.org/wiki/List_of_ISO_639_language_codes>.
`ISO_639_2` sai ⇒ forced alignment sai (uroman không normalize đúng) — đây là lỗi
hay gặp nhất khi đổi ngôn ngữ.

## 5. Từ khoá discovery

Ưu tiên nội dung **hội thoại tự nhiên** (podcast, talkshow, phỏng vấn, call-in,
vlog), tránh đọc báo/đọc truyện/audiobook. Mẫu tiếng Việt ở
`crawler/langs/vi/keywords.txt`:

```
podcast tiếng việt
talkshow việt nam
phỏng vấn việt nam
react việt nam
vlog tiếng việt
trò chuyện tiếng việt
```

Với tiếng Thái, ví dụ: `พอดแคสต์`, `ทอล์คโชว์`, `สัมภาษณ์`, `vlog ไทย`,
`รายการทอล์ค`.

## 6. Lưu ý về Whisper / LID

- `ACCEPT_LANGS` phải chứa **`LANG_CODE`**; thêm `en` nếu có code-switch. Bỏ `en`
  để loại bớt segment trộn — hữu ích khi corpus thuần một ngôn ngữ.
- fastText `lid.176` hỗ trợ 176 ngôn ngữ nhưng trên **token ngắn** (segment 2–10 s)
  độ tin cậy thấp; pipeline xử lý bằng cách thừa hưởng ngôn ngữ của neighbour.
- MMS CTC forced alignment không tốt cho mọi ngôn ngữ. Nếu ngôn ngữ của bạn không
  được hỗ trợ tốt, **bỏ bước align** và dùng timestamp của Whisper — xem
  `examples/whisper_segment/` (demo độc lập, không phụ thuộc pipeline).

## 7. Kiểm thử sau khi đổi ngôn ngữ

- [ ] `./scripts/check_env.sh` in đúng `LANG_CODE` / `ACCEPT_LANGS` / `ISO_639_2`
- [ ] crawl 1 kênh: file tải về đúng audio track (`ffprobe file.webm`)
- [ ] `python3 metadata/audio_qc.py` → `wrong_language` gần 0
- [ ] `filter_manifest.py` → tỷ lệ bị loại hợp lý (không 100%)
- [ ] `force_align.sh` chạy được (kiểm `ISO_639_2`)
- [ ] `python3 metadata/make_hf_card.py --name <unit> --dry-run` → front matter
      có `language: - tha`, và **cảnh báo prose** xuất hiện (đúng thiết kế)
- [ ] đổi lại `LANG_CODE=vi` vẫn chạy như trước (không phá pipeline gốc)

## 8. Ví dụ hoàn chỉnh: tiếng Thái

```shell
export LANG_CODE=th ACCEPT_LANGS=th,en ISO_639_2=tha
export DATA_ROOT=$HOME/data_th TARGET_HOURS=20000

mkdir -p crawler/langs/th
cp crawler/langs/vi/keywords.txt crawler/langs/th/keywords.txt   # rồi dịch từ khoá
cp crawler/langs/vi/channels_sample.txt crawler/channels_th.txt  # rồi thay kênh

python3 crawler/discover_channels.py --keywords-file crawler/langs/th/keywords.txt \
    --num-per-keyword 40 --output crawler/candidates_th.tsv
./crawler/check_channels.sh crawler/channels_th.txt
./crawler/crawl_all.sh crawler/channels_th.txt "" 2
python3 metadata/stats.py
```

Sau đó sửa `EXTRA` của charset filter (§3) rồi chạy tiếp theo
[`OPERATIONS.md`](OPERATIONS.md).

bị loại (`dropped`) có bất thường không.
