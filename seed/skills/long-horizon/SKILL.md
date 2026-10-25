---
name: long-horizon
description: Chia yêu cầu lớn (từ 3 bước hoặc nhiều file) thành kế hoạch, tự thực thi từng bước, tự chạy kiểm chứng và tự sửa lỗi trước khi báo cáo — dùng với /plan hoặc khi được giao việc dài.
---
# long-horizon — vòng lặp kế hoạch → hành động → kiểm chứng

Dùng khi yêu cầu không xong trong một lần sửa: nhiều file, nhiều tầng (code + test + tài liệu),
hoặc người dùng nói "làm hết", "xây", "refactor", "sửa toàn bộ".

## Vòng lặp (ReAct)
1. **Lập kế hoạch** — 2–8 bước, mỗi bước một mục tiêu kiểm chứng được. Nêu file/hàm dự kiến
   (tra `docs/CODEMAP.md` trước, đừng đoán). Bước 1 thường là khảo sát; bước cuối là kiểm chứng.
   Nếu người dùng gõ `/plan`, bot đã lo phần này và sẽ tự chạy.
2. **Làm đúng một bước** — đọc vùng code liên quan, sửa tối thiểu, không mở rộng phạm vi.
3. **Tự kiểm chứng** — chạy `python scripts/verify.py --fast` trong repo. Đọc **đúng lỗi**,
   không đoán. FAIL thì sửa nguyên nhân rồi chạy lại, tối đa 2 lần.
4. **Ghi nhận** — bước xong: tóm tắt 1–2 dòng (file nào đổi, bằng chứng). Bước lỗi: ghi rõ
   lỗi còn lại và đã thử gì, rồi **dừng** — không nhảy sang bước sau.
5. **Báo cáo cuối** — số bước xong/tổng, verify PASS/FAIL, thay đổi thực tế, việc còn lại.
   Không tuyên bố "đã xong" khi verify chưa PASS.

## Cổng an toàn
- Bot đã tạo **checkpoint** trước khi chạy; người dùng có thể hoàn tác bằng `/undo` hoặc nút ↩️.
- **Không** commit/push. Sau khi xong, bot hiện diff kèm nút ⬆️ Push để người dùng duyệt.
- Không xoá file, không đổi cấu hình hệ thống, không đọc `.env`/`.secrets` trong lúc làm.
- Bị chặn vì thiếu quyền/thông tin → gọi `ask_user` hoặc báo rõ cần gì; không tự đoán bừa.
- Hết ngân sách (quá 2 lần sửa cho một bước) → dừng, báo trung thực. Đó là kết quả đúng,
  không phải thất bại cần che.

## Khi nào KHÔNG cần skill này
Việc một bước (hỏi đáp, sửa một hàm, tạo một file) → trả lời trực tiếp, đừng dựng kế hoạch
cho có.
