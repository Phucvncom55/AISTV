# AI STV — Bot Telegram × OpenCode

Bot Telegram dạng agent: nhận yêu cầu, chạy **OpenCode** trong workspace, trả kết quả về chat. Có trí nhớ dài hạn, nhật ký theo ngày, skills, gửi/nhận file và lịch sử hội thoại bền vững.

Chạy được trên **Colab, VPS, máy cá nhân** — chỉ cần Python 3.10+ và mạng.

## ⚡ 3 bước

1. `bash push.sh AISTV public` → in ra **link repo** + lệnh chạy.
2. Thêm `TELEGRAM_BOT_TOKEN` (và `ALLOWED_USER_IDS`) vào 🔑 Secrets của Colab.
3. Dán lệnh này vào ô Colab:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

## 1. Tạo bot Telegram

1. Nhắn [@BotFather](https://t.me/BotFather) → `/newbot` → lấy **token** dạng `123456:ABC…`.
2. (Nên làm) Nhắn [@userinfobot](https://t.me/userinfobot) để lấy **user id** của bạn → khoá bot.

## 2. Đưa code lên GitHub

```bash
cd AISTV
gh auth login          # một lần, nếu chưa đăng nhập
bash push.sh AISTV public
```

Không có `gh`? Tạo repo trống trên GitHub rồi:

```bash
cd AISTV
git init -b main && git add -A
git commit -m "AI STV — bot Telegram chạy OpenCode"
git remote add origin https://github.com/Phucvncom55/AISTV.git
git push -u origin main
```

> **Không commit `.env`** (đã nằm trong `.gitignore`). Repo public là an toàn vì token chỉ nằm trên máy chạy.

## 3. Chạy bot bằng MỘT lệnh

`bootstrap.sh` luôn cập nhật repo rồi mới chạy `run.sh` bên trong, nên **không bị kẹt bản cũ do cache GitHub**:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

Muốn dùng repo khác, truyền link GitHub trực tiếp:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3) https://github.com/Phucvncom55/AISTV
```

Lần đầu script sẽ: tải repo → lấy/hỏi token → tạo `.venv` → cài thư viện → cài OpenCode → chạy bot.
Token lấy theo thứ tự: `.env` → biến môi trường → Colab Secrets → hỏi trực tiếp (máy có terminal).

### Chạy trên Google Colab

1. Dán link repo của bạn vào ô dưới (thay `Phucvncom55/AISTV`), **hoặc** dùng
   `bash <(curl -fsSL .../bootstrap.sh) https://github.com/Phucvncom55/AISTV`.
2. Mở 🔑 **Secrets** (cột trái) → thêm `TELEGRAM_BOT_TOKEN` (và `ALLOWED_USER_IDS`),
   bật **Notebook access**.
3. Dán vào một ô code rồi Run:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

Script tự: clone/cập nhật repo → lấy token từ Secrets → chọn Python (venv → hệ thống → uv) → cài thư viện → cài OpenCode → chạy bot.
Không có Secrets thì script báo rõ cách thêm và dừng, không cài lan man.

> Colab không có terminal tương tác nên **không nhập token bằng tay** được — hãy dùng Secrets
> (hoặc `!TELEGRAM_BOT_TOKEN=123:abc bash <(curl ...)` nếu không ngại lộ token trong notebook).

### Chạy lại / VPS

```bash
cd ~/AISTV && bash run.sh          # đã có .env thì chạy thẳng
```

Muốn chạy nền trên VPS:

```bash
cd ~/AISTV && nohup bash run.sh > aistv.log 2>&1 &
```

## 4. Dùng bot

| Lệnh | Tác dụng |
|---|---|
| `/start` `/help` | Giới thiệu, hướng dẫn |
| `/new` | Cuộc trò chuyện mới (giữ trí nhớ dài hạn) |
| `/stop` | Huỷ tác vụ đang chạy |
| `/status` | Trạng thái bot, model, thời gian chạy |
| `/model` `/models` | Xem / đổi model OpenCode |
| `/remember` `/memory` `/forget` | Trí nhớ dài hạn |
| `/skills` `/skill <tên> <yêu cầu>` | Kỹ năng chuyên biệt |
| `/files` `/get <đường dẫn>` | Liệt kê / tải file agent tạo |
| `/allow <id>` `/deny <id>` | Cấp / thu hồi quyền (chủ bot) |

**Chủ động & trí nhớ**

| Lệnh | Tác dụng |
|---|---|
| `/remind +30m uống nước` | Hẹn nhắc việc (`+2h`, `20:30`, `mai 8:00`, `25/12 20:00`, `daily 8:00`) |
| `/task daily 9:00 kiểm tra repo` | Để **agent tự chạy** yêu cầu theo lịch rồi gửi kết quả |
| `/reminders` · `/unremind <mã\|all>` | Xem / xoá nhắc việc |
| `/watch git owner/repo [nhánh]` | Báo khi repo có commit mới |
| `/watch log <file> [regex]` | Báo dòng lỗi mới trong log (bot tự theo dõi log của nó) |
| `/watch file <đường dẫn>` | Báo khi file/thư mục thay đổi |
| `/cloud [sync]` | Trạng thái trí nhớ đám mây / đẩy ngay lên Firebase |
| `/summary` | Cô đọng hội thoại hiện tại vào `MEMORY.md` |
| `/email` | Trạng thái kết nối email |
| `/email test` | Kiểm tra đăng nhập IMAP |
| `/email inbox [n]` · `/email unread [n]` | Xem hộp thư / thư chưa đọc |
| `/email read <số\|uid>` | Đọc nội dung một thư |
| `/email send a@b.c \| Tiêu đề \| Nội dung` | Gửi thư |
| `/email setup <email> <app-password>` | Lưu cấu hình (chủ bot) |
| `/email reset` | Xoá cấu hình đã lưu |

- **Trí nhớ đám mây (Firebase RTDB):** `MEMORY.md`, lịch sử chat, nhắc việc và watch được lưu trên cloud nên **restart bot / Colab reset vẫn còn**. Mỗi bot dùng namespace riêng `AISTV_CLOUD_NS/<bot id>`.
- **Tự tóm tắt:** sau ~20 lượt hỏi–đáp, bot tự cô đọng phần cũ thành gạch đầu dòng trong `MEMORY.md` rồi cắt bớt lịch sử (giữ ngữ cảnh gần).
- **Nhắc việc/việc định kỳ** sống qua restart; việc định kỳ dùng đúng model và workspace hiện tại.

**Email (IMAP/SMTP):** thêm 2 Colab Secret `AISTV_EMAIL_ADDRESS` + `AISTV_EMAIL_PASSWORD` (mật khẩu ứng dụng) rồi bật Notebook access; hoặc `/email setup <email> <app-password>`. Gmail cần bật 2FA và tạo App Password 16 ký tự. Agent cũng gọi được `aistv_email.py` để đọc/gửi thư trong lúc làm việc; mật khẩu không bao giờ bị in ra.

Gửi file cho bot → lưu vào `workspace/inbox/` để agent đọc.

**Tiến độ kiểu terminal:** trong lúc chạy, tin nhắn "Đang làm việc" tự cập nhật ~1 giây/lần trong một **trích dẫn thu gọn/mở rộng** (`blockquote expandable`); lệnh và code nằm trong khối mã nên dễ đọc trên điện thoại. Dòng cũ rơi khỏi đỉnh khi đầy. `/think off` ẩn suy nghĩ; `/activity on` hiện thêm output chi tiết.

## 5. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Token từ BotFather (bắt buộc) |
| `ALLOWED_USER_IDS` | trống | Danh sách user id được phép, cách nhau `,` |
| `STV_HOME` | `~/stv_agent` | Nơi lưu `workspace/`, `sessions/`, `archive/` |
| `OPENCODE_BIN` | tự tìm | Đường dẫn `opencode` |
| `AISTV_CLEAN_INSTALL` | `1` | `0` = không xoá & cài lại OpenCode mỗi lần chạy |
| `AISTV_VENV` | `1` | `0` = dùng Python hệ thống, không tạo `.venv` |
| `AISTV_REPO` | URL trong `run.sh` | Repo khác để tải mã nguồn |
| `AISTV_DIR` | `~/AISTV` | Nơi clone khi chạy one-liner |
| `AISTV_BRANCH` | `main` | Nhánh cần tải |
| `AISTV_FIREBASE_URL` | RTDB mặc định | URL Firebase Realtime Database cho trí nhớ đám mây |
| `AISTV_CLOUD` | `1` | `0` = tắt đồng bộ cloud (chỉ lưu cục bộ) |
| `AISTV_CLOUD_NS` | `aistv` | Namespace gốc trên Firebase |
| `AISTV_FIREBASE_SECRET` | trống | `?auth=` nếu Rules yêu cầu xác thực |
| `AISTV_AUTO_SUMMARY` | `1` | `0` = tắt tự tóm tắt hội thoại |
| `AISTV_SUMMARY_ITEMS` / `AISTV_SUMMARY_KEEP` | `40` / `16` | Ngưỡng kích hoạt / số lượt giữ lại |
| `AISTV_PROACTIVE` | `1` | `0` = tắt nhắc việc & theo dõi |
| `AISTV_REMIND_TICK` | `15` | Nhịp kiểm tra nhắc việc (giây) |
| `AISTV_WATCH_INTERVAL` / `AISTV_WATCH_GIT_INTERVAL` | `60` / `300` | Nhịp theo dõi log/file · git |
| `AISTV_WATCH_SELF` | `1` | Tự báo lỗi trong log của chính bot |
| `AISTV_PROGRESS_TICK` | `1` | Giây giữa 2 lần cập nhật khung tiến độ |
| `AISTV_PROGRESS_LINES` | `14` | Số dòng cuộn trong khung tiến độ (dòng cũ rơi khỏi đỉnh) |
| `AISTV_EMAIL_ADDRESS` | trống | Địa chỉ email nhận/gửi |
| `AISTV_EMAIL_PASSWORD` | trống | Mật khẩu ứng dụng (App Password), không phải mật khẩu đăng nhập |
| `AISTV_EMAIL_IMAP_HOST` / `AISTV_EMAIL_IMAP_PORT` | tự nhận / `993` | Máy chủ IMAP |
| `AISTV_EMAIL_SMTP_HOST` / `AISTV_EMAIL_SMTP_PORT` | tự nhận / `587` | Máy chủ SMTP |

Cấu hình nâng cao nằm ở đầu `aistv_bot.py` (model, timeout, số lịch sử, `FULL_ACCESS`, `USE_GOOGLE_DRIVE`).

## 6. Cấu trúc

```
AISTV/
├── aistv_bot.py      bot hoàn chỉnh (cài đặt, agent, Telegram, định dạng)
├── aistv_email.py    đọc/gửi email IMAP·SMTP + CLI cho agent
├── bootstrap.sh      lấy/cập nhật repo rồi chạy run.sh (khuyến nghị)
├── run.sh            chạy 1 lệnh: clone → cài → chạy
├── push.sh           tạo repo GitHub và push
├── requirements.txt
├── .env.example
├── seed/             SOUL.md, AGENTS.md, skills mặc định
├── logs/             (tạo lúc chạy) aistv.log xoay vòng 2MB × 3
└── workspace/        (tạo lúc chạy) trí nhớ, skills, inbox, file agent tạo
```

Dữ liệu chạy nằm ngoài repo tại `STV_HOME` (mặc định `~/stv_agent`), nên cập nhật code không mất trí nhớ.

## 7. Bảo mật

- Luôn đặt `ALLOWED_USER_IDS` nếu bot ở nơi công cộng.
- Token chỉ đọc từ biến môi trường / Colab Secrets / `.env`; agent không nhìn thấy token (đã xoá khỏi môi trường tiến trình con).
- `FULL_ACCESS = False` mặc định: agent chỉ ghi trong workspace và bị OpenCode chặn thao tác cần quyền.
- Repo public **không chứa bí mật**; đừng commit `.env`.
- **Firebase Rules:** mặc định bot chỉ lưu URL database, không nhúng API key. Nếu Rules đang `true` (mở), **ai biết URL cũng đọc/ghi/xoá được** — hãy siết Rules và chỉ cho phép đúng namespace `aistv/<bot id>`, hoặc bật `AISTV_FIREBASE_SECRET`. Không lưu dữ liệu nhạy cảm (mật khẩu, token) vào trí nhớ.

## Giấy phép

MIT — xem `LICENSE`.
