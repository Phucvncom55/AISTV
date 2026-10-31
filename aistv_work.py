#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_work.py — nhánh công việc dài, sống qua nhiều máy.

Ý tưởng: việc lớn chạy bằng /plan không sửa thẳng nhánh chính. Mỗi kế hoạch
được làm trên một nhánh riêng `aistv/work-<id>`; sau MỖI bước bot ghi trạng
thái kế hoạch vào `.aistv/work/<id>.json`, commit rồi đẩy nhánh lên GitHub.
Máy khác chỉ cần fetch nhánh đó là biết đang ở bước nào và làm tiếp.

Nguyên tắc an toàn:
  • Không bao giờ commit/push vào nhánh chính.
  • Chỉ bắt đầu nhánh mới khi cây làm việc sạch (không nuốt thay đổi chưa duyệt).
  • Push lỗi không làm hỏng kế hoạch — state vẫn còn trên máy.
  • State không chứa token; nội dung yêu cầu được rút gọn và che bí mật.

Không phụ thuộc thư viện ngoài; mọi hàm nhận `repo`/`plan` tường minh để test
với thư mục tạm.
"""
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

BRANCH_PREFIX = "aistv/work-"
STATE_DIR = ".aistv/work"
DEFAULT_REMOTE = "origin"
PUSH_TIMEOUT = 300

_SECRET_PATTERNS = [
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}\b"),
    re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAQ\.[0-9A-Za-z_-]{15,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\btskey-[0-9A-Za-z_-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]


# ────────────────────────────────────────────────────────────────────
# Tiện ích
# ────────────────────────────────────────────────────────────────────
def oneline(s, n: int = 200) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def scrub(text, n: int = 400) -> str:
    """Rút gọn + che token để state có thể nằm trong repo công khai."""
    s = str(text or "")
    for pat in _SECRET_PATTERNS:
        s = pat.sub("***", s)
    return oneline(s, n)


def _run(cmd, cwd=None, timeout=180):
    """Chạy lệnh, trả (rc, stdout, stderr). Không bao giờ hỏi mật khẩu."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=env)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError as e:
        return 127, "", f"không tìm thấy lệnh: {e}"
    except subprocess.TimeoutExpired:
        return 124, "", f"hết thời gian sau {timeout}s"
    except Exception as e:  # noqa
        return 1, "", str(e)


def _git(repo, *args, timeout=180):
    """Trả (rc, stdout + stderr) để báo lỗi cho người dùng."""
    rc, out, err = _run(["git"] + list(args), repo, timeout)
    return rc, (out + err).strip()


def _git_out(repo, *args, timeout=180):
    """Trả (rc, stdout) — dùng khi cần đọc dữ liệu máy (JSON, danh sách ref)."""
    return _run(["git"] + list(args), repo, timeout)[:2]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, "utf-8")
    os.replace(str(tmp), str(path))


def branch_for(plan_id) -> str:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "-", str(plan_id or "")).strip("-._")
    if not safe:
        safe = time.strftime("%Y%m%d-%H%M%S")
    return BRANCH_PREFIX + safe


def state_rel(plan_id) -> str:
    safe = re.sub(r"[^\w.-]+", "-", str(plan_id or "")).strip("-._") or "plan"
    return f"{STATE_DIR}/{safe}.json"


def _plan_id_of_branch(branch: str) -> str:
    branch = branch or ""
    return branch[len(BRANCH_PREFIX):] if branch.startswith(BRANCH_PREFIX) else branch


def is_git_repo(repo) -> bool:
    return bool(repo) and (Path(repo) / ".git").exists()


def current_branch(repo) -> str:
    rc, out = _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD", timeout=30)
    name = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
    return "" if name == "HEAD" else name


def head_sha(repo) -> str:
    rc, out = _git_out(repo, "rev-parse", "HEAD", timeout=30)
    return out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""


def is_clean(repo) -> bool:
    rc, out = _git_out(repo, "status", "--porcelain", timeout=60)
    return rc == 0 and not out.strip()


def has_remote(repo, remote: str = DEFAULT_REMOTE) -> bool:
    rc, _ = _git_out(repo, "remote", "get-url", remote, timeout=30)
    return rc == 0


def _local_branch_exists(repo, branch: str) -> bool:
    rc, _ = _git_out(repo, "show-ref", "--verify", "--quiet",
                     f"refs/heads/{branch}", timeout=30)
    return rc == 0


