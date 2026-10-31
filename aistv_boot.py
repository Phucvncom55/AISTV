#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_boot.py — bí mật khởi động cho máy trắng (Firebase, blob mã hoá).

Mục đích: `bootstrap.sh` trên máy mới KHÔNG hỏi gì, chỉ cần một lệnh curl.
Blob nhỏ nằm ở `aistv/boot.json` chứa đúng hai giá trị cần để dựng lại bot:

    TELEGRAM_BOT_TOKEN  → mở kho cấu hình mã hoá (17 mục) trong aistv_config
                          (GITHUB_TOKEN lấy từ kho, nên đổi PAT chỉ cần /key
                          một lần — blob không bao giờ giữ token cũ)

Khoá mã hoá được ghép từ hai hằng số dưới đây (bản sao nằm trong
`bootstrap.sh`). Khoá đó nằm trong file công khai, nên nói thẳng:

    • Nó chỉ chống công cụ quét token tự động và người xem qua loa.
    • Người đọc kỹ `bootstrap.sh` vẫn giải mã được. Muốn chống thật thì
      phải nhập một bí mật (Colab Secrets / pairing) — không có cách nào
      vừa "không nhập gì" vừa bí mật tuyệt đối.

Dùng:
    python3 aistv_boot.py status     # blob có? giải mã được? mấy mục?
    python3 aistv_boot.py push       # đẩy token hiện tại lên Firebase
    python3 aistv_boot.py pull       # kiểm tra + in TÊN mục (không in giá trị)
    python3 aistv_boot.py rotate     # đổi khoá (in khoá mới để dán vào bootstrap.sh)

Không bao giờ in token ra stdout/stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import aistv_config as cfg  # noqa: E402

BOOT_PATH = "aistv/boot.json"
BOOT_KEY_PREFIX = "aistv-boot|"
BOOT_KEY_PART = "7f2c9d14b6e8a305"      # PHẢI giống bootstrap.sh
BOOT_KEYS = ("TELEGRAM_BOT_TOKEN",)
USER_AGENT = "AISTV-boot/1"


def boot_key() -> str:
    """Chuỗi dùng làm khoá mã hoá blob khởi động."""
    return BOOT_KEY_PREFIX + BOOT_KEY_PART


def boot_base(values: dict = None) -> str:
    values = values or {}
    return ((os.getenv("AISTV_BOOT_URL") or "").strip()
            or (values.get("AISTV_BOOT_URL") or "").strip()
            or (os.getenv("AISTV_FIREBASE_URL") or "").strip()
            or (values.get("AISTV_FIREBASE_URL") or "").strip()
            or cfg.VAULT_DEFAULT_URL).rstrip("/")


def boot_endpoint(values: dict = None) -> str:
    base = boot_base(values)
    return f"{base}/{BOOT_PATH}" if base else ""


def boot_encrypt(data: dict) -> str:
    return cfg.vault_encrypt(data, boot_key())


def boot_decrypt(blob: str) -> dict:
    data = cfg.vault_decrypt(blob, boot_key())
    return data if isinstance(data, dict) else {}


def _get(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    payload = json.loads(raw) if raw.strip() else None
    return payload if isinstance(payload, dict) else {}


def boot_read(values: dict = None, log=None) -> dict:
    """Đọc + giải mã blob khởi động. Lỗi gì cũng trả {} (không chặn máy mới)."""
    url = boot_endpoint(values)
    if not url:
        return {}
    try:
        payload = _get(url)
    except Exception:
        return {}
    if not payload.get("blob"):
        return {}
    try:
        data = boot_decrypt(str(payload["blob"]))
    except Exception:
        if log:
            log("[boot] Blob khởi động không giải mã được (đã đổi khoá?) — bỏ qua.")
        return {}
    out = {k: str(v).strip() for k, v in data.items() if str(v or "").strip()}
    if log and out:
        log(f"[boot] Khôi phục {len(out)} mục khởi động từ Firebase.")
    return out


def boot_push(data: dict = None, bot_token: str = "", log=None) -> bool:
    """Mã hoá 2 giá trị cần thiết rồi PUT lên Firebase. Không in giá trị."""
    data = dict(data or {})
    values, _src = cfg.read_files()
    merged = dict(values)
    merged.update({k: v for k, v in data.items() if v})

    token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not cfg.valid_bot_token(token):
        token = cfg.vault_token(merged)
    if not cfg.valid_bot_token(token):
        if log:
            log("[boot] Thiếu TELEGRAM_BOT_TOKEN hợp lệ — không đẩy blob.")
        return False

    url = boot_endpoint(merged)
    if not url:
        return False
    blob = boot_encrypt({"TELEGRAM_BOT_TOKEN": token})
    body = json.dumps({"v": 1, "at": int(time.time()), "blob": blob}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as e:
        if log:
            log(f"[boot] Không ghi được blob khởi động: {type(e).__name__}.")
        return False
    if log:
        log("[boot] Đã cập nhật blob khởi động (1 mục, mã hoá) — máy mới không phải nhập gì.")
    return True


def cmd_status(quiet: bool = False) -> int:
    values, _src = cfg.read_files()
    url = boot_endpoint(values)
    try:
        payload = _get(url)
    except Exception as e:
        print(f"Blob khởi động: KHÔNG đọc được ({type(e).__name__}) — {url}")
        return 1
    if not payload.get("blob"):
        print(f"Blob khởi động: chưa có dữ liệu — {url}")
        return 1
    try:
        data = boot_decrypt(str(payload["blob"]))
    except Exception:
        print("Blob khởi động: có dữ liệu nhưng KHÔNG giải mã được (khoá đã đổi?).")
        return 1
    names = ", ".join(sorted(data)) or "(rỗng)"
    age = ""
    at = payload.get("at")
    if isinstance(at, (int, float)) and at > 0:
        age = time.strftime(" · cập nhật %d/%m/%Y %H:%M", time.localtime(at))
    print(f"Blob khởi động: OK · {len(data)} mục{age}")
    if not quiet:
        print(f"  mục      : {names}")
        print(f"  endpoint : {url}")
        print("  khoá     : nằm trong bootstrap.sh (công khai — chỉ chống quét tự động)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bí mật khởi động AI STV (Firebase)")
    parser.add_argument("action", nargs="?", default="status",
                        choices=("status", "push", "pull", "rotate"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "status":
        return cmd_status(args.quiet)
    if args.action == "push":
        return 0 if boot_push(log=None if args.quiet else print) else 1
    if args.action == "pull":
        data = boot_read(log=None if args.quiet else print)
        if not data:
            print("Không đọc được blob khởi động.", file=sys.stderr)
            return 1
        print("Blob khởi động giải mã được: " + ", ".join(sorted(data)))
        return 0
    if args.action == "rotate":
        print("Đổi khoá: sửa BOOT_KEY_PART trong aistv_boot.py VÀ bootstrap.sh "
              "thành cùng một chuỗi mới, rồi chạy `push`.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
