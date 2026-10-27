---
name: windows-vm
description: Tạo hoặc dừng máy ảo Windows (GitHub Actions + Tailscale + RDP) cho người dùng, dùng token/key của admin và gửi thông tin đăng nhập qua Telegram DM.
---
# windows-vm

Tạo máy ảo Windows tạm thời trên GitHub Actions để chạy Integration Test, truy cập qua
Tailscale + Remote Desktop. Người dùng nhận IP, tài khoản, mật khẩu và Tailscale key bằng
**tin nhắn riêng** của bot — không hiện ở chat nhóm hay log workflow.

## Khi nào dùng
- Người dùng nói "tạo máy ảo Windows", "tạo VM để test", "mở máy Windows cho tôi"…
- Người dùng muốn **dừng** máy ảo đang chạy (đỡ tốn thời gian runner).
- Người dùng hỏi cách vào máy ảo (Tailscale + mstsc).

## Cách làm
1. Gọi tool `create_vm`. Mặc định **không truyền** `github_token` / `tailscale_authkey`:
   bot dùng tài khoản admin đã cấu hình (GitHub token của bot + Tailscale key đã lưu).
   Chỉ dùng tài khoản riêng khi người dùng đưa rõ.
2. Tham số:
   - `windows_version`: `windows-latest` (mặc định) · `windows-2022` · `windows-2025`
   - `timeout_minutes`: 60–360 (khách tối đa 180)
   - `action`: `create` (mặc định) hoặc `stop`
3. Dừng máy ảo: gọi `create_vm` với `action="stop"` (hoặc hướng dẫn bấm 🛑 Dừng máy ảo trong `/vm`).
4. Sau khi tạo: nói người dùng chờ 2–3 phút, rồi kiểm tra **tin nhắn riêng** của bot.
   Không dán lại thông tin đăng nhập, token hay key vào chat.

## Quy tắc an toàn
- Không in GitHub token, Tailscale key, mật khẩu, IP vào câu trả lời hay file.
- Không bịa thông tin đăng nhập — chỉ bot gửi DM mới có.
- DM phải tới **đúng người yêu cầu**: bot truyền chat id của người đó vào workflow.
- Chỉ tạo trong chat riêng; trong nhóm hướng dẫn người dùng nhắn riêng bot rồi gõ `/vm`.
- Khách phải **xác minh email .com** trước khi tạo (mã 6 số do bot gửi qua SMTP, lưu trên Firebase).
  Hạn mức khách: 1 máy cùng lúc · 3 lượt/ngày · tối đa 180 phút/lần.

## Vào máy sau khi nhận DM
1. Cài Tailscale: https://tailscale.com/download/windows
2. Mở PowerShell/CMD và chạy (key có trong DM):
   `tailscale up --authkey=<tskey-...> --accept-routes`
3. Mở Remote Desktop: `mstsc /v:<IP>` → đăng nhập bằng User/Password trong DM.
4. Dùng xong bấm 🛑 Dừng máy ảo (máy tự huỷ khi hết thời gian).

## Lỗi thường gặp
- "Thiếu PAT/Tailscale key": chủ bot chưa cấu hình — báo chủ bot nhập qua `/vm`.
- "PAT thiếu quyền": token cần scope `workflow` (classic) hoặc Actions: write (fine-grained).
- "Fork lệch bản gốc": repo fork cũ không đồng bộ được; báo người dùng xoá fork rồi thử lại.
- Không nhận được DM: kiểm tra người dùng đã bấm Start với bot (chat riêng) chưa.
