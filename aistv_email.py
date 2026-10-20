# -*- coding: utf-8 -*-
"""Kết nối email IMAP/SMTP cho AI STV — chỉ dùng thư viện chuẩn.

Cấu hình (ưu tiên từ trên xuống):
  1. Biến môi trường / Colab Secrets:
       AISTV_EMAIL_ADDRESS      địa chỉ email (vd: ban@gmail.com)
       AISTV_EMAIL_PASSWORD     mật khẩu ứng dụng (app password), KHÔNG phải mật khẩu đăng nhập
       AISTV_EMAIL_IMAP_HOST    tuỳ chọn — mặc định tự nhận theo tên miền
       AISTV_EMAIL_IMAP_PORT    tuỳ chọn (mặc định 993)
       AISTV_EMAIL_SMTP_HOST    tuỳ chọn
       AISTV_EMAIL_SMTP_PORT    tuỳ chọn (mặc định 587)
  2. File bí mật <STV_HOME>/.secrets/email.json (do lệnh /email setup tạo, chmod 600).

Dùng như CLI (agent có thể gọi):
  python3 aistv_email.py status
  python3 aistv_email.py inbox -n 8 [--unread]
  python3 aistv_email.py read <uid>
  python3 aistv_email.py send --to x@y.z --subject "..." --body "..."
  python3 aistv_email.py test
"""

from __future__ import annotations

import argparse
import html as _html
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Optional

DOMAIN_HOSTS = {
    "gmail.com": ("imap.gmail.com", 993, True, "smtp.gmail.com", 587, False),
    "googlemail.com": ("imap.gmail.com", 993, True, "smtp.gmail.com", 587, False),
    "outlook.com": ("outlook.office365.com", 993, True, "smtp-mail.outlook.com", 587, False),
    "hotmail.com": ("outlook.office365.com", 993, True, "smtp-mail.outlook.com", 587, False),
    "live.com": ("outlook.office365.com", 993, True, "smtp-mail.outlook.com", 587, False),
    "msn.com": ("outlook.office365.com", 993, True, "smtp-mail.outlook.com", 587, False),
    "yahoo.com": ("imap.mail.yahoo.com", 993, True, "smtp.mail.yahoo.com", 587, False),
    "icloud.com": ("imap.mail.me.com", 993, True, "smtp.mail.me.com", 587, False),
    "me.com": ("imap.mail.me.com", 993, True, "smtp.mail.me.com", 587, False),
    "zoho.com": ("imap.zoho.com", 993, True, "smtp.zoho.com", 587, False),
    "gmx.com": ("imap.gmx.com", 993, True, "mail.gmx.com", 587, False),
}

HOME: Optional[Path] = None
CONFIG_FILE: Optional[Path] = None
_CACHE: dict = {"cfg": None, "at": 0.0}
_TTL = 60.0

HELP = (
    "📧 <b>Email</b>\n"
    "Kết nối hộp thư để đọc và gửi email ngay trong bot.\n\n"
    "<b>Cách 1 — Colab Secrets (khuyến nghị)</b>\n"
    "Thêm 2 secret rồi bật Notebook access:\n"
    "• <code>AISTV_EMAIL_ADDRESS</code> — địa chỉ email\n"
    "• <code>AISTV_EMAIL_PASSWORD</code> — <b>mật khẩu ứng dụng</b> (app password)\n\n"
    "<b>Cách 2 — trong chat</b>\n"
    "<code>/email setup ban@gmail.com mat-khau-ung-dung</code>\n"
    "Tin nhắn chứa mật khẩu sẽ được bot cố gắng xoá.\n\n"
    "<b>Lệnh</b>\n"
    "/email — trạng thái · /email test — kiểm tra đăng nhập\n"
    "/email inbox [n] — hộp thư · /email unread [n] — chỉ thư chưa đọc\n"
    "/email read &lt;số|uid&gt; — đọc thư\n"
    "/email send a@b.c | Tiêu đề | Nội dung — gửi thư\n"
    "/email reset — xoá cấu hình đã lưu\n\n"
    "Gmail: bật xác thực 2 bước → tạo <b>App Password</b> 16 ký tự.\n"
    "Outlook/Yahoo: dùng app password tương tự nếu bật 2FA."
)


