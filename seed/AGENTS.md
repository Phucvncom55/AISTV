# AGENTS — Quy tắc làm việc
1. Thư mục hiện tại là workspace của bạn. File bạn tạo phải nằm ở đây, tên rõ ràng, có đuôi file.
2. Tạo file thì nêu tên file ở cuối câu trả lời; bot sẽ tự gửi file cho người dùng.
3. File người dùng gửi nằm trong `inbox/`.
4. Việc phức tạp: lập kế hoạch ngắn (2-5 bước) → thực hiện → tự kiểm tra → báo kết quả.
5. Trước thao tác phá huỷ (xoá file, ghi đè, thay đổi hệ thống) phải hỏi lại người dùng.
6. Tuyệt đối không in ra hay gửi đi token, API key, mật khẩu hoặc biến môi trường.
7. `MEMORY.md` chứa thông tin lâu dài về người dùng — dùng khi liên quan, đừng lặp lại vô cớ.
8. Khi người dùng bảo "hãy nhớ…" hoặc nêu một sở thích/quy tắc lâu dài, hãy thêm MỘT dòng mới bắt đầu bằng `- ` vào cuối
   `MEMORY.md` (ví dụ `- [20/10/2026] Thích trả lời ngắn gọn`). Không xoá hay sửa các dòng cũ trừ khi được yêu cầu.
9. `memory/YYYY-MM-DD.md` là nhật ký theo ngày — chỉ mở khi người dùng hỏi về những gì đã làm trước đây.
10. `skills/` chứa quy trình chuyên biệt — làm đúng theo skill khi được kích hoạt.
11. Khi cần đọc/tra cứu tài liệu hoặc mã nguồn trên GitHub, dùng skill `github-docs` (tool `aistv_github_docs.py`).
12. Khi người dùng gửi link/file video và hỏi nội dung, dùng skill `watch` (tool `aistv_watch.py`); đọc frames bằng công cụ Read rồi trả lời kèm mốc thời gian.
13. Khi người dùng gửi ảnh/URL ảnh và hỏi nội dung, dùng `python3 aistv_watch.py image <path|url> --json` để Gemini đọc ảnh (mô tả + OCR chữ) rồi trả lời.
