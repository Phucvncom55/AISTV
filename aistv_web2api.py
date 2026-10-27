#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI STV - Gemini nội bộ: server + đồng bộ cookie dạng chữ.

Vì sao có file này
------------------
Khi model chính (OpenCode / DeepSeek...) hết hạn mức request hoặc lỗi server,
agent tự chuyển sang server Gemini nội bộ chạy ngay trên máy chủ của mình.
Server đó dùng cookie tài khoản Google (Gemini Web) nên KHÔNG cần API key trả phí.

Cookie lưu thẳng dạng chữ (KHÔNG mã hoá) để dễ sửa:
  • file đang dùng: ~/.config/aistv/web2api/cookie.txt (header `name=value; ...`);
  • bản sao trên GitHub: repo private, `web2api/cookie.txt` — sửa trực tiếp trên
    web cũng được, máy khác chạy `pull`/`auto` là có ngay;
  • dán cookie mới vào cookie.txt là server tự nạp lại và chạy, không cần `start`;
  • bản cũ `cookies.enc` + `passphrase` được tự giải mã một lần rồi chuyển sang
    `cookie.txt` nguyên văn (local và repo private), sau đó xoá file mã hoá cũ.

Dán cookie y như copy từ trình duyệt: header `a=b; c=d`, `Cookie: ...`, nhiều dòng,
JSON export (Cookie-Editor / EditThisCookie), Netscape `cookies.txt` (kể cả dòng
`#HttpOnly_...`) hoặc lệnh cURL đều được chuẩn hoá, không cần sửa tay.

Cookie là bí mật sống (ai có cookie = vào được tài khoản). Chỉ đồng bộ vào
repo PRIVATE, đừng commit vào repo public.

Lệnh thường dùng
----------------
  python aistv_web2api.py setup              # tải server + tạo config + cài httpx
  python aistv_web2api.py import cookies.json  # nạp cookie export từ trình duyệt
  python aistv_web2api.py auto               # kéo cookie mới + bật server (1 lệnh)
  python aistv_web2api.py refresh            # lấy lại XSRF token (SNlM0e)
  python aistv_web2api.py push               # đẩy cookie nguyên văn lên repo private
  python aistv_web2api.py pull               # máy mới: tải cookie từ repo private
  python aistv_web2api.py start | stop | status | logs
  python aistv_web2api.py test ["câu hỏi"]   # gọi thử 1 request
  python aistv_web2api.py doctor             # kiểm tra tổng thể, không in bí mật
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

try:                                      # Windows cmd luôn in được tiếng Việt
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_URL = "https://github.com/Sophomoresty/gemini-web2api.git"
ZIP_URL = "https://codeload.github.com/Sophomoresty/gemini-web2api/zip/refs/heads/main"
SECRETS_REPO = "Phucvncom55/AISTV-secrets"
SECRETS_PATH = "web2api/cookie.txt"          # cookie nguyên văn, sửa được trên GitHub
DEFAULT_MODEL = "gemini-3.5-flash-thinking"   # think cao mặc định; đổi bằng WEB2API_MODEL
DEFAULT_KEY = "sk-gemini"
IMAGE_PATCH = "gemini-web2api-image.patch"      # vá thêm xem ảnh + tạo ảnh
MEDIA_PATCH = "gemini-web2api-media.patch"      # vá thêm nhận audio/video
IMAGE_ENDPOINT = "/v1/images/generations"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
SAPI_SID_NAMES = ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID")
COOKIE_PRIORITY = (
    "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "SSID", "HSID", "SID",
    "APISID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "AEC", "NID", "COMPASS",
)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HTTP_TIMEOUT = 30


# ────────────────────────────────────────────────────────────────────
# Cấu hình / đường dẫn
# ────────────────────────────────────────────────────────────────────
def _config_module():
    try:
        import aistv_config
        return aistv_config
    except Exception:
        return None


def config_dir() -> Path:
    mod = _config_module()
    if mod is not None:
        try:
            return mod.config_dir()
        except Exception:
            pass
    return Path.home() / ".config" / "aistv"


def runtime_dir() -> Path:
    override = (os.getenv("WEB2API_DIR") or "").strip()
    path = Path(override).expanduser() if override else config_dir() / "web2api"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_dir() -> Path:
    return runtime_dir() / "app"


def app_script() -> Path:
    return app_dir() / "gemini_web2api.py"


def package_dir() -> Path:
    return app_dir() / "gemini_web2api"


def image_patch_path() -> Path:
    """Patch đóng gói trong repo AISTV (không phụ thuộc bản upstream mới nhất)."""
    return Path(__file__).resolve().parent / "patches" / IMAGE_PATCH


def image_files_zip() -> Path:
    """Bản package đã vá, dùng khi máy không có git/patch."""
    return image_patch_path().with_name(Path(IMAGE_PATCH).stem + "-files.zip")


def media_patch_path() -> Path:
    return Path(__file__).resolve().parent / "patches" / MEDIA_PATCH


def media_files_zip() -> Path:
    return media_patch_path().with_name(Path(MEDIA_PATCH).stem + "-files.zip")


def _read_text(path: Path) -> str:
    try:
        return path.read_text("utf-8", "replace")
    except Exception:
        return ""


def image_patch_ready() -> bool:
    """Đã vá đủ phần xem ảnh + tạo ảnh của upstream chưa."""
    server = _read_text(package_dir() / "server.py")
    generated = _read_text(package_dir() / "generated_image.py")
    return ("generate_image_structured" in server
            and "_MEDIATOR_GENERATED_IMAGE_HOSTS" in generated)