class EmailError(RuntimeError):
    pass


def configure(home) -> None:
    global HOME, CONFIG_FILE
    HOME = Path(home)
    CONFIG_FILE = HOME / ".secrets" / "email.json"
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.parent.chmod(0o700)
    except Exception:
        pass
    _CACHE.update(cfg=None, at=0.0)


def _secret(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        try:
            from google.colab import userdata
            val = (userdata.get(name) or "").strip()
        except Exception:
            val = ""
    return val


def get_secret(name: str) -> str:
    """Đọc secret từ env hoặc Colab Secrets (dùng cho cảnh báo ghi đè)."""
    return _secret(name)


def _file_cfg() -> dict:
    if CONFIG_FILE is None:
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load(force: bool = False) -> dict:
    """Trả về cấu hình email đã chuẩn hoá (không bao giờ in mật khẩu)."""
    if not force and _CACHE["cfg"] is not None and (time.time() - _CACHE["at"]) < _TTL:
        return dict(_CACHE["cfg"])
    f = _file_cfg()
    address = (_secret("AISTV_EMAIL_ADDRESS") or _secret("EMAIL_ADDRESS")
               or str(f.get("address") or "")).strip()
    password = (_secret("AISTV_EMAIL_PASSWORD") or _secret("EMAIL_APP_PASSWORD")
                or str(f.get("password") or "")).strip()
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    hosts = DOMAIN_HOSTS.get(domain, ("", 993, True, "", 587, False))
    cfg = {
        "address": address,
        "password": password,
        "imap_host": (_secret("AISTV_EMAIL_IMAP_HOST") or str(f.get("imap_host") or "") or hosts[0]).strip(),
        "imap_port": int(_secret("AISTV_EMAIL_IMAP_PORT") or f.get("imap_port") or hosts[1] or 993),
        "imap_ssl": bool(f.get("imap_ssl", hosts[2])),
        "smtp_host": (_secret("AISTV_EMAIL_SMTP_HOST") or str(f.get("smtp_host") or "") or hosts[3]).strip(),
        "smtp_port": int(_secret("AISTV_EMAIL_SMTP_PORT") or f.get("smtp_port") or hosts[4] or 587),
        "smtp_ssl": bool(f.get("smtp_ssl", hosts[5])),
        "domain": domain,
    }
    _CACHE.update(cfg=cfg, at=time.time())
    return dict(cfg)


def ready() -> bool:
    cfg = load()
    return bool(cfg["address"] and cfg["password"] and cfg["imap_host"] and cfg["smtp_host"])


def password() -> str:
    return load().get("password", "")


def save(address: str, pw: str, **extra) -> dict:
    if CONFIG_FILE is None:
        raise EmailError("Chưa khởi tạo thư mục cấu hình.")
    address = (address or "").strip()
    if "@" not in address:
        raise EmailError("Địa chỉ email không hợp lệ.")
    data = {k: v for k, v in _file_cfg().items()}
    data.update({"address": address, "password": (pw or "").strip()})
    data.update({k: v for k, v in extra.items() if v not in (None, "")})
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except Exception:
        pass
    _CACHE.update(cfg=None, at=0.0)
    return load(force=True)


def clear() -> bool:
    try:
        if CONFIG_FILE and CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            _CACHE.update(cfg=None, at=0.0)
            return True
    except Exception:
        pass
    return False


def _friendly(e: Exception) -> str:
    s = str(e)
    if isinstance(e, imaplib.IMAP4.error) or "AUTHENTICATIONFAILED" in s.upper():
        if "application-specific password" in s.lower() or "invalid credentials" in s.lower():
            return ("Đăng nhập thất bại — hãy dùng mật khẩu ứng dụng (App Password), "
                    "không phải mật khẩu thường.")
        return "Đăng nhập thất bại — kiểm tra địa chỉ email và mật khẩu ứng dụng."
    if isinstance(e, (TimeoutError, OSError)):
        return f"Không kết nối được máy chủ email ({s or 'timeout'})."
    return s or e.__class__.__name__


def _imap(cfg: dict):
    missing = [label for key, label in (("address", "địa chỉ email"),
                                        ("password", "mật khẩu ứng dụng"),
                                        ("imap_host", "IMAP host")) if not cfg.get(key)]
    if missing:
        raise EmailError("Thiếu " + ", ".join(missing) + " — đặt bằng /email setup.")
    try:
        if cfg.get("imap_ssl", True):
            conn = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"],
                                     ssl_context=ssl.create_default_context(), timeout=25)
        else:
            conn = imaplib.IMAP4(cfg["imap_host"], cfg["imap_port"], timeout=25)
        conn.login(cfg["address"], cfg["password"])
        return conn
    except Exception as e:
        raise EmailError(_friendly(e)) from e


