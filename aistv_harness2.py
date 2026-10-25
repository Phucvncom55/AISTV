#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_harness2.py — Cầu nối AI STV ↔ Harness² (google-research/harness2).

Vì sao: Harness² định nghĩa "harness" = system prompt + guardrails + memory +
tool guidance + skills + subagents + scripts + plugins, và tối ưu chính lớp đó
(không sửa trọng số model). AI STV đã có đủ các thành phần này nhưng nằm rải
rác trong SOUL.md / AGENTS.md / MEMORY.md / skills/. Tool này:

  export  -> đóng gói harness hiện tại của AI STV thành "harness tree" chuẩn
             Harness² rồi validate bằng chính bộ luật của Harness²
  check   -> validate một tree bất kỳ (bắt skill thiếu trigger, thiếu name:,
             vượt cap always-on 24k, script không compile...)
  diff    -> so sánh 2 tree (dùng khi Harness² đề xuất bản harness mới)
  demo    -> chạy pipeline recursion offline (không cần credential) để tự kiểm tra
  status  -> tình trạng cài đặt + credential còn thiếu gì
  run     -> chạy benchmark thật (cần Vertex AI), passthrough sang harness2

CLI
  python aistv_harness2.py status
  python aistv_harness2.py export [--out DIR] [--json]
  python aistv_harness2.py check [--tree DIR]
  python aistv_harness2.py diff --before DIR --after DIR
  python aistv_harness2.py demo [--k 2]
  python aistv_harness2.py run --bench jb --k 1 --mode parallel   # cần credential

