# Third-party skills

Các skill dưới đây được nhúng từ repo bên thứ ba, giữ nguyên nội dung gốc (chỉ thêm SOURCE.md / LICENSE.txt).

## mattpocock/skills

- Repo: https://github.com/mattpocock/skills
- Commit: `5beb35b040e3de97e54fa9e386d7e42d15c295c2`
- Giấy phép: MIT — xem `LICENSE-mattpocock.txt` (bản gốc) và `LICENSE.txt` trong từng skill.
- Nhóm được chọn: engineering, productivity và writing (một số skill đang ở mức in-progress của upstream).

## anthropics/skills

- Repo: https://github.com/anthropics/skills
- Commit: `dbd4588f9e1033efb41dad4bef2f7947c8993d44`
- Giấy phép: Apache-2.0 — xem `LICENSE.txt` trong từng skill và `THIRD_PARTY_NOTICES-anthropic.md`.
- Không nhúng các skill tài liệu `docx`, `pdf`, `pptx`, `xlsx` vì các skill này dùng giấy phép source-available riêng của Anthropic, không phải Apache-2.0.
- Không nhúng `doc-coauthoring` vì thư mục upstream không có `LICENSE.txt`; có thể cài riêng bằng `/skill add anthropics/skills/skills/doc-coauthoring` sau khi tự kiểm tra điều khoản.
- Không nhúng `canvas-design` để giữ repo nhẹ và tránh rủi ro thiếu glyph tiếng Việt trong font; cài riêng nếu cần.

## Nguồn định dạng

- Cursor — Agent Skills: https://cursor.com/docs/skills
- Chuẩn Agent Skills: https://agentskills.io
