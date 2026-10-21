#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_cloudflare.py — Cloudflare API wrapper cho bot AI STV.

Dùng:
  python aistv_cloudflare.py check [--json]
  python aistv_cloudflare.py accounts [--json]
  python aistv_cloudflare.py zones [--name DOMAIN] [--json]
  python aistv_cloudflare.py dns list --zone DOMAIN [--json]
  python aistv_cloudflare.py dns add --zone DOMAIN --type A --name @ --content 1.2.3.4 [--proxied] [--ttl 1] [--json]
  python aistv_cloudflare.py dns delete --zone DOMAIN --id RECORD_ID --yes [--json]
  python aistv_cloudflare.py ai models [--task text-generation] [--search q] [--json]
  python aistv_cloudflare.py ai run MODEL --prompt "..." [--out FILE] [--json]
  python aistv_cloudflare.py ai run MODEL --input '{"messages":[...]}' [--out FILE] [--json]
  python aistv_cloudflare.py pages projects [--json]
  python aistv_cloudflare.py pages deploy DIR --project NAME [--branch main] [--create] [--json]
  python aistv_cloudflare.py workers deploy [DIR] [--json]
  python aistv_cloudflare.py r2 buckets [--json]
  python aistv_cloudflare.py token-save --stdin

Token lấy từ CLOUDFLARE_API_TOKEN hoặc .secrets/cloudflare_token.
Không bao giờ in token ra màn hình.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
BASE = Path(os.getenv("AISTV_DIR") or Path(__file__).resolve().parent)
SECRETS = BASE / ".secrets"
TOKEN_FILE = SECRETS / "cloudflare_token"
ACCOUNT_FILE = SECRETS / "cloudflare_account_id"
TIMEOUT = int(os.getenv("AISTV_CF_TIMEOUT", "90"))


class CFError(RuntimeError):
    pass


def _secure(path: Path) -> None:
    try:
        if os.name == "nt":
            user = os.getenv("USERNAME") or ""
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                capture_output=True,
                timeout=20,
            )
        else:
            os.chmod(path, 0o600)
    except Exception:
        pass


