#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_vm.py — Tạo máy ảo Windows (GitHub Actions runner) cho Integration Test.

Quy trình (dùng PAT GitHub của tài khoản sẽ chạy máy ảo + Tailscale auth key):
  1. Fork repo AISTV sang tài khoản đó nếu chưa có.
  2. Bật Actions trên repo (fork của repo công khai mặc định bị tắt workflow).
  3. Ghi secrets TAILSCALE_AUTHKEY / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
     (mã hoá sealed box đúng chuẩn GitHub Actions).
  4. Kích hoạt workflow `windows-integration-test.yml`; workflow tự gửi thông tin
     đăng nhập (IP Tailscale, user, mật khẩu) qua Telegram DM.

PAT cần scope: `repo` + `workflow` (classic) hoặc Actions/Contents/Secrets write (fine-grained).
PyNaCl bắt buộc để mã hoá secret: pip install pynacl

CLI:
  python3 aistv_vm.py create --pat ghp_xxx --key tskey-auth-xxx \
      --bot-token 123:abc --chat-id 456 [--windows windows-2025] [--minutes 120]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

GH_API = "https://api.github.com"
SOURCE_REPO = (os.getenv("AISTV_VM_SOURCE_REPO") or "Phucvncom55/AISTV").strip()
REPO_NAME = (os.getenv("AISTV_VM_REPO_NAME") or "AISTV").strip()
WORKFLOW_FILE = "windows-integration-test.yml"
WINDOWS_VERSIONS = ("windows-latest", "windows-2022", "windows-2025")
MIN_MINUTES, MAX_MINUTES = 60, 360
DEFAULT_MINUTES = 360


class VMError(RuntimeError):
    """Lỗi có thông báo tiếng Việt, hiển thị thẳng cho người dùng."""


