# AI STV — Bot Telegram × OpenCode

Bot Telegram dạng agent: nhận yêu cầu, chạy **OpenCode** trong workspace, trả kết quả về chat. Có trí nhớ dài hạn, nhật ký theo ngày, skills, gửi/nhận file và lịch sử hội thoại bền vững.

Chạy được trên **Colab, VPS, máy cá nhân** — chỉ cần Python 3.10+ và mạng.

## ⚡ 3 bước

1. `bash push.sh AISTV public` → in ra **link repo** + lệnh chạy.
2. Thêm `TELEGRAM_BOT_TOKEN` (và `ALLOWED_USER_IDS`) vào 🔑 Secrets của Colab.
3. Dán lệnh này vào ô Colab:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/<USER>/AISTV/main/run.sh)
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

`push.sh` đã tự ghi URL repo của bạn vào `run.sh`, nên lệnh chỉ cần dán **một lần** (thay `Phucvncom55/AISTV`):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/run.sh)
```

Nếu chưa sửa `run.sh`, truyền repo trực tiếp (dán link GitHub):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/run.sh) https://github.com/Phucvncom55/AISTV
```

Lần đầu script sẽ: tải repo → lấy/hỏi token → tạo `.venv` → cài thư viện → cài OpenCode → chạy bot.
Token lấy theo thứ tự: `.env` → biến môi trường → Colab Secrets → hỏi trực tiếp (máy có terminal).

### Chạy trên Google Colab

1. Dán link repo của bạn vào ô dưới (thay `Phucvncom55/AISTV`), **hoặc** dùng
   `bash <(curl -fsSL .../run.sh) https://github.com/Phucvncom55/AISTV`.
2. Mở 🔑 **Secrets** (cột trái) → thêm `TELEGRAM_BOT_TOKEN` (và `ALLOWED_USER_IDS`),
   bật **Notebook access**.
3. Dán vào một ô code rồi Run:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/run.sh)
```

Script tự: clone → lấy token từ Secrets → tạo `.venv` → cài thư viện → cài OpenCode → chạy bot.
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

Gửi file cho bot → lưu vào `workspace/inbox/` để agent đọc.

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

Cấu hình nâng cao nằm ở đầu `aistv_bot.py` (model, timeout, số lịch sử, `FULL_ACCESS`, `USE_GOOGLE_DRIVE`).

## 6. Cấu trúc

```
AISTV/
├── aistv_bot.py      bot hoàn chỉnh (cài đặt, agent, Telegram, định dạng)
├── run.sh            chạy 1 lệnh: clone → cài → chạy
├── push.sh           tạo repo GitHub và push
├── requirements.txt
├── .env.example
├── seed/             SOUL.md, AGENTS.md, skills mặc định
└── workspace/        (tạo lúc chạy) trí nhớ, skills, inbox, file agent tạo
```

Dữ liệu chạy nằm ngoài repo tại `STV_HOME` (mặc định `~/stv_agent`), nên cập nhật code không mất trí nhớ.

## 7. Bảo mật

- Luôn đặt `ALLOWED_USER_IDS` nếu bot ở nơi công cộng.
- Token chỉ đọc từ biến môi trường / Colab Secrets / `.env`; agent không nhìn thấy token (đã xoá khỏi môi trường tiến trình con).
- `FULL_ACCESS = False` mặc định: agent chỉ ghi trong workspace và bị OpenCode chặn thao tác cần quyền.
- Repo public **không chứa bí mật**; đừng commit `.env`.

## Giấy phép

MIT — xem `LICENSE`.