def apply_image_patch(quiet: bool = True) -> tuple:
    """Áp patch ảnh lên bản clone upstream; chạy lại nhiều lần vẫn an toàn."""
    if image_patch_ready():
        return True, "đã có"
    patch = image_patch_path()
    if not patch.is_file():
        return False, f"thiếu {patch.name}"
    if not package_dir().is_dir():
        return False, "chưa tải server upstream"
    detail = ""
    git = shutil.which("git")
    if git and (app_dir() / ".git").exists():
        result = subprocess.run([git, "apply", str(patch)], cwd=str(app_dir()),
                                capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and image_patch_ready():
            return True, "git apply"
        detail = (result.stderr or result.stdout or "").strip()[-300:]
    tool = shutil.which("patch")
    if tool:
        result = subprocess.run([tool, "-p1", "-i", str(patch)], cwd=str(app_dir()),
                                capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and image_patch_ready():
            return True, "patch"
        detail = (result.stderr or result.stdout or "").strip()[-300:] or detail
    else:
        detail = detail or "không có git/patch"
    archive = image_files_zip()
    if archive.is_file():
        try:
            with zipfile.ZipFile(archive) as zf:
                for name in zf.namelist():
                    if name.startswith("gemini_web2api/") and name.endswith(".py"):
                        zf.extract(name, app_dir())
            if image_patch_ready():
                return True, "zip"
        except Exception as exc:
            detail = f"zip: {exc}"
    if not quiet:
        print(f"⚠️ Chưa vá được tính năng ảnh: {detail}")
    return False, detail or "không áp được patch"


def media_patch_ready() -> bool:
    """Server đã nhận được audio/video chưa (không chỉ ảnh)."""
    pkg = package_dir()
    server = _read_text(pkg / "server.py")
    tools = _read_text(pkg / "tools.py")
    multi = _read_text(pkg / "multimodal.py")
    return ("detect_media_mime" in server and "media_filename" in multi
            and "attachment_label" in tools)


def apply_media_patch(quiet: bool = True) -> tuple:
    """Áp patch audio/video lên bản đã vá ảnh; chạy lại nhiều lần vẫn an toàn."""
    if media_patch_ready():
        return True, "đã có"
    if not package_dir().is_dir():
        return False, "chưa tải server upstream"
    detail = ""
    patch = media_patch_path()
    if patch.is_file():
        git = shutil.which("git")
        if git and (app_dir() / ".git").exists():
            result = subprocess.run([git, "apply", str(patch)], cwd=str(app_dir()),
                                    capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and media_patch_ready():
                return True, "git apply"
            detail = (result.stderr or result.stdout or "").strip()[-300:]
        tool = shutil.which("patch")
        if tool:
            result = subprocess.run([tool, "-p1", "-i", str(patch)], cwd=str(app_dir()),
                                    capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and media_patch_ready():
                return True, "patch"
            detail = (result.stderr or result.stdout or "").strip()[-300:] or detail
        elif not detail:
            detail = "không có git/patch"
    archive = media_files_zip()
    if archive.is_file():
        try:
            with zipfile.ZipFile(archive) as zf:
                for name in zf.namelist():
                    if name.startswith("gemini_web2api/") and name.endswith(".py"):
                        zf.extract(name, app_dir())
            if media_patch_ready():
                return True, "zip"
        except Exception as exc:
            detail = f"zip: {exc}"
    if not quiet:
        print(f"⚠️ Chưa vá được audio/video: {detail}")
    return False, detail or "không áp được patch"


def app_entry() -> str:
    """Bản đang chạy: 'package' (đã vá, có ảnh) hoặc 'single' (file đơn cũ)."""
    if image_patch_ready() and (package_dir() / "__main__.py").is_file():
        return "package"
    return "single"


def app_command() -> list:
    """Chạy package đã vá khi có (hỗ trợ ảnh), không thì file đơn cũ."""
    if app_entry() == "package":
        return [_python(), "-m", "gemini_web2api", "--config", str(config_path())]
    return [_python(), str(app_script()), "--config", str(config_path())]


def cookie_path() -> Path:
    """File cookie đang dùng; đổi bằng WEB2API_COOKIE_FILE nếu muốn để chỗ khác."""
    override = (value("WEB2API_COOKIE_FILE") or "").strip()
    return Path(override).expanduser() if override else runtime_dir() / "cookie.txt"


def export_path() -> Path:
    return runtime_dir() / "cookies.json"


def config_path() -> Path:
    return runtime_dir() / "config.json"


def state_path() -> Path:
    return runtime_dir() / "state.json"


def log_path() -> Path:
    return runtime_dir() / "server.log"


def value(name: str, default: str = "") -> str:
    """Đọc biến môi trường → config.env dùng chung → mặc định."""
    raw = (os.getenv(name) or "").strip()
    if raw:
        return raw
    mod = _config_module()
    if mod is not None:
        try:
            raw = (mod.get_value(name) or "").strip()
            if raw:
                return raw
        except Exception:
            pass
    return default


def enabled() -> bool:
    return value("WEB2API_ENABLE", "1").lower() not in ("0", "off", "false", "no")


def base_url() -> str:
    return value("WEB2API_URL", "http://127.0.0.1:8081").rstrip("/")


def api_key() -> str:
    return value("WEB2API_API_KEY", DEFAULT_KEY)


def default_model() -> str:
    return value("WEB2API_MODEL", DEFAULT_MODEL)


def is_local() -> bool:
    host = urllib.parse.urlparse(base_url()).hostname or "127.0.0.1"
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def autostart() -> bool:
    return value("WEB2API_AUTOSTART", "1").lower() not in ("0", "off", "false", "no")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    tmp.replace(path)


# ────────────────────────────────────────────────────────────────────
# Cookie: đọc / ghi / chuyển đổi
# ────────────────────────────────────────────────────────────────────
COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
COOKIE_META = {
    "path", "domain", "expires", "max-age", "samesite", "secure", "httponly",
    "priority", "partitioned",
}


def _strip_cookie_wrapping(text: str) -> str:
    """Bỏ BOM, dấu nháy và tiền tố `Cookie:` khi người dùng dán nguyên từ trình duyệt."""
    text = (text or "").replace("\ufeff", "").replace("\r", "").strip()
    if text.startswith("```"):
        text = re.sub(r"(?is)^```[a-z0-9_-]*\s*", "", text)
        text = re.sub(r"(?is)\s*```\s*$", "", text).strip()
    # DevTools "Copy as cURL": lấy đúng phần sau header cookie.
    if "cookie:" in text.lower() and re.search(r"(?i)(?:^|\s)(?:-H|--header|curl)\b", text):
        match = re.search(r"(?is)cookie\s*:\s*(.+)$", text)
        if match:
            text = match.group(1).strip().rstrip("\\").strip()
            text = re.split(r"""["']""", text, maxsplit=1)[0]
    text = re.sub(r"(?im)^\s*cookie\s*:\s*", "", text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def _cookie_pairs(raw: str) -> list:
    """Tách `name=value` từ header / nhiều dòng; giữ giá trị y như người dùng dán."""
    raw = _strip_cookie_wrapping(raw)
    pairs, seen = [], set()
    for chunk in re.split(r"[;\n]+", raw):
        chunk = chunk.strip().strip(",").strip()
        if not chunk or "=" not in chunk:
            continue
        name, val = chunk.split("=", 1)
        name = name.strip().strip("\"'").strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if not name or not COOKIE_NAME_RE.match(name):
            continue
        if name.lower() in COOKIE_META or name in seen:
            continue
        seen.add(name)
        pairs.append(f"{name}={val}")
    return pairs


def _cookie_header(cookies: list) -> str:
    pairs = {}
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = item.get("value")
        val = "" if value is None else str(value)
        domain = str(item.get("domain") or "google.com").lower().lstrip(".")
        if not name or not COOKIE_NAME_RE.match(name):
            continue
        if not any(domain == d or domain.endswith("." + d)
                   for d in ("google.com", "googleusercontent.com",
                             "gemini.google.com")):
            continue
        pairs[name] = val
    ordered = [n for n in COOKIE_PRIORITY if n in pairs]
    ordered += [n for n in pairs if n not in ordered]
    return "; ".join(f"{n}={pairs[n]}" for n in ordered)


def _parse_json_cookies(data) -> list:
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if isinstance(data, dict) and isinstance(data.get("cookies"), dict):
        data = data["cookies"]
    if isinstance(data, dict):
        raw = data.get("cookie") or data.get("Cookie") or ""
        cookies = []
        if isinstance(raw, str) and raw.strip():
            cookies = parse_cookie_input(raw)
        if not cookies:
            # Một số công cụ export dạng {"TÊN": "giá trị", ...}.
            cookies = [{"name": str(k), "value": str(v)}
                       for k, v in data.items()
                       if isinstance(v, (str, int, float))
                       and COOKIE_NAME_RE.match(str(k))
                       and str(k).lower() not in COOKIE_META]
        if data.get("sapisid") and not any(c["name"] == "SAPISID" for c in cookies):
            cookies.append({"name": "SAPISID", "value": str(data["sapisid"])})
        return cookies
    if isinstance(data, list):
        return [c for c in data
                if isinstance(c, dict) and c.get("name")
                and c.get("value") is not None]
    return []


def parse_cookie_input(text: str) -> list:
    """Nhận JSON export (Cookie-Editor / EditThisCookie), Netscape hoặc header."""
    text = _strip_cookie_wrapping(text)
    if not text:
        return []
    if text[0] in "[{":
        data = json.loads(text)
        return _parse_json_cookies(data)
    if "\t" in text:
        cookies = []
        for line in text.splitlines():
            line = line.rstrip()
            if not line.strip():
                continue
            if line.startswith("#HttpOnly_"):     # Netscape: cookie HttpOnly vẫn là dữ liệu
                line = line[len("#HttpOnly_"):]
            elif line.lstrip().startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7:
                cookies.append({"name": fields[5].strip(),
                                "value": fields[6].strip(),
                                "domain": fields[0].strip()})
        if cookies:
            return cookies
    return [{"name": p.split("=", 1)[0], "value": p.split("=", 1)[1]}
            for p in _cookie_pairs(text)]


def load_cookies() -> list:
    return _read_json(export_path(), []) or []


def save_cookies(cookies: list) -> str:
    cookies = [c for c in cookies if isinstance(c, dict)
               and c.get("name") and c.get("value") is not None]
    header = _cookie_header(cookies)
    _write_json(export_path(), cookies)
    cookie_path().parent.mkdir(parents=True, exist_ok=True)
    cookie_path().write_text(header, "utf-8")
    try:
        cookie_path().chmod(0o600)
    except Exception:
        pass
    return header


def cookie_header() -> str:
    """Cookie đang dùng, luôn trả về header sạch dù người dùng dán định dạng nào."""
    if cookie_path().exists():
        try:
            raw = cookie_path().read_text("utf-8", "replace").strip()
        except Exception:
            raw = ""
        if raw:
            try:
                header = cleanup_cookie_header(raw)
                if header:
                    return header
            except Exception:
                pass
    header = _cookie_header(load_cookies())
    if header:
        return header
    return _legacy_local_header()


def cleanup_cookie_header(raw: str) -> str:
    """Chuẩn hoá cookie: nhận header/JSON/Netscape, bỏ xuống dòng, giữ nguyên giá trị."""
    raw = (raw or "").replace("\ufeff", "").replace("\r", "")
    if not raw.strip():
        return ""
    stripped = _strip_cookie_wrapping(raw)
    if stripped[:1] in ("[", "{") or "\t" in stripped:
        try:
            cookies = parse_cookie_input(stripped)
            header = _cookie_header(cookies)
            if header:
                return header
        except Exception:
            pass
    return "; ".join(_cookie_pairs(raw))


def refresh_xsrf(quiet: bool = False) -> tuple:
    """Lấy SNlM0e + auth_user từ trang Gemini. Trả (ok, thông điệp)."""
    header = cleanup_cookie_header(cookie_header())
    if not header:
        return False, "chưa có cookie"
    cfg = _read_json(config_path(), {})
    last = ""
    for url in ("https://gemini.google.com/app", "https://gemini.google.com/"):
        try:
            req = urllib.request.Request(url, headers={
                "Cookie": header, "User-Agent": UA,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                html = resp.read().decode("utf-8", "replace")
                final = resp.url
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            continue
        match = re.search(r'SNlM0e\\?"\s*:\s*\\?"([^"\\]+)', html)
        if not match:
            if "accounts.google.com" in final:
                return False, "cookie đã hết hạn (bị chuyển về trang đăng nhập)"
            last = "không thấy SNlM0e trong trang Gemini"
            continue
        account = re.search(r"/u/(\d+)/", final)
        cfg["xsrf_token"] = match.group(1)
        cfg["auth_user"] = account.group(1) if account else None
        cfg["xsrf_at"] = time.time()
        cfg.setdefault("cookie_file", str(cookie_path()))
        _write_json(config_path(), cfg)
        if not quiet:
            print(f"XSRF token: OK ({len(match.group(1))} ký tự), "
                  f"auth_user={cfg['auth_user']}")
        return True, "ok"
    return False, last or "không lấy được XSRF token"


# ────────────────────────────────────────────────────────────────────
# Đồng bộ cookie nguyên văn (không mã hoá) + phát hiện thay đổi
# ────────────────────────────────────────────────────────────────────
def cookie_sig(header: str = "") -> str:
    """Dấu vân tay ngắn của cookie để biết file vừa được dán mới."""
    import hashlib
    raw = cleanup_cookie_header(header or cookie_header())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] if raw else ""


def _state_update(**fields) -> dict:
    state = _read_json(state_path(), {}) or {}
    state.update(fields)
    _write_json(state_path(), state)
    return state


def _autosync() -> bool:
    return value("WEB2API_AUTOSYNC", "1").lower() not in ("0", "off", "false", "no")


def _gh_tokens() -> list:
    mod = _config_module()
    if mod is not None:
        try:
            return mod.github_tokens({})
        except Exception:
            pass
    token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    return [("env", token)] if token else []


def _gh_request(url: str, token: str, method: str = "GET", payload: dict = None,
                accept: str = "application/vnd.github+json") -> tuple:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": accept,
        "User-Agent": "aistv-web2api/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _remote_repo() -> tuple:
    repo = (value("WEB2API_SECRETS_REPO", "") or SECRETS_REPO).strip()
    path = (value("WEB2API_SECRETS_PATH", "") or SECRETS_PATH).strip().lstrip("/")
    return repo, path


def _gh_put_text(path: str, text: str, message: str) -> tuple:
    repo, _ = _remote_repo()
    tokens = _gh_tokens()
    if not tokens:
        return False, "chưa có token GitHub"
    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}"
    last = ""
    for source, token in tokens:
        if not token:
            continue
        sha = ""
        try:
            status, body = _gh_request(url, token)
            if status == 200:
                sha = json.loads(body).get("sha") or ""
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 401, 403):
                last = f"HTTP {exc.code}"
                continue
        payload = {"message": message,
                   "content": base64.b64encode(text.encode("utf-8")).decode()}
        if sha:
            payload["sha"] = sha
        try:
            _gh_request(url, token, "PUT", payload)
            return True, f"{repo}/{path}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
    return False, last or "không đẩy được"


def _gh_get_text(path: str) -> str:
    repo, _ = _remote_repo()
    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}"
    for _source, token in _gh_tokens():
        if not token:
            continue
        try:
            status, body = _gh_request(url, token, accept="application/vnd.github.raw")
            if status == 200 and body:
                return body
        except Exception:
            continue
    return ""


def _gh_delete_text(path: str, message: str) -> tuple:
    """Xoá file cũ trên repo private (dùng khi chuyển cookie mã hoá → nguyên văn)."""
    repo, _ = _remote_repo()
    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}"
    tokens = _gh_tokens()
    if not tokens:
        return False, "chưa có token GitHub"
    last = ""
    for _source, token in tokens:
        if not token:
            continue
        try:
            status, body = _gh_request(url, token)
            if status != 200:
                return True, "không có"
            sha = json.loads(body).get("sha") or ""
            _gh_request(url, token, "DELETE",
                        {"message": message, "sha": sha})
            return True, f"{repo}/{path}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
    return False, last or "không xoá được"


def _sibling_secret_path(name: str) -> str:
    _repo, path = _remote_repo()
    prefix = path.rsplit("/", 1)[0] if "/" in path else ""
    return (prefix + "/" if prefix else "") + name


def _legacy_passphrase() -> str:
    for name in ("WEB2API_COOKIE_PASSPHRASE", "AISTV_COOKIE_PASSPHRASE"):
        raw = value(name)
        if raw:
            return raw
    for folder in (runtime_dir(), cookie_path().parent):
        local = folder / "passphrase.txt"
        try:
            raw = local.read_text("utf-8").strip()
            if raw:
                return raw
        except Exception:
            continue
    return ""


def _decode_legacy_blob(text: str, phrase: str) -> str:
    """Giải mã blob AES-256-GCM của bản cũ; trả cookie dạng chữ."""
    blob = json.loads(text)
    if not isinstance(blob, dict) or not blob.get("data"):
        return text if isinstance(text, str) else ""
    if not phrase:
        raise RuntimeError("thiếu passphrase để giải mã cookie cũ")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if int(blob.get("v") or 0) != 1:
        raise RuntimeError("định dạng cookie cũ không hỗ trợ")
    salt = base64.b64decode(blob["salt"])
    nonce = base64.b64decode(blob["nonce"])
    data = base64.b64decode(blob["data"])
    key = Scrypt(salt=salt, length=32, n=2 ** 14, r=8, p=1).derive(
        phrase.encode("utf-8"))
    return AESGCM(key).decrypt(nonce, data, b"aistv-web2api-v1").decode(
        "utf-8", "replace")


def _legacy_local_payload() -> tuple:
    """Đọc cookies.enc + passphrase.txt của bản cũ (nếu còn) → cookie dạng chữ."""
    phrase = _legacy_passphrase()
    seen = set()
    for folder in (runtime_dir(), cookie_path().parent):
        enc = folder / "cookies.enc"
        try:
            key = str(enc.resolve())
        except Exception:
            key = str(enc)
        if key in seen or not enc.exists():
            continue
        seen.add(key)
        try:
            return _decode_legacy_blob(enc.read_text("utf-8", "replace"), phrase), str(enc)
        except Exception:
            continue
    return "", ""


def _legacy_local_header() -> str:
    try:
        payload, _source = _legacy_local_payload()
        if payload:
            return _cookie_header(parse_cookie_input(payload))
    except Exception:
        pass
    return ""


def _apply_legacy_meta(payload: str) -> None:
    """Giữ XSRF/auth_user cũ nếu blob có sẵn (sẽ refresh lại sau)."""
    try:
        data = json.loads(payload)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    cfg = _read_json(config_path(), {}) or {}
    if data.get("xsrf_token") and not cfg.get("xsrf_token"):
        cfg["xsrf_token"] = str(data["xsrf_token"])
        cfg["xsrf_at"] = 0
    if data.get("auth_user") and not cfg.get("auth_user"):
        cfg["auth_user"] = str(data["auth_user"])
    if cfg:
        _write_json(config_path(), cfg)


def migrate_legacy(quiet: bool = True) -> tuple:
    """Chuyển cookie mã hoá cũ (local hoặc repo private) sang cookie.txt nguyên văn."""
    plain = ""
    if cookie_path().exists():
        try:
            plain = cleanup_cookie_header(cookie_path().read_text("utf-8", "replace"))
        except Exception:
            plain = ""
    if plain:
        return False, "đã có cookie nguyên văn"
    json_cookies = load_cookies()
    if json_cookies:
        json_header = _cookie_header(json_cookies)
        if json_header:
            save_cookies(json_cookies)
            return False, "đã có cookie nguyên văn"
    payload, source = _legacy_local_payload()
    if not payload:
        enc_path = _sibling_secret_path("cookies.enc")
        remote = _gh_get_text(enc_path)
        if remote.strip():
            phrase = _legacy_passphrase() or _gh_get_text(
                _sibling_secret_path("passphrase")).strip()
            try:
                payload = _decode_legacy_blob(remote, phrase)
                source = f"{_remote_repo()[0]}/{enc_path}"
            except Exception as exc:
                if not quiet:
                    print(f"Không giải mã được cookie cũ: {exc}")
                payload = ""
    if not payload:
        return False, "không có cookie cũ để chuyển"
    try:
        cookies = parse_cookie_input(payload)
    except Exception as exc:
        return False, f"cookie cũ không đọc được: {exc}"
    if not cookies:
        return False, "cookie cũ không có cookie hợp lệ"
    header = save_cookies(cookies)
    sig = cookie_sig(header)
    _state_update(cookie_sig=sig, cookie_changed=time.time())
    _apply_legacy_meta(payload)
    ok_xsrf, xsrf_msg = refresh_xsrf(quiet=True)
    pushed = False
    if _autosync():
        pushed, _pmsg = push_secrets(quiet=True)
    if pushed:
        # Bản mã hoá cũ không còn dùng — xoá để không ai tưởng vẫn là nguồn chính.
        for name in ("cookies.enc", "passphrase"):
            try:
                _gh_delete_text(_sibling_secret_path(name),
                                "chore(web2api): bo file cookie ma hoa cu")
            except Exception:
                pass
        _state_update(synced_sig=cookie_sig(header), synced_at=time.time())
    if not quiet:
        print(f"Đã chuyển cookie cũ ({source}) → cookie.txt nguyên văn"
              + (" + GitHub" if pushed else "")
              + ("" if ok_xsrf else f" (XSRF lỗi: {xsrf_msg})"))
    return True, "đã chuyển cookie cũ sang định dạng nguyên văn"


def push_secrets(quiet: bool = False) -> tuple:
    """Đẩy cookie NGUYÊN VĂN lên repo private (một dòng, sửa được trên GitHub)."""
    header = cleanup_cookie_header(cookie_header())
    if not header:
        return False, "chưa có cookie — dán vào cookie.txt hoặc chạy `import` trước"
    repo, path = _remote_repo()
    ok, msg = _gh_put_text(path, header + "\n",
                           "chore(web2api): cap nhat cookie")
    if not ok:
        return False, msg
    _state_update(synced_sig=cookie_sig(header), synced_at=time.time())
    if not quiet:
        print(f"Đã đẩy cookie → {repo}/{path}")
    return True, f"{repo}/{path}"


def pull_secrets(quiet: bool = False) -> tuple:
    """Tải cookie nguyên văn từ repo private, ghi cookie.txt + cookies.json.

    Repo cũ chỉ có `cookies.enc` + `passphrase` vẫn dùng được: tự giải mã một lần,
    lưu `cookie.txt` nguyên văn rồi xoá file mã hoá cũ.
    """
    repo, path = _remote_repo()
    if not _gh_tokens():
        return False, "chưa có token GitHub (gh auth login hoặc AISTV_CONFIG_TOKEN)"
    text = _gh_get_text(path)
    cookies = []
    if text.strip():
        try:
            cookies = parse_cookie_input(text)
        except Exception as exc:
            if not quiet:
                print(f"File trên GitHub không đọc được: {exc}")
    if not cookies:
        migrated, migrate_msg = migrate_legacy(quiet=True)
        if migrated:
            return True, migrate_msg
        if not text.strip():
            return False, f"không tải được {repo}/{path}"
        return False, "file trên GitHub không có cookie hợp lệ"
    header = save_cookies(cookies)
    sig = cookie_sig(header)
    _state_update(cookie_sig=sig, synced_sig=sig, pulled_at=time.time())
    if not quiet:
        print(f"Đã tải {len(cookies)} cookie từ {repo}/{path}")
    return True, "ok"


def pull_if_safe(quiet: bool = True) -> tuple:
    """Kéo bản trên GitHub nếu máy này không có sửa đổi chưa đẩy."""
    if not enabled():
        return False, "đã tắt"
    repo, path = _remote_repo()
    if not _gh_tokens():
        return False, "chưa có token GitHub"
    text = _gh_get_text(path)
    remote = []
    if text.strip():
        try:
            remote = parse_cookie_input(text)
        except Exception:
            remote = []
    if not remote:
        migrated, migrate_msg = migrate_legacy(quiet=True)
        if migrated:
            return True, migrate_msg
        if not text.strip():
            return False, f"chưa có {repo}/{path}"
        return False, "bản trên GitHub không có cookie hợp lệ"
    remote_header = _cookie_header(remote)
    rsig = cookie_sig(remote_header)
    local_header = cleanup_cookie_header(cookie_header())
    lsig = cookie_sig(local_header)
    if rsig == lsig:
        if not cookie_path().exists():
            save_cookies(remote)
        return False, "đã mới nhất"
    state = _read_json(state_path(), {}) or {}
    if local_header and lsig != (state.get("synced_sig") or ""):
        return False, "cookie máy này có thay đổi chưa đẩy — giữ bản local"
    save_cookies(remote)
    _state_update(cookie_sig=rsig, synced_sig=rsig, pulled_at=time.time())
    refresh_xsrf(quiet=True)
    if health():
        _reload_server()
    if not quiet:
        print(f"Đã lấy cookie mới từ {repo}/{path}")
    return True, "đã lấy cookie mới từ GitHub"


def sync_if_changed(quiet: bool = True, push: bool = None) -> tuple:
    """Nạp cookie vừa dán trong cookie.txt; tự làm mới XSRF và chạy lại server."""
    if not enabled():
        return False, "đã tắt"
    push = _autosync() if push is None else push
    header = cleanup_cookie_header(cookie_header())
    if not header:
        state = _read_json(state_path(), {}) or {}
        if time.time() - float(state.get("pull_try") or 0) < 60:
            return False, f"chưa có cookie — dán vào {cookie_path()}"
        _state_update(pull_try=time.time())
        ok, msg = pull_secrets(quiet=True)
        if not ok:
            return False, f"chưa có cookie — dán vào {cookie_path()}"
        return True, msg
    if not cookie_path().exists():
        # Cookie cũ chỉ nằm trong cookies.enc/cookies.json → ghi cookie.txt nguyên văn.
        cookies = parse_cookie_input(header)
        if cookies:
            header = save_cookies(cookies)
    sig = cookie_sig(header)
    state = _read_json(state_path(), {}) or {}
    if sig == state.get("cookie_sig"):
        # Lần trước đẩy GitHub lỗi (mất mạng/chưa có token) → thử lại, đừng bỏ qua.
        if push and sig != (state.get("synced_sig") or "") \
                and time.time() - float(state.get("push_try") or 0) > 60:
            _state_update(push_try=time.time())
            pushed, _pmsg = push_secrets(quiet=True)
            if pushed:
                return True, "đã đẩy cookie lên GitHub"
        # XSRF sống vài giờ: làm mới trước khi model dự phòng gọi Gemini.
        if _xsrf_stale():
            ok, _msg = refresh_xsrf(quiet=True)
            if ok:
                _state_update(xsrf_ok=True, xsrf_at=time.time())
                if health():
                    _reload_server()
                return True, "đã làm mới XSRF token"
        return False, "không đổi"
    cookies = parse_cookie_input(header)
    if cookies:
        header = save_cookies(cookies)
        sig = cookie_sig(header)
    ok, xsrf_msg = refresh_xsrf(quiet=True)
    _state_update(cookie_sig=sig, cookie_changed=time.time(), xsrf_ok=bool(ok))
    if health():
        _reload_server()
    if push and sig != (state.get("synced_sig") or ""):
        pushed, pmsg = push_secrets(quiet=True)
        if not quiet:
            print("Đồng bộ GitHub: " + ("OK" if pushed else pmsg))
    if not quiet:
        print("Đã nạp cookie mới" + ("" if ok else f" (XSRF lỗi: {xsrf_msg})"))
    return True, "đã nạp cookie mới"


def auto(quiet: bool = True) -> tuple:
    """Một lệnh cho máy mới: kéo cookie, nạp cookie vừa dán, bật server."""
    _migrated, migrate_msg = migrate_legacy(quiet=True)
    _pulled, pull_msg = pull_if_safe(quiet=True)
    _changed, change_msg = sync_if_changed(quiet=True)
    ok = ensure_server(quiet=True)
    detail = ("server sẵn sàng" if ok else
              (migrate_msg if _migrated else change_msg if _changed else
               pull_msg if _pulled else
               "chưa có cookie hoặc server không khởi động được"))
    if not quiet:
        print(detail)
    return ok, detail


def import_text(text: str, push: bool = None) -> tuple:
    """Nạp cookie từ chuỗi (header/JSON/Netscape), chạy server + đồng bộ GitHub."""
    try:
        cookies = parse_cookie_input(text)
    except Exception as exc:
        return False, f"không đọc được cookie: {exc}"
    if not cookies:
        return False, "không tìm thấy cookie nào"
    header = save_cookies(cookies)
    sig = cookie_sig(header)
    _state_update(cookie_sig=sig, cookie_changed=time.time())
    ok_xsrf, xsrf_msg = refresh_xsrf(quiet=True)
    started, start_msg = start(quiet=True)
    push = _autosync() if push is None else push
    sync_msg = ""
    if push:
        pushed, pmsg = push_secrets(quiet=True)
        sync_msg = " · GitHub: " + ("OK" if pushed else pmsg)
    detail = f"đã nạp {len(cookies)} cookie"
    if not ok_xsrf:
        detail += f" · XSRF lỗi: {xsrf_msg}"
    if not started:
        detail += f" · server: {start_msg}"
    detail += sync_msg
    return bool(ok_xsrf and started), detail


# ────────────────────────────────────────────────────────────────────
# Cài đặt / chạy server
# ────────────────────────────────────────────────────────────────────
def write_config(force: bool = False) -> Path:
    cfg = _read_json(config_path(), {}) if not force else {}
    defaults = {
        "port": int(urllib.parse.urlparse(base_url()).port or 8081),
        "host": "127.0.0.1",
        "retry_attempts": 3,
        "retry_delay_sec": 2,
        "request_timeout_sec": 180,
        "gemini_bl": "boq_assistant-bard-web-server_20260716.08_p0",
        "auth_user": None,
        "xsrf_token": None,
        "default_model": default_model(),
        "log_requests": True,
        "cookie_file": str(cookie_path()),
        "proxy": value("WEB2API_PROXY", "") or None,
        "api_keys": [api_key()],
        "temporary_chats": False,
    }
    for key, val in defaults.items():
        cfg.setdefault(key, val)
    # Các giá trị dưới đây luôn theo môi trường hiện tại (đổi URL/API key có hiệu lực ngay).
    cfg["port"] = defaults["port"]
    cfg["host"] = "127.0.0.1"
    cfg["cookie_file"] = str(cookie_path())
    cfg["api_keys"] = [api_key()]
    cfg["default_model"] = default_model()
    cfg["proxy"] = defaults["proxy"]
    _write_json(config_path(), cfg)
    return config_path()


def _python() -> str:
    return sys.executable or "python3"


def _download_app() -> tuple:
    """Clone repo; nếu không có git thì tải zip."""
    app = app_dir()
    if app_script().exists():
        return True, "đã có"
    app.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if git:
        result = subprocess.run([git, "clone", "--depth", "1", REPO_URL, str(app)],
                                capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and app_script().exists():
            return True, "git clone"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "app.zip"
        urllib.request.urlretrieve(ZIP_URL, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if not roots:
            return False, "zip rỗng"
        if app.exists():
            shutil.rmtree(app)
        shutil.copytree(roots[0], app)
    return app_script().exists(), "zip"


def ensure_deps() -> tuple:
    try:
        import httpx  # noqa: F401
        return True, "có httpx"
    except Exception:
        pass
    result = subprocess.run([_python(), "-m", "pip", "install", "-q", "httpx"],
                            capture_output=True, text=True, timeout=300)
    ok = result.returncode == 0
    return ok, "đã cài httpx" if ok else (result.stderr or "pip lỗi")[-300:]


def has_curl_cffi() -> bool:
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False


def ensure_image_deps(quiet: bool = True) -> tuple:
    """curl_cffi cần cho xem ảnh + tạo ảnh qua Gemini Web (TLS kiểu Chrome)."""
    if has_curl_cffi():
        return True, "có curl_cffi"
    result = subprocess.run([_python(), "-m", "pip", "install", "-q", "curl_cffi"],
                            capture_output=True, text=True, timeout=300)
    ok = result.returncode == 0
    if not ok and not quiet:
        print("⚠️ Chưa cài được curl_cffi — tính năng ảnh sẽ tạm tắt.")
    return ok, ("đã cài curl_cffi" if ok else (result.stderr or "pip lỗi")[-300:])


def setup(force: bool = False) -> tuple:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    ok, how = _download_app()
    if not ok:
        return False, f"không tải được server: {how}"
    patch_ok, _patch_msg = apply_image_patch(quiet=True)
    if patch_ok:
        ensure_image_deps(quiet=True)
    apply_media_patch(quiet=True)
    write_config(force=force)
    dep_ok, dep_msg = ensure_deps()
    if not dep_ok:
        return False, dep_msg
    if not cookie_header():
        return True, f"server sẵn sàng ({how}); chưa có cookie — dùng lệnh import"
    refresh_xsrf(quiet=True)
    return True, f"server sẵn sàng ({how})"


def health(timeout: float = 2.5) -> bool:
    url = base_url() + "/v1/models"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + api_key()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _xsrf_stale(max_age: float = 6 * 3600) -> bool:
    """XSRF token sống vài giờ; quá cũ thì lấy lại trước khi dùng."""
    cfg = _read_json(config_path(), {})
    if not cfg.get("xsrf_token"):
        return True
    try:
        return (time.time() - float(cfg.get("xsrf_at") or 0)) > max_age
    except Exception:
        return True


def _pid() -> int:
    try:
        return int((_read_json(state_path(), {}) or {}).get("pid") or 0)
    except Exception:
        return 0


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                capture_output=True, text=True)
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start(wait: float = 25.0, quiet: bool = False) -> tuple:
    if health():
        state = _read_json(state_path(), {}) or {}
        entry = state.get("entry")
        desired = app_entry()
        # Bản cũ (single) đang chạy trong khi đã có bản vá → khởi động lại 1 lần.
        if entry == desired or (entry is None and desired == "single"):
            return True, "đã chạy"
        stop()
    if not is_local():
        return False, f"server từ xa không phản hồi: {base_url()}"
    if not cleanup_cookie_header(cookie_header()):
        migrate_legacy(quiet=True)
    if cookie_header() and not cookie_path().exists():
        save_cookies(parse_cookie_input(cookie_header()))
    if not cookie_header():
        return False, f"chưa có cookie — dán vào {cookie_path()}"
    if not app_script().exists():
        ok, msg = setup()
        if not ok:
            return False, msg
    apply_image_patch(quiet=True)
    if image_patch_ready():
        ensure_image_deps(quiet=True)
    apply_media_patch(quiet=True)
    write_config()
    if not _read_json(config_path(), {}).get("xsrf_token"):
        refresh_xsrf(quiet=True)
    log = open(log_path(), "ab")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} start =====\n".encode())
    log.flush()
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED | NEW_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        app_command(),
        cwd=str(app_dir()), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        **kwargs)
    _state_update(pid=proc.pid, started=time.time(), url=base_url(), entry=app_entry())
    deadline = time.time() + max(3, wait)
    while time.time() < deadline:
        if health():
            if not quiet:
                print(f"Gemini đã chạy tại {base_url()} (pid {proc.pid})")
            return True, "đã khởi động"
        if proc.poll() is not None:
            break
        time.sleep(0.6)
    return False, f"không khởi động được — xem {log_path()}"


def stop() -> tuple:
    pid = _pid()
    if not _alive(pid):
        return True, "không chạy"
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=30)
        else:
            os.kill(pid, 15)
    except Exception as exc:
        return False, str(exc)
    try:
        _state_update(pid=0, stopped=time.time())
    except Exception:
        pass
    return True, "đã dừng"