def load_token() -> str:
    token = (os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_API_TOKEN") or "").strip()
    if not token and TOKEN_FILE.is_file():
        token = TOKEN_FILE.read_text("utf-8").strip()
    if not token:
        raise CFError(
            "Chưa có Cloudflare API token. Tạo tại https://dash.cloudflare.com/profile/api-tokens "
            "rồi lưu vào .secrets/cloudflare_token hoặc đặt CLOUDFLARE_API_TOKEN."
        )
    return token


def save_token(token: str) -> Path:
    token = (token or "").strip()
    if not token:
        raise CFError("Token rỗng.")
    SECRETS.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n", "utf-8")
    _secure(TOKEN_FILE)
    return TOKEN_FILE


def _format_errors(payload) -> str:
    errs = (payload or {}).get("errors") or []
    parts = []
    for e in errs:
        code = e.get("code")
        msg = e.get("message") or ""
        parts.append(f"{code}: {msg}" if code else msg)
    return "; ".join(parts) or "Cloudflare trả lỗi không rõ"


def api(method: str, path: str, data=None, timeout=None, raw=False):
    token = load_token()
    url = API + path
    body = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
            content = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if raw:
                return content, ctype
            if "application/json" in ctype:
                payload = json.loads(content.decode("utf-8"))
                if not payload.get("success", False):
                    raise CFError(_format_errors(payload))
                return payload.get("result")
            return content
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = _format_errors(payload)
        except Exception:
            detail = exc.reason or ""
        hint = ""
        if exc.code in (401, 403):
            hint = " (token sai/hết hạn hoặc thiếu quyền)"
        raise CFError(f"HTTP {exc.code}{hint}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CFError(f"Không kết nối được Cloudflare API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CFError(f"Cloudflare API quá {timeout or TIMEOUT}s không trả lời.") from exc


def emit(data, as_json: bool, human: str) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(human)


def accounts() -> list:
    result = api("GET", "/accounts?per_page=50")
    return result or []


def get_account_id(explicit=None, save=True) -> str:
    if explicit:
        return explicit
    env = (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if env:
        return env
    if ACCOUNT_FILE.is_file():
        saved = ACCOUNT_FILE.read_text("utf-8").strip()
        if saved:
            return saved
    items = accounts()
    if len(items) == 1:
        aid = items[0]["id"]
        if save:
            SECRETS.mkdir(parents=True, exist_ok=True)
            ACCOUNT_FILE.write_text(aid + "\n", "utf-8")
        return aid
    if not items:
        raise CFError("Token không thấy account nào (thiếu quyền Account:Read?).")
    names = ", ".join(f"{a.get('name')} ({a.get('id')})" for a in items)
    raise CFError(f"Có nhiều account: {names}. Chạy lại với --account ID.")


def zone_id(value: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return value
    q = urllib.parse.quote(value, safe="")
    items = api("GET", f"/zones?name={q}&per_page=1")
    if not items:
        raise CFError(f"Không tìm thấy zone '{value}' trong tài khoản này.")
    return items[0]["id"]


def _record_line(r: dict) -> str:
    proxied = " proxied" if r.get("proxied") else ""
    return f"{r.get('type'):6} {r.get('name')} -> {r.get('content')} (ttl={r.get('ttl')}{proxied}) id={r.get('id')}"


def cmd_check(a) -> int:
    verify = api("GET", "/user/tokens/verify")
    items = accounts()
    data = {
        "token": verify,
        "accounts": [{"id": x.get("id"), "name": x.get("name")} for x in items],
    }
    lines = [f"Token: {verify.get('status', 'unknown')}"]
    if items:
        lines.append("Accounts:")
        lines += [f"  - {x.get('name')}  {x.get('id')}" for x in items]
    else:
        lines.append("Accounts: (không có — token thiếu quyền Account:Read?)")
    emit(data, a.json, "\n".join(lines))
    return 0


def cmd_accounts(a) -> int:
    items = accounts()
    data = [{"id": x.get("id"), "name": x.get("name")} for x in items]
    emit(data, a.json, "\n".join(f"{x['name']}  {x['id']}" for x in data) or "Không có account.")
    return 0


def cmd_zones(a) -> int:
    path = "/zones?per_page=50"
    if a.name:
        path += "&name=" + urllib.parse.quote(a.name, safe="")
    items = api("GET", path)
    data = [
        {"id": z.get("id"), "name": z.get("name"), "status": z.get("status"), "plan": (z.get("plan") or {}).get("name")}
        for z in (items or [])
    ]
    emit(data, a.json, "\n".join(f"{z['name']}  {z['status']}  {z['plan']}  {z['id']}" for z in data) or "Không có zone.")
    return 0


def cmd_dns_list(a) -> int:
    zid = zone_id(a.zone)
    items = api("GET", f"/zones/{zid}/dns_records?per_page=100")
    data = [
        {
            "id": r.get("id"),
            "type": r.get("type"),
            "name": r.get("name"),
            "content": r.get("content"),
            "proxied": r.get("proxied"),
            "ttl": r.get("ttl"),
        }
        for r in (items or [])
    ]
    emit(data, a.json, "\n".join(_record_line(r) for r in (items or [])) or "Không có bản ghi DNS.")
    return 0


def cmd_dns_add(a) -> int:
    zid = zone_id(a.zone)
    payload = {
        "type": a.type.upper(),
        "name": a.name,
        "content": a.content,
        "ttl": a.ttl,
    }
    if a.proxied is not None:
        payload["proxied"] = a.proxied
    rec = api("POST", f"/zones/{zid}/dns_records", payload)
    data = {"id": rec.get("id"), "type": rec.get("type"), "name": rec.get("name"), "content": rec.get("content")}
    emit(data, a.json, "Đã thêm: " + _record_line(rec))
    return 0


def cmd_dns_delete(a) -> int:
    if not a.yes:
        raise CFError("Xoá DNS là thao tác phá huỷ — thêm --yes để xác nhận.")
    zid = zone_id(a.zone)
    rec = api("DELETE", f"/zones/{zid}/dns_records/{a.id}")
    emit({"deleted": rec}, a.json, f"Đã xoá bản ghi {a.id}.")
    return 0


def cmd_ai_models(a) -> int:
    aid = get_account_id(a.account)
    qs = ["per_page=100", "page=1"]
    if a.task:
        qs.append("task=" + urllib.parse.quote(a.task, safe=""))
    if a.search:
        qs.append("search=" + urllib.parse.quote(a.search, safe=""))
    result = api("GET", f"/accounts/{aid}/ai/models/search?" + "&".join(qs))
    items = result if isinstance(result, list) else (result or {}).get("models", [])
    data = [
        {"name": m.get("name"), "task": (m.get("task") or {}).get("name"), "description": m.get("description")}
        for m in items
    ]
    lines = [f"{m['name']}  [{m['task']}]  {(m['description'] or '')[:90]}" for m in data]
    emit(data, a.json, "\n".join(lines) or "Không có model phù hợp.")
    return 0


def cmd_ai_run(a) -> int:
    aid = get_account_id(a.account)
    if a.input:
        raw = a.input
        if raw == "-":
            raw = sys.stdin.read()
        elif raw.startswith("@"):
            raw = Path(raw[1:]).read_text("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CFError(f"--input không phải JSON hợp lệ: {exc}") from exc
    elif a.prompt is not None:
        payload = {"prompt": a.prompt}
    else:
        raise CFError("Cần --prompt hoặc --input JSON.")
    content, ctype = api("POST", f"/accounts/{aid}/ai/run/{a.model}", payload, timeout=a.timeout, raw=True)
    if "application/json" in ctype:
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception:
            data = {"raw": content.decode("utf-8", "replace")}
        if a.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        elif isinstance(data, dict) and "response" in data:
            print(data["response"])
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    out = Path(a.out or "cloudflare_ai_output.bin")
    out.write_bytes(content)
    emit({"file": str(out), "bytes": len(content), "content_type": ctype}, a.json, f"Đã lưu kết quả: {out} ({len(content)} bytes, {ctype})")
    return 0


def _npx() -> str:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise CFError("Không tìm thấy npx. Cần Node.js/npm.")
    return exe


def run_wrangler(args, cwd=None, timeout=600) -> str:
    exe = _npx()
    cmd = [exe, "-y", "wrangler@latest", *args]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", *cmd]
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = load_token()
    env["CLOUDFLARE_ACCOUNT_ID"] = get_account_id()
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CFError(f"Wrangler quá {timeout}s không xong.") from exc
    out = (proc.stdout or "") + (proc.stderr or "")
    clean = re.sub(r"\x1b\[[0-9;]*m", "", out).strip()
    if proc.returncode != 0:
        raise CFError(clean[-3000:] or f"Wrangler thoát mã {proc.returncode}")
    return clean


def cmd_pages_projects(a) -> int:
    out = run_wrangler(["pages", "project", "list"], timeout=180)
    emit({"output": out}, a.json, out)
    return 0


def cmd_pages_deploy(a) -> int:
    folder = Path(a.dir).resolve()
    if not folder.is_dir():
        raise CFError(f"Không thấy thư mục: {folder}")
    if a.create:
        run_wrangler(["pages", "project", "create", a.project, "--production-branch", a.branch], timeout=180)
    args = ["pages", "deploy", str(folder), "--project-name", a.project, "--branch", a.branch, "--commit-dirty=true"]
    out = run_wrangler(args, timeout=a.timeout)
    urls = re.findall(r"https://[^\s]+\.pages\.dev[^\s]*", out)
    data = {"project": a.project, "branch": a.branch, "url": urls[-1] if urls else None, "output": out}
    human = out
    if urls:
        human += f"\n\nURL: {urls[-1]}"
    emit(data, a.json, human)
    return 0


def cmd_workers_deploy(a) -> int:
    folder = Path(a.dir).resolve()
    if not folder.is_dir():
        raise CFError(f"Không thấy thư mục: {folder}")
    out = run_wrangler(["deploy"], cwd=str(folder), timeout=a.timeout)
    urls = re.findall(r"https://[^\s]+\.workers\.dev[^\s]*", out)
    data = {"dir": str(folder), "url": urls[-1] if urls else None, "output": out}
    human = out
    if urls:
        human += f"\n\nURL: {urls[-1]}"
    emit(data, a.json, human)
    return 0


def cmd_r2_buckets(a) -> int:
    aid = get_account_id(a.account)
    result = api("GET", f"/accounts/{aid}/r2/buckets")
    items = (result or {}).get("buckets", [])
    data = [{"name": b.get("name"), "creation_date": b.get("creation_date"), "location": b.get("location")} for b in items]
    emit(data, a.json, "\n".join(f"{b['name']}  {b.get('creation_date') or ''}  {b.get('location') or ''}" for b in data) or "Chưa có bucket R2.")
    return 0


def cmd_token_save(a) -> int:
    if not a.stdin:
        raise CFError("Chỉ hỗ trợ --stdin để tránh token lọt vào lịch sử lệnh.")
    token = sys.stdin.read().strip()
    path = save_token(token)
    verify = api("GET", "/user/tokens/verify")
    items = accounts()
    print(f"Đã lưu token vào {path} (không in giá trị).")
    print(f"Trạng thái token: {verify.get('status')}")
    if items:
        print("Accounts: " + ", ".join(f"{x.get('name')} ({x.get('id')})" for x in items))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Cloudflare API wrapper cho AI STV")
    ap.add_argument("--json", action="store_true", help="Xuất JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("accounts")
    p.set_defaults(func=cmd_accounts)

    p = sub.add_parser("zones")
    p.add_argument("--name")
    p.set_defaults(func=cmd_zones)

    dns = sub.add_parser("dns").add_subparsers(dest="dns_cmd", required=True)
    p = dns.add_parser("list")
    p.add_argument("--zone", required=True)
    p.set_defaults(func=cmd_dns_list)
    p = dns.add_parser("add")
    p.add_argument("--zone", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--ttl", type=int, default=1)
    p.add_argument("--proxied", action="store_true", default=None)
    p.set_defaults(func=cmd_dns_add)
    p = dns.add_parser("delete")
    p.add_argument("--zone", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_dns_delete)

    ai = sub.add_parser("ai").add_subparsers(dest="ai_cmd", required=True)
    p = ai.add_parser("models")
    p.add_argument("--account")
    p.add_argument("--task")
    p.add_argument("--search")
    p.set_defaults(func=cmd_ai_models)
    p = ai.add_parser("run")
    p.add_argument("model")
    p.add_argument("--account")
    p.add_argument("--prompt")
    p.add_argument("--input", help="JSON hoặc @file hoặc - để đọc stdin")
    p.add_argument("--out")
    p.add_argument("--timeout", type=int, default=180)
    p.set_defaults(func=cmd_ai_run)

    pages = sub.add_parser("pages").add_subparsers(dest="pages_cmd", required=True)
    p = pages.add_parser("projects")
    p.set_defaults(func=cmd_pages_projects)
    p = pages.add_parser("deploy")
    p.add_argument("dir")
    p.add_argument("--project", required=True)
    p.add_argument("--branch", default="main")
    p.add_argument("--create", action="store_true")
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_pages_deploy)

    workers = sub.add_parser("workers").add_subparsers(dest="workers_cmd", required=True)
    p = workers.add_parser("deploy")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_workers_deploy)

    r2 = sub.add_parser("r2").add_subparsers(dest="r2_cmd", required=True)
    p = r2.add_parser("buckets")
    p.add_argument("--account")
    p.set_defaults(func=cmd_r2_buckets)

    p = sub.add_parser("token-save")
    p.add_argument("--stdin", action="store_true")
    p.set_defaults(func=cmd_token_save)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except CFError as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
