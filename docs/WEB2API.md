# Dự phòng Gemini Web2API

Khi model chính (OpenCode → DeepSeek) **hết hạn mức request** (429 / hết token) hoặc
**lỗi từ nhà cung cấp** (`UnknownError`, `Unexpected server error`, 5xx), AI STV tự
chuyển sang một server **Gemini Web2API** chạy ngay trên máy của bạn. Server này dùng
cookie tài khoản Google (Gemini Web) nên không cần API key trả phí.

```
Telegram ──► aistv_bot.py ──► OpenCode ──► DeepSeek (model chính)
                    │                          │ 429 / hết token / UnknownError
                    └──────────────────────────┴──► web2api (localhost:8081)
                                                       └── gemini.google.com
```

## 1. Chạy một lần, không cần `start`

Bot tự gọi `auto()` khi khởi động:

1. tải server `gemini-web2api` vào `~/.config/aistv/web2api/app`;
2. cài `httpx` nếu thiếu;
3. kéo cookie trên GitHub (máy mới) hoặc dùng cookie đang có;
4. lấy XSRF token và bật server nền.

Máy mới chỉ cần chạy bot như bình thường. Nếu muốn làm bằng tay:

```bash
python aistv_web2api.py auto       # kéo cookie + nạp cookie mới + bật server
python aistv_web2api.py doctor     # kiểm tra tổng thể
```

## 2. Dán cookie mới là chạy luôn

Cookie lưu **nguyên văn**, không mã hoá, không passphrase:

```
~/.config/aistv/web2api/cookie.txt          # Linux/macOS
%USERPROFILE%\.config\aistv\web2api\cookie.txt   # Windows
```

Mở file, dán header dạng:

```
__Secure-1PSID=...; __Secure-1PSIDTS=...; SAPISID=...; SSID=...; HSID=...; SID=...
```

Lưu file là bot tự phát hiện (vòng lặp nền ~10 giây), làm mới XSRF, khởi động lại
server và đẩy bản mới lên GitHub. **Không cần gõ `start`.**

Cũng có thể nạp từ file export của trình duyệt (Cookie-Editor / EditThisCookie),
Netscape `cookies.txt`, hoặc chuỗi header:

```bash
python aistv_web2api.py import cookies.json
```

Lệnh `import` tự chạy server và tự đẩy GitHub (thêm `--no-push` nếu không muốn).

Trong Telegram (chỉ chủ bot):

```
/web2api import __Secure-1PSID=...; SAPISID=...
```

Tin nhắn chứa cookie được xoá ngay sau khi nhận.

Cần các cookie của `gemini.google.com`: `__Secure-1PSID`, `SAPISID`, `SSID`,
`__Secure-1PSIDTS`… (script tự lọc và sắp xếp).

Sau khi nạp cookie, script tự lấy **XSRF token** (`SNlM0e`) — bắt buộc khi gọi
bằng tài khoản đã đăng nhập.

## 3. Đổi máy / sửa cookie trên GitHub

Bản backup nằm **nguyên văn** tại repo private:

```
Phucvncom55/AISTV-secrets → web2api/cookie.txt
```

- Sửa trực tiếp file này trên web GitHub rồi bấm **Commit**.
- Máy đang chạy tự kéo bản mới khoảng 2 phút/lần (hoặc `/web2api pull`).
- Máy mới: chạy bot là tự kéo + bật server, không cần copy file thủ công.
- Nếu máy local đang có cookie mới hơn (chưa đẩy), bot giữ bản local rồi đẩy lên,
  không ghi đè mất.

Đổi repo/path:

```env
WEB2API_SECRETS_REPO=Phucvncom55/AISTV-secrets
WEB2API_SECRETS_PATH=web2api/cookie.txt
WEB2API_COOKIE_FILE=D:\cookies\gemini.txt   # đổi luôn file local
```

Repo phải là **private**. Cookie Google là mật khẩu sống: ai có cookie vào được
tài khoản. Không commit vào repo public, không dán vào chat công khai.

Bản mã hoá cũ (`web2api/cookies.enc`, `passphrase.txt`) không còn dùng — có thể xoá.

## 4. Lệnh quản lý