def ensure_server(quiet: bool = True) -> bool:
    """Bảo đảm server sẵn sàng; dùng từ bot/watch trước khi fallback.

    Tự kéo cookie trên GitHub (máy mới), tự chuyển cookie mã hoá cũ, tự nạp
    cookie vừa dán vào cookie.txt và tự bật server — không cần chạy `start`.
    """
    if not enabled():
        return False
    if not cleanup_cookie_header(cookie_header()):
        try:
            migrate_legacy(quiet=True)
        except Exception:
            pass
    try:
        sync_if_changed(quiet=True)
    except Exception:
        pass
    if health():
        state = _read_json(state_path(), {}) or {}
        entry, desired = state.get("entry"), app_entry()
        if entry != desired and not (entry is None and desired == "single"):
            ok, _msg = start(quiet=quiet)      # bản cũ → tự chuyển bản vá
            return ok
        cfg = _read_json(config_path(), {}) or {}
        if str(cfg.get("cookie_file") or "") != str(cookie_path()):
            write_config()
            _reload_server()
        if _xsrf_stale():
            ok, _msg = refresh_xsrf(quiet=True)
            if ok:
                _state_update(xsrf_ok=True, xsrf_at=time.time())
                _reload_server()
        return health()
    if not is_local() or not autostart():
        return False
    try:
        ok, msg = start(quiet=quiet)
        if not ok and not quiet:
            print(msg)
        return ok
    except Exception:
        return False


