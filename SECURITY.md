# SECURITY — những gì TUYỆT ĐỐI không được commit

Repo này là **code + tài liệu**. Mọi thứ dưới đây phải nằm ngoài git
(`.gitignore` đã chặn sẵn, nhưng đừng dựa hoàn toàn vào nó):

| Loại | Ví dụ | Vì sao |
|---|---|---|
| **Cookie YouTube** | `cookies.txt`, `crawler/cookies/*.txt` (Netscape format) | xác thực một tài khoản Google thật; lộ = mất tài khoản |
| **Token HuggingFace** | `HF_TOKEN`, `~/.cache/huggingface/token` | quyền ghi/xoá dataset của bạn |
| **Google OAuth / rclone** | `~/.config/rclone/rclone.conf` | quyền truy cập Drive |
| **GitHub PAT / SSH key** | `ghp_…`, `id_rsa`, `*.pem` | quyền push vào repo |
| **Audio / transcript đã crawl** | `*.wav`, `*.webm`, `*.jsonl` trong `$DOWNLOAD_DIR` | bản quyền nội dung YouTube |
| **Danh sách kênh đang khai thác** | `crawler/channels.txt`, `crawler/candidates*.tsv` | state vận hành của bạn, không phải template |
| **Link dataset riêng tư** | `huggingface.co/datasets/<account>/…` trong tài liệu | tiết lộ tài khoản/hạ tầng nội bộ |

## Nơi đặt credential (đúng cách)

| Credential | Đặt ở đâu |
|---|---|
| Cookie YouTube | `crawler/cookies/<name>.txt`, `chmod 600`, chỉ account phụ |
| Token HuggingFace | `hf auth login` → `~/.cache/huggingface/token`, hoặc `export HF_TOKEN=…` trong shell |
| rclone (Google Drive) | `rclone config` → `~/.config/rclone/rclone.conf` (`chmod 600`) |
| Biến cục bộ theo máy | `config.local.env` (đã gitignore) rồi `set -a; . ./config.local.env; set +a` |

**Không bao giờ** đặt token trong `config.env`, trong script, trong Makefile hay
trong issue/PR.

## Trước mỗi lần commit

```shell
# 1) quét secret (chạy trong repo)
git grep -nIE 'hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH) PRIVATE KEY' \
  && echo "❌ CÓ SECRET — dừng lại" || echo "✅ clean"

# 2) quét PII / link nội bộ
git grep -nIE '@gmail\.com|huggingface\.co/datasets/[A-Za-z0-9_-]+/|/home/[a-z]+/' \
  && echo "❌ còn PII/nhà cung cấp — dừng lại" || echo "✅ clean"

# 3) xem đúng những gì sắp vào commit
git add -A && git status --short && git diff --cached --stat
```

Bật thêm trên GitHub (Settings → Code security): **Secret scanning** +
**Push protection**.

## Nếu đã lỡ commit secret

1. **Thu hồi ngay** credential đó (cookie → logout khỏi account; HF token → revoke;
   rclone → `rclone config reconnect`; PAT → delete).
2. Xoá khỏi lịch sử (`git filter-repo --path <file> --invert-paths` hoặc BFG) và
   force-push; coi như secret đó **đã bị lộ vĩnh viễn** — đổi mới là bắt buộc.
3. Ghi lại sự cố vào PR/commit message để người sau biết.

## Báo lỗi bảo mật

Mở issue **riêng tư** (hoặc liên hệ maintainer trực tiếp), **không** paste secret
vào issue công khai.
