---
name: tiktok
description: Xem thông tin, tải video không watermark, tách âm thanh và tìm video TikTok — gồm cả link TikTok Lite.
---
# tiktok
Xem thông tin, tải video không watermark, tách âm thanh và tìm video TikTok — gồm cả link TikTok Lite.

## Khi nào dùng
- Người dùng gửi link TikTok (kể cả `vt.`, `vm.`, `lite.tiktok.com/t/...`) và hỏi nội dung, tác giả, thống kê.
- Người dùng muốn tải video/audio TikTok về máy.
- Người dùng nhờ tìm video TikTok theo từ khoá.

## Lệnh
Chạy từ workspace; repo AISTV nằm ở `../../AISTV` (hoặc dùng `$AISTV_DIR` nếu có):
```bash
TT="${AISTV_DIR:-../../AISTV}/aistv_tiktok.py"
python3 "$TT" info "URL"
python3 "$TT" download "URL" -q hd
python3 "$TT" download "URL" -q h264
python3 "$TT" download "URL" --audio
python3 "$TT" search "từ khoá" -n 8
python3 "$TT" resolve "URL"
```

- `info --json`, `download --json`, `search --json` khi cần dữ liệu có cấu trúc.
- `-q hd` bản nét nhất (có thể H.265); `-q h264` tương thích máy cũ/TV; `-q sd` nhẹ hơn.
- `download` mặc định lưu vào workspace, bot tự gửi nếu ≤ 45MB. Đổi thư mục bằng `-o`.
- Windows: `python "%AISTV_DIR%\aistv_tiktok.py" ...`.

## Quy trình
1. Có link → `info` trước để lấy tiêu đề, tác giả, thời lượng, lượt xem/thích/chia sẻ và nhạc nền.
2. Link rút gọn hoặc TikTok Lite → cứ đưa thẳng vào `info`/`download`; nếu cần kiểm tra đích đến thì chạy `resolve`.
3. Người dùng muốn tải → `download`; muốn nhạc/giọng nói → thêm `--audio`.
4. Tìm theo từ khoá → `search`; nêu tên video + tác giả, không dán quá nhiều kết quả.
5. Tóm tắt/trả lời theo đúng yêu cầu, trích dẫn ngắn; không bịa nội dung nếu chỉ có metadata.

## Giới hạn
- Chỉ video **công khai**. Video riêng tư, giới hạn tuổi/vùng có thể cần cookie trong `TIKTOK_COOKIES`.
- Link `lite.tiktok.com/t/...` thường là link **mời/nhận thưởng**, không phải video → báo rõ và hướng dẫn mở đúng video rồi Chia sẻ → Sao chép liên kết.
- Bài ảnh/slideshow chưa hỗ trợ tải; chỉ xem được thông tin nếu TikTok trả dữ liệu.
- Bot Telegram chỉ gửi được file ≤ 45MB; video lớn hơn sẽ báo rõ.
- TikTok hay chặn IP datacenter; nếu lỗi truy cập, kiểm tra đã cài `curl_cffi` (có trong requirements) chưa.
