---
name: youtube
description: Lướt YouTube — tìm video, xem thông tin, lấy phụ đề/transcript để đọc hoặc tóm tắt.
---
# youtube
Lướt YouTube: tìm video, xem thông tin, lấy phụ đề/transcript để đọc hoặc tóm tắt.

## Khi nào dùng
- Người dùng gửi link YouTube và hỏi nội dung, muốn tóm tắt/dịch/ghi chú.
- Người dùng muốn tìm video theo từ khoá.
- Cần kiểm tra tiêu đề, kênh, thời lượng, mô tả trước khi tải.

## Lệnh
Chạy từ workspace; repo AISTV nằm ở `../../AISTV` (hoặc dùng `$AISTV_DIR` nếu có):
```bash
YT="${AISTV_DIR:-../../AISTV}/aistv_youtube.py"
python3 "$YT" search "từ khoá" -n 5
python3 "$YT" info "URL"
python3 "$YT" transcript "URL"
python3 "$YT" transcript "URL" -l vi,en --timestamps --max-chars 12000
```

- `search --json` / `transcript --json` khi cần dữ liệu có cấu trúc.
- `info --full` để lấy đầy đủ mô tả và chương.
- Windows: `python ..\..\AISTV\aistv_youtube.py ...` hoặc `python "%AISTV_DIR%\aistv_youtube.py" ...`.

## Quy trình
1. Có link → `info` trước, rồi `transcript` nếu người dùng hỏi nội dung.
2. Tóm tắt theo đúng yêu cầu; giữ mốc thời gian khi hữu ích (`--timestamps`).
3. Trích dẫn ngắn gọn, không chép toàn bộ transcript vào chat.
4. Transcript lỗi → nói rõ chỉ có tiêu đề/mô tả, không bịa nội dung video.

## Lưu ý
- Ưu tiên phụ đề tiếng Việt, tự động chuyển sang tiếng Anh.
- Chỉ tải metadata/phụ đề, không tải video để tiết kiệm thời gian.
- Lỗi 429 (YouTube giới hạn) → thử lại sau hoặc chỉ dùng `info`.
