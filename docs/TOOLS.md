# Bộ công cụ AI STV

Các module chạy **local**, không tốn quota Gemini. Agent gọi qua shell.

## 1. Trình duyệt — `aistv_browser.py` (Playwright)

```bash
python aistv_browser.py --install          # 1 lần: pip + Chromium
python aistv_browser.py --check
python aistv_browser.py --url https://studio.youtube.com --open   # login tay, lưu profile
python aistv_browser.py --url https://example.com --shot page.png
python aistv_browser.py steps.json         # kịch bản nhiều bước
```

Profile (cookie/login) lưu ở `$STV_HOME/browser/profile`.
Kịch bản: `goto`, `fill`, `click`, `press`, `wait`, `shot`, `text`, `html`.

## 2. Đọc tài liệu — `aistv_docs.py` (PDF/DOCX/OCR)

```bash
python aistv_docs.py --check
python aistv_docs.py hop-dong.pdf --out out.txt --json
python aistv_docs.py anh.jpg --lang vie+eng --json
```

Ưu tiên: `pdftotext` → PyMuPDF → pdfminer; DOCX: python-docx → XML;
ảnh: tesseract. Cài:

```bash
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-vie
pip install pymupdf python-docx
```

## 3. Tìm trí nhớ — `aistv_memory_index.py` (SQLite FTS5)

```bash
python aistv_memory_index.py index
python aistv_memory_index.py search "bạc liêu" -n 8
python aistv_memory_index.py stats
```

Index `MEMORY.md`, `memory/**/*.md`, `history/*.json`.
DB: `$STV_HOME/memory.db`. Chỉ đọc file đổi (theo mtime+size) nên chạy lại rất nhanh.

## 5. Giọng nói — `aistv_voice.py` (Piper + Whisper)

```bash
python aistv_voice.py check
python aistv_voice.py tts "Xin chào" -o out.ogg
python aistv_voice.py stt voice.ogg --json
```

Cài:

```bash
pip install piper-tts faster-whisper
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json
```

## 6. MCP — `aistv_mcp.py`

```bash
python aistv_mcp.py list
python aistv_mcp.py add notion --command "npx -y @notionhq/notion-mcp-server" --env NOTION_TOKEN=ntn_xxx
python aistv_mcp.py add drive --url https://mcp.example.com/sse --header "Authorization: Bearer xxx"
python aistv_mcp.py remove notion
```

Ghi vào `workspace/opencode.json` → `mcp.servers`, giữ nguyên cấu hình khác.
Restart bot để nạp.

## Skill đi kèm

| Skill | Nhận input |
|---|---|
| `lich-hoc` | **ảnh chụp TKB**, PDF/DOCX/Excel → OCR → `workspace/hoc-tap/tkb.json` |
| `dich-tai-lieu` | PDF/DOCX/ảnh → dịch giữ heading + bảng |

## Chưa làm (theo lựa chọn của bạn)

- **Cron bền** (#4): dùng `/remind` hiện có; lịch lặp lưu qua restart chưa có.
