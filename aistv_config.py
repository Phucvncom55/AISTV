#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI STV - đồng bộ cấu hình (token / API key) cho MỌI môi trường.

Một chỗ duy nhất, dùng chung cho:
  • Windows cmd         (run.bat)
  • Windows PowerShell  (run.ps1)
  • Google Colab / Linux / macOS (run.sh)
  • Bot                 (aistv_bot.py gọi khi thiếu token)

Thứ tự ưu tiên khi đọc:
  1. biến môi trường của tiến trình
  2. .env trong repo / thư mục hiện tại / home / STV_HOME
  3. config.env dùng chung
     • Windows : %USERPROFILE%\\.config\\aistv\\config.env
     • Linux   : ~/.config/aistv/config.env
     • Colab   : /content/drive/MyDrive/aistv/config.env (nếu đã mount Drive)

Nguồn tải từ xa (theo thứ tự):
  0. Kho cấu hình mã hoá (mặc định Firebase RTDB `aistv/secrets`, khoá là
     TELEGRAM_BOT_TOKEN) — máy mới chỉ cần token bot là khôi phục đủ GitHub PAT,
     Gemini, Cloudflare, email… KHÔNG phải đăng nhập GitHub bằng mã.
     Tắt: AISTV_VAULT=0 · đổi nơi lưu: AISTV_VAULT_URL
     Token bot có thể đặt sẵn (không nhập tay) ở: AISTV_BOOTSTRAP_TOKEN,
     $STV_HOME/.secrets/bootstrap_token, ~/.config/aistv/token, ~/.aistv_token,
     /content/.aistv_token, /content/drive/MyDrive/aistv/token (xem bootstrap_token).
  1. AISTV_ENV_URL      - URL công khai trả về nội dung config.env
  2. AISTV_CONFIG_REPO  - repo private, mặc định Phucvncom55/AISTV-secrets
     Xác thực bằng (theo thứ tự): AISTV_CONFIG_TOKEN → GH_TOKEN / GITHUB_TOKEN
     → .secrets/github_token → `gh auth token` → Colab Secrets.
     Không có nguồn nào → tự chạy GitHub device login (github.com/login/device),
     in mã, chờ bạn xác nhận rồi lưu token (AISTV_DEVICE_LOGIN=0 để tắt).

Lệnh:
  python aistv_config.py sync [--quiet]   # nạp + đồng bộ, exit 0 nếu có token bot
  python aistv_config.py check            # im lặng, exit 0/2
  python aistv_config.py get KEY          # in giá trị (script khác dùng)
  python aistv_config.py set KEY --from-env VAR | --stdin
  python aistv_config.py vault status|push|pull   # kho cấu hình mã hoá
  python aistv_config.py doctor           # xem nguồn cấu hình (không in bí mật)
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:                                    # Windows cmd luôn in được tiếng Việt
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_REPO = "Phucvncom55/AISTV-secrets"
DEFAULT_PATH = "config.env"
CONFIG_JSON_NAME = "config.json"
CORE_KEYS = ("TELEGRAM_BOT_TOKEN",)
HTTP_TIMEOUT = 20
USER_AGENT = "aistv-config/1.0"

# Device login (giống `gh auth login`): dùng client công khai của GitHub CLI.
GH_CLIENT_ID = os.getenv("AISTV_GH_CLIENT_ID", "178c6fc778ccc68e1d6a")
GH_SCOPES = os.getenv("AISTV_GH_SCOPES", "repo workflow read:user")
DEVICE_TIMEOUT = int(os.getenv("AISTV_DEVICE_TIMEOUT", "600") or 600)
_DEVICE_ATTEMPTED = False

# ── Kho cấu hình mã hoá (khôi phục trên máy mới, KHÔNG cần mã GitHub) ──
# Bot đẩy các bí mật đã mã hoá bằng TELEGRAM_BOT_TOKEN lên Firebase RTDB.
# Máy mới chỉ cần token bot (env / .env / Colab Secrets) là đọc lại được
# toàn bộ: GitHub PAT, Gemini key, Cloudflare, email, Firebase URL…
# Endpoint công khai chỉ trả blob đã mã hoá; thiếu token bot thì không mở được.
# Ghi đè bằng biến môi trường AISTV_VAULT_URL nếu đổi database.
VAULT_DEFAULT_URL = "https://sever-login-ae5cc-default-rtdb.firebaseio.com"
VAULT_PATH = "aistv/secrets.json"
VAULT_SALT = b"aistv-secrets-v1"
VAULT_ITER = 120_000


# ────────────────────────────────────────────────────────────────────
# Đường dẫn
# ────────────────────────────────────────────────────────────────────
def repo_dir() -> Path:
    return Path(__file__).resolve().parent


