#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_planner.py — kế hoạch tự trị, checkpoint/hoàn tác và kiểm chứng.

Phần này là "bộ nhớ ngoài" cho vòng lặp dài của bot:

  • Plan     : chia yêu cầu lớn thành các bước, lưu xuống đĩa để sống sót khi
               bot khởi động lại; mỗi bước có trạng thái + số lần thử.
  • Checkpoint: chụp trạng thái repo (patch các file đã sửa + tar file mới)
               TRƯỚC khi agent làm việc, để hoàn tác được bằng một nút bấm.
  • Verify   : chạy scripts/verify.py để biết "đã xong" thật hay chỉ nói xong.

Không phụ thuộc thư viện ngoài, không cần git server; mọi hàm nhận `home` và
`repo` tường minh để test được với thư mục tạm.
"""
import html
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

PLAN_STEPS_MAX = 12
CHECKPOINT_KEEP = 20
STEP_ATTEMPTS_MAX = 2
STATUS_ICON = {
    "pending": "○", "running": "▶", "done": "✅", "failed": "✖", "skipped": "⏭",
}
PLAN_STATUS = {
    "draft": "nháp", "running": "đang chạy", "done": "xong",
    "failed": "lỗi", "cancelled": "đã huỷ",
}


# ────────────────────────────────────────────────────────────────────
# Tiện ích
# ────────────────────────────────────────────────────────────────────
def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def oneline(s, n: int = 200) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def _run(cmd, cwd=None, timeout=180, binary=False):
    """Chạy lệnh, trả (returncode, stdout). binary=True → bytes."""
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            timeout=timeout, **({} if binary else
                                {"text": True, "encoding": "utf-8", "errors": "replace"}))
        out = r.stdout if binary else (r.stdout or "") + (r.stderr or "")
        return r.returncode, out
    except FileNotFoundError as e:
        return 127, (b"" if binary else f"không tìm thấy lệnh: {e}")
    except subprocess.TimeoutExpired:
        return 124, (b"" if binary else f"hết thời gian sau {timeout}s")
    except Exception as e:  # noqa
        return 1, (b"" if binary else str(e))


def _git(repo, *args, timeout=180, binary=False):
    return _run(["git"] + list(args), cwd=repo, timeout=timeout, binary=binary)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    os.replace(str(tmp), str(path))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────
# Verify
# ────────────────────────────────────────────────────────────────────
def verify_repo(repo, fast: bool = True, timeout: int = 420) -> dict:
    """Chạy scripts/verify.py. Trả {ok, summary, checks, elapsed}."""
    repo = Path(repo)
    script = repo / "scripts" / "verify.py"
    if not script.is_file():
        return {"ok": True, "summary": "không có scripts/verify.py", "checks": []}
    cmd = [sys.executable or "python3", str(script), "--json"]
    if fast:
        cmd.append("--fast")
    rc, out = _run(cmd, cwd=repo, timeout=timeout)
    start = out.find("{")
    data = None
    if start >= 0:
        try:
            data = json.loads(out[start:])
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return {"ok": rc == 0, "summary": oneline(out[-900:] or f"exit {rc}", 900),
                "checks": []}
    checks = data.get("checks") or []
    failed = [c for c in checks if not c.get("ok")]
    if failed:
        summary = "\n".join(
            f"✖ {c.get('name')}: {oneline((c.get('detail') or '').strip(), 400)}"
            for c in failed)
    else:
        summary = " · ".join(f"✓ {c.get('name')}" for c in checks)
    return {"ok": bool(data.get("ok")), "summary": summary, "checks": checks,
            "elapsed": data.get("elapsed")}


def diff_stat(repo) -> dict:
    """Thống kê thay đổi chưa commit trong repo (dùng cho cổng review)."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        return {"ok": False, "text": "không phải repo git", "files": 0,
                "added": 0, "deleted": 0, "untracked": 0}
    rc, out = _git(repo, "diff", "--numstat", "HEAD", timeout=60)
    files = added = deleted = 0
    if rc == 0:
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            files += 1
            a, d = parts[0], parts[1]
            added += int(a) if a.isdigit() else 0
            deleted += int(d) if d.isdigit() else 0
    rc2, untracked = _git(repo, "ls-files", "--others", "--exclude-standard", timeout=60)
    new_files = len([x for x in (untracked or "").splitlines() if x.strip()]) if rc2 == 0 else 0
    parts = []
    if files:
        parts.append(f"{files} file sửa (+{added}/−{deleted})")
    if new_files:
        parts.append(f"{new_files} file mới")
    text = " · ".join(parts) or "không có thay đổi"
    return {"ok": True, "text": text, "files": files, "added": added,
            "deleted": deleted, "untracked": new_files}


