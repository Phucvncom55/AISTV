# AI STV — Bot Telegram × OpenCode

Bot Telegram dạng agent: nhận yêu cầu, chạy **OpenCode** trong workspace rồi trả kết quả về chat.
Có trí nhớ dài hạn, nhắc việc, skills, gửi/nhận file, và đọc được ảnh, video, YouTube, Facebook, TikTok.

**Model:** DeepSeek v4.1 (chính) + Gemini 3.8 Flash (đọc ảnh, xem video).
Chạy trên Colab, VPS, Linux/macOS và Windows — chỉ cần Python 3.10+ và mạng.

## 1. Chạy bot

Lấy token: nhắn [@BotFather](https://t.me/BotFather) → `/newbot` → token dạng `123456:ABC…`.
Lấy user id của bạn: nhắn [@userinfobot](https://t.me/userinfobot).

**Google Colab** — thêm `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS` vào 🔑 Secrets (bật Notebook access), rồi Run:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

**Linux / macOS / VPS** — một lệnh:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

**Windows (cmd)** — dán một dòng:

```bat
curl -fsSL -o "%TEMP%\aistv.bat" "https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.bat?v=1" && call "%TEMP%\aistv.bat"
```

Lần đầu script tự clone repo, tạo `.venv`, cài thư viện + OpenCode, hỏi token nếu chưa có rồi chạy bot.
Các lần sau chỉ cần:

```bash
cd ~/AISTV && bash run.sh           # Colab / Linux / macOS
# chạy nền: nohup bash run.sh > aistv.log 2>&1 &
```

```bat
cd /d "%USERPROFILE%\AISTV"
run.bat
```

Dữ liệu (trí nhớ, lịch sử, file agent tạo) nằm ngoài repo ở `~/stv_agent` — cập nhật code không mất.

## 2. Cấu hình tối thiểu

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token BotFather |
| `ALLOWED_USER_IDS` | nên đặt | Chỉ những id này dùng được bot (cách nhau dấu phẩy) |
| `GEMINI_API_KEY` | tuỳ chọn | Đọc ảnh, xem video, chép lời (thiếu vẫn chạy) |
| `AISTV_FIREBASE_URL` | tuỳ chọn | URL Firebase RTDB để đồng bộ trí nhớ cloud (đặt trong `config.env` của repo private) |

Đặt key ngay trong chat (tin nhắn chứa key tự xoá): `/key gemini AIza...`

## 3. Bot làm được gì

- **Sửa code như agent:** sửa file trong workspace, chạy lệnh, báo diff. `/plan <yêu cầu>` chia 2–8 bước, tự chạy – tự kiểm chứng – tự sửa. `/undo` hoàn tác, nút ⬆️ Push để đẩy lên GitHub (mặc định không tự push).
- **Trí nhớ dài hạn:** `/remember`, `/memory`, `/forget`; tự tóm tắt hội thoại cũ vào `MEMORY.md`; lưu cloud nên restart vẫn còn.
- **Nhắc việc & tự động:** `/remind +30m uống nước`, `/task daily 9:00 kiểm tra repo`, `/watch git owner/repo`, `/watch log <file>`, `/watch file <đường dẫn>`.
- **Ảnh:** gửi ảnh kèm câu hỏi → Gemini mô tả, OCR, đọc biểu đồ. `/see <url>`, `/image <mô tả>` tạo ảnh (nhiều style, tỉ lệ), `/mindmap <chủ đề>` vẽ sơ đồ tư duy.
- **Video:** `/video <link|file>` xem video dưới 45 phút (hình + tiếng, kèm mốc thời gian). Gửi file ≤ 20MB; dài hơn thì gửi link.
- **YouTube / Facebook / TikTok:** tìm, lấy thông tin, phụ đề, tải video/âm thanh (TikTok không watermark).
- **Tin nhắn thoại:** gửi voice → chép lời rồi xử lý như tin chữ.
- **GitHub:** `/github login` (mã device), quét/tạo repo, đọc README–docs–mã nguồn không cần clone, `/push`.
- **Email:** `/email inbox`, `/email read`, `/email send`, `/email setup`.
- **File:** gửi file cho bot → lưu `workspace/inbox/` để agent đọc; `/files`, `/get <đường dẫn>`.
- **Skills:** `/skills` xem, `/skill <tên> <yêu cầu>` ép dùng, `/skill add owner/repo/path` cài thêm. Có sẵn: debug, TDD, code review, PR, thiết kế codebase, spec/ticket, dạy học, viết lách, frontend design, MCP server…
- **Chế độ khách:** người ngoài `ALLOWED_USER_IDS` chỉ chat chữ, không dùng lệnh/nút/file/lịch sử.

## 4. Lệnh hay dùng

| Lệnh | Tác dụng |
|---|---|
| `/new` `/stop` `/status` | Chat mới · huỷ tác vụ · trạng thái |
| `/plan <yêu cầu>` | Chia bước và tự thực thi |
| `/undo` `/push` | Hoàn tác · đẩy code lên GitHub |
| `/model` `/models` | Xem / đổi model |
| `/remember` `/memory` | Trí nhớ dài hạn |
| `/remind` `/reminders` `/task` | Nhắc việc · việc định kỳ |
| `/see` `/video` `/image` `/mindmap` | Ảnh · video · tạo ảnh · sơ đồ tư duy |
| `/skills` `/skill` | Kỹ năng |
| `/github` | Đăng nhập, chọn/tạo repo, push |
| `/email` | Đọc / gửi email |
| `/files` `/get` | Xem / tải file agent tạo |
| `/allow` `/deny` | Cấp / thu quyền (chủ bot) |

## 5. Lưu ý

- Luôn đặt `ALLOWED_USER_IDS` nếu bot ở nơi công cộng.
- Không commit `.env`; repo public không chứa bí mật.
- Chi tiết công cụ: [docs/TOOLS.md](docs/TOOLS.md) · bản đồ code: [docs/CODEMAP.md](docs/CODEMAP.md) · khóa Firebase: [docs/FIREBASE.md](docs/FIREBASE.md).

Giấy phép: MIT — xem `LICENSE`.