def _reload_server() -> None:
    """Khởi động lại server để nạp XSRF token vừa làm mới."""
    if not is_local() or not health():
        return
    try:
        stop()
        deadline = time.time() + 8
        while health(0.8) and time.time() < deadline:
            time.sleep(0.3)
        start(quiet=True)
    except Exception:
        pass


def _http_json(url: str, payload: dict, timeout: float = 180,
               headers: dict = None) -> tuple:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key(),
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            msg = (json.loads(raw).get("error") or {}).get("message") or raw
        except Exception:
            msg = raw
        return None, f"HTTP {exc.code}: {msg[:400]}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


_CITE_RE = re.compile(r"\s*\[cite:\s*\d+(?:\s*,\s*\d+)*\]", re.I)


def _clean_reply(text: str) -> str:
    """Bỏ chú thích [cite: N] mà Gemini Web chèn vào câu trả lời."""
    return _CITE_RE.sub("", text or "").strip()


def chat(messages: list, model: str = "", timeout: float = 180, **extra) -> tuple:
    payload = {"model": model or default_model(), "messages": messages, **extra}
    data, err = _http_json(base_url() + "/v1/chat/completions", payload, timeout)
    if err:
        return None, err
    try:
        content = data["choices"][0]["message"].get("content")
    except Exception:
        return None, "phản hồi không đúng định dạng"
    content = _clean_reply(content)
    if not content:
        return None, "phản hồi rỗng (ảnh có thể chưa được nhận)"
    return content, None


