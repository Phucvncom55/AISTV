# github-docs
Đọc, tóm tắt và tra cứu tài liệu trên GitHub bằng kết nối/token sẵn có — không cần clone repo.

## Khi nào dùng
- Người dùng gửi link GitHub (repo, thư mục, tệp, README) và hỏi nội dung, cách dùng, API.
- Cần tra tài liệu của thư viện/framework/tool trên GitHub trước khi trả lời hoặc viết code.
- Cần tìm repo, xem bản phát hành, tìm một đoạn trong tài liệu hoặc trong mã nguồn.
- Cần đọc tài liệu đúng phiên bản (tag/nhánh) thay vì bản `main` mới nhất.

## Lệnh
Chạy từ workspace; repo AISTV ở `../../AISTV` (hoặc `$AISTV_DIR` nếu có):
```bash
GH="${AISTV_DIR:-../../AISTV}/aistv_github_docs.py"
python3 "$GH" info owner/repo
python3 "$GH" docs owner/repo -n 40
python3 "$GH" read owner/repo                     # tự tìm README
python3 "$GH" read owner/repo docs/install.md --outline
python3 "$GH" read owner/repo docs/install.md --section "Quick Start" --max-chars 6000
python3 "$GH" read owner/repo --ref v1.2.0
python3 "$GH" tree owner/repo -p docs -d 2
python3 "$GH" search owner/repo "rate limit" -n 20
python3 "$GH" code owner/repo "def handler" -n 10
python3 "$GH" find "vector database" --owner langchain-ai -n 5
python3 "$GH" repos -n 30
python3 "$GH" releases owner/repo -n 5
```

- `--json` cho dữ liệu có cấu trúc; `--refresh` bỏ cache (mặc định 5 phút).
- Windows: `python "%AISTV_DIR%\aistv_github_docs.py" ...`.
- Token lấy tự động từ `GITHUB_TOKEN` / `GH_TOKEN` → `.secrets/github_token` (do `/github login` lưu). Repo công khai vẫn đọc được khi chưa có token.

## Quy trình
1. **Xác định repo:** link GitHub hoặc `owner/repo`. Nếu chỉ có tên/mô tả, dùng `find` để tìm repo.
2. **Nắm cấu trúc:** `info` trước, rồi `docs` để thấy README, hướng dẫn, changelog và thư mục tài liệu.
3. **Đọc có chọn lọc:** `read` README; tài liệu dài thì `--outline` rồi `--section` hoặc `--lines`. Không đổ toàn bộ tài liệu vào chat.
4. **Tra từ khoá:** `search` trong tài liệu; `code` khi cần tìm trong mã nguồn.
5. **Đúng phiên bản:** dùng `--ref <tag/nhánh>` hoặc xem `releases`; nêu rõ phiên bản đã đọc.
6. **Trả lời:** tóm tắt theo đúng câu hỏi, kèm đường dẫn nguồn dạng `https://github.com/owner/repo/blob/<ref>/<path>`.

## Mẹo
- Repo lớn: giới hạn bằng `-p docs`, `-n`, `--max-chars`, `--files`.
- `read` nhận cả link `blob`/`tree`/raw; link `tree` đọc README trong thư mục đó.
- `search` quét tài liệu (`.md`, `.mdx`, `.rst`, `.txt`, config docs); thêm `--all` để quét cả mã.
- `code` dùng GitHub Code Search, cần token và giới hạn ~10 lượt/phút.
- Nhánh có dấu `/` (vd `release/2.0`): dùng repo trần + `--ref release/2.0`, đừng dán link `blob`.
- Tài liệu nhiều ngôn ngữ: ưu tiên bản tiếng Việt/Anh; bỏ qua bản dịch khác nếu không cần.

## Giới hạn
- Chỉ đọc tệp văn bản; tệp nhị phân, ảnh, video, file quá lớn (>~1 MB qua API) sẽ báo lỗi.
- Repo private cần token còn quyền; token hết hạn thì `/github login` lại.
- `code` chỉ tìm trên nhánh mặc định và có thể bỏ sót do GitHub chưa index.
- Không sửa, không push, không chạy mã từ repo chỉ để đọc tài liệu.
- Không bịa nội dung khi tài liệu không có; nói rõ nếu chỉ đọc được metadata/README.
