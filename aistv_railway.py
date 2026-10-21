#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_railway.py — wrapper Railway CLI cho bot AI STV.

Dùng:
  python aistv_railway.py check [--json]
  python aistv_railway.py projects [--json]
  python aistv_railway.py status [--json]
  python aistv_railway.py logs -n 100 [--build] [--http] [--service S] [--environment E] [--filter F] [--json]
  python aistv_railway.py deployments [--limit 10] [--json]
  python aistv_railway.py deploy [PATH] [--message M] [--wait] [--json]
  python aistv_railway.py vars [--show-values] [--json]
  python aistv_railway.py var-set KEY=VALUE [--deploy]
  python aistv_railway.py domains [--service S] [--json]

Không bao giờ in giá trị biến môi trường trừ khi truyền --show-values.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT = int(os.getenv("AISTV_RAILWAY_TIMEOUT", "180"))
TOKEN_KEYS = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE|CREDENTIAL)", re.I)


class RailwayError(RuntimeError):
    pass


def find_cli() -> str:
    explicit = os.getenv("RAILWAY_BIN", "")
    if explicit and Path(explicit).is_file():
        return explicit
    for name in ("railway.exe", "railway"):
        exe = shutil.which(name)
        if exe and not exe.lower().endswith((".cmd", ".bat", ".ps1")):
            return exe
    prefixes = [
        Path(os.getenv("APPDATA", "")) / "npm",
        Path(os.getenv("ProgramFiles", "")) / "nodejs",
        Path("C:/npm/prefix"),
    ]
    for base in prefixes:
        candidate = base / "node_modules" / "@railway" / "cli" / "bin" / "railway.exe"
        if candidate.is_file():
            return str(candidate)
    cmd = shutil.which("railway.cmd") or shutil.which("railway")
    if cmd:
        return cmd
    raise RailwayError(
        "Chưa có Railway CLI. Cài bằng: npm install -g @railway/cli"
    )


def run(args, timeout=None, cwd=None, stdin=None) -> subprocess.CompletedProcess:
    exe = find_cli()
    cmd = [exe, *args]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", *cmd]
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    try:
        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or TIMEOUT,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RailwayError(f"Không chạy được Railway CLI: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RailwayError(
            f"Railway CLI quá {timeout or TIMEOUT}s không trả lời (lệnh stream log? thêm -n)."
        ) from exc


def _clean(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
    return text.strip()


def _fail(proc) -> str:
    out = _clean(proc.stderr) or _clean(proc.stdout)
    if "Unauthorized" in out or "not logged in" in out.lower():
        return "Chưa đăng nhập Railway. Chạy: railway login (hoặc đặt RAILWAY_TOKEN)."
    if "No linked project" in out or "not linked" in out.lower():
        return "Thư mục chưa link project. Chạy: railway link -p <project> -e <env> -s <service>."
    return out or f"Railway CLI thoát với mã {proc.returncode}."


def _json_arg(proc, what):
    text = _clean(proc.stdout)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RailwayError(f"Không đọc được JSON {what}: {text[:300]}")


def emit(data, as_json: bool, human: str):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(human)


def cmd_check(a):
    exe = find_cli()
    ver = run(["--version"], timeout=30)
    who = run(["whoami"], timeout=30)
    logged_in = who.returncode == 0
    info = {
        "cli": exe,
        "version": _clean(ver.stdout) or _clean(ver.stderr),
        "logged_in": logged_in,
        "account": _clean(who.stdout) if logged_in else None,
        "hint": None if logged_in else "Chạy: railway login",
    }
    emit(info, a.json, "\n".join(
        [f"CLI: {info['version']} ({exe})",
         f"Đăng nhập: {'có — ' + info['account'] if logged_in else 'CHƯA'}"
         + ("" if logged_in else "\n→ railway login")]
    ))
    return 0 if logged_in else 2


def cmd_projects(a):
    proc = run(["list", "--json"])
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    data = _json_arg(proc, "danh sách project")
    items = data if isinstance(data, list) else data.get("projects", data)
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for p in items:
            name = p.get("name") or p.get("id")
            print(f"- {name}  [{p.get('id', '')}]")
    return 0


def cmd_status(a):
    proc = run(["status", "--json"])
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    data = _json_arg(proc, "status")
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    project = data.get("name") or data.get("project", {}).get("name")
    env = (data.get("environment") or {})
    env_name = env.get("name") if isinstance(env, dict) else env
    print(f"Project: {project}")
    print(f"Environment: {env_name or '?'}")
    services = (data.get("services") or {}).get("edges") or data.get("services") or []
    for edge in services:
        node = edge.get("node", edge) if isinstance(edge, dict) else edge
        print(f"- service: {node.get('name')} [{node.get('id', '')}]")
    return 0


def cmd_logs(a):
    args = ["logs", "-n", str(a.lines)]
    if a.build:
        args.append("--build")
    if a.http:
        args.append("--http")
    if a.service:
        args += ["--service", a.service]
    if a.environment:
        args += ["--environment", a.environment]
    if a.filter:
        args += ["--filter", a.filter]
    if a.json:
        args.append("--json")
    proc = run(args, timeout=a.timeout)
    out = _clean(proc.stdout)
    if proc.returncode != 0 and not out:
        raise RailwayError(_fail(proc))
    if a.json:
        for line in out.splitlines():
            try:
                print(json.dumps(json.loads(line), ensure_ascii=False))
            except json.JSONDecodeError:
                print(json.dumps({"message": line}, ensure_ascii=False))
    else:
        print(out[-20000:] if out else "(không có log)")
    return 0


def cmd_deployments(a):
    args = ["deployment", "list", "--json", "--limit", str(a.limit)]
    if a.service:
        args += ["--service", a.service]
    if a.environment:
        args += ["--environment", a.environment]
    proc = run(args)
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    data = _json_arg(proc, "deployments")
    items = data if isinstance(data, list) else data.get("deployments", data)
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for d in items:
            print(f"- {d.get('status', '?'):<10} {d.get('createdAt', '')}  {d.get('id', '')}")
    return 0


def _latest_status(a):
    proc = run(["deployment", "list", "--json", "--limit", "1"], timeout=60)
    if proc.returncode != 0:
        return None
    data = _json_arg(proc, "deployments")
    items = data if isinstance(data, list) else data.get("deployments", [])
    return items[0] if items else None


def cmd_deploy(a):
    path = str(Path(a.path or ".").resolve())
    args = ["up", path, "-d", "--json", "-y"]
    if a.message:
        args += ["--message", a.message]
    if a.service:
        args += ["--service", a.service]
    if a.environment:
        args += ["--environment", a.environment]
    proc = run(args, timeout=a.timeout)
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    info = {"path": path, "submitted": True, "deployment": None, "output": _clean(proc.stdout)[-1500:]}
    if a.wait:
        deadline = time.time() + a.wait
        last = ""
        while time.time() < deadline:
            dep = _latest_status(a)
            if dep:
                status = str(dep.get("status", ""))
                info["deployment"] = dep
                last = status
                if status.upper() in {"SUCCESS", "FAILED", "CRASHED", "REMOVED", "SKIPPED"}:
                    break
            time.sleep(5)
        info["final_status"] = last
    if a.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"Đã gửi deploy: {path}")
        if a.wait:
            print(f"Trạng thái cuối: {info.get('final_status') or 'chưa rõ (quá thời gian chờ)'}")
        else:
            print("Theo dõi: aistv_railway.py deployments --limit 3")
    return 0