def _remote_branch_exists(repo, branch: str, remote: str = DEFAULT_REMOTE) -> bool:
    rc, _ = _git_out(repo, "show-ref", "--verify", "--quiet",
                     f"refs/remotes/{remote}/{branch}", timeout=30)
    return rc == 0


def _default_branch(repo) -> str:
    rc, out = _git_out(repo, "symbolic-ref", "--short",
                       "refs/remotes/origin/HEAD", timeout=30)
    name = (out or "").strip().splitlines()[-1] if rc == 0 and out.strip() else ""
    if name.startswith(f"{DEFAULT_REMOTE}/"):
        name = name[len(DEFAULT_REMOTE) + 1:]
    if name and _local_branch_exists(repo, name):
        return name
    for cand in ("main", "master"):
        if _local_branch_exists(repo, cand):
            return cand
    return current_branch(repo) or "main"


# ────────────────────────────────────────────────────────────────────
# State
# ────────────────────────────────────────────────────────────────────
def build_state(plan: dict) -> dict:
    """Bản ghi gọn, an toàn để commit vào repo (kể cả repo công khai)."""
    steps = []
    for s in plan.get("steps") or []:
        steps.append({
            "n": int(s.get("n") or 0),
            "title": scrub(s.get("title"), 160),
            "detail": scrub(s.get("detail"), 700),
            "verify": scrub(s.get("verify"), 300),
            "status": s.get("status") or "pending",
            "attempts": int(s.get("attempts") or 0),
            "result": scrub(s.get("result"), 400),
            "last_verify": scrub(s.get("last_verify"), 400),
            "finished": s.get("finished") or 0,
        })
    return {
        "v": 1,
        "id": str(plan.get("id") or ""),
        "title": scrub(plan.get("title") or "Kế hoạch", 140),
        "request": scrub(plan.get("request"), 400),
        "status": plan.get("status") or "draft",
        "created": plan.get("created") or time.time(),
        "updated": time.time(),
        "work_branch": plan.get("work_branch") or "",
        "work_base": plan.get("work_base") or "",
        "work_base_sha": plan.get("work_base_sha") or "",
        "machine": socket.gethostname(),
        "steps": steps,
    }


def write_state(repo, plan: dict) -> str:
    """Ghi state vào cây làm việc; trả đường dẫn tương đối."""
    rel = state_rel(plan.get("id"))
    _write_text(Path(repo) / rel, json.dumps(build_state(plan), ensure_ascii=False,
                                             indent=1))
    return rel


def read_state(repo, ref: str, plan_id: str):
    """Đọc state từ một ref (branch hoặc origin/branch). Trả dict hoặc None."""
    rel = state_rel(plan_id)
    rc, out = _git_out(repo, "show", f"{ref}:{rel}", timeout=60)
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ────────────────────────────────────────────────────────────────────
# Bắt đầu / kết thúc nhánh
# ────────────────────────────────────────────────────────────────────
def prepare(repo, plan: dict, remote: str = DEFAULT_REMOTE) -> dict:
    """Đưa repo sang nhánh công việc. Trả {ok, branch, base, resumed, error}.

    Chỉ tạo nhánh mới khi cây làm việc sạch — tránh commit/push thay đổi mà
    người dùng chưa duyệt.
    """
    repo = Path(repo)
    if not is_git_repo(repo):
        return {"ok": False, "error": "không phải repo git"}
    branch = plan.get("work_branch") or branch_for(plan.get("id"))
    base = plan.get("work_base") or _default_branch(repo)
    base_sha = plan.get("work_base_sha") or ""
    cur = current_branch(repo)

    exists = _local_branch_exists(repo, branch) or _remote_branch_exists(repo, branch, remote)
    if exists:
        if cur != branch:
            if not is_clean(repo):
                return {"ok": False, "branch": branch, "base": base,
                        "error": "repo còn thay đổi chưa commit nên chưa chuyển được "
                                 "về nhánh công việc."}
            if _local_branch_exists(repo, branch):
                rc, out = _git(repo, "checkout", branch, timeout=120)
            else:
                rc, out = _git(repo, "checkout", "-b", branch,
                               f"{remote}/{branch}", timeout=120)
            if rc != 0:
                return {"ok": False, "branch": branch, "base": base,
                        "error": f"không chuyển được nhánh: {oneline(out, 300)}"}
        return {"ok": True, "branch": branch, "base": base,
                "base_sha": base_sha or head_sha(repo), "resumed": True, "error": ""}

    if not is_clean(repo):
        return {"ok": False, "branch": branch, "base": base,
                "error": "repo đang có thay đổi chưa push — chưa tạo nhánh công việc "
                         "(đẩy hoặc hoàn tác thay đổi cũ trước)."}
    if cur != base:
        rc, out = _git(repo, "checkout", base, timeout=120)
        if rc != 0:
            return {"ok": False, "branch": branch, "base": base,
                    "error": f"không về được nhánh {base}: {oneline(out, 300)}"}
    base_sha = head_sha(repo)
    rc, out = _git(repo, "checkout", "-b", branch, timeout=120)
    if rc != 0:
        # Có thể nhánh vừa được tạo ở tiến trình khác — thử checkout thường.
        rc, out = _git(repo, "checkout", branch, timeout=120)
    if rc != 0:
        return {"ok": False, "branch": branch, "base": base,
                "error": f"không tạo được nhánh: {oneline(out, 300)}"}
    return {"ok": True, "branch": branch, "base": base, "base_sha": base_sha,
            "resumed": False, "error": ""}


