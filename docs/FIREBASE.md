# Firebase — khóa Rules

DB đang mở công khai thì ai biết URL cũng đọc/ghi/xóa được. Repo có sẵn `database.rules.json`:
chặn toàn bộ ở gốc, chỉ mở nhánh `aistv` cho client có auth.

## 1. Tạo database secret

Firebase Console → **Project settings** → **Service accounts** → tab **Database secrets** → *Show*.

Thêm vào `config.env` (repo private `AISTV-secrets` hoặc `~/.config/aistv/config.env`):

```dotenv
AISTV_FIREBASE_SECRET=<secret>
```

Bot đã hỗ trợ sẵn: mọi request cloud sẽ kèm `?auth=<secret>`.

## 2. Deploy rules

```bash
npx --yes firebase-tools@latest login
npx --yes firebase-tools@latest deploy --only database --project <PROJECT_ID>
```

`<PROJECT_ID>` là project của DB (xem URL trong `config.env`). Cần đăng nhập bằng tài khoản
Google sở hữu project.

## 3. Kiểm tra

```bash
python scripts/check_firebase_rules.py --url https://<db>.firebaseio.com
```

Mong đợi: đọc ẩn danh trả **401/403**; nếu truyền `AISTV_FIREBASE_SECRET` thì nhánh `aistv`
trả **200**. Exit code `1` = vẫn còn mở.

## 4. Lưu ý

- DB dùng chung với app khác (`servers`, `vms`, `rdp`, `bots`, `user_tokens`, `config`).
  Sau khi khóa gốc, app đó **mất truy cập** cho tới khi thêm auth hoặc chuyển sang DB riêng.
- Rotate ngay các token từng lộ trong DB: GitHub PAT, Telegram bot token, Tailscale key.
- URL cũ đã bị xoá khỏi toàn bộ git history (commit cũ vẫn có thể còn trên GitHub theo SHA;
  rules khóa mới là lớp bảo vệ thật, không phải ẩn URL).
- Dữ liệu cá nhân (`hist`, `mem`, `summary`, `rem`, `watch`) được mã hoá toàn bộ trước khi ghi
  lên cloud, khoá dẫn xuất từ bot token. Đổi bot token thì dữ liệu cũ không giải mã được nữa.
  Node thô kiểu cũ được tự mã hoá lại một lần khi bot khởi động (`AISTV_CLOUD_ENCRYPT_MIGRATE=0` để tắt).
- Không muốn dùng cloud nữa: đặt `AISTV_CLOUD=0` (mất đồng bộ trí nhớ giữa các máy).
