---
name: facebook
description: Đọc bài viết công khai, xem/tải video, reel và tìm nội dung trên Facebook.
---
# facebook
Đọc bài viết công khai, xem/tải video, reel và tìm nội dung trên Facebook.

## Khi nào dùng
- Người dùng gửi link Facebook (bài viết, video, reel, watch) và hỏi nội dung, muốn tóm tắt/dịch.
- Người dùng nhờ tìm bài/video Facebook theo từ khoá.
- Người dùng muốn tải video/reel về máy.

## Lệnh
Chạy từ workspace; repo AISTV nằm ở `../../AISTV` (hoặc dùng `$AISTV_DIR` nếu có):
```bash
FB="${AISTV_DIR:-../../AISTV}/aistv_facebook.py"
python3 "$FB" info "URL"
python3 "$FB" read "URL" --comments -n 12000
python3 "$FB" download "URL" -q sd
python3 "$FB" search "từ khoá" -n 8
```

- `info --json`, `read --json`, `search --json` khi cần dữ liệu có cấu trúc.
- `read` mặc định bỏ bình luận; thêm `--comments` nếu người dùng muốn xem thảo luận.
- `download -q hd` lấy bản nét hơn (mặc định `sd`, nhẹ hơn cho Telegram).
- Windows: `python "%AISTV_DIR%\aistv_facebook.py" ...`.

## Quy trình
1. Có link → `info` trước. Video/reel trả tiêu đề, kênh, thời lượng, lượt xem, mô tả; bài viết trả nội dung.
2. Người dùng hỏi nội dung → `read` (thêm `--comments` nếu cần).
3. Muốn tải video → `download`; file lưu vào workspace và bot tự gửi nếu ≤ 45MB.
4. Tìm theo từ khoá → `search` (mặc định giới hạn `site:facebook.com`).
5. Tóm tắt theo đúng yêu cầu, trích dẫn ngắn; không chép nguyên cả bài dài vào chat.

## Giới hạn
- Chỉ đọc nội dung **công khai**. Trang cá nhân, nhóm kín, feed, nội dung bạn bè cần đăng nhập → báo rõ không xem được.
- Facebook hay chặn truy cập ẩn danh; nếu lỗi đăng nhập thì thử lại link bài/video cụ thể thay vì link trang chủ.
- `search` dùng DuckDuckGo nên có thể chậm hoặc bị giới hạn tần suất.
- Không tải video quá lớn; bot Telegram chỉ gửi được file ≤ 45MB.
