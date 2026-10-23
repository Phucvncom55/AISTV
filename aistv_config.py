#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI STV - đồng bộ cấu hình (token / API key) cho MỌI môi trường.

Một chỗ duy nhất, dùng chung cho:
  • Windows cmd         (run.bat)
  • Windows PowerShell  (run.ps1)
  • Linux / macOS / Colab / DataCamp (run.sh)
  • Bot                 (aistv_bot.py gọi khi thiếu token)

Thứ tự ưu tiên khi đọc:
  1. biến môi trường của tiến trình
  2. .env trong repo / thư mục hiện tại / home / STV_HOME
  3. config.env dùng chung
     • Windows : %USERPROFILE%\\.config\\aistv\\config.env
     • Linux   : ~/.config/aistv/config.env
     • Colab   : /content/drive/MyDrive/aistv/config.env (nếu đã mount Drive)

Nguồn tải từ xa (khi có):
  1. AISTV_ENV_URL      - URL công khai trả về nội dung config.env
  2. AISTV_CONFIG_REPO  - repo private, mặc định Phucvncom55/AISTV-secrets
     Xác thực bằng (theo thứ tự): AISTV_CONFIG_TOKEN → GH_TOKEN / GITHUB_TOKEN
     → `gh auth token` → Colab Secrets.

Lệnh:
  python aistv_config.py sync [--quiet]   # nạp + đồng bộ, exit 0 nếu có token bot
  python aistv_config.py check            # im lặng, exit 0/2
  python aistv_config.py get KEY          # in giá trị (script khác dùng)
  python aistv_config.py set KEY --from-env VAR | --stdin
  python aistv_config.py doctor           # xem nguồn cấu hình (không in bí mật)
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
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
CORE_KEYS = ("TELEGRAM_BOT_TOKEN",)
HTTP_TIMEOUT = 20
USER_AGENT = "aistv-config/1.0"


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
    """Trả về (values, sources). Repo .env thắng config.env."""
    values, sources = {}, {}
    for path in reversed(env_files(repo)):
        try:
            if not path.is_file():
                continue
            for name, value in parse_env_text(path.read_text("utf-8", "replace")).items():
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


def _pick(name: str, values: dict) -> str:
    return ((os.getenv(name) or "").strip()
            or (values or {}).get(name, "").strip()
            or colab_secret(name))


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


def normalize_repo(repo: str) -> str:
    repo = (repo or "").strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if repo.lower().startswith(prefix):
            repo = repo[len(prefix):]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo


def fetch_url(url: str) -> str:
    try:
        return _http_get(url)
    except Exception:
        return ""


def fetch_github(repo: str, path: str, token: str = "") -> str:
    repo = normalize_repo(repo)
    path = (path or DEFAULT_PATH).lstrip("/")
    if not repo or ".." in path:
        return ""
    quoted = urllib.parse.quote(path)
    headers = {"Accept": "application/vnd.github.raw"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        text = _http_get(f"https://api.github.com/repos/{repo}/contents/{quoted}", headers)
        if "=" in text:
            return text
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 404):
            pass
    except Exception:
        pass
    # Dự phòng cho repo public / raw.githubusercontent.com
    try:
        return _http_get(f"https://raw.githubusercontent.com/{repo}/HEAD/{quoted}")
    except Exception:
        return ""


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
        # Repo mặc định + không có token → gần như chắc chắn private: bỏ qua cho nhanh.
        explicit = bool((os.getenv("AISTV_CONFIG_REPO") or values.get("AISTV_CONFIG_REPO") or "").strip())
        if tokens or explicit:
            candidates = tokens or [("không xác thực", "")]
            for source, token in candidates:
                text = fetch_github(repo, path, token)
                data = parse_env_text(text)
                if data:
                    for name, value in data.items():
                        if value and not merged.get(name):
                            merged[name] = value
                    labels.append(f"GitHub {repo}" + (f" ({source})" if source != "không xác thực" else ""))
                    break
    if log and not labels:
        log("Chưa có nguồn cấu hình từ xa (gh chưa đăng nhập / chưa có "
            "AISTV_CONFIG_TOKEN / AISTV_ENV_URL) — dùng cấu hình sẵn có.")
    return merged, labels


# ────────────────────────────────────────────────────────────────────
# API cho runner / bot
# ────────────────────────────────────────────────────────────────────
def _have_token(values: dict = None) -> bool:
    values = values or {}
    token = ((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
             or (values.get("TELEGRAM_BOT_TOKEN") or "").strip()
             or colab_secret("TELEGRAM_BOT_TOKEN"))
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
    if not offline and os.getenv("AISTV_CONFIG_SYNC", "1").lower() not in ("0", "off", "false"):
        remote, labels = fetch_remote(values, log=log)
    to_save = dict(colab_values)
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
    write_env_var(shared_config_path(), name, value)
    write_env_var(Path(repo or repo_dir()) / ".env", name, value)
    return True


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
    tokens = github_tokens(values)
    print("Token GitHub    : " + (", ".join(s for s, _ in tokens) if tokens else "không có"))
    print(f"AISTV_ENV_URL   : {'có' if _pick('AISTV_ENV_URL', values) else 'chưa đặt'}")
    print(f"Repo cấu hình   : {_pick('AISTV_CONFIG_REPO', values) or DEFAULT_REPO}")
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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
