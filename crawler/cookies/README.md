# crawler/cookies/ — nơi chứa cookies YouTube (NHẠY CẢM)

## Trạng thái hiện tại: KHÔNG dùng cookies

Kết luận đã kiểm chứng (`PROJECT_STATUS.md` §15): cookie hợp lệ, đủ cookie đăng nhập,
chưa hết hạn, login OK — nhưng YouTube **chặn mọi request media** (`The page needs to be
reloaded`) khi request đến từ **IP datacenter**. Vì vậy mặc định crawl **KHÔNG cookies**.

Cookie chỉ cần cho: **video giới hạn tuổi / member-only**.

## Quy tắc bắt buộc

1. **KHÔNG bao giờ commit** file cookie (đã có `../.gitignore`).
2. `chmod 700 cookies/`, `chmod 600 cookies/*.txt` (file Netscape format).
3. Chỉ dùng **account phụ**, không dùng account chính.
4. Trước khi bật cookies, **BẮT BUỘC** chạy test media thật:

   ```shell
   cd crawler
   ./check_cookies.sh cookies/mycookies.txt      # verdict phải là "ok (usable)"
   ```

   Chỉ khi verdict = `ok (usable)` mới được đặt `COOKIES_FILE=cookies/mycookies.txt`.

5. Nếu vẫn 429/bot-check khi đã có cookies: **giảm `JOBS=1`**, tăng
   `SLEEP_INTERVAL` 8–15s, hoãn batch — **KHÔNG** xoay nhiều account từ cùng IP.

## Cách tạo file cookies (Netscape)

Xuất từ browser bằng extension "Get cookies.txt (Netscape)" khi đang đăng nhập
YouTube, rồi copy vào thư mục này. File phải bắt đầu bằng dòng
`# Netscape HTTP Cookie File`.