def _commit_message(plan: dict, step=None, note: str = "") -> tuple:
    total = len(plan.get("steps") or [])
    if step:
        status = step.get("status") or "running"
        first = (f"aistv: bước {step.get('n')}/{total} — "
                 f"{scrub(step.get('title') or '', 80)}")
        detail = f"Trạng thái bước: {status}"
    else:
        first = f"aistv: {scrub(note or 'cập nhật kế hoạch', 80)}"
        detail = f"Trạng thái: {plan.get('status') or 'running'}"
    body = (f"Kế hoạch: {scrub(plan.get('title') or '', 120)} "
            f"({plan.get('id') or '?'})\n"
            f"{detail}\n"
            f"Máy: {socket.gethostname()}")
    return first, body


def commit_step(repo, plan: dict, step=None, note: str = "", push: bool = True,
                remote: str = DEFAULT_REMOTE) -> dict:
    """Ghi state + commit mọi thay đổi trên nhánh công việc rồi push.

    Trả {ok, sha, pushed, error, branch}. Push lỗi không phải lỗi commit.
    """
    repo = Path(repo)
    branch = plan.get("work_branch") or ""
    if not branch:
        return {"ok": False, "error": "chưa có nhánh công việc", "pushed": False}
    cur = current_branch(repo)
    if cur != branch:
        return {"ok": False, "pushed": False,
                "error": f"đang ở nhánh {cur or '?'}, không phải {branch}"}

    rel = write_state(repo, plan)
    _git(repo, "add", "-A", timeout=180)
    _git(repo, "add", "-f", rel, timeout=60)
    rc, out = _git(repo, "diff", "--cached", "--quiet", timeout=60)
    sha = ""
    if rc not in (0, 1):
        return {"ok": False, "pushed": False,
                "error": f"git add lỗi: {oneline(out, 300)}"}
    if rc == 1:                                   # có thay đổi để commit
        first, body = _commit_message(plan, step, note)
        rc, out = _git(repo, "-c", "user.name=AI STV",
                       "-c", "user.email=aistv@localhost",
                       "commit", "-m", first, "-m", body, timeout=180)
        if rc != 0:
            return {"ok": False, "pushed": False,
                    "error": f"commit lỗi: {oneline(out, 400)}"}
        sha = head_sha(repo)

    pushed, err = False, ""
    if push and has_remote(repo, remote):
        rc, out = _git(repo, "push", "-u", remote, branch, timeout=PUSH_TIMEOUT)
        pushed = rc == 0
        if not pushed:
            err = oneline(out, 400)
    elif push:
        err = "repo chưa có remote GitHub để đẩy nhánh"
    return {"ok": True, "sha": sha, "pushed": pushed, "error": err,
            "branch": branch}


def push_branch(repo, plan: dict, remote: str = DEFAULT_REMOTE) -> dict:
    branch = plan.get("work_branch") or ""
    if not branch:
        return {"ok": False, "error": "chưa có nhánh công việc"}
    if not has_remote(repo, remote):
        return {"ok": False, "error": "repo chưa có remote để push"}
    rc, out = _git(repo, "push", "-u", remote, branch, timeout=PUSH_TIMEOUT)
    return {"ok": rc == 0, "error": "" if rc == 0 else oneline(out, 500)}


def return_to_base(repo, base: str) -> tuple:
    """Trả repo về nhánh chính. Trả (ok, detail)."""
    if not base:
        return True, ""
    if current_branch(repo) == base:
        return True, ""
    if not is_clean(repo):
        return False, "repo còn thay đổi chưa commit nên chưa trả về nhánh chính."
    rc, out = _git(repo, "checkout", base, timeout=120)
    if rc != 0:
        return False, f"không trả được về {base}: {oneline(out, 300)}"
    return True, f"đã trả repo về nhánh {base}"


