---
name: cloudflare-aistv
description: Dùng Cloudflare qua API token của AI STV — Workers AI (chạy model), upload web (Pages/Workers), DNS, R2, kiểm tra token/account.
---
# cloudflare-aistv

Wrapper: `python %AISTV_DIR%\aistv_cloudflare.py <lệnh>` (Linux/mac: `python3 "$AISTV_DIR/aistv_cloudflare.py"`).
Bộ skill chính thức của Cloudflare đã cài ở `~/.agents/skills/` (`cloudflare`, `wrangler`, `cf-cli`, `agents-sdk`, `workers-best-practices`…). Đọc các skill đó khi cần code/deploy chuyên sâu.

## Token & account
- Token lưu ở `.secrets/cloudflare_token`, account ở `.secrets/cloudflare_account_id`; hoặc env `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.
- **Không bao giờ in token** ra chat/log. Không đưa token vào tham số dòng lệnh; dùng `token-save --stdin`.
- Token tối thiểu cho các việc dưới đây:
  - `Account:Read` (bắt buộc)
  - `Workers AI:Edit` (chạy model)
  - `Pages:Edit` + `Workers Scripts:Edit` (upload web)
  - `Zone:Read` + `DNS:Edit` (DNS)
  - `R2:Edit` (bucket R2)
- Tạo token: https://dash.cloudflare.com/profile/api-tokens → *Create Token* → *Custom token*.
- Kiểm tra: `check` (trạng thái token + account), `accounts`, `zones`.
- Trạng thái 21/10/2026: token **active**, account `1ffec22db7e8ba74af2364ae5ca81bef`; Workers AI và Pages chạy OK (7 project Pages sẵn có); **R2 chưa bật** trên dashboard nên lệnh R2 trả lỗi 10042.

## Lệnh thường dùng
```powershell
CF="$env:AISTV_DIR\aistv_cloudflare.py"
python "$CF" check
python "$CF" zones --name example.com
python "$CF" dns list --zone example.com
python "$CF" dns add --zone example.com --type A --name www --content 1.2.3.4 --proxied
python "$CF" ai models --task text-generation
python "$CF" ai run @cf/meta/llama-3.1-8b-instruct --prompt "Viết 3 câu về Cà Mau"
python "$CF" ai run @cf/black-forest-labs/flux-1-schnell --input '{"prompt":"sunset over Ca Mau"}' --out sunset.jpg
python "$CF" pages deploy .\dist --project my-site --branch main --create
python "$CF" workers deploy .\my-worker
python "$CF" r2 buckets
```

## Upload web
- Thư mục tĩnh/SPA có sẵn `dist`/`build`: `pages deploy <dir> --project <tên> --create` (lần đầu), các lần sau bỏ `--create`.
- Project mới Cloudflare khuyến nghị **Workers + Static Assets** thay vì Pages; dùng skill `wrangler`/`cloudflare` để tạo `wrangler.jsonc` rồi `workers deploy`.
- Deploy xong báo lại **URL** (`*.pages.dev` hoặc `*.workers.dev`) và lỗi đầu tiên nếu fail.
- Trước khi deploy đè production hoặc xoá project/bucket/DNS: **hỏi người dùng**.

## Workers AI
- Model phải đúng schema: model chat dùng `{"messages":[{"role":"user","content":"..."}]}`; model cũ dùng `{"prompt":"..."}`.
- Ảnh/audio trả về nhị phân → luôn truyền `--out`.
- Xem model + task: `ai models --search <từ khoá>`.

## MCP Cloudflare
- Đã cấu hình `cloudflare` remote MCP trong `~/.config/opencode/opencode.jsonc` (`https://mcp.cloudflare.com/mcp`).
- Cần OAuth một lần: `opencode mcp auth cloudflare` → mở link, Authorize. Kiểm tra `opencode mcp list`.
- Nếu chưa auth, dùng wrapper/API token ở trên vẫn chạy bình thường.

## Lỗi thường gặp
- `HTTP 401/403` → token sai/hết hạn/thiếu quyền; tạo token mới đúng scope.
- `Có nhiều account` → thêm `--account ID` hoặc lưu `.secrets/cloudflare_account_id`.
- `Không tìm thấy zone` → token không có quyền zone đó hoặc domain chưa add vào Cloudflare.
- Wrangler fail → đọc 100 dòng cuối output; kiểm tra `wrangler.jsonc`, tên project, quyền token.
