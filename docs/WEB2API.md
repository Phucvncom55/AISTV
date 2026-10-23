# Dự phòng Gemini Web2API

Khi model chính (OpenCode → DeepSeek) **hết hạn mức request** (429 / hết token),
AI STV tự chuyển sang một server **Gemini Web2API** chạy ngay trên máy của bạn.
Server này dùng cookie tài khoản Google (Gemini Web) nên không cần API key trả phí.

```
Telegram ──► aistv_bot.py ──► OpenCode ──► DeepSeek (model chính)
                    │                          │ hết hạn mức (429/quota)
                    └──────────────────────────┴──► web2api (localhost:8081)
                                                       └── gemini.google.com
```

## 1. Cài đặt lần đầu

```bash
python -m pip install -r requirements.txt          # có cryptography
python aistv_web2api.py setup                       # tải server + tạo config
python aistv_web2api.py import cookies.json --push  # nạp cookie + backup mã hoá
python aistv_web2api.py doctor                      # kiểm tra
```

`cookies.json` là file export từ trình duyệt (Cookie-Editor / EditThisCookie),
hoặc file Netscape `cookies.txt`, hoặc chuỗi `name=value; name=value`.

Cần các cookie của `gemini.google.com`: `__Secure-1PSID`, `SAPISID`, `SSID`,
`__Secure-1PSIDTS`… (script tự lọc và sắp xếp).

Sau khi nạp cookie, script tự lấy **XSRF token** (`SNlM0e`) — bắt buộc khi gọi
bằng tài khoản đã đăng nhập. Token này hết hạn theo phiên; làm mới bằng:

```bash
python aistv_web2api.py refresh
```

## 2. Đổi máy / dựng server mới

Cookie được mã hoá **AES-256-GCM** (scrypt KDF) rồi lưu tại repo private
`Phucvncom55/AISTV-secrets`, đường dẫn `web2api/cookies.enc`.

Máy mới chỉ cần:

```bash
gh auth login                      # hoặc đặt AISTV_CONFIG_TOKEN
python aistv_web2api.py pull       # tải + giải mã cookie, làm mới XSRF
python aistv_web2api.py setup
python aistv_web2api.py start
```

Passphrase được backup cùng repo private (`web2api/passphrase`) để `pull` chạy
được ngay trên máy mới. Bản thân repo đã là private và chỉ token của bạn đọc
được, nhưng nếu muốn tách khoá ra khỏi GitHub:

```bash
# đặt trong config.env của máy chạy, KHÔNG commit
WEB2API_KEY_BACKUP=0
WEB2API_COOKIE_PASSPHRASE=<khoá bạn tự giữ>
```

Xem khoá hiện tại: `python aistv_web2api.py passphrase`. Đổi khoá:
`python aistv_web2api.py passphrase --new` rồi `python aistv_web2api.py push`
(máy khác phải `pull` lại).

## 3. Lệnh quản lý

| Lệnh | Việc |
| --- | --- |
| `python aistv_web2api.py setup` | tải server, tạo `config.json`, cài `httpx` |
| `python aistv_web2api.py import <file> [--push]` | nạp cookie + backup |
| `python aistv_web2api.py refresh [--push]` | lấy lại XSRF token |
| `python aistv_web2api.py push` | mã hoá + đẩy lên repo private |
| `python aistv_web2api.py pull` | tải + giải mã (máy mới) |
| `python aistv_web2api.py passphrase` | in passphrase hiện tại (giữ kín) |
| `python aistv_web2api.py start\|stop\|restart` | bật/tắt server nền |
| `python aistv_web2api.py status` | trạng thái nhanh |
| `python aistv_web2api.py doctor` | kiểm tra cookie/XSRF/khoá/kết nối |
| `python aistv_web2api.py test "2+2=?"` | gọi thử 1 request |
| `python aistv_web2api.py logs` | 60 dòng log cuối |

Trong Telegram: `/web2api` (xem trạng thái), `/web2api start|stop|restart|refresh|pull|push`
(chỉ chủ bot).

## 4. Cách bot dùng

* `workspace/opencode.json` được thêm provider `web2api`
  (`@opencode/ai/providers/openai-compatible` → `http://127.0.0.1:8081/v1`).
* `run_agent()` chạy model chính; nếu lỗi khớp `429/quota/rate limit/...` **và
  chưa chạy tool nào**, nó tự chạy lại bằng `web2api/gemini-3.6-flash`.
  Nếu tool đã chạy, bot dừng và báo lý do để tránh lặp tác dụng phụ.
* `aistv_watch.py` (đọc ảnh/video) khi Gemini API chính hết quota cũng tự gọi
  Web2API nội bộ.

Tắt dự phòng: `WEB2API_FALLBACK=0` (hoặc `WEB2API_ENABLE=0`).

Đổi model dự phòng:

```env
WEB2API_MODEL=gemini-3.5-flash-thinking
OPENCODE_FALLBACK_MODELS=web2api/gemini-3.5-flash-thinking
```

## 5. Bảo mật

* Cookie Google là **mật khẩu sống**: ai có cookie vào được tài khoản.
  Không dán vào chat, không commit, không đưa lên repo public.
* Nếu cookie từng bị lộ: vào `myaccount.google.com` → *Bảo mật* → đăng xuất
  khỏi mọi thiết bị, rồi export cookie mới.
* Bản backup trên GitHub đã mã hoá; passphrase backup cùng repo private
  (`web2api/passphrase`). Đặt `WEB2API_KEY_BACKUP=0` nếu muốn giữ khoá ngoài GitHub.
* Cookie hết hạn sau vài tháng (trường `expirationDate`) — nạp lại bằng `import`.

## 6. Sự cố thường gặp

| Triệu chứng | Cách xử lý |
| --- | --- |
| `HTTP 400: Bad Request` khi chat | thiếu/hết XSRF → `refresh` |
| Cookie hết hạn | export cookie mới → `import ... --push` |
| `502` / rỗng khi dùng Docker | dùng `--network host` (xem README repo gốc) |
| Không vào được gemini.google.com | đặt `WEB2API_PROXY` (Clash/V2Ray) |
| Không thấy model `web2api/...` | chạy `/restart` để ghi lại `workspace/opencode.json` |