def _normalise_parts(parts: list) -> list:
    """Google native: chấp nhận cả inline_data/mime_type (snake_case)."""
    out = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        if "inline_data" in part and "inlineData" not in part:
            raw = part["inline_data"] or {}
            part = {k: v for k, v in part.items() if k != "inline_data"}
            part["inlineData"] = {
                "mimeType": raw.get("mime_type") or raw.get("mimeType") or "image/png",
                "data": raw.get("data") or "",
            }
        if "file_data" in part and "fileData" not in part:
            raw = part["file_data"] or {}
            part = {k: v for k, v in part.items() if k != "file_data"}
            part["fileData"] = {
                "mimeType": raw.get("mime_type") or raw.get("mimeType"),
                "fileUri": raw.get("file_uri") or raw.get("fileUri"),
            }
        out.append(part)
    return out


def generate(parts: list, model: str = "", timeout: float = 240,
             temperature: float = 0.2, max_tokens: int = 8192,
             system: str = "") -> tuple:
    """Gọi /v1beta/models/{model}:generateContent, trả (text, lỗi)."""
    if not ensure_server():
        return None, "Gemini chưa sẵn sàng"
    body = {
        "contents": [{"role": "user", "parts": _normalise_parts(parts)}],
        "generationConfig": {"temperature": temperature,
                             "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    url = (f"{base_url()}/v1beta/models/"
           f"{urllib.parse.quote(model or default_model())}:generateContent")
    data, err = _http_json(url, body, timeout)
    if err:
        if "400" in err or "xsrf" in err.lower():
            refresh_xsrf(quiet=True)
            _reload_server()
            data, err = _http_json(url, body, timeout)
        if err:
            return None, err
    try:
        chunks = (((data.get("candidates") or [{}])[0].get("content") or {})
                  .get("parts") or [])
        text = "\n".join(str(p.get("text") or "") for p in chunks).strip()
    except Exception:
        text = ""
    text = _clean_reply(text)
    if text:
        return text, None
    feedback = (data.get("promptFeedback") or {}).get("blockReason")
    return None, f"Gemini không trả lời{(' (' + feedback + ')') if feedback else ''}"


def _image_mime(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


_IMAGE_VERB_RE = re.compile(
    r"(?i)^\s*(create|generate|draw|make|paint|render)\s+(an?\s+)?(image|picture|photo)")

_IMAGE_HOSTS = ("googleusercontent.com", "gstatic.com", "googleapis.com", "ggpht.com")
_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp|gif|avif)$", re.I)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(https?://[^)\s]+)\s*\)")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def normalize_image_url(url: str) -> str:
    """Đưa link ảnh về https và bỏ phần bao ngoài markdown."""
    value = (url or "").strip().strip("<>\"'")
    if value.startswith("//"):
        value = "https:" + value
    if value.lower().startswith("http://"):
        value = "https://" + value[7:]
    return value