# ────────────────────────────────────────────────────────────────────
# Thống kê / gộp / xoá
# ────────────────────────────────────────────────────────────────────
def diff_from_base(repo, plan: dict) -> str:
    base = plan.get("work_base_sha") or plan.get("work_base") or "HEAD"
    rc, out = _git_out(repo, "diff", "--numstat", f"{base}..HEAD", "--", ".",
                       ":(exclude).aistv/**", timeout=120)
    if rc != 0:
        return ""
    files = added = deleted = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        added += int(parts[0]) if parts[0].isdigit() else 0
        deleted += int(parts[1]) if parts[1].isdigit() else 0
    if not files:
        return "không có thay đổi"
    return f"{files} file sửa (+{added}/−{deleted})"


def commit_count(repo, plan: dict) -> int:
    base = plan.get("work_base_sha") or plan.get("work_base") or "HEAD"
    rc, out = _git_out(repo, "rev-list", "--count", f"{base}..HEAD", timeout=60)
    try:
        return int(out.strip()) if rc == 0 else 0
    except ValueError:
        return 0


def merge_into_base(repo, plan: dict) -> tuple:
    """Gộp nhánh công việc vào nhánh chính bằng squash, để nguyên chưa commit.

    Nhờ vậy cổng duyệt ⬆️ Push / ↩️ Hoàn tác hiện có vẫn dùng được.
    """
    repo = Path(repo)
    branch = plan.get("work_branch") or ""
    base = plan.get("work_base") or _default_branch(repo)
    if not branch or not _local_branch_exists(repo, branch):
        return False, "Không tìm thấy nhánh công việc trên máy này."
    if not is_clean(repo):
        return False, "Repo còn thay đổi chưa commit — hãy Push hoặc Hoàn tác trước."
    if current_branch(repo) != base:
        rc, out = _git(repo, "checkout", base, timeout=120)
        if rc != 0:
            return False, f"Không chuyển được về {base}: {oneline(out, 300)}"
    rc, out = _git(repo, "merge", "--squash", branch, timeout=180)
    if rc != 0:
        _git(repo, "reset", "--merge", timeout=60)
        return False, f"Gộp lỗi (xung đột?): {oneline(out, 500)}"
    # State chỉ để máy khác làm tiếp — không đưa file .aistv vào nhánh chính.
    rel = state_rel(plan.get("id"))
    _git(repo, "rm", "-r", "--cached", "--ignore-unmatch", rel, timeout=60)
    try:
        (repo / rel).unlink()
    except OSError:
        pass
    for d in (repo / STATE_DIR / "work", repo / STATE_DIR):
        try:
            d.rmdir()
        except OSError:
            pass
    n = commit_count(repo, plan)
    return True, f"Đã gộp {n} commit từ {branch} vào {base} (chưa commit)."


def drop_branch(repo, plan: dict, remote: str = DEFAULT_REMOTE,
                delete_remote: bool = True) -> tuple:
    repo = Path(repo)
    branch = plan.get("work_branch") or ""
    base = plan.get("work_base") or _default_branch(repo)
    if not branch:
        return False, "Không có nhánh công việc."
    if not is_clean(repo):
        return False, "Repo còn thay đổi chưa commit — hãy Push hoặc Hoàn tác trước."
    if current_branch(repo) == branch:
        rc, out = _git(repo, "checkout", base, timeout=120)
        if rc != 0:
            return False, f"Không về được {base}: {oneline(out, 300)}"
    detail = []
    if _local_branch_exists(repo, branch):
        rc, out = _git(repo, "branch", "-D", branch, timeout=60)
        if rc != 0:
            return False, f"Không xoá được nhánh: {oneline(out, 300)}"
        detail.append("đã xoá nhánh trên máy")
    if delete_remote and has_remote(repo, remote):
        rc, out = _git(repo, "push", remote, "--delete", branch, timeout=PUSH_TIMEOUT)
        if rc == 0:
            detail.append("đã xoá nhánh trên GitHub")
        elif "remote ref does not exist" not in out.lower():
            detail.append("chưa xoá được nhánh trên GitHub")
    return True, "; ".join(detail) or "đã xoá nhánh."


