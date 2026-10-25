---
name: headroom
description: Nén context cho AI agent bằng Headroom (headroomlabs-ai/headroom) — cắt 20-95% token từ tool output, log, JSON, RAG trước khi đưa vào LLM. Chạy local, đảo ngược được (CCR), có MCP server, nhỏ hơn 1 ms/lượt nén. Dùng khi output công cụ quá lớn làm phình session.
---
# headroom

Headroom nén nội dung trước khi đưa vào LLM: SmartCrusher (JSON), CodeCompressor (code AST), Kompress-v2-base (văn).
Nguyên bản lưu cache local và có thể gọi `headroom_retrieve` lấy lại (CCR) — không mất dữ liệu, không gửi nội dung đi đâu để nén.

## Lệnh (CLI đã cài: `headroom-ai` 0.41.0 tại /usr/local/bin/headroom)

```bash
export HEADROOM_OFFLINE=1   # tắt beacon telemetry ẩn danh (mặc định đang bật)
headroom doctor             # kiểm tra cài đặt
headroom stats              # số tiết kiệm đã ghi nhận
headroom mcp serve          # MCP stdio: headroom_compress / headroom_retrieve / headroom_stats
headroom proxy --port 8787  # proxy OpenAI/Anthropic tương thích — CHỈ bật khi người dùng yêu cầu
```

Thư viện Python:

```python
from headroom import compress
result = compress(messages, model="gpt-4o")   # result.tokens_saved / result.compression_ratio
```

## Khi nào dùng
- Tool output / log / JSON / RAG lớn (hàng nghìn token) sẽ phải lưu vào memory hoặc nhắc lại nhiều lượt → nén trước rồi nêu lệnh `headroom_retrieve` để lấy nguyên bản khi cần.
- Đã đo 25/10/2026 (v0.41.0, offline): JSON lặp cấu trúc **9.262 → 3.940 token (−57,5%)**; log thuần và văn dày đặc nén gần 0 — đừng đoán, dùng `compress()` đo trước rồi báo con số thật.
- Block < `min_input_words` trả về nguyên văn byte-for-byte, như vậy là an toàn.

## Quy tắc
- KHÔNG tự `headroom wrap` / `unwrap` hay đổi config opencode: `wrap opencode` mặc định đẩy upstream về `api.openai.com` — với nhà cung cấp khác (DeepSeek…) thiếu `--openai-api-url` sẽ gửi key sai chỗ và 401. Muốn bật, hỏi người dùng trước.
- MCP server `headroom` đã đăng ký trong `opencode.json` (env `HEADROOM_OFFLINE=1`); cần /restart để nạp tool.
- Source clone ở `/root/headroom-src` (commit `3fef15d`, v0.41.0). Repo của headroomlabs-ai (Apache-2.0) — bên thứ ba, không phải công cụ của AI STV; trích nguồn khi báo cáo.