def _is_image_url(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(normalize_image_url(url))
    except Exception:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    if not any(host == h or host.endswith("." + h) for h in _IMAGE_HOSTS):
        return False
    return bool(_IMAGE_EXT_RE.search(parts.path)
                or "/image_generation_content/" in parts.path
                or "googleusercontent" in host)


def extract_image_urls(text: str, limit: int = 3) -> list:
    """Tìm link ảnh Gemini chèn trong câu trả lời (markdown hoặc URL trần)."""
    found = []
    for match in _MD_IMAGE_RE.finditer(text or ""):
        url = normalize_image_url(match.group(1))
        if _is_image_url(url) and url not in found:
            found.append(url)
    for match in _URL_RE.finditer(text or ""):
        url = normalize_image_url(match.group(0).rstrip(".,;:!?"))
        if _is_image_url(url) and url not in found:
            found.append(url)
    return found[:max(0, limit)]


def download_image(url: str, timeout: float = 120, allow_any: bool = False) -> tuple:
    """Tải ảnh từ link Google (kèm cookie Gemini Web) → (bytes, mime, lỗi)."""
    url = normalize_image_url(url)
    if not url.lower().startswith("https://") or not urllib.parse.urlsplit(url).hostname:
        return None, "", "link ảnh không hợp lệ"
    if not allow_any and not _is_image_url(url):
        return None, "", "link không phải ảnh Google hợp lệ"
    headers = {
        "User-Agent": UA,
        "Referer": "https://gemini.google.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h)
           for h in ("google.com", "googleusercontent.com", "gstatic.com")):
        cookie = cookie_header()
        if cookie:
            headers["Cookie"] = cookie
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_IMAGE_BYTES + 1)
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as exc:
        return None, "", f"HTTP {exc.code} khi tải ảnh"
    except Exception as exc:
        return None, "", f"không tải được ảnh: {type(exc).__name__}"
    if len(raw) > MAX_IMAGE_BYTES:
        return None, "", "ảnh vượt quá 15 MB"
    if raw[:1] == b"<" or "text/html" in ctype:
        return None, "", "link không trả về ảnh (có thể đã hết hạn)"
    head = raw[:16]
    if not (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff")
            or (head[:4] == b"RIFF" and raw[8:12] == b"WEBP")):
        return None, "", "dữ liệu tải về không phải ảnh"
    return raw, _image_mime(raw), None


