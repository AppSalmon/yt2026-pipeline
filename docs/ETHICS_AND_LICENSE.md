# ETHICS, ToS & LICENSE

## 1. Đây là gì (và không là gì)

Repo này là **code** để thu thập audio công khai trên YouTube phục vụ **nghiên
cứu ASR**. Nó **không** phân phối audio, không chứa dữ liệu, và không cấp quyền
gì đối với nội dung của người khác.

## 2. Tuân thủ YouTube ToS

- Việc tải nội dung phải tuân theo [YouTube Terms of Service](https://www.youtube.com/t/terms)
  và bản quyền của chủ sở hữu. **Tự chịu trách nhiệm** khi dùng.
- Không dùng pipeline để tải nội dung trả phí, member-only, hoặc DRM.
- Cookies (nếu bật) là **tài khoản phụ**, không dùng account chính; không chia sẻ,
  không commit (xem `SECURITY.md`).
- Không xoay nhiều account/IP để lách rate-limit — đó là hành vi bị đánh dấu.

## 3. Bản quyền nội dung (audio + transcript)

| Việc | Được phép? |
|---|---|
| Tải về để nghiên cứu nội bộ | tuỳ ToS + luật áp dụng, tự chịu trách nhiệm |
| Commit audio/transcript vào repo | ❌ **không bao giờ** |
| Phát hành dataset công khai | ⚠️ chỉ khi bạn chấp nhận rủi ro pháp lý và có chính sách takedown (§4) |
| Bán/dùng thương mại | ❌ không, trừ khi bạn có quyền từ chủ sở hữu |

Nguyên tắc của repo: **code public, dữ liệu private/riêng**. Nếu phát hành
dataset, luôn kèm `license: other` + mô tả giới hạn và **gated access**.

## 4. Chính sách takedown (nếu bạn phát hành dataset)

- Mọi bản ghi giữ `video_id`, `channel_id`, `upload_date` ⇒ **xoá chính xác,
  tái lập được**: URL gốc = `https://www.youtube.com/watch?v=<video_id>`.
- Khi có yêu cầu từ chủ sở hữu: xoá item đó (hoặc cả kênh) trong vòng **7 ngày**,
  ghi lại vào `CHANGELOG.md` và phát hành lại manifest.
- Ưu tiên **gated = manual** (người duyệt) thay vì public hoàn toàn, để còn khả
  năng kiểm soát.

## 5. Quyền riêng tư (privacy)

Audio nói tự nhiên có thể chứa **thông tin cá nhân** (tên, số điện thoại, địa chỉ,
dữ liệu sức khoẻ). Nếu corpus dùng cho mục đích khác nghiên cứu nội bộ:

- không phát hành kèm metadata cá nhân ngoài những gì YouTube đã công khai;
- cân nhắc lọc bớt nội dung nhạy cảm trước khi chia sẻ;
- ghi rõ giới hạn sử dụng trong dataset card.

## 6. Giấy phép

### Code trong repo
**Apache License 2.0** — xem [`../LICENSE`](../LICENSE).

Vì sao Apache-2.0: repo có thành phần phái sinh từ
[GigaSpeech2](https://github.com/SpeechColab/GigaSpeech2) (Apache-2.0), nên dùng
cùng giấy phép để tương thích và giữ nguyên nghĩa vụ attribution.

### Thành phần bên thứ ba
Xem [`../NOTICE`](../NOTICE):

| Thành phần | Giấy phép | Vị trí |
|---|---|---|
| GigaSpeech2 (các file phái sinh) | Apache-2.0 | `convert_transcribe/`, `crawler/download_from_youtube.sh`, `segmentation/filter_manifest.py`, `utils/force_alignment/`, `run_pipeline.sh` |
| uroman (isi-nlp) | MIT | `utils/uroman/` (kèm `LICENSE.txt`) |
| fastText `lid.176.ftz` | CC-BY-SA 3.0 | **không** commit — tải bằng `scripts/download_models.sh` |
| Whisper / MMS CTC | giấy phép riêng của model | tải runtime vào `~/.cache` |

### Nếu bạn fork
Giữ nguyên `LICENSE` + `NOTICE`, hoặc thay bằng giấy phép tương thích Apache-2.0.
Nếu bạn sửa file phái sinh từ GigaSpeech2, ghi chú thay đổi ngay trong header file
(như các file hiện tại đang làm).

## 7. Citation

Nếu công bố kết quả dùng pipeline/dữ liệu sinh ra từ repo này, trích dẫn:

- GigaSpeech2 (nền tảng kiến trúc) — xem repo upstream để lấy BibTeX chính thức;
- nguồn dữ liệu gốc (YouTube, từng kênh) theo yêu cầu của chủ sở hữu;
- repo này: `<repo-url>` (kèm commit hash của phiên bản đã dùng).