# ────────────────────────────────────────────────────────────────────
# Checkpoint / hoàn tác
# ────────────────────────────────────────────────────────────────────
def _cp_dir(home, cp_id: str) -> Path:
    return Path(home) / "checkpoints" / re.sub(r"[^\w.-]+", "", cp_id or "")


def create_checkpoint(home, repo, label: str = "") -> tuple:
    """Chụp trạng thái repo trước khi agent sửa. Trả (meta, error).

    Repo sạch → chỉ ghi HEAD (không tốn dung lượng); hoàn tác khi đó là
    `git reset --hard HEAD` + xoá file mới. Repo đang dở → lưu patch + tar.
    """
    repo = Path(repo)
    if not (repo / ".git").exists():
        return None, "không tìm thấy repo git để tạo checkpoint"
    rc, head = _git(repo, "rev-parse", "HEAD", timeout=30)
    if rc != 0:
        return None, f"git rev-parse lỗi: {oneline(head, 300)}"
    head = (head or "").strip().splitlines()[0]
    cp_id = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    d = _cp_dir(home, cp_id)
    d.mkdir(parents=True, exist_ok=True)

    rc, status = _git(repo, "status", "--porcelain", timeout=60)
    dirty = rc == 0 and bool((status or "").strip())
    meta = {
        "id": cp_id, "at": time.time(),
        "label": oneline(label, 120), "repo": str(repo),
        "head": head, "dirty": dirty, "patch": False, "tar": False,
        "untracked": [], "stat": diff_stat(repo)["text"],
    }
    if dirty:
        rc, patch = _git(repo, "diff", "--binary", "--no-color", "HEAD",
                         timeout=120, binary=True)
        if rc == 0 and patch:
            (d / "work.patch").write_bytes(patch)
            meta["patch"] = True
        rc, raw = _git(repo, "ls-files", "--others", "--exclude-standard", "-z",
                       timeout=60, binary=True)
        if rc == 0 and raw:
            names = [p for p in raw.decode("utf-8", "replace").split("\0") if p]
            with tarfile.open(str(d / "untracked.tar.gz"), "w:gz") as tf:
                for name in names:
                    src = repo / name
                    if src.is_file() or src.is_symlink():
                        tf.add(str(src), arcname=name)
                        meta["untracked"].append(name)
            meta["tar"] = bool(meta["untracked"])
    _write_json(d / "meta.json", meta)
    _prune_checkpoints(home)
    return meta, ""


def load_checkpoint(home, cp_id: str):
    return _read_json(_cp_dir(home, cp_id) / "meta.json")


def list_checkpoints(home, limit: int = 10) -> list:
    root = Path(home) / "checkpoints"
    if not root.is_dir():
        return []
    items = []
    for p in root.glob("*/meta.json"):
        meta = _read_json(p)
        if isinstance(meta, dict):
            items.append(meta)
    items.sort(key=lambda m: m.get("at") or 0, reverse=True)
    return items[:limit]


def _prune_checkpoints(home) -> None:
    root = Path(home) / "checkpoints"
    if not root.is_dir():
        return
    items = list_checkpoints(home, limit=10_000)
    for meta in items[CHECKPOINT_KEEP:]:
        d = _cp_dir(home, str(meta.get("id") or ""))
        try:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()
        except OSError:
            pass


