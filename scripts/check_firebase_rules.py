#!/usr/bin/env python3
"""Kiểm tra Firebase RTDB đã khóa chưa: người lạ phải bị từ chối đọc.

Dùng sau khi deploy database.rules.json:

    python scripts/check_firebase_rules.py --url https://<db>.firebaseio.com
    AISTV_FIREBASE_SECRET=... python scripts/check_firebase_rules.py

Exit 0 = đã khóa (ẩn danh bị từ chối), 1 = còn mở, 2 = không kiểm tra được.
"""
import argparse
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def _urllib_status(url: str, timeout: int) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _curl_status(url: str, timeout: int) -> int:
    curl = shutil.which("curl")
    if not curl:
        return 0
    try:
        out = subprocess.run(
            [curl, "-s", "-o", os.devnull, "-m", str(timeout), "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        code = (out.stdout or "").strip()
        return int(code) if code.isdigit() else 0
    except Exception:
        return 0


def http_status(url: str, timeout: int = 15) -> int:
    code = _urllib_status(url, timeout)
    return code or _curl_status(url, timeout)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Kiểm tra Rules Firebase Realtime Database.")
    ap.add_argument("--url", default=(os.getenv("AISTV_FIREBASE_URL") or "").strip(),
                    help="URL DB (mặc định lấy AISTV_FIREBASE_URL)")
    ap.add_argument("--secret", default=(os.getenv("AISTV_FIREBASE_SECRET") or "").strip(),
                    help="Database secret (mặc định lấy AISTV_FIREBASE_SECRET)")
    ap.add_argument("--namespace", default=(os.getenv("AISTV_CLOUD_NS") or "aistv").strip())
    args = ap.parse_args()

    base = args.url.rstrip("/")
    if not base:
        print("Thiếu URL: đặt AISTV_FIREBASE_URL hoặc truyền --url.", file=sys.stderr)
        return 2

    ns = urllib.parse.quote(args.namespace.strip("/") or "aistv")
    anon_root = http_status(f"{base}/.json?shallow=true")
    anon_ns = http_status(f"{base}/{ns}.json?shallow=true")

    def show(label: str, code: int, ok_codes: tuple) -> None:
        state = "OK" if code in ok_codes else "FAIL"
        print(f"  {label:<28} HTTP {code or '---':<4} [{state}]")

    print("Firebase Rules check")
    print(f"  {'URL':<28} {base}")
    show("ẩn danh  /", anon_root, (401, 403))
    show(f"ẩn danh  /{args.namespace}", anon_ns, (401, 403))

    auth_ok = None
    if args.secret:
        url = (f"{base}/{ns}.json?shallow=true&auth="
               + urllib.parse.quote(args.secret))
        auth_ok = http_status(url)
        show(f"có auth  /{args.namespace}", auth_ok, (200,))

    if anon_root == 0 or anon_ns == 0:
        print("KẾT LUẬN: không kết nối được tới Firebase.")
        return 2
    if anon_root == 200 or anon_ns == 200:
        print("KẾT LUẬN: DB còn mở — người lạ vẫn đọc được. Hãy deploy database.rules.json.")
        return 1
    if args.secret and auth_ok != 200:
        print("KẾT LUẬN: đã khóa ẩn danh, nhưng auth chưa đọc được (sai secret hoặc chưa cấu hình).")
        return 2
    print("KẾT LUẬN: Rules đã khóa — chỉ client có auth đọc/ghi được.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
