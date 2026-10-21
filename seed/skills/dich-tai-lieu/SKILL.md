---
name: dich-tai-lieu
description: Dịch tài liệu PDF/DOCX/ảnh scan sang tiếng Việt (hoặc ngược lại) mà GIỮ định dạng: tiêu đề, đoạn, bảng, ghi chú. Nhận file hoặc ảnh, đọc bằng OCR local rồi dịch từng đoạn. Dùng khi người dùng gửi tài liệu nước ngoài, đề bài tiếng Anh, hợp đồng, slide, sách.
---

# Dịch tài liệu giữ định dạng

## Quy trình bắt buộc

1. **Đọc file** (local, không tốn Gemini cho phần đọc):
   ```
   python aistv_docs.py "<file>" --out workspace/dich/src.txt --json
   ```
   - Ảnh/PDF scan → OCR bằng `--lang vie+eng` (hoặc `eng` nếu tài liệu tiếng Anh).
   - Nếu `ok=false`: báo đúng lỗi (thiếu tesseract / PDF scan), không bịa nội dung.

2. **Tách cấu trúc** thành khối có nhãn, lưu `workspace/dich/blocks.json`:
   ```json
   [{"id":1,"kind":"h1","text":"INTRODUCTION"},
    {"id":2,"kind":"p","text":"..."},
    {"id":3,"kind":"table","rows":[["A","B"],["1","2"]]}]
   ```
   Giữ nguyên thứ tự và số khối. Không gộp 2 đoạn thành 1.

3. **Dịch từng khối** (batch 8–12 khối/lần để không mất ngữ cảnh):
   - Văn phong: trung tính, đúng thuật ngữ ngành.
   - Tên riêng, số liệu, công thức, mã code, trích dẫn: **giữ nguyên**.
   - Thuật ngữ lặp lại: dùng `workspace/dich/glossary.json` để nhất quán.
   - Không thêm bình luận, không tóm tắt, không bỏ câu.

4. **Xuất bản dịch**:
   - Mặc định: `workspace/dich/<ten>-vi.md` (Markdown, giữ heading/bảng).
   - Nếu người dùng cần DOCX: tạo bằng `python-docx` theo đúng `blocks.json`
     (heading style, bảng thật, không phải ảnh).
   - Giữ tên file gốc + hậu tố `-vi`.

5. **Báo cáo ngắn**:
   ```
   ✅ Đã dịch 42 khối · 6 trang · 3 bảng
   📄 workspace/dich/ten-vi.md
   ⚠️ 2 khối OCR không chắc: #7, #19
   ```

## Chất lượng

- Câu dài tiếng Anh: tách thành 2 câu tiếng Việt nếu cần, không dịch word-by-word.
- Không dịch: URL, email, mã lệnh trong backtick, số hiệu điều khoản.
- Nếu tài liệu > 30 trang: dịch theo chương, lưu tiến độ vào
  `workspace/dich/progress.json`, báo người dùng tiếp tục bằng `/tiep`.
- Sai chính tả OCR ở tên riêng: giữ nguyên bản gốc + ghi chú trong ngoặc.

## Không làm

- Không tự tóm tắt thay vì dịch.
- Không đổi đơn vị đo, tiền tệ, ngày tháng.
- Không bỏ qua bảng — bảng phải được dịch và giữ cấu trúc ô.
