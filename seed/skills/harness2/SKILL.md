---
name: harness2
description: Audit và tối ưu chính harness của AI STV bằng Harness² (google-research/harness2) — đóng gói SOUL/AGENTS/MEMORY/skills thành harness tree, validate bằng luật của Google, so sánh bản đề xuất.
---
# harness2
Audit và tối ưu "harness" của chính AI STV (prompt, guardrails, memory, tool guidance, skills) bằng Harness² của Google Research — tối ưu lớp bao quanh model, **không sửa trọng số model**.

## Khi nào dùng
- Người dùng hỏi về Harness², "agent tự nâng cấp", "tối ưu harness/prompt/skills".
- Cần kiểm tra: skill nào không bao giờ được nạp, skill thiếu `name:`/`description:`, always-on vượt cap 24k ký tự, script được nhắc nhưng thiếu file.
- Có bản harness mới do Harness² đề xuất và cần xem khác gì bản đang chạy.
- Muốn thử nghiệm pipeline recursion của Google mà không cần credential.

## Công cụ
`python3 /root/AISTV/aistv_harness2.py <lệnh>` (Harness² ở `/root/harness2-src`, venv Python 3.12, commit 1cfe254).

```bash
python3 aistv_harness2.py status          # cài đặt + credential còn thiếu
python3 aistv_harness2.py export          # SOUL+AGENTS+MEMORY+skills -> /root/AISTV/harness/tree
python3 aistv_harness2.py check           # validate tree bằng luật surface opencode
python3 aistv_harness2.py diff --before A --after B
python3 aistv_harness2.py demo --k 2      # recursion offline, không cần credential
python3 aistv_harness2.py run --bench jb ...   # benchmark thật, CẦN Vertex AI
```

## Kết quả kiểm chứng (25/10/2026)
- Tree hợp lệ: 38 skills, 58 file, always-on 23.664/24.000 ký tự.
- `MEMORY.md` bị cắt ~68 dòng cũ trong **bản export** (file thật không đổi) để vừa cap always-on.
- 117 file phụ trong `skills/` (references, templates) nằm ngoài surface nên không vào tree.
- `demo --k 2`: 2 task hoàn tất, 0 failed (offline, không cần credential).

## Quy tắc
- `export`/`check`/`demo` chỉ đọc và ghi vào `/root/AISTV/harness/`, **không sửa** SOUL.md, AGENTS.md, MEMORY.md hay `skills/`.
- Không tự áp bản harness đề xuất vào agent đang chạy: đưa `diff` cho người dùng xem trước.
- `run` (benchmark thật: JobBench/LAB/WorkBuddy) cần `GOOGLE_CLOUD_PROJECT` + model + `gcloud auth application-default login`; thiếu thì nói rõ, không giả vờ đã chạy.
- Harness² là repo của Google (Apache-2.0), không phải công cụ của AI STV — trích nguồn khi báo cáo.