def config_dir() -> Path:
    """Thư mục cấu hình dùng chung (giống run.sh / bot)."""
    override = (os.getenv("AISTV_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    # Colab có Drive đã mount → cấu hình sống qua các phiên.
    drive = Path("/content/drive/MyDrive")
    try:
        if drive.is_dir():
            return drive / "aistv"
    except Exception:
        pass
    if os.name != "nt":
        xdg = (os.getenv("XDG_CONFIG_HOME") or "").strip()
        if xdg:
            return Path(xdg).expanduser() / "aistv"
    return Path.home() / ".config" / "aistv"


def shared_config_path() -> Path:
    return config_dir() / "config.env"


def env_files(repo: Path = None) -> list:
    repo = Path(repo or repo_dir())
    files = [
        repo / ".env",
        Path.cwd() / ".env",
        Path.home() / ".env",
    ]
    stv = (os.getenv("STV_HOME") or "").strip()
    if stv:
        files.append(Path(stv).expanduser() / ".env")
    files.append(shared_config_path())
    seen, out = set(), []
    for path in files:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def config_json_files(repo: Path = None) -> list:
    """File config.json, ưu tiên repo > thư mục hiện tại > config_dir."""
    override = (os.getenv("AISTV_CONFIG_JSON") or "").strip()
    if override:
        return [Path(override).expanduser()]
    repo = Path(repo or repo_dir())
    files = [repo / CONFIG_JSON_NAME,
             Path.cwd() / CONFIG_JSON_NAME,
             config_dir() / CONFIG_JSON_NAME]
    seen, out = set(), []
    for path in files:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def parse_config_json(text: str) -> dict:
    """Đọc config.json dạng phẳng: {"TELEGRAM_BOT_TOKEN": "..."}."""
    data = json.loads((text or "").lstrip("\ufeff"))
    if not isinstance(data, dict):
        return {}
    values = {}
    for name, value in data.items():
        if not isinstance(name, str) or not _KEY_RE.match(name):
            continue
        if value is None or isinstance(value, (dict, list, bool)):
            continue
        value = str(value).strip()
        if value:
            values[name] = value
    return values


def config_source_paths(repo: Path = None) -> list:
    """Các nguồn cấu hình theo thứ tự ưu tiên giảm dần (để chẩn đoán)."""
    return config_json_files(repo) + env_files(repo)


def describe_config_sources(repo: Path = None) -> list:
    """Mô tả từng nguồn: tồn tại/đọc được/JSON hợp lệ hay không."""
    repo = Path(repo or repo_dir())
    env_set = bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip())
    lines = [f"  - env TELEGRAM_BOT_TOKEN: "
             f"{'đã đặt' if env_set else 'không đặt'}"]
    for path in config_source_paths(repo):
        try:
            if not path.is_file():
                lines.append(f"  - {path}: không có")
                continue
            text = path.read_text("utf-8", "replace")
            if path.suffix.lower() == ".json":
                try:
                    parse_config_json(text)
                except Exception as e:
                    lines.append(f"  - {path}: JSON lỗi ({e})")
                    continue
            lines.append(f"  - {path}: có")
        except OSError as e:
            lines.append(f"  - {path}: không đọc được ({e.strerror or e})")
    return lines


# ────────────────────────────────────────────────────────────────────
# Đọc / ghi file .env
# ────────────────────────────────────────────────────────────────────
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BOT_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


def valid_bot_token(value: str) -> bool:
    """Token BotFather có dạng 123456789:AAH... — chặn dán nhầm lệnh khác."""
    return bool(BOT_TOKEN_RE.match((value or "").strip()))


def parse_env_text(text: str) -> dict:
    values = {}
    for raw in (text or "").lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not _KEY_RE.match(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name] = value
    return values


def read_files(repo: Path = None):
    """Trả về (values, sources).

    Ưu tiên tăng dần: config.env dùng chung < .env home/STV/cwd < .env repo
    < config.json (repo > cwd > config_dir). Biến môi trường do get_value xử lý.
    """
    values, sources = {}, {}
    data_paths = list(reversed(env_files(repo)))
    data_paths += list(reversed(config_json_files(repo)))
    for path in data_paths:
        try:
            if not path.is_file():
                continue
            text = path.read_text("utf-8", "replace")
            parsed = (parse_config_json(text) if path.suffix.lower() == ".json"
                      else parse_env_text(text))
            for name, value in parsed.items():
                values[name] = value
                sources[name] = path
        except Exception:
            continue
    return values, sources


def format_value(value: str) -> str:
    value = str(value)
    if value == "" or re.search(r"[\s#\"'`$]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def write_env_var(path: Path, name: str, value: str) -> bool:
    """Ghi/cập nhật một biến, giữ nguyên comment và thứ tự file."""
    try:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text("utf-8", "replace").splitlines() if path.is_file() else []
        new_line = f"{name}={format_value(value)}"
        found, out = False, []
        for line in lines:
            stripped = line.strip()
            probe = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
            if probe.startswith(name + "="):
                if not found:
                    out.append(new_line)
                    found = True
                continue
            out.append(line)
        if not found:
            if out and out[-1].strip():
                out.append("")
            out.append(new_line)
        if not lines:
            out.insert(0, "# AI STV - cau hinh dung chung (cmd / PowerShell / Colab / Linux)")
            out.insert(1, "# File do aistv_config.py tao va cap nhat tu dong.")
            out.insert(2, "")
        path.write_text("\n".join(out).rstrip() + "\n", "utf-8")
        try:
            if os.name != "nt":
                path.chmod(0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False


def save_values(values: dict, repo: Path = None, protected=None) -> int:
    """Ghi các giá trị vào config.env + .env của repo.

    `protected` là tập biến môi trường không được ghi đè (mặc định: mọi biến
    đang có trong tiến trình). Bot truyền vào các biến thật sự do người dùng
    đặt, để còn cập nhật được các key đọc từ file.

    Chỉ ghi khi khác với nội dung hiện có để lần chạy sau không đụng file.
    Trả về số tên biến thực sự thay đổi.
    """
    repo = Path(repo or repo_dir())
    if protected is None:
        protected = set(os.environ)
    protected = set(protected)
    targets = [shared_config_path(), repo / ".env"]
    changed = set()
    for name, value in values.items():
        if not value or not _KEY_RE.match(name):
            continue
        if name == "TELEGRAM_BOT_TOKEN" and not valid_bot_token(value):
            continue                      # không ghi token rác đè token tốt
        if name in protected:
            continue                      # biến môi trường do người dùng đặt
        for path in targets:
            current = ""
            try:
                if path.is_file():
                    current = parse_env_text(path.read_text("utf-8", "replace")).get(name, "")
            except Exception:
                current = ""
            if current != value:
                if write_env_var(path, name, value):
                    changed.add(name)
    return len(changed)


# ────────────────────────────────────────────────────────────────────
# Tải cấu hình từ xa
# ────────────────────────────────────────────────────────────────────
def _colab_available() -> bool:
    return Path("/content").is_dir() or bool(os.getenv("COLAB_RELEASE_TAG"))


def colab_secret(name: str) -> str:
    if not _colab_available():
        return ""
    try:
        from google.colab import userdata       # type: ignore
        return (userdata.get(name) or "").strip()
    except Exception:
        return ""


def bootstrap_token_files() -> list:
    """Các file có thể chứa token bot đặt sẵn (theo thứ tự ưu tiên)."""
    out = []
    stv = (os.getenv("STV_HOME") or "").strip()
    if stv:
        out.append(Path(stv).expanduser() / ".secrets" / "bootstrap_token")
    out += [
        Path("/content/stv_agent/.secrets/bootstrap_token"),
        config_dir() / "token",
        repo_dir() / ".secrets" / "bootstrap_token",
        Path.home() / ".secrets" / "bootstrap_token",
        Path.home() / ".aistv_token",
        Path("/content/.aistv_token"),
        Path("/content/drive/MyDrive/aistv/token"),
        Path("/content/drive/MyDrive/.aistv/token"),
    ]
    return out


def bootstrap_token() -> str:
    """Token bot đặt sẵn trong máy ảnh / ổ đĩa dùng chung (không cần nhập tay).

    Tìm theo thứ tự: biến môi trường AISTV_BOOTSTRAP_TOKEN → file token trong
    thư mục cấu hình / home / Drive → repo cấu hình private (nếu có GitHub
    token). Chỉ nhận token đúng định dạng BotFather.
    """
    for name in ("AISTV_BOOTSTRAP_TOKEN", "AISTV_BOT_TOKEN"):
        value = (os.getenv(name) or "").strip()
        if valid_bot_token(value):
            return value
    for path in bootstrap_token_files():
        try:
            if not path.is_file():
                continue
            first = path.read_text("utf-8", "replace").strip().splitlines()
            value = (first[0] if first else "").strip()
            if valid_bot_token(value):
                return value
        except Exception:
            continue
    return repo_bot_token()


_REPO_BOT_TOKEN = None


def repo_bot_token(values: dict = None) -> str:
    """Lấy TELEGRAM_BOT_TOKEN trong repo cấu hình private bằng GitHub token có sẵn.

    Nhờ vậy máy mới chỉ cần MỘT bí mật duy nhất là GitHub token (đã cần sẵn để
    clone repo code / đọc repo cấu hình) — không phải nhập lại token bot.
    Không tự mở đăng nhập GitHub; không có token sẵn → trả về "".
    """
    global _REPO_BOT_TOKEN
    if _REPO_BOT_TOKEN is not None:
        return _REPO_BOT_TOKEN
    _REPO_BOT_TOKEN = ""
    if (os.getenv("AISTV_BOOT_REPO") or "1").strip().lower() in ("0", "off", "false", "no"):
        return ""
    values = values or {}
    repo = _pick("AISTV_CONFIG_REPO", values) or DEFAULT_REPO
    if repo.lower() in ("0", "off", "none", "false"):
        return ""
    path = _pick("AISTV_CONFIG_PATH", values) or DEFAULT_PATH
    try:
        tokens = github_tokens(values)[:4]
    except Exception:
        tokens = []
    for _source, token in tokens:
        try:
            text, _status = fetch_github_status(repo, path, token)
        except Exception:
            continue
        value = (parse_env_text(text).get("TELEGRAM_BOT_TOKEN") or "").strip()
        if valid_bot_token(value):
            _REPO_BOT_TOKEN = value
            return value
    return ""


def _pick(name: str, values: dict) -> str:
    return ((os.getenv(name) or "").strip()
            or (values or {}).get(name, "").strip()
            or colab_secret(name))


def stored_github_token() -> str:
    """Token bot đã lưu sau /github login — dùng được cả khi máy không có gh."""
    stv = (os.getenv("STV_HOME") or "").strip()
    candidates = [Path("/content/drive/MyDrive/stv_agent/.secrets/github_token"),
                  Path("/content/stv_agent/.secrets/github_token"),
                  Path.home() / "stv_agent" / ".secrets" / "github_token",
                  Path.home() / ".secrets" / "github_token",
                  repo_dir() / ".secrets" / "github_token"]
    if stv:
        candidates.insert(0, Path(stv).expanduser() / ".secrets" / "github_token")
    for path in candidates:
        try:
            if path.is_file():
                token = path.read_text("utf-8").strip()
                if token:
                    return token
        except Exception:
            continue
    return ""


def github_tokens(values: dict = None) -> list:
    """Các cặp (nguồn, token) có thể dùng để đọc repo private."""
    values = values or {}
    seen, out = set(), []
    for name in ("AISTV_CONFIG_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "AISTV_GITHUB_TOKEN"):
        for source, token in (
            ("env " + name, (os.getenv(name) or "").strip()),
            ("config.env " + name, (values.get(name) or "").strip()),
            ("Colab Secrets " + name, colab_secret(name)),
        ):
            if token and token not in seen:
                seen.add(token)
                out.append((source, token))
    stored = stored_github_token()
    if stored and stored not in seen:
        seen.add(stored)
        out.append(("file .secrets/github_token", stored))
    gh = shutil.which("gh")
    if gh:
        try:
            token = subprocess.run([gh, "auth", "token"], capture_output=True, text=True,
                                   timeout=15).stdout.strip()
            if token and token not in seen:
                seen.add(token)
                out.append(("gh auth token", token))
        except Exception:
            pass
    return out


def _http_get(url: str, headers: dict = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def _copy_to_clipboard(text: str) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(["clip"], input=text, text=True, timeout=5,
                       capture_output=True, check=False)
    except Exception:
        pass


def github_device_login(timeout: int = None, log=None) -> str:
    """Đăng nhập GitHub bằng mã (device flow) và trả về token.

    Cùng luồng với `gh auth login --web`: in mã, chờ người dùng nhập trên
    github.com/login/device, rồi tự đi tiếp. Không bao giờ in token.
    """
    global _DEVICE_ATTEMPTED
    if _DEVICE_ATTEMPTED:
        return ""
    if os.getenv("AISTV_DEVICE_LOGIN", "1").strip().lower() in ("0", "off", "false", "no"):
        return ""
    _DEVICE_ATTEMPTED = True
    say = log or (lambda message: print(message, flush=True))
    try:
        start = _post_form("https://github.com/login/device/code",
                           {"client_id": GH_CLIENT_ID, "scope": GH_SCOPES})
    except Exception as e:
        say(f"[config] Không xin được mã đăng nhập GitHub: {type(e).__name__}.")
        return ""
    user_code = str(start.get("user_code") or "").strip()
    url = str(start.get("verification_uri") or "https://github.com/login/device").strip()
    if not user_code:
        say("[config] GitHub không trả về mã đăng nhập.")
        return ""
    interval = max(5, int(start.get("interval") or 5))
    expires = min(int(timeout or DEVICE_TIMEOUT), int(start.get("expires_in") or 900))
    _copy_to_clipboard(user_code)
    say("")
    say("🔑 Cần đăng nhập GitHub để lấy token/API key từ repo private.")
    say(f"   1. Mở: {url}")
    say(f"   2. Nhập mã: {user_code}")
    say("   3. Bấm Authorize — script tự chạy tiếp, không cần làm gì thêm.")
    say("   (chỉ cần một lần — token được lưu lại cho các lần chạy sau)")
    say(f"   (chờ tối đa {expires}s · AISTV_DEVICE_LOGIN=0 để bỏ qua)")
    say("")
    deadline = time.time() + expires
    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = _post_form("https://github.com/login/oauth/access_token", {
                "client_id": GH_CLIENT_ID,
                "device_code": str(start.get("device_code") or ""),
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except Exception:
            continue
        err = str(r.get("error") or "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            say(f"[config] Đăng nhập GitHub thất bại: {err}")
            return ""
        token = str(r.get("access_token") or "").strip()
        if token:
            say("[config] ✅ Đã đăng nhập GitHub — tiếp tục đồng bộ cấu hình.")
            return token
    say("[config] ⏱ Hết thời gian chờ đăng nhập GitHub — sẽ thử lại lần chạy sau.")
    return ""


def _remember_config_token(token: str, values: dict = None) -> list:
    """Lưu token vừa đăng nhập để lần chạy sau không phải đăng nhập lại.

    Ghi vào config.env dùng chung, .env của repo và .secrets/github_token
    ($STV_HOME + repo) — nơi nào còn tồn tại là lần sau dùng lại được.
    """
    values = values if values is not None else {}
    os.environ.setdefault("AISTV_CONFIG_TOKEN", token)
    values.setdefault("AISTV_CONFIG_TOKEN", token)
    saved = []
    has_gh = bool((os.getenv("GITHUB_TOKEN") or "").strip()
                  or (values.get("GITHUB_TOKEN") or "").strip())
    for path in (shared_config_path(), repo_dir() / ".env"):
        if write_env_var(path, "AISTV_CONFIG_TOKEN", token):
            saved.append(path)
        if not has_gh and write_env_var(path, "GITHUB_TOKEN", token):
            saved.append(path)
    # File token riêng: stored_github_token() và bot /github login cùng đọc.
    for base in (Path(os.getenv("STV_HOME") or "").expanduser() if os.getenv("STV_HOME")
                 else Path.home() / "stv_agent", repo_dir()):
        try:
            path = base / ".secrets" / "github_token"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token + "\n", "utf-8")
            try:
                if os.name != "nt":
                    path.chmod(0o600)
            except Exception:
                pass
            saved.append(path)
        except Exception:
            continue
    return saved


def _persist_warning(log=None) -> None:
    """Cảnh báo khi thư mục cấu hình không sống qua lần chạy sau."""
    if not log:
        return
    shared = str(shared_config_path())
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
        log("[config] ⚠ Railway không giữ file khi redeploy: đặt TELEGRAM_BOT_TOKEN "
            "trong Variables — máy mới chỉ cần token bot là tự khôi phục phần còn lại.")
    elif Path("/content").is_dir() and not shared.startswith("/content/drive"):
        log("[config] ⚠ Colab không giữ file giữa các phiên: đặt TELEGRAM_BOT_TOKEN trong "
            "🔑 Secrets (bật Notebook access) là đủ — các key khác tự khôi phục từ kho mã hoá. "
            "Muốn giữ cả file: mount Drive.")


def normalize_repo(repo: str) -> str:
    repo = (repo or "").strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if repo.lower().startswith(prefix):
            repo = repo[len(prefix):]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo


def prompt_bot_token(log=None) -> str:
    """Hỏi token bot khi chưa có nguồn nào (Colab: input() hiện ô nhập).

    Chỉ chạy khi có terminal hoặc đang ở Colab — CI/daemon không bị treo.
    """
    if os.getenv("AISTV_ASK_TOKEN", "1").strip().lower() in ("0", "off", "false", "no"):
        return ""
    try:
        interactive = sys.stdin.isatty()
    except Exception:
        interactive = False
    if not interactive and not _colab_available():
        return ""
    say = lambda message: print(message, flush=True)   # luôn hiện: đây là prompt
    say("🔑 Chưa có Telegram Bot Token.")
    say("   • Bot đã tạo: https://t.me/BotFather → /mybots → API Token")
    say("   • Tạo mới   : /newbot → đặt tên → copy token")
    say("   Dán một lần: GitHub/Gemini/Cloudflare… tự khôi phục, KHÔNG cần mã GitHub.")
    try:
        value = re.sub(r"\s+", "", input("   Token (Enter để bỏ qua): "))
    except (EOFError, OSError, KeyboardInterrupt):
        return ""
    if not value:
        return ""
    if not valid_bot_token(value):
        say("⚠ Token không đúng định dạng (phải dạng 123456:ABC...) — không lưu.")
        return ""
    os.environ["TELEGRAM_BOT_TOKEN"] = value
    saved = [p for p in (shared_config_path(), repo_dir() / ".env")
             if write_env_var(p, "TELEGRAM_BOT_TOKEN", value)]
    if saved:
        say("✅ Đã lưu token vào: " + ", ".join(str(p) for p in saved))
        say("   Lần sau không cần nhập lại.")
    else:
        say("⚠ Không ghi được file cấu hình — token chỉ dùng cho lần chạy này.")
    return value


def _vault_base(values: dict = None) -> str:
    """Endpoint kho cấu hình (không phải bí mật — dữ liệu trong đó đã mã hoá)."""
    values = values or {}
    return ((os.getenv("AISTV_VAULT_URL") or "").strip()
            or str(values.get("AISTV_VAULT_URL") or "").strip()
            or VAULT_DEFAULT_URL).rstrip("/")


def _vault_endpoint(values: dict = None) -> str:
    base = _vault_base(values)
    if not base:
        return ""
    url = f"{base}/{VAULT_PATH.lstrip('/')}"
    secret = ((os.getenv("AISTV_FIREBASE_SECRET") or "").strip()
              or str((values or {}).get("AISTV_FIREBASE_SECRET") or "").strip())
    if secret:
        url += "?auth=" + urllib.parse.quote(secret)
    return url


def _vault_keys(token: str) -> tuple:
    master = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), VAULT_SALT, VAULT_ITER)
    return (hmac.new(master, b"enc", hashlib.sha256).digest(),
            hmac.new(master, b"mac", hashlib.sha256).digest())


def _vault_stream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = bytearray()
    block = 0
    while len(out) < size:
        out += hmac.new(key, nonce + block.to_bytes(8, "big"), hashlib.sha256).digest()
        block += 1
    return bytes(out[:size])


def vault_encrypt(data: dict, token: str) -> str:
    """Mã hoá JSON bằng token bot — cùng định dạng blob của aistv_bot._seal."""
    enc, mac = _vault_keys(token)
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(raw, _vault_stream(enc, nonce, len(raw))))
    tag = hmac.new(mac, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + ct).decode("ascii")


def vault_decrypt(blob: str, token: str) -> dict:
    raw = base64.b64decode(blob)
    if len(raw) < 48:
        raise ValueError("dữ liệu quá ngắn")
    nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
    enc, mac = _vault_keys(token)
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("sai khoá hoặc dữ liệu bị sửa")
    plain = bytes(a ^ b for a, b in zip(ct, _vault_stream(enc, nonce, len(ct))))
    data = json.loads(plain.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _http_json(url: str, data=None, method: str = "GET", timeout: int = HTTP_TIMEOUT):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else None


def vault_token(values: dict = None) -> str:
    """Token bot dùng làm khoá mã hoá kho cấu hình."""
    values = values or {}
    token = ((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
             or str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
             or colab_secret("TELEGRAM_BOT_TOKEN")
             or bootstrap_token())
    return token if valid_bot_token(token) else ""


def vault_restore(values: dict = None, log=None) -> dict:
    """Đọc + giải mã kho cấu hình. Không có token bot / lỗi mạng → {}."""
    values = values or {}
    token = vault_token(values)
    url = _vault_endpoint(values)
    if not token or not url:
        return {}
    try:
        payload = _http_json(url)
    except urllib.error.HTTPError as e:
        if log:
            log(f"[config] Kho cấu hình: HTTP {e.code} — bỏ qua, dùng nguồn khác.")
        return {}
    except Exception:
        return {}
    if not isinstance(payload, dict) or not payload.get("blob"):
        return {}
    try:
        data = vault_decrypt(str(payload["blob"]), token)
    except Exception:
        if log:
            log("[config] Kho cấu hình không giải mã được (token bot đã đổi?) — bỏ qua.")
        return {}
    out = {}
    for name, value in data.items():
        name, value = str(name), str(value or "").strip()
        if name == "TELEGRAM_BOT_TOKEN" or not value or not _KEY_RE.match(name):
            continue
        out[name] = value
    if out and log:
        log(f"[config] Khôi phục {len(out)} mục từ kho cấu hình mã hoá "
            "(không cần đăng nhập GitHub).")
    return out


def vault_push(values: dict = None, token: str = "", log=None) -> bool:
    """Mã hoá + ghi kho cấu hình. Không in giá trị bí mật."""
    values = dict(values or {})
    token = token or vault_token(values)
    url = _vault_endpoint(values)
    if not token or not url:
        return False
    data = {k: v for k, v in values.items()
            if v and _KEY_RE.match(k)
            and k not in ("TELEGRAM_BOT_TOKEN", "AISTV_VAULT_URL")}
    if not data:
        return False
    blob = vault_encrypt(data, token)
    try:
        _http_json(url, {"v": 1, "at": int(time.time()), "blob": blob}, "PUT")
    except Exception as e:
        if log:
            log(f"[config] Không ghi được kho cấu hình: {type(e).__name__}.")
        return False
    if log:
        log(f"[config] Đã cập nhật kho cấu hình ({len(data)} mục, mã hoá bằng token bot).")
    return True


def fetch_url(url: str) -> str:
    try:
        return _http_get(url)
    except Exception:
        return ""


def fetch_github_status(repo: str, path: str, token: str = "") -> tuple:
    """Tải file trong repo → (nội dung, mã HTTP). Mã 0 = lỗi mạng."""
    repo = normalize_repo(repo)
    path = (path or DEFAULT_PATH).lstrip("/")
    if not repo or ".." in path:
        return "", 0
    quoted = urllib.parse.quote(path)
    headers = {"Accept": "application/vnd.github.raw"}
    if token:
        headers["Authorization"] = "Bearer " + token
    status = 0
    try:
        text = _http_get(f"https://api.github.com/repos/{repo}/contents/{quoted}", headers)
        if "=" in text:
            return text, 200
        return text, 204
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = 0
    if status in (401, 403):
        return "", status            # token sai/thiếu quyền → raw cũng không đọc được
    try:
        text = _http_get(f"https://raw.githubusercontent.com/{repo}/HEAD/{quoted}")
        if "=" in text:
            return text, 200
        return text, 204
    except urllib.error.HTTPError as e:
        return "", e.code
    except Exception:
        return "", status


def fetch_github(repo: str, path: str = DEFAULT_PATH, token: str = "") -> str:
    return fetch_github_status(repo, path, token)[0]


def fetch_remote(values: dict = None, log=None) -> tuple:
    """Tải cấu hình từ xa → (values, nhãn nguồn).

    AISTV_ENV_URL thắng các key nó có; repo chỉ bổ sung key còn thiếu.
    """
    values = values or {}
    merged, labels = {}, []
    url = _pick("AISTV_ENV_URL", values)
    if url:
        text = fetch_url(url)
        data = parse_env_text(text)
        if data:
            merged.update(data)
            labels.append("AISTV_ENV_URL")

    repo = _pick("AISTV_CONFIG_REPO", values) or DEFAULT_REPO
    if repo.lower() not in ("0", "off", "none", "false"):
        path = _pick("AISTV_CONFIG_PATH", values) or DEFAULT_PATH
        tokens = github_tokens(values)
        # Máy đã có cấu hình cục bộ (token bot) thì không chặn 10 phút chờ đăng nhập
        # GitHub chỉ để làm mới cấu hình — bot vẫn chạy bình thường.
        if not tokens and _have_token(values):
            if log:
                log("[config] Đã có cấu hình cục bộ — bỏ qua đăng nhập GitHub. "
                    "Muốn đồng bộ repo private: đặt AISTV_CONFIG_TOKEN hoặc `gh auth login`.")
            return merged, labels
        # Chưa có nguồn token nào → đăng nhập GitHub bằng mã một lần rồi tiếp tục.
        if not tokens:
            token = github_device_login(log=log)
            if token:
                saved = _remember_config_token(token, values)
                if log:
                    if saved:
                        log("[config] Đã lưu token đăng nhập vào: "
                            + ", ".join(str(p) for p in saved[:3]))
                    else:
                        log("[config] ⚠ Không ghi được token đăng nhập xuống đĩa.")
                _persist_warning(log)
                tokens = [("GitHub device login", token)]
        explicit = bool((os.getenv("AISTV_CONFIG_REPO") or values.get("AISTV_CONFIG_REPO") or "").strip())
        if tokens or explicit:
            candidates = tokens or [("không xác thực", "")]
            for source, token in candidates:
                text, status = fetch_github_status(repo, path, token)
                data = parse_env_text(text)
                if data:
                    for name, value in data.items():
                        if value and not merged.get(name):
                            merged[name] = value
                    labels.append(f"GitHub {repo}" + (f" ({source})" if source != "không xác thực" else ""))
                    break
                if log:
                    if status == 404:
                        log(f"[config] Không đọc được {repo}/{path} bằng {source}: HTTP 404 "
                            "— token thiếu quyền Contents:Read hoặc file không tồn tại.")
                    elif status == 401 or status == 403:
                        log(f"[config] Không đọc được {repo}/{path} bằng {source}: HTTP {status} "
                            "— token hết hạn hoặc thiếu quyền.")
                    elif status == 0:
                        log(f"[config] Không kết nối được GitHub bằng {source} (lỗi mạng).")
                    else:
                        log(f"[config] Không đọc được {repo}/{path} bằng {source}: HTTP {status}.")
    if log and not labels:
        log("Chưa có nguồn cấu hình từ xa (chưa đăng nhập GitHub / chưa có "
            "AISTV_CONFIG_TOKEN / AISTV_ENV_URL) — dùng cấu hình sẵn có.")
    return merged, labels


# ────────────────────────────────────────────────────────────────────
# API cho runner / bot
# ────────────────────────────────────────────────────────────────────
def _have_token(values: dict = None) -> bool:
    values = values or {}
    token = ((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
             or (values.get("TELEGRAM_BOT_TOKEN") or "").strip()
             or colab_secret("TELEGRAM_BOT_TOKEN")
             or bootstrap_token())
    return valid_bot_token(token)


def sync(quiet: bool = False, repo: Path = None, offline: bool = False, protected=None) -> dict:
    """Đọc file + tải cấu hình từ xa (nếu có) và ghi lại.

    Trả về dict: ok, have_token, added, sources, path, values.
    `values` chỉ dùng nội bộ (bot cập nhật env) — CLI không in ra.
    Không bao giờ in giá trị bí mật.
    """
    def log(message):
        if not quiet:
            print(message, flush=True)

    values, _sources = read_files(repo)

    # Colab Secrets: lấy token bot / PAT / URL một lần rồi lưu xuống config.env
    # (Drive) để các phiên sau không phụ thuộc quyền đọc Secrets.
    colab_values = {}
    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_IDS", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "AISTV_CONFIG_TOKEN", "AISTV_ENV_URL",
                 "AISTV_CONFIG_REPO", "AISTV_CONFIG_PATH"):
        value = colab_secret(name)
        if value:
            colab_values[name] = value
    values.update({k: v for k, v in colab_values.items() if not values.get(k)})

    added, labels = 0, []
    remote = {}
    vault = {}
    if not offline:
        # 0) Chưa có token bot ở đâu cả → hỏi một lần (Colab hiện ô nhập),
        #    thay vì bắt đăng nhập GitHub bằng mã.
        if not vault_token(values) and not os.getenv("AISTV_TOKEN_ASKED"):
            os.environ["AISTV_TOKEN_ASKED"] = "1"
            if not quiet:
                log("[config] Chưa thấy TELEGRAM_BOT_TOKEN. Đã kiểm tra:")
                for line in describe_config_sources(repo):
                    log(line)
            if prompt_bot_token(log=log):
                values["TELEGRAM_BOT_TOKEN"] = os.environ["TELEGRAM_BOT_TOKEN"]
        # 1) Kho cấu hình mã hoá: máy mới chỉ cần token bot là đủ.
        if os.getenv("AISTV_VAULT", "1").strip().lower() not in ("0", "off", "false", "no"):
            vault = vault_restore(values, log=log)
        for name, value in vault.items():
            if value and not values.get(name):
                values[name] = value
        if vault:
            labels.append("kho cấu hình mã hoá")
    if not offline and os.getenv("AISTV_CONFIG_SYNC", "1").lower() not in ("0", "off", "false"):
        remote, remote_labels = fetch_remote(values, log=log)
        labels.extend(remote_labels)
    to_save = dict(colab_values)
    if vault:
        to_save.update({k: v for k, v in vault.items() if v and not to_save.get(k)})
    to_save.update({k: v for k, v in remote.items() if v})
    if remote.get("TELEGRAM_BOT_TOKEN") and not valid_bot_token(remote["TELEGRAM_BOT_TOKEN"]):
        log("[config] Cảnh báo: TELEGRAM_BOT_TOKEN trên GitHub sai định dạng — giữ token cũ.")
    to_save = {k: v for k, v in to_save.items()
               if v and not (k == "TELEGRAM_BOT_TOKEN" and not valid_bot_token(v))}
    if to_save:
        added = save_values(to_save, repo, protected=protected)
        values.update(to_save)
        if label_text := ", ".join(filter(None, labels + (["Colab Secrets"] if colab_values else []))):
            if added:
                log(f"[config] Đã đồng bộ {added} mục từ {label_text} → {shared_config_path()}")
            elif remote:
                log(f"[config] Cấu hình đã khớp với {label_text}.")

    ok = _have_token(values)
    if not quiet:
        if ok:
            log(f"[config] Telegram Bot Token: có · file dùng chung: {shared_config_path()}")
        else:
            log("[config] Telegram Bot Token: chưa có.")
    return {"ok": ok, "have_token": ok, "added": added,
            "sources": labels, "path": str(shared_config_path()),
            "values": dict(to_save)}


def get_value(name: str, repo: Path = None) -> str:
    if (os.getenv(name) or "").strip():
        return os.getenv(name, "").strip()
    values, _sources = read_files(repo)
    if (values.get(name) or "").strip():
        return values[name].strip()
    return colab_secret(name)


def set_value(name: str, value: str, repo: Path = None) -> bool:
    if not _KEY_RE.match(name or "") or not value:
        return False
    if name == "TELEGRAM_BOT_TOKEN" and not valid_bot_token(value):
        return False
    wrote = False
    for path in (shared_config_path(), Path(repo or repo_dir()) / ".env"):
        wrote = write_env_var(path, name, value) or wrote
    return wrote


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────
def _mask(value: str) -> str:
    if not value:
        return "(trống)"
    return f"đã đặt ({len(value)} ký tự)"


def cmd_doctor(repo: Path = None) -> int:
    repo = Path(repo or repo_dir())
    values, sources = read_files(repo)
    print("== AI STV config ==")
    print(f"Repo            : {repo}")
    print(f"Config dùng chung: {shared_config_path()} "
          f"({'có' if shared_config_path().is_file() else 'chưa có'})")
    print(f".env của repo   : {repo / '.env'} "
          f"({'có' if (repo / '.env').is_file() else 'chưa có'})")
    print(f"config.json     : {repo / CONFIG_JSON_NAME} "
          f"({'có' if (repo / CONFIG_JSON_NAME).is_file() else 'chưa có'})")
    print("Nguồn cấu hình (ưu tiên giảm dần):")
    for line in describe_config_sources(repo):
        print(line)
    tokens = github_tokens(values)
    print("Token GitHub    : " + (", ".join(s for s, _ in tokens) if tokens else "không có"))
    print(f"AISTV_ENV_URL   : {'có' if _pick('AISTV_ENV_URL', values) else 'chưa đặt'}")
    base = _vault_base(values)
    host = base.split("//")[-1] if base else ""
    print(f"Kho cấu hình    : {host or '(chưa cấu hình)'}")
    if base:
        token = vault_token(values)
        if not token:
            print("  trạng thái    : cần TELEGRAM_BOT_TOKEN để mở kho")
        else:
            try:
                payload = _http_json(_vault_endpoint(values))
            except urllib.error.HTTPError as e:
                payload, note = None, f"HTTP {e.code}"
            except Exception:
                payload, note = None, "lỗi mạng"
            else:
                note = ""
            if isinstance(payload, dict) and payload.get("blob"):
                try:
                    count = len(vault_decrypt(str(payload["blob"]), token))
                    age = int(time.time()) - int(payload.get("at") or 0)
                    print(f"  trạng thái    : mở được · {count} mục · cập nhật "
                          f"{max(0, age) // 60} phút trước")
                except Exception:
                    print("  trạng thái    : không giải mã được (token bot khác)")
            else:
                print(f"  trạng thái    : chưa có dữ liệu {('· ' + note) if note else ''}")
    repo = _pick("AISTV_CONFIG_REPO", values) or DEFAULT_REPO
    print(f"Repo cấu hình   : {repo}")
    path = _pick("AISTV_CONFIG_PATH", values) or DEFAULT_PATH
    if repo.lower() not in ("0", "off", "none", "false"):
        for source, token in tokens or [("không xác thực", "")]:
            text, status = fetch_github_status(repo, path, token)
            count = len(parse_env_text(text))
            state = f"OK ({count} biến)" if count else (
                f"HTTP {status}" if status else "lỗi mạng")
            print(f"  đọc bằng      : {source} → {state}")
    print("Biến đang có:")
    keys = sorted(set(values) | {"TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY"})
    for name in keys:
        value = get_value(name, repo)
        if not value:
            print(f"  - {name:<24} (trống)")
            continue
        if name == "TELEGRAM_BOT_TOKEN" and not valid_bot_token(value):
            print(f"  - {name:<24} SAI ĐỊNH DẠNG ({len(value)} ký tự) — cần dạng 123456:ABC...")
            continue
        where = "env" if (os.getenv(name) or "").strip() else str(sources.get(name, "Colab Secrets"))
        print(f"  - {name:<24} {_mask(value)}  [{where}]")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Đồng bộ cấu hình AI STV")
    sub = parser.add_subparsers(dest="cmd")

    p_sync = sub.add_parser("sync", help="nạp và đồng bộ cấu hình")
    p_sync.add_argument("--quiet", action="store_true")
    p_sync.add_argument("--offline", action="store_true")
    p_sync.add_argument("--json", action="store_true")

    sub.add_parser("check", help="kiểm tra token bot (exit 0/2)")

    p_get = sub.add_parser("get", help="in giá trị một biến")
    p_get.add_argument("key")

    p_set = sub.add_parser("set", help="ghi một biến vào config.env + .env")
    p_set.add_argument("key")
    p_set.add_argument("--from-env", dest="from_env", default="")
    p_set.add_argument("--stdin", action="store_true")

    p_doc = sub.add_parser("doctor", help="xem nguồn cấu hình")
    p_doc.add_argument("--json", action="store_true")

    p_vault = sub.add_parser("vault", help="kho cấu hình mã hoá (khôi phục máy mới)")
    p_vault.add_argument("action", nargs="?", default="status",
                         choices=("status", "push", "pull"))
    p_vault.add_argument("--quiet", action="store_true")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "sync":
        result = sync(quiet=args.quiet, offline=args.offline)
        if args.json:
            print({k: v for k, v in result.items() if k != "values"})
        return 0 if result["have_token"] else 2

    if args.cmd == "check":
        return 0 if _have_token(read_files()[0]) else 2

    if args.cmd == "get":
        value = get_value(args.key)
        if not value:
            return 1
        print(value)
        return 0

    if args.cmd == "set":
        value = ""
        if args.from_env:
            value = (os.getenv(args.from_env) or "").strip()
        elif args.stdin:
            value = (sys.stdin.readline() or "").strip()
        if not value:
            print(f"Thiếu giá trị cho {args.key}", file=sys.stderr)
            return 1
        if args.key == "TELEGRAM_BOT_TOKEN" and not valid_bot_token(value):
            print("Token Telegram không đúng định dạng (phải dạng 123456:ABC...). Không lưu.",
                  file=sys.stderr)
            return 1
        if not set_value(args.key, value):
            print(f"Không ghi được {args.key}", file=sys.stderr)
            return 1
        print(f"Đã lưu {args.key} vào {shared_config_path()}")
        return 0

    if args.cmd == "doctor":
        return cmd_doctor()

    if args.cmd == "vault":
        values, _src = read_files()
        if args.action == "status":
            cmd_doctor()
            return 0
        if args.action == "push":
            tokens = github_tokens(values)
            if tokens and not values.get("GITHUB_TOKEN"):
                values["GITHUB_TOKEN"] = tokens[0][1]
            ok = vault_push(values, log=None if args.quiet else print)
            return 0 if ok else 1
        if args.action == "pull":
            data = vault_restore(values, log=None if args.quiet else print)
            if not data:
                print("Không đọc được kho cấu hình (thiếu token bot hoặc chưa có dữ liệu).",
                      file=sys.stderr)
                return 1
            changed = save_values(data, protected=set())
            print(f"Đã khôi phục {len(data)} mục ({changed} mục thay đổi) → {shared_config_path()}")
            return 0
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
