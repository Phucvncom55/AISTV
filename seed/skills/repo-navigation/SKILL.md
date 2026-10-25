---
name: repo-navigation
description: Định vị code trong repo AISTV bằng CODEMAP + grep thay vì đọc cả file — dùng khi tìm hàm/class, hiểu một module, hoặc sửa code của bot.
---
# repo-navigation

## Hai thư mục, đừng lẫn
- **Repo chính** (code bot): thư mục chứa `aistv_bot.py`, env `$AISTV_DIR`
  (thường `/root/AISTV` hoặc `~/AISTV`). Đây là nơi sửa code.
- **Workspace** (dữ liệu người dùng): `$HOME/workspace` — nơi bạn tạo file, ghi `MEMORY.md`,
  `memory/`, `skills/`, `inbox/`.
- `seed/` chỉ là bản mẫu cho máy mới; sửa `seed/` **không** làm bản đang chạy đổi theo.

## Quy trình định vị (làm theo thứ tự)
1. **Xem bản đồ**: đọc `docs/CODEMAP.md` trong repo. Bảng đầu tiên cho biết mỗi file
   làm gì và dài bao nhiêu dòng; phần sau liệt kê `L<dòng> def/class tên(...) — mô tả`.
2. **Grep symbol**: `grep -n "def tên_hàm" aistv_bot.py` (hoặc `grep -n "class Tên"`).
   Với handler/nút bấm: `grep -n "tên_callback" aistv_bot.py`.
3. **Đọc có cửa sổ**: chỉ đọc 60–150 dòng quanh symbol bằng `Read` với `offset`/`limit`.
   Không đọc cả `aistv_bot.py` (hơn 7.000 dòng) và không đoán số dòng.
4. **Sửa tối thiểu**: giữ đúng phong cách file (hàm đồng bộ/async, chuỗi tiếng Việt,
   `esc()` cho HTML Telegram, `oneline()` cho log). Không reformat cả file.
5. **Kiểm chứng**: `python scripts/verify.py --fast` trong repo; PASS rồi mới báo xong.
   Sửa test/cấu hình thì chạy đầy đủ `python scripts/verify.py`.
6. **Cập nhật bản đồ**: thêm/bớt hàm hoặc class cấp module → chạy
   `python scripts/code_map.py` để sinh lại `docs/CODEMAP.md` (verify sẽ báo nếu bản đồ cũ).

## Mẹo
- Tìm theo hành vi: `grep -n "AUTO_PUSH\|callback_data\|@guard" aistv_bot.py`.
- Muốn biết hàm được gọi ở đâu: `grep -rn "tên_hàm" --include=*.py .`.
- CODEMAP chỉ quét file `.py` cấp gốc + `scripts/` + `tests/`; JS trong
  `.opencode/tools/` và `seed/skills/` không có trong bản đồ.
- Không bao giờ mở `.env`, `.secrets/`, hay file token để "kiểm tra" — chỉ đọc tên biến.

## Kết quả cần đạt
Nêu đúng file + số dòng của phần đã sửa, kết quả verify, và những chỗ **chưa** kiểm chứng được.