# ────────────────────────────────────────────────────────────────────
# Tìm / khôi phục việc đang dở
# ────────────────────────────────────────────────────────────────────
def _refs(repo, remote: str = DEFAULT_REMOTE) -> list:
    rc, out = _git_out(repo, "for-each-ref", "--format=%(refname:short)",
                       f"refs/heads/{BRANCH_PREFIX}*",
                       f"refs/remotes/{remote}/{BRANCH_PREFIX}*", timeout=60)
    if rc != 0:
        return []
    return [x.strip() for x in out.splitlines() if x.strip()]


def fetch_tasks(repo, remote: str = DEFAULT_REMOTE, fetch: bool = True) -> list:
    """Liệt kê các nhánh công việc (local + remote), mới nhất trước."""
    repo = Path(repo)
    if not is_git_repo(repo):
        return []
    if fetch and has_remote(repo, remote):
        _git(repo, "fetch", remote,
             f"+refs/heads/{BRANCH_PREFIX}*:refs/remotes/{remote}/{BRANCH_PREFIX}*",
             "--prune", timeout=180)

    items, seen = [], {}
    for name in _refs(repo, remote):
        is_remote = name.startswith(f"{remote}/")
        branch = name[len(remote) + 1:] if is_remote else name
        ref = name if is_remote else branch
        pid = _plan_id_of_branch(branch)
        data = read_state(repo, ref, pid) or {}
        updated = data.get("updated") or 0
        task = {
            "id": data.get("id") or pid,
            "branch": branch,
            "ref": ref,
            "base": data.get("work_base") or "",
            "title": data.get("title") or pid,
            "status": data.get("status") or "unknown",
            "updated": updated,
            "machine": data.get("machine") or "",
            "steps": data.get("steps") or [],
            "done": len([s for s in data.get("steps") or []
                         if s.get("status") == "done"]),
            "total": len(data.get("steps") or []),
            "remote": remote,
            "source": "remote" if is_remote else "local",
            "state": data,
        }
        prev = seen.get(branch)
        if prev is None or updated >= (prev.get("updated") or 0):
            seen[branch] = task
    items = list(seen.values())
    items.sort(key=lambda t: t.get("updated") or 0, reverse=True)
    return items


def unfinished(tasks: list) -> list:
    return [t for t in tasks if (t.get("status") or "") not in ("done", "merged")]


def find_task(tasks: list, key: str):
    key = (key or "").strip()
    if not key:
        return None
    for t in tasks:
        if t.get("id") == key or t.get("branch") == key:
            return t
    for t in tasks:
        if t.get("id", "").startswith(key) or t.get("branch", "").endswith(key):
            return t
    return None


def checkout_task(repo, task: dict) -> tuple:
    """Chuyển sang nhánh của task và trả về plan đã khôi phục. (plan, error)."""
    repo = Path(repo)
    branch = task.get("branch") or ""
    if not branch:
        return None, "Task thiếu tên nhánh."
    if not is_clean(repo):
        return None, ("Repo đang có thay đổi chưa commit — hãy /push hoặc /undo "
                      "trước khi tiếp tục việc khác.")
    if _local_branch_exists(repo, branch):
        if current_branch(repo) != branch:
            rc, out = _git(repo, "checkout", branch, timeout=120)
            if rc != 0:
                return None, f"Không chuyển được nhánh: {oneline(out, 300)}"
        remote = task.get("remote") or DEFAULT_REMOTE
        if _remote_branch_exists(repo, branch, remote):
            # Máy này có thể đang giữ bản cũ; chỉ fast-forward, không nuốt commit local.
            _git(repo, "merge", "--ff-only", f"{remote}/{branch}", timeout=120)
    else:
        ref = task.get("ref") or f"{task.get('remote') or DEFAULT_REMOTE}/{branch}"
        rc, out = _git(repo, "checkout", "-b", branch, ref, timeout=120)
        if rc != 0:
            return None, f"Không tạo được nhánh từ GitHub: {oneline(out, 300)}"

    pid = task.get("id") or _plan_id_of_branch(branch)
    data = read_state(repo, branch, pid) or task.get("state") or {}
    if not data:
        return None, "Không đọc được trạng thái công việc trên nhánh."
    plan = dict(data)
    plan["id"] = pid
    plan["work_branch"] = branch
    plan["work_base"] = task.get("base") or plan.get("work_base") or _default_branch(repo)
    plan["checkpoint"] = ""              # checkpoint của máy cũ không dùng được
    plan["status"] = "draft"             # run_plan sẽ đặt lại "running"
    plan["resumed"] = True
    plan["resumed_from"] = task.get("machine") or ""
    return plan, ""