def mask_value(value: str) -> str:
    """Che giá trị bí mật khi hiển thị: giữ 4 ký tự đầu và 2 ký tự cuối."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-2:]}"


def normalize_windows(value: str) -> str:
    """Chuẩn hoá tên runner Windows; rỗng → windows-latest."""
    win = (value or "").strip().lower() or "windows-latest"
    if win not in WINDOWS_VERSIONS:
        raise VMError(f"Windows runner không hợp lệ: {win}. "
                      f"Chọn: {', '.join(WINDOWS_VERSIONS)}")
    return win


def clamp_minutes(value) -> int:
    """Ép thời gian chạy về khoảng 60–360 phút; rỗng → 360."""
    if value in (None, ""):
        return DEFAULT_MINUTES
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise VMError(f"Thời gian chạy phải là số phút ({MIN_MINUTES}–{MAX_MINUTES}), "
                      f"nhận được: {value!r}")
    return max(MIN_MINUTES, min(MAX_MINUTES, minutes))


def validate_credentials(pat: str, tailscale_authkey: str) -> tuple:
    """Kiểm tra hình dạng PAT + Tailscale key trước khi gọi GitHub."""
    pat = (pat or "").strip()
    key = (tailscale_authkey or "").strip()
    if not pat or len(pat) < 20 or any(ch.isspace() for ch in pat):
        raise VMError("PAT GitHub không hợp lệ (cần chuỗi ghp_… hoặc github_pat_…, không có dấu cách).")
    if not key or any(ch.isspace() for ch in key):
        raise VMError("Tailscale auth key không hợp lệ (cần chuỗi tskey-…, không có dấu cách).")
    return pat, key


def _api(method: str, path: str, token: str, payload: Optional[dict] = None,
         timeout: int = 30) -> tuple:
    """Gọi GitHub REST API, trả (status, body). Không ném lỗi HTTP."""
    url = path if path.startswith("http") else GH_API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "AISTV-bot")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except Exception:
            body = {"message": raw[:300]}
        return e.code, body


def whoami(pat: str) -> str:
    """Tên tài khoản của PAT (dùng để chọn repo đích)."""
    code, body = _api("GET", "/user", pat, timeout=20)
    if code == 401:
        raise VMError("GitHub từ chối PAT (401) — token sai hoặc đã bị thu hồi.")
    if code != 200:
        raise VMError(f"Không gọi được GitHub API (HTTP {code}): {body.get('message', '')}")
    login = str(body.get("login") or "").strip()
    if not login:
        raise VMError("GitHub không trả về tên tài khoản — kiểm tra lại PAT.")
    return login


def _repo_info(login: str, pat: str) -> Optional[dict]:
    code, body = _api("GET", f"/repos/{login}/{REPO_NAME}", pat, timeout=20)
    return body if code == 200 else None


def ensure_repo(login: str, pat: str) -> str:
    """Đảm bảo tài khoản có repo chứa workflow. Trả 'existing' hoặc 'forked'."""
    if _repo_info(login, pat):
        return "existing"
    code, body = _api("POST", f"/repos/{SOURCE_REPO}/forks", pat, {}, timeout=30)
    if code not in (200, 201, 202):
        raise VMError(f"Không fork được {SOURCE_REPO} (HTTP {code}): {body.get('message', '')}")
    for _ in range(20):                       # fork chạy nền — chờ tối đa ~60 giây
        time.sleep(3)
        if _repo_info(login, pat):
            return "forked"
    raise VMError("Fork đang được GitHub tạo — thử lại sau khoảng 1 phút.")


def sync_fork(login: str, pat: str, branch: str = "main") -> str:
    """Đồng bộ fork đã có với repo nguồn trước khi chạy workflow.

    Fork cũ vẫn giữ workflow lỗi thời, nên phải merge-upstream mỗi lần tạo máy.
    Trả: 'updated' | 'up-to-date' | 'diverged' | 'skipped'.
    """
    code, body = _api("POST", f"/repos/{login}/{REPO_NAME}/merge-upstream", pat,
                      {"branch": branch}, timeout=30)
    if code == 200:
        return "up-to-date" if body.get("merge_type") == "none" else "updated"
    if code == 409 or "conflict" in str(body.get("message") or "").lower():
        return "diverged"
    return "skipped"


def enable_actions(login: str, pat: str) -> None:
    """Bật Actions (fork của repo công khai mặc định bị tắt workflow)."""
    _api("PUT", f"/repos/{login}/{REPO_NAME}/actions/permissions", pat,
         {"enabled": True}, timeout=20)
    # Không kiểm tra mã lỗi: repo thường đã bật sẵn; PAT thiếu quyền admin thì
    # bước dispatch sẽ báo lỗi rõ ràng hơn.


def seal_secret(public_key_b64: str, value: str) -> str:
    """Mã hoá secret theo chuẩn GitHub Actions (libsodium sealed box)."""
    try:
        from nacl.public import PublicKey, SealedBox
    except Exception as e:
        raise VMError("Thiếu thư viện PyNaCl — chạy: pip install pynacl") from e
    box = SealedBox(PublicKey(base64.b64decode(public_key_b64)))
    return base64.b64encode(box.encrypt(value.encode("utf-8"))).decode("ascii")


def set_secret(login: str, pat: str, name: str, value: str,
               public_key: Optional[dict] = None) -> None:
    """Ghi một Repository Secret (bỏ qua nếu giá trị rỗng)."""
    if not str(value or "").strip():
        return
    pk = public_key
    if not pk:
        code, pk = _api("GET", f"/repos/{login}/{REPO_NAME}/actions/secrets/public-key",
                        pat, timeout=20)
        if code != 200:
            raise VMError(f"Không lấy được public key của repo (HTTP {code}) — "
                          "PAT cần quyền admin/secrets.")
    encrypted = seal_secret(pk["key"], str(value))
    code, body = _api("PUT", f"/repos/{login}/{REPO_NAME}/actions/secrets/{name}", pat,
                      {"encrypted_value": encrypted, "key_id": pk["key_id"]}, timeout=20)
    if code not in (201, 204):
        raise VMError(f"Ghi secret {name} thất bại (HTTP {code}): {body.get('message', '')}")


def dispatch_workflow(login: str, pat: str, windows: str, minutes: int,
                      ref: str = "main") -> None:
    """Kích hoạt workflow_dispatch với tham số runner + thời gian chạy."""
    code, body = _api(
        "POST", f"/repos/{login}/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}/dispatches", pat,
        {"ref": ref, "inputs": {"windows_version": windows, "timeout_minutes": str(minutes)}},
        timeout=30)
    if code in (201, 204):
        return
    if code == 404:
        raise VMError(f"Repo {login}/{REPO_NAME} chưa có workflow {WORKFLOW_FILE} trên nhánh "
                      f"{ref} — hãy fork AISTV bản mới nhất rồi thử lại.")
    if code in (403, 422):
        raise VMError("PAT thiếu quyền chạy workflow (classic PAT cần scope `workflow`; "
                      "fine-grained PAT cần quyền Actions: write).")
    raise VMError(f"Kích hoạt workflow thất bại (HTTP {code}): {body.get('message', '')}")


def latest_run_url(login: str, pat: str) -> str:
    """URL của lần chạy mới nhất của workflow (rỗng nếu chưa thấy)."""
    for _ in range(10):
        time.sleep(3)
        code, body = _api("GET", f"/repos/{login}/{REPO_NAME}/actions/runs?per_page=5",
                          pat, timeout=20)
        if code != 200:
            continue
        for run in body.get("workflow_runs") or []:
            if str(run.get("path") or "").endswith(WORKFLOW_FILE):
                return str(run.get("html_url") or "")
    return ""


def create_vm(pat: str, tailscale_authkey: str, telegram_bot_token: str = "",
              telegram_chat_id="", windows_version: str = "", timeout_minutes=None) -> dict:
    """Tạo máy ảo trên tài khoản của PAT; trả dict mô tả kết quả.

    Thông tin đăng nhập KHÔNG đi qua hàm này — workflow tự gửi qua Telegram DM.
    """
    pat, key = validate_credentials(pat, tailscale_authkey)
    windows = normalize_windows(windows_version)
    minutes = clamp_minutes(timeout_minutes)

    login = whoami(pat)
    repo_state = ensure_repo(login, pat)
    info = _repo_info(login, pat) or {}
    ref = str(info.get("default_branch") or "main")
    sync = sync_fork(login, pat, ref) if repo_state == "existing" else "skipped"
    enable_actions(login, pat)

    code, pk = _api("GET", f"/repos/{login}/{REPO_NAME}/actions/secrets/public-key",
                    pat, timeout=20)
    if code != 200:
        raise VMError(f"Không lấy được public key của {login}/{REPO_NAME} (HTTP {code}).")
    set_secret(login, pat, "TAILSCALE_AUTHKEY", key, pk)
    set_secret(login, pat, "TELEGRAM_BOT_TOKEN", telegram_bot_token, pk)
    set_secret(login, pat, "TELEGRAM_CHAT_ID", str(telegram_chat_id or ""), pk)

    dispatch_workflow(login, pat, windows, minutes, ref)
    run_url = latest_run_url(login, pat)

    return {
        "login": login,
        "repo": f"{login}/{REPO_NAME}",
        "repo_state": repo_state,
        "sync": sync,
        "windows": windows,
        "minutes": minutes,
        "run_url": run_url,
        "workflow_url": f"https://github.com/{login}/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}",
    }


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Tạo máy ảo Windows Integration Test qua GitHub Actions.")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("create", help="fork (nếu cần) + ghi secrets + kích hoạt workflow")
    p.add_argument("--pat", required=True, help="GitHub PAT của tài khoản sẽ chạy máy ảo")
    p.add_argument("--key", required=True, help="Tailscale auth key (tag:vm-user)")
    p.add_argument("--bot-token", default="", help="Telegram bot token để workflow gửi DM")
    p.add_argument("--chat-id", default="", help="Telegram chat id nhận thông tin đăng nhập")
    p.add_argument("--windows", default="", help="windows-latest | windows-2022 | windows-2025")
    p.add_argument("--minutes", default="", help=f"thời gian chạy {MIN_MINUTES}–{MAX_MINUTES} phút")
    args = parser.parse_args(argv)
    if args.cmd != "create":
        parser.print_help()
        return 2
    try:
        result = create_vm(args.pat, args.key, args.bot_token, args.chat_id,
                           args.windows, args.minutes)
    except VMError as e:
        print(f"LỖI: {e}")
        return 1
    except Exception as e:
        print(f"LỖI không mong đợi: {e}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