Ghi chú: phần export/check/diff chỉ đọc file, không sửa harness đang chạy.
"""
import argparse
import json
import os
import re as _RE
import subprocess
import sys
import time
from pathlib import Path

AI = Path(__file__).resolve().parent
WORKSPACE = Path(os.getenv("AISTV_WORKSPACE") or "/content/stv_agent/workspace")
H2_ROOT = Path(os.getenv("HARNESS2_ROOT") or "/root/harness2-src")
H2_PY = H2_ROOT / ".venv" / "bin" / "python"
TREE_OUT = AI / "harness" / "tree"
ALWAYS_ON_CAP = 24_000
TRIGGER = "- Khi {desc}, nạp skill `{name}`."
MANUAL_DESC = {
    "aistv_bot.py": "Bot Telegram chính: nhận tin, định tuyến, gọi OpenCode/Web2API và gửi file",
    "aistv_config.py": "Đồng bộ token/API key từ .env, config.env hoặc repo private GitHub",
}


# ---------------------------------------------------------------- harness2 glue
def h2():
    """Import harness2 từ source tree (core không cần dependency ngoài)."""
    if not (H2_ROOT / "harness2" / "core" / "tree.py").is_file():
        sys.exit(f"Chưa có Harness² tại {H2_ROOT}. Cài: xem `status`.")
    if str(H2_ROOT) not in sys.path:
        sys.path.insert(0, str(H2_ROOT))
    from harness2.core import tree as HT
    from harness2.substrate.opencode import OPENCODE_SURFACE
    return HT, OPENCODE_SURFACE


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def first_doc_line(p: Path) -> str:
    """Dòng mô tả đầu tiên trong docstring của một script AI STV (bỏ banner ASCII)."""
    if p.name in MANUAL_DESC:
        return MANUAL_DESC[p.name]
    for line in read_text(p).splitlines()[:14]:
        s = line.strip().strip('"').strip()
        if not s or s.startswith(("#", "-", "'")):
            continue
        letters = sum(c.isalnum() or c.isspace() for c in s) / max(1, len(s))
        if letters < 0.75 or any(c in s for c in "═║╔╗╚╝╠╣│┌┐└┘─━"):
            continue
        if s.endswith(":") or s.isupper() or len(s) < 18:
            continue
        if any(x in s for x in ("curl", "http", "bash ", "python ", "•")):
            continue
        s = s.replace(p.name + " — ", "").replace(p.name + " - ", "").strip()
        return s
    return MANUAL_DESC.get(p.name, "")


# --------------------------------------------------------------------- export
def skill_script_names(tree: dict) -> set:
    """Tên script nằm trong skills/*/scripts/ — SKILL.md tham chiếu chúng theo đường dẫn
    tương đối nên Harness² cần biết chúng có sẵn (mặc định nó chỉ nhận scripts/ ở gốc)."""
    return {rel.rsplit("/", 1)[-1] for rel in tree if rel.startswith("skills/") and "/scripts/" in rel}


def skill_files() -> dict:
    """Chỉ copy phần surface của OpenCode chấp nhận: SKILL.md + scripts/*."""
    out = {}
    root = WORKSPACE / "skills"
    for skill in sorted(p for p in root.iterdir() if p.is_dir()):
        md = skill / "SKILL.md"
        if not md.is_file():
            continue
        out[f"skills/{skill.name}/SKILL.md"] = read_text(md)
        scripts = skill / "scripts"
        if scripts.is_dir():
            for f in sorted(scripts.glob("*")):
                if f.is_file() and f.suffix in (".py", ".sh", ".js", ".ts", ".txt", ".json", ".md"):
                    out[f"skills/{skill.name}/scripts/{f.name}"] = read_text(f)
    copied = len(out)
    total = sum(1 for f in root.rglob("*") if f.is_file())
    return {"files": out, "dropped": max(0, total - copied)}


def tool_guidance() -> str:
    lines = [
        "# TOOL GUIDANCE — công cụ local của AI STV",
        "",
        "Chạy bằng `python3 <script>` trong /root/AISTV. Không cần gọi model.",
    ]
    for p in sorted(AI.glob("aistv_*.py")):
        desc = first_doc_line(p)
        if desc:
            lines.append(f"- `{p.name}` — {desc}")
    return "\n".join(lines) + "\n"


def fit_memory(text: str, budget: int) -> tuple[str, int]:
    """Cắt MEMORY.md theo ngân sách always-on, giữ phần MỚI nhất (entry nằm cuối file)."""
    if len(text) <= budget:
        return text, 0
    lines = text.splitlines()
    head = [ln for ln in lines[:3] if ln.startswith("#")]
    body = lines[len(head):]
    kept, used = [], len("\n".join(head))
    for ln in reversed(body):
        if used + len(ln) + 1 > budget - 120:
            break
        kept.append(ln)
        used += len(ln) + 1
    kept.reverse()
    dropped = len(body) - len(kept)
    marker = f"<!-- cắt {dropped} dòng cũ để vừa cap always-on {ALWAYS_ON_CAP} -->"
    return "\n".join(head + [marker] + kept) + "\n", dropped


def build_tree() -> dict:
    soul = read_text(WORKSPACE / "SOUL.md")
    agents = read_text(WORKSPACE / "AGENTS.md")
    memory = read_text(WORKSPACE / "MEMORY.md")
    guide = tool_guidance()

    systemprompt = (
        "# AI STV — trợ lý agent trên Telegram\n\n"
        + soul
        + "\n\n## Cách làm việc\nTuân thủ guardrails.md. Kỹ năng nạp qua `skill` khi khớp mô tả.\n"
    )
    tree = {
        "systemprompt.md": systemprompt,
        "guardrails.md": agents + "\n",
        "LongTermMEMORY.md": "",
        "tool_descriptions/tool_guidance.md": guide,
    }
    tree.update(skill_files()["files"])

    # Harness² yêu cầu mọi skill phải được nêu tên trong always-on text. AGENTS.md chỉ
    # liệt kê một phần, nên tính trước chỗ cho trigger line rồi mới chia ngân sách cho memory.
    HT, SURFACE = h2()
    body = HT.always_on_text(SURFACE, tree)
    missing = [n for n in HT.skill_names(SURFACE, tree) if n not in body]
    lines = [TRIGGER.format(desc=trigger_desc(tree, n), name=n) for n in missing]
    fixed = len(systemprompt) + len(agents) + len(guide) + sum(len(x) for x in lines) + 200
    tree["LongTermMEMORY.md"], dropped = fit_memory(memory, max(1_500, ALWAYS_ON_CAP - fixed))
    if lines:
        tree["guardrails.md"] = tree["guardrails.md"].rstrip() + "\n\n" + "\n".join(lines) + "\n"
    return {
        "tree": tree,
        "memory_dropped": dropped,
        "skill_extras_dropped": skill_files()["dropped"],
        "triggers_added": len(lines),
        "untriggered": [n for n in HT.skill_names(SURFACE, tree) if n not in
                        HT.always_on_text(SURFACE, tree)],
    }


def trigger_desc(tree: dict, name: str) -> str:
    """Mô tả ngắn (<=140 ký tự) cho trigger line của một skill."""
    automate = "hợp với kỹ năng này"
    fm = tree.get(f"skills/{name}/SKILL.md", "")[:600]
    m = _RE.search(r"^description:\s*(.+)$", fm, _RE.M)
    desc = (m.group(1).strip() if m else automate).strip('"\'').rstrip(" .,;:").strip()
    desc = desc or automate
    return desc if len(desc) <= 110 else desc[:107].rstrip(" .,;:-") + "..."




def cmd_export(a) -> int:
    HT, SURFACE = h2()
    data = build_tree()
    tree = data["tree"]
    out = Path(a.out or TREE_OUT)
    try:
        census = HT.validate(SURFACE, tree, reserved_scripts=skill_script_names(tree))
    except ValueError as e:
        print("❌ Harness chưa hợp lệ với surface opencode của Harness²:")
        for part in str(e).split(" | "):
            print(f"  - {part}")
        return 2
    HT.write_tree(SURFACE, tree, out, stubs=True)
    if a.json:
        print(json.dumps({**census, "out": str(out), "memory_lines_dropped": data["memory_dropped"]},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"✅ Đã export harness AI STV -> {out}")
    print(f"  files={census['n_files']} skills={census['skills']} "
          f"scripts={census['scripts']} always-on={census['always_on_chars']}/{ALWAYS_ON_CAP} ký tự")
    if data["memory_dropped"]:
        print(f"  ⚠️  MEMORY.md: cắt {data['memory_dropped']} dòng cũ để vừa cap always-on")
    if data["skill_extras_dropped"]:
        print(f"  ⚠️  {data['skill_extras_dropped']} file phụ trong skills/ không thuộc surface "
              f"(references/templates) — Harness² bỏ qua")
    return 0


def cmd_check(a) -> int:
    HT, SURFACE = h2()
    d = Path(a.tree or TREE_OUT)
    if not d.is_dir():
        print(f"❌ Không có tree tại {d}. Chạy `export` trước.")
        return 2
    rejected: list[str] = []
    tree = HT.read_tree(SURFACE, d, rejected=rejected)
    try:
        census = HT.validate(SURFACE, tree, reserved_scripts=skill_script_names(tree))
    except ValueError as e:
        print(f"❌ {d} KHÔNG hợp lệ:")
        for part in str(e).split(" | "):
            print(f"  - {part}")
        return 2
    print(f"✅ {d} hợp lệ: files={census['n_files']} skills={census['skills']} "
          f"always-on={census['always_on_chars']}/{ALWAYS_ON_CAP}")
    if rejected:
        print(f"  bỏ qua {len(rejected)} file ngoài surface: " + ", ".join(rejected[:5]))
    return 0


def cmd_diff(a) -> int:
    HT, SURFACE = h2()
    before = HT.read_tree(SURFACE, Path(a.before))
    after = HT.read_tree(SURFACE, Path(a.after))
    d = HT.diff_summary(SURFACE, before, after)
    for key in ("added", "removed", "modified"):
        items = d.get(key) or []
        print(f"{key} ({len(items)}):")
        for rel in items[:20]:
            print(f"  {rel}")
        if len(items) > 20:
            print(f"  ... +{len(items) - 20}")
    delta = d.get("always_on_char_delta") or 0
    print(f"always-on: {delta:+d} ký tự")
    return 0


# ------------------------------------------------------------------ ops/status
def h2_commit() -> str:
    try:
        p = subprocess.run(["git", "-C", str(H2_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() or "?"
    except Exception:
        return "?"


def creds() -> dict:
    env = {}
    for key in ("HARNESS2_SOLVER_MODEL", "HARNESS2_IMPROVER_MODEL", "HARNESS2_JUDGE_MODEL",
                "GOOGLE_CLOUD_PROJECT"):
        env[key] = "đã đặt" if os.getenv(key) else "thiếu"
    return env


def cmd_status(a) -> int:
    ok_repo = (H2_ROOT / "pyproject.toml").is_file()
    print(f"{'✅' if ok_repo else '❌'} Harness²: {H2_ROOT} (commit {h2_commit() if ok_repo else '-'})")
    print(f"{'✅' if H2_PY.is_file() else '⚠️ '} venv: {H2_PY}")
    demo = H2_ROOT / "runs" / "demo" / "demo.json"
    if demo.is_file():
        try:
            d = json.loads(demo.read_text())
            print(f"✅ demo offline: {d.get('n_tasks')} task, failed={d.get('failed')} "
                  f"({time.strftime('%d/%m %H:%M', time.localtime(demo.stat().st_mtime))})")
        except Exception:
            print(f"⚠️  demo có file nhưng không đọc được: {demo}")
    else:
        print("⚠️  chưa chạy demo offline (`demo`)")
    print(f"{'✅' if Path('/tools/node/bin/opencode').exists() else '⚠️ '} opencode CLI: "
          f"{subprocess.run(['opencode', '--version'], capture_output=True, text=True).stdout.strip() or '?'}")
    c = creds()
    ready = all(v == "đã đặt" for v in c.values())
    print(f"{'✅' if ready else '⚠️ '} credential chạy benchmark thật: " +
          ", ".join(f"{k}={v}" for k, v in c.items()))
    if Path(a.tree or TREE_OUT).is_dir():
        print(f"✅ harness tree của AI STV: {Path(a.tree or TREE_OUT)}")
    else:
        print("⚠️  chưa export harness tree (`export`)")
    return 0


def cmd_demo(a) -> int:
    out = H2_ROOT / "runs" / f"demo-{time.strftime('%Y%m%d-%H%M%S')}"
    py = str(H2_PY if H2_PY.is_file() else sys.executable)
    cmd = [py, "-m", "harness2.cli.demo", "--output", str(out), "--k", str(a.k)]
    p = subprocess.run(cmd, cwd=str(H2_ROOT), capture_output=True, text=True, timeout=1800)
    tail = (p.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print(line)
    if p.returncode != 0:
        print((p.stderr or "").strip()[-500:])
    return p.returncode


def cmd_run(a) -> int:
    c = creds()
    missing = [k for k, v in c.items() if v != "đã đặt"]
    if missing:
        print("❌ Chạy benchmark thật cần credential Vertex AI, đang thiếu: " + ", ".join(missing))
        print("   Cách bật: cp .env.example .env → điền GOOGLE_CLOUD_PROJECT + model → "
              "gcloud auth application-default login")
        print("   Không cần credential thì dùng: `demo` (offline) hoặc `export` + `check`.")
        return 2
    argv = ["harness2"] + [x for x in a.rest if x != "--"]
    print("→ " + " ".join(argv))
    return subprocess.run(argv, cwd=str(H2_ROOT)).returncode


def main() -> int:
    # `run` chuyển nguyên tham số cho harness2, nên bắt trước khi argparse nuốt mất.
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        return cmd_run(argparse.Namespace(rest=sys.argv[2:]))

    ap = argparse.ArgumentParser(description="Cầu nối AI STV ↔ Harness²")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="tình trạng cài đặt + credential")
    s.add_argument("--tree")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("export", help="đóng gói harness AI STV thành harness tree")
    s.add_argument("--out")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("check", help="validate một harness tree")
    s.add_argument("--tree")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("diff", help="so sánh 2 harness tree")
    s.add_argument("--before", required=True)
    s.add_argument("--after", required=True)
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("demo", help="chạy recursion offline (không cần credential)")
    s.add_argument("--k", type=int, default=2)
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("run", help="chạy benchmark thật (cần Vertex AI)")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_run)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