def _decode(value) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _clean(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return _clean(_html.unescape(raw))


def list_messages(limit: int = 10, unread: bool = False) -> list:
    cfg = load()
    conn = _imap(cfg)
    try:
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise EmailError("Không mở được hộp thư INBOX.")
        typ, data = conn.uid("search", None, "UNSEEN" if unread else "ALL")
        if typ != "OK":
            raise EmailError("Không tìm được thư.")
        uids = (data[0] or b"").split()
        picked = list(reversed(uids[-max(1, min(limit, 50)):]))
        out = []
        for uid in picked:
            typ, rows = conn.uid(
                "fetch", uid,
                "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK":
                continue
            meta = b""
            flags = b""
            for row in rows or []:
                if isinstance(row, tuple):
                    flags += row[0] or b""
                    meta += row[1] or b""
            msg = message_from_bytes(meta, policy=policy.default)
            out.append({
                "uid": uid.decode("ascii", "ignore"),
                "from": _decode(msg.get("From")),
                "subject": _decode(msg.get("Subject")) or "(không có tiêu đề)",
                "date": _decode(msg.get("Date")),
                "unread": b"\\seen" not in flags.lower(),
            })
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def read_message(uid: str, max_chars: int = 6000) -> dict:
    cfg = load()
    conn = _imap(cfg)
    try:
        typ, _ = conn.select("INBOX", readonly=False)
        if typ != "OK":
            raise EmailError("Không mở được hộp thư INBOX.")
        typ, rows = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
        if typ != "OK":
            raise EmailError(f"Không đọc được thư uid {uid}.")
        raw = b""
        for row in rows or []:
            if isinstance(row, tuple):
                raw += row[1] or b""
        if not raw:
            raise EmailError(f"Không tìm thấy thư uid {uid}.")
        msg = message_from_bytes(raw, policy=policy.default)
        body, attachments = "", []
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                name = part.get_filename()
                if name:
                    attachments.append(_decode(name))
                continue
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html") or body:
                continue
            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                content = payload.decode(part.get_content_charset() or "utf-8", "replace")
            body = _html_to_text(content) if ctype == "text/html" else _clean(content)
        body = body or "(thư không có nội dung văn bản)"
        return {
            "uid": str(uid),
            "from": _decode(msg.get("From")),
            "to": _decode(msg.get("To")),
            "subject": _decode(msg.get("Subject")) or "(không có tiêu đề)",
            "date": _decode(msg.get("Date")),
            "body": body[:max_chars],
            "truncated": len(body) > max_chars,
            "attachments": attachments[:10],
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def send(to: str, subject: str, body: str) -> None:
    cfg = load()
    if not cfg.get("address") or not cfg.get("password") or not cfg.get("smtp_host"):
        raise EmailError("Chưa cấu hình email. Xem /email.")
    if "@" not in (to or ""):
        raise EmailError("Địa chỉ người nhận không hợp lệ.")
    msg = EmailMessage()
    msg["From"] = cfg["address"]
    msg["To"] = to.strip()
    msg["Subject"] = (subject or "").strip() or "(không có tiêu đề)"
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body or "")
    try:
        if cfg.get("smtp_ssl") or int(cfg.get("smtp_port") or 0) == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"] or 465,
                                      context=ssl.create_default_context(), timeout=30)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"] or 587, timeout=30)
        with server:
            server.ehlo()
            if not (cfg.get("smtp_ssl") or int(cfg.get("smtp_port") or 0) == 465):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(cfg["address"], cfg["password"])
            server.send_message(msg)
    except EmailError:
        raise
    except Exception as e:
        raise EmailError(_friendly(e)) from e


def test() -> dict:
    cfg = load()
    missing = [label for key, label in (("address", "địa chỉ email"),
                                        ("password", "mật khẩu ứng dụng")) if not cfg.get(key)]
    if missing:
        raise EmailError("Thiếu " + ", ".join(missing) + " — đặt bằng /email setup.")
    conn = _imap(cfg)
    try:
        typ, data = conn.select("INBOX", readonly=True)
        count = 0
        if typ == "OK" and data and data[0]:
            try:
                count = int(data[0])
            except Exception:
                count = 0
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return {"address": cfg["address"], "imap": cfg["imap_host"], "smtp": cfg["smtp_host"],
            "messages": count}


def mask(address: str) -> str:
    if "@" not in (address or ""):
        return address or ""
    user, domain = address.split("@", 1)
    shown = user[:2] + "…" + user[-1:] if len(user) > 3 else user[:1] + "…"
    return f"{shown}@{domain}"


def _cli() -> int:
    configure(os.getenv("STV_HOME") or ("/content/stv_agent" if Path("/content").exists()
                                        else Path.home() / "stv_agent"))
    p = argparse.ArgumentParser(prog="aistv_email", description="Đọc/gửi email cho AI STV")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status", help="Xem cấu hình")
    sub.add_parser("test", help="Kiểm tra đăng nhập IMAP")
    pi = sub.add_parser("inbox", help="Liệt kê thư mới")
    pi.add_argument("-n", "--limit", type=int, default=10)
    pi.add_argument("--unread", action="store_true")
    pr = sub.add_parser("read", help="Đọc một thư")
    pr.add_argument("uid")
    ps = sub.add_parser("send", help="Gửi thư")
    ps.add_argument("--to", required=True)
    ps.add_argument("--subject", required=True)
    ps.add_argument("--body", required=True)
    ps.add_argument("--body-file")
    args = p.parse_args()

    try:
        if args.cmd in (None, "status"):
            cfg = load()
            if not cfg.get("address"):
                print("Email: chưa cấu hình (đặt AISTV_EMAIL_ADDRESS / AISTV_EMAIL_PASSWORD "
                      "hoặc dùng /email setup).")
                return 1
            print(f"Email: {cfg['address']}")
            print(f"IMAP: {cfg['imap_host']}:{cfg['imap_port']}  SMTP: {cfg['smtp_host']}:{cfg['smtp_port']}")
            print(f"Mật khẩu: {'đã đặt' if cfg.get('password') else 'THIẾU'}")
            return 0
        if args.cmd == "test":
            info = test()
            print(f"OK: {info['address']} · INBOX {info['messages']} thư · "
                  f"IMAP {info['imap']} · SMTP {info['smtp']}")
            return 0
        if args.cmd == "inbox":
            rows = list_messages(args.limit, args.unread)
            if not rows:
                print("(không có thư)")
                return 0
            for i, m in enumerate(rows, 1):
                flag = "●" if m["unread"] else "○"
                print(f"{i}. {flag} [{m['uid']}] {m['subject']}")
                print(f"   {m['from']} · {m['date']}")
            return 0
        if args.cmd == "read":
            m = read_message(args.uid)
            print(f"Từ: {m['from']}\nTiêu đề: {m['subject']}\nNgày: {m['date']}\n")
            print(m["body"])
            if m["truncated"]:
                print("\n…(đã cắt bớt)")
            if m["attachments"]:
                print("\nĐính kèm: " + ", ".join(m["attachments"]))
            return 0
        if args.cmd == "send":
            body = Path(args.body_file).read_text("utf-8") if args.body_file else args.body
            send(args.to, args.subject, body)
            print(f"Đã gửi tới {args.to}: {args.subject}")
            return 0
    except EmailError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"LỖI: {_friendly(e)}", file=sys.stderr)
        return 2
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
