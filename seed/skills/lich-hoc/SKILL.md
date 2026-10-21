---
name: lich-hoc
description: Thời khoá học (TKB) cho học sinh. Nhận ẢNH chụp thời khoá biểu, file PDF/DOCX/Excel/ảnh, đọc bằng OCR local rồi lưu thành tkb.json; trả lời "hôm nay học gì", nhắc trước buổi kiểm tra, đếm ngược. Dùng khi người dùng gửi ảnh TKB, hỏi lịch học, lịch thi, hoặc muốn nhắc môn/buổi sắp tới.
---

# Thời khoá biểu (lich-hoc)

## Nguyên tắc

- TKB đến từ **ảnh chụp / file** là chính. Không bắt người dùng gõ lại.
- Đọc bằng `aistv_docs.py` (OCR local, không tốn Gemini). Nếu OCR sai
  tên môn, hỏi lại đúng 1 lần rồi sửa.
- Mọi dữ liệu lưu ở `workspace/hoc-tap/tkb.json`. Không lưu trong MEMORY.md.
- Giờ Việt Nam (Asia/Ho_Chi_Minh). Tuần bắt đầu Thứ 2.

## Các bước khi nhận ảnh/file TKB

1. Xác định đường dẫn file người dùng vừa gửi (thường trong `workspace/uploads/`).
2. Đọc:
   ```
   python aistv_docs.py "<duong-dan>" --lang vie+eng --json
   ```
   Nếu `ok=false` và báo thiếu tesseract → nói rõ cần cài, đồng thời đề nghị
   người dùng gửi ảnh rõ hơn. Không bịa TKB.
3. Chuẩn hoá về JSON:
   ```json
   {
     "lop": "11A1",
     "cap_nhat": "2026-10-21",
     "tiet": {"1": "07:00", "2": "07:45", "3": "08:35", "4": "09:25", "5": "13:30"},
     "tuan": {
       "thu2": [{"tiet": 1, "mon": "Toán", "gv": "", "phong": ""}],
       "thu3": [], "thu4": [], "thu5": [], "thu6": [], "thu7": [], "cn": []
     },
     "kiem_tra": [{"ngay": "2026-10-25", "mon": "Sinh", "noi_dung": "Chương 2"}]
   }
   ```
4. Ghi vào `workspace/hoc-tap/tkb.json` (giữ dữ liệu cũ nếu có, chỉ thay phần
   người dùng đưa).
5. Trả lời bằng bảng gọn, ví dụ:
   ```
   📅 TKB 11A1 (từ 21/10)
   T2: Toán · Lý · Anh · Sinh
   T3: Văn · Hoá · Tin · GDCD
   ...
   ```
   Rồi hỏi đúng 1 câu: "Có môn nào OCR sai không?"

## Trả lời câu hỏi lịch

Đọc `tkb.json` rồi tính theo ngày thật (`date`), không đoán thứ.

- "hôm nay học gì" → lịch của thứ tương ứng hôm nay + tiết đầu tiên.
- "mai học gì" → thứ kế tiếp.
- "còn mấy ngày thi Sinh" → đếm từ hôm nay tới `kiem_tra.ngay`.
- "nhắc trước 1 ngày" → tạo nhắc việc (`/remind`) lúc 20:00 hôm trước.

## Nhắc kiểm tra

Khi người dùng thêm `kiem_tra`, tự đề nghị:

```
/remind 2026-10-24 20:00 Ôn Sinh — kiểm tra Chương 2 ngày mai
```

Không tự tạo nhắc khi chưa được đồng ý.

## Giới hạn

- Không sửa TKB của lớp khác nếu người dùng không nói rõ lớp.
- Ảnh mờ: nói rõ vùng không đọc được, đừng suy diễn.
