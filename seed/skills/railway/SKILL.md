---
name: railway
description: Triển khai, xem log, quản lý biến môi trường và dịch vụ trên Railway bằng Railway CLI (đã cài 5.71.0).
---
# railway
Dùng Railway CLI để deploy, xem log, đọc/ghi biến môi trường và quản lý project/service trên Railway.

## Khi nào dùng
- Người dùng muốn **deploy** code/thư mục hiện tại lên Railway.
- Hỏi **log**, trạng thái deploy, service có sống không, lỗi build/runtime.
- Xem/đặt/xoá **biến môi trường**, lấy domain, mở dashboard, chạy lệnh với env của Railway.

## Kiểm tra & đăng nhập
```powershell
railway --version
railway whoami            # Unauthorized = chưa đăng nhập
```
- Đăng nhập có người ngồi máy: `railway login` (tự mở trình duyệt, chờ tối đa ~10 phút).
- Máy không có trình duyệt: `railway login --browserless` → gửi link + mã cho người dùng nhập trên điện thoại.
- Token tự động: đặt env `RAILWAY_TOKEN` (project token, chỉ 1 project/env) hoặc `RAILWAY_API_TOKEN` (account/team). Nếu lưu file thì để trong `.secrets/railway_token` và **không bao giờ in ra**.
- Không tự đăng nhập bằng tài khoản của người khác; không dán token vào chat.

## Wrapper có sẵn (khuyến nghị)
`aistv_railway.py` gói CLI lại, luôn giới hạn log, che giá trị biến và báo lỗi tiếng Việt:
```powershell
RW="${AISTV_DIR:-../../AISTV}/aistv_railway.py"
python "$RW" check                  # version + đã đăng nhập chưa
python "$RW" projects --json
python "$RW" status --json
python "$RW" logs -n 100 --filter "@level:error"
python "$RW" deployments --limit 5
python "$RW" deploy . --wait 300 --json
python "$RW" vars                   # chỉ in tên biến, giá trị bị che
python "$RW" var-set KEY=VALUE      # mặc định không trigger deploy
python "$RW" domains
```
Máy Windows: `python "%AISTV_DIR%\aistv_railway.py" ...`

## Lệnh CLI gốc
```powershell
railway list                       # danh sách project
railway link -p <project> -e <env> -s <service>   # gắn project vào thư mục hiện tại
railway status --json              # project/service/env đang link
railway service                    # chọn/kiểm tra service
railway deployment list --json     # lịch sử deploy + trạng thái
railway logs -n 100                # 100 dòng gần nhất (KHÔNG stream)
railway logs -b -n 100             # log build
railway logs --http --status ">=400" -n 50
railway logs --since 1h -f "@level:error"
railway variable list --json       # CẨN THẬN: chứa giá trị thật
railway variable set KEY=VALUE --skip-deploys
railway domain                     # xem/tạo domain
railway metrics                    # CPU/RAM/HTTP
railway open                       # mở dashboard
railway run <lệnh>                 # chạy local với env của Railway
```

## Quy trình deploy
1. `railway status --json` (hoặc `railway link ...`) để chắc đúng project/env/service.
2. `railway up -d --json --message "..."` → trả về ngay, **không chờ healthy**.
3. Theo dõi: `railway deployment list --json` + `railway logs --latest -n 100`.
4. Báo người dùng: trạng thái (SUCCESS/FAILED/BUILDING), URL domain, lỗi đầu tiên nếu fail.

## An toàn
- **Phải hỏi người dùng trước** khi chạy: `railway down`, `railway delete`, `railway variable delete`, xoá service/environment, `railway redeploy` / `railway restart` trên production.
- `railway logs` không có `-n`/`--since` sẽ **stream mãi** → luôn giới hạn số dòng, hoặc chạy nền có timeout.
- `variable list --json/--kv` in **giá trị thật** → chỉ trích tên biến, không dán giá trị vào câu trả lời.
- Không đưa `.env`, token, file `.secrets/` lên repo hoặc vào log.

## Lỗi thường gặp
- `Unauthorized` → chưa đăng nhập hoặc token hết hạn: `railway whoami`, rồi login lại.
- `No linked project` → `railway link` hoặc thêm `-p/-e/-s` vào lệnh.
- Build fail do thiếu biến → `railway variable list --json` đối chiếu, bổ sung rồi redeploy.
- Upload quá lớn → kiểm tra `.gitignore`/`.railwayignore`, hoặc `railway up <path> --path-as-root`.
- Cần full tài liệu: `railway docs` hoặc https://docs.railway.com/llms.txt