def restore_checkpoint(home, repo, cp_id: str) -> tuple:
    """Trả repo về đúng trạng thái lúc chụp. Trả (ok, detail).

    Từ chối nếu HEAD đã đổi (có commit mới) để không nuốt lịch sử.
    Chỉ xoá file untracked do agent tạo; file ignored (.env, .secrets) giữ nguyên.
    """
    repo = Path(repo)
    meta = load_checkpoint(home, cp_id)
    if not meta:
        return False, "Không tìm thấy checkpoint này."
    if not (repo / ".git").exists():
        return False, "Không tìm thấy repo git."
    rc, head = _git(repo, "rev-parse", "HEAD", timeout=30)
    cur = (head or "").strip().splitlines()[0] if rc == 0 else ""
    if cur != meta.get("head"):
        return False, ("Repo đã có commit mới sau checkpoint nên không tự hoàn tác. "
                       "Dùng git thủ công nếu thật sự cần.")
    rc, out = _git(repo, "reset", "--hard", "HEAD", timeout=120)
    if rc != 0:
        return False, f"git reset lỗi: {oneline(out, 400)}"

    baseline = set(meta.get("untracked") or [])
    removed = []
    rc, raw = _git(repo, "ls-files", "--others", "--exclude-standard", "-z",
                   timeout=60, binary=True)
    if rc == 0 and raw:
        for name in raw.decode("utf-8", "replace").split("\0"):
            if not name or name in baseline:
                continue
            f = repo / name
            try:
                if f.is_file() or f.is_symlink():
                    f.unlink()
                    removed.append(name)
            except OSError:
                pass

    d = _cp_dir(home, cp_id)
    restored_patch = False
    patch = d / "work.patch"
    if meta.get("patch") and patch.is_file() and patch.stat().st_size:
        rc, out = _git(repo, "apply", "--binary", str(patch), timeout=120)
        if rc != 0:
            return False, f"Đã reset nhưng không áp lại được patch: {oneline(out, 400)}"
        restored_patch = True

    restored_tar = 0
    tar = d / "untracked.tar.gz"
    if meta.get("tar") and tar.is_file():
        try:
            with tarfile.open(str(tar), "r:gz") as tf:
                members = [m for m in tf.getmembers()
                           if m.isfile() and not m.name.startswith(("/", ".."))]
                try:
                    tf.extractall(str(repo), members=members, filter="data")
                except TypeError:            # Python < 3.12 không có filter
                    tf.extractall(str(repo), members=members)
                restored_tar = len(members)
        except Exception as e:  # noqa
            return False, f"Đã reset nhưng không giải nén được file mới: {e}"

    bits = []
    if restored_patch:
        bits.append("đã khôi phục file đang sửa")
    if restored_tar:
        bits.append(f"đã khôi phục {restored_tar} file mới")
    if removed:
        bits.append(f"đã xoá {len(removed)} file agent tạo")
    if not bits:
        bits.append("repo đã sạch như lúc chụp")
    return True, "; ".join(bits) + "."


# ────────────────────────────────────────────────────────────────────
# Plan
# ────────────────────────────────────────────────────────────────────
def _plans_dir(home) -> Path:
    return Path(home) / "plans"


def new_plan(home, chat_id: int, title: str, request: str, steps: list) -> dict:
    plan_id = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
    now = time.time()
    plan = {
        "id": plan_id, "chat_id": int(chat_id or 0), "created": now, "updated": now,
        "title": oneline(title or "Kế hoạch", 140),
        "request": (request or "").strip()[:4000],
        "status": "draft", "checkpoint": "",
        "steps": [],
        "verify": {}, "diff": "", "report": "",
    }
    for i, step in enumerate(steps[:PLAN_STEPS_MAX], 1):
        if isinstance(step, str):
            step = {"title": step}
        plan["steps"].append({
            "n": i,
            "title": oneline(step.get("title") or f"Bước {i}", 160),
            "detail": (step.get("detail") or "").strip()[:1200],
            "verify": (step.get("verify") or "").strip()[:500],
            "status": "pending", "attempts": 0, "result": "",
            "last_verify": "", "started": 0, "finished": 0,
        })
    save_plan(home, plan)
    return plan


