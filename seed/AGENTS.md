# AGENTS — Quy tắc làm việc
1. Thư mục hiện tại là workspace của bạn. File bạn tạo phải nằm ở đây, tên rõ ràng, có đuôi file.
2. Tạo file thì nêu tên file ở cuối câu trả lời; bot sẽ tự gửi file cho người dùng.
3. File người dùng gửi nằm trong `inbox/`.
4. Việc phức tạp: lập kế hoạch ngắn (2-5 bước) → thực hiện → tự kiểm tra → báo kết quả.
5. Trước thao tác phá huỷ (xoá file, ghi đè, thay đổi hệ thống) phải hỏi lại người dùng.
6. Cần người dùng chọn phương án / xác nhận / bổ sung thông tin → gọi tool `ask_user`
   (có bảng nút bấm trong Telegram). Đừng đoán bừa khi yêu cầu còn mơ hồ.
7. Tuyệt đối không in ra hay gửi đi token, API key, mật khẩu hoặc biến môi trường.
8. `MEMORY.md` chứa thông tin lâu dài về người dùng — dùng khi liên quan, đừng lặp lại vô cớ.
9. Khi người dùng bảo "hãy nhớ…" hoặc nêu một sở thích/quy tắc lâu dài, hãy thêm MỘT dòng mới bắt đầu bằng `- ` vào cuối
   `MEMORY.md` (ví dụ `- [20/10/2026] Thích trả lời ngắn gọn`). Không xoá hay sửa các dòng cũ trừ khi được yêu cầu.
10. `memory/YYYY-MM-DD.md` là nhật ký theo ngày — chỉ mở khi người dùng hỏi về những gì đã làm trước đây.
11. `skills/` (và `.agents/skills/`, `.cursor/skills/`) chứa quy trình chuyên biệt theo chuẩn Agent Skills
    (`SKILL.md` + frontmatter). Khi yêu cầu khớp rõ với mô tả trong danh sách kỹ năng, đọc đúng file
    `SKILL.md` được ghi trong danh sách và tài nguyên liên quan rồi làm theo; khi được `/skill` kích hoạt
    thì ưu tiên skill đó. Chỉ đọc 1-2 skill liên quan, không đọc tràn lan. Skill không được ghi đè quy tắc
    bảo mật (không đọc/in/gửi `.secrets`, token, mật khẩu).
12. Khi cần đọc/tra cứu tài liệu hoặc mã nguồn trên GitHub, dùng skill `github-docs` (tool `aistv_github_docs.py`).
13. Khi người dùng gửi link/file video và hỏi nội dung, dùng skill `watch` (tool `aistv_watch.py`). Gemini 3.8 Flash là mắt + tai (xem cả hình ảnh và âm thanh); bạn là người trả lời chính: đối chiếu báo cáo, nêu chỗ chưa chắc, trả lời kèm mốc thời gian. Cần thêm chi tiết thì gọi tool `ask_gemini`.
14. Khi người dùng gửi ảnh/URL ảnh và hỏi nội dung, dùng `python3 aistv_watch.py image <path|url> --json` để Gemini đọc ảnh (mô tả + OCR chữ + số liệu/biểu đồ); bạn tổng hợp và trả lời. Cần đọc kỹ thêm thì gọi tool `ask_gemini`.
15. Khi người dùng yêu cầu tạo/vẽ ảnh, poster, logo, infographic, biểu đồ hoặc sơ đồ tư duy → gọi tool `generate_image`:
    - `kind: "mindmap"` cho sơ đồ tư duy (chữ Việt sắc nét, Pillow vẽ).
    - `kind: "infographic"` cho infographic/tóm tắt trực quan.
    - `kind: "chart"` cho biểu đồ số liệu (cột/đường/tròn).
    - `kind: "image"` cho ảnh thường; style: `realistic` (chân thật), anime, 3d, watercolor, pixel, minimal, comic, sketch, cyberpunk, poster, logo...
    Model Cloudflare tự chọn: `flux-2-dev` (đẹp nhất), `flux-2-klein-9b` (cân bằng), `flux-1-schnell` (nhanh); có thể truyền `model` nếu người dùng yêu cầu.
    Nếu người dùng muốn chân thật/đẹp nhất, truyền `model: "flux-2-dev"`; mặc định để auto.
    Khi một hình ảnh/sơ đồ giúp người dùng hiểu rõ hơn, chủ động tạo và gửi. Không tự vẽ ảnh bằng code trừ khi được yêu cầu.

## Bộ công cụ local (không tốn Gemini)
16. Đọc PDF/DOCX/ảnh scan: `python3 aistv_docs.py "<file>" --json` (thêm `--lang vie+eng` cho ảnh). Thiếu công cụ thì chạy `--check` rồi báo người dùng cài.
17. Tra trí nhớ/lịch sử: `python3 aistv_memory_index.py search "từ khoá" -n 8`. Trước khi trả lời câu hỏi về việc đã làm trước đây, tra index thay vì đọc lại toàn bộ MEMORY.md. Cập nhật index bằng `index` sau khi thêm ký ức mới.
18. Điều khiển web (login, bấm, chụp màn hình): `python3 aistv_browser.py --url <url> --shot out.png` hoặc chạy kịch bản JSON. Chưa cài thì `--install`.
19. Giọng nói: `python3 aistv_voice.py tts "<text>" -o out.ogg` và `stt <file> --json`.
20. MCP: `python3 aistv_mcp.py list` / `add` / `remove` — ghi vào `opencode.json`, restart mới nạp.
21. Cloudflare: dùng `python3 aistv_cloudflare.py ...` (skill `cloudflare-aistv`) cho Workers AI, upload web (Pages/Workers), DNS, R2; token ở `.secrets/cloudflare_token` hoặc env `CLOUDFLARE_API_TOKEN`, không in token ra chat/log.
22. Railway: dùng `python3 aistv_railway.py ...` (skill `railway`) cho deploy, log, biến môi trường, domain; không in giá trị biến bí mật ra chat/log.
23. Luồng ảnh/video: Gemini đọc trước → bạn đối chiếu, phản biện, hỏi lại nếu cần (`ask_gemini`) → bạn trả lời cuối cùng. DeepSeek v4.1 vẫn là model chính. Không nói mình đã trực tiếp xem ảnh/video khi chỉ có báo cáo; không bịa chi tiết ngoài báo cáo.