def _load_vars(a):
    args = ["variable", "list", "--json"]
    if a.service:
        args += ["--service", a.service]
    if a.environment:
        args += ["--environment", a.environment]
    proc = run(args)
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    return _json_arg(proc, "variables")


def cmd_vars(a):
    data = _load_vars(a)
    values = data if isinstance(data, dict) else {str(i): v for i, v in enumerate(data)}
    if a.show_values:
        emit(values, a.json, "\n".join(f"{k}={v}" for k, v in values.items()))
        return 0
    secret = {k: "<hidden>" if (v is None or TOKEN_KEYS.search(k)) else "<set>" for k, v in values.items()}
    emit(secret, a.json, "\n".join(f"- {k} = <set>" for k in values))
    return 0


def cmd_var_set(a):
    pair = a.pair
    if "=" in pair:
        key, value = pair.split("=", 1)
        args = ["variable", "set", f"{key}={value}"]
    else:
        key = pair
        value = sys.stdin.read() if a.stdin else ""
        args = ["variable", "set", key, "--stdin"]
    if a.service:
        args += ["--service", a.service]
    if a.environment:
        args += ["--environment", a.environment]
    if not a.deploy:
        args.append("--skip-deploys")
    proc = run(args, stdin=value if "--stdin" in args else None)
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    print(json.dumps({"ok": True, "key": key, "deploy_triggered": a.deploy}, ensure_ascii=False))
    return 0


def cmd_domains(a):
    args = ["domain", "list", "--json"]
    if a.service:
        args += ["--service", a.service]
    proc = run(args)
    if proc.returncode != 0:
        raise RailwayError(_fail(proc))
    try:
        data = json.loads(_clean(proc.stdout))
    except json.JSONDecodeError:
        data = _clean(proc.stdout)
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="Railway CLI wrapper cho AI STV")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--service", help="tên/id service")
        sp.add_argument("--environment", help="tên/id environment")

    sub.add_parser("check").add_argument("--json", action="store_true")
    sub.add_parser("projects").add_argument("--json", action="store_true")
    sub.add_parser("status").add_argument("--json", action="store_true")

    sp = sub.add_parser("logs")
    sp.add_argument("-n", "--lines", type=int, default=100)
    sp.add_argument("--build", action="store_true")
    sp.add_argument("--http", action="store_true")
    sp.add_argument("--filter", default="")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--timeout", type=int, default=90)
    common(sp)

    sp = sub.add_parser("deployments")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    common(sp)

    sp = sub.add_parser("deploy")
    sp.add_argument("path", nargs="?", default=".")
    sp.add_argument("--message", default="deploy by AI STV")
    sp.add_argument("--wait", type=int, default=0, help="giây chờ trạng thái cuối (0 = không chờ)")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--timeout", type=int, default=300)
    common(sp)

    sp = sub.add_parser("vars")
    sp.add_argument("--show-values", action="store_true")
    sp.add_argument("--json", action="store_true")
    common(sp)

    sp = sub.add_parser("var-set")
    sp.add_argument("pair", help="KEY=VALUE hoặc KEY (giá trị đọc từ stdin)")
    sp.add_argument("--stdin", action="store_true")
    sp.add_argument("--deploy", action="store_true")
    common(sp)

    sp = sub.add_parser("domains")
    sp.add_argument("--json", action="store_true")
    common(sp)
    return p


def main():
    a = build_parser().parse_args()
    handler = {
        "check": cmd_check,
        "projects": cmd_projects,
        "status": cmd_status,
        "logs": cmd_logs,
        "deployments": cmd_deployments,
        "deploy": cmd_deploy,
        "vars": cmd_vars,
        "var-set": cmd_var_set,
        "domains": cmd_domains,
    }[a.cmd]
    try:
        return handler(a)
    except RailwayError as exc:
        payload = {"ok": False, "error": str(exc)}
        if getattr(a, "json", False):
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"LỖI: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