def save_plan(home, plan: dict) -> None:
    plan["updated"] = time.time()
    _write_json(_plans_dir(home) / f"{plan['id']}.json", plan)


def load_plan(home, plan_id: str):
    plan_id = re.sub(r"[^\w.-]+", "", plan_id or "")
    return _read_json(_plans_dir(home) / f"{plan_id}.json")


def list_plans(home, limit: int = 10) -> list:
    root = _plans_dir(home)
    if not root.is_dir():
        return []
    items = []
    for p in root.glob("*.json"):
        plan = _read_json(p)
        if isinstance(plan, dict):
            items.append(plan)
    items.sort(key=lambda p: p.get("created") or 0, reverse=True)
    return items[:limit]


def latest_plan(home, chat_id=None):
    for plan in list_plans(home, limit=50):
        if chat_id is None or int(plan.get("chat_id") or 0) == int(chat_id):
            return plan
    return None


def set_step(plan, n: int, **fields) -> dict:
    for step in plan.get("steps") or []:
        if int(step.get("n") or 0) == int(n):
            step.update(fields)
            return step
    return {}


def next_pending(plan):
    for step in plan.get("steps") or []:
        if step.get("status") in ("pending", "running"):
            return step
    return None


def progress(plan) -> tuple:
    steps = plan.get("steps") or []
    done = len([s for s in steps if s.get("status") == "done"])
    return done, len(steps)


