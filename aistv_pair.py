#!/usr/bin/env python3
"""Ghép bot Telegram với chủ sở hữu — kiểu "device flow" của GitHub.

    python aistv_pair.py                  # in link, chờ bạn bấm Start
    python aistv_pair.py --timeout 300    # chờ lâu hơn (mặc định 180s)
    python aistv_pair.py --link-only      # chỉ in link rồi thoát
    python aistv_pair.py --json           # kết quả máy đọc được

Luồng hoạt động
---------------
1. Gọi getMe để biết username bot → in https://t.me/<bot>?start=<mã>.
2. Long-poll getUpdates, chờ đúng mã đó.
3. Lưu ALLOWED_USER_IDS vào ~/.config/aistv/config.env và .env của repo.
   Nhờ vậy lần chạy sau không phải nhập tay, và không mất khi clone lại repo.

Không bao giờ in token ra màn hình.
Mã thoát: 0 = xác nhận xong, 2 = hết thời gian chờ, 3 = bot đang chạy,
4 = thiếu/sai token, 130 = người dùng bỏ qua (Ctrl+C).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(os.getenv("AISTV_CONFIG_DIR") or (Path.home() / ".config" / "aistv"))
CONFIG_FILE = CONFIG_DIR / "config.env"
PROJECT_ENV = Path(__file__).resolve().parent / ".env"
API = "https://api.telegram.org/bot{token}/{method}"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def env_files() -> list[Path]:
    """Cùng thứ tự với bot: repo .env rồi tới config.env toàn cục."""
    files = [PROJECT_ENV, Path.cwd() / ".env", Path.home() / ".env"]
    stv = os.getenv("STV_HOME")
    if stv:
        files.append(Path(stv) / ".env")
    files.append(CONFIG_FILE)
    seen, out = set(), []
    for path in files:
        try:
            key = str(path.expanduser().resolve())
        except Exception:
            key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path.expanduser())
    return out


def load_env() -> None:
    """Nạp .env nhưng KHÔNG ghi đè biến môi trường đã có."""
    for path in env_files():
        try:
            if not path.is_file():
                continue
            for raw in path.read_text("utf-8", "replace").splitlines():
                line = raw.strip()
                if line.startswith("export "):
                    line = line[7:].lstrip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip()
                value = value.strip().strip("'\"")
                if name and value and name not in os.environ:
                    os.environ[name] = value
        except Exception:
            continue


def save_env(name: str, value: str) -> list[Path]:
    """Ghi biến vào .env của repo + config.env toàn cục (quyền 600)."""
    written: list[Path] = []
    for path in (PROJECT_ENV, CONFIG_FILE):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            lines = path.read_text("utf-8", "replace").splitlines() if path.is_file() else []
            out, done = [], False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("export "):
                    stripped = stripped[7:].lstrip()
                if stripped.startswith(name + "="):
                    if not done:
                        out.append(f"{name}={value}")
                        done = True
                    continue
                out.append(line)
            if not done:
                if out and out[-1].strip():
                    out.append("")
                out.append(f"{name}={value}")
            path.write_text("\n".join(out).rstrip() + "\n", "utf-8")
            try:
                path.chmod(0o600)
            except Exception:
                pass
            written.append(path)
        except Exception:
            continue
    if written:
        os.environ[name] = value
    return written


def token() -> str:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("AISTV_BOT_TOKEN", "").strip()
    )


def api(bot_token: str, method: str, timeout: float = 30, **params) -> dict:
    url = API.format(token=bot_token, method=method)
    data = urllib.parse.urlencode(params).encode() if params else None
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def die(msg: str, code: int) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def main() -> int:
    _utf8()
    load_env()

    parser = argparse.ArgumentParser(description="Chờ bạn xác nhận bot Telegram rồi lưu ALLOWED_USER_IDS.")
    parser.add_argument("--token", default="", help="Bot token (mặc định đọc từ .env / biến môi trường)")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("AISTV_PAIR_TIMEOUT", "180")),
                        help="Số giây chờ xác nhận (0 = chỉ in link, mặc định 180)")
    parser.add_argument("--code", default="", help="Mã xác nhận tự đặt (mặc định sinh ngẫu nhiên)")
    parser.add_argument("--link-only", action="store_true", help="Chỉ in link rồi thoát")
    parser.add_argument("--json", action="store_true", help="In kết quả dạng JSON")
    parser.add_argument("--save", action="store_true", default=True, help="Lưu ALLOWED_USER_IDS (mặc định bật)")
    args = parser.parse_args()

    bot_token = args.token.strip() or token()
    if not bot_token:
        die("✖ Thiếu TELEGRAM_BOT_TOKEN. Tạo bot với @BotFather rồi chạy lại.", 4)

    code = (args.code or "".join(secrets.choice(ALPHABET) for _ in range(6))).upper()

    try:
        me = api(bot_token, "getMe", timeout=20)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 404):
            die("✖ Token bot không hợp lệ (BotFather cho token khác?).", 4)
        die(f"✖ Telegram trả về HTTP {exc.code}. Thử lại sau.", 4)
    except Exception as exc:  # noqa: BLE001
        die(f"✖ Không gọi được Telegram: {type(exc).__name__}. Kiểm tra mạng rồi thử lại.", 4)

    if not me.get("ok"):
        die("✖ Telegram từ chối token bot.", 4)

    username = (me.get("result") or {}).get("username") or ""
    link = f"https://t.me/{username}?start={code}" if username else ""

    if args.json:
        print(json.dumps({"bot": username, "code": code, "link": link}, ensure_ascii=False))
    else:
        print(f"🤖 Bot: @{username}" if username else "🤖 Bot: (không có username)")
        if link:
            print(f"🔗 Mở link này hoặc nhắn /start {code} cho bot:\n   {link}")
        else:
            print(f"🔗 Nhắn /start {code} cho bot của bạn.")

    existing = os.getenv("ALLOWED_USER_IDS", "").strip()
    if args.link_only or args.timeout <= 0:
        return 0

    if not args.json:
        print(f"⏳ Đang chờ xác nhận… tối đa {args.timeout}s (Ctrl+C để bỏ qua)")

    deadline = time.monotonic() + max(1, args.timeout)
    offset = 0
    next_note = time.monotonic() + 15
    conflict = 0

    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        try:
            data = api(bot_token, "getUpdates", timeout=min(25, max(5, remaining)),
                       offset=offset, allowed_updates=json.dumps(["message"]))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            if exc.code == 409:
                conflict += 1
                if conflict >= 2:
                    msg = ("⚠ Bot đang chạy nên không nhận được tin nhắn mới.\n"
                           "  Dừng bot (Ctrl+C ở cửa sổ đang chạy) rồi chạy lại lệnh này,\n"
                           "  hoặc bỏ qua: AISTV_PAIR=0 bash run.sh")
                    if args.json:
                        print(json.dumps({"error": "conflict", "message": msg}, ensure_ascii=False))
                    else:
                        print(msg, file=sys.stderr)
                    return 3
                time.sleep(3)
                continue
            if exc.code in (401, 404):
                die("✖ Token bot không hợp lệ.", 4)
            time.sleep(3)
            continue
        except Exception:  # noqa: BLE001 — mạng chập chờn: chờ tiếp, không treo
            time.sleep(3)
            continue

        conflict = 0
        for upd in data.get("result") or []:
            offset = max(offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or {}
            sender = msg.get("from") or {}
            text = (msg.get("text") or "").strip()
            chat_id = str((msg.get("chat") or {}).get("id") or sender.get("id") or "")
            if not chat_id:
                continue
            norm = text.lower().lstrip("/")
            if not norm.startswith("start"):
                continue
            payload = norm[5:].strip() if len(norm) > 5 else ""
            if code.lower() not in payload:
                continue

            name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x).strip()
            handle = f"@{sender['username']}" if sender.get("username") else ""
            label = " ".join(x for x in (name, handle) if x).strip() or chat_id

            ids = [x.strip() for x in existing.split(",") if x.strip()]
            if chat_id not in ids:
                ids.append(chat_id)
            value = ",".join(ids)
            saved = save_env("ALLOWED_USER_IDS", value) if args.save else []

            if args.json:
                print(json.dumps({"ok": True, "user_id": chat_id, "name": label,
                                  "allowed": value, "saved": [str(p) for p in saved]},
                                 ensure_ascii=False))
            else:
                print(f"✅ Đã xác nhận: {label} (id {chat_id})")
                for path in saved:
                    print(f"   Đã lưu ALLOWED_USER_IDS vào {path}")
                if not saved:
                    print("   (không ghi được file — dùng biến ALLOWED_USER_IDS trong phiên này)")
            return 0

        now = time.monotonic()
        if not args.json and now >= next_note:
            print(f"   … vẫn đang chờ ({int(deadline - now)}s)")
            next_note = now + 15

    if args.json:
        print(json.dumps({"ok": False, "error": "timeout", "code": code,
                          "link": link}, ensure_ascii=False))
    else:
        print("⏱ Hết thời gian chờ — chưa nhận được xác nhận.")
        print("   Bot vẫn chạy được: người nhắn đầu tiên sẽ thành chủ bot.")
        if link:
            print(f"   Thử lại sau bằng: python aistv_pair.py   (link: {link})")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n↷ Bỏ qua bước xác nhận.", file=sys.stderr)
        raise SystemExit(130)