| Lệnh | Việc |
| --- | --- |
| `python aistv_web2api.py auto` | kéo cookie + nạp cookie mới + bật server |
| `python aistv_web2api.py watch` | theo dõi `cookie.txt` liên tục (dán mới là chạy) |
| `python aistv_web2api.py import <file> [--no-push]` | nạp cookie + chạy + đồng bộ |
| `python aistv_web2api.py refresh [--push]` | lấy lại XSRF token |
| `python aistv_web2api.py push` | đẩy cookie nguyên văn lên repo private |
| `python aistv_web2api.py pull` | tải cookie từ repo private + bật server |
| `python aistv_web2api.py start\|stop\|restart` | bật/tắt server (thường không cần) |
| `python aistv_web2api.py status` | trạng thái nhanh |
| `python aistv_web2api.py doctor` | kiểm tra cookie/XSRF/kết nối |
| `python aistv_web2api.py test "2+2=?"` | gọi thử 1 request |
| `python aistv_web2api.py logs` | 60 dòng log cuối |

Trong Telegram: `/web2api` (trạng thái), `/web2api import <cookie>`,
`/web2api start|stop|restart|refresh|pull|push|auto` (chỉ chủ bot).

## 5. Cách bot dùng

- `workspace/opencode.json` được thêm provider `web2api`
  (`@opencode/ai/providers/openai-compatible` → `http://127.0.0.1:8081/v1`).
- `run_agent()` chạy model chính; nếu lỗi khớp `429/quota` **hoặc lỗi server**
  (`UnknownError`, `Unexpected server error`, 5xx, `fetch failed`…) **và chưa chạy
  tool nào**, nó tự chạy lại bằng `web2api/gemini-3.6-flash`.
  Nếu tool đã chạy, bot dừng và báo lý do để tránh lặp tác dụng phụ.
- `aistv_watch.py` (đọc ảnh/video) khi Gemini API chính hết quota cũng tự gọi
  Web2API nội bộ.

Tắt dự phòng: `WEB2API_FALLBACK=0` (hoặc `WEB2API_ENABLE=0`).

Đổi model dự phòng:

```env
WEB2API_MODEL=gemini-3.5-flash-thinking
OPENCODE_FALLBACK_MODELS=web2api/gemini-3.5-flash-thinking
```

## 6. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `WEB2API_ENABLE` | `1` | `0` = tắt hoàn toàn |
| `WEB2API_FALLBACK` | `1` | `0` = không tự chuyển model |
| `WEB2API_AUTOSTART` | `1` | `0` = không tự bật server |
| `WEB2API_AUTOSYNC` | `1` | `0` = không tự kéo/đẩy GitHub |
| `WEB2API_URL` | `http://127.0.0.1:8081` | Địa chỉ server |
| `WEB2API_API_KEY` | `sk-gemini` | Khoá nội bộ |
| `WEB2API_MODEL` | `gemini-3.6-flash` | Model dự phòng |
| `WEB2API_COOKIE_FILE` | `~/.config/aistv/web2api/cookie.txt` | File dán cookie |
| `WEB2API_SECRETS_REPO` | `Phucvncom55/AISTV-secrets` | Repo private backup |
| `WEB2API_SECRETS_PATH` | `web2api/cookie.txt` | Đường dẫn file trong repo |
| `WEB2API_PROXY` | trống | Proxy nếu không vào được gemini.google.com |

## 7. Sự cố thường gặp

| Triệu chứng | Cách xử lý |
| --- | --- |
| `HTTP 400: Bad Request` khi chat | thiếu/hết XSRF → `refresh` |
| Cookie hết hạn | export cookie mới → dán vào `cookie.txt` hoặc `import` |
| `UnknownError` / `Unexpected server error` từ model chính | bot tự chuyển Web2API; nếu vẫn lỗi xem `logs` và `doctor` |
| `502` / rỗng khi dùng Docker | dùng `--network host` (xem README repo gốc) |
| Không vào được gemini.google.com | đặt `WEB2API_PROXY` (Clash/V2Ray) |
| Không thấy model `web2api/...` | chạy `/restart` để ghi lại `workspace/opencode.json` |
| Máy mới chưa có cookie | đặt `AISTV_CONFIG_TOKEN` hoặc `gh auth login` rồi chạy bot / `auto` |