def parse_plan(text: str) -> tuple:
    """Bóc JSON kế hoạch khỏi câu trả lời model. Trả (plan_dict, error)."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None, "Model không trả về JSON kế hoạch."
    try:
        obj = json.loads(raw[start:end + 1])
    except ValueError as e:
        return None, f"JSON lỗi: {e}"
    if not isinstance(obj, dict):
        return None, "JSON phải là đối tượng."
    steps = obj.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, "JSON thiếu danh sách bước (steps)."
    clean = []
    for item in steps:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        title = oneline(item.get("title") or item.get("name") or "", 160)
        if not title:
            continue
        clean.append({
            "title": title,
            "detail": (item.get("detail") or item.get("description") or "").strip(),
            "verify": (item.get("verify") or item.get("done") or "").strip(),
        })
    if not clean:
        return None, "Các bước đều thiếu tiêu đề."
    title = oneline(obj.get("title") or "", 140)
    return {"title": title, "steps": clean[:PLAN_STEPS_MAX]}, ""


def render_plan(plan: dict, show_request: bool = True) -> str:
    steps = plan.get("steps") or []
    done, total = progress(plan)
    status = PLAN_STATUS.get(plan.get("status") or "draft", plan.get("status") or "")
    head = (f"🧭 <b>{esc(plan.get('title') or 'Kế hoạch')}</b>\n"
            f"<i>{total} bước · {done}/{total} xong · {esc(status)}</i>")
    lines = [head]
    if show_request and plan.get("request"):
        lines.append(f"\n📝 <b>Yêu cầu:</b> {esc(oneline(plan['request'], 500))}")
    lines.append("")
    for step in steps:
        icon = STATUS_ICON.get(step.get("status") or "pending", "○")
        line = f"{icon} <b>{step.get('n')}.</b> {esc(step.get('title') or '')}"
        if step.get("attempts"):
            line += f" <i>(thử {step.get('attempts')})</i>"
        lines.append(line)
        if step.get("status") == "failed" and step.get("last_verify"):
            lines.append(f"　　<code>{esc(oneline(step['last_verify'], 300))}</code>")
    if plan.get("work_branch"):
        lines.append(f"\n🌿 Nhánh công việc: <code>{esc(plan['work_branch'])}</code>")
        if plan.get("work_merged"):
            lines.append("<i>Đã gộp vào nhánh chính (chưa commit) — bấm ⬆️ Push.</i>")
        else:
            lines.append("<i>Code chính không đổi · máy khác gõ “tiếp tục công việc”.</i>")
    return "\n".join(lines)


def render_report(plan: dict) -> str:
    done, total = progress(plan)
    failed = [s for s in plan.get("steps") or [] if s.get("status") == "failed"]
    ok = plan.get("status") == "done"
    head = (f"{'✅' if ok else '❌'} <b>{esc(plan.get('title') or 'Kế hoạch')}</b>\n"
            f"<b>{done}/{total}</b> bước xong"
            + (f" · lỗi ở bước {', '.join(str(s['n']) for s in failed)}" if failed else ""))
    lines = [head]
    if plan.get("work_dropped"):
        lines.append("\n🗑 Đã xoá nhánh công việc. Nhánh chính không đổi.")
    elif plan.get("work_branch"):
        back = plan.get("work_back")
        pushed = plan.get("work_pushed")
        lines.append("\n🌿 <b>Nhánh công việc:</b> "
                     f"<code>{esc(plan['work_branch'])}</code>")
        bits = []
        if plan.get("work_commits"):
            bits.append(f"{plan['work_commits']} commit")
        bits.append("đã đẩy GitHub" if pushed else "chưa đẩy được GitHub")
        if back:
            bits.append(f"đã trả về {plan.get('work_base') or 'nhánh chính'}")
        lines.append("• " + esc(" · ".join(bits)))
        if plan.get("work_error"):
            lines.append("• ⚠️ " + esc(oneline(plan["work_error"], 300)))
        if plan.get("work_merged"):
            lines.append("• 🔀 Đã gộp vào nhánh chính (chưa commit) — bấm ⬆️ Push.")
        else:
            lines.append("• Code chính không bị sửa.")
            lines.append("• Máy khác: gõ “tiếp tục công việc” hoặc <code>/tieptuc</code>.")
    elif plan.get("work_error"):
        lines.append("\n⚠️ Không tạo được nhánh công việc: "
                     + esc(oneline(plan["work_error"], 400)))
    ver = plan.get("verify") or {}
    if ver:
        lines.append("\n🧪 <b>Kiểm chứng:</b> "
                     + ("PASS" if ver.get("ok") else "FAIL")
                     + f"\n<code>{esc(oneline(ver.get('summary') or '', 700))}</code>")
    if plan.get("diff"):
        lines.append(f"\n📦 <b>Thay đổi:</b> {esc(plan['diff'])}")
    lines.append("\n<b>Chi tiết</b>")
    for step in plan.get("steps") or []:
        icon = STATUS_ICON.get(step.get("status") or "pending", "○")
        lines.append(f"{icon} {step.get('n')}. {esc(oneline(step.get('title') or '', 160))}")
        if step.get("result"):
            lines.append(f"　　<i>{esc(oneline(step['result'], 240))}</i>")
    if plan.get("report"):
        lines.append("\n" + esc(oneline(plan["report"], 900)))
    if plan.get("checkpoint"):
        lines.append("\n↩️ Có checkpoint để hoàn tác toàn bộ thay đổi của kế hoạch này.")
    return "\n".join(lines)


def plan_prompt(request: str, repo: str = "", workspace: str = "",
                context: str = "") -> str:
    repo = repo or "(không rõ)"
    workspace = workspace or "(không rõ)"
    extra = f"\n## BỐI CẢNH THÊM\n{context.strip()}\n" if context and context.strip() else ""
    return (
        "## NHIỆM VỤ: LẬP KẾ HOẠCH (KHÔNG THỰC THI)\n"
        "Bạn là kiến trúc sư của AI STV. Người dùng đưa một yêu cầu lớn; nhiệm vụ "
        "của bạn ở lượt này CHỈ là chia nó thành các bước nhỏ để một agent khác "
        "thực thi lần lượt. Tuyệt đối không sửa file, không chạy lệnh thay đổi.\n\n"
        f"## MÔI TRƯỜNG\n- Repo chính: `{repo}`\n- Workspace: `{workspace}`\n"
        f"{extra}\n"
        "## YÊU CẦU CỦA NGƯỜI DÙNG\n" + (request or "").strip()[:8000] + "\n\n"
        "## QUY TẮC CHIA BƯỚC\n"
        "- 2–8 bước, mỗi bước một mục tiêu kiểm chứng được (không gộp 3 việc vào 1 bước).\n"
        "- Bước 1 nên là khảo sát/đọc code liên quan; bước cuối là kiểm chứng/tài liệu.\n"
        "- Nêu file/hàm cụ thể khi biết; dùng CODEMAP (`docs/CODEMAP.md`) nếu cần.\n"
        "- Không đưa bước push/deploy hay xoá dữ liệu; người dùng sẽ duyệt riêng.\n"
        "- Không bao giờ đưa token, mật khẩu hay nội dung `.secrets` vào kế hoạch.\n\n"
        "## ĐỊNH DẠNG TRẢ VỀ (bắt buộc)\n"
        "Chỉ trả về MỘT đối tượng JSON, không markdown, không lời dẫn:\n"
        '{"title": "tên kế hoạch ngắn", "steps": ['
        '{"title": "việc cần làm", "detail": "cách làm, file/hàm liên quan", '
        '"verify": "cách biết bước này xong"}]}\n'
    )


def step_prompt(plan: dict, step: dict, repo: str = "", workspace: str = "",
                verify_hint: str = "") -> str:
    done, total = progress(plan)
    remaining = [f"{s['n']}. {s['title']}" for s in plan.get("steps") or []
                 if s.get("status") == "pending" and s["n"] != step.get("n")]
    hint = ""
    if verify_hint:
        hint = ("\n## LẦN TRƯỚC THẤT BẠI — SỬA NGUYÊN NHÂN\n"
                f"```text\n{verify_hint[:1200]}\n```\n")
    rest = ("\n## CÁC BƯỚC CÒN LẠI (chỉ để biết, KHÔNG làm luôn)\n"
            + "\n".join(remaining)) if remaining else ""
    return (
        f"## THỰC THI KẾ HOẠCH: {plan.get('title') or ''}\n"
        f"Tiến độ: {done}/{total} bước.\n\n"
        f"## BƯỚC {step.get('n')}/{total}: {step.get('title')}\n"
        f"{step.get('detail') or '(không có mô tả thêm)'}\n"
        f"{hint}{rest}\n\n"
        "## RÀNG BUỘC\n"
        f"- Repo chính: `{repo or '(không rõ)'}` · Workspace: `{workspace or '(không rõ)'}`.\n"
        "- CHỈ làm đúng bước này. Không làm trước bước sau, không đổi phạm vi.\n"
        "- Sửa code trong repo chính thì đọc `docs/CODEMAP.md` để định vị, chỉ đọc "
        "60–150 dòng quanh symbol cần sửa.\n"
        "- Sửa xong chạy `python scripts/verify.py --fast` (trong repo) và sửa tới khi PASS.\n"
        "- KHÔNG commit, KHÔNG push, KHÔNG xoá dữ liệu ngoài phạm vi bước.\n"
        "- Không in/ghi token, API key, mật khẩu hay nội dung `.secrets`.\n"
        "- Nếu bước đã xong từ trước: không sửa gì, nói ngắn gọn là đã có.\n\n"
        "## ĐỊNH NGHĨA HOÀN THÀNH\n"
        f"{step.get('verify') or 'Bước này chạy được và kiểm chứng không lỗi.'}\n\n"
        "Kết thúc bằng 2–4 dòng: đã làm gì, file nào đổi, còn rủi ro gì."
    )
