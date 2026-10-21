#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_browser.py — Điều khiển trình duyệt thật bằng Playwright.

Dùng để: đăng nhập web, bấm nút, điền form, chụp màn hình, lấy HTML.
Phiên đăng nhập được lưu trong profile nên chỉ cần login 1 lần.

Cài
  python aistv_browser.py --install      # pip install playwright + tải Chromium

Dùng nhanh
  python aistv_browser.py --url https://example.com --shot page.png
  python aistv_browser.py --url https://facebook.com --open      # mở có giao diện để login
  python aistv_browser.py steps.json                             # chạy kịch bản

steps.json
  [
    {"goto": "https://studio.youtube.com"},
    {"fill": ["input[name=identifier]", "me@example.com"]},
    {"click": "button[type=submit]"},
    {"wait": 3000},
    {"shot": "studio.png"},
    {"text": "h1"}
  ]
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

HOME = Path(os.getenv("STV_HOME") or (Path.home() / "stv_agent"))
PROFILE = Path(os.getenv("AISTV_BROWSER_PROFILE") or (HOME / "browser" / "profile"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class BrowserError(RuntimeError):
    pass


def _pw():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception:
        raise BrowserError(
            "chưa có playwright. Cài: python aistv_browser.py --install")


def check() -> dict:
    info = {"playwright": False, "chromium": False}
    try:
        import playwright  # noqa
        info["playwright"] = True
    except Exception:
        return info
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            info["chromium"] = Path(p.chromium.executable_path).exists()
    except Exception:
        pass
    return info


def _context(p, headless: bool, slow: int = 0):
    PROFILE.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, slow_mo=slow,
        viewport={"width": 1440, "height": 900},
        user_agent=UA, locale="vi-VN",
        args=["--disable-blink-features=AutomationControlled"])


def _run_steps(page, steps: list, outdir: Path) -> list:
    log = []
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            continue
        try:
            if "goto" in s:
                page.goto(s["goto"], wait_until=s.get("wait_until", "domcontentloaded"),
                          timeout=s.get("timeout", 60000))
                log.append(f"{i}. goto {s['goto']}")
            elif "fill" in s:
                sel, val = s["fill"]
                page.fill(sel, str(val), timeout=s.get("timeout", 30000))
                log.append(f"{i}. fill {sel}")
            elif "click" in s:
                page.click(s["click"], timeout=s.get("timeout", 30000))
                log.append(f"{i}. click {s['click']}")
            elif "press" in s:
                page.keyboard.press(s["press"])
                log.append(f"{i}. press {s['press']}")
            elif "wait" in s:
                page.wait_for_timeout(int(s["wait"]))
                log.append(f"{i}. wait {s['wait']}ms")
            elif "shot" in s:
                path = outdir / s["shot"]
                page.screenshot(path=str(path), full_page=bool(s.get("full")))
                log.append(f"{i}. shot {path}")
            elif "text" in s:
                txt = page.inner_text(s["text"], timeout=s.get("timeout", 15000))
                log.append(f"{i}. text {s['text']}: {txt[:300]}")
            elif "html" in s:
                path = outdir / s["html"]
                path.write_text(page.content(), "utf-8")
                log.append(f"{i}. html {path}")
        except Exception as e:
            log.append(f"{i}. LỖI {list(s)[0]}: {e}")
            if not s.get("optional"):
                break
    return log


def cmd_install(args) -> int:
    print("· pip install playwright")
    p = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "playwright"])
    if p.returncode != 0:
        print("pip lỗi — thử: pip install playwright", file=sys.stderr)
        return 1
    print("· playwright install chromium")
    p = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    if p.returncode != 0:
        print("Tải Chromium lỗi. Trên Debian cần thêm:\n"
              "  sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 "
              "libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 "
              "libxfixes3 libxrandr2 libgbm1 libasound2", file=sys.stderr)
        return 1
    print("Xong. Kiểm tra: python aistv_browser.py --check")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Playwright cho AI STV")
    ap.add_argument("steps", nargs="?", help="file JSON kịch bản")
    ap.add_argument("--url", help="mở 1 URL")
    ap.add_argument("--shot", help="chụp màn hình ra file này")
    ap.add_argument("--full", action="store_true", help="chụp toàn trang")
    ap.add_argument("--html", help="lưu HTML ra file")
    ap.add_argument("--text", help="lấy text của selector")
    ap.add_argument("--open", action="store_true", help="hiện trình duyệt (để login tay)")
    ap.add_argument("--outdir", default=".", help="thư mục xuất ảnh/html")
    ap.add_argument("--slow", type=int, default=0, help="slow_mo ms")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.check:
        info = check()
        if args.json:
            print(json.dumps(info, ensure_ascii=False))
        else:
            for k, v in info.items():
                print(f"{'OK ' if v else '---'} {k}")
        return 0 if all(info.values()) else 1
    if args.install:
        return cmd_install(args)

    steps = []
    if args.steps:
        steps = json.loads(Path(args.steps).read_text("utf-8"))
    elif args.url:
        steps.append({"goto": args.url})
        if args.text:
            steps.append({"text": args.text})
        if args.html:
            steps.append({"html": args.html})
        if args.shot:
            steps.append({"shot": args.shot, "full": args.full})
        if not (args.shot or args.html or args.text):
            steps.append({"wait": 1500})
    else:
        ap.print_help()
        return 2

    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        sync_playwright = _pw()
    except BrowserError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        ctx = _context(p, headless=not args.open, slow=args.slow)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log = []
        try:
            log = _run_steps(page, steps, outdir)
        finally:
            if args.open and not args.steps:
                try:
                    input("Nhấn Enter để đóng trình duyệt…")
                except EOFError:
                    pass
            ctx.close()
    if args.json:
        print(json.dumps({"ok": True, "log": log}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(log))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