def generate_image(prompt: str, model: str = "", timeout: float = 240,
                   response_format: str = "b64_json") -> tuple:
    """Tạo ảnh qua /v1/images/generations của server đã vá.

    Trả (bytes, mime, lỗi). Server cũ chưa vá sẽ trả 404/501 → báo rõ.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return None, "", "thiếu mô tả ảnh"
    if not ensure_server():
        return None, "", "Gemini chưa sẵn sàng"
    # Gemini Web đôi khi trả lời bằng văn bản (công thức, hướng dẫn) nếu câu lệnh
    # không nói rõ là tạo ảnh. Thêm tiền tố để luôn vào chế độ sinh ảnh.
    full = prompt if _IMAGE_VERB_RE.match(prompt) else f"Create an image: {prompt}"
    payload = {"prompt": full, "n": 1, "response_format": response_format}
    if model:
        payload["model"] = model
    data, err = _http_json(base_url() + IMAGE_ENDPOINT, payload, timeout)
    if err and "no generated image" in err.lower():
        # Gemini Web thỉnh thoảng trả lời bằng chữ thay vì ảnh → thử lại 1 lần.
        payload["prompt"] = f"Generate an image. Do not reply with text: {prompt}"
        data, err = _http_json(base_url() + IMAGE_ENDPOINT, payload, timeout)
    if err:
        low = err.lower()
        if "404" in low or "501" in low or "not found" in low:
            return None, "", ("server Gemini chưa có tính năng tạo ảnh — "
                              "chạy `python aistv_web2api.py setup` để vá")
        return None, "", err
    try:
        item = (data.get("data") or [{}])[0]
    except Exception:
        return None, "", "phản hồi tạo ảnh không đúng định dạng"
    raw = b""
    if item.get("b64_json"):
        try:
            raw = base64.b64decode(item["b64_json"])
        except Exception:
            return None, "", "ảnh base64 không hợp lệ"
    elif item.get("url"):
        raw, mime, err = download_image(str(item["url"]), timeout=min(timeout, 120),
                                        allow_any=True)
        if not raw:
            return None, "", err or "không tải được ảnh"
        return raw, mime or "image/png", None
    if not raw:
        return None, "", "server không trả dữ liệu ảnh"
    return raw, _image_mime(raw), None


# ────────────────────────────────────────────────────────────────────
# Lệnh
# ────────────────────────────────────────────────────────────────────
def cmd_import(path: str, push: bool = None) -> int:
    try:
        if path in ("-", "/dev/stdin"):
            raw = sys.stdin.read()
        else:
            raw = Path(path).expanduser().read_text("utf-8", "replace")
    except Exception as exc:
        print(f"Không đọc được file: {exc}")
        return 1
    ok, detail = import_text(raw, push=push)
    print(("Đã nạp: " if ok else "Lỗi: ") + detail)
    return 0 if ok else 2


def status_report() -> dict:
    """Thông tin ngắn cho bot (không in bí mật)."""
    cfg = _read_json(config_path(), {})
    state = _read_json(state_path(), {}) or {}
    running = health(1.5)
    images = image_patch_ready()
    media = media_patch_ready()
    return {
        "enabled": enabled(),
        "url": base_url(),
        "local": is_local(),
        "running": running,
        "images": images,
        "media": media,
        "curl_cffi": has_curl_cffi(),
        "images_ready": bool(images and running and has_curl_cffi()),
        "media_ready": bool(media and running),
        "cookie": bool(cookie_header()),
        "xsrf": bool(cfg.get("xsrf_token")),
        "model": default_model(),
        "synced": bool(state.get("cookie_sig")) and state.get("cookie_sig") == state.get("synced_sig"),
        "cookie_file": str(cookie_path()),
        "store": "/".join(_remote_repo()),
    }


def cmd_doctor() -> int:
    print("== Gemini ==")
    print(f"Runtime      : {runtime_dir()}")
    print(f"Cookie file  : {cookie_path()}")
    print(f"Server       : {base_url()} ({'local' if is_local() else 'remote'})")
    print(f"Đang chạy    : {'có' if health() else 'không'}")
    cfg = _read_json(config_path(), {})
    state = _read_json(state_path(), {}) or {}
    header = cookie_header()
    print(f"Cookie       : {'có' if header else 'chưa có'} ({len(header)} ký tự)")
    print(f"XSRF token   : {'có' if cfg.get('xsrf_token') else 'chưa có'}")
    print(f"Model mặc định: {default_model()}")
    print(f"Xem/tạo ảnh  : {'✅ đã vá' if image_patch_ready() else '❌ chưa vá (chạy setup)'}"
          f" · curl_cffi: {'✅' if has_curl_cffi() else '❌ (pip install curl_cffi)'}")
    print(f"Audio/video  : {'✅ đã vá' if media_patch_ready() else '❌ chưa vá (chạy setup)'}")
    print(f"Đồng bộ      : {'✅' if header and state.get('cookie_sig') and state.get('cookie_sig') == state.get('synced_sig') else '⏳ chưa đẩy'}"
          f" ({'nguyên văn, không mã hoá' if header else 'chưa có cookie'})")
    repo, path = _remote_repo()
    print(f"Repo bí mật  : {repo}/{path}")
    print(f"Token GitHub : {', '.join(s for s, t in _gh_tokens() if t) or 'không có'}")
    if health():
        text, err = chat([{"role": "user", "content": "Trả lời đúng một chữ: OK"}],
                         timeout=90)
        print("Thử chat     : " + (repr(text) if text else "lỗi — " + str(err)))
    return 0


def cmd_test(prompt: str, image: bool = False, out: str = "") -> int:
    if not ensure_server(quiet=False):
        print("Server chưa sẵn sàng.")
        return 2
    if image:
        raw, mime, err = generate_image(prompt, timeout=300)
        if not raw:
            print(f"Lỗi tạo ảnh: {err}")
            return 1
        ext = ".png" if mime == "image/png" else (".jpg" if mime == "image/jpeg" else ".webp")
        path = Path(out).expanduser() if out else Path.cwd() / f"web2api_image_{time.strftime('%Y%m%d_%H%M%S')}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        print(str(path))
        return 0
    text, err = chat([{"role": "user", "content": prompt}], timeout=180)
    print(text if text else f"Lỗi: {err}")
    return 0 if text else 1


def cmd_watch(interval: float = 5.0) -> int:
    """Theo dõi cookie.txt: dán cookie mới là tự nạp lại + chạy server."""
    print(f"Đang theo dõi {cookie_path()} — dán cookie mới là tự chạy (Ctrl+C để dừng).")
    auto(quiet=False)
    last_remote = time.time()
    try:
        while True:
            time.sleep(max(2, interval))
            changed, detail = sync_if_changed(quiet=False)
            if changed:
                ensure_server()
            if time.time() - last_remote > 120:
                pull_if_safe(quiet=True)
                last_remote = time.time()
            if not health():
                ensure_server()
    except KeyboardInterrupt:
        print("Đã dừng theo dõi.")
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Gemini nội bộ + đồng bộ cookie nguyên văn cho AISTV")
    sub = parser.add_subparsers(dest="cmd")

    p_setup = sub.add_parser("setup", help="tải server + tạo config")
    p_setup.add_argument("--force", action="store_true", help="ghi lại config.json")

    p_import = sub.add_parser("import", help="nạp cookie export từ trình duyệt")
    p_import.add_argument("file", nargs="?", default="-",
                          help="file cookie, hoặc - để dán từ stdin")
    p_import.add_argument("--push", action="store_true", help="(mặc định) đẩy cookie lên GitHub")
    p_import.add_argument("--no-push", action="store_true", help="không đẩy lên GitHub")

    p_refresh = sub.add_parser("refresh", help="lấy lại XSRF token")
    p_refresh.add_argument("--push", action="store_true")

    sub.add_parser("push", help="đẩy cookie nguyên văn lên repo private")
    sub.add_parser("pull", help="tải cookie từ repo private")
    sub.add_parser("auto", help="kéo cookie + nạp cookie mới + bật server")
    sub.add_parser("watch", help="theo dõi cookie.txt, dán mới là tự chạy")
    sub.add_parser("start", help="chạy server nền")
    sub.add_parser("stop", help="dừng server")
    sub.add_parser("restart", help="chạy lại server")
    sub.add_parser("status", help="xem trạng thái")
    sub.add_parser("logs", help="xem log server")
    sub.add_parser("doctor", help="kiểm tra tổng thể")
    p_test = sub.add_parser("test", help="gọi thử một request")
    p_test.add_argument("prompt", nargs="?", default="Trả lời đúng một chữ: OK")
    p_test.add_argument("--image", action="store_true", help="thử tạo ảnh thay vì chat")
    p_test.add_argument("--out", default="", help="file ảnh đầu ra khi dùng --image")

    args = parser.parse_args(argv)
    cmd = args.cmd or "status"

    try:
        if cmd == "setup":
            ok, msg = setup(force=args.force)
            print(msg)
            return 0 if ok else 1
        if cmd == "import":
            push = False if args.no_push else None
            return cmd_import(args.file, push=push)
        if cmd == "auto":
            ok, msg = auto(quiet=False)
            return 0 if ok else 2
        if cmd == "watch":
            return cmd_watch()
        if cmd == "refresh":
            ok, msg = refresh_xsrf()
            print(msg)
            if ok:
                _reload_server()
            if ok and args.push:
                pushed, pmsg = push_secrets()
                print("Đồng bộ: " + ("OK → " + pmsg if pushed else "lỗi — " + pmsg))
            return 0 if ok else 2
        if cmd == "push":
            ok, msg = push_secrets()
            print(("Đã đồng bộ → " if ok else "Lỗi: ") + msg)
            return 0 if ok else 1
        if cmd == "pull":
            ok, msg = pull_secrets()
            print(("Đã tải ← " if ok else "Lỗi: ") + msg)
            if ok:
                refresh_xsrf()
                ensure_server(quiet=False)
            return 0 if ok else 1
        if cmd == "start":
            ok, msg = start(quiet=False)
            print(msg)
            return 0 if ok else 1
        if cmd == "stop":
            ok, msg = stop()
            print(msg)
            return 0 if ok else 1
        if cmd == "restart":
            stop()
            ok, msg = start(quiet=False)
            print(msg)
            return 0 if ok else 1
        if cmd == "logs":
            if log_path().exists():
                lines = log_path().read_text("utf-8", "replace").splitlines()[-60:]
                print("\n".join(lines))
            else:
                print("chưa có log")
            return 0
        if cmd == "doctor":
            return cmd_doctor()
        if cmd == "test":
            return cmd_test(args.prompt, image=args.image, out=args.out)
        # status
        cfg = _read_json(config_path(), {})
        state = _read_json(state_path(), {}) or {}
        print(f"Gemini: {'ON' if enabled() else 'OFF'} · {base_url()} · "
              f"{'đang chạy' if health() else 'không chạy'}")
        print(f"Cookie : {'có' if cookie_header() else 'chưa có'} · "
              f"XSRF: {'có' if cfg.get('xsrf_token') else 'chưa có'} · "
              f"model: {default_model()}")
        print(f"File   : {cookie_path()} · "
              f"GitHub: {'đã đồng bộ' if cookie_header() and state.get('cookie_sig') and state.get('cookie_sig') == state.get('synced_sig') else 'chưa đẩy'}")
        return 0
    except RuntimeError as exc:
        print(f"Lỗi: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
