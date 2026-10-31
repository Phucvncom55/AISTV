# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════════════╗
║   AI STV AGENT  —  Telegram × OpenCode   (dán 1 ô Colab là chạy)   ║
╚════════════════════════════════════════════════════════════════════╝

CÁCH DÙNG
  • Chạy 1 lệnh từ GitHub (repo public):
      bash <(curl -fsSL https://raw.githubusercontent.com/<USER>/<REPO>/main/run.sh)
  • Trong repo đã clone:
      bash run.sh                    (Linux / macOS / Colab)
      run.bat                        (Windows — cmd hoặc PowerShell)
  • Windows, chưa clone (cmd thuần, không cần PowerShell):
      curl -fsSL -o "%TEMP%\aistv.bat" "https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.bat?v=1" && call "%TEMP%\aistv.bat"
  • Trên Colab: dán TOÀN BỘ file này vào MỘT ô code → Run (tự cài đặt),
    hoặc thêm secret TELEGRAM_BOT_TOKEN rồi chạy lệnh run.sh ở trên.
  • Token: tự lấy từ `.env` / `config.env` / repo private GitHub (gh auth hoặc
    AISTV_CONFIG_TOKEN). Chỉ hỏi khi tất cả đều chưa có; kiểm tra bằng
    `python aistv_config.py doctor`.
    Nên đặt ALLOWED_USER_IDS (user id Telegram, hỏi @userinfobot) để khoá bot chắc chắn.
  • Mở Telegram, nhắn /start. Người nhắn đầu tiên là CHỦ BOT.

KIẾN TRÚC (học theo OpenClaw)
  workspace/SOUL.md      tính cách & văn phong
  workspace/AGENTS.md    quy tắc làm việc
  workspace/MEMORY.md    trí nhớ dài hạn (/remember, /memory, /forget)
  workspace/memory/      nhật ký theo ngày
  workspace/skills/      kỹ năng tuỳ chỉnh (/skills, /skill)
  workspace/inbox/       file người dùng gửi cho bot
  workspace/opencode.json cấu hình OpenCode (công tắc FULL_ACCESS ở mục 0)
  sessions/*.jsonl       lịch sử hội thoại bền vững theo từng chat
"""

# ════════════════════════════════════════════════════════════════════
# 0. CẤU HÌNH — chỉnh ở đây
# ════════════════════════════════════════════════════════════════════
import os, sys, re, json, time, html, shutil, asyncio, getpass, logging, subprocess, functools, hashlib, importlib.util, mimetypes, unicodedata, tempfile
import base64, hmac
import secrets, threading, textwrap, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from typing import Optional

try:
    import aistv_skills as skill_lib
except Exception:                       # vẫn chạy được nếu thiếu module (bản cũ)
    skill_lib = None

try:
    import aistv_config as config_lib   # đồng bộ cấu hình dùng chung cho mọi runner
except Exception:                       # bản cũ chưa có file → dùng logic dự phòng bên dưới
    config_lib = None

IS_WINDOWS = os.name == "nt"


# ── .env: đọc ngay khi bot khởi động, để chạy `python aistv_bot.py` trực tiếp
#    cũng không phải nhập token lại. Không ghi đè biến môi trường đã có.
def _env_files():
    override = os.getenv("AISTV_ENV_FILE", "").strip()
    if override:
        return [Path(override).expanduser()]       # file chỉ định: chỉ đọc file này
    cfg_dirs = []
    try:
        if config_lib is not None:
            cfg_dirs.append(config_lib.config_dir())
    except Exception:
        pass
    default_cfg = Path.home() / ".config" / "aistv"
    if default_cfg not in cfg_dirs:
        cfg_dirs.append(default_cfg)
    files = [
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / ".env",
        Path.home() / ".env",
        Path(os.getenv("STV_HOME", "")) / ".env" if os.getenv("STV_HOME") else None,
        # Cấu hình dùng chung, không mất khi clone lại repo / đổi AISTV_DIR.
        # Trên Colab ưu tiên Drive (giống run.sh); vẫn đọc ~/.config để tương thích bản cũ.
        *(d / "config.env" for d in cfg_dirs),
    ]
    seen, result = set(), []
    for path in files:
        if path is None:
            continue
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


ENV_FROM_FILES: set = set()     # biến nạp từ .env/config.env (nạp lại khi restart)


def _load_env_path(path: Path) -> None:
    """Nạp KEY=VALUE từ một file, không ghi đè biến môi trường đã có."""
    try:
        if not path.is_file():
            return
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
                ENV_FROM_FILES.add(name)
    except Exception:
        pass


def _load_dotenv():
    for path in _env_files():
        _load_env_path(path)


_load_dotenv()

# Bản cũ có thể còn giữ model Gemini cũ trong môi trường (restart cũ không nạp lại
# .env) → tự chuyển một lần sang model mới để /restart đầu tiên là có hiệu lực.
for _k, _old, _new in (
    ("WATCH_GEMINI_MODEL", "gemini-3-flash-preview", "gemini-3.8-flash"),
    ("WATCH_GEMINI_FALLBACKS", "gemini-2.5-flash,gemini-3.1-flash-lite",
     "gemini-3.7-flash,gemini-3.5-flash"),
):
    if os.getenv(_k) == _old:
        os.environ[_k] = _new
        ENV_FROM_FILES.add(_k)

# Bí mật được đồng bộ lên Firebase (mã hoá bằng token bot) để sang máy/terminal
# khác không phải đăng nhập lại. Thêm tên biến vào đây nếu muốn sync thêm.
SECRETS_DIRTY = False
SECRETS_CLOUD_KEYS: set = set()       # tên bí mật đang có trên cloud (lần đọc gần nhất)
SECRET_SYNC_KEYS = (
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "JINA_API_KEY",
    "AISTV_EMAIL_ADDRESS", "AISTV_EMAIL_PASSWORD",
    "ALLOWED_USER_IDS", "WATCH_GEMINI_MODEL", "WATCH_GEMINI_FALLBACKS",
    "AISTV_IMAGE_MODEL", "AISTV_IMAGE_FALLBACKS", "AISTV_IMAGE_PROVIDER",
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
    "TOGETHER_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY",
    "AISTV_FIREBASE_URL", "AISTV_FIREBASE_SECRET",
)


def _write_env_var(path: Path, name: str, value: str) -> Path:
    """Ghi/ cập nhật một biến trong file .env kiểu KEY=VALUE."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text("utf-8", "replace").splitlines() if path.is_file() else []
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if stripped.startswith(name + "="):
            lines[i] = f"{name}={value}"
            found = True
            break
    if not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{name}={value}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n", "utf-8")
    tmp.replace(path)
    try:
        if not IS_WINDOWS:
            path.chmod(0o600)
    except Exception:
        pass
    return path


def save_env_var(name: str, value: str) -> Path:
    """Lưu biến vào .env của repo VÀ config.env dùng chung.

    Nhờ file dùng chung (~/.config/aistv/config.env) token không mất khi
    clone lại repo hay đổi AISTV_DIR — lần sau chạy không phải nhập lại.
    """
    global SECRETS_DIRTY
    primary = Path(os.getenv("AISTV_ENV_FILE", "") or (Path(__file__).resolve().parent / ".env"))
    try:
        shared = (config_lib.shared_config_path() if config_lib is not None
                  else Path(os.getenv("AISTV_CONFIG_DIR", "").strip()
                            or (Path.home() / ".config" / "aistv")) / "config.env")
    except Exception:
        shared = Path.home() / ".config" / "aistv" / "config.env"
    for path in (primary, shared):
        try:
            _write_env_var(path, name, value)
        except Exception:
            continue
    os.environ[name] = value
    if name in SECRET_SYNC_KEYS:
        SECRETS_DIRTY = True                  # cloud_loop sẽ đẩy lên Firebase
    return primary


def _persist_shared_config() -> None:
    """Lưu token + bí mật đang có vào config.env dùng chung (chỉ thêm, không ghi đè).

    Nhờ vậy máy khác chỉ cần clone repo / copy config.env là bot kết nối được,
    không phải nhập lại token hay API key.
    """
    if os.getenv("AISTV_ENV_FILE", "").strip():
        return                                # người dùng chỉ định file riêng: không đụng
    try:
        shared = (config_lib.shared_config_path() if config_lib is not None
                  else Path(os.getenv("AISTV_CONFIG_DIR", "").strip()
                            or (Path.home() / ".config" / "aistv")) / "config.env")
    except Exception:
        shared = Path.home() / ".config" / "aistv" / "config.env"
    for name in ("TELEGRAM_BOT_TOKEN",) + tuple(SECRET_SYNC_KEYS):
        value = (os.getenv(name) or "").strip()
        if not value:
            continue
        try:
            if shared.is_file():
                has = False
                for line in shared.read_text("utf-8", "replace").splitlines():
                    s = line.strip()
                    if s.startswith("export "):
                        s = s[7:].lstrip()
                    if s.startswith(name + "=") and s.split("=", 1)[1].strip():
                        has = True
                        break
                if has:
                    continue
            _write_env_var(shared, name, value)
        except Exception:
            continue


_persist_shared_config()


# Windows: console mặc định không phải UTF-8 (cp1252/cp437) → in tiếng Việt/emoji sẽ lỗi.
if IS_WINDOWS:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

try:
    import aistv_email as mail
except Exception:                       # thiếu mô-đun → bot vẫn chạy, chỉ tắt email
    mail = None

try:
    import aistv_web2api as web2api     # dự phòng khi model chính hết hạn mức
except Exception:                       # thiếu module → chỉ tắt dự phòng, bot vẫn chạy
    web2api = None

try:
    import aistv_planner as planner    # kế hoạch dài, checkpoint/undo, verify
except Exception:                       # thiếu module → tắt /plan, bot vẫn chạy
    planner = None

try:
    import aistv_work as workmod       # nhánh công việc dài, tiếp tục trên máy khác
except Exception:                       # thiếu module → /plan chạy kiểu cũ
    workmod = None

try:
    import aistv_vm as vm_lib          # tạo máy ảo Windows (GitHub Actions + Tailscale)
except Exception:                       # thiếu module → tắt /vm, bot vẫn chạy
    vm_lib = None

CLEAN_INSTALL = os.getenv("AISTV_CLEAN_INSTALL", "0") != "0"   # 1 = xoá & cài lại OpenCode; 0 = giữ bản đã cài
USE_GOOGLE_DRIVE = False        # True = lưu trí nhớ/lịch sử vào Google Drive (sống sót khi Colab reset)
FULL_ACCESS = True              # True = agent được đọc/ghi NGOÀI workspace, chạy lệnh & truy cập web
                                #        không cần hỏi quyền (mọi tool của OpenCode đều được auto-approve)
# Model chính, đổi nhanh bằng /model hoặc OPENCODE_MODEL.
# Mặc định DeepSeek v4.1 Flash. Model này thường KHÔNG phát event reasoning
# (chỉ trả text), nên khung 💭 Suy nghĩ sẽ báo rõ "không trả reasoning".
# Muốn thấy reasoning: /model chọn glm-5.3-flash-free / flint-40b-free / nemotron.
DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"
LEGACY_GEMINI_MODEL = "google/gemini-3.8-flash"       # bản trước lỡ đặt Gemini làm model chính → tự quay lại model mặc định
VISION_MODEL = "gemini-3.8-flash"                     # mắt + tai: đọc ảnh / xem video (không phải model trả lời)
WEB2API_MODEL = (os.getenv("WEB2API_MODEL") or "gemini-3.5-flash-thinking").strip()
                                                      # mặc định think cao (server: "Deep thinking mode")
WEB2API_FALLBACK = os.getenv("WEB2API_FALLBACK", "1") != "0"   # 0 = tắt dự phòng Gemini Web2API
# Người không phải chủ bot: chat, tạo ảnh/sơ đồ và nhờ Gemini đọc ảnh/video qua Web2API.
GUEST_CHAT = os.getenv("AISTV_GUEST_CHAT", "1") != "0"         # 0 = chặn hoàn toàn người lạ
GUEST_MODEL = (os.getenv("AISTV_GUEST_MODEL") or WEB2API_MODEL).strip()
GUEST_TIMEOUT = max(30, int(os.getenv("AISTV_GUEST_TIMEOUT", "180") or 180))
GUEST_HISTORY = max(0, int(os.getenv("AISTV_GUEST_HISTORY", "6") or 6))   # số lượt nhớ riêng của khách
GUEST_MIN_GAP = max(0.0, float(os.getenv("AISTV_GUEST_GAP", "1") or 1))   # giây giữa 2 tin của 1 khách
GUEST_CONCURRENCY = max(1, int(os.getenv("AISTV_GUEST_PARALLEL", "3") or 3))
# Khách dùng miễn phí các khả năng của Web2API: chat, hỏi code, tạo ảnh, sơ đồ.
GUEST_FEATURES = os.getenv("AISTV_GUEST_FEATURES", "1") != "0"   # 0 = chỉ chat chữ
GUEST_MEDIA = os.getenv("AISTV_GUEST_MEDIA", "1") != "0"         # 0 = tắt tạo ảnh/sơ đồ cho khách
GUEST_RATE = max(1, int(os.getenv("AISTV_GUEST_RATE", "10") or 10))          # tin/phút/người
GUEST_CHAT_RATE = max(1, int(os.getenv("AISTV_GUEST_CHAT_RATE", "40") or 40))  # lượt/phút/nhóm
GUEST_MEDIA_GAP = max(5, int(os.getenv("AISTV_GUEST_MEDIA_GAP", "45") or 45))  # giây giữa 2 ảnh/người
GUEST_MEDIA_RATE = max(1, int(os.getenv("AISTV_GUEST_MEDIA_RATE", "6") or 6))  # ảnh/giờ/người
GUEST_MEDIA_CHAT_RATE = max(1, int(os.getenv("AISTV_GUEST_MEDIA_CHAT", "20") or 20))
GUEST_MEDIA_PARALLEL = max(1, int(os.getenv("AISTV_GUEST_MEDIA_PARALLEL", "1") or 1))
GUEST_MEDIA_TIMEOUT = max(60, int(os.getenv("AISTV_GUEST_MEDIA_TIMEOUT", "180") or 180))
# Đọc ảnh/video miễn phí cho khách (Gemini qua Web2API, không dùng key của chủ).
GUEST_VISION = os.getenv("AISTV_GUEST_VISION", "1") != "0"      # 0 = tắt đọc ảnh/video
GUEST_VISION_GAP = max(3, int(os.getenv("AISTV_GUEST_VISION_GAP", "10") or 10))
GUEST_VISION_RATE = max(1, int(os.getenv("AISTV_GUEST_VISION_RATE", "20") or 20))   # lượt/giờ/người
GUEST_VISION_CHAT_RATE = max(1, int(os.getenv("AISTV_GUEST_VISION_CHAT", "40") or 40))
GUEST_VISION_PARALLEL = max(1, int(os.getenv("AISTV_GUEST_VISION_PARALLEL", "1") or 1))
GUEST_VISION_TIMEOUT = max(60, int(os.getenv("AISTV_GUEST_VISION_TIMEOUT", "420") or 420))
GUEST_VISION_MAX_SEC = max(30, int(os.getenv("AISTV_GUEST_VISION_SEC", "600") or 600))
GUEST_HIST_USERS = max(20, int(os.getenv("AISTV_GUEST_HIST_USERS", "200") or 200))
GUEST_MODEL_OPTIONS = list(dict.fromkeys(
    [GUEST_MODEL, "gemini-3.6-flash", "gemini-3.8-flash"]
    + [m.strip() for m in (os.getenv("AISTV_GUEST_MODELS") or "").split(",")
       if m.strip()]))
VISION_HANDOFF = os.getenv("AISTV_VISION_HANDOFF", "1") != "0"
                                                      # 1 = Gemini đọc media → DeepSeek (model chính) trả lời
VISION_FOLLOWUPS = max(0, int(os.getenv("AISTV_VISION_FOLLOWUPS", "2") or 2))
                                                      # số lần DeepSeek được hỏi lại Gemini cho mỗi media
TIMEZONE = "Asia/Ho_Chi_Minh"
MAX_HISTORY = 12                # số lượt hỏi-đáp đưa vào ngữ cảnh
MAX_PARALLEL = 2                # số tiến trình OpenCode chạy cùng lúc
AGENT_TIMEOUT = 0               # LUÔN không giới hạn: dự án lớn chạy tới khi xong.
                                # (bỏ qua AISTV_AGENT_TIMEOUT để không bao giờ tự cắt ngang)
                                # Muốn bật lại: sửa số 0 thành số giây.
ASK_TIMEOUT = int(os.getenv("AISTV_ASK_TIMEOUT", "0") or 0)
                                # 0 (mặc định) = chờ không giới hạn, không bao giờ tự cắt ngang
                                # Muốn giới hạn: đặt AISTV_ASK_TIMEOUT=<số giây>
GH_CLIENT_ID = os.getenv("AISTV_GH_CLIENT_ID", "178c6fc778ccc68e1d6a")   # GitHub CLI (public client)
GH_SCOPES = os.getenv("AISTV_GH_SCOPES", "repo workflow read:user")
MAX_PROMPT_BYTES = 28_000 if IS_WINDOWS else 110_000   # Windows giới hạn dòng lệnh 32K ký tự
SKILL_BODY_LIMIT = 7_000 if IS_WINDOWS else 24_000      # phần SKILL.md nhét vào prompt; file đầy đủ vẫn đọc được
SKILL_INSTALL_LOCK = asyncio.Lock()                     # tránh cài 2 skill cùng lúc
SPLIT_LIMIT = 3000              # ký tự tối đa mỗi tin nhắn Telegram (trước khi đổi sang HTML)
PROGRESS_DETAIL = 500           # ký tự tối đa cho mỗi đoạn chi tiết (lệnh, code, output) trong tin nhắn tiến độ
PROGRESS_KEEP = 6               # số việc gần nhất hiển thị trong tin nhắn tiến độ
PROGRESS_TICK = float(os.getenv("AISTV_PROGRESS_TICK", "1") or 1)   # giây giữa 2 lần cập nhật tiến độ
PROGRESS_LINES = int(os.getenv("AISTV_PROGRESS_LINES", "14") or 14) # số dòng cuộn trong tin nhắn tiến độ
PROGRESS_CHARS = 3700           # giới hạn ký tự của khung cuộn (Telegram tối đa 4096)

# ── Trí nhớ đám mây: Firebase Realtime Database (sống sót khi restart / Colab reset) ──
# Không hardcode URL: đặt AISTV_FIREBASE_URL trong config.env của repo private.
# Thiếu biến này thì CLOUD_ENABLED = False, bot vẫn chạy (chỉ mất đồng bộ cloud).
FIREBASE_URL = (os.getenv("AISTV_FIREBASE_URL") or "").strip().rstrip("/")
FIREBASE_SECRET = os.getenv("AISTV_FIREBASE_SECRET", "")   # chỉ cần nếu Rules yêu cầu auth (?auth=...)
CLOUD_ENABLED = bool(FIREBASE_URL) and os.getenv("AISTV_CLOUD", "1") != "0"
CLOUD_NS_BASE = os.getenv("AISTV_CLOUD_NS", "aistv")       # namespace riêng, không đụng dữ liệu app khác
HIST_PUSH_DELAY = 2.0           # gom thay đổi lịch sử rồi đẩy 1 lần (giây)
HIST_KEEP_REMOTE = 300          # số lượt giữ trên cloud mỗi chat

# ── Tự tóm tắt hội thoại dài → trí nhớ dài hạn ──
AUTO_SUMMARY = os.getenv("AISTV_AUTO_SUMMARY", "1") != "0"
SUMMARY_MIN_ITEMS = int(os.getenv("AISTV_SUMMARY_ITEMS", "40"))     # số lượt (user+AI) để kích hoạt
SUMMARY_KEEP_ITEMS = int(os.getenv("AISTV_SUMMARY_KEEP", "16"))     # số lượt gần nhất giữ nguyên
SUMMARY_TIMEOUT = int(os.getenv("AISTV_SUMMARY_TIMEOUT", "420"))

# ── Nhắc việc định kỳ & theo dõi repo/log ──
REMIND_TICK = int(os.getenv("AISTV_REMIND_TICK", "15"))             # giây giữa 2 lần kiểm tra
WATCH_INTERVAL = int(os.getenv("AISTV_WATCH_INTERVAL", "60"))       # nhịp mặc định cho log/file
WATCH_GIT_INTERVAL = int(os.getenv("AISTV_WATCH_GIT_INTERVAL", "300"))
WATCH_SELF = os.getenv("AISTV_WATCH_SELF", "1") != "0"              # tự báo lỗi trong log của bot
PROACTIVE = os.getenv("AISTV_PROACTIVE", "1") != "0"


# ════════════════════════════════════════════════════════════════════
# 1. TỰ ĐỘNG CÀI ĐẶT MÔI TRƯỜNG
# ════════════════════════════════════════════════════════════════════
def _shell_prefix() -> list:
    """Lệnh shell phù hợp hệ điều hành: bash trên Linux/macOS, PowerShell/cmd trên Windows."""
    if IS_WINDOWS:
        for name in ("pwsh", "powershell"):
            exe = shutil.which(name)
            if exe:
                return [exe, "-NoProfile", "-NonInteractive", "-Command"]
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c"]
    bash = shutil.which("bash") or "bash"
    return [bash, "-c"]


def _sh(cmd: str, timeout: int = 900) -> subprocess.CompletedProcess:
    full = cmd if IS_WINDOWS else "set -o pipefail; " + cmd
    return subprocess.run(_shell_prefix() + [full],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _safe_is_dir(p: Path) -> bool:
    """is_dir() nhưng không nổ khi gặp thư mục không có quyền (vd /root trên Colab/VPS)."""
    try:
        return p.is_dir()
    except OSError:
        return False


def _opencode_dirs() -> list:
    home = Path.home()
    dirs = [home / ".opencode" / "bin", home / ".local" / "bin", home / ".bun" / "bin"]
    if IS_WINDOWS:
        for var, parts in (("APPDATA", ("npm",)), ("LOCALAPPDATA", ("opencode", "bin")),
                           ("LOCALAPPDATA", ("Programs", "opencode")),
                           ("USERPROFILE", ("scoop", "shims")),
                           ("ProgramData", ("chocolatey", "bin"))):
            base = os.getenv(var)
            if base:
                dirs.append(Path(base).joinpath(*parts))
    elif hasattr(os, "geteuid") and os.geteuid() == 0:
        # /root không đọc được với user thường (Colab) → chỉ thêm khi là root
        dirs.append(Path("/root/.opencode/bin"))
    return dirs


_OPENCODE_PICK: Optional[str] = None
_OPENCODE_VER: dict = {}


def _opencode_version(binary: str) -> str:
    """Chuỗi phiên bản của binary (vd "1.19.4", "opencode v2.1.4"); "" nếu không chạy được."""
    if binary in _OPENCODE_VER:
        return _OPENCODE_VER[binary]
    ver = ""
    try:
        r = subprocess.run([binary, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        lines = (r.stdout or "").strip().splitlines()
        ver = lines[-1].strip() if lines else ""
    except (OSError, subprocess.SubprocessError):
        ver = ""
    _OPENCODE_VER[binary] = ver
    return ver


def _opencode_major(ver: str) -> int:
    m = re.search(r"(\d+)\.", ver or "")
    return int(m.group(1)) if m else 0


def find_opencode() -> Optional[str]:
    """Tìm binary OpenCode, ưu tiên bản v2.

    Máy hay còn binary v1 do lần cài cũ (~/.opencode/bin/opencode) trong khi dữ
    liệu ~/.local/share/opencode đã được nâng lên schema v2. Chạy v1 trên DB v2
    sẽ báo "Database is not empty and has no session table" và /models trống,
    nên chỉ dùng v1 khi không có bản v2 nào.
    """
    global _OPENCODE_PICK
    env_bin = (os.getenv("OPENCODE_BIN") or "").strip()
    if env_bin and Path(env_bin).exists():
        return env_bin                    # người dùng chỉ định rõ thì tôn trọng
    if _OPENCODE_PICK and Path(_OPENCODE_PICK).exists():
        return _OPENCODE_PICK
    _OPENCODE_PICK = None                 # binary đã bị xoá/dời → quét lại
    cands = []
    found = shutil.which("opencode")
    if found:
        cands.append(found)
    for p in _opencode_dirs():
        exe = p / ("opencode.exe" if IS_WINDOWS else "opencode")
        if _safe_is_dir(p) and exe.exists():
            cands.append(str(exe))
    seen = set()
    v1 = None
    pick = None
    for c in [c for c in cands if not (c in seen or seen.add(c))]:
        if _opencode_major(_opencode_version(c)) >= 2:
            pick = c
            break
        if v1 is None:
            v1 = c
    pick = pick or v1
    if pick:
        folder = str(Path(pick).parent)
        if folder not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        _OPENCODE_PICK = pick
    return pick


# OpenCode 2 có kênh cài riêng: https://opencode.ai/install chỉ cài bản 1.x,
# còn bản 2 nằm ở /v2/install (gói npm @opencode/cli). Dùng nhầm kênh là lỗi
# "cài opencode cũ" quen thuộc: bot cài xong vẫn ra v1 rồi hỏng phiên v2.
OPENCODE_INSTALL_URL = "https://opencode.ai/v2/install"
OPENCODE_NPM_PKG = "@opencode/cli"
OPENCODE_NPM_META = "https://opencode.ai/update/api/latest/cli/npm"


def _npm_cli_targets() -> list:
    """Tên gói npm chứa binary v2 cho nền tảng hiện tại (khớp CPU/libc trước)."""
    import platform
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if IS_WINDOWS:
        return ["windows-arm64"] if arm else ["windows-x64"]
    if sys.platform == "darwin":
        return ["darwin-arm64"] if arm else ["darwin-x64", "darwin-x64-baseline"]
    if arm:
        return ["linux-arm64", "linux-arm64-musl"]
    return ["linux-x64", "linux-x64-baseline", "linux-x64-musl", "linux-x64-baseline-musl"]


def _install_opencode_npm_tarball() -> Optional[str]:
    """Dự phòng khi không có npm/script cài: tải thẳng binary v2 từ gói npm.

    Gói @opencode/cli-<nền tảng> chứa sẵn binary (package/bin/opencode[.exe]) nên
    không phụ thuộc GitHub Releases — nơi bản "latest" vẫn là OpenCode 1.
    """
    import tarfile
    import tempfile

    dest = Path.home() / ".opencode" / "bin"
    dest.mkdir(parents=True, exist_ok=True)
    ua = {"User-Agent": "AISTV-bot"}
    try:
        req = urllib.request.Request(OPENCODE_NPM_META, headers=ua)
        with urllib.request.urlopen(req, timeout=30) as resp:
            ver = str((json.load(resp) or {}).get("version") or "").strip()
    except Exception as e:
        print(f"   ⚠️ Không lấy được phiên bản OpenCode 2: {e}")
        return None
    if not ver:
        print("   ⚠️ Không lấy được phiên bản OpenCode 2.")
        return None

    exe = "opencode.exe" if IS_WINDOWS else "opencode"
    for target in _npm_cli_targets():
        pkg = f"@opencode/cli-{target}"
        url = f"https://registry.npmjs.org/{pkg}/-/{pkg.rsplit('/', 1)[-1]}-{ver}.tgz"
        tmp_tar = None
        try:
            req = urllib.request.Request(url, headers=ua)
            with urllib.request.urlopen(req, timeout=900) as resp:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as fh:
                    tmp_tar = fh.name
                    shutil.copyfileobj(resp, fh)
            with tarfile.open(tmp_tar, "r:gz") as tf:
                member = next((m for m in tf.getmembers()
                               if m.isfile() and m.name.replace("\\", "/")
                               in (f"package/bin/{exe}", "package/bin/opencode")), None)
                src = tf.extractfile(member) if member else None
                if src is None:
                    raise FileNotFoundError("gói không có binary opencode")
                with open(dest / exe, "wb") as out:
                    shutil.copyfileobj(src, out)
            (dest / exe).chmod(0o755)
            _reset_opencode_cache()
            if _opencode_major(_opencode_version(str(dest / exe))) >= 2:
                print(f"   • Đã cài {pkg} {ver}")
                return find_opencode()
            print(f"   ⚠️ {pkg} {ver}: binary không chạy được trên máy này, thử bản khác…")
        except Exception as e:
            print(f"   ⚠️ {pkg} {ver}: {e}")
        finally:
            if tmp_tar:
                try:
                    os.unlink(tmp_tar)
                except Exception:
                    pass
    return None


def _install_opencode_windows() -> Optional[str]:
    """Windows: npm (gói v2) → tải binary v2 từ npm."""
    if shutil.which("npm"):
        print("   • Thử cài bằng npm…")
        _sh(f"npm install -g {OPENCODE_NPM_PKG}", timeout=900)
        _reset_opencode_cache()           # npm có thể đặt binary ở thư mục khác
        found = find_opencode()
        if found and _opencode_major(_opencode_version(found)) >= 2:
            return found
    print("   • Tải binary OpenCode 2 từ npm…")
    return _install_opencode_npm_tarball()


def _install_opencode_unix() -> Optional[str]:
    """Linux/macOS: tải thẳng binary v2 từ npm (dự phòng khi script cài bị chặn)."""
    print("   • Tải binary OpenCode 2 từ npm…")
    return _install_opencode_npm_tarball()


def _reset_opencode_cache() -> None:
    global _OPENCODE_PICK
    _OPENCODE_PICK = None
    _OPENCODE_VER.clear()


def _upgrade_opencode() -> None:
    """Nâng OpenCode lên v2 đè lên bản cũ, GIỮ nguyên dữ liệu phiên.

    Khác với cài sạch: không xoá ~/.local/share/opencode (nơi chứa phiên, memory).
    """
    _reset_opencode_cache()
    if IS_WINDOWS:
        _install_opencode_windows()
        return
    print("   • Đang nâng cấp OpenCode lên v2 (giữ nguyên dữ liệu phiên)…")
    res = _sh(f"curl -fsSL {OPENCODE_INSTALL_URL} | bash")
    if res.returncode != 0:
        print("\n".join(res.stdout.splitlines()[-15:]))
    _reset_opencode_cache()               # bản mới có thể nằm ở thư mục khác bản cũ
    if _opencode_major(_opencode_version(find_opencode() or "")) < 2 and shutil.which("npm"):
        print("   • Thử cài bằng npm…")
        _sh(f"npm install -g {OPENCODE_NPM_PKG}", timeout=900)
        _reset_opencode_cache()
    if _opencode_major(_opencode_version(find_opencode() or "")) < 2:
        _install_opencode_unix()


def _opencode_ver_tuple(ver: str) -> tuple:
    """Chuỗi phiên bản ("2.1.4" / "opencode v2.1.4") → (2, 1, 4); () nếu không đọc được."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", ver or "")
    return tuple(int(x) for x in m.groups()) if m else ()


def _opencode_latest_version() -> str:
    """Bản OpenCode 2 mới nhất trên npm ("" nếu không kiểm tra được)."""
    try:
        req = urllib.request.Request(OPENCODE_NPM_META, headers={"User-Agent": "AISTV-bot"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return str((json.load(resp) or {}).get("version") or "").strip()
    except Exception:
        return ""


def _best_opencode(cands: list) -> Optional[str]:
    """Chọn binary v2 có phiên bản cao nhất trong danh sách."""
    best, best_ver = None, ()
    for c in cands:
        if not c or not Path(c).exists() or _opencode_major(_opencode_version(c)) < 2:
            continue
        ver = _opencode_ver_tuple(_opencode_version(c))
        if ver > best_ver:
            best, best_ver = c, ver
    return best


def _maybe_update_opencode(binary: str) -> str:
    """Tự nâng OpenCode 2 lên bản mới nhất trên npm, giữ nguyên phiên.

    Tắt bằng AISTV_OPENCODE_UPDATE=0. Bỏ qua khi người dùng ghim OPENCODE_BIN
    (đã chỉ định rõ binary thì không tự đổi).
    """
    global _OPENCODE_PICK
    if os.getenv("AISTV_OPENCODE_UPDATE", "1") == "0" or os.getenv("OPENCODE_BIN"):
        return binary
    cur = _opencode_ver_tuple(_opencode_version(binary))
    latest = _opencode_ver_tuple(_opencode_latest_version())
    if not cur or not latest or latest <= cur:
        return binary
    print(f"   • OpenCode {'.'.join(map(str, latest))} mới hơn bản đang dùng "
          f"{'.'.join(map(str, cur))} — nâng (giữ nguyên phiên)…")
    _upgrade_opencode()
    new = _best_opencode([str(Path.home() / ".opencode" / "bin" /
                              ("opencode.exe" if IS_WINDOWS else "opencode")),
                          find_opencode() or ""]) or binary
    new_ver = _opencode_ver_tuple(_opencode_version(new))
    if new_ver >= latest:
        print(f"   • Đã nâng OpenCode lên {'.'.join(map(str, new_ver))}")
        _OPENCODE_PICK = new
        folder = str(Path(new).parent)
        if folder not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    else:
        print(f"   ⚠️ Chưa nâng được lên {'.'.join(map(str, latest))} — dùng bản hiện có.")
    return new


def setup_environment() -> None:
    print("⏳ [1/3] Kiểm tra thư viện Python (python-telegram-bot, nest_asyncio)...")
    missing = [name for name in ("telegram", "nest_asyncio")
               if importlib.util.find_spec(name) is None]
    if missing:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                            "python-telegram-bot", "nest_asyncio"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise SystemExit("❌ Thiếu thư viện Python và không cài được.\n"
                             "   Chạy bằng run.sh / run.bat, hoặc: python -m pip install -r requirements.txt")
    print("✅ [1/3] Thư viện Python OK")

    print("⏳ [2/3] Cài OpenCode...")
    current = find_opencode()
    outdated = bool(current) and _opencode_major(_opencode_version(current)) < 2
    if IS_WINDOWS:
        if CLEAN_INSTALL or not current:
            _reset_opencode_cache()
            for d in (Path.home() / ".local" / "share" / "opencode", Path.home() / ".opencode"):
                shutil.rmtree(d, ignore_errors=True)
            _install_opencode_windows()
        elif outdated:
            _upgrade_opencode()
    elif CLEAN_INSTALL or not current:
        _reset_opencode_cache()
        _sh("rm -rf ~/.local/share/opencode ~/.opencode")
        res = _sh(f"curl -fsSL {OPENCODE_INSTALL_URL} | bash")
        if res.returncode != 0:
            print("\n".join(res.stdout.splitlines()[-15:]))
        if not find_opencode() and shutil.which("npm"):
            print("   • Thử cài bằng npm…")
            _sh(f"npm install -g {OPENCODE_NPM_PKG}", timeout=900)
        if not find_opencode():
            _install_opencode_unix()
    elif outdated:
        _upgrade_opencode()
    _reset_opencode_cache()               # đừng dùng lại kết quả quét trước khi cài
    binary = find_opencode()
    if not binary:
        raise SystemExit("❌ Không cài được OpenCode.\n"
                         + ("   Cài thủ công: npm install -g @opencode/cli  (hoặc choco/scoop install opencode)"
                            if IS_WINDOWS else
                            "   Cài thủ công: curl -fsSL https://opencode.ai/v2/install | bash"))
    binary = _maybe_update_opencode(binary)
    print(f"✅ [3/3] OpenCode sẵn sàng: {binary}")


if os.getenv("STV_SKIP_SETUP") != "1":
    setup_environment()

import nest_asyncio
nest_asyncio.apply()

# --- Tương thích Python 3.14 + nest_asyncio ---------------------------------
# nest_asyncio 1.6.0 đổi asyncio.Task sang bản Python thuần, nhưng từ Python
# 3.14 asyncio.current_task/all_tasks vẫn là bản C nên không thấy các task đó
# (current_task() trả về None). anyio/httpx dùng current_task() để lấy task
# hiện tại, nên sẽ nổ: "cannot create weak reference to 'NoneType' object".
# Trỏ lại về bản Python thuần để mọi thứ hoạt động với nest_asyncio.
if sys.version_info >= (3, 14):
    _py_current_task = getattr(asyncio.tasks, "_py_current_task", None)
    _py_all_tasks = getattr(asyncio.tasks, "_py_all_tasks", None)
    if _py_current_task is not None:
        asyncio.current_task = asyncio.tasks.current_task = _py_current_task
    if _py_all_tasks is not None:
        asyncio.all_tasks = asyncio.tasks.all_tasks = _py_all_tasks

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      BotCommand, LinkPreviewOptions)
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest, RetryAfter, Conflict
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(TIMEZONE)
except Exception:
    TZ = None


def now() -> datetime:
    return datetime.now(TZ) if TZ else datetime.now()


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def oneline(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ════════════════════════════════════════════════════════════════════
# 2. ĐƯỜNG DẪN, TRẠNG THÁI, BẢO MẬT
# ════════════════════════════════════════════════════════════════════
def _default_home() -> str:
    if os.getenv("STV_HOME"):
        return os.environ["STV_HOME"]
    if USE_GOOGLE_DRIVE:
        try:
            from google.colab import drive
            drive.mount("/content/drive")
            return "/content/drive/MyDrive/stv_agent"
        except Exception as e:
            print(f"⚠️ Không mount được Google Drive ({e}), dùng ổ tạm.")
    return "/content/stv_agent" if Path("/content").exists() else str(Path.home() / "stv_agent")


HOME = Path(_default_home())
WORKSPACE = HOME / "workspace"
MEMORY_DIR = WORKSPACE / "memory"
SKILLS_DIR = WORKSPACE / "skills"
# Tương thích cả chuẩn Cursor: .agents/skills/ và .cursor/skills/ (chỉ đọc, không ghi).
SKILL_ROOTS = [SKILLS_DIR, WORKSPACE / ".agents" / "skills", WORKSPACE / ".cursor" / "skills"]
INBOX = WORKSPACE / "inbox"
WATCH_CLI = Path(__file__).resolve().parent / "aistv_watch.py"
IMAGE_CLI = Path(__file__).resolve().parent / "aistv_image.py"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".3gp"}
SESSIONS = HOME / "sessions"
ARCHIVE = HOME / "archive"
SECRETS_DIR = HOME / ".secrets"
GITHUB_TOKEN_FILE = SECRETS_DIR / "github_token"
GITHUB_REPO_FILE = SECRETS_DIR / "github_repo"      # owner/name đang dùng (đổi bằng /github repo)
VM_CREDS_FILE = SECRETS_DIR / "vm_creds.json"       # PAT + Tailscale key cho /vm (đồng bộ mã hoá qua Firebase)
STATE_FILE = HOME / "state.json"
LOG_DIR = HOME / "logs"
LOG_FILE = LOG_DIR / "aistv.log"
for _d in (WORKSPACE, MEMORY_DIR, SKILLS_DIR, INBOX, SESSIONS, ARCHIVE, SECRETS_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
try:
    SECRETS_DIR.chmod(0o700)
except Exception:
    pass
if mail:
    try:
        mail.configure(HOME)
    except Exception:
        mail = None

START_TIME = time.time()
BOT_TOKEN = ""
OPENCODE_BIN = ""
OPENCODE_VERSION = "?"
RUNNING: dict = {}                 # chat_id -> tiến trình OpenCode đang chạy
CANCELLED: set = set()
LOCKS = defaultdict(asyncio.Lock)  # mỗi chat xử lý tuần tự
SEM = asyncio.Semaphore(MAX_PARALLEL)
GEMINI_MEDIA_LOCK = asyncio.Lock()      # xếp hàng ảnh/video để không vượt 10 RPM
LAST_MEDIA: dict = {}                   # chat_id -> {"source", "kind", "model"} của media vừa đọc
VISION_FOLLOWUP_LEFT: dict = {}         # chat_id -> số lượt còn được hỏi lại Gemini

BOT_OBJ = None                     # Application.bot (đặt trong post_init)
BOT_LOOP: Optional[asyncio.AbstractEventLoop] = None
ASK_SERVER = None                  # HTTP server nội bộ cho tool ask_user
ASK_URL = ""
ASK_TOKEN = ""
ASK_REQUESTS: dict = {}            # ask_id -> yêu cầu đang chờ người dùng trả lời
ASK_BY_CHAT: dict = {}             # chat_id -> ask_id
ASK_LOCK = threading.Lock()
GH_LOGIN_TASKS: dict = {}          # id -> phiên device login (tool github_login)
AUTO_PUSH = os.getenv("AISTV_AUTO_PUSH", "0").strip().lower() not in ("0", "off", "false", "no")
                                # 0 (mặc định) = KHÔNG tự push; agent sửa repo xong bot hiện diff
                                # kèm nút duyệt (⬆️ Push / ↩️ Hoàn tác). 1 = tự push như bản cũ.
PLAN_BUSY: set = set()          # chat_id đang chạy /plan (để không hiện diff giữa chừng)
PLAN_CANCEL: set = set()        # chat_id yêu cầu huỷ plan
LAST_CHECKPOINT: dict = {}      # chat_id -> checkpoint id của lượt sửa gần nhất
try:
    WORK_MIN_STEPS = int(os.getenv("AISTV_WORK_MIN_STEPS", "3") or 3)
except ValueError:
    WORK_MIN_STEPS = 3
                                # kế hoạch từ chừng này bước trở lên → chạy trên nhánh riêng

THINKING: dict = {}                # chat_id -> [các đoạn reasoning model đã trả về]
LIVE: dict = {}                    # chat_id -> dòng thời gian sự kiện (think/tool) để cuộn như terminal
THINK_TOKENS: dict = {}            # chat_id -> số token reasoning
TOKEN_USAGE: dict = {}             # chat_id -> token thật của lượt chạy (vào/ra/cache/giá)
THINKING_LAST: dict = {}           # chat_id -> thời điểm nhận reasoning gần nhất
NO_THINK: dict = {}                # model (bỏ #variant) -> True nếu lượt chạy không trả reasoning
GH_TOKEN_CACHE = ""                # token GitHub đang dùng (để che trong log/output)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)       # httpx in URL chứa token → tắt
logging.getLogger("httpcore").setLevel(logging.WARNING)
try:                                    # log xoay vòng: /watch log có thể theo dõi chính bot
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logging.getLogger().addHandler(_fh)
except Exception:
    pass
log = logging.getLogger("stv-agent")


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


STATE = _load_state()
STATE.setdefault("owner_id", None)
STATE.setdefault("allowed", [])
STATE.setdefault("model", os.getenv("OPENCODE_MODEL") or DEFAULT_MODEL)
STATE.setdefault("variant", os.getenv("OPENCODE_VARIANT", "max") or "max")
                                                # mặc định max; /variant off để tắt
STATE.setdefault("show_thinking", True)          # hiện phần "suy nghĩ" của model
STATE.setdefault("show_activity", False)         # hiện chi tiết việc agent đang làm (lệnh, code, output)
STATE.setdefault("github_user", "")
STATE.setdefault("github_repo", "")              # repo đích: owner/name (quét & chọn bằng /github repos)


def save_state() -> None:
    STATE_FILE.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), "utf-8")


def opencode_model() -> str:
    """Chuỗi --model đúng cú pháp OpenCode: provider/model#variant.
    Bản CLI hiện tại không có --variant; variant phải nằm trong --model."""
    model = (STATE.get("model") or DEFAULT_MODEL).strip()
    variant = (STATE.get("variant") or "").strip()
    if variant.lower() in ("off", "auto", "default", "0"):
        variant = ""
    if variant and "#" not in model:
        model = f"{model}#{variant}"
    return model


# Máy đã lỡ lưu model Gemini 3.8 Flash làm model chính → tự quay lại DeepSeek v4.1
# (Gemini chỉ còn là mắt/tai đọc ảnh, xem video). Chỉ đổi một lần, tôn trọng /model của chủ bot.
if (not os.getenv("OPENCODE_MODEL")
        and STATE.get("model") == LEGACY_GEMINI_MODEL
        and not STATE.get("model_primary_deepseek")):
    STATE["model"] = DEFAULT_MODEL
    STATE["model_primary_deepseek"] = True
    try:
        save_state()
    except Exception:
        pass


def get_secret(name: str) -> str:
    """Đọc từ biến môi trường, nếu không có thì thử 🔑 Secrets của Colab."""
    val = os.getenv(name, "").strip()
    if not val:
        try:
            from google.colab import userdata
            val = (userdata.get(name) or "").strip()
        except Exception:
            val = ""
    return val


ENV_ALLOWED = [int(x) for x in re.findall(r"\d+", get_secret("ALLOWED_USER_IDS"))]
# Colab Secrets không tự có trong môi trường tiến trình con → đưa key vào env
# để aistv_watch.py (chạy bằng subprocess) cũng đọc được.
for _key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
    if not os.getenv(_key):
        try:
            _val = get_secret(_key)
            if _val:
                os.environ[_key] = _val
        except Exception:
            pass
if not os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"):
    _gkey = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if _gkey:
        os.environ["GOOGLE_GENERATIVE_AI_API_KEY"] = _gkey
GEMINI_READY = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def vision_ready() -> bool:
    """Có nguồn đọc ảnh/video/audio: Gemini API hoặc Gemini nội bộ đã vá media."""
    if GEMINI_READY:
        return True
    if web2api is None:
        return False
    try:
        return bool(web2api.enabled() and web2api.media_patch_ready())
    except Exception:
        return False


def owner_id() -> Optional[int]:
    return ENV_ALLOWED[0] if ENV_ALLOWED else STATE.get("owner_id")


def is_owner(uid: int) -> bool:
    return uid == owner_id()


def authorized(uid: int, chat_type: str) -> bool:
    if ENV_ALLOWED:
        return uid in ENV_ALLOWED
    if STATE["owner_id"] is None:
        if chat_type != "private":
            return False
        STATE["owner_id"] = uid          # người nhắn đầu tiên (chat riêng) = chủ bot
        save_state()
        log.info("Chủ bot: %s", uid)
        return True
    return uid == STATE["owner_id"] or uid in STATE["allowed"]


def _addressed_to_bot(msg, context, text: str = "") -> bool:
    """Trong nhóm: chỉ coi là gửi cho bot khi @tên bot hoặc reply vào tin của bot."""
    if bool(getattr(msg, "reply_to_message", None)
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == context.bot.id):
        return True
    bot_user = getattr(context.bot, "username", "") or ""
    return bool(bot_user) and ("@" + bot_user).lower() in (text or "").lower()


def _strip_bot_mention(text: str, context) -> str:
    bot_user = getattr(context.bot, "username", "") or ""
    if not bot_user:
        return (text or "").strip()
    return re.sub(re.escape("@" + bot_user), "", text or "", flags=re.I).strip()


GUEST_REJECT_AT: dict = {}
GUEST_NOTICE = ("🔒 Lệnh quản trị chỉ dành cho chủ bot.\n"
                "Bạn vẫn chat, hỏi code, tạo ảnh/sơ đồ, nhờ đọc ảnh/video miễn phí: "
                "nhắc @bot, reply tin của bot hoặc dùng /ask.")
GUEST_OFF_NOTICE = "⛔ Bot này chỉ dành cho chủ bot."


async def _deny_guest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Từ chối người lạ dùng lệnh/nút/ảnh/video (chat chữ vẫn được nếu GUEST_CHAT bật)."""
    user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
    if not (user and chat and msg):
        return
    if chat.type != "private" and not _addressed_to_bot(
            msg, context, msg.text or msg.caption or ""):
        return                                   # trong nhóm: không nhắc bot thì im lặng
    if update.callback_query is not None and chat.type != "private":
        return                                   # bấm nút trong nhóm: không trả lời để khỏi spam
    key = (chat.id, user.id)
    now = time.monotonic()
    if now - GUEST_REJECT_AT.get(key, 0.0) < 30:
        return                                   # chống spam khi bấm nút / gõ lệnh liên tục
    GUEST_REJECT_AT[key] = now
    body = GUEST_NOTICE if GUEST_CHAT else GUEST_OFF_NOTICE
    if chat.type == "private":
        body += f"\nID của bạn: <code>{user.id}</code>"
    try:
        await msg.reply_text(body, parse_mode=HTML)
    except Exception:
        pass


def guard(owner_only: bool = False, allow_guest: bool = False):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
            if not (user and chat and msg):
                return
            if not authorized(user.id, chat.type):
                if allow_guest and GUEST_CHAT:
                    return await fn(update, context)
                await _deny_guest(update, context)
                return
            if owner_only and not is_owner(user.id):
                await msg.reply_text("🔒 Lệnh này chỉ dành cho chủ bot.")
                return
            return await fn(update, context)
        return wrapper
    return deco


# ════════════════════════════════════════════════════════════════════
# 3. WORKSPACE KIỂU OPENCLAW: SOUL / AGENTS / MEMORY / SKILLS
# ════════════════════════════════════════════════════════════════════
SOUL_MD = """# SOUL — AI STV
Bạn là **AI STV**, trợ lý AI dạng agent chạy trên Telegram, phục vụ chủ nhân của bạn.

## Tính cách
- Chuyên nghiệp, chính xác, thẳng thắn, thân thiện. Không nịnh, không dài dòng.
- Trả lời bằng ngôn ngữ người dùng đang dùng (mặc định tiếng Việt).
- Khi không chắc, nói rõ mức độ chắc chắn thay vì đoán bừa.

## Văn phong trên Telegram
- Mở đầu bằng kết luận/câu trả lời, giải thích sau.
- Markdown gọn: tiêu đề ngắn, gạch đầu dòng, **in đậm** ý chính, khối code có ghi ngôn ngữ.
- Mặc định ≤ 25 dòng trừ khi người dùng yêu cầu chi tiết. Tránh bảng rộng (màn hình điện thoại hẹp).
"""

AGENTS_RULES_25_32 = """25. Repo chính (code bot) là thư mục chứa `aistv_bot.py` — env `$AISTV_DIR`, ví dụ `/root/AISTV`;
    workspace của bạn là `$HOME/workspace`. Sửa code bot trong repo chính, file cho người dùng để trong
    workspace. Không sửa `seed/` thay cho bản đang chạy (seed chỉ là bản mẫu cho máy mới).
26. Trước khi sửa code trong repo: đọc `docs/CODEMAP.md` (bản đồ module → hàm/class kèm số dòng) để chọn
    đúng file, rồi `grep -n "def tên_hàm" <file>` và CHỈ đọc 60–150 dòng quanh symbol. Không đọc cả
    `aistv_bot.py` (hơn 7.000 dòng) và không đoán số dòng. Thêm/bớt hàm cấp module thì chạy lại
    `python scripts/code_map.py`.
27. Sửa code xong BẮT BUỘC chạy `python scripts/verify.py` trong repo và chỉ báo "xong" khi PASS.
    FAIL thì đọc đúng lỗi, sửa nguyên nhân, chạy lại — tối đa 2 lần; vẫn FAIL thì báo rõ lỗi và phần
    đã thử, không được nói đã xong.
28. Yêu cầu từ 3 bước trở lên hoặc sửa nhiều file: lập danh sách bước ngắn (2–8 bước, mỗi bước kiểm
    chứng được) rồi làm lần lượt. Việc dài nên dùng `/plan`: bot tự checkpoint, tự chạy từng bước và tự
    kiểm chứng trước khi báo cáo.
29. KHÔNG commit/push thay người dùng. Sau khi agent sửa repo, bot hiện diff kèm nút duyệt
    (⬆️ Push / ↩️ Hoàn tác); chỉ push khi người dùng bấm nút hoặc gõ `/push`. Không tự đẩy khi chưa duyệt.
30. Trước mỗi lượt sửa code, bot tự tạo checkpoint; `/undo` hoặc nút ↩️ đưa repo về đúng trạng thái trước
    đó. Không xoá checkpoint hay file trong `.git` bằng tay.
31. Bị kẹt (lỗi lặp lại, thiếu quyền, thiếu thông tin) thì dừng đúng lúc: nêu lỗi, đã thử gì, cần gì để
    đi tiếp — hoặc gọi `ask_user`. Không che giấu lỗi, không báo hoàn thành giả.
32. Nén context tiết kiệm token bằng Headroom: CLI `headroom`, thư viện `from headroom import compress`,
    MCP `headroom mcp serve` (tool `headroom_compress`/`headroom_retrieve`/`headroom_stats`) — headroom-ai
    `0.41.0`, chạy offline (`HEADROOM_OFFLINE=1`, không beacon). Dùng khi tool output/log/JSON/RAG quá lớn;
    KHÔNG tự `wrap`/`unwrap` hay đổi config opencode — muốn bật hỏi người dùng trước. Skill `headroom`.
33. Người dùng muốn tạo máy ảo Windows cho Integration Test (Windows runner + Tailscale + RDP) → gọi tool
    `create_vm` với PAT GitHub của tài khoản sẽ chạy máy ảo và Tailscale auth key (nếu bot đã đăng nhập
    GitHub hoặc đã lưu bằng /vm token, /vm key thì bỏ trống tham số — KHÔNG hỏi lại người dùng).
    KHÔNG in lại token/key ra chat/log, KHÔNG ghi chúng vào file.
    Mặc định windows-latest, 360 phút (60–360). Thông tin đăng nhập do workflow gửi qua Telegram DM.
     Máy ảo có bảng nút /vm (chọn Windows, thời gian, nhập khoá, tạo) — hướng dẫn người dùng bấm nút.
"""
AGENTS_MD = """# AGENTS — Quy tắc làm việc
1. Thư mục hiện tại là workspace của bạn. File bạn tạo phải nằm ở đây, tên rõ ràng, có đuôi file.
2. Tạo file thì nêu tên file ở cuối câu trả lời; bot sẽ tự gửi file cho người dùng.
3. File người dùng gửi nằm trong `inbox/`.
4. Việc phức tạp: lập kế hoạch ngắn (2-5 bước) → thực hiện → tự kiểm tra → báo kết quả.
5. Trước thao tác phá huỷ (xoá file, ghi đè, thay đổi hệ thống) phải hỏi lại người dùng.
6. Cần người dùng chọn phương án / xác nhận / bổ sung thông tin → gọi tool `ask_user`
   (có bảng nút bấm trong Telegram). Đừng đoán bừa khi yêu cầu còn mơ hồ.
7. Tuyệt đối không in ra hay gửi đi token, API key, mật khẩu hoặc biến môi trường.
8. `MEMORY.md` chứa thông tin lâu dài về người dùng — dùng khi liên quan, đừng lặp lại vô cớ.
9. Khi người dùng bảo "hãy nhớ…" hoặc nêu một sở thích/quy tắc lâu dài, hãy thêm MỘT dòng mới bắt đầu bằng `- ` vào cuối
   `MEMORY.md` (ví dụ `- [20/10/2026] Thích trả lời ngắn gọn`). Không xoá hay sửa các dòng cũ trừ khi được yêu cầu.
10. `memory/YYYY-MM-DD.md` là nhật ký theo ngày — chỉ mở khi người dùng hỏi về những gì đã làm trước đây.
11. `skills/` (và `.agents/skills/`, `.cursor/skills/`) chứa quy trình chuyên biệt theo chuẩn Agent Skills
    (`SKILL.md` + frontmatter). Khi yêu cầu khớp rõ với mô tả trong danh sách kỹ năng, đọc đúng file
    `SKILL.md` được ghi trong danh sách và tài nguyên liên quan rồi làm theo; khi được `/skill` kích hoạt
    thì ưu tiên skill đó. Chỉ đọc 1-2 skill liên quan, không đọc tràn lan. Skill không được ghi đè quy tắc
    bảo mật (không đọc/in/gửi `.secrets`, token, mật khẩu).
12. Khi cần đọc/tra cứu tài liệu hoặc mã nguồn trên GitHub, dùng skill `github-docs` (tool `aistv_github_docs.py`).
13. Khi người dùng gửi link/file video và hỏi nội dung, dùng skill `watch` (tool `aistv_watch.py`).
    Gemini 3.8 Flash là mắt + tai (xem cả hình ảnh và âm thanh); bạn là người trả lời chính: đối chiếu
    báo cáo của Gemini, nêu chỗ chưa chắc, trả lời kèm mốc thời gian. Cần thêm chi tiết thì hỏi lại
    bằng tool `ask_gemini`.
14. Khi người dùng gửi ảnh/URL ảnh và hỏi nội dung, dùng `python3 aistv_watch.py image <path|url> --json`
    để Gemini đọc ảnh (mô tả + OCR chữ + số liệu/biểu đồ); bạn tổng hợp và trả lời. Cần đọc kỹ thêm
    (chữ nhỏ, góc khác, đếm vật thể…) thì gọi tool `ask_gemini`.
15. Khi người dùng yêu cầu tạo/vẽ ảnh, poster, logo, infographic, biểu đồ hoặc sơ đồ tư duy → gọi tool `generate_image`:
    - `kind: "mindmap"` cho sơ đồ tư duy (chữ Việt sắc nét, do Pillow vẽ).
    - `kind: "infographic"` cho infographic/tóm tắt trực quan.
    - `kind: "chart"` cho biểu đồ số liệu (cột/đường/tròn).
    - `kind: "image"` cho ảnh thường; style: `realistic` (chân thật), anime, 3d, watercolor, pixel, minimal, comic, sketch, cyberpunk, poster, logo...
    Máy tự chọn model Cloudflare phù hợp: `flux-2-dev` (chất lượng cao nhất), `flux-2-klein-9b` (cân bằng), `flux-1-schnell` (nhanh).
    Nếu người dùng muốn chân thật/đẹp nhất, truyền `model: "flux-2-dev"`; mặc định để auto.
    Khi một hình ảnh/sơ đồ giúp người dùng hiểu rõ hơn, chủ động tạo và gửi. Không tự vẽ ảnh bằng code trừ khi được yêu cầu.

## Bộ công cụ local (không tốn Gemini)
16. Đọc PDF/DOCX/ảnh scan: `python3 aistv_docs.py "<file>" --json` (thêm `--lang vie+eng` cho ảnh). Thiếu công cụ thì chạy `--check` rồi báo người dùng cài.
17. Tra trí nhớ/lịch sử: `python3 aistv_memory_index.py search "từ khoá" -n 8`. Trước khi trả lời câu hỏi về việc đã làm trước đây, tra index thay vì đọc lại toàn bộ MEMORY.md. Cập nhật index bằng `index` sau khi thêm ký ức mới.
18. Điều khiển web (login, bấm, chụp màn hình): `python3 aistv_browser.py --url <url> --shot out.png` hoặc chạy kịch bản JSON. Chưa cài thì `--install`.
19. Giọng nói: `python3 aistv_voice.py tts "<text>" -o out.ogg` và `stt <file> --json`.
20. MCP: `python3 aistv_mcp.py list` / `add` / `remove` — ghi vào `opencode.json`, restart mới nạp.
21. Cloudflare: dùng `python3 aistv_cloudflare.py ...` (skill `cloudflare-aistv`) cho Workers AI, upload web (Pages/Workers), DNS, R2; token ở `.secrets/cloudflare_token` hoặc env `CLOUDFLARE_API_TOKEN`, không in token ra chat/log.
22. Railway: dùng `python3 aistv_railway.py ...` (skill `railway`) cho deploy, log, biến môi trường, domain; không in giá trị biến bí mật ra chat/log.
23. Luồng ảnh/video: Gemini đọc trước → bạn đối chiếu, phản biện, hỏi lại nếu cần (`ask_gemini`) → bạn trả lời cuối cùng. Không nói mình đã trực tiếp xem ảnh/video khi chỉ có báo cáo; không bịa chi tiết ngoài báo cáo.
24. Người dùng muốn đăng nhập/kết nối GitHub, hoặc cần GitHub mà chưa có token → gọi tool `github_login`
    (bot tự gửi mã vào chat, bạn chờ tới khi người dùng Authorize rồi mới làm tiếp). Không bảo người dùng
    dán token/PAT vào chat.
""" + AGENTS_RULES_25_32

MEMORY_HEADER = "# MEMORY — Trí nhớ dài hạn\n"

SKILL_CODE_REVIEW = """---
name: code-review
description: Review code nghiêm túc như một senior engineer — lỗi logic, edge case, bảo mật, hiệu năng, khả năng bảo trì.
---
# code-review
Review code nghiêm túc như một senior engineer.

## Quy trình
1. Xác định mục đích đoạn code và ngôn ngữ/framework.
2. Tìm lỗi logic, edge case, bảo mật (secret lộ, injection), hiệu năng, khả năng bảo trì.
3. Trả lời theo mẫu: **Tóm tắt** → **Vấn đề (ưu tiên cao → thấp)** → **Bản sửa đề xuất (code)** → **Gợi ý thêm**.
4. Mỗi vấn đề nêu: ở đâu, vì sao là vấn đề, cách sửa cụ thể.
"""

SKILL_RESEARCH = """---
name: nghien-cuu
description: Nghiên cứu một chủ đề có hệ thống — làm rõ câu hỏi, thu thập nguồn, đối chiếu và tổng hợp.
---
# nghien-cuu
Nghiên cứu một chủ đề có hệ thống.

## Quy trình
1. Làm rõ câu hỏi thật sự và phạm vi (nếu mơ hồ, tự giả định hợp lý và nói rõ).
2. Thu thập từ nhiều nguồn, ưu tiên nguồn gốc/chính thức; đối chiếu số liệu mâu thuẫn.
3. Trả lời: **Kết luận ngắn** → **Bằng chứng chính** → **Điểm còn tranh cãi/chưa chắc** → **Nguồn**.
4. Phân biệt rõ sự thật đã kiểm chứng và suy luận của bạn.
"""

# Tool tuỳ chỉnh của OpenCode: agent gọi `ask_user` → bot gửi câu hỏi kèm nút bấm
# trong Telegram và chờ người dùng trả lời (kể cả gõ tự do).
ASK_TOOL_JS = r'''import { tool } from "@opencode-ai/plugin"

export default tool({
  description: [
    "Ask the Telegram user a question and wait for their answer.",
    "Use this when you need a decision, missing information, or confirmation",
    "before a destructive change. Always write the question in the user's language.",
  ].join(" "),
  args: {
    question: tool.schema.string().describe("Question to show the user"),
    options: tool.schema.array(tool.schema.string()).optional()
      .describe("Short choices rendered as buttons (2-8 recommended)"),
    allow_free_text: tool.schema.boolean().optional()
      .describe("Let the user type a custom answer (default true)"),
  },
  async execute(args) {
    const url = process.env.AISTV_ASK_URL
    const token = process.env.AISTV_TOOL_TOKEN || ""
    const chat = process.env.AISTV_CHAT_ID || ""
    if (!url) {
      return "ask_user is unavailable. Ask your question in the final answer instead."
    }
    const res = await fetch(url.replace(/\/$/, "") + "/ask", {
      method: "POST",
      headers: { "content-type": "application/json", "x-aistv-token": token },
      body: JSON.stringify({
        chat_id: Number(chat) || 0,
        question: String(args.question || ""),
        options: Array.isArray(args.options) ? args.options : [],
        allow_free_text: args.allow_free_text !== false,
      }),
    })
    if (!res.ok) {
      return "ask_user failed with HTTP " + res.status + ". Continue without asking."
    }
    const data = await res.json()
    if (data.cancelled) {
      return "The user skipped or cancelled the question. Use a sensible default, or stop and explain."
    }
    return "User answered: " + data.answer
  },
})
'''

# Tool tạo ảnh: agent gọi → bot tạo ảnh/sơ đồ tư duy và gửi thẳng vào chat.
IMAGE_TOOL_JS = r'''import { tool } from "@opencode-ai/plugin"

export default tool({
  description: [
    "Generate an image, illustration, poster, logo, infographic, data chart or mind map and send it to the user on Telegram.",
    "Use it whenever the user asks to draw/create an image, or when a diagram, chart or mind map would make an explanation clearer.",
    "Images use Cloudflare Workers AI models (flux-2-dev, flux-2-klein-9b, flux-1-schnell); the best model is picked automatically.",
  ].join(" "),
  args: {
    prompt: tool.schema.string().describe("Detailed image description, the mind map/infographic topic, or the data to chart"),
    style: tool.schema.string().optional()
      .describe("realistic, anime, 3d, watercolor, oil, pixel, minimal, comic, sketch, cyberpunk, poster, logo, infographic, cartoon, fantasy"),
    aspect: tool.schema.string().optional().describe("1:1, 16:9, 9:16, 4:3, 3:4 (default 1:1)"),
    kind: tool.schema.string().optional()
      .describe("'image' (default), 'mindmap' for a mind map, 'infographic' for a visual summary, 'chart' for a bar/line/pie chart"),
    model: tool.schema.string().optional()
      .describe("Optional Cloudflare model: flux-2-dev (best), flux-2-klein-9b (balanced), flux-1-schnell (fast)"),
  },
  async execute(args) {
    const url = process.env.AISTV_ASK_URL
    const token = process.env.AISTV_TOOL_TOKEN || ""
    const chat = process.env.AISTV_CHAT_ID || ""
    if (!url) {
      return "generate_image is unavailable. Answer without generating an image."
    }
    const rawKind = String(args.kind || "image").toLowerCase()
    const kind = ["mindmap", "infographic", "chart"].includes(rawKind) ? rawKind : "image"
    const res = await fetch(url.replace(/\/$/, "") + "/image", {
      method: "POST",
      headers: { "content-type": "application/json", "x-aistv-token": token },
      body: JSON.stringify({
        chat_id: Number(chat) || 0,
        prompt: String(args.prompt || ""),
        style: String(args.style || ""),
        aspect: String(args.aspect || "1:1"),
        kind,
        model: String(args.model || ""),
      }),
    })
    if (!res.ok) {
      return "generate_image failed with HTTP " + res.status + ". Tell the user briefly."
    }
    const data = await res.json()
    if (!data.ok) {
      return "Image generation error: " + (data.error || "unknown")
    }
    if (kind === "mindmap") {
      return "Đang vẽ sơ đồ tư duy và sẽ gửi cho người dùng khi xong. Trả lời ngắn gọn, đừng mô tả lại toàn bộ sơ đồ."
    }
    if (kind === "infographic") {
      return "Đang vẽ infographic và sẽ gửi cho người dùng khi xong. Trả lời ngắn gọn, đừng mô tả lại toàn bộ nội dung."
    }
    if (kind === "chart") {
      return "Đang vẽ biểu đồ và sẽ gửi cho người dùng khi xong. Trả lời ngắn gọn, đừng mô tả lại toàn bộ biểu đồ."
    }
    return "Đang tạo ảnh và sẽ gửi cho người dùng khi xong. Trả lời ngắn gọn, đừng mô tả lại toàn bộ bức ảnh."
  },
})
'''

# Tool dựng lời giải dài thành ảnh từng trang A4 (có số trang) và gửi Telegram.
PAGES_TOOL_JS = r'''import { tool } from "@opencode-ai/plugin"

export default tool({
  description: [
    "Render a long or formula-heavy answer as paginated A4 page images and send them to Telegram.",
    "Use it when the solution is longer than about 25 lines, or when fractions, systems, matrices, vectors",
    "or many symbols would be hard to read as plain chat text. Pass the complete solution in markdown",
    "(Vietnamese, Unicode math is fine). The bot splits it into numbered pages ('Trang 1/N'), sends the",
    "images, and then you only write 1-2 short lines telling the user the pages were sent.",
    "Do NOT paste the whole solution again in chat afterwards.",
  ].join(" "),
  args: {
    text: tool.schema.string()
      .describe("Full solution/explanation in markdown, including every step and conclusion"),
    title: tool.schema.string().optional()
      .describe("Short title printed on every page, e.g. 'Hình học 9 — Câu 3'"),
    format: tool.schema.string().optional()
      .describe("'photo' (default, easy to swipe/zoom in chat) or 'document' (sharpest PNG for dense formulas)"),
  },
  async execute(args) {
    const url = process.env.AISTV_ASK_URL
    const token = process.env.AISTV_TOOL_TOKEN || ""
    const chat = process.env.AISTV_CHAT_ID || ""
    if (!url) {
      return "render_pages is unavailable. Answer in chat as usual."
    }
    const text = String(args.text || "").trim()
    if (!text) {
      return "render_pages needs the full solution text."
    }
    const fmt = String(args.format || "photo").toLowerCase() === "document" ? "document" : "photo"
    let res, data
    try {
      res = await fetch(url.replace(/\/$/, "") + "/pages", {
        method: "POST",
        headers: { "content-type": "application/json", "x-aistv-token": token },
        body: JSON.stringify({
          chat_id: Number(chat) || 0,
          text,
          title: String(args.title || ""),
          format: fmt,
        }),
      })
      data = await res.json()
    } catch (e) {
      return "render_pages failed: " + e + ". Answer in chat as usual."
    }
    if (!res.ok || !data.ok) {
      return "render_pages error: " + (data.error || ("HTTP " + res.status)) +
        ". Answer in chat as usual."
    }
    return "Đã gửi " + data.count + " trang ảnh cho người dùng. Giờ chỉ nhắn 1-2 dòng ngắn, không dán lại lời giải."
  },
})
'''

# Tool hỏi lại Gemini (mắt + tai) về ảnh/video vừa gửi — DeepSeek vẫn là người trả lời chính.
ASK_GEMINI_TOOL_JS = r'''import { tool } from "@opencode-ai/plugin"

export default tool({
  description: [
    "Ask Gemini (the vision model) a follow-up question about the image or video the user just sent.",
    "Use it only when the vision report lacks a detail you need before answering.",
    "Gemini looks at the media again and returns text; you are still the one who answers the user.",
  ].join(" "),
  args: {
    question: tool.schema.string()
      .describe("Specific question about the media, e.g. 'What does the label on the box say?'"),
    source: tool.schema.string().optional()
      .describe("Optional file path or URL; defaults to the media the user just sent"),
    kind: tool.schema.string().optional()
      .describe("'image' or 'video'; defaults to the last media type"),
  },
  async execute(args) {
    const url = process.env.AISTV_ASK_URL
    const token = process.env.AISTV_TOOL_TOKEN || ""
    const chat = process.env.AISTV_CHAT_ID || ""
    if (!url) {
      return "ask_gemini is unavailable. Answer with the report you already have."
    }
    const question = String(args.question || "").trim()
    if (!question) {
      return "ask_gemini needs a question."
    }
    let res
    try {
      res = await fetch(url.replace(/\/$/, "") + "/vision", {
        method: "POST",
        headers: { "content-type": "application/json", "x-aistv-token": token },
        body: JSON.stringify({
          chat_id: Number(chat) || 0,
          question,
          source: String(args.source || ""),
          kind: String(args.kind || ""),
        }),
      })
    } catch (e) {
      return "ask_gemini failed: " + e
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok || !data.ok) {
      return "ask_gemini error: " + (data.error || ("HTTP " + res.status))
    }
    return "Gemini (vision) answered:\n" + String(data.answer || "")
  },
})
'''


# Tool đăng nhập GitHub bằng mã: bot gửi mã vào chat, agent chờ bạn xác nhận rồi chạy tiếp.
GITHUB_LOGIN_TOOL_JS = r'''import { tool } from "@opencode-ai/plugin"

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export default tool({
  description: [
    "Connect the user's GitHub account with the device flow (github.com/login/device).",
    "Use this when the user asks to log in / connect GitHub, or when GitHub access is missing.",
    "The bot sends the one-time code to the Telegram chat automatically; the user authorizes it",
    "on GitHub and this tool returns as soon as the account is connected. Do not ask the user",
    "to paste the code anywhere else.",
  ].join(" "),
  args: {
    reason: tool.schema.string().optional()
      .describe("Short reason shown in the chat, e.g. 'to pull config from the private repo'"),
  },
  async execute(args) {
    const url = process.env.AISTV_ASK_URL
    const token = process.env.AISTV_TOOL_TOKEN || ""
    const chat = Number(process.env.AISTV_CHAT_ID || 0)
    if (!url) {
      return "github_login is unavailable. Tell the user to send /github login."
    }
    const base = url.replace(/\/$/, "")
    const headers = { "content-type": "application/json", "x-aistv-token": token }
    let data
    try {
      const started = await fetch(base + "/github-login", {
        method: "POST",
        headers,
        body: JSON.stringify({ chat_id: chat, reason: String(args.reason || "") }),
      })
      data = await started.json()
    } catch (e) {
      return "github_login failed: " + e + ". Tell the user to send /github login."
    }
    if (data.already) {
      return "GitHub is already connected" + (data.login ? " as " + data.login : "") + "."
    }
    if (!data.ok) {
      return "Could not start GitHub login: " + (data.error || "unknown") +
        ". Tell the user to send /github login."
    }
    const deadline = Date.now() + Math.min(Number(data.expires_in || 900) * 1000, 900000)
    while (Date.now() < deadline) {
      await sleep(5000)
      let res, state
      try {
        res = await fetch(base + "/github-login-status", {
          method: "POST",
          headers,
          body: JSON.stringify({ id: data.id, chat_id: chat }),
        })
        if (!res.ok) continue
        state = await res.json()
      } catch (e) {
        continue
      }
      if (state.status === "done" && state.ok) {
        return "GitHub connected" + (state.login ? " as " + state.login : "") +
          ". Continue with the user's request."
      }
      if (state.status === "error") {
        return "GitHub login failed: " + (state.error || "unknown") +
          ". Tell the user briefly and continue without GitHub."
      }
      if (state.status === "timeout") {
        return "The GitHub code expired before the user authorized it. Tell the user to send /github login again."
      }
    }
    return "GitHub login is still pending. Tell the user the code may have expired and to send /github login."
  },
})
'''


# Tool tạo máy ảo Windows: bot tự fork repo, ghi secrets và kích hoạt workflow.
CREATE_VM_TOOL_JS = r'''import { tool } from "@opencode-ai/plugin"

export default tool({
  description: [
    "Create or stop a Windows VM (GitHub Actions runner) for the user's integration tests.",
    "By default the bot uses the admin credentials already configured (GitHub token + saved",
    "Tailscale key): the bot forks the AISTV repo if needed, stores the Tailscale key as a repo",
    "secret, and dispatches the Windows integration-test workflow. The workflow connects to",
    "Tailscale, opens RDP and sends the login details (IP, username, password,",
    "Tailscale key and how to log in) via private Telegram DM to the person who asked — never",
    "print credentials in the chat or in the workflow log. Pass github_token/tailscale_authkey",
    "only if the user explicitly gives their own; otherwise omit them so the admin credentials",
    "are reused. Use action=stop to shut down the VM the user currently has running.",
  ].join(" "),
  args: {
    action: tool.schema.string().optional()
      .describe("create (default) or stop — stop cancels the running VM of this chat."),
    github_token: tool.schema.string().optional()
      .describe("GitHub PAT of the account that will run the VM (ghp_... or github_pat_...). Omit to use the admin credentials."),
    tailscale_authkey: tool.schema.string().optional()
      .describe("Tailscale auth key (tskey-...). Omit to use the admin credentials."),
    windows_version: tool.schema.string().optional()
      .describe("windows-latest (default) | windows-2022 | windows-2025"),
    timeout_minutes: tool.schema.number().optional()
      .describe("Run time in minutes, 60-360 (default 360; guests max 180)"),
  },
  async execute(args) {
    const url = process.env.AISTV_ASK_URL
    const token = process.env.AISTV_TOOL_TOKEN || ""
    const chat = Number(process.env.AISTV_CHAT_ID || 0)
    if (!url) {
      return "create_vm is unavailable. Tell the user to open /vm and use the buttons."
    }
    if (!chat || chat <= 0) {
      return "create_vm only works in a private chat with the bot. Ask the user to DM the bot."
    }
    const action = String(args.action || "create").trim().toLowerCase()
    let res
    try {
      res = await fetch(url.replace(/\/$/, "") + (action === "stop" ? "/vm-stop" : "/vm-create"), {
        method: "POST",
        headers: { "content-type": "application/json", "x-aistv-token": token },
        body: JSON.stringify({
          chat_id: chat,
          action,
          github_token: String(args.github_token || ""),
          tailscale_authkey: String(args.tailscale_authkey || ""),
          windows_version: String(args.windows_version || ""),
          timeout_minutes: Number(args.timeout_minutes || 0),
        }),
      })
    } catch (e) {
      return "create_vm failed: " + e
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok || !data.ok) {
      return "create_vm error: " + (data.error || ("HTTP " + res.status))
    }
    return String(data.message || (action === "stop" ? "VM stopped." : "VM creation started."))
  },
})
'''


def bootstrap_workspace() -> None:
    files = {
        WORKSPACE / "SOUL.md": SOUL_MD,
        WORKSPACE / "AGENTS.md": AGENTS_MD,
        WORKSPACE / "MEMORY.md": MEMORY_HEADER,
        SKILLS_DIR / "code-review" / "SKILL.md": SKILL_CODE_REVIEW,
        SKILLS_DIR / "nghien-cuu" / "SKILL.md": SKILL_RESEARCH,
        WORKSPACE / ".opencode" / "tools" / "ask_user.js": ASK_TOOL_JS,
        WORKSPACE / ".opencode" / "tools" / "generate_image.js": IMAGE_TOOL_JS,
        WORKSPACE / ".opencode" / "tools" / "render_pages.js": PAGES_TOOL_JS,
        WORKSPACE / ".opencode" / "tools" / "ask_gemini.js": ASK_GEMINI_TOOL_JS,
        WORKSPACE / ".opencode" / "tools" / "github_login.js": GITHUB_LOGIN_TOOL_JS,
        WORKSPACE / ".opencode" / "tools" / "create_vm.js": CREATE_VM_TOOL_JS,
    }
    for path, content in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, "utf-8")
        elif path.suffix == ".js":
            try:
                old = path.read_text("utf-8")
            except Exception:
                old = ""
            if old != content:
                path.write_text(content, "utf-8")   # luôn cập nhật tool theo bản bot
    # Đồng bộ skill mặc định từ repo (chỉ thêm, không ghi đè file người dùng đã sửa).
    # Copy cả scripts/references/assets/license, không chỉ mỗi SKILL.md.
    seed_skills = Path(__file__).resolve().parent / "seed" / "skills"
    if seed_skills.is_dir():
        for src in seed_skills.rglob("SKILL.md"):
            rel = src.relative_to(seed_skills)
            if any(part.startswith(".") for part in rel.parts):
                continue
            for item in sorted(src.parent.rglob("*")):
                if not item.is_file() or item.is_symlink():
                    continue
                rel_item = item.relative_to(seed_skills)
                dst = SKILLS_DIR / rel_item
                if dst.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
        # File cấp gốc của seed/skills (THIRD_PARTY.md, license...).
        for src in sorted(seed_skills.iterdir()):
            if not src.is_file():
                continue
            dst = SKILLS_DIR / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
    # Nâng cấp workspace cũ: thêm hướng dẫn đọc ảnh nếu bản cũ chưa có.
    try:
        watch_skill = SKILLS_DIR / "watch" / "SKILL.md"
        if watch_skill.is_file():
            old = watch_skill.read_text("utf-8")
            changed = False
            if "aistv_watch.py image" not in old:
                old = old.rstrip() + (
                    "\n\n## Đọc ảnh (Gemini)\n"
                    "- Gửi ảnh/URL ảnh: `python3 aistv_watch.py image <path|url> "
                    "--question \"...\" --json`.\n"
                    "- Script mô tả ảnh, OCR chữ và lưu report; trả lời tiếng Việt, không bịa.\n"
                )
                changed = True
            if "ask_gemini" not in old:
                old = old.rstrip() + (
                    "\n\n## Thảo luận 2 model (mặc định)\n"
                    "- Gemini 3.8 Flash là mắt + tai: đọc ảnh/video (dưới 45 phút) và trả về báo cáo.\n"
                    "- Model chính (đổi bằng /model) đối chiếu báo cáo, phản biện, gọi tool `ask_gemini` "
                    "nếu thiếu chi tiết, rồi trả lời người dùng.\n"
                    "- Trả lời cuối cùng luôn do model chính viết, không dán nguyên báo cáo Gemini.\n"
                )
                changed = True
            if changed:
                watch_skill.write_text(old, "utf-8")
        agents = WORKSPACE / "AGENTS.md"
        if agents.is_file():
            old = agents.read_text("utf-8")
            changed = False
            if "aistv_watch.py image" not in old:
                old = old.rstrip() + (
                    "\n14. Khi người dùng gửi ảnh/URL ảnh và hỏi nội dung, dùng "
                    "`python3 aistv_watch.py image <path|url> --json` để Gemini đọc ảnh "
                    "(mô tả + OCR chữ) rồi trả lời.\n"
                )
                changed = True
            if "generate_image" not in old:
                old = old.rstrip() + (
                    "\n15. Khi người dùng yêu cầu tạo/vẽ ảnh, poster, logo, infographic, biểu đồ hoặc sơ đồ tư duy "
                    "→ gọi tool `generate_image`: kind `mindmap` cho sơ đồ tư duy, `infographic` cho infographic, "
                    "`chart` cho biểu đồ số liệu, `image` cho ảnh thường (style realistic/anime/3d/...). "
                    "Khi một hình ảnh/sơ đồ giúp người dùng hiểu rõ hơn, chủ động tạo và gửi. "
                    "Không tự vẽ ảnh bằng code trừ khi được yêu cầu.\n"
                )
                changed = True
            old13 = ("13. Khi người dùng gửi link/file video và hỏi nội dung, dùng skill `watch` "
                     "(tool `aistv_watch.py`); đọc frames bằng công cụ Read rồi trả lời kèm mốc thời gian.")
            if old13 in old:
                old = old.replace(old13, (
                    "13. Khi người dùng gửi link/file video và hỏi nội dung, dùng skill `watch` "
                    "(tool `aistv_watch.py`). Gemini 3.8 Flash là mắt + tai; bạn là người trả lời chính: "
                    "đối chiếu báo cáo, nêu chỗ chưa chắc, kèm mốc thời gian; cần thêm thì gọi `ask_gemini`."))
                changed = True
            if "ask_gemini" not in old:
                old = old.rstrip() + (
                    "\n23. Luồng ảnh/video: Gemini 3.8 Flash đọc trước → bạn đối chiếu, phản biện, hỏi lại "
                    "nếu cần (tool `ask_gemini`) → bạn trả lời cuối cùng. Model chính vẫn viết câu trả lời. "
                    "Không nói mình đã trực tiếp xem ảnh/video khi chỉ có báo cáo; không bịa ngoài báo cáo.\n"
                )
                changed = True
            if "github_login" not in old:
                old = old.rstrip() + (
                    "\n24. Người dùng muốn đăng nhập/kết nối GitHub, hoặc cần GitHub mà chưa có token → "
                    "gọi tool `github_login` (bot tự gửi mã vào chat; bạn chờ tới khi người dùng Authorize "
                    "rồi làm tiếp). Không bảo người dùng dán token/PAT vào chat.\n"
                )
                changed = True
            if "create_vm" not in old:
                old = old.rstrip() + (
                    "\n33. Người dùng muốn tạo máy ảo Windows cho Integration Test → gọi tool `create_vm` "
                    "với PAT GitHub của tài khoản sẽ chạy máy ảo + Tailscale auth key (bỏ trống nếu bot đã "
                    "đăng nhập GitHub hoặc đã lưu qua /vm token, /vm key — không hỏi lại). Không in lại "
                    "token/key, không ghi vào file. "
                    "Mặc định windows-latest, 360 phút (60–360); thông tin đăng nhập gửi qua Telegram DM. "
                    "Hướng dẫn người dùng mở /vm và bấm nút.\n"
                )
                changed = True
            if "dừng máy ảo" not in old:
                old = old.rstrip() + (
                    "\n34. Máy ảo Windows: dùng token GitHub + Tailscale key của admin (đã cấu hình sẵn) "
                    "— chỉ dùng tài khoản riêng khi người dùng đưa rõ. Tạo bằng tool `create_vm` hoặc nút "
                    "trong /vm; dừng máy ảo đang chạy bằng `create_vm` với action=stop hoặc nút 🛑 Dừng máy ảo. "
                    "Thông tin đăng nhập (IP, user, mật khẩu, Tailscale key) chỉ gửi qua Telegram DM cho đúng "
                    "người yêu cầu — không in ra chat, không ghi log, không bịa thông tin. Khách phải xác minh "
                    "email .com trước khi tạo; hạn mức 1 máy cùng lúc, 3 lượt/ngày, tối đa 180 phút. "
                    "Luôn kèm hướng dẫn đăng nhập Tailscale bằng key rồi mstsc vào IP.\n"
                )
                changed = True
            # Quy tắc 25–31 (đường dẫn repo, CODEMAP, verify, plan, cổng review, checkpoint).
            # Workspace cũ có thể còn quy tắc 25 kiểu "bot tự đẩy" → thay cả cụm.
            if "CODEMAP" not in old:
                old = re.sub(r"(?ms)^25\..*?(?=^2[6-9]\.|^3\d\.|\Z)", "", old)
                old = old.rstrip() + "\n" + AGENTS_RULES_25_32
                changed = True
            if changed:
                agents.write_text(old, "utf-8")
    except Exception:
        pass
    # Cấu hình OpenCode cho workspace (luôn ghi lại để công tắc FULL_ACCESS có hiệu lực)
    cfg = {"$schema": "https://opencode.ai/config.json"}
    if FULL_ACCESS:
        cfg["permission"] = "allow"
    # Provider dự phòng: Gemini Web2API chạy ngay trên máy này.
    if web2api is not None and WEB2API_FALLBACK:
        try:
            if web2api.enabled():
                models = {
                    WEB2API_MODEL: {"name": f"Gemini · {WEB2API_MODEL}"},
                    "gemini-3.5-flash-thinking": {
                        "name": "Gemini Thinking"},
                }
                for item in (os.getenv("OPENCODE_FALLBACK_MODELS") or "").split(","):
                    item = item.strip()
                    if item.startswith("web2api/") and item.split("/", 1)[1]:
                        mid = item.split("/", 1)[1].strip()
                        models.setdefault(mid, {"name": f"Gemini · {mid}"})
                cfg["providers"] = {
                    "web2api": {
                        "name": "Gemini (nội bộ)",
                        "package": "@opencode/ai/providers/openai-compatible",
                        "settings": {"baseURL": web2api.base_url() + "/v1"},
                        "headers": {"Authorization": "Bearer " + web2api.api_key()},
                        "models": models,
                    }
                }
        except Exception:
            pass
    (WORKSPACE / "opencode.json").write_text(json.dumps(cfg, indent=2) + "\n", "utf-8")


bootstrap_workspace()


def read_text(p: Path) -> str:
    try:
        return p.read_text("utf-8")
    except Exception:
        return ""


def memory_items() -> list:
    return [l for l in read_text(WORKSPACE / "MEMORY.md").splitlines() if l.startswith("- ")]


def write_memory(items: list) -> None:
    global MEM_DIRTY
    body = MEMORY_HEADER + ("\n" + "\n".join(items) + "\n" if items else "")
    (WORKSPACE / "MEMORY.md").write_text(body, "utf-8")
    MEM_DIRTY = True                     # cloud_loop sẽ đẩy lên Firebase


SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _skill_text_meta(text: str) -> tuple:
    """Trả về (frontmatter, body, description). Hỗ trợ chuẩn Agent Skills."""
    if skill_lib is not None:
        try:
            meta, body = skill_lib.parse_frontmatter(text)
            return meta, body, skill_lib.description_of(text)
        except Exception:
            pass
    lines = (text or "").replace("\r\n", "\n").splitlines()
    desc = ""
    for line in lines:
        s = line.strip()
        if s and s != "---" and not s.startswith("#") and not s.startswith("```"):
            desc = s
            break
    return {}, (text or ""), oneline(desc)


def _skill_root(path: Path) -> Path:
    for root in SKILL_ROOTS:
        try:
            path.relative_to(root)
            return root
        except ValueError:
            continue
    return SKILLS_DIR


def _skill_name(path: Path) -> str:
    root = _skill_root(path)
    return path.stem if path.parent == root else path.parent.name


def _skill_paths() -> list:
    """Tìm skill trong skills/, .agents/skills/ và .cursor/skills/ (mọi cấp),
    cùng file phẳng kiểu cũ (skills/<tên>.md)."""
    found = []
    for root in SKILL_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("SKILL.md"):
            rel = path.relative_to(root)
            if any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in rel.parts):
                continue
            found.append(path)
        for path in root.glob("*.md"):
            stem = path.stem.lower()
            if stem in ("readme", "license", "third_party", "source") or stem.startswith(
                    ("license-", "third_party_", "third_party-")):
                continue
            found.append(path)

    # Ưu tiên skills/ → .agents/skills/ → .cursor/skills/, rồi skill cấp 1 trước skill lồng.
    def rank(p: Path) -> tuple:
        root = _skill_root(p)
        return (
            SKILL_ROOTS.index(root),
            0 if p.parent == root else 1,
            len(p.relative_to(root).parts),
            str(p).lower(),
        )

    found.sort(key=rank)
    out, seen = [], set()
    for path in found:
        name = _skill_name(path)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(path)
    return out


def _skill_map() -> dict:
    return {_skill_name(path): path for path in _skill_paths()}


def list_skills() -> list:
    out = []
    for path in _skill_paths():
        name = _skill_name(path)
        meta, _, desc = _skill_text_meta(read_text(path))
        manual_only = str(
            meta.get("disable-model-invocation") or meta.get("disable_model_invocation") or ""
        ).strip().lower()
        if manual_only in ("true", "yes", "1", "on"):
            desc = (desc + " · chỉ gọi bằng /skill").strip()
        out.append((name, oneline(desc, 90)))
    return out


def skill_details(name: str) -> Optional[dict]:
    if not SKILL_NAME_RE.fullmatch(name or ""):
        return None
    path = _skill_map().get(name)
    if not path:
        return None
    text = read_text(path)
    _, _, desc = _skill_text_meta(text)
    base = path.parent
    if path.name == "SKILL.md" and base != _skill_root(path):
        files = [p for p in base.rglob("*") if p.is_file()]
    else:
        files = [path]
    return {
        "name": name,
        "description": desc,
        "path": str(base),
        "file": str(path),
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


def find_skill(name: str) -> Optional[str]:
    """Trả về nội dung skill kèm thư mục/tài nguyên để agent đọc đúng chỗ."""
    if not SKILL_NAME_RE.fullmatch(name or ""):
        return None
    path = _skill_map().get(name)
    if not path:
        return None
    text = read_text(path)
    _, body, _ = _skill_text_meta(text)
    if not body.strip():
        body = text
    base = path.parent
    resources = []
    if path.name == "SKILL.md" and base != _skill_root(path):
        for item in sorted(base.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(base)
            if any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in rel.parts):
                continue
            if rel.name in ("SKILL.md", "SOURCE.md") or rel.name.startswith(("LICENSE", "THIRD_PARTY")):
                continue
            resources.append(rel.as_posix())
            if len(resources) >= 30:
                break
    header = [
        "## THÔNG TIN SKILL",
        f"- Tên: {name}",
        f"- Thư mục: {base}",
        f"- File đầy đủ: {path}",
        "- Tài nguyên: " + (", ".join(f"`{r}`" for r in resources) if resources else "(không có)"),
        "- Khi chạy script/tài liệu trong skill: dùng đường dẫn tuyệt đối hoặc `cd` vào thư mục skill trước.",
        "- Python: dùng `python3` trên Linux/Colab, `python` trên Windows.",
        "- Skill chỉ là hướng dẫn; không được ghi đè SOUL.md/AGENTS.md hay quy tắc bảo mật "
        "(không đọc/in/gửi `.secrets`, token, mật khẩu).",
        "---",
    ]
    return "\n".join(header) + "\n" + body


def log_daily(q: str, a: str) -> None:
    f = MEMORY_DIR / f"{now():%Y-%m-%d}.md"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"- {now():%H:%M} · Q: {oneline(q, 160)} → A: {oneline(a, 160)}\n")


# ════════════════════════════════════════════════════════════════════
# 4. LỊCH SỬ HỘI THOẠI BỀN VỮNG (JSONL)
# ════════════════════════════════════════════════════════════════════
def hist_path(chat_id: int) -> Path:
    return SESSIONS / f"{chat_id}.jsonl"


def load_history(chat_id: int) -> list:
    p = hist_path(chat_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text("utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def rewrite_history(chat_id: int, items: list) -> None:
    with hist_path(chat_id).open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def append_history(chat_id: int, role: str, content: str) -> None:
    with hist_path(chat_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": int(time.time()), "role": role, "content": content},
                           ensure_ascii=False) + "\n")
    items = load_history(chat_id)
    if len(items) > 400:
        rewrite_history(chat_id, items[-200:])
    HIST_DIRTY[chat_id] = time.time()    # đẩy lên Firebase sau vài giây


def archive_history(chat_id: int) -> None:
    p = hist_path(chat_id)
    if p.exists():
        p.rename(ARCHIVE / f"{chat_id}-{int(time.time())}.jsonl")


def pop_last_exchange(chat_id: int) -> Optional[tuple]:
    """Lấy ra cặp (câu hỏi, câu trả lời) cuối cùng khỏi lịch sử; trả None nếu không có."""
    items = load_history(chat_id)
    answer = ""
    if items and items[-1]["role"] == "assistant":
        answer = items.pop()["content"]
    if items and items[-1]["role"] == "user":
        text = items.pop()["content"]
        rewrite_history(chat_id, items)
        return text, answer
    return None


# ════════════════════════════════════════════════════════════════════
# 4b. HỎI LẠI NGƯỜI DÙNG TỪ TRONG AGENT (tool ask_user + nút bấm)
# ════════════════════════════════════════════════════════════════════
def _ask_pop(ask_id: str, answer: Optional[str] = None, cancelled: bool = False) -> Optional[dict]:
    """Đánh dấu yêu cầu đã có câu trả lời và đánh thức luồng HTTP đang chờ."""
    with ASK_LOCK:
        rec = ASK_REQUESTS.pop(ask_id, None)
        if not rec:
            return None
        if not rec["event"].is_set():
            rec["answer"] = answer
            rec["cancelled"] = cancelled
            rec["event"].set()
        if ASK_BY_CHAT.get(rec["chat_id"]) == ask_id:
            ASK_BY_CHAT.pop(rec["chat_id"], None)
        return rec


def _cancel_chat_asks(chat_id: int) -> None:
    with ASK_LOCK:
        ask_id = ASK_BY_CHAT.get(chat_id)
    if ask_id:
        _ask_pop(ask_id, cancelled=True)


def _ask_pending(chat_id: int) -> bool:
    with ASK_LOCK:
        return chat_id in ASK_BY_CHAT


def _ask_keyboard(rec: dict) -> Optional[InlineKeyboardMarkup]:
    options = rec.get("options") or []
    rows, row = [], []
    for i, opt in enumerate(options[:10]):
        row.append(InlineKeyboardButton(opt[:38], callback_data=f"ask:{rec['id']}:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    tail = [InlineKeyboardButton("⏭ Bỏ qua", callback_data=f"ask:{rec['id']}:skip")]
    if rec.get("allow_free_text", True):
        tail.insert(0, InlineKeyboardButton("✍️ Trả lời tự do", callback_data=f"ask:{rec['id']}:free"))
    rows.append(tail)
    return InlineKeyboardMarkup(rows)


async def _deliver_ask(rec: dict) -> None:
    """Gửi câu hỏi của agent sang Telegram kèm bảng nút bấm."""
    if BOT_OBJ is None:
        _ask_pop(rec["id"], cancelled=True)
        return
    question = _clip(clean_output(rec["question"]), 1800)
    hint = "Chọn một phương án bên dưới hoặc nhắn câu trả lời của bạn."
    try:
        rec["msg"] = await BOT_OBJ.send_message(
            rec["chat_id"], f"❓ <b>Agent hỏi</b>\n{esc(question)}\n\n<i>{hint}</i>",
            parse_mode=HTML, reply_markup=_ask_keyboard(rec),
            link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.warning("Không gửi được câu hỏi ask_user: %s", e)
        _ask_pop(rec["id"], cancelled=True)


# ── Device login GitHub cho agent (tool github_login) ────────────────
async def _gh_login_notice(chat_id: int, text: str) -> None:
    if BOT_OBJ is None:
        return
    try:
        await BOT_OBJ.send_message(chat_id, text, parse_mode=HTML,
                                   link_preview_options=NO_PREVIEW)
    except Exception as e:
        log.debug("Không gửi được thông báo github_login: %s", e)


def _sync_config_after_login() -> int:
    """Sau khi đăng nhập GitHub: kéo token/API key còn thiếu từ repo private."""
    global ENV_ALLOWED
    if config_lib is None:
        return 0
    try:
        protected = set(os.environ) - set(ENV_FROM_FILES)
        result = config_lib.sync(quiet=True, protected=protected)
        for name, value in (result.get("values") or {}).items():
            if name in ENV_FROM_FILES and value:
                os.environ[name] = value
        _load_dotenv()
        ids = [int(x) for x in re.findall(r"\d+", os.environ.get("ALLOWED_USER_IDS") or "")]
        if ids:
            ENV_ALLOWED = ids        # áp dụng ngay, không phải khởi động lại
        return int(result.get("added") or 0)
    except Exception as e:
        log.warning("Đồng bộ config sau đăng nhập GitHub: %s", oneline(str(e), 160))
        return 0


async def _deliver_github_login(chat_id: int, rid: str, device: dict) -> None:
    state = GH_LOGIN_TASKS.get(rid) or {}
    if BOT_OBJ is None:
        state.update(status="error", error="bot chưa sẵn sàng")
        return
    try:
        await BOT_OBJ.send_message(
            chat_id,
            "🐙 <b>Kết nối GitHub</b>\n"
            f"1. Mở: {esc(state.get('url'))}\n"
            f"2. Nhập mã: <code>{esc(state.get('code'))}</code>\n"
            "3. Bấm <b>Authorize</b> — mình tự chạy tiếp ngay khi bạn xác nhận.\n"
            "<i>Không cần nhắn gì thêm. Mã có hiệu lực khoảng 15 phút.</i>",
            parse_mode=HTML, link_preview_options=NO_PREVIEW)
    except Exception as e:
        state.update(status="error", error=oneline(str(e), 160))
        return
    asyncio.create_task(_gh_login_wait(chat_id, rid, device))


async def _gh_login_wait(chat_id: int, rid: str, device: dict) -> None:
    state = GH_LOGIN_TASKS.get(rid) or {}
    interval = max(5, int(device.get("interval") or 5))
    deadline = time.time() + int(device.get("expires_in") or 900)
    while time.time() < deadline and state.get("status") == "waiting":
        await asyncio.sleep(interval)
        try:
            r = await asyncio.to_thread(_gh_device_poll, device["device_code"])
        except Exception:
            continue
        err = str(r.get("error") or "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            state.update(status="error", error=err)
            await _gh_login_notice(chat_id, f"❌ Đăng nhập GitHub thất bại: <code>{esc(err)}</code>")
            return
        token = str(r.get("access_token") or "")
        if not token:
            continue
        try:
            info = await asyncio.to_thread(save_github_token, token)
        except Exception as e:
            state.update(status="error", error=oneline(str(e), 160))
            await _gh_login_notice(chat_id, f"❌ Không lưu được token GitHub: {esc(oneline(str(e), 200))}")
            return
        added = await asyncio.to_thread(_sync_config_after_login)
        login = str(info.get("login") or "")
        state.update(status="done", ok=True, login=login)
        text = (f"✅ <b>Đã kết nối GitHub</b> · <b>{esc(login or '?')}</b>\n"
                "• Token đã lưu — lần sau không phải đăng nhập lại.")
        if added:
            text += f"\n• Đã đồng bộ thêm {added} mục cấu hình từ repo private."
        await _gh_login_notice(chat_id, text)
        return
    if state.get("status") == "waiting":
        state.update(status="timeout", error="expired")
        await _gh_login_notice(chat_id, "⌛ Mã đăng nhập đã hết hạn — gửi /github login để lấy mã mới.")


class _AskHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):        # không in log HTTP (tránh ồn)
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass                    # client đã đóng socket, không phải lỗi bot
        self.close_connection = True

    def do_POST(self):
        try:
            self._handle_post()
        except (ConnectionError, OSError):
            log.debug("ask_user: client ngắt kết nối trước khi trả lời")
            self.close_connection = True
        except Exception as e:
            log.warning("ask_user handler lỗi: %s", e)
            self.close_connection = True

    def _handle_post(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if path not in ("/ask", "/image", "/pages", "/vision", "/github-login",
                        "/github-login-status", "/vm-create", "/vm-stop", "/vm-status"):
            self._json(404, {"error": "not found"})
            return
        got = self.headers.get("x-aistv-token", "")
        if not ASK_TOKEN or not secrets.compare_digest(got, ASK_TOKEN):
            self._json(403, {"error": "forbidden"})
            return
        try:
            size = int(self.headers.get("content-length") or 0)
            if size <= 0 or size > 1_000_000:
                raise ValueError("bad size")
            data = json.loads(self.rfile.read(size) or b"{}")
            chat_id = int(data.get("chat_id") or 0)
        except Exception as e:
            self._json(400, {"error": f"bad request: {e}"})
            return

        if path in ("/github-login", "/github-login-status"):
            self._handle_github_login(path, data)
            return

        if path in ("/vm-create", "/vm-stop", "/vm-status"):
            self._handle_vm(path, data)
            return

        if path == "/vision":                # agent hỏi lại Gemini về ảnh/video vừa gửi
            try:
                question = str(data.get("question") or "").strip()
                media = LAST_MEDIA.get(chat_id) or {}
                source = str(data.get("source") or media.get("source") or "").strip()
                kind = str(data.get("kind") or media.get("kind") or "image").strip().lower()
                if kind not in ("image", "video"):
                    kind = "image"
                if not question or not source or chat_id <= 0:
                    raise ValueError("missing question/media")
                left = VISION_FOLLOWUP_LEFT.get(chat_id, 0)
                if left <= 0:
                    self._json(200, {
                        "ok": False,
                        "error": "đã hết lượt hỏi lại Gemini cho media này — hãy kết luận "
                                 "bằng báo cáo đã có",
                    })
                    return
                VISION_FOLLOWUP_LEFT[chat_id] = left - 1
            except Exception as e:
                self._json(400, {"error": f"bad request: {e}"})
                return
            ok, answer, detail = _vision_followup(source, question, kind)
            self._json(200, {"ok": ok, "answer": answer, "error": detail})
            return

        if path == "/pages":                 # agent gọi tool render_pages
            text = str(data.get("text") or "").strip()
            if not text or chat_id <= 0:
                self._json(400, {"error": "missing text/chat_id"})
                return
            if len(text) > 120_000:
                self._json(200, {"ok": False, "error": "nội dung quá dài (giới hạn 120.000 ký tự)"})
                return
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    _tool_pages_job(chat_id, text,
                                    str(data.get("title") or "").strip(),
                                    str(data.get("format") or "photo").strip().lower()),
                    BOT_LOOP)
                result = fut.result(timeout=180)
            except Exception as e:
                self._json(500, {"error": oneline(_redact_secrets(str(e)), 400)})
                return
            self._json(200, result)
            return

        if path == "/image":                 # agent gọi tool generate_image
            prompt = str(data.get("prompt") or "").strip()
            if not prompt or chat_id <= 0:
                self._json(400, {"error": "missing prompt/chat_id"})
                return
            try:
                asyncio.run_coroutine_threadsafe(
                    _tool_image_job(chat_id, prompt,
                                    str(data.get("style") or "").strip(),
                                    str(data.get("aspect") or "1:1").strip(),
                                    str(data.get("kind") or "image").strip().lower(),
                                    str(data.get("model") or "").strip()),
                    BOT_LOOP)
            except Exception as e:
                self._json(500, {"error": str(e)})
                return
            self._json(200, {"ok": True, "started": True})
            return

        try:
            question = str(data.get("question") or "").strip()
            if not question or chat_id <= 0:
                raise ValueError("missing question/chat_id")
            raw_opts = data.get("options") or []
            options = [str(x).strip()[:60] for x in raw_opts if str(x).strip()][:10]
            allow_free = bool(data.get("allow_free_text", True))
        except Exception as e:
            self._json(400, {"error": f"bad request: {e}"})
            return

        rec = {"id": secrets.token_hex(4), "chat_id": chat_id, "question": question,
               "options": options, "allow_free_text": allow_free,
               "created": time.time(), "event": threading.Event(),
               "answer": None, "cancelled": False, "msg": None}
        with ASK_LOCK:
            ASK_REQUESTS[rec["id"]] = rec
            ASK_BY_CHAT[chat_id] = rec["id"]

        try:
            fut = asyncio.run_coroutine_threadsafe(_deliver_ask(rec), BOT_LOOP)
            fut.result(timeout=20)
        except Exception as e:
            log.warning("ask_user không gửi được: %s", e)
            _ask_pop(rec["id"], cancelled=True)

        if not rec["event"].wait(ASK_TIMEOUT if ASK_TIMEOUT > 0 else None):
            _ask_pop(rec["id"], cancelled=True)
        self._json(200, {"answer": rec.get("answer"), "cancelled": bool(rec.get("cancelled"))})

    def _handle_github_login(self, path: str, data: dict) -> None:
        """Bắt đầu / kiểm tra phiên đăng nhập GitHub bằng mã cho agent."""
        chat_id = int(data.get("chat_id") or 0)
        if path == "/github-login-status":
            rid = str(data.get("id") or "")
            state = GH_LOGIN_TASKS.get(rid)
            if not state:
                self._json(404, {"ok": False, "status": "unknown", "error": "not found"})
                return
            self._json(200, {"ok": bool(state.get("ok")), "status": state.get("status"),
                             "login": state.get("login") or "",
                             "error": state.get("error") or ""})
            return
        if chat_id <= 0:
            self._json(400, {"ok": False, "error": "missing chat_id"})
            return
        token = github_token()
        if token:
            try:
                info = apply_github_config(token)
                self._json(200, {"ok": True, "already": True,
                                 "login": str(info.get("login") or "")})
                return
            except Exception:
                pass
        for rid, state in GH_LOGIN_TASKS.items():
            if state.get("chat_id") == chat_id and state.get("status") == "waiting":
                self._json(200, {"ok": True, "id": rid, "code": state.get("code"),
                                 "url": state.get("url"),
                                 "expires_in": state.get("expires_in")})
                return
        try:
            device = _gh_device_start()
        except Exception as e:
            self._json(200, {"ok": False, "error": oneline(str(e), 200)})
            return
        now = time.time()
        for old in [k for k, v in GH_LOGIN_TASKS.items()
                    if now - float(v.get("created") or 0) > 1800]:
            GH_LOGIN_TASKS.pop(old, None)
        rid = secrets.token_hex(4)
        GH_LOGIN_TASKS[rid] = {
            "chat_id": chat_id, "code": str(device.get("user_code") or ""),
            "url": str(device.get("verification_uri") or "https://github.com/login/device"),
            "expires_in": int(device.get("expires_in") or 900),
            "status": "waiting", "ok": False, "login": "", "error": "",
            "created": now}
        try:
            asyncio.run_coroutine_threadsafe(
                _deliver_github_login(chat_id, rid, device), BOT_LOOP).result(timeout=20)
        except Exception as e:
            GH_LOGIN_TASKS[rid].update(status="error", error=oneline(str(e), 160))
        state = GH_LOGIN_TASKS[rid]
        if state.get("status") == "error":
            self._json(200, {"ok": False, "error": state.get("error") or "unknown"})
            return
        self._json(200, {"ok": True, "id": rid, "code": state.get("code"),
                         "url": state.get("url"), "expires_in": state.get("expires_in")})

    def _handle_vm(self, path: str, data: dict) -> None:
        """Tool create_vm của agent: trạng thái creds / tạo hoặc dừng máy ảo Windows."""
        chat_id = int(data.get("chat_id") or 0)
        if path == "/vm-status":
            creds = load_vm_creds()
            active = vm_run_active(chat_id) if chat_id > 0 else None
            self._json(200, {
                "ok": True,
                "has_pat": bool(creds.get("pat") or github_token()),
                "has_key": bool(creds.get("tailscale_key")),
                "windows": creds.get("windows") or "windows-latest",
                "minutes": int(creds.get("minutes") or 360),
                "active_run": ({"run_id": active.get("run_id"), "repo": active.get("repo")}
                               if active else None),
            })
            return
        if vm_lib is None:
            self._json(200, {"ok": False, "error": "thiếu module aistv_vm trên máy này"})
            return
        if chat_id <= 0:
            self._json(200, {"ok": False,
                             "error": "chỉ tạo máy ảo từ chat riêng (private) với bot"})
            return
        action = str(data.get("action") or "create").strip().lower()
        if path == "/vm-stop":
            action = "stop"
        if action in ("stop", "cancel"):
            ok, text = _vm_stop_sync(chat_id)
            self._json(200, {"ok": ok, "message": re.sub(r"<[^>]+>", "", text)})
            return
        creds = load_vm_creds()
        explicit_pat = str(data.get("github_token") or "").strip()
        saved_pat = str(creds.get("pat") or "").strip()
        pat = explicit_pat or saved_pat or github_token()
        key = (str(data.get("tailscale_authkey") or "").strip()
               or str(creds.get("tailscale_key") or ""))
        win = str(data.get("windows_version") or "").strip() or str(creds.get("windows") or "")
        minutes = data.get("timeout_minutes") or creds.get("minutes") or ""
        source = "owner" if (explicit_pat or saved_pat) else "admin"
        try:
            res = vm_lib.create_vm(pat, key, BOT_TOKEN, chat_id, win, minutes,
                                   requested_by=str(data.get("requested_by") or "")[:64])
        except Exception as e:
            self._json(200, {"ok": False, "error": oneline(_redact_secrets(str(e)), 400)})
            return
        save_vm_creds(pat=explicit_pat or None, tskey=key,
                      windows=res["windows"], minutes=res["minutes"])
        _vm_run_record(chat_id, res, chat_id, res["minutes"], res["windows"], source)
        self._json(200, {
            "ok": True,
            "login": res["login"],
            "repo": res["repo"],
            "windows": res["windows"],
            "minutes": res["minutes"],
            "run_id": res.get("run_id") or 0,
            "run_url": res["run_url"],
            "workflow_url": res["workflow_url"],
            "sync": res["sync"],
            "message": (
                f"Đã kích hoạt máy ảo trên account {res['login']} ({res['repo']}, "
                f"{res['windows']}, {res['minutes']} phút). Theo dõi: "
                f"{res['run_url'] or res['workflow_url']}. "
                "Thông tin đăng nhập sẽ được gửi qua Telegram DM khi máy ảo sẵn sàng (~2-3 phút). "
                "Dừng sớm bằng nút 🛑 Dừng máy ảo trong /vm."
                + (" Fork đang lệch bản gốc nên chưa đồng bộ được code mới — cần sync thủ công."
                   if res["sync"] == "diverged" else "")
            ),
        })


class _AskServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, OSError)):
            log.debug("ask_user server: %s", exc)   # client tự ngắt, bỏ qua
            return
        log.warning("ask_user server lỗi: %r", exc)


def start_ask_server() -> None:
    """Mở HTTP server 127.0.0.1 để tool ask_user gọi vào bot."""
    global ASK_SERVER, ASK_URL, ASK_TOKEN, BOT_LOOP
    if ASK_SERVER is not None:
        return
    BOT_LOOP = asyncio.get_running_loop()
    ASK_TOKEN = secrets.token_urlsafe(24)
    ASK_SERVER = _AskServer(("127.0.0.1", 0), _AskHandler)
    port = ASK_SERVER.server_address[1]
    threading.Thread(target=ASK_SERVER.serve_forever, daemon=True).start()
    ASK_URL = f"http://127.0.0.1:{port}"          # tool JS tự nối /ask, /image
    os.environ["AISTV_ASK_URL"] = ASK_URL
    os.environ["AISTV_TOOL_TOKEN"] = ASK_TOKEN
    log.info("ask_user server: %s", ASK_URL)


# ════════════════════════════════════════════════════════════════════
# 4c. GITHUB: ĐĂNG NHẬP MỘT LẦN, LƯU BỀN VỮNG, TỰ CẬP NHẬT BOT
# ════════════════════════════════════════════════════════════════════
def _gh_http(url: str, data: Optional[dict] = None, token: str = "", timeout: int = 30) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "AISTV-bot"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def _gh_device_start() -> dict:
    return _gh_http("https://github.com/login/device/code",
                    {"client_id": GH_CLIENT_ID, "scope": GH_SCOPES})


def _gh_device_poll(device_code: str) -> dict:
    return _gh_http("https://github.com/login/oauth/access_token",
                    {"client_id": GH_CLIENT_ID, "device_code": device_code,
                     "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})


def github_token() -> str:
    """Token theo thứ tự: env/Colab Secrets → file bền vững → gh CLI."""
    global GH_TOKEN_CACHE
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        tok = get_secret(name)
        if tok:
            GH_TOKEN_CACHE = tok.strip()
            return GH_TOKEN_CACHE
    try:
        tok = GITHUB_TOKEN_FILE.read_text("utf-8").strip()
        if tok:
            GH_TOKEN_CACHE = tok
            return tok
    except Exception:
        pass
    if shutil.which("gh"):
        try:
            r = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                GH_TOKEN_CACHE = r.stdout.strip()
                return GH_TOKEN_CACHE
        except Exception:
            pass
    return ""


def github_token_source() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if get_secret(name):
            return "env / Colab Secrets"
    try:
        if GITHUB_TOKEN_FILE.read_text("utf-8").strip():
            return "file bền vững (.secrets/github_token)"
    except Exception:
        pass
    if shutil.which("gh"):
        try:
            r = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return "gh CLI"
        except Exception:
            pass
    return "chưa có"


def apply_github_config(token: str) -> dict:
    """Cấu hình git credential + gh CLI + user.name/email từ token."""
    info = {}
    try:
        info = _gh_http("https://api.github.com/user", token=token)
    except Exception as e:
        raise RuntimeError(f"Token không hợp lệ hoặc không gọi được GitHub API: {oneline(str(e), 160)}")

    login = str(info.get("login") or "").strip()
    email = str(info.get("email") or "").strip() or (f"{login}@users.noreply.github.com" if login else "")

    try:
        subprocess.run(["git", "config", "--global", "credential.helper", "store"],
                       capture_output=True, timeout=20)
        cred = Path.home() / ".git-credentials"
        lines = []
        if cred.exists():
            lines = [l for l in cred.read_text("utf-8").splitlines()
                     if l.strip() and "@github.com" not in l]
        safe = urllib.parse.quote(token, safe="")
        lines.append(f"https://x-access-token:{safe}@github.com")
        # Ghi LF thay vì CRLF: git credential-store trên Windows không đọc được
        # file .git-credentials dùng CRLF (sẽ báo không tìm thấy credential).
        cred.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        cred.chmod(0o600)
        if login:
            subprocess.run(["git", "config", "--global", "user.name", login],
                           capture_output=True, timeout=20)
            subprocess.run(["git", "config", "--global", "user.email", email],
                           capture_output=True, timeout=20)
    except Exception as e:
        log.warning("Không cấu hình được git: %s", e)

    if shutil.which("gh"):
        try:
            subprocess.run(["gh", "auth", "login", "--hostname", "github.com", "--with-token"],
                           input=token + "\n", text=True, capture_output=True, timeout=40)
            subprocess.run(["gh", "auth", "setup-git"], capture_output=True, timeout=40)
        except Exception as e:
            log.warning("Không cấu hình được gh CLI: %s", e)

    if login:
        STATE["github_user"] = login
        save_state()
    return info


def save_github_token(token: str) -> dict:
    """Lưu token (chmod 600) + bản sao trên Google Drive nếu đang mount."""
    global GH_TOKEN_CACHE, SECRETS_DIRTY
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Token rỗng.")
    info = apply_github_config(token)
    GITHUB_TOKEN_FILE.write_text(token, "utf-8")
    GITHUB_TOKEN_FILE.chmod(0o600)
    GH_TOKEN_CACHE = token
    SECRETS_DIRTY = True
    drive = Path("/content/drive/MyDrive/stv_agent/.secrets/github_token")
    if drive.parent.parent.parent.exists() and drive.parent.resolve() != GITHUB_TOKEN_FILE.parent.resolve():
        try:
            drive.parent.mkdir(parents=True, exist_ok=True)
            drive.write_text(token, "utf-8")
            drive.chmod(0o600)
        except Exception:
            pass
    return info


def clear_github_token() -> None:
    global GH_TOKEN_CACHE
    try:
        GITHUB_TOKEN_FILE.unlink()
    except Exception:
        pass
    try:
        cred = Path.home() / ".git-credentials"
        if cred.exists():
            keep = [l for l in cred.read_text("utf-8").splitlines() if "@github.com" not in l]
            cred.write_bytes(("\n".join(keep) + ("\n" if keep else "")).encode("utf-8"))
    except Exception:
        pass
    if shutil.which("gh"):
        try:
            subprocess.run(["gh", "auth", "logout", "--hostname", "github.com"],
                           capture_output=True, timeout=30)
        except Exception:
            pass
    GH_TOKEN_CACHE = ""
    STATE["github_user"] = ""
    save_state()


# ── Máy ảo Windows: thông tin đã lưu (PAT + Tailscale key) ──────────
def load_vm_creds() -> dict:
    try:
        data = json.loads(VM_CREDS_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_vm_creds(creds: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    VM_CREDS_FILE.write_text(json.dumps(creds), "utf-8")
    try:
        VM_CREDS_FILE.chmod(0o600)
    except Exception:
        pass


def save_vm_creds(pat: Optional[str] = None, tskey: Optional[str] = None,
                  windows: Optional[str] = None, minutes: Optional[int] = None) -> dict:
    global SECRETS_DIRTY
    creds = load_vm_creds()
    if pat is not None:
        creds["pat"] = (pat or "").strip()
    if tskey is not None:
        creds["tailscale_key"] = (tskey or "").strip()
    if windows:
        creds["windows"] = windows
    if minutes:
        creds["minutes"] = int(minutes)
    _write_vm_creds(creds)
    SECRETS_DIRTY = True                 # cloud_loop đẩy blob mã hoá lên Firebase
    return creds


def clear_vm_creds() -> None:
    global SECRETS_DIRTY
    try:
        VM_CREDS_FILE.unlink()
    except Exception:
        pass
    SECRETS_DIRTY = True


VM_AWAIT: dict = {}                  # chat_id -> ("pat" | "key", thời điểm bắt đầu chờ)
VM_AWAIT_SECONDS = 900
VM_WINDOWS = ("windows-latest", "windows-2022", "windows-2025")
VM_MINUTES = (60, 120, 180, 240, 300, 360)

# Khách: xác minh email .com bằng mã 6 số (lưu Firebase, gửi qua SMTP của chủ bot)
VM_VERIFY_ENABLED = os.getenv("AISTV_VM_VERIFY", "1") != "0"
VM_VERIFY_SUFFIX = (os.getenv("AISTV_VM_VERIFY_DOMAIN") or ".com").strip().lower()
VM_VERIFY_TTL = max(120, int(os.getenv("AISTV_VM_VERIFY_TTL", "600") or 600))
VM_VERIFY_TRIES = max(1, int(os.getenv("AISTV_VM_VERIFY_TRIES", "5") or 5))
VM_VERIFY_DAYS = max(1, int(os.getenv("AISTV_VM_VERIFY_DAYS", "30") or 30))
GUEST_VM = os.getenv("AISTV_GUEST_VM", "1") != "0"
GUEST_VM_MINUTES = (60, 120, 180)
GUEST_VM_MAX_MINUTES = GUEST_VM_MINUTES[-1]
GUEST_VM_DAILY = max(1, int(os.getenv("AISTV_GUEST_VM_DAILY", "3") or 3))

VM_RUNS_FILE = SECRETS_DIR / "vm_runs.json"
VM_RUNS: dict = {}                   # "u<uid>" -> lần chạy máy ảo đang giữ
VM_DAILY: dict = {}                  # "<uid>:<YYYY-MM-DD>" -> số lượt tạo trong ngày
VM_RUNS_LOADED = False
VM_VERIFY_AWAIT: dict = {}           # uid -> {"step","email","digest","exp","tries","chat_id"}
VM_VERIFY_LAST: dict = {}            # uid -> lần gửi mã gần nhất (chống spam email)
VM_VERIFY_COOLDOWN = 60
VM_VERIFIED: dict = {}               # uid -> {"email","until"}
GUEST_VM_CHOICE: dict = {}           # uid -> {"windows","minutes"}


def _vm_runs_load() -> None:
    global VM_RUNS, VM_DAILY, VM_RUNS_LOADED
    if VM_RUNS_LOADED:
        return
    VM_RUNS_LOADED = True
    try:
        data = json.loads(VM_RUNS_FILE.read_text("utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    runs = data.get("runs")
    if isinstance(runs, dict):
        VM_RUNS.update({k: v for k, v in runs.items() if isinstance(v, dict)})
    daily = data.get("daily")
    if isinstance(daily, dict):
        for key, value in daily.items():
            try:
                VM_DAILY[str(key)] = int(value)
            except (TypeError, ValueError):
                continue


def _vm_runs_save() -> None:
    try:
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        VM_RUNS_FILE.write_text(json.dumps({"runs": VM_RUNS, "daily": VM_DAILY}), "utf-8")
        try:
            VM_RUNS_FILE.chmod(0o600)
        except Exception:
            pass
    except Exception:
        pass


def vm_run_active(uid) -> Optional[dict]:
    """Lần chạy máy ảo còn hiệu lực của người dùng (None nếu không có)."""
    _vm_runs_load()
    key = f"u{int(uid)}"
    rec = VM_RUNS.get(key)
    if not isinstance(rec, dict):
        return None
    if float(rec.get("until") or 0) <= time.time():     # đã hết giờ → tự dọn
        VM_RUNS.pop(key, None)
        _vm_runs_save()
        return None
    return rec


def _vm_run_record(uid, res: dict, chat_id: int, minutes: int,
                   windows: str, source: str) -> None:
    _vm_runs_load()
    now = time.time()
    VM_RUNS[f"u{int(uid)}"] = {
        "run_id": int(res.get("run_id") or 0),
        "repo": str(res.get("repo") or ""),
        "login": str(res.get("login") or ""),
        "chat_id": int(chat_id),
        "minutes": int(minutes),
        "windows": str(windows or ""),
        "source": source,                    # admin = token bot, owner = PAT đã lưu
        "started": int(now),
        "until": int(now + int(minutes) * 60 + 180),   # cộng thời gian runner khởi động
    }
    _vm_runs_save()


def _vm_run_forget(uid) -> None:
    _vm_runs_load()
    if VM_RUNS.pop(f"u{int(uid)}", None) is not None:
        _vm_runs_save()


def _vm_daily_used(uid) -> int:
    _vm_runs_load()
    return int(VM_DAILY.get(f"{int(uid)}:{time.strftime('%Y-%m-%d')}", 0))


def _vm_daily_bump(uid) -> None:
    _vm_runs_load()
    today = time.strftime("%Y-%m-%d")
    key = f"{int(uid)}:{today}"
    VM_DAILY[key] = int(VM_DAILY.get(key, 0)) + 1
    for old in [k for k in VM_DAILY if not k.endswith(":" + today)]:
        VM_DAILY.pop(old, None)
    _vm_runs_save()


def _mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:2] if len(local) > 2 else ''}***@{domain}"


def _vm_verified_cached(uid) -> bool:
    rec = VM_VERIFIED.get(int(uid))
    return bool(rec and float(rec.get("until") or 0) > time.time())


async def vm_verified(uid) -> Optional[dict]:
    """Trạng thái xác minh email: RAM trước, sau đó đọc node vmverify trên Firebase."""
    uid = int(uid)
    now = time.time()
    rec = VM_VERIFIED.get(uid)
    if rec and float(rec.get("until") or 0) > now:
        return rec
    if CLOUD_ENABLED:
        data = await fb("GET", f"vmverify/{uid}")
        if isinstance(data, dict):
            try:
                until = float(data.get("until") or 0)
            except (TypeError, ValueError):
                until = 0.0
            if until > now:
                rec = {"email": str(data.get("email") or ""), "until": until}
                VM_VERIFIED[uid] = rec
                return rec
    return None


async def _vm_verified_save(uid, email: str) -> dict:
    until = time.time() + VM_VERIFY_DAYS * 86400
    rec = {"email": _mask_email(email), "until": until}
    VM_VERIFIED[int(uid)] = rec
    if CLOUD_ENABLED:
        await fb("PUT", f"vmverify/{int(uid)}",
                 {"email": rec["email"], "until": int(until), "at": int(time.time())})
    return rec


def _mail_ready() -> bool:
    try:
        return bool(mail and mail.ready())
    except Exception:
        return False


def _send_verify_mail(to: str, code: str, minutes: int) -> None:
    if mail is None:
        raise RuntimeError("Bot chưa có module gửi email.")
    body = (
        "Xin chào,\n\n"
        f"Mã xác minh của bạn là: {code}\n"
        f"Mã có hiệu lực trong {minutes} phút.\n\n"
        "Nhập mã này vào chat với bot AI STV để xác minh email.\n"
        "Nếu bạn không yêu cầu tạo máy ảo, hãy bỏ qua email này.\n"
    )
    mail.send(to, "AI STV · Mã xác minh tạo máy ảo Windows", body)


async def _vm_verify_start(bot, chat_id: int, uid: int) -> None:
    if not VM_VERIFY_ENABLED:
        await bot.send_message(chat_id, "⚠️ Xác minh email đang tắt — báo chủ bot.")
        return
    if not _mail_ready():
        await bot.send_message(
            chat_id,
            "⚠️ Chủ bot chưa cấu hình email (SMTP) nên chưa gửi được mã xác minh.\n"
            "Hãy liên hệ chủ bot để bật <code>/email setup</code>.",
            parse_mode=HTML)
        return
    now = time.time()
    wait_left = VM_VERIFY_COOLDOWN - (now - float(VM_VERIFY_LAST.get(int(uid)) or 0))
    if wait_left > 0:
        await bot.send_message(chat_id, f"⏳ Vui lòng chờ ~{int(wait_left) + 1} giây rồi thử lại.")
        return
    VM_VERIFY_AWAIT[int(uid)] = {"step": "email", "exp": time.time() + VM_AWAIT_SECONDS,
                                 "chat_id": int(chat_id)}
    await bot.send_message(
        chat_id,
        "📧 <b>Xác minh email</b>\n"
        f"Gửi địa chỉ email <b>{esc(VM_VERIFY_SUFFIX)}</b> của bạn vào chat này.\n"
        "Bot gửi mã 6 số tới email đó; mã dùng một lần.",
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✖️ Huỷ", callback_data="vm:gcancel")]]))


async def _vm_verify_input(msg, context, chat, user, text: str) -> bool:
    """Xử lý email/mã khi khách đang chờ xác minh; True nếu đã tiêu thụ tin nhắn."""
    uid = int(user.id)
    st = VM_VERIFY_AWAIT.get(uid)
    if not st or st.get("chat_id") != chat.id:
        return False
    if time.time() > float(st.get("exp") or 0):
        VM_VERIFY_AWAIT.pop(uid, None)
        await chat.send_message("⌛ Hết thời gian xác minh — bấm ✅ Xác minh email để thử lại.")
        return True
    if vm_lib is None:
        VM_VERIFY_AWAIT.pop(uid, None)
        await chat.send_message("⚠️ Module aistv_vm chưa có trên máy này.")
        return True
    if st.get("step") == "email":
        try:
            email = vm_lib.validate_email(text, VM_VERIFY_SUFFIX)
        except Exception as e:
            await chat.send_message("⚠️ " + oneline(str(e), 200))
            return True
        code = vm_lib.new_code()
        now = time.time()
        wait_left = VM_VERIFY_COOLDOWN - (now - float(VM_VERIFY_LAST.get(uid) or 0))
        if wait_left > 0:
            await chat.send_message(f"⏳ Vui lòng chờ ~{int(wait_left) + 1} giây rồi gửi lại email.")
            return True
        VM_VERIFY_LAST[uid] = now
        try:
            await asyncio.to_thread(_send_verify_mail, email, code, VM_VERIFY_TTL // 60)
        except Exception as e:
            VM_VERIFY_AWAIT.pop(uid, None)
            await chat.send_message("❌ Không gửi được email: " + oneline(str(e), 300))
            return True
        digest = vm_lib.code_digest(uid, code)
        exp = time.time() + VM_VERIFY_TTL
        st.update(step="code", email=email, digest=digest, exp=exp, tries=0)
        if CLOUD_ENABLED:                       # mã lưu Firebase để xác minh được ở máy khác
            await fb("PUT", f"vmverify_pending/{uid}",
                     {"h": digest, "email": _mask_email(email), "exp": int(exp),
                      "at": int(time.time())})
        await chat.send_message(
            f"📨 Đã gửi mã 6 số tới <b>{esc(_mask_email(email))}</b>.\n"
            f"Nhập mã vào chat này (hiệu lực {VM_VERIFY_TTL // 60} phút).",
            parse_mode=HTML)
        return True

    code = re.sub(r"\D", "", text or "")
    if len(code) != 6:
        await chat.send_message("⚠️ Mã gồm đúng 6 chữ số.")
        return True
    digest = str(st.get("digest") or "")
    email = str(st.get("email") or "")
    exp = float(st.get("exp") or 0)
    if CLOUD_ENABLED:
        data = await fb("GET", f"vmverify_pending/{uid}")
        if isinstance(data, dict) and data.get("h"):
            digest = str(data["h"])
            try:
                exp = float(data.get("exp") or 0)
            except (TypeError, ValueError):
                exp = 0.0
    if not digest or exp <= time.time():
        VM_VERIFY_AWAIT.pop(uid, None)
        if CLOUD_ENABLED:
            await fb("DELETE", f"vmverify_pending/{uid}")
        await chat.send_message("⌛ Mã đã hết hạn — bấm ✅ Xác minh email để nhận mã mới.")
        return True
    if not hmac.compare_digest(digest, vm_lib.code_digest(uid, code)):
        st["tries"] = int(st.get("tries") or 0) + 1
        left = VM_VERIFY_TRIES - st["tries"]
        if left <= 0:
            VM_VERIFY_AWAIT.pop(uid, None)
            if CLOUD_ENABLED:
                await fb("DELETE", f"vmverify_pending/{uid}")
            await chat.send_message("❌ Sai mã quá số lần — bấm ✅ Xác minh email để nhận mã mới.")
        else:
            await chat.send_message(f"❌ Mã không đúng. Còn {left} lần thử.")
        return True
    VM_VERIFY_AWAIT.pop(uid, None)
    if CLOUD_ENABLED:
        await fb("DELETE", f"vmverify_pending/{uid}")
    rec = await _vm_verified_save(uid, email)
    await chat.send_message(
        f"✅ <b>Đã xác minh email</b> <code>{esc(rec['email'])}</code>\n"
        f"Hiệu lực {VM_VERIFY_DAYS} ngày — giờ bạn có thể tạo máy ảo.",
        parse_mode=HTML, reply_markup=guest_vm_keyboard(uid))
    return True


def vm_defaults() -> tuple:
    """(runner, số phút) đang chọn — mặc định windows-latest / 360."""
    default_min = getattr(vm_lib, "DEFAULT_MINUTES", 360) if vm_lib else 360
    creds = load_vm_creds()
    return (str(creds.get("windows") or "windows-latest"),
            int(creds.get("minutes") or default_min))


def vm_keyboard() -> InlineKeyboardMarkup:
    win, minutes = vm_defaults()
    rows = [[InlineKeyboardButton(("✅ " if w == win else "") + w,
                                 callback_data=f"vm:win:{w}") for w in VM_WINDOWS],
            [InlineKeyboardButton(("✅ " if m == minutes else "") + f"{m} phút",
                                  callback_data=f"vm:min:{m}") for m in VM_MINUTES[:3]],
            [InlineKeyboardButton(("✅ " if m == minutes else "") + f"{m} phút",
                                  callback_data=f"vm:min:{m}") for m in VM_MINUTES[3:]],
            [InlineKeyboardButton("🔑 Nhập PAT GitHub", callback_data="vm:pat"),
             InlineKeyboardButton("🔑 Nhập Tailscale key", callback_data="vm:key")],
            [InlineKeyboardButton("🚀 Tạo máy ảo", callback_data="vm:create"),
             InlineKeyboardButton("🧹 Xoá đã lưu", callback_data="vm:forget")],
            [InlineKeyboardButton("🛑 Dừng máy ảo", callback_data="vm:stop")]]
    return InlineKeyboardMarkup(rows)


def _guest_vm_choice(uid) -> tuple:
    rec = GUEST_VM_CHOICE.get(int(uid)) or {}
    try:
        minutes = int(rec.get("minutes") or GUEST_VM_MAX_MINUTES)
    except (TypeError, ValueError):
        minutes = GUEST_VM_MAX_MINUTES
    return (str(rec.get("windows") or "windows-latest"),
            max(GUEST_VM_MINUTES[0], min(GUEST_VM_MAX_MINUTES, minutes)))


def guest_vm_keyboard(uid) -> InlineKeyboardMarkup:
    uid = int(uid)
    win, minutes = _guest_vm_choice(uid)
    rows = [[InlineKeyboardButton(("✅ " if w == win else "") + w,
                                  callback_data=f"vm:gwin:{w}") for w in VM_WINDOWS],
            [InlineKeyboardButton(("✅ " if m == minutes else "") + f"{m} phút",
                                  callback_data=f"vm:gmin:{m}") for m in GUEST_VM_MINUTES]]
    if vm_run_active(uid):
        rows.append([InlineKeyboardButton("🛑 Dừng máy ảo", callback_data="vm:gstop")])
    else:
        rows.append([InlineKeyboardButton("🚀 Tạo máy ảo", callback_data="vm:gcreate")])
    if not _vm_verified_cached(uid):
        rows.append([InlineKeyboardButton("✅ Xác minh email", callback_data="vm:gverify")])
    return InlineKeyboardMarkup(rows)


async def guest_vm_panel(uid) -> tuple:
    """(text, keyboard) bảng máy ảo dành cho khách."""
    uid = int(uid)
    lines = ["🖥 <b>Máy ảo Windows · dành cho khách</b>"]
    rec = await vm_verified(uid)
    if rec:
        days = max(0, int((float(rec["until"]) - time.time()) / 86400))
        lines.append(f"• Email: ✅ <code>{esc(rec['email'])}</code> · còn {days} ngày")
    else:
        lines.append(f"• Email: <b>chưa xác minh</b> — bấm ✅ Xác minh email (đuôi {esc(VM_VERIFY_SUFFIX)})")
    active = vm_run_active(uid)
    if active:
        left = max(1, int((float(active["until"]) - time.time()) / 60))
        lines.append(f"• Máy đang chạy: <b>còn ~{left} phút</b> · "
                     f"{esc(active.get('windows') or '')} · {active.get('minutes') or 0} phút")
    else:
        lines.append(f"• Hôm nay: {_vm_daily_used(uid)}/{GUEST_VM_DAILY} lượt · "
                     f"mỗi máy tối đa {GUEST_VM_MAX_MINUTES} phút")
    win, minutes = _guest_vm_choice(uid)
    lines += ["", f"Runner <b>{esc(win)}</b> · <b>{minutes} phút</b>",
              "",
              "🔐 IP, user, mật khẩu và key Tailscale chỉ gửi vào <b>chat riêng này</b> "
              "khi máy sẵn sàng (~2–3 phút)."]
    return "\n".join(lines), guest_vm_keyboard(uid)


async def _guest_vm_entry(msg, chat, user) -> None:
    if not GUEST_VM:
        await chat.send_message("⛔ Tính năng máy ảo đang tắt cho khách.")
        return
    if chat.type != "private":
        await msg.reply_text("🖥 Máy ảo chỉ tạo trong chat riêng — nhắn riêng bot rồi gõ /vm nhé.")
        return
    text, kb = await guest_vm_panel(user.id)
    await msg.reply_text(text, parse_mode=HTML, reply_markup=kb)


VM_INTENT_RE = re.compile(
    r"(tạo|tao|làm|lam|mở|mo|dựng|dung|lấy|lay)\s+(một\s+|mot\s+)?máy\s+ảo"
    r"|(máy\s+ảo|may\s+ao)\s+(windows|win)\b"
    r"|(dừng|dung|huỷ|huy|tắt|tat|stop)\s+(máy\s+ảo|may\s+ao)\b"
    r"|\b(create|start|spin\s+up|launch)\s+(a\s+|an\s+)?(windows\s+)?vm\b"
    r"|\bstop\s+(the\s+|my\s+)?(windows\s+)?vm\b",
    re.IGNORECASE)


def _guest_vm_wants(text: str) -> bool:
    """Khách có đang yêu cầu tạo máy ảo (để mở bảng nút thay vì hỏi LLM)."""
    return bool(VM_INTENT_RE.search(text or ""))


def _vm_stop_sync(uid) -> tuple:
    """Huỷ lần chạy máy ảo của uid; trả (ok, text HTML)."""
    if vm_lib is None:
        return False, "⚠️ Module aistv_vm chưa có trên máy này."
    rec = vm_run_active(uid)
    if not rec:
        return False, "ℹ️ Không có máy ảo nào đang chạy."
    pat = github_token() if rec.get("source") == "admin" else vm_pat()
    if not pat:
        return False, "⚠️ Thiếu GitHub token để dừng máy ảo."
    try:
        vm_lib.cancel_run(rec.get("login"), pat, rec.get("run_id"))
    except Exception as e:
        text = oneline(_redact_secrets(str(e)), 300)
        if "đã kết thúc" in text or "Không tìm thấy" in text:
            _vm_run_forget(uid)
        return False, "❌ " + esc(text)
    _vm_run_forget(uid)
    return True, (
        "🛑 <b>Đã dừng máy ảo</b>\n"
        f"• Repo: <code>{esc(rec.get('repo') or '')}</code>\n"
        "• Runner bị huỷ trong vài giây — máy ảo biến mất, không dùng tiếp được.")


async def _on_guest_vm_button(q, data: str) -> None:
    user, chat = q.from_user, (q.message.chat if q.message else None)
    if not (user and chat and chat.type == "private" and chat.id == user.id):
        await q.answer("Chỉ dùng trong chat riêng với bot.", show_alert=True)
        return
    uid = int(user.id)
    if _guest_banned(uid):
        await q.answer("Bạn đang bị chặn.", show_alert=True)
        return
    parts = data.split(":")
    act = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    bot = q.get_bot()

    async def _refresh() -> None:
        text, kb = await guest_vm_panel(uid)
        try:
            await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
        except Exception:
            pass

    if act == "gwin":
        try:
            win = vm_lib.normalize_windows(arg) if vm_lib else arg
        except Exception as e:
            await q.answer(oneline(str(e), 180), show_alert=True)
            return
        GUEST_VM_CHOICE.setdefault(uid, {})["windows"] = win
        await q.answer(f"Runner: {win}")
        await _refresh()
        return
    if act == "gmin":
        try:
            minutes = int(arg)
        except (TypeError, ValueError):
            await q.answer("Số phút không hợp lệ.", show_alert=True)
            return
        minutes = max(GUEST_VM_MINUTES[0], min(GUEST_VM_MAX_MINUTES, minutes))
        GUEST_VM_CHOICE.setdefault(uid, {})["minutes"] = minutes
        await q.answer(f"{minutes} phút")
        await _refresh()
        return
    if act == "gverify":
        VM_VERIFY_AWAIT.pop(uid, None)
        await q.answer()
        await _vm_verify_start(bot, chat.id, uid)
        return
    if act == "gcancel":
        VM_VERIFY_AWAIT.pop(uid, None)
        await q.answer("Đã huỷ")
        try:
            await q.edit_message_text("✖️ Đã huỷ xác minh.")
        except Exception:
            pass
        return
    if act == "gcreate":
        await q.answer("Đang kiểm tra…")
        await _guest_vm_create(bot, chat.id, user)
        return
    if act == "gstop":
        await q.answer("Đang dừng…")
        _, text = await asyncio.to_thread(_vm_stop_sync, uid)
        await bot.send_message(chat.id, text, parse_mode=HTML)
        await _refresh()
        return
    await q.answer()


async def _guest_vm_create(bot, chat_id: int, user) -> None:
    uid = int(user.id)
    if not GUEST_VM or vm_lib is None:
        await bot.send_message(chat_id, "⛔ Tính năng máy ảo đang tắt.")
        return
    if VM_VERIFY_ENABLED and not await vm_verified(uid):
        await bot.send_message(chat_id, "🔐 Cần xác minh email trước khi tạo máy ảo.",
                               reply_markup=guest_vm_keyboard(uid))
        return
    if vm_run_active(uid):
        await bot.send_message(chat_id, "⚠️ Bạn đang có một máy ảo chạy. "
                                        "Bấm 🛑 Dừng máy ảo trước khi tạo máy mới.")
        return
    if _vm_daily_used(uid) >= GUEST_VM_DAILY:
        await bot.send_message(chat_id, f"⚠️ Bạn đã dùng hết {GUEST_VM_DAILY} lượt tạo máy hôm nay. "
                                        "Thử lại ngày mai.")
        return
    pat = vm_pat()
    key = str(load_vm_creds().get("tailscale_key") or "").strip()
    if not pat or not key:
        await bot.send_message(chat_id, "⚠️ Chủ bot chưa cấu hình GitHub token / Tailscale key "
                                        "cho dịch vụ máy ảo.")
        return
    win, minutes = _guest_vm_choice(uid)
    name = " ".join(x for x in [user.full_name or "", f"@{user.username}" if user.username else ""] if x)
    await _vm_create_flow(bot, chat_id, "", "", win, minutes,
                          as_guest=True, uid=uid, requested_by=name)


def vm_pat() -> str:
    """PAT cho máy ảo: ưu tiên PAT đã lưu, không có thì dùng token GitHub của bot."""
    pat = str(load_vm_creds().get("pat") or "").strip()
    return pat or github_token()


def vm_status_text(uid: int = 0) -> str:
    if vm_lib is None:
        return "⚠️ Module aistv_vm chưa có trên máy này."
    creds = load_vm_creds()
    saved_pat = str(creds.get("pat") or "")
    pat = saved_pat or github_token()
    key = str(creds.get("tailscale_key") or "")
    if pat:
        masked = vm_lib.mask_value(pat) if vm_lib else "***"
        pat_line = f"<code>{esc(masked)}</code>" + ("" if saved_pat else " <i>(token bot)</i>")
    else:
        pat_line = "<b>chưa lưu</b>"
    key_line = (f"<code>{esc(vm_lib.mask_value(key))}</code>" if key
                else "<b>chưa lưu</b>")
    win, minutes = vm_defaults()
    lines = ["🖥 <b>Máy ảo Windows (Integration Test)</b>",
             f"• PAT GitHub: {pat_line}",
             f"• Tailscale key: {key_line}",
             f"• Runner: {esc(win)} · {minutes} phút"]
    active = vm_run_active(uid) if uid else None
    if active:
        left = max(1, int((float(active["until"]) - time.time()) / 60))
        lines.append(f"• Đang chạy: <b>còn ~{left} phút</b> · "
                     f"{esc(active.get('repo') or '')} — bấm 🛑 để dừng")
    elif pat and key:
        lines.append("• Sẵn sàng — bấm 🚀 Tạo máy ảo")
    elif pat:
        lines.append("• Còn thiếu Tailscale key — bấm 🔑 Nhập Tailscale key")
    elif key:
        lines.append("• Còn thiếu PAT — bấm 🔑 Nhập PAT (hoặc /github login)")
    else:
        lines.append("• Cần nhập PAT và Tailscale key bằng nút bên dưới")
    lines += ["", "Thông tin đăng nhập (IP, user, mật khẩu) gửi qua Telegram DM.",
              (f"Khách: /vm · xác minh email {VM_VERIFY_SUFFIX} · "
               f"tối đa {GUEST_VM_DAILY} lượt/ngày, {GUEST_VM_MAX_MINUTES} phút/lượt."
               if GUEST_VM else "Khách: tính năng máy ảo đang tắt."),
              ("PAT + key được mã hoá, đồng bộ Firebase." if CLOUD_ENABLED
               else "⚠️ Cloud đang tắt — chỉ lưu máy này. Gửi /cloud url &lt;URL&gt; để đồng bộ.")]
    return "\n".join(lines)


def _vm_creds_from_cloud(data: dict) -> dict:
    """Tách PAT/key/runner/phút từ blob secrets trên Firebase."""
    out = {}
    for name, value in (data or {}).items():
        if not str(name).startswith("AISTV_VM_"):
            continue
        value = str(value or "").strip()
        if not value:
            continue
        field = str(name)[len("AISTV_VM_"):].lower()
        if field == "minutes":
            try:
                value = int(value)
            except ValueError:
                continue
        out["tailscale_key" if field == "tskey" else field] = value
    return out


# ── Quét repo của tài khoản đang dùng token & chọn repo đích ──
GH_REPOS_CACHE: dict = {"token": "", "items": [], "at": 0.0}
GH_REPO_PICK: dict = {}            # chat_id -> [owner/name] của trang đang hiển thị


def _gh_api(path: str, token: str, method: str = "GET", payload: Optional[dict] = None,
            timeout: int = 30) -> dict:
    url = path if path.startswith("http") else "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AISTV-bot"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = str(json.loads(e.read().decode("utf-8", "replace")).get("message") or "")
        except Exception:
            pass
        raise RuntimeError(f"GitHub {e.code}: {detail or e.reason}")
    except Exception as e:
        raise RuntimeError(f"Không gọi được GitHub API: {oneline(str(e), 160)}")
    return json.loads(raw) if raw.strip() else {}


def gh_all_repos(token: str, refresh: bool = False) -> list:
    """Toàn bộ repo token nhìn thấy (chủ, cộng tác, tổ chức), mới đẩy lên trước."""
    if (not refresh and GH_REPOS_CACHE["token"] == token
            and time.time() - GH_REPOS_CACHE["at"] < 180):
        return GH_REPOS_CACHE["items"]
    items: list = []
    for page in (1, 2):
        batch = _gh_api("/user/repos?per_page=100&page=%d&sort=updated"
                        "&affiliation=owner,collaborator,organization_member" % page,
                        token, timeout=40)
        if not isinstance(batch, list):
            break
        items += batch
        if len(batch) < 100:
            break
    repos = []
    for r in items:
        slug = str(r.get("full_name") or "").strip()
        if not slug:
            continue
        repos.append({"slug": slug, "private": bool(r.get("private")),
                      "pushed": str(r.get("pushed_at") or ""),
                      "fork": bool(r.get("fork")),
                      "can_push": bool((r.get("permissions") or {}).get("push"))})
    repos.sort(key=lambda r: (r["can_push"], r["pushed"]), reverse=True)
    GH_REPOS_CACHE.update({"token": token, "items": repos, "at": time.time()})
    return repos


def gh_repo_meta(slug: str, token: str) -> Optional[dict]:
    try:
        d = _gh_api(f"/repos/{_norm_repo(slug)}", token, timeout=25)
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("full_name") else None


def gh_repo_has_bot(slug: str, token: str) -> bool:
    try:
        d = _gh_api(f"/repos/{_norm_repo(slug)}/contents/aistv_bot.py", token, timeout=25)
    except Exception:
        return False
    return isinstance(d, dict) and d.get("type") == "file"


def current_repo_slug() -> str:
    """Repo đích: env → file .secrets/github_repo → state → origin của bản clone."""
    for name in ("AISTV_GITHUB_REPO", "AISTV_REPO"):
        val = get_secret(name)
        if val:
            return _norm_repo(val)
    try:
        val = GITHUB_REPO_FILE.read_text("utf-8").strip()
        if val:
            return _norm_repo(val)
    except Exception:
        pass
    val = _norm_repo(str(STATE.get("github_repo") or ""))
    if val:
        return val
    return repo_remote_slug()


def repo_remote_slug() -> str:
    rd = repo_dir()
    if not rd:
        return ""
    rc, out = _git(["remote", "get-url", "origin"], rd, timeout=15)
    return _norm_repo(out.splitlines()[0]) if rc == 0 and out else ""


def set_repo_slug(slug: str) -> str:
    slug = _norm_repo(slug)
    parts = slug.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[\w.-]+", p) for p in parts):
        raise RuntimeError("Repo phải dạng owner/name (ví dụ Phucvncom55/AISTV).")
    STATE["github_repo"] = slug
    save_state()
    try:
        GITHUB_REPO_FILE.write_text(slug + "\n", "utf-8")
        GITHUB_REPO_FILE.chmod(0o600)
    except Exception:
        pass
    return slug


def gh_repo_picker(chat_id: int, token: str, page: int = 0, refresh: bool = False) -> tuple:
    repos = gh_all_repos(token, refresh)
    if not repos:
        raise RuntimeError("Tài khoản này chưa có repo nào — tạo mới bằng "
                           "/github repo create <ten> [private].")
    per = 6
    pages = max(1, (len(repos) + per - 1) // per)
    page = max(0, min(page, pages - 1))
    chunk = repos[page * per:(page + 1) * per]
    GH_REPO_PICK[chat_id] = [r["slug"] for r in chunk]
    cur = current_repo_slug()
    lines = [f"🗂 <b>Repo của tài khoản</b> · {len(repos)} repo",
             f"Trang {page + 1}/{pages}"]
    if cur:
        lines.append(f"Đang dùng: <code>{esc(cur)}</code>")
    lines.append("")
    rows = []
    for i, r in enumerate(chunk):
        mark = "✅ " if r["slug"] == cur else ""
        lock = "🔒 " if r["private"] else "🌐 "
        lines.append(f"{mark}{lock}<code>{esc(r['slug'])}</code>"
                     + ("" if r["can_push"] else " · chỉ đọc"))
        rows.append([InlineKeyboardButton(f"{mark}{lock}{r['slug']}"[:60],
                                          callback_data=f"ghr:s:{i}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Trước", callback_data=f"ghr:p:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Sau ▶️", callback_data=f"ghr:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔄 Quét lại", callback_data="ghr:r"),
                 InlineKeyboardButton("➕ Tạo repo", callback_data="ghr:new")])
    lines += ["", "Bấm một repo để đặt làm repo đích."]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def gh_repo_detail(chat_id: int, idx: int) -> tuple:
    slugs = GH_REPO_PICK.get(chat_id) or []
    if not (0 <= idx < len(slugs)):
        raise RuntimeError("Danh sách đã cũ — gửi /github repos để quét lại.")
    slug = slugs[idx]
    token = github_token()
    meta = gh_repo_meta(slug, token)
    if not meta:
        raise RuntimeError(f"Không truy cập được {slug} bằng token hiện tại.")
    has_bot = gh_repo_has_bot(slug, token)
    set_repo_slug(slug)
    origin = repo_remote_slug()
    perms = meta.get("permissions") or {}
    lines = [f"✅ <b>Đã chọn repo đích</b> <code>{esc(slug)}</code>",
             f"• Quyền: {'đẩy code' if perms.get('push') else 'chỉ đọc'}",
             f"• Code bot: {'có' if has_bot else 'chưa có'}",
             f"• Origin máy này: <code>{esc(origin or 'chưa có')}</code>"]
    rows = []
    if has_bot and repo_dir() and origin != slug:
        rows.append([InlineKeyboardButton("🔀 Đổi origin + pull repo này",
                                          callback_data=f"ghr:o:{idx}")])
    if perms.get("push") and repo_dir():
        rows.append([InlineKeyboardButton(
            "⬆️ Đẩy code lên repo này" if not has_bot else "⬆️ Push code hiện tại",
            callback_data=f"ghr:up:{idx}")])
    rows.append([InlineKeyboardButton("🗂 Danh sách repo", callback_data="ghr:r")])
    lines += ["", "Repo đích đã lưu — /update sẽ dùng repo này."]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _gh_set_origin(rd: Path, slug: str) -> tuple:
    url = f"https://github.com/{_norm_repo(slug)}.git"
    rc, out = _git(["remote", "set-url", "origin", url], rd, timeout=20)
    if rc != 0:
        rc, out = _git(["remote", "add", "origin", url], rd, timeout=20)
    return rc, out


def gh_switch_repo(slug: str) -> str:
    """Đổi origin sang repo đã chọn rồi fetch/pull fast-forward."""
    rd = repo_dir()
    if not rd:
        raise RuntimeError("Không tìm thấy repo (.git) trên máy để đổi origin.")
    rc, out = _gh_set_origin(rd, slug)
    if rc != 0:
        raise RuntimeError(f"Không đổi được origin: {oneline(out, 300)}")
    rc, out = _git(["fetch", "origin", "--prune"], rd, timeout=300)
    if rc != 0:
        raise RuntimeError(f"Fetch lỗi: {oneline(out, 300)}")
    rc, out = _git(["pull", "--ff-only"], rd, timeout=300)
    if rc != 0:
        raise RuntimeError("Đã đổi origin nhưng chưa pull được (lịch sử khác nhau hoặc có "
                           f"thay đổi chưa commit): {oneline(out, 300)}")
    return f"origin → {slug}\n{oneline(out, 300)}"


def gh_push_code(slug: str) -> str:
    """Đặt origin về repo đã chọn rồi đẩy code hiện tại lên."""
    rd = repo_dir()
    if not rd:
        raise RuntimeError("Không tìm thấy repo (.git) trên máy để đẩy code.")
    rc, out = _gh_set_origin(rd, slug)
    if rc != 0:
        raise RuntimeError(f"Không đổi được origin: {oneline(out, 300)}")
    if _git(["status", "--porcelain"], rd, timeout=60)[1]:
        _git(["add", "-A"], rd, timeout=180)
        _git(["commit", "-m", f"AI STV — cập nhật {now():%d/%m/%Y %H:%M}"], rd, timeout=180)
    rc, out = _git(["push", "-u", "origin", "HEAD"], rd, timeout=300)
    if rc != 0:
        raise RuntimeError("Push thất bại (repo đã có lịch sử khác?). Chọn repo trống/khác "
                           f"hoặc xử lý thủ công: {oneline(out, 400)}")
    return f"origin → {slug}\n{oneline(out, 300)}"


def gh_create_repo(name: str, token: str, private: bool = False) -> str:
    name = re.sub(r"[^\w.-]+", "-", (name or "").strip()).strip("-._")
    if not name:
        raise RuntimeError("Tên repo không hợp lệ.")
    d = _gh_api("/user/repos", token, "POST",
                {"name": name, "private": bool(private), "auto_init": False,
                 "description": "AI STV — Telegram × OpenCode"}, timeout=40)
    slug = str((d or {}).get("full_name") or "").strip()
    if not slug:
        raise RuntimeError("GitHub không trả về tên repo vừa tạo.")
    GH_REPOS_CACHE.update({"token": "", "items": [], "at": 0.0})
    return slug


def repo_access(slug: str, token: str) -> bool:
    return bool(slug) and gh_repo_meta(slug, token) is not None


def repo_can_push(slug: str, token: str) -> bool:
    meta = gh_repo_meta(slug, token)
    return bool(meta and (meta.get("permissions") or {}).get("push"))


def repo_dir() -> Optional[Path]:
    here = Path(__file__).resolve().parent
    for cand in (here, HOME / "AISTV", Path.cwd()):
        if (cand / ".git").exists():
            return cand
    return None


def _git(args: list, cwd: Path, timeout: int = 180) -> tuple:
    try:
        r = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def restart_bot() -> bool:
    """Thay tiến trình hiện tại bằng bản mới. Không làm trong notebook Colab."""
    if "ipykernel" in sys.modules:
        return False
    try:
        env = os.environ.copy()
        # Bỏ các biến đã nạp từ .env để tiến trình mới đọc lại giá trị mới nhất.
        for name in ENV_FROM_FILES:
            env.pop(name, None)
        env["STV_SKIP_SETUP"] = "1"
        argv = [sys.executable, str(Path(__file__).resolve())] + sys.argv[1:]
        if IS_WINDOWS:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            with open(LOG_FILE, "ab") as logf:
                subprocess.Popen(argv, env=env, close_fds=True, creationflags=flags,
                                 cwd=str(Path(__file__).resolve().parent),
                                 stdin=subprocess.DEVNULL, stdout=logf,
                                 stderr=subprocess.STDOUT)
            os._exit(0)
        os.execve(sys.executable, argv, env)
        return True
    except Exception as e:
        log.error("Không khởi động lại được: %s", e)
        return False


# ════════════════════════════════════════════════════════════════════
# 5. DỰNG PROMPT + CHẠY OPENCODE (ASYNC, KHÔNG CHẶN BOT)
# ════════════════════════════════════════════════════════════════════
QUOTE_LIMIT = 3000              # ký tự tối đa của tin nhắn được trả lời đưa vào prompt

_MEDIA_LABEL = (("photo", "[ảnh]"), ("video", "[video]"), ("voice", "[tin nhắn thoại]"),
                ("audio", "[âm thanh]"), ("video_note", "[video tròn]"),
                ("sticker", "[nhãn dán]"), ("animation", "[GIF]"))


def _msg_brief(m) -> str:
    """Nội dung ngắn gọn của một tin nhắn Telegram (chữ, chú thích, loại tệp)."""
    if not m:
        return ""
    txt = (getattr(m, "text", "") or getattr(m, "caption", "") or "").strip()
    bits = [label for attr, label in _MEDIA_LABEL if getattr(m, attr, None)]
    doc = getattr(m, "document", None)
    if doc is not None:
        bits.append("[tệp " + (getattr(doc, "file_name", "") or "không tên") + "]")
    if getattr(m, "location", None):
        bits.append("[vị trí]")
    if getattr(m, "poll", None):
        bits.append("[bình chọn]")
    head = " ".join(bits)
    return f"{head} {txt}".strip() if head and txt else (txt or head)


def reply_context(msg) -> tuple:
    """Phân tích tin nhắn đang được trả lời/trích dẫn (Reply Message / Quoting).

    Trả về (khối ngữ cảnh cho prompt, nhãn ngắn để lưu vào lịch sử).
    """
    if msg is None:
        return "", ""
    ref = getattr(msg, "reply_to_message", None)
    sel = getattr(msg, "quote", None)
    sel_txt = (getattr(sel, "text", "") or "").strip()
    if ref is None and not sel_txt:
        return "", ""
    full = _msg_brief(ref)
    if not full and not sel_txt:
        return "", ""
    if len(full) > QUOTE_LIMIT:
        full = full[:QUOTE_LIMIT] + " …[cắt bớt]"
    sel_txt = sel_txt[:QUOTE_LIMIT]
    who = ""
    fu = getattr(ref, "from_user", None) if ref is not None else None
    if fu is not None:
        who = "AI STV" if getattr(fu, "is_bot", False) else (getattr(fu, "full_name", "") or str(getattr(fu, "id", "")))
    lines = [
        "## TIN NHẮN ĐANG ĐƯỢC TRẢ LỜI / TRÍCH DẪN (Reply Message)",
        "Người dùng vừa trả lời trực tiếp tin nhắn dưới đây. Các cụm như “cái này”, “đoạn trên”, "
        "“phần này”, “chỗ đó”, “sửa lại đi”, “ý này”… là chỉ tin nhắn/phần được trích dẫn — hãy "
        "hiểu yêu cầu mới gắn với nội dung đó, không đoán sang việc khác.",
    ]
    if who:
        lines.append(f"- Người gửi tin được trả lời: {who}")
    full = full.replace("```", "ʼʼʼ")
    if full:
        lines.append("- Toàn bộ tin được trả lời:\n```text\n" + full + "\n```")
    if sel_txt:
        clean_sel = sel_txt.replace("```", "ʼʼʼ")
        if clean_sel != full:
            lines.append("- Phần người dùng bôi đen để trích dẫn (ƯU TIÊN hiểu theo phần này):\n"
                         "```text\n" + clean_sel + "\n```")
    label_src = sel_txt or full
    label = "↪︎ trả lời “" + oneline(label_src, 160) + "”:"
    return "\n".join(lines), label


MATH_STYLE_MD = """## QUY TẮC TRÌNH BÀY BÀI GIẢI TOÁN / LÝ / HOÁ / SINH
Áp dụng cho mọi bài giải môn tự nhiên, kể cả khi người dùng không nhắc tới quy tắc này:
1. **Tách câu rõ ràng:** mỗi câu một tiêu đề riêng, có dòng trống — `**Câu a — …**`, `**Câu b — …**`.
2. **Mỗi ý một dòng:** không viết dồn thành đoạn văn dài; mỗi lập luận bắt đầu bằng `*` hoặc `1.` và xuống dòng.
3. **Ký hiệu chuẩn, viết bằng Unicode** (Telegram không render LaTeX): △ (tam giác), ∥, ⊥, ≡, ≅, ⇒, ⇔,
   ∠, °, ≠, ≤, ≥, ≈, √, ½, α β γ Δ π. Tách riêng đoạn thẳng, góc, độ dài — ví dụ `AB = a`, `∠A = 90°`
   thay vì viết dính thành một cụm.
4. **Mỗi ý chứng minh đủ 3 phần, mỗi phần một dòng:**
   - **Xét / Ta có:** nêu giả thiết hoặc tính chất đang áp dụng.
   - **Mà / Suy ra:** lập luận logic trung gian.
   - **Kết luận:** khẳng định điều cần chứng minh.
5. **Bài dài → ảnh từng trang:** nếu lời giải dài hơn ~25 dòng, có nhiều phân số lồng nhau,
   hệ phương trình, ma trận hoặc quá nhiều ký hiệu khó đọc trên khung chat, hãy gọi tool
   `render_pages` với TOÀN BỘ lời giải (markdown, tiếng Việt) để bot gửi ảnh A4 từng trang
   có ghi "Trang 1/N". Sau đó chỉ nhắn 1–2 dòng xác nhận, KHÔNG dán lại lời giải vào chat.
Ví dụ mẫu:
**Câu a — Tứ giác ADFE là hình gì? Vì sao?**
* **Xét** tứ giác ADFE, ta có:
  - AE ∥ DF (AE ⊂ AB, DF ⊂ CD, mà AB ∥ CD).
  - AE = DF = ½AB = a (E, F là trung điểm của AB, CD).
* **Suy ra:** ADFE là hình bình hành (một cặp cạnh đối song song và bằng nhau).
* **Mặt khác:** ∠A = 90° (góc hình chữ nhật) và AE = AD = a.
* **Kết luận:** ADFE là **hình vuông**."""


def build_prompt(chat_id: int, user_text: str, skill: Optional[tuple] = None,
                 quote: str = "") -> str:
    user_text = user_text[:20000]
    head = ["## HỒ SƠ AGENT\n" + read_text(WORKSPACE / "SOUL.md").strip()
            + "\n\n" + read_text(WORKSPACE / "AGENTS.md").strip()]
    head.append(MATH_STYLE_MD)
    mem = "\n".join(memory_items())
    if mem:
        head.append("## TRÍ NHỚ DÀI HẠN (MEMORY.md)\n" + mem[-4000:])
    idx = build_skills_index(exclude=skill[0] if skill else None)
    if idx:
        head.append(idx)
    if skill:
        body = skill[1]
        if len(body) > SKILL_BODY_LIMIT:
            body = body[:SKILL_BODY_LIMIT].rstrip() + (
                "\n\n[… nội dung đã cắt bớt. Đọc file đầy đủ theo đường dẫn "
                "trong phần THÔNG TIN SKILL ở trên.]"
            )
        head.append(f"## SKILL ĐANG KÍCH HOẠT: {skill[0]}\n" + body)
    head.append(f"## BỐI CẢNH\n- Bây giờ: {now():%d/%m/%Y %H:%M} ({TIMEZONE})\n"
                f"- Thư mục làm việc (workspace): {WORKSPACE}")
    _rd = repo_dir()
    if _rd:
        head.append(
            f"## REPO CHÍNH (code bot)\n"
            f"- Đường dẫn: {_rd}\n"
            f"- Bản đồ code: {_rd / 'docs' / 'CODEMAP.md'} (đọc trước khi sửa; "
            "grep symbol rồi chỉ đọc 60–150 dòng quanh nó)\n"
            f"- Kiểm chứng: cd \"{_rd}\" && python scripts/verify.py (chỉ báo xong khi PASS)\n"
            "- Sửa code bot ở đây; file cho người dùng tạo trong workspace, không lẫn hai nơi.")
    if mail:
        try:
            ecfg = mail.load()
            if ecfg.get("address") and ecfg.get("password"):
                cli = Path(__file__).resolve().parent / "aistv_email.py"
                head.append(
                    f"## EMAIL (đã kết nối)\n- Hộp thư: {ecfg['address']}\n"
                    f"- CLI: python3 {cli} status|test|inbox -n 10 [--unread]|read <uid>\n"
                    f"- Gửi: python3 {cli} send --to a@b.c --subject \"…\" --body \"…\"\n"
                    "- Không bao giờ in mật khẩu hay nội dung file .secrets/email.json.")
        except Exception:
            pass
    head_s = "\n\n".join(head)
    tail = ""
    if quote:
        tail += quote.strip() + "\n\n"
    tail += f"## YÊU CẦU MỚI\n[Người dùng]: {user_text}\n\nHãy trả lời yêu cầu mới ở trên."

    budget = MAX_PROMPT_BYTES - len(head_s.encode()) - len(tail.encode()) - 200
    lines, used = [], 0
    for m in reversed(load_history(chat_id)[-MAX_HISTORY * 2:]):
        c = m["content"]
        if _is_error_history(c):
            continue                      # bỏ JSON lỗi cũ từng bị lưu nhầm
        c = c if len(c) <= 2500 else c[:2500] + " …[cắt bớt]"
        line = f"[{'Người dùng' if m['role'] == 'user' else 'AI STV'}]: {c}"
        b = len(line.encode()) + 1
        if used + b > budget:
            break
        lines.append(line)
        used += b
    lines.reverse()
    conv = ("## LỊCH SỬ HỘI THOẠI GẦN ĐÂY\n" + "\n".join(lines)) if lines else ""
    return "\n\n".join(x for x in (head_s, conv, tail) if x)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


_HEADER = re.compile(r"\A(?:>\s*\w[\w-]*\s*·[^\n]*\n+)+")      # dòng "> build · model" nếu lọt vào stdout


_SECRET_RE = re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret)\b\s*[=:]\s*\S+")
_GH_SECRET_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def _redact(s) -> str:
    s = str(s or "")
    if BOT_TOKEN:
        s = s.replace(BOT_TOKEN, "***")
    if GH_TOKEN_CACHE:
        s = s.replace(GH_TOKEN_CACHE, "***")
    if mail:
        try:
            pw = mail.password()
            if pw:
                s = s.replace(pw, "***")
        except Exception:
            pass
    s = _GH_SECRET_RE.sub("***", s)
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", s)


def clean_output(s: str) -> str:
    s = _ANSI.sub("", s or "").replace("\r", "").strip()
    s = _HEADER.sub("", s).strip()
    return _redact(s)


ACTIVITY: dict = {}                # chat_id -> danh sách việc agent đã làm (hiện trong tin nhắn tiến độ)


def _clip(s, n: int = PROGRESS_DETAIL) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def _rel(path) -> str:
    try:
        return Path(path).resolve().relative_to(WORKSPACE.resolve()).as_posix()
    except Exception:
        return str(path or "")


def _int(x) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _fmt_tok(n: int) -> str:
    """1234 -> '1,2k' cho footer gọn trên điện thoại."""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "k"


def _note_usage(chat_id: int, tokens: dict, cost=None) -> None:
    """Cộng dồn token thật OpenCode báo ở mỗi bước (sự kiện step_finish).

    `input`/cache của mỗi bước là toàn bộ ngữ cảnh gửi cho model nên lấy mức lớn
    nhất (ngữ cảnh đỉnh); `output`/`reasoning`/`cost` thì cộng dồn qua các bước.
    """
    tokens = tokens or {}
    cache = tokens.get("cache") or {}
    u = TOKEN_USAGE.setdefault(chat_id, {"input": 0, "cache_read": 0, "cache_write": 0,
                                         "output": 0, "reasoning": 0, "cost": 0.0})
    u["input"] = max(u["input"], _int(tokens.get("input")))
    u["cache_read"] = max(u["cache_read"], _int(cache.get("read")))
    u["cache_write"] = max(u["cache_write"], _int(cache.get("write")))
    u["output"] += _int(tokens.get("output"))
    u["reasoning"] += _int(tokens.get("reasoning"))
    try:
        u["cost"] += float(cost or 0)
    except (TypeError, ValueError):
        pass


_HEADROOM_ON = os.getenv("AISTV_HEADROOM", "1") != "0"
_headroom_compress = None            # hàm compress của Headroom (nạp lười)
_headroom_tried = False
_headroom_lock = threading.Lock()    # Headroom không an toàn khi nén song song
HEADROOM_KEEP = 0.97                # phải giảm ≥3% mới đáng dùng


def _headroom_fn():
    """Nạp Headroom một lần; máy chưa cài thì trả None (bot vẫn chạy bình thường)."""
    global _headroom_compress, _headroom_tried
    if not _headroom_tried:
        _headroom_tried = True
        try:
            os.environ.setdefault("HEADROOM_OFFLINE", "1")   # không tải model, không gửi telemetry
            from headroom import compress as fn
            _headroom_compress = fn
            logging.getLogger("headroom").setLevel(logging.WARNING)   # đỡ rác log mỗi lượt
        except Exception as e:                      # thiếu thư viện / lỗi cài đặt
            log.info("Headroom không dùng được: %s", e)
    return _headroom_compress


def _headroom_warm() -> None:
    """Gọi thử một lần cho Headroom nạp sẵn pipeline (lần đầu mất vài giây)."""
    fn = _headroom_fn()
    if not fn or not _HEADROOM_ON:
        return
    try:
        sample = ", ".join(f'{{"id":{i},"status":"ok","value":{i * 3}}}' for i in range(60))
        with _headroom_lock:
            fn([{"role": "user", "content": "Kết quả tool:\n" + sample}],
               compress_user_messages=True, kompress_model="disabled")
        log.info("Headroom sẵn sàng")
    except Exception as e:
        log.info("Headroom warm-up lỗi: %s", e)


def _headroom_shrink(text: str) -> tuple:
    """Nén phần ngữ cảnh của prompt (giữ nguyên yêu cầu mới của người dùng).

    Trả (prompt_mới, token_trước, token_sau). Không nén được thì trả lại bản gốc.
    """
    fn = _headroom_fn()
    if not _HEADROOM_ON or fn is None or len(text) < 4000:
        return text, 0, 0
    mark = "## YÊU CẦU MỚI\n[Người dùng]: "
    i = text.rfind(mark)
    if i <= 0:
        return text, 0, 0
    head, tail = text[:i].rstrip(), text[i:]
    try:
        with _headroom_lock:
            r = fn([{"role": "user", "content": head}], compress_user_messages=True,
                   kompress_model="disabled")
        out = (r.messages or [{}])[0].get("content") or ""
    except Exception as e:
        log.warning("Headroom nén prompt lỗi: %s", e)
        return text, 0, 0
    before, after = _int(getattr(r, "tokens_before", 0)), _int(getattr(r, "tokens_after", 0))
    if (not out or before <= 0 or after <= 0 or after > before * HEADROOM_KEEP
            or len(out) >= len(head)):
        return text, 0, 0
    return out.rstrip() + "\n\n" + tail, before, after


async def _headroom_prompt(prompt: str) -> tuple:
    """Chạy nén ở luồng riêng, tối đa 2,5 giây — quá giờ thì dùng prompt gốc."""
    if not _HEADROOM_ON:
        return prompt, 0, 0
    try:
        return await asyncio.wait_for(asyncio.to_thread(_headroom_shrink, prompt), 2.5)
    except Exception:
        return prompt, 0, 0


def _token_footer(chat_id: int, saved: int = 0) -> str:
    """Cụm token cuối tin nhắn: token gốc và phần còn lại sau khi qua Headroom."""
    u = TOKEN_USAGE.get(chat_id) or {}
    think = _int(THINK_TOKENS.get(chat_id, 0))
    used = _int(u.get("input")) or (_int(u.get("cache_read")) + _int(u.get("cache_write")))
    out = _int(u.get("output"))
    if not used:
        # Model không báo token vào (web2api dự phòng…) → giữ cách hiện cũ.
        return f"🧠 {_fmt_tok(think)} tok" if think else ""
    goc = used + max(0, saved)
    seg = f"🧠 {_fmt_tok(goc)} tok gốc"
    if saved > 0:
        pct = round(saved * 100 / goc)
        seg += f" → {_fmt_tok(used)} qua headroom (−{pct}%)"
    else:
        seg += " · headroom không giảm"
    if out:
        seg += f" · ra {_fmt_tok(out)}"
    return seg


_TOOL_INFO = {
    "bash": ("⚙️", "Chạy lệnh"),
    "shell": ("⚙️", "Chạy lệnh"),         # OpenCode v2 đổi tên bash → shell
    "execute": ("🤖", "Chạy tool phụ"),
    "search": ("🌐", "Tìm web"),
    "write": ("📝", "Tạo file"),
    "edit": ("✏️", "Sửa code"),
    "patch": ("✏️", "Sửa code"),
    "read": ("📖", "Đọc file"),
    "webfetch": ("🌐", "Truy cập web"),
    "websearch": ("🌐", "Tìm web"),
    "grep": ("🔎", "Tìm trong mã"),
    "glob": ("🔎", "Tìm file"),
    "list": ("📂", "Liệt kê"),
    "task": ("🤖", "Giao việc phụ"),
    "todowrite": ("📋", "Cập nhật kế hoạch"),
    "ask_user": ("❓", "Hỏi bạn"),
    "render_pages": ("📄", "Dựng ảnh trang"),
}


def _tool_entry(part: dict) -> Optional[dict]:
    """Đổi 1 sự kiện tool_use của OpenCode thành dòng tiến độ gọn cho Telegram."""
    tool = (part.get("tool") or "").lower()
    st = part.get("state") or {}
    inp = st.get("input") or {}
    icon, label = _TOOL_INFO.get(tool, ("🔧", tool or "Công cụ"))
    target, detail, lang = "", "", ""

    output = ""
    if tool in ("bash", "shell"):
        cmd = _clip(_redact(inp.get("command", "")), PROGRESS_DETAIL)
        target = _clip(" ".join(str(cmd).split()), 80)
        output = _clip(_redact(st.get("output", "")), PROGRESS_DETAIL)
        detail = _clip(f"$ {cmd}") if (len(cmd) > 80 or "\n" in cmd) else ""
        lang = "bash"
    elif tool == "execute":
        code = str(inp.get("code") or "")
        m = re.search(r"tools(?:\.|\[\s*[\"'])(\w+)", code)
        target = m.group(1) if m else ""
        if not target:
            detail = _clip(_redact(code))
            lang = "javascript"
    elif tool == "search":
        target = _clip(_redact(inp.get("query", "")), 120)
    elif tool in ("write", "patch"):
        target = _rel(inp.get("filePath", ""))
        detail = _clip(_redact(inp.get("content", "") or inp.get("patch", "")))
        lang = "diff" if tool == "patch" else ""
    elif tool == "edit":
        target = _rel(inp.get("filePath", ""))
        old = _clip(_redact(inp.get("oldString", "")), 240)
        new = _clip(_redact(inp.get("newString", "")), 240)
        detail = _clip("\n".join(x for x in (f"- {old}" if old else "", f"+ {new}" if new else "") if x))
        lang = "diff"
    elif tool in ("read", "list"):
        target = _rel(inp.get("filePath", "") or inp.get("path", ""))
    elif tool in ("webfetch", "websearch"):
        target = _clip(_redact(inp.get("url", "") or inp.get("query", "")), 200)
    elif tool in ("grep", "glob"):
        target = _clip(_redact(inp.get("pattern", "")), 80)
        p = inp.get("path")
        if p:
            target += f" · {_clip(_rel(p), 60)}"
    elif tool == "task":
        target = _clip(_redact(inp.get("description", "") or inp.get("prompt", "")), 120)
    elif tool == "todowrite":
        todos = inp.get("todos") or []
        target = f"{len(todos)} mục" if isinstance(todos, list) else ""
    elif tool == "ask_user":
        target = _clip(_redact(inp.get("question", "")), 160)
        opts = inp.get("options") or []
        if isinstance(opts, list) and opts:
            target += f" · {len(opts)} lựa chọn"

    if not target and tool not in _TOOL_INFO:
        for v in inp.values():
            if isinstance(v, str) and v.strip():
                target = _clip(_redact(v), 100)
                break
    if not target:
        target = _clip(_redact(st.get("title") or ""), 100)
    target = " ".join(str(target).split())
    when = st.get("time") or {}
    status = str(st.get("status") or "").lower()
    return {"icon": icon, "label": label, "target": target, "detail": detail,
            "output": output, "lang": lang, "ok": status != "error",
            "call": part.get("callID") or part.get("id") or part.get("partID"),
            "status": status,
            "tstart": when.get("start"), "tend": when.get("end"),
            "seen": time.monotonic()}


def _keep_tool_timing(old: dict, new: dict) -> dict:
    """Cập nhật cùng callID: giữ mốc quan sát đầu tiên để đo thời gian chạy."""
    new["seen"] = old.get("seen") or new.get("seen")
    new["tstart"] = new.get("tstart") or old.get("tstart")
    new["tend"] = new.get("tend") or old.get("tend")
    return new


def _dur_text(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m{s:02d}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _tool_dur(e: dict, live: bool = True) -> str:
    """Thời gian tool đang/đã chạy: ' · 35s' (rỗng nếu chưa đo được)."""
    try:
        start, end = e.get("tstart"), e.get("tend")
        if start and end:
            sec = (float(end) - float(start)) / 1000.0
        elif (live and str(e.get("status") or "").lower() in ("running", "pending")
              and e.get("seen")):
            sec = time.monotonic() - float(e["seen"])
        else:
            return ""
    except (TypeError, ValueError):
        return ""
    if sec < 1 or sec > 86400:
        return ""
    return " · " + _dur_text(sec)


def _status_rows(chat_id: int, limit: int = PROGRESS_KEEP) -> list:
    rows = []
    for e in (ACTIVITY.get(chat_id) or [])[-limit:]:
        mark = "" if e.get("ok", True) else "⚠️ "
        line = f"{e['icon']} {mark}<b>{esc(e['label'])}</b>"
        if e.get("target"):
            line += f" <code>{esc(e['target'])}</code>"
        line += _tool_dur(e, live=False)
        rows.append(line)
        if e.get("detail"):
            rows.append(f"<pre>{esc(e['detail'])}</pre>")
    return rows


def _model_base(name: str = "") -> str:
    """Tên model bỏ phần #variant để so sánh."""
    return (name or STATE.get("model") or DEFAULT_MODEL).split("#")[0].strip()


def _model_has_no_thinking() -> bool:
    """Model hiện tại đã từng chạy mà không trả reasoning (vd bản flash free)."""
    return bool(NO_THINK.get(_model_base()))


def _thinking_text(chat_id: int) -> str:
    parts = THINKING.get(chat_id) or []
    if not parts:
        return ""
    return clean_output("\n\n".join(parts)).strip()


def _thinking_tail(chat_id: int, n: int = 600) -> str:
    t = _thinking_text(chat_id)
    return t[-n:] if len(t) > n else t


def _last_action(chat_id: int) -> str:
    items = ACTIVITY.get(chat_id) or []
    if not items:
        return ""
    e = items[-1]
    line = f"{e['icon']} {e['label']}"
    if e.get("target"):
        line += " " + _clip(e["target"], 48)
    return line


def _push_live(chat_id: int, kind: str, payload, call: Optional[str] = None) -> None:
    """Ghi 1 sự kiện vào dòng thời gian để tin nhắn tiến độ cuộn như terminal."""
    box = LIVE.setdefault(chat_id, [])
    if kind == "think":
        txt = str(payload or "")
        if not txt:
            return
        if box and box[-1].get("kind") == "think":
            box[-1]["text"] = (box[-1]["text"] + txt)[-4000:]
        else:
            box.append({"kind": "think", "text": txt[-4000:]})
    else:
        if call:
            for i, old in enumerate(box):
                if old.get("call") == call:
                    prev = old.get("entry") or {}
                    box[i] = {"kind": "tool", "entry": _keep_tool_timing(prev, payload),
                              "call": call}
                    return
        box.append({"kind": "tool", "entry": payload, "call": call})
    del box[:-300]


def _wrap_live(text: str, width: int = 44) -> list:
    out = []
    for para in str(text or "").splitlines():
        para = para.strip()
        if not para:
            continue
        out.extend(textwrap.wrap(para, width=width, break_long_words=True,
                                 replace_whitespace=False) or [para])
    return out


def _code_block(text: str, lang: str = "") -> str:
    """Khối mã kiểu ```lang … ``` để lệnh/code dễ đọc trên Telegram."""
    cls = f' class="language-{lang}"' if lang and lang.isalnum() else ""
    return f"<pre><code{cls}>{esc(text)}</code></pre>"


def _live_blocks(chat_id: int, detailed: bool = False) -> list:
    """Đổi dòng thời gian thành các khối HTML gọn, mới nhất ở cuối."""
    blocks = []
    show_think = STATE.get("show_thinking", True)
    for ev in LIVE.get(chat_id) or []:
        if ev.get("kind") == "think":
            if not show_think:
                continue
            text = clean_output(ev.get("text") or "").strip()
            if not text:
                continue
            lines = _wrap_live(text[-900:])
            if len(lines) > 6:
                # Reasoning của OpenCode v2 về thành 1 cục ở cuối lượt: giữ cả mở đầu
                # lẫn kết luận để không bị đọc như đoạn cắt giữa câu.
                shown = "\n".join(lines[:2] + ["…"] + lines[-3:])
            else:
                shown = "\n".join(lines)
            blocks.append("💭 <i>Suy nghĩ</i>\n<i>" + esc(shown) + "</i>")
        else:
            e = ev.get("entry") or {}
            line = f"{e.get('icon', '🔧')} " + ("" if e.get("ok", True) else "⚠️ ")
            line += f"<b>{esc(e.get('label', 'Công cụ'))}</b>"
            if e.get("target"):
                line += f" <code>{esc(e['target'])}</code>"
            line += _tool_dur(e)
            detail = str(e.get("detail") or "").strip()
            if detail:
                dlines = detail.splitlines()
                keep = 8 if detailed else 4
                if len(dlines) > keep:
                    detail = "\n".join(dlines[:keep]) + "\n…"
                line += "\n" + _code_block(detail, e.get("lang") or "")
            output = str(e.get("output") or "").strip() if detailed else ""
            if output:
                olines = output.splitlines()
                if len(olines) > 6:
                    output = "\n".join(olines[:6]) + "\n…"
                line += "\n" + _code_block(output)
            blocks.append(line)
    return blocks


def _tail_blocks(blocks: list, max_lines: int = PROGRESS_LINES,
                 max_chars: int = PROGRESS_CHARS) -> tuple:
    """Giữ các khối cuối vừa khung; khối cũ rơi khỏi đỉnh (cuộn xuống)."""
    kept, used_lines, used_chars = [], 0, 0
    for b in reversed(blocks):
        n = b.count("\n") + 1
        c = len(b) + 1
        if kept and (used_lines + n > max_lines or used_chars + c > max_chars):
            break
        kept.append(b)
        used_lines += n
        used_chars += c
    kept.reverse()
    return kept, len(kept) < len(blocks)


def _render_status(chat_id: int, started: float, frame: str = "🧠") -> str:
    secs = int(time.monotonic() - started)
    last = _last_action(chat_id)
    head = (f"{frame} <i>Đang làm việc…</i> {secs}s"
            + (f" · {esc(last)}" if last else ""))
    detailed = bool(STATE.get("show_activity", False))
    blocks = _live_blocks(chat_id, detailed=detailed)
    if (STATE.get("show_thinking", True) and not THINKING.get(chat_id)
            and _model_has_no_thinking()):
        blocks.append("💭 <i>Model này không trả phần suy nghĩ — đổi bằng /model "
                      "(xem /models)</i>")
    kept, cut = _tail_blocks(blocks, PROGRESS_LINES + (4 if detailed else 0))
    if not kept:
        return head + "\n⏳ <i>Đang chờ model phản hồi…</i>"
    if cut:
        kept.insert(0, "⏫ <i>…đã cuộn, mở rộng để xem đầy đủ</i>")
    return head + "\n<blockquote expandable>" + "\n\n".join(kept) + "</blockquote>"


async def _iter_lines(stream, max_line: int = 4 * 1024 * 1024):
    """Đọc theo chunk và tự cắt dòng.

    asyncio StreamReader.readline() ném "Separator is not found, and chunk exceed
    the limit" khi một dòng dài hơn buffer (opencode --format json có thể in ra
    dòng JSON rất dài vì tool output/base64). Hàm này không bao giờ ném lỗi đó:
    dòng quá dài bị cắt bớt nhưng vẫn đọc tiếp bình thường.
    """
    buf = bytearray()
    skipped = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        start = 0
        while True:
            nl = chunk.find(b"\n", start)
            if nl < 0:
                if not skipped:
                    buf += chunk[start:]
                    if len(buf) > max_line:
                        del buf[max_line:]
                        skipped = True
                break
            if not skipped:
                buf += chunk[start:nl]
                if len(buf) > max_line:
                    del buf[max_line:]
                    skipped = True
            yield bytes(buf)
            buf.clear()
            skipped = False
            start = nl + 1
    if buf:
        yield bytes(buf)


async def _talk(proc, data: Optional[bytes], chat_id: int, err_lines: list) -> str:
    """Gửi prompt qua stdin, đọc stdout từng dòng.
    OpenCode chạy với --format json nên mỗi dòng là 1 sự kiện: text / tool_use / step_start."""
    texts, raw, buf, mid = [], [], [], None

    async def feed():
        if data is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    async def read_out():
        nonlocal buf, mid
        assert proc.stdout is not None
        async for line in _iter_lines(proc.stdout):
            t = line.decode("utf-8", "replace").strip()
            if not t:
                continue
            if not t.startswith("{"):
                raw.append(t)
                continue
            try:
                ev = json.loads(t)
            except Exception:
                raw.append(t)
                continue
            etype = ev.get("type")
            part = ev.get("part") or {}
            if etype == "text":
                txt = part.get("text") or ""
                if not txt:
                    continue
                m = part.get("messageID")
                if m != mid:
                    if buf:
                        texts.append("".join(buf))
                    buf, mid = [], m
                buf.append(txt)
            elif etype == "reasoning":
                txt = part.get("text") or ""
                if txt:
                    parts = THINKING.setdefault(chat_id, [])
                    parts.append(txt)
                    del parts[:-200]
                    THINKING_LAST[chat_id] = time.monotonic()
                    _push_live(chat_id, "think", txt)
            elif etype == "step_finish":
                tk = part.get("tokens") or {}
                rt = _int(tk.get("reasoning"))
                if rt:
                    THINK_TOKENS[chat_id] = THINK_TOKENS.get(chat_id, 0) + rt
                _note_usage(chat_id, tk, part.get("cost"))
            elif etype == "tool_use":
                entry = _tool_entry(part)
                if entry:
                    items = ACTIVITY.setdefault(chat_id, [])
                    call = entry.get("call")
                    if call:
                        for i, old in enumerate(items):          # cùng callID: cập nhật, không lặp
                            if old.get("call") == call:
                                entry = items[i] = _keep_tool_timing(old, entry)
                                break
                        else:
                            items.append(entry)
                    else:
                        items.append(entry)
                    del items[:-PROGRESS_KEEP * 3]
                    _push_live(chat_id, "tool", entry, call)
            elif etype == "error":
                err = part.get("error") or ev.get("error") or ""
                if isinstance(err, dict):
                    err = json.dumps(err, ensure_ascii=False)
                if err:
                    raw.append(str(err))
            elif ev.get("name") or ev.get("error"):
                # JSON lỗi không có "type" (UnknownError...) — vẫn phải báo về.
                raw.append(t)

    async def watch_err():
        try:
            async for line in _iter_lines(proc.stderr):
                t = clean_output(line.decode("utf-8", "replace"))
                if t:
                    err_lines.append(t)
                    del err_lines[:-60]
        except Exception:
            pass

    await asyncio.gather(read_out(), feed(), watch_err())
    await proc.wait()
    if buf:
        texts.append("".join(buf))
    return (texts[-1] if texts else "") or "\n".join(raw)


_OPENCODE_BAD_OUTPUT = (
    "usage\n  opencode run",
    "run opencode with a message",
    "unrecognized flag:",
    "the command line is too long",
)

_ERROR_TEXT_MARKERS = (
    "unexpected server error", "internal server error", "unknown error",
    "unknownerror", "provider error", "bad gateway", "service unavailable",
    "gateway timeout", "fetch failed", "socket hang up", "econnreset",
    "connection reset", "upstream connect error", "no healthy upstream",
    "freeusagelimiterror", "provider.free-limit",
)


def _is_opencode_error_output(text: str) -> bool:
    """CLI in help/lỗi cú pháp thay vì câu trả lời — đừng gửi nguyên văn cho người dùng."""
    low = (text or "").lower()
    return any(marker in low for marker in _OPENCODE_BAD_OUTPUT)


def _is_error_payload(text: str) -> bool:
    """OpenCode đôi khi in nguyên JSON/lỗi (UnknownError...) như 'câu trả lời'."""
    raw = (text or "").strip()
    if not raw:
        return False
    stripped = re.sub(r"(?is)^```[a-z0-9_-]*\s*|\s*```$", "", raw).strip()
    low = stripped.lower()

    # 1) Dạng chữ thuần: chỉ coi là lỗi khi cả phản hồi bắt đầu bằng lỗi.
    #    (Không dùng danh sách marker cho mọi câu chữ, vì một câu trả lời giải
    #    thích lỗi — vd. "Mình đã sửa lỗi UnknownError…" — sẽ bị bỏ oan.)
    if low.startswith(("error:", "unknown error", "unknownerror",
                       "unexpected server error", "provider error",
                       "internal server error")):
        return True

    # 2) Dạng JSON do `opencode run --format json` in ra stdout.
    if not stripped.startswith(("{", "[")):
        return False
    if "ref err_" in low or "check server logs" in low:
        return True
    # Object lỗi hạn mức free: type=provider.free-limit, status=429, retryAfterMs…
    # Trước đây bị coi là câu trả lời nên còn được lưu vào lịch sử.
    if "provider.free-limit" in low or "freeusagelimiterror" in low \
            or '"retryafterms"' in low:
        return True
    if "free usage limit" in low and '"status"' in low:
        return True
    if re.search(r'"status"\s*:\s*(?:429|5\d\d)\b', stripped) \
            and ('"body"' in low or '"provider.' in low):
        return True
    candidates = [stripped.splitlines()[0].strip(), stripped]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or "")
        if name.endswith("Error") or data.get("type") == "error" or "error" in data:
            return True
        message = str(data.get("message") or "")
        if message and any(marker in message.lower() for marker in _ERROR_TEXT_MARKERS):
            return True
    return False


def _is_error_history(content: str) -> bool:
    """Lọc bỏ nội dung lỗi từng bị lưu nhầm vào lịch sử hội thoại.

    Không dùng thẳng _is_error_payload vì một câu trả lời bình thường có thể
    nhắc tới cụm "Unexpected server error" khi đang giải thích lỗi.
    """
    raw = (content or "").strip()
    if not raw:
        return False
    if raw.startswith(("{", "[")) and _is_error_payload(raw):
        return True
    return raw.lower().startswith((
        "error:", "unknownerror", "⚠️ model chính", "⚠️ opencode không trả về",
    ))


_QUOTA_MARKERS = (
    "429", "too many requests", "rate limit", "rate-limit", "quota",
    "resource exhausted", "resource_exhausted", "insufficient",
    "out of tokens", "token budget", "usage limit", "limit exceeded",
    "exceeded your", "no credits", "credit balance", "payment required",
    "billing", "free trial", "402", "exhausted", "daily limit", "monthly limit",
    "free usage limit", "freeusagelimiterror", "provider.free-limit",
    "subscribe to opencode go", "retryafterms",
)


def _is_quota_error(text: str) -> bool:
    """Lỗi hết hạn mức / hết token (không phải lỗi cấu hình model)."""
    low = (text or "").lower()
    if not low:
        return False
    if any(m in low for m in ("model not found", "model unavailable",
                              "unknown model", "no model is available")):
        return False
    return any(marker in low for marker in _QUOTA_MARKERS)


_SERVER_ERROR_MARKERS = (
    "unknownerror", "unknown error", "unexpected server error",
    "internal server error", "server error", "bad gateway",
    "service unavailable", "overloaded", "upstream", "econnreset",
    "socket hang up", "fetch failed", "provider error", "502", "503", "504",
    "http 500", "http 400", "http 401", "http 403", "bad request",
    "unauthorized", "forbidden", "invalid cookie", "cookie expired",
    "xsrf", "snlm0e", "authentication",
)


def _is_server_error(text: str) -> bool:
    """Lỗi từ nhà cung cấp model (UnknownError, 5xx...) — cũng nên thử dự phòng."""
    low = (text or "").lower()
    if not low:
        return False
    if any(m in low for m in ("model not found", "model unavailable",
                              "unknown model", "no model is available")):
        return False
    return any(marker in low for marker in _SERVER_ERROR_MARKERS)


def _human_secs(sec: float) -> str:
    """Đổi số giây thành chuỗi ngắn kiểu '18 giờ 20 phút'."""
    try:
        sec = int(max(0, sec))
    except Exception:
        return "?"
    if sec < 90:
        return f"{sec} giây"
    minutes = sec // 60
    if minutes < 90:
        return f"{minutes} phút"
    hours, minutes = divmod(minutes, 60)
    if hours < 36:
        return f"{hours} giờ" + (f" {minutes} phút" if minutes else "")
    days, hours = divmod(hours, 24)
    return f"{days} ngày" + (f" {hours} giờ" if hours else "")


def _pretty_error(text: str) -> str:
    """Rút gọn JSON lỗi của OpenCode thành một dòng dễ đọc."""
    raw = (text or "").strip()
    low = raw.lower()
    if "has no session table" in low:
        return ("OpenCode đang chạy bản cũ (v1) trên dữ liệu của bản mới (v2). "
                "Cài bản mới rồi chạy lại bot: curl -fsSL https://opencode.ai/v2/install | bash "
                "(hoặc đặt OPENCODE_BIN trỏ tới binary v2).")
    if "free usage limit" in low or "provider.free-limit" in low \
            or "freeusagelimiterror" in low:
        msg = "OpenCode đã hết hạn mức model miễn phí"
        retry = re.search(r'"retryAfterMs"\s*:\s*(\d+)', raw)
        if retry:
            try:
                msg += f" — thử lại sau khoảng {_human_secs(int(retry.group(1)) / 1000)}"
            except Exception:
                pass
        msg += " (hoặc đổi model trả phí / dùng model dự phòng)."
        return msg
    match = re.search(r'"message"\s*:\s*"([^"]{3,400})"', raw)
    if not match:
        return raw[-1200:]
    msg = match.group(1)
    ref = re.search(r'"ref"\s*:\s*"([^"]+)"', raw)
    if ref:
        msg += f" (ref {ref.group(1)})"
    return msg


def agent_model_chain() -> list:
    """Model chính + model dự phòng (Gemini) khi hết hạn mức."""
    chain = [opencode_model()]
    if not WEB2API_FALLBACK or web2api is None:
        return chain
    try:
        if not web2api.enabled():
            return chain
    except Exception:
        return chain
    raw = (os.getenv("OPENCODE_FALLBACK_MODELS") or "").strip()
    candidates = raw.split(",") if raw else [f"web2api/{WEB2API_MODEL}"]
    for item in candidates:
        item = (item or "").strip()
        if item and item not in chain:
            chain.append(item)
    return chain


def _fallback_hint() -> str:
    """Gợi ý ngắn khi model dự phòng không trả lời được (dựa trên trạng thái thật)."""
    if web2api is None:
        return "💡 Thiếu module Gemini nên không có model dự phòng."
    try:
        info = web2api.status_report()
    except Exception:
        return "💡 Gửi /gemini để kiểm tra model dự phòng."
    if not info.get("enabled"):
        return "💡 Model dự phòng đang tắt."
    if not info.get("cookie"):
        return ("💡 Chưa có cookie Gemini. Dán cookie mới: /gemini import "
                "__Secure-1PSID=...; SAPISID=... rồi thử lại.")
    if not info.get("running"):
        return "💡 Server dự phòng chưa chạy. Gửi /gemini auto để bật lại."
    if not info.get("xsrf"):
        return "💡 Gemini thiếu XSRF token. Gửi /gemini refresh rồi thử lại."
    # Server + cookie + XSRF đều ổn → đừng đổ lỗi cookie. Xem log để biết lý do thật.
    return ("💡 Gemini vẫn chạy và đã có cookie/XSRF — lỗi nằm ở phía Gemini "
            "hoặc OpenCode. Gửi /gemini logs (hoặc /gemini test \"ping\") để xem chi tiết.")


def _agent_failure(err_text: str, quota: bool = False, tools: bool = False,
                   server: bool = False) -> str:
    if server:
        head = ("⚠️ Model chính gặp lỗi từ nhà cung cấp và model dự phòng "
                "cũng chưa trả lời được.")
        if tools:
            head = ("⚠️ Model chính gặp lỗi từ nhà cung cấp. Tác vụ đã chạy "
                    "được một phần nên không tự chạy lại để tránh trùng lặp.")
    elif not quota:
        head = "⚠️ OpenCode không trả về phản hồi."
    elif tools:
        head = ("⚠️ Model chính đã hết hạn mức request. Tác vụ đã chạy được một phần "
                "nên không tự chạy lại để tránh trùng lặp.")
    else:
        head = "⚠️ Model chính đã hết hạn mức request và model dự phòng cũng chưa trả lời được."
    detail = _pretty_error(err_text)
    hint = ""
    if not tools and (server or quota):
        try:
            if len(agent_model_chain()) > 1:
                hint = _fallback_hint()
        except Exception:
            hint = ""
    return head + (f"\n\n{detail}" if detail else "") + (f"\n\n{hint}" if hint else "")


async def _run_opencode_once(chat_id: int, prompt: str, env: dict, model: str) -> tuple:
    """Chạy một lượt OpenCode. Trả (ok, text/lỗi, đã_chạy_tool)."""
    cmd = [OPENCODE_BIN, "run", "--model", model,
           "--auto", "--thinking", "--format", "json"]
    ACTIVITY[chat_id] = []
    THINKING[chat_id] = []
    LIVE[chat_id] = []
    THINK_TOKENS[chat_id] = 0
    TOKEN_USAGE.pop(chat_id, None)
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(WORKSPACE), env=env, limit=2 ** 20,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    RUNNING[chat_id] = proc
    err_lines: list = []
    try:
        coro = _talk(proc, prompt.encode("utf-8"), chat_id, err_lines)
        out = (await asyncio.wait_for(coro, timeout=AGENT_TIMEOUT)
               if AGENT_TIMEOUT > 0 else await coro)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    finally:
        RUNNING.pop(chat_id, None)
        _cancel_chat_asks(chat_id)
    # Ghi nhớ model nào không trả reasoning để lần sau báo rõ thay vì khung 💭 trống.
    base = _model_base(model)
    if base:
        if THINKING.get(chat_id) or THINK_TOKENS.get(chat_id):
            NO_THINK.pop(base, None)
        else:
            NO_THINK[base] = True
    tools_ran = bool(ACTIVITY.get(chat_id) or LIVE.get(chat_id))
    text = clean_output(out)
    if text and not _is_opencode_error_output(text) and not _is_error_payload(text):
        # OpenCode có thể trả rc=1 sau khi tool lỗi nhưng vẫn có câu trả lời hoàn chỉnh.
        if proc.returncode not in (0, None):
            log.warning("OpenCode rc=%s nhưng vẫn có câu trả lời — dùng câu trả lời",
                        proc.returncode)
        return True, text, tools_ran
    err_text = "\n".join(x for x in (("\n".join(err_lines)).strip(), text.strip()) if x)
    log.warning("OpenCode không trả kết quả (model %s, rc=%s): %s",
                model, proc.returncode, err_text[-300:])
    return False, err_text, tools_ran


_TOOLLESS_RULES = (
    "HƯỚNG DẪN HỆ THỐNG (quan trọng hơn yêu cầu bên dưới):\n"
    "Bạn đang trả lời ở chế độ DỰ PHÒNG và KHÔNG có công cụ nào: không mở trình duyệt, "
    "không chạy lệnh, không đọc/ghi/gửi file, không chụp màn hình, không truy cập mạng. "
    "Tuyệt đối không viết như đã thực hiện, không bịa tên file, không ghi dòng "
    "'File kết quả: ...'. Nếu người dùng yêu cầu một hành động, hãy nói thật là chưa "
    "thực hiện được vì model chính đang lỗi, và đề nghị họ thử lại sau ít phút."
)

_FAKE_FILE_LINE = re.compile(
    r"^\s*(?:[-*>]+\s*)?(?:file\s+(?:kết quả|đính kèm|đầu ra)|output\s+file)\s*:.*$",
    re.IGNORECASE)


def _drop_fake_files(text: str) -> str:
    """Bỏ dòng 'File kết quả: …' khi câu trả lời đến từ đường không có công cụ."""
    lines = (text or "").splitlines()
    kept = [ln for ln in lines if not _FAKE_FILE_LINE.match(ln)]
    if len(kept) == len(lines):
        return text
    note = ("⚠️ Lượt này chạy ở chế độ dự phòng (không có công cụ) nên "
            "không có file nào được tạo.")
    return ("\n".join(kept).strip() + "\n\n" + note).strip()


async def _run_web2api_direct(prompt: str, model: str) -> tuple:
    """Gọi thẳng server Gemini dự phòng, không qua OpenCode.

    OpenCode đôi khi trả 500 "Unexpected server error. Check server logs for
    details." cho cả model dự phòng dù server Gemini vẫn khoẻ (request không
    hề tới server). Đường tắt này giữ cho dự phòng hoạt động đúng ý nghĩa của nó.
    Đường tắt này KHÔNG có công cụ nên phải nói rõ để model không bịa là đã làm.
    Trả (ok, text hoặc lỗi).
    """
    if web2api is None:
        return False, "Thiếu module Gemini nên không gọi được model dự phòng."
    prompt = _TOOLLESS_RULES + "\n\nYÊU CẦU CỦA NGƯỜI DÙNG:\n" + prompt
    mid = model.split("/", 1)[1] if "/" in model else ""
    try:
        ready = await asyncio.to_thread(web2api.ensure_server)
    except Exception as exc:
        return False, f"Gemini: {type(exc).__name__}: {exc}"
    if not ready:
        return False, "Gemini: server chưa sẵn sàng"
    timeout = 240 if AGENT_TIMEOUT <= 0 else max(60, min(AGENT_TIMEOUT, 300))
    try:
        text, err = await asyncio.to_thread(
            web2api.chat, [{"role": "user", "content": prompt}], mid, timeout)
    except Exception as exc:
        return False, f"Gemini: {type(exc).__name__}: {exc}"
    text = _drop_fake_files(clean_output(text or ""))
    if text:
        return True, text
    return False, "Gemini: " + (err or "không trả lời")


def make_checkpoint(chat_id: int, label: str = "") -> str:
    """Chụp repo trước khi agent sửa. Trả checkpoint id ('' nếu không làm được)."""
    LAST_CHECKPOINT.pop(chat_id, None)
    if planner is None:
        return ""
    rd = repo_dir()
    if not rd:
        return ""
    try:
        meta, err = planner.create_checkpoint(HOME, rd, label)
    except Exception as e:  # noqa
        log.warning("Tạo checkpoint lỗi: %s", oneline(str(e), 200))
        return ""
    if not meta:
        log.warning("Không tạo được checkpoint: %s", err)
        return ""
    LAST_CHECKPOINT[chat_id] = meta["id"]
    return meta["id"]


def review_markup(chat_id: int) -> InlineKeyboardMarkup:
    cp = LAST_CHECKPOINT.get(chat_id) or ""
    row = [InlineKeyboardButton("⬆️ Push", callback_data="up:push")]
    if cp:
        row.append(InlineKeyboardButton("↩️ Hoàn tác", callback_data=f"up:undo:{cp}"))
    rows = [row, [InlineKeyboardButton("📄 Xem thay đổi", callback_data="up:diff")]]
    return InlineKeyboardMarkup(rows)


async def _autopush_after_agent(chat_id: int) -> None:
    """Sau lượt agent: tự push (nếu bật) hoặc hiện diff + nút duyệt."""
    if planner is None:
        return
    rd = repo_dir()
    if not rd or chat_id in PLAN_BUSY:
        return                       # plan có báo cáo riêng ở cuối
    try:
        stat = await asyncio.to_thread(planner.diff_stat, rd)
    except Exception:
        return
    if not stat.get("files") and not stat.get("untracked"):
        return
    cp_id = LAST_CHECKPOINT.get(chat_id) or ""
    if cp_id:
        meta = planner.load_checkpoint(HOME, cp_id)
        if meta and (meta.get("stat") or "") == (stat.get("text") or ""):
            return                       # repo đã dở từ trước, lượt này không đổi gì thêm
    if AUTO_PUSH and github_token():
        try:
            slug = current_repo_slug() or repo_remote_slug()
            if slug and await asyncio.to_thread(repo_can_push, slug, github_token()):
                await asyncio.to_thread(gh_push_code, slug)
            else:
                return
        except Exception as e:
            log.warning("Tự đẩy code lên GitHub thất bại: %s", oneline(str(e), 200))
            return
        if BOT_OBJ is not None:
            try:
                await BOT_OBJ.send_message(
                    chat_id,
                    "⬆️ Đã đẩy code lên GitHub.\n"
                    "Windows chạy <code>run.bat</code> (hoặc <code>/update</code>) sẽ nhận bản này.",
                    parse_mode=HTML)
            except Exception:
                pass
        return
    if BOT_OBJ is None:
        return
    text = ("📝 <b>Repo có thay đổi</b> — chưa push.\n"
            f"• {esc(stat['text'])}\n"
            "Duyệt bằng nút bên dưới; ↩️ đưa repo về trước lượt sửa này.")
    try:
        await BOT_OBJ.send_message(chat_id, text, parse_mode=HTML,
                                   reply_markup=review_markup(chat_id))
    except Exception as e:
        log.warning("Không gửi được thông báo diff: %s", oneline(str(e), 200))


async def run_agent(chat_id: int, prompt: str, retries: int = 1) -> tuple:
    """Trả về (ok, text).
    Luôn gửi prompt qua stdin + `--format json` để theo dõi tiến độ và tránh giới
    hạn độ dài dòng lệnh Windows (prompt kèm báo cáo ảnh có thể rất dài).
    Hết hạn mức model chính → tự chuyển sang Gemini Web2API (nếu bật)."""
    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)          # không để agent nhìn thấy token
    env.update(NO_COLOR="1", TERM="dumb", PWD=str(WORKSPACE), AISTV_CHAT_ID=str(chat_id),
               AISTV_DIR=str(Path(__file__).resolve().parent))
    _repo = repo_dir()
    if _repo:
        env["AISTV_REPO"] = str(_repo)
    if web2api is not None:
        try:
            env.setdefault("WEB2API_API_KEY", web2api.api_key())
            env.setdefault("WEB2API_URL", web2api.base_url())
        except Exception:
            pass
    models = agent_model_chain()
    err_text = ""
    for index, model in enumerate(models):
        attempts = (retries if index == 0 else 0) + 1
        for attempt in range(attempts):
            try:
                ok, text, tools_ran = await _run_opencode_once(chat_id, prompt, env, model)
            except asyncio.TimeoutError:
                return False, (f"⏱ Yêu cầu vượt quá {AGENT_TIMEOUT} giây nên đã bị dừng. "
                               "Hãy chia nhỏ yêu cầu rồi thử lại.")
            if chat_id in CANCELLED:
                CANCELLED.discard(chat_id)
                return False, "🛑 Đã huỷ tác vụ."
            if ok:
                if index > 0:
                    log.info("Đã trả lời bằng model dự phòng: %s", model)
                asyncio.create_task(_autopush_after_agent(chat_id))
                return True, text
            err_text = text
            quota = _is_quota_error(err_text)
            server = (not quota) and _is_server_error(err_text)
            # Model dự phòng mà OpenCode báo lỗi nội bộ (500/UnknownError) → gọi
            # thẳng Web2API. Chỉ làm khi chưa có tool nào chạy để tránh trùng tác dụng.
            if model.startswith("web2api/") and not tools_ran:
                direct_ok, direct_text = await _run_web2api_direct(prompt, model)
                if direct_ok:
                    log.info("Đã trả lời bằng Web2API trực tiếp: %s", model)
                    return True, direct_text
                log.warning("Web2API trực tiếp cũng lỗi (%s): %s", model, direct_text[-300:])
                err_text = direct_text
                quota = _is_quota_error(err_text)
                server = (not quota) and _is_server_error(err_text)
            if not quota and not server:
                if attempt + 1 < attempts:
                    continue
                return False, _agent_failure(err_text)
            # Hết hạn mức / lỗi server: chỉ chuyển model khi chưa chạy tool nào (tránh trùng tác dụng).
            if tools_ran:
                return False, _agent_failure(err_text, quota=quota, tools=True, server=server)
            if index + 1 >= len(models):
                return False, _agent_failure(err_text, quota=quota, server=server)
            if web2api is not None:
                try:
                    await asyncio.to_thread(web2api.ensure_server)
                except Exception:
                    pass
            log.warning("Lỗi model ở %s (%s) → chuyển sang %s", model,
                        "hết hạn mức" if quota else "server", models[index + 1])
            break
    return False, _agent_failure(err_text, quota=True)


_SKIP_DIRS = {"memory", "skills", ".agents", ".cursor", "inbox", "node_modules", "__pycache__"}
_SYSTEM_FILES = {"SOUL.md", "AGENTS.md", "MEMORY.md", "opencode.json"}


def snapshot() -> dict:
    snap = {}
    for root, dirs, files in os.walk(WORKSPACE):
        rel_root = Path(root).relative_to(WORKSPACE)
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in _SKIP_DIRS and d != "__pycache__"]
        for fn in files:
            rel = (rel_root / fn).as_posix()
            if fn.startswith(".") or rel in _SYSTEM_FILES:
                continue
            try:
                st = (Path(root) / fn).stat()
            except OSError:
                continue
            sig = (st.st_mtime_ns, st.st_size)
            if st.st_size <= 2 * 1024 * 1024:                 # bắt cả trường hợp sửa cùng kích thước, cùng tick
                try:
                    sig += (hashlib.blake2b((Path(root) / fn).read_bytes(), digest_size=8).hexdigest(),)
                except OSError:
                    pass
            snap[rel] = sig
    return snap


# ════════════════════════════════════════════════════════════════════
# 6. ĐỊNH DẠNG ĐẸP: MARKDOWN → HTML TELEGRAM, CHIA TIN NHẮN AN TOÀN
# ════════════════════════════════════════════════════════════════════
_FENCE = re.compile(r"```[ \t]*([\w+#.\-]*)[ \t]*\n(.*?)\n?```", re.S)
_TABLE = re.compile(r"(?:^[ \t]*\|.*\|[ \t]*(?:\n|$)){2,}", re.M)
_ICODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")

# LaTeX → Unicode: Telegram không render LaTeX nên phải đổi trước khi gửi.
_MATH_SYMBOLS = {
    "triangle": "△", "vartriangle": "△", "Delta": "Δ", "square": "□",
    "parallel": "∥", "nparallel": "∦", "perp": "⊥", "angle": "∠",
    "measuredangle": "∡", "equiv": "≡", "cong": "≅", "approx": "≈",
    "sim": "∼", "simeq": "≃", "neq": "≠", "ne": "≠",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ll": "≪", "gg": "≫",
    "pm": "±", "mp": "∓", "times": "×", "cdot": "·", "div": "÷",
    "Rightarrow": "⇒", "rightarrow": "→", "to": "→", "longrightarrow": "⟶",
    "Leftarrow": "⇐", "leftarrow": "←", "gets": "←",
    "Leftrightarrow": "⇔", "leftrightarrow": "↔",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩",
    "emptyset": "∅", "varnothing": "∅", "forall": "∀", "exists": "∃",
    "infty": "∞", "partial": "∂", "nabla": "∇",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮",
    "therefore": "∴", "because": "∵",
    "dots": "…", "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "circ": "∘", "degree": "°", "prime": "′",
    "langle": "⟨", "rangle": "⟩", "mid": "|", "vert": "|", "Vert": "‖",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "omicron": "ο", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_SUP = dict(zip("0123456789+-=()nix", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣ"))
_SUB = dict(zip("0123456789+-=()aeoxhklmnpst",
                "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ"))
_FRAC_UNICODE = {"1/2": "½", "1/3": "⅓", "2/3": "⅔", "1/4": "¼",
                 "3/4": "¾", "1/5": "⅕", "1/8": "⅛"}


def _math_chars(text: str, table: dict) -> str:
    text = text.strip()
    if text and all(ch in table for ch in text):
        return "".join(table[ch] for ch in text)
    return ""


def _sup_text(text: str) -> str:
    text = text.strip()
    if text in (r"\circ", r"\degree"):
        return "°"
    mapped = _math_chars(text, _SUP)
    return mapped or ("^" + (text if len(text) == 1 else f"({text})"))


def _sub_text(text: str) -> str:
    text = text.strip()
    mapped = _math_chars(text, _SUB)
    return mapped or ("_" + (text if len(text) == 1 else f"({text})"))


def _frac_text(num: str, den: str) -> str:
    num, den = num.strip(), den.strip()
    special = _FRAC_UNICODE.get(f"{num}/{den}")
    if special:
        return special

    def wrap(part):
        return part if re.fullmatch(r"[\w.]+", part) else f"({part})"

    return f"{wrap(num)}/{wrap(den)}"


def latex_to_unicode(src: str) -> str:
    """Đổi công thức LaTeX đơn giản sang ký tự Unicode Telegram đọc được."""
    s = str(src or "").replace("\r", " ")
    for raw, token in ((r"\{", "\x01"), (r"\}", "\x02"), (r"\%", "\x03"),
                       (r"\&", "\x04"), (r"\#", "\x05"), (r"\_", "\x06"),
                       (r"\$", "\x07"), (r"\lbrace", "\x01"), (r"\rbrace", "\x02")):
        s = s.replace(raw, token)

    s = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", s)
    s = s.replace("&", " ")
    s = re.sub(r"\\(?:quad|qquad|;|:|,|!)", " ", s)
    s = s.replace("\\ ", " ").replace("~", " ")
    s = s.replace("\\\\", "\n")

    s = re.sub(r"\\dfrac|\\tfrac|\\frac", r"\\frac", s)
    for _ in range(3):
        s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}",
                   lambda m: _frac_text(m.group(1), m.group(2)), s)
    s = re.sub(r"\\sqrt\s*\[([^\]]*)\]\s*\{([^{}]*)\}",
               lambda m: _sup_text(m.group(1)) + "√(" + m.group(2).strip() + ")", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}",
               lambda m: "√" + (m.group(1).strip()
                                if re.fullmatch(r"[\w.]+", m.group(1).strip())
                                else "(" + m.group(1).strip() + ")"), s)
    s = re.sub(r"\\sqrt\s*([A-Za-z0-9])", r"√\1", s)

    s = re.sub(r"\^\s*\{([^{}]*)\}", lambda m: _sup_text(m.group(1)), s)
    s = re.sub(r"\^\s*(?:\\circ|\\degree)\b", "°", s)
    s = re.sub(r"\^\s*([0-9nix+\-=()])", lambda m: _SUP.get(m.group(1), m.group(0)), s)
    s = re.sub(r"_\s*\{([^{}]*)\}", lambda m: _sub_text(m.group(1)), s)
    s = re.sub(r"_\s*([A-Za-z0-9])", lambda m: _SUB.get(m.group(1), m.group(0)), s)

    s = re.sub(r"\\(?:widehat|hat)\s*\{([^{}]*)\}",
               lambda m: "".join(ch + "\u0302" for ch in m.group(1).strip()), s)
    s = re.sub(r"\\(?:overline|bar)\s*\{([^{}]*)\}",
               lambda m: "".join(ch + "\u0305" for ch in m.group(1).strip()), s)
    s = re.sub(r"\\(?:overrightarrow|vec)\s*\{([^{}]*)\}",
               lambda m: "".join(ch + "\u20d7" for ch in m.group(1).strip()), s)
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit|mathsf|operatorname|mbox)\s*\{([^{}]*)\}",
               r"\1", s)
    s = re.sub(r"\\(?:left|right|displaystyle|textstyle)\b", "", s)

    s = re.sub(r"\\(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh"
               r"|log|ln|lg|lim|max|min|det|gcd|mod)\b", r"\1", s)
    s = re.sub(r"\\mathbb\s*\{([^{}]*)\}",
               lambda m: {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ",
                          "C": "ℂ", "P": "ℙ"}.get(m.group(1).strip(), m.group(1).strip()), s)
    s = re.sub(r"\\([A-Za-z]+)", lambda m: _MATH_SYMBOLS.get(m.group(1), m.group(1)), s)
    s = re.sub(r"([△□∠∡])\s+", r"\1", s)      # △ABC, ∠A — không dính khoảng trắng thừa

    for _ in range(3):
        s = re.sub(r"\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    s = re.sub(r"\n{2,}", "\n", s).strip()
    for token, raw in (("\x01", "{"), ("\x02", "}"), ("\x03", "%"), ("\x04", "&"),
                       ("\x05", "#"), ("\x06", "_"), ("\x07", "$")):
        s = s.replace(token, raw)
    return unicodedata.normalize("NFC", s)


_MATH_BLOCK = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
_MATH_INLINE = re.compile(r"(?<![\\$])\$(?!\$)([^$\n]+?)\$(?!\$)|\\\(([^\n]+?)\\\)")
_MATH_HINT = re.compile(r"[\\^_=+<>/±×÷≤≥≠≈√∠△∥⊥⇒⇔]")


def _looks_math(text: str) -> bool:
    """Phân biệt $x = 1$ với giá tiền kiểu $5 và $7."""
    text = text.strip()
    if not text:
        return False
    return bool(_MATH_HINT.search(text) or re.fullmatch(r"[A-Za-z0-9,.]+", text))


def md_to_tg_html(md: str) -> str:
    stash: list = []

    def keep(s: str) -> str:
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    def fence(m):
        lang = m.group(1)
        cls = f' class="language-{esc(lang)}"' if lang else ""
        return keep(f"<pre><code{cls}>{esc(m.group(2))}</code></pre>")

    def link(m):
        url = esc(m.group(2)).replace('"', "%22")
        return keep(f'<a href="{url}">{esc(m.group(1))}</a>')

    def math(m, dollar=False):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        if "\x00" in raw:                 # công thức chứa code/placeholder — để nguyên, không phá
            return m.group(0)
        if dollar and m.group(1) is not None and not _looks_math(raw):
            return m.group(0)             # "$5 và $7" là giá tiền, không phải công thức
        return keep(esc(latex_to_unicode(raw)))

    md = _FENCE.sub(fence, md)
    md = _TABLE.sub(lambda m: keep(f"<pre>{esc(m.group(0).strip())}</pre>"), md)
    md = _ICODE.sub(lambda m: keep(f"<code>{esc(m.group(1))}</code>"), md)
    md = _LINK.sub(link, md)              # cất link trước để _ và * trong URL không bị biến thành nghiêng/đậm
    md = _MATH_BLOCK.sub(math, md)        # $$…$$ / \[…\]
    md = _MATH_INLINE.sub(lambda m: math(m, dollar=True), md)   # $…$ / \(…\)
    md = md.replace("\\$", "$")
    md = esc(md)

    md = re.sub(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", "──────────", md, flags=re.M)
    md = re.sub(r"^([ \t]*)[-*+][ \t]+", r"\1• ", md, flags=re.M)
    md = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", r"<b>\1</b>", md, flags=re.M)
    md = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", md)
    md = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<b>\1</b>", md)
    md = re.sub(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])", r"<i>\1</i>", md)
    md = re.sub(r"(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])", r"<i>\1</i>", md)
    md = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", md)
    md = re.sub(r"^&gt;[ \t]?(.*)$", r"▎ <i>\1</i>", md, flags=re.M)

    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], md)


def split_markdown(text: str, limit: int = SPLIT_LIMIT) -> list:
    """Chia theo đoạn văn; luôn đóng/mở lại khối code để không vỡ định dạng."""
    text = text.strip()
    if not text:
        return []
    chunks, cur, size, fence = [], [], 0, None

    def flush():
        nonlocal cur, size
        if not any(l.strip() for l in cur):
            cur, size = [], 0
            return
        body = "\n".join(cur).rstrip()
        if fence is not None:
            body += "\n```"
        chunks.append(body)
        cur = [fence] if fence is not None else []
        size = sum(len(l) + 1 for l in cur)

    for line in text.split("\n"):
        while len(line) > limit:
            piece, line = line[:limit], line[limit:]
            if size + len(piece) + 1 > limit:
                flush()
            cur.append(piece)
            size += len(piece) + 1
            flush()
        if fence is None and not line.strip() and size > limit * 0.7:
            flush()
            continue
        if size + len(line) + 1 > limit:
            flush()
        cur.append(line)
        size += len(line) + 1
        if line.lstrip().startswith("```"):
            fence = None if fence is not None else line.strip()
    flush()
    return chunks


NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
HTML = ParseMode.HTML


async def _reply(message, body: str, fallback: str, **kw):
    for _ in range(3):
        try:
            try:
                return await message.reply_text(body, parse_mode=HTML, link_preview_options=NO_PREVIEW, **kw)
            except BadRequest:
                return await message.reply_text(fallback[:4000], link_preview_options=NO_PREVIEW, **kw)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)


async def send_rich(message, text: str, footer: str = "", markup=None) -> None:
    chunks = split_markdown(text) or ["(trống)"]
    for i, ch in enumerate(chunks):
        last = i == len(chunks) - 1
        body = md_to_tg_html(ch)
        if last and footer:
            body += "\n\n" + footer
        if len(body) > 4096:               # HTML phình quá giới hạn → gửi bản chữ thường thay vì cắt giữa thẻ
            await message.reply_text(ch[:4000], link_preview_options=NO_PREVIEW,
                                     reply_markup=markup if last else None)
            continue
        await _reply(message, body, ch, reply_markup=markup if last else None)
        if not last:
            await asyncio.sleep(0.4)


async def send_thinking(message, chat_id: int) -> None:
    """Gửi phần reasoning của model dưới dạng blockquote mở rộng được."""
    text = _thinking_text(chat_id)
    if not text:
        return
    total = len(text)
    shown = text if total <= 3500 else text[:3500] + "\n…"
    body = (f"💭 <b>Suy nghĩ</b> <i>({total} ký tự)</i>\n"
            f"<blockquote expandable>{esc(shown)}</blockquote>")
    try:
        await message.reply_text(body, parse_mode=HTML, link_preview_options=NO_PREVIEW)
    except BadRequest:
        try:
            await message.reply_text(f"💭 Suy nghĩ:\n{shown}", link_preview_options=NO_PREVIEW)
        except Exception:
            pass
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
    except Exception as e:
        log.warning("Không gửi được thinking: %s", e)


# ════════════════════════════════════════════════════════════════════
# 7. LÕI XỬ LÝ YÊU CẦU
# ════════════════════════════════════════════════════════════════════
ANSWER_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Viết lại", callback_data="regen"),
                                   InlineKeyboardButton("🧹 Chat mới", callback_data="new")]])
STOP_KB = InlineKeyboardMarkup([[InlineKeyboardButton("⛔ Dừng", callback_data="stop")]])
MENU_KB = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Trạng thái", callback_data="status"),
                                 InlineKeyboardButton("🧩 Skills", callback_data="skills"),
                                 InlineKeyboardButton("🧠 Trí nhớ", callback_data="memory")],
                                [InlineKeyboardButton("🧹 Chat mới", callback_data="new")]])


async def _ticker(bot, chat_id: int, status, started: float, stop: asyncio.Event) -> None:
    frames, i, last = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", 0, ""
    tick = max(0.3, PROGRESS_TICK)
    edit_every = max(3.0, tick)        # sửa tin nhắn dày ~1/s sẽ bị Telegram 429
    typing_at = 0.0
    next_edit = 0.0
    while not stop.is_set():
        now = time.monotonic()
        # "đang nhập" ~5s/lần, chạy độc lập với nhịp sửa tin nhắn: khi bị 429
        # chỉ hoãn lần sửa kế tiếp, không làm tắt luôn hiệu ứng đang nhập.
        if now - typing_at >= 4.5:
            typing_at = now
            try:
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass
        if now >= next_edit:
            body = _render_status(chat_id, started, frames[i % len(frames)])
            if body != last:
                try:
                    await status.edit_text(body, parse_mode=HTML, link_preview_options=NO_PREVIEW)
                    last = body
                    next_edit = time.monotonic() + edit_every
                except RetryAfter as e:
                    next_edit = time.monotonic() + min(30.0, e.retry_after + 1)
                except BadRequest:
                    last = body
                    next_edit = time.monotonic() + edit_every
                except Exception:
                    next_edit = time.monotonic() + edit_every
            else:
                next_edit = time.monotonic() + tick
        i += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=tick)
        except asyncio.TimeoutError:
            pass


async def _finish_status(status, chat_id: int, started: float, ok: bool) -> None:
    """Chốt tin nhắn tiến độ; ở chế độ gọn thì xoá hẳn để nhường chỗ cho câu trả lời."""
    rows = _status_rows(chat_id)
    if not STATE.get("show_activity", False) or not rows:
        try:
            await status.delete()
        except Exception:
            pass
        ACTIVITY.pop(chat_id, None)
        LIVE.pop(chat_id, None)
        return
    head = (f"✅ <b>Hoàn tất</b> · {time.monotonic() - started:.1f}s" if ok
            else f"⚠️ <b>Dừng lại</b> · {time.monotonic() - started:.1f}s")
    body = "\n".join([head, "", "<b>Việc đã làm</b>"] + rows)
    if len(body) > 3900:
        body = body[:3890] + "\n…"
    try:
        await status.edit_text(body, parse_mode=HTML, link_preview_options=NO_PREVIEW)
    except Exception:
        try:
            await status.delete()
        except Exception:
            pass
    try:
        await status.edit_reply_markup(reply_markup=None)   # bỏ nút Dừng
    except Exception:
        pass
    ACTIVITY.pop(chat_id, None)
    LIVE.pop(chat_id, None)


async def send_new_files(message, before: dict) -> None:
    after = snapshot()
    # Không gửi lại artifact nội bộ: báo cáo watch/, ảnh đã gửi riêng ở generated/.
    changed = [k for k, v in after.items()
               if before.get(k) != v and 0 < v[1] < 45 * 1024 * 1024
               and not k.startswith(("watch/", "generated/"))]
    changed.sort(key=lambda k: (k not in before, k))          # file sửa trước, file tạo mới sau
    for rel in changed[:10]:
        try:
            with (WORKSPACE / rel).open("rb") as fh:
                mark = "✏️ Đã sửa" if rel in before else "🆕 Tạo mới"
                await message.reply_document(fh, filename=Path(rel).name, caption=f"{mark}: {rel}")
        except Exception as e:
            log.warning("Không gửi được %s: %s", rel, e)
    if len(changed) > 10:
        await message.reply_text(f"📂 Còn {len(changed) - 10} file khác — dùng /files và /get <tên> để tải.")


async def respond(message, context, chat_id: int, text: str, skill: Optional[tuple] = None,
                  quoted_msg=None, store_text: Optional[str] = None) -> bool:
    quote, quote_label = reply_context(quoted_msg)
    lock = LOCKS[chat_id]
    if lock.locked():
        await message.reply_text("⏳ Tôi đang xử lý yêu cầu trước — yêu cầu này đã được xếp hàng.")
    async with lock:
        async with SEM:
            await ensure_history(chat_id)        # máy mới → lấy lại hội thoại từ cloud
            status = await message.reply_text("🧠 <i>Đang làm việc…</i>", parse_mode=HTML,
                                              reply_markup=STOP_KB)
            started = time.monotonic()
            prompt = build_prompt(chat_id, text, skill, quote)
            prompt, hr_before, hr_after = await _headroom_prompt(prompt)
            hr_saved = max(0, hr_before - hr_after)
            if hr_saved:
                log.info("Headroom nén ngữ cảnh: %s → %s token (−%d%%)", hr_before, hr_after,
                         round(hr_saved * 100 / hr_before))
            before = snapshot()
            # Chụp repo trước khi agent sửa để ↩️ hoàn tác được (chỉ tốn khi repo đang dở).
            if planner is not None and repo_dir():
                await asyncio.to_thread(
                    make_checkpoint, chat_id, f"trước khi agent sửa: {oneline(text, 80)}")
            stop = asyncio.Event()
            ticker = asyncio.create_task(_ticker(context.bot, chat_id, status, started, stop))
            try:
                ok, answer = await run_agent(chat_id, prompt)
            finally:
                stop.set()
                await ticker
            await _finish_status(status, chat_id, started, ok)
            if ok:
                stored = store_text or ((quote_label + " " + text) if quote_label else text)
                append_history(chat_id, "user", stored)
                append_history(chat_id, "assistant", answer[:6000])
                log_daily(stored, answer)
                maybe_schedule_summary(chat_id)
            foot = f"⏱ {time.monotonic() - started:.1f}s · {esc(STATE['model'].split('/')[-1])}"
            tok_line = _token_footer(chat_id, saved=hr_saved)
            if tok_line:
                foot += f" · {tok_line}"
            footer = f"<i>{foot}</i>"
            await send_rich(message, answer, footer if ok else "", ANSWER_KB if ok else None)
            if ok:
                await send_new_files(message, before)
            THINKING.pop(chat_id, None)
            THINK_TOKENS.pop(chat_id, None)
            TOKEN_USAGE.pop(chat_id, None)
            LIVE.pop(chat_id, None)
            return ok


# ════════════════════════════════════════════════════════════════════
# 7b. KẾ HOẠCH TỰ TRỊ · CỔNG DUYỆT · HOÀN TÁC
# ════════════════════════════════════════════════════════════════════
def plan_keyboard(plan: dict) -> InlineKeyboardMarkup:
    pid = plan.get("id") or ""
    st = plan.get("status") or "draft"
    wb = plan.get("work_branch") or ""
    dropped = bool(plan.get("work_dropped"))
    rows = []
    if st in ("draft", "failed", "cancelled"):
        rows.append([InlineKeyboardButton("▶️ Thực thi", callback_data=f"plan:run:{pid}"),
                     InlineKeyboardButton("✏️ Lập lại", callback_data=f"plan:edit:{pid}")])
    if st == "running":
        rows.append([InlineKeyboardButton("▶️ Tiếp tục", callback_data=f"plan:run:{pid}"),
                     InlineKeyboardButton("⛔ Dừng", callback_data="stop")])
    if wb and not dropped and st in ("done", "failed", "cancelled"):
        act = []
        if plan.get("work_error") or not plan.get("work_pushed"):
            act.append(InlineKeyboardButton("⬆️ Đẩy nhánh", callback_data=f"work:push:{pid}"))
        if not plan.get("work_merged"):
            act.append(InlineKeyboardButton("🔀 Gộp vào main", callback_data=f"work:merge:{pid}"))
        if act:
            rows.append(act)
        rows.append([InlineKeyboardButton("🗑 Xoá nhánh", callback_data=f"work:drop:{pid}")])
    elif st in ("done", "failed") and plan.get("diff") and plan["diff"] != "không có thay đổi":
        rows.append([InlineKeyboardButton("⬆️ Push", callback_data=f"plan:push:{pid}"),
                     InlineKeyboardButton("↩️ Hoàn tác", callback_data=f"plan:undo:{pid}")])
    elif plan.get("checkpoint") and st in ("done", "failed", "cancelled"):
        rows.append([InlineKeyboardButton("↩️ Hoàn tác", callback_data=f"plan:undo:{pid}")])
    rows.append([InlineKeyboardButton("🔄 Xem", callback_data=f"plan:view:{pid}"),
                 InlineKeyboardButton("🗂 Danh sách", callback_data="plan:list")])
    return InlineKeyboardMarkup(rows)


def plans_list_text() -> tuple:
    items = planner.list_plans(HOME, 8) if planner else []
    if not items:
        return ("🗂 Chưa có kế hoạch nào.\nDùng <code>/plan &lt;yêu cầu&gt;</code> để bot "
                "chia việc thành bước rồi tự chạy."), None
    lines = ["🗂 <b>KẾ HOẠCH GẦN ĐÂY</b>"]
    rows = []
    for p in items:
        done, total = planner.progress(p)
        st = planner.PLAN_STATUS.get(p.get("status") or "", p.get("status") or "")
        mark = "🌿 " if p.get("work_branch") and not p.get("work_dropped") else ""
        lines.append(f"• {mark}{esc(oneline(p.get('title') or '?', 60))} — {done}/{total} "
                     f"bước · {esc(st)}")
        rows.append([InlineKeyboardButton(
            oneline(p.get("title") or p["id"], 30), callback_data=f"plan:view:{p['id']}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _plan_edit(msg, plan: dict, note: str = "") -> None:
    text = planner.render_plan(plan)
    if note:
        text += f"\n\n<i>{esc(note)}</i>"
    try:
        await msg.edit_text(text[:4000], parse_mode=HTML, reply_markup=STOP_KB)
    except Exception:
        pass


# ── Nhánh công việc: mỗi bước commit + push, máy khác làm tiếp ──────
async def _work_begin(rd, plan: dict) -> None:
    """Đưa kế hoạch dài sang nhánh riêng (nếu repo sạch và đủ bước)."""
    if not (workmod and rd and planner):
        return
    if len(plan.get("steps") or []) < WORK_MIN_STEPS:
        return
    slug = current_repo_slug() or repo_remote_slug()
    if slug:
        try:
            await asyncio.to_thread(_gh_set_origin, rd, slug)
        except Exception as e:  # noqa
            log.warning("Không đặt được origin trước khi tạo nhánh: %s", oneline(str(e), 160))
    try:
        prep = await asyncio.to_thread(workmod.prepare, rd, plan)
    except Exception as e:  # noqa
        plan["work_error"] = "Không tạo được nhánh: " + oneline(str(e), 240)
        return
    if not prep.get("ok"):
        plan["work_error"] = prep.get("error") or "không tạo được nhánh công việc"
        if plan.get("work_branch"):
            raise RuntimeError("Không mở lại được nhánh công việc: "
                               + oneline(plan["work_error"], 300))
        return
    plan["work_branch"] = prep.get("branch") or ""
    plan["work_base"] = prep.get("base") or ""
    plan["work_base_sha"] = prep.get("base_sha") or ""
    plan["work_resumed"] = bool(prep.get("resumed"))
    plan["work_error"] = ""
    plan["status"] = "running"
    planner.save_plan(HOME, plan)
    await _work_sync(rd, plan, note="bắt đầu kế hoạch")


async def _work_sync(rd, plan: dict, step=None, note: str = "") -> None:
    """Commit + push trạng thái hiện tại lên nhánh công việc (lỗi không chặn)."""
    if not (workmod and rd and plan.get("work_branch")):
        return
    try:
        cur = await asyncio.to_thread(workmod.current_branch, rd)
        if cur != plan.get("work_branch"):
            return                      # đã trả về nhánh chính — không ghi lỗi giả
        res = await asyncio.to_thread(workmod.commit_step, rd, plan, step, note)
    except Exception as e:  # noqa
        plan["work_error"] = "Đồng bộ nhánh lỗi: " + oneline(str(e), 240)
        return
    if not res.get("ok"):
        plan["work_error"] = res.get("error") or "không commit được lên nhánh"
        return
    plan["work_pushed"] = bool(res.get("pushed"))
    plan["work_commit"] = res.get("sha") or plan.get("work_commit") or ""
    plan["work_error"] = res.get("error") or ""


async def _work_finish(rd, plan: dict) -> None:
    """Chốt state cuối, đo thay đổi so với nhánh chính rồi trả repo về nhánh cũ."""
    if not (workmod and rd and plan.get("work_branch")):
        return
    try:
        await _work_sync(rd, plan, note="kết thúc kế hoạch")
        plan["diff"] = await asyncio.to_thread(workmod.diff_from_base, rd, plan)
        plan["work_commits"] = await asyncio.to_thread(workmod.commit_count, rd, plan)
        ok, detail = await asyncio.to_thread(
            workmod.return_to_base, rd, plan.get("work_base") or "")
        plan["work_back"] = bool(ok)
        if not ok:
            plan["work_error"] = detail
    except Exception as e:  # noqa
        plan["work_error"] = "Kết thúc nhánh lỗi: " + oneline(str(e), 240)


async def create_plan(chat_id: int, request: str, msg) -> None:
    if planner is None:
        await msg.reply_text("❌ Thiếu <code>aistv_planner.py</code> — chạy /update.",
                             parse_mode=HTML)
        return
    status = await msg.reply_text("🧭 <i>Đang chia việc thành các bước…</i>",
                                  parse_mode=HTML)
    rd = repo_dir()
    prompt = planner.plan_prompt(request, repo=str(rd or ""), workspace=str(WORKSPACE))
    ok, answer = await run_agent(chat_id, prompt)
    if not ok:
        await status.edit_text("❌ Không lập được kế hoạch:\n" + esc(oneline(answer, 700)),
                               parse_mode=HTML)
        return
    obj, err = planner.parse_plan(answer)
    if err:
        await status.edit_text(
            "❌ " + esc(err) + "\n\n<pre>" + esc(oneline(answer, 1500)) + "</pre>\n"
            "Thử lại với yêu cầu cụ thể hơn.", parse_mode=HTML)
        return
    plan = planner.new_plan(HOME, chat_id, obj.get("title") or oneline(request, 80),
                            request, obj["steps"])
    text = planner.render_plan(plan) + (
        "\n\n▶️ Bấm <b>Thực thi</b> để bot tự làm từng bước (có checkpoint để hoàn tác).\n"
        "Bước nào lỗi, bot tự sửa tối đa 2 lần rồi báo rõ.")
    await status.edit_text(text[:4000], parse_mode=HTML,
                           reply_markup=plan_keyboard(plan))


async def run_plan(chat_id: int, plan_id: str) -> None:
    plan = planner.load_plan(HOME, plan_id)
    if not plan:
        if BOT_OBJ:
            await BOT_OBJ.send_message(chat_id, "❌ Không tìm thấy kế hoạch này.")
        return
    if chat_id in PLAN_BUSY:
        if BOT_OBJ:
            await BOT_OBJ.send_message(chat_id, "⏳ Đang chạy một kế hoạch khác.")
        return
    PLAN_BUSY.add(chat_id)
    PLAN_CANCEL.discard(chat_id)
    msg = None
    rd = None
    try:
        rd = repo_dir()
        cp_ok = bool(plan.get("checkpoint")
                     and planner.load_checkpoint(HOME, plan["checkpoint"]))
        if rd and not cp_ok:
            plan["checkpoint"] = ""
            meta, _err = await asyncio.to_thread(
                planner.create_checkpoint, HOME, rd,
                f"plan {plan['id']}: {plan.get('title') or ''}")
            if meta:
                plan["checkpoint"] = meta["id"]
                LAST_CHECKPOINT[chat_id] = meta["id"]
        if rd:
            await _work_begin(rd, plan)          # kế hoạch dài → nhánh riêng
        plan["status"] = "running"
        planner.save_plan(HOME, plan)
        msg = await BOT_OBJ.send_message(chat_id, planner.render_plan(plan)[:4000],
                                         parse_mode=HTML, reply_markup=STOP_KB)
        total = len(plan.get("steps") or [])
        for step in plan.get("steps") or []:
            if step.get("status") == "done":
                continue
            if chat_id in PLAN_CANCEL:
                plan["status"] = "cancelled"
                break
            planner.set_step(plan, step["n"], status="running", started=time.time(),
                             attempts=0)
            planner.save_plan(HOME, plan)
            await _plan_edit(msg, plan, f"▶️ Bước {step['n']}/{total}: {step['title']}")
            ok = False
            answer = ""
            hint = ""
            stopped = False
            for attempt in range(1, planner.STEP_ATTEMPTS_MAX + 1):
                if chat_id in PLAN_CANCEL:
                    stopped = True
                    break
                step["attempts"] = attempt
                planner.save_plan(HOME, plan)
                prompt = planner.step_prompt(
                    plan, step, repo=str(rd or ""), workspace=str(WORKSPACE),
                    verify_hint=hint)
                ok, answer = await run_agent(chat_id, prompt)
                if chat_id in PLAN_CANCEL or (not ok and str(answer).startswith("🛑")):
                    stopped = True
                    break
                if not ok:
                    hint = "Agent báo lỗi:\n" + str(answer)[:900]
                    step["last_verify"] = oneline(answer, 400)
                    planner.save_plan(HOME, plan)
                    await _plan_edit(msg, plan, f"⚠️ Bước {step['n']} lỗi — thử lại "
                                                f"({attempt}/{planner.STEP_ATTEMPTS_MAX})…")
                    continue
                ver = (await asyncio.to_thread(planner.verify_repo, rd, True)
                       if rd else {"ok": True, "summary": "không có repo để kiểm chứng"})
                if ver["ok"]:
                    step["status"] = "done"
                    step["result"] = oneline(answer, 320)
                    step["last_verify"] = oneline(ver.get("summary") or "", 400)
                    step["finished"] = time.time()
                    planner.save_plan(HOME, plan)
                    break
                hint = "Kiểm chứng FAIL:\n" + (ver.get("summary") or "")
                step["last_verify"] = oneline(ver.get("summary") or "", 400)
                planner.save_plan(HOME, plan)
                await _plan_edit(msg, plan, f"🧪 Bước {step['n']} chưa PASS — tự sửa "
                                            f"({attempt}/{planner.STEP_ATTEMPTS_MAX})…")
            if stopped:
                plan["status"] = "cancelled"
                planner.set_step(plan, step["n"], status="skipped", finished=time.time())
                planner.save_plan(HOME, plan)
                await _work_sync(rd, plan, step, note="dừng kế hoạch")
                break
            if step.get("status") != "done":
                plan["status"] = "failed"
                planner.set_step(plan, step["n"], status="failed",
                                 finished=time.time(),
                                 last_verify=oneline(hint or answer, 400))
                planner.save_plan(HOME, plan)
                await _work_sync(rd, plan, step, note="bước lỗi")
                break
            await _work_sync(rd, plan, step)
            await _plan_edit(msg, plan, f"✅ Xong bước {step['n']}/{total}")
        ver = (await asyncio.to_thread(planner.verify_repo, rd, False)
               if rd else {"ok": True, "summary": "không có repo để kiểm chứng"})
        plan["verify"] = {"ok": bool(ver.get("ok")), "summary": oneline(ver.get("summary"), 800)}
        if plan["status"] == "running":
            plan["status"] = "done" if ver.get("ok") else "failed"
        if rd and not plan.get("work_branch"):
            stat = await asyncio.to_thread(planner.diff_stat, rd)
            plan["diff"] = stat.get("text") or ""
        done, total = planner.progress(plan)
        plan["report"] = (f"Bot tự chạy {done}/{total} bước; kiểm chứng "
                          f"{'PASS' if ver.get('ok') else 'FAIL'}.")
        planner.save_plan(HOME, plan)
        if rd and plan.get("work_branch"):
            await _work_finish(rd, plan)         # chốt nhánh + trả repo về nhánh cũ
            planner.save_plan(HOME, plan)
        if msg:
            try:
                await msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await BOT_OBJ.send_message(chat_id, planner.render_report(plan)[:4000],
                                   parse_mode=HTML, reply_markup=plan_keyboard(plan))
        try:
            log_daily(f"/plan {plan.get('title')}",
                      f"{plan['status']} · {plan['report']}")
        except Exception:
            pass
    except Exception as e:  # noqa
        log.exception("Kế hoạch %s lỗi", plan_id)
        plan["status"] = "failed"
        plan["report"] = "Lỗi hệ thống: " + oneline(str(e), 300)
        if rd and plan.get("work_branch"):
            try:
                await _work_sync(rd, plan, note="lỗi hệ thống")
            except Exception:  # noqa
                pass
        try:
            planner.save_plan(HOME, plan)
        except Exception:
            pass
        if BOT_OBJ:
            try:
                await BOT_OBJ.send_message(
                    chat_id, "❌ Kế hoạch dừng vì lỗi:\n" + esc(oneline(str(e), 600)),
                    parse_mode=HTML, reply_markup=plan_keyboard(plan))
            except Exception:
                pass
    finally:
        if workmod and rd and plan.get("work_branch"):
            try:
                await asyncio.to_thread(workmod.return_to_base, rd,
                                        plan.get("work_base") or "")
                planner.save_plan(HOME, plan)
            except Exception:  # noqa
                pass
        PLAN_BUSY.discard(chat_id)
        PLAN_CANCEL.discard(chat_id)


async def push_repo_now() -> str:
    slug = current_repo_slug() or repo_remote_slug()
    if not slug:
        raise RuntimeError("Chưa chọn repo đích — dùng /github repos để chọn.")
    tok = github_token()
    if not tok:
        raise RuntimeError("Chưa kết nối GitHub — dùng /github login.")
    if not await asyncio.to_thread(repo_can_push, slug, tok):
        raise RuntimeError(f"Token không có quyền push vào {slug}.")
    return await asyncio.to_thread(gh_push_code, slug)


async def _q_edit(q, text: str, markup="keep") -> None:
    kwargs = {"parse_mode": HTML}
    if markup != "keep":
        kwargs["reply_markup"] = markup
    try:
        await q.message.edit_text(text[:4000], **kwargs)
    except Exception:
        pass


async def _on_review_button(q, data: str) -> None:
    """Nút ⬆️ Push / ↩️ Hoàn tác / 📄 Xem thay đổi của cổng duyệt."""
    uid = q.from_user.id if q.from_user else 0
    if not is_owner(uid):
        await q.answer("Chỉ chủ bot được duyệt code.", show_alert=True)
        return
    if planner is None:
        await q.answer("Thiếu aistv_planner.py — chạy /update.")
        return
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    cp = parts[2] if len(parts) > 2 else ""
    rd = repo_dir()
    if action == "noop":
        await q.answer()
        return
    if action == "diff":
        await q.answer()
        if not rd:
            await q.message.reply_text("Không tìm thấy repo git.")
            return
        rc, out = await asyncio.to_thread(_git, ["diff", "--stat", "HEAD"], rd)
        rc2, unt = await asyncio.to_thread(
            _git, ["ls-files", "--others", "--exclude-standard"], rd)
        body = (out or "").strip() if rc == 0 else ""
        names = [x for x in (unt or "").splitlines() if x.strip()] if rc2 == 0 else []
        text = "<b>Thay đổi chưa commit</b>\n<pre>" + esc(body[:2500] or "(không có)") + "</pre>"
        if names:
            text += "\n<b>File mới:</b>\n<pre>" + esc("\n".join(names[:20])) + "</pre>"
        await q.message.reply_text(text, parse_mode=HTML)
        return
    if action == "push":
        await q.answer("Đang push…")
        await _q_edit(q, "⬆️ Đang push lên GitHub…", markup=None)
        try:
            out = await push_repo_now()
            await _q_edit(q, "✅ <b>Đã push.</b>\n<pre>" + esc(oneline(out, 1500))
                          + "</pre>\nWindows chạy <code>run.bat</code> để nhận bản mới.")
        except Exception as e:  # noqa
            await _q_edit(q, "❌ Push lỗi: " + esc(oneline(str(e), 600)))
        return
    if action in ("undo", "undo2"):
        if not rd:
            await q.answer("Không tìm thấy repo.", show_alert=True)
            return
        if not cp:
            await q.answer("Không có checkpoint cho lượt này.", show_alert=True)
            return
        if action == "undo":
            await q.answer()
            await _q_edit(
                q,
                "↩️ <b>Hoàn tác?</b>\nMọi thay đổi <b>chưa commit</b> trong repo sẽ mất "
                "(file mới do agent tạo cũng bị xoá). File ignored như <code>.env</code> "
                "được giữ nguyên.",
                markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✔️ Hoàn tác ngay", callback_data=f"up:undo2:{cp}"),
                    InlineKeyboardButton("✖️ Không", callback_data="up:noop")]]))
            return
        await q.answer("Đang hoàn tác…")
        ok, detail = await asyncio.to_thread(planner.restore_checkpoint, HOME, rd, cp)
        await _q_edit(q, ("✅ <b>Đã hoàn tác.</b>\n" if ok else "❌ <b>Không hoàn tác được.</b>\n")
                      + esc(detail), markup=None)
        return
    await q.answer()


async def _on_plan_button(q, data: str) -> None:
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    pid = parts[2] if len(parts) > 2 else ""
    uid = q.from_user.id if q.from_user else 0
    chat_id = q.message.chat_id if q.message else uid
    if planner is None:
        await q.answer("Thiếu aistv_planner.py — chạy /update.")
        return
    if action == "list":
        await q.answer()
        text, markup = plans_list_text()
        await q.message.reply_text(text, parse_mode=HTML, reply_markup=markup)
        return
    plan = planner.load_plan(HOME, pid)
    if not plan:
        await q.answer("Không tìm thấy kế hoạch này.", show_alert=True)
        return
    if action in ("run", "cancel", "edit", "push", "undo", "undo2") and not is_owner(uid):
        await q.answer("Chỉ chủ bot được điều khiển kế hoạch.", show_alert=True)
        return
    if action == "view":
        await q.answer()
        body = (planner.render_report(plan) if plan.get("status") in ("done", "failed", "cancelled")
                else planner.render_plan(plan))
        await q.message.reply_text(body[:4000], parse_mode=HTML,
                                   reply_markup=plan_keyboard(plan))
        return
    if action == "run":
        await q.answer("Bắt đầu…")
        await q.message.reply_text(
            f"▶️ Chạy kế hoạch <b>{esc(oneline(plan.get('title') or '', 90))}</b>.",
            parse_mode=HTML)
        asyncio.create_task(run_plan(chat_id, plan["id"]))
        return
    if action == "edit":
        await q.answer()
        await q.message.reply_text(
            "✏️ Gửi <code>/plan &lt;yêu cầu đã chỉnh&gt;</code> để bot lập kế hoạch mới. "
            "Kế hoạch cũ vẫn được giữ trong danh sách.", parse_mode=HTML)
        return
    if action == "cancel":
        if plan.get("status") == "running":
            PLAN_CANCEL.add(chat_id)
        plan["status"] = "cancelled"
        planner.save_plan(HOME, plan)
        await q.answer("Đã huỷ kế hoạch.")
        await _q_edit(q, planner.render_plan(plan), markup=plan_keyboard(plan))
        return
    if action == "push":
        await q.answer("Đang push…")
        if plan.get("work_branch") and workmod:
            rd = repo_dir()
            res = await asyncio.to_thread(workmod.push_branch, rd, plan) if rd else \
                {"ok": False, "error": "không thấy repo"}
            if res.get("ok"):
                plan["work_pushed"] = True
                plan["work_error"] = ""
                planner.save_plan(HOME, plan)
                await _q_edit(q, "✅ <b>Đã đẩy nhánh công việc lên GitHub.</b>")
            else:
                await _q_edit(q, "❌ Đẩy nhánh lỗi: "
                              + esc(oneline(res.get("error") or "", 600)))
            return
        await _q_edit(q, "⬆️ Đang push lên GitHub…", markup=None)
        try:
            out = await push_repo_now()
            plan["pushed"] = True
            planner.save_plan(HOME, plan)
            await _q_edit(q, "✅ <b>Đã push kế hoạch.</b>\n<pre>" + esc(oneline(out, 1500))
                          + "</pre>")
        except Exception as e:  # noqa
            await _q_edit(q, "❌ Push lỗi: " + esc(oneline(str(e), 600)))
        return
    if action in ("undo", "undo2"):
        cp = plan.get("checkpoint") or ""
        rd = repo_dir()
        if not cp or not rd:
            await q.answer("Kế hoạch này không có checkpoint.", show_alert=True)
            return
        if action == "undo":
            await q.answer()
            await _q_edit(
                q,
                "↩️ <b>Hoàn tác toàn bộ kế hoạch?</b>\nRepo sẽ về đúng trạng thái trước khi "
                "chạy kế hoạch; thay đổi chưa commit sẽ mất.",
                markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✔️ Hoàn tác ngay", callback_data=f"plan:undo2:{pid}"),
                    InlineKeyboardButton("✖️ Không", callback_data="plan:view:" + pid)]]))
            return
        await q.answer("Đang hoàn tác…")
        ok, detail = await asyncio.to_thread(planner.restore_checkpoint, HOME, rd, cp)
        if ok:
            plan["status"] = "cancelled"
            plan["diff"] = ""
            planner.save_plan(HOME, plan)
        await _q_edit(q, ("✅ <b>Đã hoàn tác kế hoạch.</b>\n" if ok
                          else "❌ <b>Không hoàn tác được.</b>\n") + esc(detail))
        return
    await q.answer()


# ────────────────────────────────────────────────────────────────────
# 7c. NHÁNH CÔNG VIỆC · TIẾP TỤC TRÊN MÁY KHÁC
# ────────────────────────────────────────────────────────────────────
def _task_when(t: dict) -> str:
    ts = t.get("updated") or 0
    return time.strftime("%d/%m %H:%M", time.localtime(ts)) if ts else "?"


def _task_line(t: dict) -> str:
    st = t.get("status") or "?"
    label = {"draft": "nháp", "running": "đang chạy", "failed": "lỗi",
             "cancelled": "đã dừng", "done": "xong", "unknown": "?"}.get(st, st)
    return (f"• <b>{esc(oneline(t.get('title') or '?', 90))}</b>\n"
            f"  {t.get('done') or 0}/{t.get('total') or 0} bước · {esc(label)} · "
            f"{_task_when(t)}" + (f" · <code>{esc(t.get('machine') or '')}</code>"
                                  if t.get("machine") else ""))


def _work_list_text(tasks: list) -> tuple:
    if not tasks:
        return ("🌿 <b>CHƯA CÓ NHÁNH CÔNG VIỆC</b>\n"
                "Kế hoạch từ 3 bước trở lên sẽ tự chạy trên nhánh riêng và được "
                "đẩy lên GitHub sau từng bước."), None
    lines = ["🌿 <b>VIỆC ĐANG DỞ TRÊN GITHUB</b>", ""]
    rows = []
    for t in tasks[:8]:
        lines.append(_task_line(t))
        if t.get("id"):
            rows.append([InlineKeyboardButton(
                f"▶️ {oneline(t.get('title') or t['id'], 36)}",
                callback_data=f"work:resume:{t['id']}")])
    if rows:
        lines += ["", "Bấm một việc để làm tiếp từ bước còn dở."]
    return "\n".join(lines), (InlineKeyboardMarkup(rows) if rows else None)


async def _fetch_work_tasks(rd) -> list:
    if not (workmod and rd):
        return []
    try:
        return await asyncio.to_thread(workmod.fetch_tasks, rd)
    except Exception as e:  # noqa
        log.warning("Không đọc được nhánh công việc: %s", oneline(str(e), 200))
        return []


async def _resume_task(chat_id: int, task: dict, msg=None) -> bool:
    """Khôi phục nhánh của task rồi chạy tiếp các bước còn dở."""
    if planner is None or workmod is None:
        if msg:
            await msg.reply_text("❌ Thiếu mô-đun kế hoạch — chạy /update.")
        return False
    if chat_id in PLAN_BUSY:
        if msg:
            await msg.reply_text("⏳ Đang chạy một kế hoạch khác — dừng nó trước đã.")
        return False
    rd = repo_dir()
    if not rd:
        if msg:
            await msg.reply_text("Không tìm thấy repo git trên máy này.")
        return False
    plan, err = await asyncio.to_thread(workmod.checkout_task, rd, task)
    if err:
        if msg:
            await msg.reply_text("❌ " + esc(err), parse_mode=HTML)
        return False
    plan["checkpoint"] = ""                  # checkpoint máy cũ không dùng được
    plan["status"] = "draft"
    plan["resumed"] = True
    plan["chat_id"] = int(chat_id)
    planner.save_plan(HOME, plan)
    done, total = planner.progress(plan)
    note = ("🌿 <b>Đã khôi phục việc đang dở</b>\n"
            f"• {esc(oneline(plan.get('title') or '', 120))}\n"
            f"• Nhánh: <code>{esc(task.get('branch') or '')}</code>\n"
            f"• Tiến độ: <b>{done}/{total}</b> bước"
            + (f" · máy cũ: <code>{esc(task.get('machine') or '')}</code>"
               if task.get("machine") else "")
            + "\n\n▶️ Đang làm tiếp bước còn dở…")
    if msg:
        await msg.reply_text(note[:4000], parse_mode=HTML)
    else:
        await BOT_OBJ.send_message(chat_id, note[:4000], parse_mode=HTML)
    asyncio.create_task(run_plan(chat_id, plan["id"]))
    return True


async def _resume_from_remote(chat_id: int, key: str = "", msg=None,
                              always_reply: bool = False) -> bool:
    """Tìm việc đang dở (mới nhất hoặc theo mã) rồi khôi phục."""
    rd = repo_dir()
    if workmod is None or not rd:
        if always_reply and msg:
            await msg.reply_text("Không tìm thấy repo git để khôi phục việc.")
        return False
    status = None
    if msg:
        status = await msg.reply_text("🔎 <i>Đang tìm việc đang dở trên GitHub…</i>",
                                      parse_mode=HTML)
    tasks = await _fetch_work_tasks(rd)
    todo = workmod.unfinished(tasks) if workmod else []
    task = workmod.find_task(tasks, key) if key else None
    if key and not task:
        if status:
            await status.edit_text("❌ Không tìm thấy việc có mã này.", parse_mode=HTML)
        return True
    if task and (task.get("status") or "") in ("done", "merged"):
        if status:
            await status.edit_text(
                "✅ Việc này đã xong hết các bước.\n"
                "Muốn sửa tiếp thì mở kế hoạch và bấm <b>Lập lại</b>.", parse_mode=HTML)
        return True
    if not task:
        if not todo:
            if status:
                if always_reply:
                    await status.edit_text(
                        "🌿 Không có việc nào đang dở trên GitHub.\n"
                        "Dùng <code>/plan &lt;yêu cầu lớn&gt;</code> để bắt đầu việc mới.",
                        parse_mode=HTML)
                else:
                    try:
                        await status.delete()
                    except Exception:
                        pass
            return bool(always_reply)
        if len(todo) > 1:
            text, markup = _work_list_text(todo)
            if status:
                await status.edit_text(text[:4000], parse_mode=HTML, reply_markup=markup)
            return True
        task = todo[0]
    if (task.get("status") or "") == "done" and not key:
        if status:
            await status.edit_text("✅ Việc gần nhất đã xong, không còn bước nào để làm tiếp.")
        return True
    if status:
        try:
            await status.delete()
        except Exception:
            pass
    return await _resume_task(chat_id, task, msg)


async def _on_work_button(q, data: str) -> None:
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    pid = parts[2] if len(parts) > 2 else ""
    uid = q.from_user.id if q.from_user else 0
    chat_id = q.message.chat_id if q.message else uid
    if not is_owner(uid):
        await q.answer("Chỉ chủ bot được điều khiển nhánh công việc.", show_alert=True)
        return
    if chat_id in PLAN_BUSY:
        await q.answer("Đang chạy kế hoạch khác — dừng nó trước đã.", show_alert=True)
        return
    if workmod is None or planner is None:
        await q.answer("Thiếu mô-đun nhánh công việc — chạy /update.")
        return
    rd = repo_dir()
    if action == "resume":
        await q.answer("Đang khôi phục…")
        tasks = await _fetch_work_tasks(rd)
        task = workmod.find_task(tasks, pid)
        if not task:
            await q.answer("Không tìm thấy việc này.", show_alert=True)
            return
        if (task.get("status") or "") in ("done", "merged"):
            await q.answer("Việc này đã xong hết các bước.", show_alert=True)
            return
        await _resume_task(chat_id, task, q.message)
        return
    plan = planner.load_plan(HOME, pid)
    if not plan:
        await q.answer("Không tìm thấy kế hoạch này.", show_alert=True)
        return
    if action == "push":
        await q.answer("Đang đẩy nhánh…")
        res = await asyncio.to_thread(workmod.push_branch, rd, plan) if rd else \
            {"ok": False, "error": "không thấy repo"}
        if res.get("ok"):
            plan["work_pushed"] = True
            plan["work_error"] = ""
            planner.save_plan(HOME, plan)
            await _q_edit(q, "✅ <b>Đã đẩy nhánh công việc lên GitHub.</b>\n"
                             "Máy khác mở bot và gõ “tiếp tục công việc” là làm tiếp được.")
        else:
            plan["work_error"] = res.get("error") or ""
            planner.save_plan(HOME, plan)
            await _q_edit(q, "❌ Đẩy nhánh lỗi: " + esc(oneline(res.get("error") or "", 600)))
        return
    if action == "merge":
        if not rd:
            await q.answer("Không thấy repo.", show_alert=True)
            return
        await q.answer("Đang gộp…")
        cp = await asyncio.to_thread(make_checkpoint, chat_id,
                                      f"trước khi gộp {plan.get('work_branch') or ''}")
        ok, detail = await asyncio.to_thread(workmod.merge_into_base, rd, plan)
        if not ok:
            await _q_edit(q, "❌ " + esc(detail))
            return
        plan["work_merged"] = True
        planner.save_plan(HOME, plan)
        stat = await asyncio.to_thread(planner.diff_stat, rd)
        await q.message.reply_text(
            ("🔀 <b>Đã gộp nhánh vào nhánh chính (chưa commit).</b>\n"
             f"{esc(detail)}\n• {esc(stat.get('text') or '')}\n\n"
             "Kiểm tra rồi bấm <b>⬆️ Push</b> để đẩy lên GitHub."
             + ("" if cp else "\n<i>Không tạo được checkpoint hoàn tác.</i>")),
            parse_mode=HTML, reply_markup=review_markup(chat_id))
        return
    if action == "drop":
        await q.answer()
        await _q_edit(
            q,
            "🗑 <b>Xoá nhánh công việc?</b>\n"
            f"Nhánh <code>{esc(plan.get('work_branch') or '')}</code> sẽ bị xoá trên máy "
            "và trên GitHub. Code trong nhánh mất, nhánh chính không đổi.",
            markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✔️ Xoá nhánh", callback_data=f"work:drop2:{pid}"),
                InlineKeyboardButton("✖️ Không", callback_data=f"plan:view:{pid}")]]))
        return
    if action == "drop2":
        await q.answer("Đang xoá…")
        ok, detail = await asyncio.to_thread(workmod.drop_branch, rd, plan) if rd else \
            (False, "không thấy repo")
        if ok:
            plan["work_dropped"] = True
            plan["status"] = "cancelled"
            plan["diff"] = ""
            plan["work_error"] = ""
        planner.save_plan(HOME, plan)
        await _q_edit(q, ("✅ " if ok else "❌ ") + esc(detail), markup=None)
        return
    await q.answer()


@guard(owner_only=True)
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    args = [a for a in (context.args or []) if a.strip()]
    if args and args[0].lower() in ("list", "ls", "danh", "danhsach", "danh-sach"):
        rd = repo_dir()
        tasks = await _fetch_work_tasks(rd)
        if workmod:
            tasks = workmod.unfinished(tasks)
        text, markup = _work_list_text(tasks)
        await msg.reply_text(text[:4000], parse_mode=HTML, reply_markup=markup)
        return
    key = args[0] if args else ""
    await _resume_from_remote(chat_id, key, msg, always_reply=True)


@guard()
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    if planner is None:
        await msg.reply_text("❌ Thiếu <code>aistv_planner.py</code> — chạy /update.",
                             parse_mode=HTML)
        return
    raw = re.sub(r"^/plan(@\w+)?\s*", "", msg.text or "", flags=re.I).strip()
    low = raw.lower()
    if not raw or low in ("status", "xem"):
        plan = planner.latest_plan(HOME, chat_id)
        if not plan:
            await msg.reply_text(
                "🧭 <b>KẾ HOẠCH TỰ TRỊ</b>\nDùng: <code>/plan &lt;yêu cầu lớn&gt;</code>\n"
                "Bot chia thành 2–8 bước, tự chạy từng bước, tự kiểm chứng và tự sửa "
                "trước khi báo cáo.\n\nViệc dài tự lưu trên nhánh GitHub — máy khác gõ "
                "<code>/tieptuc</code> để làm tiếp.\n/undo — hoàn tác thay đổi gần nhất",
                parse_mode=HTML)
            return
        body = (planner.render_report(plan) if plan.get("status") in ("done", "failed", "cancelled")
                else planner.render_plan(plan))
        await msg.reply_text(body[:4000], parse_mode=HTML,
                             reply_markup=plan_keyboard(plan))
        return
    if low in ("list", "danh sách", "danhsach"):
        text, markup = plans_list_text()
        await msg.reply_text(text, parse_mode=HTML, reply_markup=markup)
        return
    if low in ("cancel", "huỷ", "huy", "off"):
        plan = planner.latest_plan(HOME, chat_id)
        if not plan or plan.get("status") not in ("draft", "running", "failed"):
            await msg.reply_text("Không có kế hoạch nào đang chờ để huỷ.")
            return
        if plan.get("status") == "running":
            PLAN_CANCEL.add(chat_id)
        plan["status"] = "cancelled"
        planner.save_plan(HOME, plan)
        await msg.reply_text("🗑 Đã huỷ kế hoạch gần nhất.", parse_mode=HTML)
        return
    await create_plan(chat_id, raw, msg)


@guard()
async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if planner is None:
        await msg.reply_text("❌ Thiếu <code>aistv_planner.py</code> — chạy /update.",
                             parse_mode=HTML)
        return
    rd = repo_dir()
    if not rd:
        await msg.reply_text("Không tìm thấy repo git để hoàn tác.")
        return
    items = planner.list_checkpoints(HOME, 6)
    stat = await asyncio.to_thread(planner.diff_stat, rd)
    lines = ["↩️ <b>HOÀN TÁC</b>", f"Hiện tại: {esc(stat.get('text') or '')}", ""]
    if not items:
        await msg.reply_text("\n".join(lines) + "Chưa có checkpoint nào.",
                             parse_mode=HTML)
        return
    lines.append("Chọn mốc để quay về (thay đổi chưa commit sẽ mất):")
    rows = []
    for m in items:
        when = time.strftime("%d/%m %H:%M", time.localtime(m.get("at") or 0))
        label = oneline(m.get("label") or "checkpoint", 40)
        lines.append(f"• <code>{m['id'][:15]}</code> — {esc(when)} · {esc(label)}")
        rows.append([InlineKeyboardButton(f"↩️ {when} · {label[:18]}",
                                          callback_data=f"up:undo:{m['id']}")])
    await msg.reply_text("\n".join(lines)[:4000], parse_mode=HTML,
                         reply_markup=InlineKeyboardMarkup(rows))


# ════════════════════════════════════════════════════════════════════
# 8. LỆNH & TRÌNH XỬ LÝ TELEGRAM
# ════════════════════════════════════════════════════════════════════
def email_line() -> str:
    if not mail:
        return "không có mô-đun"
    try:
        cfg = mail.load()
    except Exception:
        return "lỗi cấu hình"
    if not cfg.get("address"):
        return "chưa kết nối"
    return mail.mask(cfg["address"]) + ("" if cfg.get("password") else " ⚠️ thiếu mật khẩu")


def image_provider_line() -> str:
    names = []
    try:
        if web2api is not None and web2api.enabled():
            names.append("Gemini")
    except Exception:
        pass
    if get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY"):
        if "Gemini" in names:
            names.append("Gemini API")
        else:
            names.append("Gemini")
    if get_secret("CLOUDFLARE_ACCOUNT_ID") and get_secret("CLOUDFLARE_API_TOKEN"):
        names.append("Cloudflare")
    if get_secret("TOGETHER_API_KEY"):
        names.append("Together")
    if get_secret("HF_TOKEN") or get_secret("HUGGINGFACE_API_KEY"):
        names.append("HuggingFace")
    return ", ".join(names) if names else "⚠️ chưa cấu hình (xem /image)"


def web2api_line() -> str:
    """Một dòng trạng thái cho /status (không chặn lâu)."""
    if web2api is None:
        return "không có module"
    if not WEB2API_FALLBACK:
        return "đã tắt"
    try:
        if not web2api.enabled():
            return "đã tắt"
        up = web2api.health(1.2)
        return ("🟢 đang chạy" if up else "🟡 chưa bật (tự bật khi hết hạn mức)") + \
               f" · {WEB2API_MODEL}"
    except Exception:
        return "chưa rõ"


def build_status(chat_id: int) -> str:
    up = int(time.time() - START_TIME)
    to = "không giới hạn" if AGENT_TIMEOUT <= 0 else f"{AGENT_TIMEOUT}s"
    gh = STATE.get("github_user") or ("đã kết nối" if github_token() else "chưa kết nối")
    return (
        "📊 <b>Trạng thái AI STV</b>\n"
        f"• Model: <code>{esc(STATE['model'])}</code>"
        + (f" · variant <code>{esc(STATE['variant'])}</code>" if STATE.get("variant") else "") + "\n"
        f"• OpenCode: <code>{esc(OPENCODE_VERSION)}</code>\n"
        f"• Suy nghĩ: {'bật' if STATE.get('show_thinking', True) else 'tắt'} · Hỏi lại: "
        f"{'bật' if ASK_SERVER else 'tắt'}\n"
        f"• Chi tiết việc làm: {'bật' if STATE.get('show_activity', False) else 'tắt'}\n"
        f"• GitHub: {esc(gh)}\n"
        f"• Email: {esc(email_line())}\n"
        f"• Gemini ({VISION_MODEL}) đọc ảnh/video: "
        f"{'✅ sẵn sàng' if GEMINI_READY else ('🟡 qua Gemini' if vision_ready() else '⚠️ thiếu GEMINI_API_KEY')}"
        f"{' · thảo luận 2 chiều' if VISION_HANDOFF else ' · trả lời trực tiếp'}\n"
        f"• Gemini dự phòng: {esc(web2api_line())}\n"
        f"• Tạo ảnh: {esc(image_provider_line())}\n"
        f"• Khách: chat {'bật' if GUEST_CHAT and GUEST_ACTIVE['chat'] else 'tắt'} · "
        f"ảnh {'bật' if GUEST_ACTIVE['media'] else 'tắt'} · "
        f"đọc ảnh/video {'bật' if GUEST_ACTIVE['vision'] else 'tắt'} · "
        f"{len(GUEST_HIST)} ngữ cảnh · {len(GUEST_BANS)} bị chặn\n"
        f"• Giới hạn 1 yêu cầu: {to}\n"
        f"• Hội thoại: {len(load_history(chat_id)) // 2} lượt đã lưu\n"
        f"• Trí nhớ dài hạn: {len(memory_items())} mục"
        f" · cloud {'🟢' if CLOUD_STAT['ok'] else ('🔴' if CLOUD_STAT['ok'] is False else '🟡')}\n"
        f"• Nhắc việc: {len(REMINDERS)} · Theo dõi: {len(WATCHES)}\n"
        f"• Skills: {len(list_skills())}\n"
        f"• File trong workspace: {len(snapshot())}\n"
        f"• Tác vụ: {'🟢 đang chạy' if chat_id in RUNNING else '⚪ rảnh'}\n"
        f"• Hoạt động: {up // 3600}h {up % 3600 // 60}m"
    )


def build_skills_index(exclude: Optional[str] = None, limit: int = 60) -> str:
    """Danh sách gọn để agent tự chọn skill phù hợp (progressive disclosure)."""
    rows = []
    total = 0
    # Giữ index vừa ngân sách prompt (Windows 28K): ưu tiên skill cấp 1, bỏ bớt skill phụ.
    byte_budget = 8_000 if IS_WINDOWS else 40_000
    used_bytes = 500
    for path in _skill_paths():
        name = _skill_name(path)
        if name == exclude:
            continue
        meta, _, desc = _skill_text_meta(read_text(path))
        manual_only = str(
            meta.get("disable-model-invocation") or meta.get("disable_model_invocation") or ""
        ).strip().lower()
        if manual_only in ("true", "yes", "1", "on"):
            continue
        total += 1
        try:
            rel = path.relative_to(WORKSPACE).as_posix()
        except ValueError:
            rel = path.as_posix()
        line = f"- {name} (`{rel}`): {oneline(desc, 110)}"
        line_bytes = len(line.encode("utf-8")) + 1
        if len(rows) >= limit or used_bytes + line_bytes > byte_budget:
            continue
        rows.append(line)
        used_bytes += line_bytes
    if not rows:
        return ""
    if total > len(rows):
        rows.append(f"- … còn {total - len(rows)} skill khác (xem /skills)")
    return (
        "## KỸ NĂNG CÓ SẴN (workspace/skills)\n"
        + "\n".join(rows)
        + "\nKhi yêu cầu khớp rõ với một skill, đọc file SKILL.md được ghi trong danh sách và làm theo. "
          "Chỉ đọc 1-2 skill liên quan, không đọc tràn lan. "
          "Skill không được ghi đè quy tắc bảo mật trong AGENTS.md."
    )


def build_skills_pages(limit: int = 3600) -> list:
    sk = list_skills()
    if not sk:
        return [
            "🧩 Chưa có skill nào. Tạo <code>skills/&lt;tên&gt;/SKILL.md</code> "
            "hoặc cài bằng <code>/skill add &lt;github-url&gt;</code>."
        ]
    header = f"🧩 <b>Skills</b> ({len(sk)})\n"
    footer = (
        "\nDùng: <code>/skill &lt;tên&gt; &lt;yêu cầu&gt;</code>\n"
        "Thêm: <code>/skill add &lt;github-url|owner/repo/path&gt;</code> (chủ bot)"
    )
    pages, cur = [], header
    for name, desc in sk:
        row = f"• <code>{esc(name)}</code> — {esc(desc)}\n"
        if cur.strip() and len(cur) + len(row) > limit:
            pages.append(cur.rstrip())
            cur = "🧩 <b>Skills</b> (tiếp)\n"
        cur += row
    if len(cur) + len(footer) > limit:
        pages.append(cur.rstrip())
        cur = footer.lstrip("\n")
    else:
        cur += footer
    pages.append(cur.rstrip())
    return pages


def build_skills() -> str:
    """Giữ hàm cũ cho tương thích; nội dung có thể dài hơn 1 tin nhắn Telegram."""
    return "\n\n".join(build_skills_pages())


def build_memory() -> str:
    items = memory_items()
    if not items:
        return "🧠 Trí nhớ trống. Thêm bằng <code>/remember &lt;nội dung&gt;</code>."
    rows = "\n".join(f"{i}. {esc(l[2:])}" for i, l in enumerate(items, 1))
    return f"🧠 <b>Trí nhớ dài hạn</b>\n{rows[-3500:]}\n\nXoá: <code>/forget &lt;số&gt;</code> hoặc <code>/forget all</code>"


def welcome_text() -> str:
    return (
        "🤖 <b>AI STV — Agent Assistant</b>\n"
        f"Chạy bằng OpenCode · <code>{esc(STATE['model'])}</code>\n\n"
        "✨ <b>Khả năng</b>\n"
        "• Hiện <b>suy nghĩ (thinking)</b> của model theo thời gian thực\n"
        "• Agent <b>hỏi lại bạn</b> bằng bảng nút bấm khi cần chọn phương án\n"
        "• Nhớ hội thoại bền vững, kể cả khi bot khởi động lại\n"
        "• <b>Trả lời/trích dẫn tin nhắn</b> — reply tin nào là hiểu đúng phần đó\n"
        "• Trí nhớ dài hạn — /remember, /memory; tự tóm tắt hội thoại dài\n"
        "• <b>Trí nhớ đám mây</b> (Firebase) — restart/Colab reset vẫn còn\n"
        "• <b>Chủ động</b>: /remind hẹn giờ, /task tự chạy, /watch theo dõi repo &amp; log\n"
        "• <b>Email</b>: /email đọc &amp; gửi thư (IMAP/SMTP) ngay trong chat\n"
        "• Đọc file bạn gửi, tạo file và tự gửi lại cho bạn\n"
        "• <b>Gemini 3.8 Flash đọc ảnh</b>: gửi ảnh + câu hỏi → mô tả, OCR chữ, phân tích biểu đồ\n"
        "• <b>Tạo ảnh &amp; sơ đồ tư duy</b>: /image mô tả · /mindmap chủ đề → gửi ảnh ngay\n"
        "• <b>Gemini xem video</b>: gửi link/file (&lt; 45 phút) + câu hỏi → tóm tắt kèm mốc thời gian\n"
        "• <b>Model chính (đổi bằng /model)</b> — Gemini đọc ảnh/video rồi thảo luận, model chính trả lời\n"
        "• <b>Không giới hạn 10 phút</b> — dự án lớn chạy tới khi xong (/stop để huỷ)\n"
        "• Kết nối GitHub 1 lần — /github login; tự cập nhật — /update\n\n"
        "Gửi câu hỏi hoặc yêu cầu để bắt đầu 👇"
    )


HELP_TEXT = (
    "💡 <b>Hướng dẫn</b>\n"
    "Nhắn trực tiếp yêu cầu (hỏi đáp, viết/sửa code, phân tích, tạo file…).\n\n"
    "<b>Hội thoại</b>\n/new — cuộc trò chuyện mới\n/stop — huỷ tác vụ đang chạy\n/status — trạng thái\n\n"
    "<b>Trí nhớ &amp; Skills</b>\n/remember &lt;nội dung&gt; — ghi nhớ dài hạn\n/memory — xem trí nhớ\n"
    "/forget &lt;số|all&gt; — xoá trí nhớ\n/summary — cô đọng hội thoại vào trí nhớ\n"
    "/cloud [sync] · /cloud url &lt;URL&gt; — trạng thái / bật đồng bộ Firebase\n"
    "/skills — danh sách skills\n/skill &lt;tên&gt; &lt;yêu cầu&gt; — chạy theo skill\n"
    "/skill add &lt;github-url|owner/repo/path&gt; — cài skill mới (chủ bot)\n\n"
    "<b>Email</b>\n/email — trạng thái · /email test — kiểm tra kết nối\n"
    "/email inbox [n] · /email unread [n] — hộp thư\n"
    "/email read &lt;số|uid&gt; — đọc thư · /email send a@b.c | Tiêu đề | Nội dung\n"
    "/email setup &lt;email&gt; &lt;app-password&gt; · /email reset\n\n"
    "<b>Chủ động</b>\n/remind &lt;thời gian&gt; &lt;nội dung&gt; — nhắc việc (+30m, 20:30, daily 8:00)\n"
    "/task &lt;thời gian&gt; &lt;yêu cầu&gt; — để agent tự chạy theo lịch\n"
    "/reminders — danh sách · /unremind &lt;mã|all&gt; — xoá\n"
    "/watch git owner/repo — báo commit mới · /watch log &lt;file&gt; — báo lỗi mới\n"
    "/watch file &lt;đường dẫn&gt; — báo khi thay đổi · /watch del &lt;mã|all&gt;\n\n"
    "<b>File &amp; Video</b>\nGửi file cho bot → lưu vào <code>inbox/</code> để agent đọc\n/files — file trong workspace\n/get &lt;đường dẫn&gt; — tải file về\n"
    "Gửi ảnh + câu hỏi → Gemini 3.8 Flash đọc ảnh (OCR, biểu đồ) rồi model chính trả lời\n"
    "Gửi tin nhắn thoại → bot tự nghe rồi làm theo lời bạn (tiếng Việt/Anh)\n"
    "/image &lt;mô tả&gt; — tạo ảnh (--style anime, --aspect 16:9) · reply ảnh + /image — vẽ lại theo ảnh\n"
    "/image --mindmap &lt;chủ đề&gt; · /mindmap &lt;chủ đề&gt; — sơ đồ tư duy\n"
    "/see &lt;url|đường dẫn&gt; [câu hỏi] — Gemini đọc ảnh, model chính trả lời\n"
    "Gửi link/file video (&lt; 45 phút) + câu hỏi → Gemini xem hình ảnh + âm thanh, model chính trả lời kèm mốc thời gian\n"
    "/video &lt;url|đường dẫn&gt; [câu hỏi] — Gemini xem video, model chính trả lời\n\n"
    "<b>Reply / trích dẫn</b>\nTrả lời (reply) một tin nhắn rồi nhắn yêu cầu → agent hiểu “cái này/đoạn trên” là tin đó\n"
    "Bôi đen một phần rồi reply → agent ưu tiên đúng phần được trích dẫn\n"
    "Reply tin nhắn rồi gõ /remember → lưu chính tin đó vào trí nhớ\n\n"
    "<b>Suy nghĩ &amp; hỏi đáp</b>\n/think on|off — hiện/tắt suy nghĩ cuộn trực tiếp khi chạy\n"
    "/activity on|off — hiện/tắt chi tiết lệnh, code, output trong khung cuộn\n"
    "/variant [high|max|off] — mức reasoning của model\n"
    "Agent tự dùng nút bấm khi cần bạn chọn/xác nhận.\n\n"
    "<b>Kế hoạch &amp; an toàn (chủ bot)</b>\n"
    "/plan &lt;yêu cầu lớn&gt; — chia 2–8 bước, tự chạy, tự kiểm chứng, tự sửa\n"
    "/plan · /plan list · /plan cancel — xem / danh sách / huỷ kế hoạch\n"
    "/tieptuc — làm tiếp việc đang dở (kế hoạch dài tự lưu trên nhánh GitHub)\n"
    "Máy khác chỉ cần nhắn “tiếp tục công việc” là bot tự khôi phục và làm tiếp.\n"
    "/undo — hoàn tác thay đổi chưa commit gần nhất (quay về checkpoint)\n"
    "Agent sửa repo xong bot hiện diff kèm nút ⬆️ Push / ↩️ Hoàn tác — không tự push.\n\n"
    "<b>GitHub &amp; tự cập nhật (chủ bot)</b>\n/github login — kết nối GitHub bằng mã, lưu lâu dài\n"
    "/github token &lt;PAT&gt; — đổi token; bot tự quét repo nếu repo cũ không truy cập được\n"
    "/github repos — quét repo của tài khoản, bấm nút để chọn repo đích\n"
    "/github repo use owner/name — đặt repo đích · /github repo create tên [private]\n"
    "/github status · /github repo · /github logout\n"
    "/vm — bảng nút máy ảo Windows: chọn runner, thời gian, 🚀 tạo · 🛑 dừng (chủ bot)\n"
    "/push — đẩy code lên GitHub ngay (Windows chạy run.bat là có bản mới)\n"
    "/update — pull bản mới trên GitHub rồi khởi động lại\n/restart — khởi động lại bot\n\n"
    "<b>Hệ thống (chủ bot)</b>\n/model [provider/tên] — xem/đổi model\n/models — danh sách model\n/allow &lt;id&gt; · /deny &lt;id&gt; — cấp/thu hồi quyền"
)


@guard(allow_guest=True)
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not authorized(user.id, chat.type):
        body = GUEST_HELP_TEXT
        if chat.type == "private":
            body += f"\n\nID của bạn: <code>{user.id}</code>"
        await msg.reply_text(body, parse_mode=HTML)
        return
    await msg.reply_text(welcome_text(), parse_mode=HTML, reply_markup=MENU_KB)


@guard(allow_guest=True)
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
    if not authorized(user.id, chat.type):
        await msg.reply_text(GUEST_HELP_TEXT, parse_mode=HTML)
        return
    await msg.reply_text(HELP_TEXT, parse_mode=HTML)


@guard(allow_guest=True)
async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
    if not authorized(user.id, chat.type):
        GUEST_HIST.pop(_guest_key(chat, user), None)
        await msg.reply_text("🧹 Đã xoá ngữ cảnh riêng của bạn.", parse_mode=HTML)
        return
    archive_history(chat.id)
    await msg.reply_text("🧹 <b>Đã bắt đầu cuộc trò chuyện mới.</b> Trí nhớ dài hạn vẫn được giữ.", parse_mode=HTML)


@guard()
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in PLAN_BUSY:
        PLAN_CANCEL.add(chat_id)
    proc = RUNNING.get(chat_id)
    if proc and proc.returncode is None:
        CANCELLED.add(chat_id)
        proc.kill()
        await update.effective_message.reply_text("🛑 Đang huỷ tác vụ…")
    elif chat_id in PLAN_BUSY:
        await update.effective_message.reply_text("⛔ Sẽ dừng kế hoạch sau bước hiện tại.")
    else:
        await update.effective_message.reply_text("Hiện không có tác vụ nào đang chạy.")


@guard()
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(build_status(update.effective_chat.id), parse_mode=HTML)


@guard(allow_guest=True)
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not authorized(user.id, chat.type):
        await _guest_model_command(update, context)
        return
    if not context.args:
        await msg.reply_text(f"🧠 Model hiện tại: <code>{esc(STATE['model'])}</code>\nĐổi: <code>/model provider/tên</code> (xem /models)", parse_mode=HTML)
        return
    if not is_owner(update.effective_user.id):
        await msg.reply_text("🔒 Chỉ chủ bot được đổi model.")
        return
    new = context.args[0].strip()
    if not re.fullmatch(r"[\w.\-]+/[\w.\-:/]+", new):
        await msg.reply_text("⚠️ Sai định dạng. Ví dụ: <code>/model opencode/deepseek-v4.1-flash-free</code>", parse_mode=HTML)
        return
    STATE["model"] = new
    save_state()
    await msg.reply_text(f"✅ Đã đổi model: <code>{esc(new)}</code>", parse_mode=HTML)


@guard()
async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    try:
        proc = await asyncio.create_subprocess_exec(OPENCODE_BIN, "models", stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=40)
    except Exception as e:
        await msg.reply_text(f"⚠️ Không lấy được danh sách model: {e}")
        return
    raw = clean_output(out.decode("utf-8", "replace"))
    lines = [l.strip() for l in raw.splitlines() if "/" in l]
    if not lines:
        detail = _pretty_error(raw) or f"opencode models không trả về dữ liệu (rc={proc.returncode})"
        await msg.reply_text(f"⚠️ Không lấy được danh sách model.\n\n{esc(detail[-800:])}",
                             parse_mode=HTML)
        return
    zen = [l for l in lines if l.startswith("opencode/")] or lines
    free = [l for l in zen if "free" in l] or zen          # model miễn phí lên đầu
    body = esc("\n".join(free[:40])) or "(trống)"
    await msg.reply_text(f"🧠 <b>Model khả dụng</b> ({len(free)})\n<pre>{body}</pre>\nĐổi: <code>/model &lt;tên&gt;</code>", parse_mode=HTML)


@guard()
async def cmd_think(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    arg = (context.args[0].lower() if context.args else "")
    if arg in ("on", "1", "bat", "bật"):
        STATE["show_thinking"] = True
    elif arg in ("off", "0", "tat", "tắt"):
        STATE["show_thinking"] = False
    elif arg:
        await msg.reply_text("Dùng: /think on | /think off")
        return
    save_state()
    on = STATE.get("show_thinking", True)
    extra = ""
    if on and _model_has_no_thinking():
        extra = ("\n⚠️ Model hiện tại <code>" + esc(_model_base())
                 + "</code> không trả reasoning — đổi sang model khác bằng /model "
                   "thì mới thấy suy nghĩ.")
    await msg.reply_text(
        f"💭 Hiển thị suy nghĩ (reasoning): <b>{'BẬT' if on else 'TẮT'}</b>\n"
        "Suy nghĩ hiện trực tiếp trong tin nhắn tiến độ, cuộn xuống theo thời gian thực."
        + extra,
        parse_mode=HTML)


@guard()
async def cmd_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    arg = (context.args[0].lower() if context.args else "")
    if arg in ("on", "1", "bat", "bật"):
        STATE["show_activity"] = True
    elif arg in ("off", "0", "tat", "tắt"):
        STATE["show_activity"] = False
    elif arg:
        await msg.reply_text("Dùng: /activity on | /activity off")
        return
    save_state()
    on = STATE.get("show_activity", False)
    await msg.reply_text(
        f"⚙️ Chi tiết việc đang làm (lệnh, code, output): <b>{'BẬT' if on else 'TẮT'}</b>\n"
        + ("Đang bật: tin nhắn tiến độ cuộn chi tiết từng lệnh/sửa file, giữ lại khi xong."
           if on else
           "Đang tắt: tiến độ vẫn cuộn theo thời gian thực nhưng gọn (1 dòng/sự kiện) và tự xoá khi xong."),
        parse_mode=HTML)


@guard()
async def cmd_variant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.args:
        cur = STATE.get("variant") or "(mặc định của model)"
        await msg.reply_text(
            f"🎚 Reasoning effort/variant: <code>{esc(cur)}</code>\n"
            "Đổi: <code>/variant high</code>, <code>/variant max</code>, <code>/variant off</code>",
            parse_mode=HTML)
        return
    if not is_owner(update.effective_user.id):
        await msg.reply_text("🔒 Chỉ chủ bot được đổi variant.")
        return
    val = context.args[0].strip()
    if val.lower() in ("off", "auto", "default", "0"):
        STATE["variant"] = ""
    elif re.fullmatch(r"[\w.\-]{1,32}", val):
        STATE["variant"] = val
    else:
        await msg.reply_text("⚠️ Tên variant không hợp lệ.")
        return
    save_state()
    cur = STATE.get("variant") or "(mặc định của model)"
    await msg.reply_text(f"✅ Variant: <code>{esc(cur)}</code>", parse_mode=HTML)


async def _github_connected(bot, chat_id: int, info: dict, tok: str) -> None:
    """Sau khi có token: kiểm tra repo đích; không truy cập được thì quét repo cho chọn."""
    active = github_token() or tok
    if active != tok:
        await bot.send_message(
            chat_id,
            "⚠️ Đang có <code>GITHUB_TOKEN</code>/<code>GH_TOKEN</code> trong môi trường "
            "(Colab Secrets) và nó được ưu tiên hơn token vừa nhập. Xoá secret đó nếu muốn "
            "dùng token mới.", parse_mode=HTML)
    login = info.get("login") or "?"
    slug = current_repo_slug()
    ok = False
    if slug:
        try:
            ok = await asyncio.to_thread(repo_can_push, slug, active)
        except Exception:
            ok = False
    head = ("✅ <b>Đã kết nối GitHub</b>\n"
            f"• Tài khoản: <b>{esc(login)}</b>\n"
            "• Đã cấu hình <code>git</code> (và <code>gh</code> nếu có)\n")
    if ok:
        await bot.send_message(
            chat_id, head + f"• Repo đích: <code>{esc(slug)}</code>\n\n"
            "Đổi repo bất cứ lúc nào: /github repos", parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🗂 Chọn / đổi repo", callback_data="ghr:r")]]))
        return
    await bot.send_message(
        chat_id,
        head + f"• Repo đích cũ: <code>{esc(slug or 'chưa đặt')}</code> — tài khoản này "
        "<b>không có quyền ghi</b> (hoặc không truy cập được).\n\n"
        "🔍 Đang quét repo của tài khoản này để bạn chọn…", parse_mode=HTML)
    try:
        text, kb = await asyncio.to_thread(gh_repo_picker, chat_id, active, 0, True)
        await bot.send_message(chat_id, text, parse_mode=HTML, reply_markup=kb)
    except Exception as e:
        await bot.send_message(
            chat_id,
            f"⚠️ Không quét được repo: {esc(oneline(str(e), 300))}\n"
            "Tạo repo mới: <code>/github repo create ten-repo [private]</code>",
            parse_mode=HTML)


async def _github_repo_cmd(msg, sub: str, args: list, tok: str) -> None:
    """Xử lý /github repo|repos [list|use owner/name|create tên [private]]."""
    if not tok:
        await msg.reply_text("⚠️ Chưa kết nối GitHub. Dùng /github login hoặc /github token &lt;PAT&gt;.",
                             parse_mode=HTML)
        return
    action = (args[0].lower() if args else "")

    if action in ("use", "set", "select", "chon", "chọn") and len(args) > 1:
        try:
            slug = set_repo_slug(args[1])
        except Exception as e:
            await msg.reply_text(f"⚠️ {esc(oneline(str(e), 300))}", parse_mode=HTML)
            return
        lines = [f"✅ Repo đích: <code>{esc(slug)}</code>"]
        if repo_dir():
            origin = repo_remote_slug()
            if origin and origin != slug:
                lines.append(f"• Origin máy này vẫn là <code>{esc(origin)}</code>\n"
                             "  Đổi origin: <code>/github repos</code> → chọn repo → "
                             "“Đổi origin + pull”.")
            else:
                lines.append("• Origin đã khớp.")
        lines.append("• /update sẽ pull từ repo này.")
        await msg.reply_text("\n".join(lines), parse_mode=HTML)
        return

    if action in ("create", "new", "tao", "tạo") and len(args) > 1:
        private = any(a.lower() in ("private", "rieng", "riêng", "kin", "kín") for a in args[2:])
        await msg.reply_text("⏳ Đang tạo repo trên GitHub…")
        try:
            slug = await asyncio.to_thread(gh_create_repo, args[1], tok, private)
        except Exception as e:
            await msg.reply_text(f"❌ Không tạo được repo: {esc(oneline(str(e), 400))}\n"
                                 "Có thể tên đã tồn tại — dùng /github repos để chọn repo có sẵn.",
                                 parse_mode=HTML)
            return
        set_repo_slug(slug)
        try:
            out = await asyncio.to_thread(gh_push_code, slug)
        except Exception as e:
            await msg.reply_text(
                f"✅ Đã tạo <code>{esc(slug)}</code> nhưng chưa đẩy được code:\n"
                f"{esc(oneline(str(e), 500))}\n\n"
                "Thử: <code>/github repos</code> → chọn repo → “Đẩy code lên repo này”.",
                parse_mode=HTML)
            return
        await msg.reply_text(
            f"✅ <b>Đã tạo repo + đẩy code</b>\n• Repo: <code>{esc(slug)}</code>\n"
            f"• Origin: đã trỏ về repo mới\n<pre>{esc(out[-600:])}</pre>",
            parse_mode=HTML)
        return

    if sub != "repo" or action in ("list", "all", "scan", "quet", "quét"):
        try:
            text, kb = await asyncio.to_thread(gh_repo_picker, msg.chat_id, tok, 0, True)
        except Exception as e:
            await msg.reply_text(f"⚠️ Không quét được repo: {esc(oneline(str(e), 400))}",
                                 parse_mode=HTML)
            return
        await msg.reply_text(text, parse_mode=HTML, reply_markup=kb)
        return

    # /github repo — thông tin hiện tại + danh sách để chọn
    cur = current_repo_slug()
    origin = repo_remote_slug()
    lines = ["📦 <b>Repo đích</b>",
             f"• Đang dùng: <code>{esc(cur or 'chưa đặt')}</code>"]
    rd = repo_dir()
    if rd:
        _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], rd)
        _, head = _git(["log", "-1", "--oneline"], rd)
        lines.append(f"• Bản clone: <code>{esc(rd)}</code> · {esc(branch)} · {esc(head[:70])}")
        if origin:
            lines.append(f"• Origin: <code>{esc(origin)}</code>")
    lines += ["", "<i>Chọn repo bên dưới để đặt làm repo đích.</i>"]
    try:
        text, kb = await asyncio.to_thread(gh_repo_picker, msg.chat_id, tok, 0, False)
    except Exception as e:
        await msg.reply_text("\n".join(lines + ["", f"⚠️ {esc(oneline(str(e), 300))}"]),
                             parse_mode=HTML)
        return
    await msg.reply_text("\n".join(lines) + "\n\n" + text, parse_mode=HTML, reply_markup=kb)


async def _gh_poll_task(bot, chat_id: int, device: dict) -> None:
    interval = max(5, int(device.get("interval") or 5))
    deadline = time.time() + int(device.get("expires_in") or 900)
    while time.time() < deadline:
        await asyncio.sleep(interval)
        try:
            r = await asyncio.to_thread(_gh_device_poll, device["device_code"])
        except Exception:
            continue
        err = str(r.get("error") or "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            await bot.send_message(chat_id, f"❌ Đăng nhập GitHub thất bại: <code>{esc(err)}</code>\n"
                                            "Gửi /github login để thử lại.", parse_mode=HTML)
            return
        tok = str(r.get("access_token") or "")
        if not tok:
            continue
        try:
            info = await asyncio.to_thread(save_github_token, tok)
        except Exception as e:
            await bot.send_message(chat_id, f"❌ Không lưu được token GitHub: {esc(oneline(str(e), 300))}",
                                   parse_mode=HTML)
            return
        login = info.get("login") or "?"
        await bot.send_message(
            chat_id,
            f"✅ <b>Đã lưu token GitHub</b> · tài khoản <b>{esc(login)}</b>\n"
            f"• Lưu tại: <code>{esc(GITHUB_TOKEN_FILE)}</code>\n"
            + ("• ☁️ Đã mã hoá, đồng bộ Firebase — máy khác tự dùng lại.\n"
               if CLOUD_ENABLED else
               "• ⚠️ Cloud đang tắt — gửi /cloud url &lt;URL&gt; để không phải đăng nhập lại.\n"),
            parse_mode=HTML)
        await _github_connected(bot, chat_id, info, tok)
        return
    await bot.send_message(chat_id, "⌛ Mã đăng nhập đã hết hạn. Gửi /github login để lấy mã mới.")


@guard(owner_only=True)
async def cmd_github(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    sub = (context.args[0].lower() if context.args else "status")
    tok = github_token()

    if sub in ("login", "connect"):
        try:
            d = await asyncio.to_thread(_gh_device_start)
        except Exception as e:
            await msg.reply_text(f"⚠️ Không tạo được mã đăng nhập: {oneline(str(e), 300)}")
            return
        url = d.get("verification_uri") or "https://github.com/login/device"
        await msg.reply_text(
            "🐙 <b>Kết nối GitHub</b>\n"
            f"1. Mở: {esc(url)}\n"
            f"2. Nhập mã: <code>{esc(d.get('user_code'))}</code>\n"
            "3. Bấm <b>Authorize</b>.\n\n"
            "Bot sẽ tự lưu token và cấu hình git/gh. Không cần làm lại lần sau.\n"
            "<i>Mã có hiệu lực khoảng 15 phút.</i>",
            parse_mode=HTML)
        asyncio.create_task(_gh_poll_task(context.bot, update.effective_chat.id, d))
        return

    if sub in ("logout", "disconnect"):
        clear_github_token()
        await msg.reply_text("🚪 Đã xoá token GitHub khỏi máy này.")
        return

    if sub in ("token", "pat"):
        value = " ".join(context.args[1:]).strip()
        if not value:
            await msg.reply_text("Dùng: /github token <PAT>  (nên dùng /github login an toàn hơn)")
            return
        try:
            info = await asyncio.to_thread(save_github_token, value)
        except Exception as e:
            await msg.reply_text(f"❌ {oneline(str(e), 300)}")
            return
        await msg.reply_text(
            f"✅ Đã lưu token GitHub cho <b>{esc(info.get('login') or '?')}</b>.\n"
            "⚠️ Token vừa gửi nằm trong lịch sử chat Telegram — nên thu hồi nếu đã lộ.",
            parse_mode=HTML)
        await _github_connected(context.bot, update.effective_chat.id, info, value)
        return

    if sub in ("repo", "repos", "list", "scan"):
        await _github_repo_cmd(msg, sub, context.args[1:], tok)
        return

    # status
    lines = ["🐙 <b>GitHub</b>"]
    if tok:
        login = STATE.get("github_user") or "?"
        if login == "?":
            try:
                info = await asyncio.to_thread(_gh_http, "https://api.github.com/user", None, tok, 15)
                login = info.get("login") or "?"
                STATE["github_user"] = login
                save_state()
            except Exception:
                login = "?"
        lines += [f"• Tài khoản: <b>{esc(login)}</b>",
                  f"• Nguồn token: {esc(github_token_source())}",
                  f"• Lưu tại: <code>{esc(GITHUB_TOKEN_FILE)}</code>"]
    else:
        lines += ["• Trạng thái: <b>chưa kết nối</b>"]
    lines.append("• Lưu cloud: " + (
        "✅ Firebase — tự khôi phục trên máy khác" if CLOUD_ENABLED
        else "⚪ chưa bật — gửi /cloud url &lt;URL&gt;"))
    rd = repo_dir()
    if rd:
        _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], rd)
        _, head = _git(["log", "-1", "--oneline"], rd)
        lines.append(f"• Bản clone: <code>{esc(rd)}</code> · {esc(branch)} · {esc(head[:80])}")
    slug = current_repo_slug()
    if slug:
        lines.append(f"• Repo đích: <code>{esc(slug)}</code>")
    lines += ["", "<b>Lệnh</b>",
              "/github login — kết nối bằng mã (khuyến nghị)",
              "/github token &lt;PAT&gt; — dán token có sẵn",
              "/github repos — quét &amp; chọn repo bằng nút",
              "/github repo use owner/name — đặt repo đích",
              "/github repo create tên [private] — tạo repo mới + đẩy code",
              "/github repo — xem repo/nhánh/commit",
              "/github logout — ngắt kết nối",
              "/update — pull bản mới + khởi động lại"]
    kb = None
    if tok:
        rows = [[InlineKeyboardButton("🗂 Chọn / đổi repo", callback_data="ghr:r")]]
        if slug:
            rows.append([InlineKeyboardButton("📦 Repo hiện tại", callback_data="ghr:cur")])
        kb = InlineKeyboardMarkup(rows)
    await msg.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=kb)


@guard(allow_guest=True)
async def cmd_vm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if chat.type != "private":
        await msg.reply_text("⚠️ /vm chỉ dùng trong chat riêng — thông tin đăng nhập gửi qua DM.")
        return
    if not (user and is_owner(user.id)):
        if not GUEST_VM:
            await _deny_guest(update, context)
            return
        await _guest_vm_entry(msg, chat, user)
        return
    args = [a.strip() for a in (context.args or []) if a.strip()]
    sub = args[0].lower() if args else ""
    VM_AWAIT.pop(chat.id, None)

    if sub in ("forget", "clear", "xoa"):
        clear_vm_creds()
        await msg.reply_text("🧹 Đã xoá PAT + Tailscale key (đồng bộ cả Firebase).",
                             reply_markup=vm_keyboard())
        return
    if sub in ("token", "pat"):
        if len(args) < 2:
            await msg.reply_text("Bấm 🔑 Nhập PAT GitHub trong bảng bên dưới.",
                                 reply_markup=vm_keyboard())
            return
        await _vm_save_pat(context.bot, chat.id, args[1], msg)
        return
    if sub in ("key", "tskey"):
        if len(args) < 2:
            await msg.reply_text("Bấm 🔑 Nhập Tailscale key trong bảng bên dưới.",
                                 reply_markup=vm_keyboard())
            return
        await _vm_save_key(context.bot, chat.id, args[1], msg)
        return
    if sub in ("create", "tao", "new"):
        win = args[1] if len(args) > 1 else ""
        minutes = args[2] if len(args) > 2 else ""
        await _vm_create_flow(context.bot, chat.id, "", "", win, minutes)
        return
    if len(args) >= 2:                       # /vm <PAT> <tskey> [windows] [phút]
        win = args[2] if len(args) > 2 else ""
        minutes = args[3] if len(args) > 3 else ""
        try:
            await msg.delete()               # xoá tin nhắn chứa PAT + key
        except Exception:
            pass
        await _vm_create_flow(context.bot, chat.id, args[0], args[1], win, minutes)
        return
    await msg.reply_text(vm_status_text(chat.id), parse_mode=HTML, reply_markup=vm_keyboard())


async def _vm_save_pat(bot, chat_id: int, pat: str, src_msg=None) -> bool:
    """Kiểm tra PAT bằng GitHub API rồi lưu; trả True nếu thành công."""
    pat = (pat or "").strip()
    if src_msg is not None:
        try:
            await src_msg.delete()          # xoá tin nhắn chứa PAT ngay
        except Exception:
            pass
    if vm_lib is None:
        await bot.send_message(chat_id, "⚠️ Module aistv_vm chưa có trên máy này.")
        return False
    try:
        login = await asyncio.to_thread(vm_lib.whoami, pat)
    except Exception as e:
        await bot.send_message(chat_id, "❌ " + oneline(_redact_secrets(str(e)), 300),
                               reply_markup=vm_keyboard())
        return False
    save_vm_creds(pat=pat)
    await bot.send_message(
        chat_id,
        f"✅ Đã lưu PAT cho account <b>{esc(login)}</b> (đồng bộ Firebase).",
        parse_mode=HTML, reply_markup=vm_keyboard())
    return True


async def _vm_save_key(bot, chat_id: int, key: str, src_msg=None) -> bool:
    """Kiểm tra hình dạng Tailscale key rồi lưu."""
    key = (key or "").strip()
    if src_msg is not None:
        try:
            await src_msg.delete()          # xoá tin nhắn chứa key ngay
        except Exception:
            pass
    if not key.startswith("tskey-") or any(c.isspace() for c in key):
        await bot.send_message(chat_id,
                               "❌ Tailscale key phải bắt đầu bằng <code>tskey-</code>.",
                               parse_mode=HTML, reply_markup=vm_keyboard())
        return False
    save_vm_creds(tskey=key)
    mask = vm_lib.mask_value(key) if vm_lib else "***"
    await bot.send_message(chat_id,
                           f"✅ Đã lưu Tailscale key <code>{esc(mask)}</code> (đồng bộ Firebase).",
                           parse_mode=HTML, reply_markup=vm_keyboard())
    return True


async def _vm_take_input(msg, context: ContextTypes.DEFAULT_TYPE, chat, text: str,
                         mode: str) -> None:
    """Tin nhắn người dùng gửi sau khi bấm nút nhập PAT / Tailscale key."""
    bot = context.bot
    value = (text or "").strip().strip('"').strip("'")
    try:
        await msg.delete()                   # xoá tin nhắn chứa khoá
    except Exception:
        pass
    ok = (await _vm_save_key(bot, chat.id, value) if mode == "key"
          else await _vm_save_pat(bot, chat.id, value))
    if not ok:                               # nhập sai → chờ gửi lại
        VM_AWAIT[chat.id] = (mode, time.time())
        await bot.send_message(
            chat.id, "Gửi lại khoá hoặc bấm Huỷ.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✖️ Huỷ", callback_data="vm:cancel")]]))


async def _vm_edit_menu(q) -> None:
    try:
        await q.edit_message_text(vm_status_text(q.from_user.id), parse_mode=HTML,
                                  reply_markup=vm_keyboard())
    except Exception:
        pass


async def _on_vm_button(q, data: str) -> None:
    chat_id = q.message.chat_id if q.message else 0
    if not (q.from_user and is_owner(q.from_user.id)):
        await q.answer("Chỉ chủ bot dùng được.", show_alert=True)
        return
    if chat_id <= 0:
        await q.answer("Chỉ dùng trong chat riêng.", show_alert=True)
        return
    parts = data.split(":")
    act = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    bot = q.get_bot()

    if act == "win":
        try:
            win = vm_lib.normalize_windows(arg) if vm_lib else arg
        except Exception as e:
            await q.answer(oneline(str(e), 180), show_alert=True)
            return
        save_vm_creds(windows=win)
        await q.answer(f"Runner: {win}")
        await _vm_edit_menu(q)
        return
    if act == "min":
        try:
            minutes = vm_lib.clamp_minutes(arg) if vm_lib else int(arg)
        except Exception as e:
            await q.answer(oneline(str(e), 180), show_alert=True)
            return
        save_vm_creds(minutes=minutes)
        await q.answer(f"{minutes} phút")
        await _vm_edit_menu(q)
        return
    if act in ("pat", "key"):
        VM_AWAIT[chat_id] = (act, time.time())
        await q.answer()
        label = "PAT GitHub" if act == "pat" else "Tailscale auth key (tskey-…)"
        await bot.send_message(
            chat_id,
            f"🔑 Gửi <b>{label}</b> vào chat này.\n"
            "Tin nhắn chứa khoá sẽ bị xoá ngay sau khi lưu.",
            parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✖️ Huỷ", callback_data="vm:cancel")]]))
        return
    if act == "cancel":
        VM_AWAIT.pop(chat_id, None)
        await q.answer("Đã huỷ")
        try:
            await q.edit_message_text("✖️ Đã huỷ nhập.")
        except Exception:
            pass
        return
    if act == "forget":
        VM_AWAIT.pop(chat_id, None)
        clear_vm_creds()
        await q.answer("Đã xoá")
        await _vm_edit_menu(q)
        return
    if act == "create":
        creds = load_vm_creds()
        if not (creds.get("pat") or github_token()) or not creds.get("tailscale_key"):
            await q.answer("Cần nhập PAT và Tailscale key trước.", show_alert=True)
            return
        await q.answer("Đang tạo máy ảo…")
        await _vm_create_flow(bot, chat_id, "", "", "", "")
        return
    if act == "stop":
        await q.answer("Đang dừng…")
        _, text = await asyncio.to_thread(_vm_stop_sync, q.from_user.id)
        await bot.send_message(chat_id, text, parse_mode=HTML)
        await _vm_edit_menu(q)
        return
    await q.answer()


async def _vm_create_flow(bot, chat_id: int, pat: str, key: str,
                          win: str, minutes, *, as_guest: bool = False,
                          uid: int = 0, requested_by: str = "") -> None:
    """Tạo máy ảo từ creds truyền vào hoặc creds đã lưu; báo kết quả vào chat.

    `as_guest=True`: dùng GitHub token + Tailscale key của chủ bot, ép hạn mức
    khách và ghi nhận lần chạy để nút 🛑 hoạt động.
    """
    if vm_lib is None:
        await bot.send_message(chat_id, "⚠️ Module aistv_vm chưa có trên máy này — cập nhật bot rồi thử lại.")
        return
    explicit_pat = (pat or "").strip()
    creds = load_vm_creds()
    if as_guest:
        pat = str(creds.get("pat") or "").strip() or github_token()
        key = str(creds.get("tailscale_key") or "").strip()
        source = "owner" if str(creds.get("pat") or "").strip() else "admin"
    else:
        saved_pat = str(creds.get("pat") or "").strip()
        pat = explicit_pat or saved_pat or github_token()
        key = (key or "").strip() or str(creds.get("tailscale_key") or "").strip()
        source = "owner" if (explicit_pat or saved_pat) else "admin"
    if not pat or not key:
        await bot.send_message(
            chat_id,
            ("⚠️ Dịch vụ máy ảo chưa cấu hình — báo chủ bot." if as_guest
             else "⚠️ Thiếu PAT GitHub hoặc Tailscale key — bấm 🔑 để nhập."),
            reply_markup=guest_vm_keyboard(uid) if as_guest else vm_keyboard())
        return
    if as_guest:
        try:
            minutes = max(GUEST_VM_MINUTES[0],
                          min(GUEST_VM_MAX_MINUTES, int(minutes or GUEST_VM_MAX_MINUTES)))
        except (TypeError, ValueError):
            minutes = GUEST_VM_MAX_MINUTES
    uid = int(uid or (0 if as_guest else chat_id))

    wait = await bot.send_message(chat_id, "⏳ Đang tạo máy ảo… (fork repo, ghi secrets, kích hoạt workflow)")
    try:
        res = await asyncio.to_thread(
            vm_lib.create_vm, pat, key, BOT_TOKEN, chat_id,
            win or str(creds.get("windows") or ""), minutes or creds.get("minutes") or "",
            requested_by=requested_by)
    except Exception as e:
        text = "❌ " + oneline(_redact_secrets(str(e)), 500)
        try:
            await wait.edit_text(text)
        except Exception:
            await bot.send_message(chat_id, text)
        return
    if as_guest:
        if uid:
            _vm_run_record(uid, res, chat_id, res["minutes"], res["windows"], source)
            _vm_daily_bump(uid)
    else:
        save_vm_creds(pat=explicit_pat or None, tskey=key,
                      windows=res["windows"], minutes=res["minutes"])
        if uid:
            _vm_run_record(uid, res, chat_id, res["minutes"], res["windows"], source)
    if res["repo_state"] == "forked":
        state_note = "fork mới"
    elif res.get("sync") == "updated":
        state_note = "đã đồng bộ"
    elif res.get("sync") == "diverged":
        state_note = "fork lệch bản gốc"
    else:
        state_note = "sẵn sàng"
    url = res["run_url"] or res["workflow_url"]
    text = (
        "🖥 <b>Máy ảo Windows · Đang khởi tạo</b>\n\n"
        "<b>Phiên chạy</b>\n"
        f"<pre>Account  {esc(res['login'])}\n"
        f"Repo     {esc(res['repo'])}\n"
        f"Runner   {esc(res['windows'])} · {res['minutes']} phút\n"
        f"Trạng thái  {esc(state_note)}</pre>\n"
        f'🔗 <a href="{esc(url)}">Theo dõi trên GitHub Actions</a>\n\n'
        "<b>Tiếp theo</b>\n"
        "1. Chờ 2–3 phút để runner cài Tailscale và bật RDP.\n"
        "2. Bot gửi <b>tin nhắn riêng</b> cho người yêu cầu: IP, user, mật khẩu, "
        "Tailscale key và 4 bước vào máy.\n"
        "3. Dừng sớm: /vm → 🛑 Dừng máy ảo."
    )
    try:
        await wait.edit_text(text, parse_mode=HTML, disable_web_page_preview=True)
    except Exception:
        await bot.send_message(chat_id, text, parse_mode=HTML, disable_web_page_preview=True)


@guard(owner_only=True)
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rd = repo_dir()
    if not rd:
        await msg.reply_text("⚠️ Không tìm thấy repo (.git) để cập nhật.")
        return
    slug = current_repo_slug()
    origin = repo_remote_slug()
    if slug and slug != origin:
        rc, out = _gh_set_origin(rd, slug)
        if rc != 0:
            await msg.reply_text(f"⚠️ Không trỏ được origin về repo đích {slug}: {oneline(out, 300)}")
            return
    rc, dirty = _git(["status", "--porcelain"], rd)
    if dirty:
        await msg.reply_text(
            "⚠️ Repo có thay đổi chưa commit nên không tự pull (để tránh mất code).\n"
            f"<pre>{esc(dirty[-1200:])}</pre>\n"
            "Hãy commit/stash rồi gửi lại /update.",
            parse_mode=HTML)
        return
    await msg.reply_text("⏳ Đang kiểm tra bản mới trên GitHub…")
    _, before = _git(["rev-parse", "HEAD"], rd)
    rc, out = _git(["pull", "--ff-only"], rd, timeout=300)
    if rc != 0:
        await msg.reply_text(
            "⚠️ Không cập nhật được (có thể do chưa đăng nhập GitHub hoặc nhánh bị lệch).\n"
            f"<pre>{esc(out[-1500:])}</pre>\n"
            "Kiểm tra bằng /github và /github repo.",
            parse_mode=HTML)
        return
    _, after = _git(["rev-parse", "HEAD"], rd)
    if before == after:
        await msg.reply_text("✅ Bot đang ở bản mới nhất trên GitHub.")
        return
    _, changed = _git(["diff", "--name-only", before, after], rd)
    if "requirements.txt" in changed.splitlines():
        await msg.reply_text("📦 Có thư viện mới — đang cài…")
        try:
            await asyncio.to_thread(subprocess.run,
                                    [sys.executable, "-m", "pip", "install", "-q", "-U",
                                     "-r", str(rd / "requirements.txt")],
                                    timeout=600)
        except Exception as e:
            log.warning("Cài requirements thất bại: %s", e)
    await msg.reply_text(
        f"✅ Đã cập nhật <code>{esc(before[:7])}</code> → <code>{esc(after[:7])}</code>.\n"
        "🔄 Đang khởi động lại bot…",
        parse_mode=HTML)
    await asyncio.sleep(1)
    if not restart_bot():
        await msg.reply_text("ℹ️ Không tự khởi động lại được trong notebook. Hãy dừng ô và chạy lại lệnh run.")


@guard(owner_only=True)
async def cmd_push(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Đẩy code hiện tại lên GitHub để Windows CMD chạy run.bat là có bản mới."""
    msg = update.effective_message
    if not github_token():
        await msg.reply_text("⚠️ Chưa kết nối GitHub. Dùng /github login rồi thử lại.")
        return
    rd = repo_dir()
    if not rd:
        await msg.reply_text("⚠️ Không tìm thấy repo (.git) trên máy.")
        return
    slug = current_repo_slug() or repo_remote_slug()
    if not slug:
        await msg.reply_text("⚠️ Chưa đặt repo đích. Dùng /github repos để chọn.")
        return
    await msg.reply_text(f"⏳ Đang đẩy code lên <code>{esc(slug)}</code>…", parse_mode=HTML)
    try:
        out = await asyncio.to_thread(gh_push_code, slug)
    except Exception as e:
        await msg.reply_text(f"⚠️ {esc(oneline(str(e), 500))}", parse_mode=HTML)
        return
    await msg.reply_text(
        f"✅ Đã đẩy code lên <code>{esc(slug)}</code>.\n"
        "Windows chỉ cần chạy <code>run.bat</code> để nhận bản mới.\n"
        f"<pre>{esc(out[-500:])}</pre>", parse_mode=HTML)


@guard(owner_only=True)
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🔄 Đang khởi động lại bot…")
    await asyncio.sleep(0.5)
    if not restart_bot():
        await update.effective_message.reply_text(
            "ℹ️ Không thể tự khởi động lại trong notebook Colab. Hãy dừng ô và chạy lại lệnh run.")


@guard()
async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = oneline(" ".join(context.args), 500)
    if not text and update.effective_message.reply_to_message:
        text = oneline(_msg_brief(update.effective_message.reply_to_message), 500)
    if not text:
        await update.effective_message.reply_text(
            "Dùng: /remember <điều cần nhớ>\nHoặc trả lời (reply) một tin nhắn rồi gõ /remember để lưu chính tin đó.")
        return
    items = memory_items() + [f"- [{now():%d/%m/%Y}] {text}"]
    write_memory(items)
    await update.effective_message.reply_text("✅ Đã ghi vào trí nhớ dài hạn.")


@guard()
async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(build_memory(), parse_mode=HTML)


@guard(owner_only=True)
async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, items = update.effective_message, memory_items()
    arg = (context.args[0].lower() if context.args else "")
    if arg == "all":
        write_memory([])
        await msg.reply_text("🗑 Đã xoá toàn bộ trí nhớ dài hạn.")
    elif arg.isdigit() and 1 <= int(arg) <= len(items):
        removed = items.pop(int(arg) - 1)
        write_memory(items)
        await msg.reply_text(f"🗑 Đã xoá: {oneline(removed[2:], 120)}")
    else:
        await msg.reply_text("Dùng: /forget <số> hoặc /forget all (xem số bằng /memory)")


async def _reply_skills(message):
    for page in build_skills_pages():
        await message.reply_text(page, parse_mode=HTML, disable_web_page_preview=True)


def _parse_skill_add_args(args: list) -> tuple:
    source, force, name, ref = None, False, None, None
    allow_restricted = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--force", "-f"):
            force = True
        elif arg == "--allow-restricted":
            allow_restricted = True
        elif arg == "--name":
            if i + 1 >= len(args):
                raise ValueError("--name cần một giá trị.")
            i += 1
            name = args[i]
        elif arg == "--ref":
            if i + 1 >= len(args):
                raise ValueError("--ref cần một giá trị.")
            i += 1
            ref = args[i]
        elif source is None:
            source = arg
        else:
            raise ValueError(f"Tham số thừa: {arg}")
        i += 1
    return source, force, name, ref, allow_restricted


def _format_skill_install(result: dict) -> str:
    lines = []
    installed = result.get("installed") or []
    skipped = result.get("skipped") or []
    if installed:
        lines.append(f"✅ Đã cài {len(installed)} skill:")
        for item in installed[:10]:
            lines.append(
                f"• <code>{esc(item['name'])}</code> — {esc(oneline(item.get('description', ''), 110))} "
                f"({item.get('files', 0)} file, {max(1, item.get('bytes', 0) // 1024)} KB)"
            )
        if len(installed) > 10:
            lines.append(f"• … và {len(installed) - 10} skill khác (xem /skills)")
    if skipped:
        lines.append(f"⚠️ Bỏ qua {len(skipped)} skill:")
        for item in skipped[:4]:
            lines.append(f"• <code>{esc(str(item.get('name', '?')))}</code>: {esc(item.get('reason', ''))}")
        if len(skipped) > 4:
            lines.append(f"• … và {len(skipped) - 4} skill khác")
    all_warnings = result.get("warnings") or []
    for warning in all_warnings[:4]:
        lines.append(f"ℹ️ {esc(warning)}")
    if len(all_warnings) > 4:
        lines.append(f"ℹ️ … và {len(all_warnings) - 4} cảnh báo khác")
    if not installed and not skipped:
        lines.append("Không có skill nào được cài.")
    if installed:
        lines.append("Xem <code>/skills</code> · Chạy <code>/skill &lt;tên&gt; &lt;yêu cầu&gt;</code>")
    return "\n".join(lines)


async def _cmd_skill_add(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         source: str, force: bool, name: Optional[str],
                         ref: Optional[str], allow_restricted: bool = False) -> None:
    msg = update.effective_message
    if not is_owner(update.effective_user.id):
        await msg.reply_text("🔒 Chỉ chủ bot mới được cài skill.")
        return
    if skill_lib is None:
        await msg.reply_text("❌ Thiếu module <code>aistv_skills.py</code> — hãy /update rồi thử lại.", parse_mode=HTML)
        return
    status = await msg.reply_text("⏳ <i>Đang tải và cài skill…</i>", parse_mode=HTML)
    try:
        async with SKILL_INSTALL_LOCK:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    skill_lib.install, source, SKILLS_DIR,
                    force=force, name=name, ref=ref,
                    token=get_secret("GITHUB_TOKEN") or get_secret("GH_TOKEN"),
                    allow_restricted=allow_restricted,
                ),
                timeout=300,
            )
    except asyncio.TimeoutError:
        text = "⏱ Cài skill quá lâu (quá 5 phút). Kiểm tra mạng rồi thử lại với đường dẫn cụ thể hơn."
        try:
            await status.edit_text(text)
        except Exception:
            await msg.reply_text(text)
        return
    except Exception as exc:
        log.warning("Cài skill lỗi: %s", exc)
        text = f"❌ Không cài được skill: {esc(str(exc))}"
        try:
            await status.edit_text(text, parse_mode=HTML)
        except Exception:
            await msg.reply_text(text, parse_mode=HTML)
        return
    text = _format_skill_install(result)
    try:
        await status.edit_text(text, parse_mode=HTML, disable_web_page_preview=True)
    except Exception:
        await msg.reply_text(text, parse_mode=HTML, disable_web_page_preview=True)


@guard()
async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply_skills(update.effective_message)


@guard()
async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    args = context.args or []
    if not args:
        await msg.reply_text(
            "Dùng:\n"
            "/skill <tên> <yêu cầu> — chạy theo skill\n"
            "/skill <tên> — xem thông tin skill\n"
            "/skill add <github-url|owner/repo/path> [--force] [--name tên] [--ref nhánh] [--allow-restricted] — cài skill mới (chủ bot)"
        )
        return
    if args[0].lower() in ("add", "install", "cai", "cài"):
        try:
            source, force, name, ref, allow_restricted = _parse_skill_add_args(args[1:])
        except ValueError as exc:
            await msg.reply_text(f"⚠️ {exc}")
            return
        if not source:
            await msg.reply_text(
                "Dùng: /skill add <github-url|owner/repo/path> [--force] [--name tên] [--ref nhánh] [--allow-restricted]\n"
                "Ví dụ: /skill add mattpocock/skills/skills/engineering/tdd"
            )
            return
        await _cmd_skill_add(update, context, source, force, name, ref, allow_restricted)
        return
    name = args[0]
    body = find_skill(name)
    if body is None:
        await msg.reply_text(f"⚠️ Không tìm thấy skill “{name}”. Xem /skills.")
        return
    if len(args) == 1:
        info = skill_details(name)
        if info:
            await msg.reply_text(
                f"🧩 <b>{esc(name)}</b>\n{esc(info['description'])}\n\n"
                f"📁 <code>{esc(info['path'])}</code>\n"
                f"📦 {info['files']} file · {max(1, info['bytes'] // 1024)} KB\n\n"
                f"Dùng: <code>/skill {esc(name)} &lt;yêu cầu&gt;</code>",
                parse_mode=HTML,
            )
        return
    task = " ".join(args[1:])
    await respond(msg, context, update.effective_chat.id, task, skill=(name, body))


@guard()
async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    snap = sorted(snapshot().items(), key=lambda kv: kv[1][0], reverse=True)[:20]
    if not snap:
        await update.effective_message.reply_text("📂 Workspace chưa có file nào do agent tạo.")
        return
    rows = "\n".join(f"{esc(k)}  ({v[1] / 1024:.1f} KB)" for k, v in snap)
    await update.effective_message.reply_text(f"📂 <b>File mới nhất</b>\n<pre>{rows}</pre>\nTải: <code>/get &lt;đường dẫn&gt;</code>", parse_mode=HTML)


@guard()
async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.args:
        await msg.reply_text("Dùng: /get <đường dẫn trong workspace>")
        return
    try:
        p = (WORKSPACE / " ".join(context.args)).resolve()
        p.relative_to(WORKSPACE.resolve())
        assert p.is_file() and p.stat().st_size < 45 * 1024 * 1024
    except Exception:
        await msg.reply_text("⚠️ File không tồn tại, quá lớn (>45MB) hoặc nằm ngoài workspace.")
        return
    with p.open("rb") as fh:
        await msg.reply_document(fh, filename=p.name)


@guard(owner_only=True)
async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not (context.args and context.args[0].isdigit()):
        await update.effective_message.reply_text("Dùng: /allow <user_id>")
        return
    uid = int(context.args[0])
    if uid not in STATE["allowed"]:
        STATE["allowed"].append(uid)
        save_state()
    await update.effective_message.reply_text(f"✅ Đã cấp quyền cho {uid}.")


@guard(owner_only=True)
async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not (context.args and context.args[0].isdigit()):
        await update.effective_message.reply_text("Dùng: /deny <user_id>")
        return
    uid = int(context.args[0])
    if uid in STATE["allowed"]:
        STATE["allowed"].remove(uid)
        save_state()
    await update.effective_message.reply_text(f"🚫 Đã thu hồi quyền của {uid}.")


_KEY_ALIASES = {
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "jina": "JINA_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
    "cf": "CLOUDFLARE_API_TOKEN",
    "cloudflare_account": "CLOUDFLARE_ACCOUNT_ID",
    "cf_account": "CLOUDFLARE_ACCOUNT_ID",
    "together": "TOGETHER_API_KEY",
    "hf": "HF_TOKEN",
    "huggingface": "HF_TOKEN",
}


def _mask_secret(value: str) -> str:
    value = (value or "").strip()
    return f"{value[:4]}…{value[-3:]}" if len(value) > 8 else "…"


@guard(owner_only=True)
async def cmd_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem / đặt API key ngay trong chat — không cần mở terminal."""
    global GEMINI_READY
    msg = update.effective_message
    args = list(context.args or [])

    if not args:
        lines = ["🔑 <b>API key đang dùng</b>"]
        for name in dict.fromkeys(_KEY_ALIASES.values()):
            value = get_secret(name)
            state = f"✅ {esc(_mask_secret(value))}" if value else "— chưa có"
            lines.append(f"• <code>{name}</code>: {state}")
        lines.append("\nĐặt: <code>/key gemini &lt;key&gt;</code> (tin nhắn chứa key sẽ bị xoá ngay).")
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
        return

    alias = args[0].lower().lstrip("-")
    name = _KEY_ALIASES.get(alias) or (args[0].upper() if args[0].upper() in _KEY_ALIASES.values() else "")
    if not name:
        await msg.reply_text(
            "Dùng: <code>/key gemini|groq|openai|jina|cloudflare|cf_account|together|hf &lt;giá trị&gt;</code>\n"
            "Xem trạng thái: <code>/key</code>", parse_mode="HTML")
        return

    value = " ".join(args[1:]).strip().strip("\"'")
    if not value:
        await msg.reply_text(f"Dùng: <code>/key {alias} &lt;giá trị&gt;</code>", parse_mode="HTML")
        return

    try:
        path = save_env_var(name, value)
    except Exception as e:
        await msg.reply_text(f"❌ Không lưu được: {esc(oneline(str(e), 200))}", parse_mode="HTML")
        return

    os.environ[name] = value
    if name == "GEMINI_API_KEY":
        GEMINI_READY = True
    if CLOUD_ENABLED:
        asyncio.create_task(cloud_push_secrets())      # mã hoá + đẩy lên cloud ngay

    # Xoá tin nhắn gốc để key không nằm lại trong lịch sử chat.
    gone = False
    try:
        await msg.delete()
        gone = True
    except Exception:
        pass

    note = ("\n🗑 Đã xoá tin nhắn chứa key." if gone
            else "\n⚠️ Không xoá được tin nhắn của bạn — nên tự xoá để tránh lộ key.")
    await update.effective_chat.send_message(
        f"✅ Đã lưu <code>{name}</code> = <code>{esc(_mask_secret(value))}</code>\n"
        f"<i>{esc(str(path))}</i>{note}\n"
        + ("Dùng ngay: gửi ảnh hoặc <code>/see &lt;đường dẫn&gt;</code>."
           if name == "GEMINI_API_KEY" else "Đã áp dụng cho phiên này."),
        parse_mode="HTML")


GUEST_SYSTEM = (
    "Bạn là trợ lý AI trong bot Telegram, đang trả lời một người KHÔNG phải chủ bot.\n"
    "Bạn chỉ trả lời bằng văn bản: không có công cụ, không chạy lệnh, không đọc/ghi tệp, "
    "không truy cập web/URL, không xem ảnh/video, không tạo ảnh, không đọc dữ liệu hay lịch sử của chủ bot.\n"
    "Bạn được phép giải thích, dạy học, viết code mẫu và giải bài tập. Code đặt trong khối ```ngôn_ngữ```.\n"
    "Nếu được yêu cầu đọc file, chạy lệnh hay lấy dữ liệu riêng, nói ngắn gọn rằng chỉ chủ bot mới làm được.\n"
    "Trả lời gọn (thường ≤ 20 dòng), đúng ngôn ngữ người dùng; không bịa là đã thực hiện hành động. "
    "Không viết link ảnh; nếu cần ảnh, nói người dùng gõ 'vẽ ảnh …'.\n"
    "Máy ảo Windows: nếu người dùng muốn tạo/dừng máy ảo, hướng dẫn họ nhắn riêng bot và gõ "
    "/vm (cần xác minh email .com trước). Không bao giờ tự bịa thông tin đăng nhập, IP hay mật khẩu — "
    "bot gửi các thông tin đó qua tin nhắn riêng."
)
GUEST_CODE_HINT = (
    "\nNgười dùng đang hỏi về code: đưa code chạy được, ngắn và đúng, kèm 1-2 dòng giải thích. "
    "Không bịa API không tồn tại; nếu thiếu thông tin thì hỏi lại 1 câu."
)
GUEST_HELP_TEXT = (
    "🤖 <b>AI STV — trợ lý miễn phí trong nhóm</b>\n"
    "Nhắc <code>@tên_bot</code>, reply tin của bot hoặc dùng <code>/ask</code>:\n"
    "• Hỏi đáp, giải thích, viết/sửa code…\n"
    "• <code>vẽ ảnh …</code>, <code>sơ đồ tư duy …</code>, <code>biểu đồ …</code>\n"
    "• Gửi ảnh/video kèm câu hỏi — Gemini đọc miễn phí (trong nhóm: reply tin bot "
    "hoặc ghi <code>@tên_bot</code> vào chú thích)\n"
    "• <code>/ask &lt;câu hỏi&gt;</code> — chắc chắn bot nhận được trong nhóm\n"
    "• <code>/model</code> — xem/đổi model trả lời (mặc định Gemini)\n"
    "• <code>/new</code> — xoá ngữ cảnh riêng của bạn\n"
    "• <code>/vm</code> — máy ảo Windows dùng thử (chat riêng, cần xác minh email .com)\n"
    "Giới hạn: 10 tin/phút, 1 ảnh/45 giây, ảnh/video cách nhau 10 giây mỗi người. "
    "Lệnh quản trị chỉ dành cho chủ bot."
)
GUEST_HIST: dict = {}
GUEST_LOCKS = defaultdict(asyncio.Lock)
GUEST_LAST: dict = {}
GUEST_LAST_MEDIA: dict = {}
GUEST_LAST_VISION: dict = {}
GUEST_SEM = asyncio.Semaphore(GUEST_CONCURRENCY)
GUEST_MEDIA_SEM = asyncio.Semaphore(GUEST_MEDIA_PARALLEL)
GUEST_VISION_SEM = asyncio.Semaphore(GUEST_VISION_PARALLEL)
GUEST_MODEL_BY_USER: dict = {}
GUEST_ACTIVE = {"chat": GUEST_FEATURES, "media": GUEST_MEDIA, "vision": GUEST_VISION}
GUEST_BANS: dict = {}
GUEST_NOTICE_AT: dict = {}


class _WindowLimit:
    """Giới hạn số lần trong một cửa sổ thời gian, tách riêng theo từng khoá."""

    def __init__(self, count: int, window: float):
        self.count = max(1, int(count))
        self.window = float(window)
        self.events: dict = {}

    def check(self, key, now: float = None) -> float:
        """Trả 0 nếu được phép; ngược lại trả số giây cần chờ."""
        now = time.monotonic() if now is None else now
        self._prune(now)
        items = [t for t in self.events.get(key, ()) if now - t < self.window]
        if len(items) >= self.count:
            self.events[key] = items
            return max(0.0, self.window - (now - items[0]))
        items.append(now)
        self.events[key] = items
        return 0.0

    def _prune(self, now: float) -> None:
        if len(self.events) < 512:
            return
        for key, items in list(self.events.items()):
            alive = [t for t in items if now - t < self.window]
            if alive:
                self.events[key] = alive
            else:
                self.events.pop(key, None)


GUEST_TEXT_LIMIT = _WindowLimit(GUEST_RATE, 60)
GUEST_CHAT_LIMIT = _WindowLimit(GUEST_CHAT_RATE, 60)
GUEST_MEDIA_LIMIT = _WindowLimit(GUEST_MEDIA_RATE, 3600)
GUEST_MEDIA_CHAT_LIMIT = _WindowLimit(GUEST_MEDIA_CHAT_RATE, 3600)
GUEST_VISION_LIMIT = _WindowLimit(GUEST_VISION_RATE, 3600)
GUEST_VISION_CHAT_LIMIT = _WindowLimit(GUEST_VISION_CHAT_RATE, 3600)

_GUEST_MINDMAP_RE = re.compile(r"(?i)\b(sơ đồ tư duy|sodo tu duy|mind\s?map|mindmap)\b")
_GUEST_INFO_RE = re.compile(r"(?i)\b(infographic|đồ hoạ thông tin|do hoa thong tin)\b")
_GUEST_CHART_RE = re.compile(r"(?i)\b(biểu đồ|bieu do|chart)\b")
_GUEST_IMAGE_RE = re.compile(
    r"(?i)(^|\b)(vẽ|draw|paint|sketch|generate|create|make|tạo|sinh|thiết kế)\b"
    r".{0,60}\b(ảnh|hình|image|picture|photo|logo|poster|banner|avatar|icon)\b")
_GUEST_CODE_RE = re.compile(
    r"(?i)\b(code|coding|lập trình|lap trinh|thuật toán|thuat toan|python|javascript|"
    r"typescript|java|kotlin|swift|php|sql|html|css|react|node(?:js)?|api|script|"
    r"function|hàm|class|bug|debug|sửa lỗi|sua loi)\b")
_GUEST_SUBJECT_RE = re.compile(
    r"(?i)^\s*(hãy\s+|giúp (tôi|mình)\s+)?(vẽ|tạo|thiết kế|làm|draw|create|make|generate)\s+"
    r"(cho (tôi|mình)\s+)?(một\s+|1\s+)?"
    r"(sơ đồ tư duy|mind\s?map|infographic|biểu đồ|chart|ảnh|hình|image|picture|photo)?\s*"
    r"(về|of|about|:)?\s*")


def guest_intent(text: str) -> str:
    """Phân loại yêu cầu của khách: mindmap/infographic/chart/image/code/chat."""
    value = (text or "").strip()
    if not value:
        return "chat"
    if _GUEST_MINDMAP_RE.search(value):
        return "mindmap"
    if _GUEST_INFO_RE.search(value):
        return "infographic"
    if _GUEST_CHART_RE.search(value):
        return "chart"
    if re.match(r"(?i)^\s*(vẽ|draw|paint|sketch)\b", value) or _GUEST_IMAGE_RE.search(value):
        return "image"
    if _GUEST_CODE_RE.search(value):
        return "code"
    return "chat"


def _guest_subject(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"(?i)^\s*(mind\s?map|sơ đồ tư duy|infographic|biểu đồ|chart)\s*"
                   r"(về|of|about|:|-)?\s*", "", value)
    value = _GUEST_SUBJECT_RE.sub("", value).strip(" :,-")
    return (value or (text or "").strip())[:800]


def _guest_key(chat, user) -> tuple:
    return (chat.id, user.id)


def _guest_banned(user_id: int) -> bool:
    until = GUEST_BANS.get(user_id)
    if until is None:
        return False
    if until and until < time.time():
        GUEST_BANS.pop(user_id, None)
        return False
    return True


def _guest_model(user_id: int) -> str:
    return GUEST_MODEL_BY_USER.get(user_id) or GUEST_MODEL


async def _guest_model_command(update, context) -> None:
    msg, user = update.effective_message, update.effective_user
    args = [str(a).strip() for a in (context.args or []) if str(a).strip()]
    current = _guest_model(user.id)
    if not args:
        rows = "\n".join(
            f"{i}. <code>{esc(m)}</code>" + ("  ← đang dùng" if m == current else "")
            for i, m in enumerate(GUEST_MODEL_OPTIONS, 1))
        await msg.reply_text(
            f"🧠 Model của bạn: <code>{esc(current)}</code>\n{rows}\n"
            "Đổi bằng <code>/model &lt;số&gt;</code> hoặc <code>/model &lt;tên&gt;</code>.",
            parse_mode=HTML)
        return
    choice = args[0]
    model = ""
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(GUEST_MODEL_OPTIONS):
            model = GUEST_MODEL_OPTIONS[idx - 1]
    elif choice in GUEST_MODEL_OPTIONS:
        model = choice
    if not model:
        await msg.reply_text(
            "Model đó chưa mở cho khách. Xem danh sách bằng /model; "
            "chủ bot thêm model bằng biến AISTV_GUEST_MODELS.", parse_mode=HTML)
        return
    GUEST_MODEL_BY_USER[user.id] = model
    await msg.reply_text(f"✅ Model của bạn: <code>{esc(model)}</code>", parse_mode=HTML)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask: trong nhóm luôn được bot nhận, không cần @mention (khách chat miễn phí)."""
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    text = " ".join(str(a) for a in (context.args or [])).strip()
    if not text and msg.reply_to_message:
        text = (msg.reply_to_message.text or msg.reply_to_message.caption or "").strip()
    if not text:
        await msg.reply_text(
            "Dùng: <code>/ask &lt;câu hỏi&gt;</code> hoặc reply một tin rồi gõ /ask.",
            parse_mode=HTML)
        return
    if authorized(user.id, chat.type):
        await _dispatch_text(msg, context, chat, text, direct=True)
    elif GUEST_CHAT:
        if chat.type == "private" and GUEST_VM and _guest_vm_wants(text):
            await _guest_vm_entry(msg, chat, user)
            return
        await _guest_answer(msg, context, chat, user, text, direct=True)
    else:
        await _deny_guest(update, context)


def _guest_hist(key) -> list:
    hist = GUEST_HIST.get(key)
    if hist is None:
        if len(GUEST_HIST) >= GUEST_HIST_USERS:
            GUEST_HIST.pop(next(iter(GUEST_HIST)), None)
        hist = GUEST_HIST.setdefault(key, [])
    return hist


def _guest_notice(key, gap: float = 25.0) -> bool:
    """Chỉ gửi 1 tin nhắc trong `gap` giây cho mỗi khoá (chống spam thông báo)."""
    now = time.monotonic()
    if now - GUEST_NOTICE_AT.get(key, 0.0) < gap:
        return False
    GUEST_NOTICE_AT[key] = now
    return True


def _thread_kw(msg) -> dict:
    kw = {}
    if getattr(msg, "is_topic_message", False) and getattr(msg, "message_thread_id", None):
        kw["message_thread_id"] = msg.message_thread_id
    return kw


def _strip_image_links(text: str, urls: list) -> str:
    out = text or ""
    for url in urls:
        out = re.sub(r"!\[[^\]]*\]\(\s*" + re.escape(url) + r"\s*\)", "", out)
        out = re.sub(r"(?i)https?://" + re.escape(url.split("://", 1)[-1]), "", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


async def _guest_send_url_images(msg, chat, urls: list) -> int:
    """Tải ảnh Gemini trả về trong câu trả lời và gửi thành ảnh thật (không gửi link trần)."""
    sent = 0
    if BOT_OBJ is None:
        return 0
    for url in (urls or [])[:2]:
        raw, mime, err = await asyncio.to_thread(web2api.download_image, url)
        if not raw:
            log.info("Ảnh Gemini không tải được: %s", oneline(_redact_secrets(str(err)), 160))
            continue
        try:
            import aistv_image as _img
            path = await asyncio.to_thread(_img._save, raw, mime)
            ready = await asyncio.to_thread(_photo_for_telegram, path)
            with open(ready, "rb") as fh:
                await BOT_OBJ.send_photo(
                    chat.id, photo=fh, caption="🖼 <i>Ảnh từ Gemini</i>",
                    parse_mode=HTML, reply_to_message_id=msg.message_id, **_thread_kw(msg))
            sent += 1
        except Exception as exc:
            log.warning("Gửi ảnh Gemini lỗi: %s", oneline(_redact_secrets(str(exc)), 160))
    return sent


async def _guest_media_reply(msg, context, chat, user, text: str, kind: str = "image",
                             prompt: str = "", style: str = "", aspect: str = "1:1") -> bool:
    """Khách tạo ảnh / sơ đồ qua nguồn miễn phí (Gemini, dự phòng Pollinations)."""
    if not GUEST_ACTIVE["media"]:
        await msg.reply_text("🎨 Tạo ảnh đang tắt cho khách. Chủ bot có thể bật lại bằng /guest images on.")
        return True
    key = _guest_key(chat, user)
    now = time.monotonic()
    wait = GUEST_MEDIA_GAP - (now - GUEST_LAST_MEDIA.get(key, 0.0))
    if wait > 0:
        if _guest_notice(("media", key)):
            await msg.reply_text(f"⏳ Mỗi người tạo ảnh cách nhau {GUEST_MEDIA_GAP}s. "
                                 f"Thử lại sau {int(wait) + 1}s nhé.")
        return True
    wait = GUEST_MEDIA_LIMIT.check(key)
    if wait > 0:
        if _guest_notice(("media-hour", key)):
            await msg.reply_text(f"⏳ Bạn đã dùng hết {GUEST_MEDIA_RATE} ảnh/giờ. "
                                 f"Còn khoảng {int(wait // 60) + 1} phút.")
        return True
    wait = GUEST_MEDIA_CHAT_LIMIT.check(chat.id)
    if wait > 0:
        if _guest_notice(("media-chat", chat.id)):
            await msg.reply_text("⏳ Nhóm tạo ảnh hơi nhiều, thử lại sau ít phút nhé.")
        return True
    GUEST_LAST_MEDIA[key] = now

    label = {"mindmap": "sơ đồ tư duy", "infographic": "infographic",
             "chart": "biểu đồ"}.get(kind, "ảnh")
    topic = (prompt or _guest_subject(text))[:800]
    if not topic:
        await msg.reply_text("Bạn muốn tạo ảnh/sơ đồ về gì?")
        return True
    status = await msg.reply_text(f"🎨 <i>Đang tạo {label}…</i>", parse_mode=HTML)
    acquired = False
    try:
        await asyncio.wait_for(GUEST_MEDIA_SEM.acquire(), timeout=15)
        acquired = True
        data = await generate_image_job(topic, style, aspect, kind, provider="guest",
                                        timeout=GUEST_MEDIA_TIMEOUT)
        await send_generated_image(chat.id, data, reply_to=msg.message_id, **_thread_kw(msg))
        try:
            await status.delete()
        except Exception:
            pass
    except asyncio.TimeoutError:
        try:
            await status.edit_text("⏳ Đang có người tạo ảnh, bạn thử lại sau ít phút nhé.",
                                   parse_mode="HTML")
        except Exception:
            pass
    except Exception as exc:
        detail = oneline(_redact_secrets(str(exc)), 300)
        log.warning("Tạo %s cho khách lỗi: %s", label, detail)
        try:
            await status.edit_text(
                f"⚠️ Chưa tạo được {label}.\n<code>{esc(detail)}</code>", parse_mode="HTML")
        except Exception:
            pass
    finally:
        if acquired:
            GUEST_MEDIA_SEM.release()
    return True


def _guest_vision_ready(kind: str) -> bool:
    """Web2API đã vá đọc ảnh (image) hoặc video chưa."""
    if web2api is None:
        return False
    try:
        if not web2api.enabled():
            return False
        return bool(web2api.image_patch_ready() if kind == "image"
                    else web2api.media_patch_ready())
    except Exception:
        return False


def _guest_vision_args(kind: str, source: str, question: str) -> list:
    """Lệnh aistv_watch.py chỉ dùng Web2API — không chạm key Gemini của chủ."""
    ask = _vision_question(kind, question)
    if kind == "image":
        return ["image", source, "--engine", "web2api", "--json", "--question", ask]
    return ["watch", source, "--engine", "web2api", "--detail", "balanced",
            "--json", "--question", ask]


async def _guest_vision_gate(msg, chat, user, label: str) -> bool:
    """Kiểm tra giới hạn trước khi tải file; True = bị chặn (đã báo)."""
    key = _guest_key(chat, user)
    now = time.monotonic()
    wait = GUEST_VISION_GAP - (now - GUEST_LAST_VISION.get(key, 0.0))
    if wait > 0:
        if _guest_notice(("vision-gap", key)):
            await msg.reply_text(f"⏳ Mỗi {label} cách nhau {GUEST_VISION_GAP}s. "
                                 f"Thử lại sau {int(wait) + 1}s nhé.")
        return True
    wait = GUEST_VISION_LIMIT.check(key)
    if wait > 0:
        if _guest_notice(("vision-hour", key)):
            await msg.reply_text(f"⏳ Bạn đã dùng hết {GUEST_VISION_RATE} lượt đọc {label}/giờ. "
                                 f"Còn khoảng {int(wait // 60) + 1} phút.")
        return True
    wait = GUEST_VISION_CHAT_LIMIT.check(chat.id)
    if wait > 0:
        if _guest_notice(("vision-chat", chat.id)):
            await msg.reply_text("⏳ Nhóm đang gửi nhiều ảnh/video, thử lại sau ít phút nhé.")
        return True
    GUEST_LAST_VISION[key] = now
    return False


async def _guest_vision_reply(msg, chat, user, source: str, question: str, kind: str) -> None:
    """Khách nhờ Gemini đọc ảnh/video qua Web2API (miễn phí, không dùng key chủ)."""
    label = "ảnh" if kind == "image" else "video"
    started = time.monotonic()
    status = await msg.reply_text(f"👁️ <i>Đang đọc {label}…</i>", parse_mode=HTML)
    acquired = False
    try:
        await asyncio.wait_for(GUEST_VISION_SEM.acquire(), timeout=20)
        acquired = True
        rc, out, err = await asyncio.to_thread(
            _watch_cli, _guest_vision_args(kind, source, question), GUEST_VISION_TIMEOUT)
        text, _model = _vision_parse(out) if rc == 0 else ("", "")
        if not text:
            lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
            detail = _redact_secrets(lines[-1] if lines else "lỗi không rõ")
            raise RuntimeError(detail)
        try:
            await status.delete()
        except Exception:
            pass
        await send_rich(msg, _clip(text, 9000),
                        f"<i>👁️ AI STV · {time.monotonic() - started:.1f}s</i>")
        hist = _guest_hist(_guest_key(chat, user))
        if GUEST_HISTORY:
            hist += [{"role": "user", "content": _clip(f"[{label}] {question}".strip(), 600)},
                     {"role": "assistant", "content": _clip(text, 3000)}]
            del hist[:-GUEST_HISTORY * 2]
    except asyncio.TimeoutError:
        try:
            await status.edit_text("⏳ Đang có người gửi ảnh/video, bạn thử lại sau ít phút nhé.",
                                   parse_mode=HTML)
        except Exception:
            pass
    except Exception as exc:
        detail = oneline(_redact_secrets(str(exc)), 400)
        log.warning("Khách đọc %s lỗi: %s", label, detail)
        try:
            await status.edit_text(
                f"⚠️ Chưa đọc được {label}.\n<code>{esc(detail)}</code>", parse_mode=HTML)
        except Exception:
            pass
    finally:
        if acquired:
            GUEST_VISION_SEM.release()


async def _guest_media_read(update, context, kind: str, media, name: str, mime: str) -> None:
    """Tải ảnh/video của khách vào thư mục tạm riêng, đọc xong xoá ngay."""
    msg, chat, user = (update.effective_message, update.effective_chat,
                       update.effective_user)
    if not (msg and chat and user):
        return
    caption = (msg.caption or "").strip()
    if chat.type != "private":
        if not _addressed_to_bot(msg, context, caption):
            return
        caption = _strip_bot_mention(caption, context)
    if _guest_banned(user.id):
        return
    label = "ảnh" if kind == "image" else "video"
    if not GUEST_ACTIVE["vision"]:
        await msg.reply_text(f"👁️ Đọc {label} đang tắt cho khách.")
        return
    if not _guest_vision_ready(kind):
        await msg.reply_text(
            f"⚠️ Chưa bật đọc {label} miễn phí. "
            "Chủ bot gửi <code>/gemini restart</code> để bật.", parse_mode=HTML)
        return
    if kind == "video":
        duration = int(getattr(media, "duration", 0) or 0)
        if duration > GUEST_VISION_MAX_SEC:
            await msg.reply_text(
                f"⚠️ Video dài {duration // 60} phút; khách xem tối đa "
                f"{GUEST_VISION_MAX_SEC // 60} phút.")
            return
    if await _guest_vision_gate(msg, chat, user, label):
        return
    tmp = Path(tempfile.mkdtemp(prefix="aistv_guest_vision_"))
    try:
        dest = await _download_telegram_file(msg, media, name, mime, folder=tmp)
        if not dest:
            return
        await _guest_vision_reply(msg, chat, user, str(dest), caption, kind)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _guest_typing(bot, chat_id: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.5)
        except asyncio.TimeoutError:
            pass


async def _guest_answer(msg, context, chat, user, text: str, direct: bool = False) -> None:
    """Khách: Gemini miễn phí cho chat/code/ảnh/sơ đồ/đọc media; không tool, không dữ liệu của chủ."""
    if not GUEST_ACTIVE["chat"] or _guest_banned(user.id):
        return
    if chat.type != "private" and not direct:
        if not _addressed_to_bot(msg, context, text):
            return
        text = _strip_bot_mention(text, context)
    text = (text or "").strip()
    if not text:
        return
    if web2api is None:
        await msg.reply_text("⚠️ Trợ lý chữ đang không sẵn sàng.")
        return
    key = _guest_key(chat, user)
    wait = GUEST_TEXT_LIMIT.check(key)
    if wait > 0:
        if _guest_notice(("rate", key)):
            await msg.reply_text(f"⏳ Bạn gửi hơi nhanh — thử lại sau {int(wait) + 1}s nhé.")
        return
    wait = GUEST_CHAT_LIMIT.check(chat.id)
    if wait > 0:
        if _guest_notice(("rate-chat", chat.id)):
            await msg.reply_text("⏳ Nhóm đang gửi nhiều yêu cầu, chờ một chút nhé.")
        return

    intent = guest_intent(text)
    if intent in ("image", "mindmap", "infographic", "chart"):
        await _guest_media_reply(msg, context, chat, user, text, kind=intent)
        return

    wait = GUEST_MIN_GAP - (time.monotonic() - GUEST_LAST.get(key, 0.0))
    if wait > 0:
        await asyncio.sleep(min(wait, GUEST_MIN_GAP))   # giữ nhịp, không bỏ tin của khách
    GUEST_LAST[key] = time.monotonic()
    lock = GUEST_LOCKS[key]
    if lock.locked():
        await msg.reply_text("⏳ Đang trả lời tin trước của bạn…")
        return

    text = _clip(text, 4000)
    model = _guest_model(user.id)
    started = time.monotonic()
    status = await msg.reply_text("💬 <i>Đang trả lời…</i>", parse_mode=HTML)
    stop = asyncio.Event()
    typing = asyncio.create_task(_guest_typing(context.bot, chat.id, stop))
    answer, err = "", ""
    acquired = False
    try:
        async with lock:
            try:
                await asyncio.wait_for(GUEST_SEM.acquire(), timeout=min(45, GUEST_TIMEOUT))
                acquired = True
                ready = await asyncio.to_thread(web2api.ensure_server)
                if not ready:
                    err = "Gemini chưa sẵn sàng"
                else:
                    system = GUEST_SYSTEM + (GUEST_CODE_HINT if intent == "code" else "")
                    messages = [{"role": "system", "content": system}]
                    messages += _guest_hist(key)
                    messages.append({"role": "user", "content": text})
                    answer, err = await asyncio.to_thread(
                        web2api.chat, messages, model, GUEST_TIMEOUT)
            finally:
                if acquired:
                    GUEST_SEM.release()
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        await typing
    answer = (answer or "").strip()
    if not answer:
        log.warning("Web2API trả lời khách lỗi: %s", _redact_secrets(str(err)))
        try:
            await status.edit_text(
                "⚠️ Trợ lý chữ đang bận, bạn thử lại sau ít phút nhé.", parse_mode=HTML)
        except Exception:
            pass
        return
    try:
        await status.delete()
    except Exception:
        pass
    urls = web2api.extract_image_urls(answer)
    if urls:
        answer = _strip_image_links(answer, urls)
        sent = await _guest_send_url_images(msg, chat, urls)
        if not answer and not sent:
            answer = "⚠️ Ảnh Gemini trả về không tải được (link có thể đã hết hạn)."
    hist = _guest_hist(key)
    if GUEST_HISTORY:
        hist += [{"role": "user", "content": _clip(text, 2000)},
                 {"role": "assistant", "content": _clip(answer, 4000)}]
        del hist[:-GUEST_HISTORY * 2]
    if answer:
        footer = f"<i>💬 AI STV · {time.monotonic() - started:.1f}s</i>"
        await send_rich(msg, answer, footer)


_RESUME_WORDS = re.compile(
    r"(?i)^\s*(?:hãy\s+|hay\s+)?(?:tiếp tục|tiep tuc|làm tiếp|lam tiep)\s+"
    r"(?:công việc|cong viec|việc|viec|cái việc|cai viec)\b"
    r"|\b(?:tiếp tục|tiep tuc)\s+(?:việc|viec)\s+(?:đang làm|dang lam|đang dở|dang do|cũ|cu)\b"
    r"|^\s*(?:continue|resume)(?:\s+the)?\s+work\b"
)


async def _dispatch_text(msg, context, chat, text: str, direct: bool = False):
    """Dùng chung cho tin nhắn gõ tay và tin nhắn thoại đã chép lời (chỉ chủ bot)."""
    text = (text or "").strip()
    if not text:
        return
    user = getattr(msg, "from_user", None)
    if not (user and authorized(user.id, chat.type)):
        return                                       # khách không bao giờ chạm vào luồng hỏi-đáp của agent
    pending = VM_AWAIT.get(chat.id)
    if pending and chat.type == "private":           # đang chờ PAT / Tailscale key từ nút /vm
        mode, started = pending
        VM_AWAIT.pop(chat.id, None)
        if time.time() - started <= VM_AWAIT_SECONDS:
            await _vm_take_input(msg, context, chat, text, mode)
            return
    with ASK_LOCK:
        ask_id = ASK_BY_CHAT.get(chat.id)
    if ask_id:                                       # đang chờ agent hỏi → tin nhắn này là câu trả lời
        rec = _ask_pop(ask_id, text)
        if rec:
            try:
                if rec.get("msg"):
                    await rec["msg"].edit_text(
                        f"❓ {esc(_clip(rec['question'], 1500))}\n\n✅ <b>Trả lời:</b> {esc(_clip(text, 500))}",
                        parse_mode=HTML)
            except Exception:
                pass
            return
    if (chat.type == "private" and is_owner(user.id) and workmod
            and _RESUME_WORDS.search(text)):
        if await _resume_from_remote(chat.id, "", msg):
            return
    if chat.type != "private" and not direct:        # trong nhóm: chỉ trả lời khi được nhắc tên / reply
        if not _addressed_to_bot(msg, context, text):
            return
        text = _strip_bot_mention(text, context)
    await respond(msg, context, chat.id, text, quoted_msg=msg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    user = update.effective_user
    if not (msg and chat and user):
        return
    text = msg.text or ""
    if not text.strip():
        return
    if authorized(user.id, chat.type):
        await _dispatch_text(msg, context, chat, text)
        return
    if not GUEST_CHAT:
        await _deny_guest(update, context)
        return
    if chat.type == "private" and await _vm_verify_input(msg, context, chat, user, text):
        return
    if GUEST_VM and _guest_vm_wants(text):
        if chat.type != "private" and not _addressed_to_bot(msg, context, text):
            await _guest_answer(msg, context, chat, user, text)
            return
        await _guest_vm_entry(msg, chat, user)
        return
    await _guest_answer(msg, context, chat, user, text)


_VOICE_EXTS = {
    "audio/ogg": ".ogg", "audio/opus": ".ogg", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/webm": ".webm", "audio/flac": ".flac", "audio/x-flac": ".flac",
}


@guard()
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tin nhắn thoại / file âm thanh → chép lời bằng Gemini → xử lý như tin nhắn chữ."""
    msg = update.effective_message
    if update.effective_chat.type != "private":
        return
    media = msg.voice or msg.audio
    if not media:
        return
    mime = (getattr(media, "mime_type", "") or ("audio/ogg" if msg.voice else "audio/mpeg")).lower()
    name = getattr(media, "file_name", "") or ""
    if not Path(name).suffix:
        ext = _VOICE_EXTS.get(mime, ".ogg")
        name = f"voice_{getattr(media, 'file_unique_id', int(time.time()))}{ext}"

    status = await msg.reply_text("🎙️ <i>Đang nghe…</i>", parse_mode=HTML)
    dest = await _download_telegram_file(msg, media, name, mime)
    if not dest:
        try:
            await status.delete()
        except Exception:
            pass
        return
    if not vision_ready():
        try:
            await status.edit_text(
                "⚠️ Cần GEMINI_API_KEY hoặc Gemini đã bật media để nghe tin nhắn thoại.\n"
                "Gửi: <code>/key gemini &lt;key&gt;</code> hoặc <code>/gemini restart</code>",
                parse_mode=HTML)
        except Exception:
            pass
        return

    timeout = int(os.getenv("VOICE_TIMEOUT", "330") or 330)
    rc, out, err = await asyncio.to_thread(
        _watch_cli, ["voice", str(dest), "--mime", mime, "--json"], timeout)
    text = ""
    if rc == 0:
        try:
            text = (json.loads(out or "{}").get("text") or "").strip()
        except Exception:
            text = (out or "").strip()
    if not text:
        lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
        detail = _redact_secrets(lines[-1] if lines else "lỗi không rõ")
        try:
            await status.edit_text(
                f"⚠️ Không nghe được tin nhắn thoại.\n<code>{esc(detail[:1500])}</code>",
                parse_mode=HTML)
        except Exception:
            pass
        return

    try:
        await status.edit_text(f"🎙️ <b>Nghe được:</b> {esc(_clip(text, 1200))}", parse_mode=HTML)
    except Exception:
        pass
    await _dispatch_text(msg, context, update.effective_chat, text)


def _redact_secrets(text: str) -> str:
    text = str(text or "")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TELEGRAM_BOT_TOKEN"):
        value = get_secret(name)
        if value:
            text = text.replace(value, "***")
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "***", text)
    text = re.sub(r"\bAQ\.[0-9A-Za-z_-]{15,}\b", "***", text)
    text = re.sub(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", "***", text)
    text = re.sub(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}\b", "***", text)
    text = re.sub(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b", "***", text)
    text = re.sub(r"\btskey-[0-9A-Za-z_-]{10,}\b", "***", text)
    return text


def _watch_cli(args: list, timeout: int = 900):
    """Chạy aistv_watch.py bằng đúng Python của bot; trả về (code, stdout, stderr)."""
    if not WATCH_CLI.is_file():
        return 127, "", f"thiếu {WATCH_CLI.name}"
    cmd = [sys.executable, str(WATCH_CLI)] + [str(x) for x in args]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=str(WORKSPACE), env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"quá thời gian chờ ({timeout}s)"
    except Exception as e:
        return 1, "", str(e)


def _image_cli(args: list, timeout: int = 300):
    """Chạy aistv_image.py bằng đúng Python của bot."""
    if not IMAGE_CLI.is_file():
        return 127, "", f"thiếu {IMAGE_CLI.name}"
    cmd = [sys.executable, str(IMAGE_CLI)] + [str(x) for x in args]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=str(WORKSPACE), env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"quá thời gian chờ ({timeout}s)"
    except Exception as e:
        return 1, "", str(e)


def _resolve_media_source(source: str) -> str:
    source = (source or "").strip().strip("<>")
    if re.match(r"^https?://", source, re.I):
        return source
    path = Path(source).expanduser()
    if path.is_file():
        return str(path.resolve())
    for base in (WORKSPACE, Path.cwd(), Path(__file__).resolve().parent):
        candidate = base / source
        if candidate.is_file():
            return str(candidate.resolve())
    return str(path)


VISION_ASK_IMAGE = ("Hãy mô tả chi tiết ảnh: người/vật thể, bố cục, màu sắc, ngữ cảnh; "
                    "đọc nguyên văn mọi chữ (OCR), số liệu, nhãn hiệu, biểu đồ nếu có. "
                    "Nêu rõ chỗ không đọc được hoặc không chắc.")
VISION_ASK_VIDEO = ("Hãy xem toàn bộ video và ghi lại bằng chứng: diễn biến chính kèm mốc [mm:ss], "
                    "người/vật/hành động, lời nói quan trọng, chữ hiện trên màn hình (nguyên văn), số liệu. "
                    "Nêu rõ chỗ không nghe/không thấy hoặc không chắc.")


def _vision_question(kind: str, question: str) -> str:
    base = VISION_ASK_IMAGE if kind == "image" else VISION_ASK_VIDEO
    q = (question or "").strip()
    return f"{base}\n\nCâu hỏi/yêu cầu của người dùng: {q}" if q else base


def _vision_cli_args(source: str, question: str, kind: str) -> list:
    if kind == "image":
        args = ["image", source, "--engine", "auto", "--json"]
    else:
        args = ["watch", source, "--engine", "auto", "--detail", "balanced", "--json"]
    args += ["--question", question]
    return args


def _vision_timeout(kind: str) -> int:
    key = "AISTV_IMAGE_TIMEOUT" if kind == "image" else "AISTV_VIDEO_TIMEOUT"
    return int(os.getenv(key, "600" if kind == "image" else "900"))


def _vision_parse(out: str) -> tuple:
    """(text, model) từ JSON của aistv_watch.py."""
    try:
        data = json.loads(out)
        gem = data.get("gemini") or {}
        return (gem.get("text") or "").strip(), (gem.get("model") or VISION_MODEL).strip()
    except Exception:
        return "", VISION_MODEL


def _vision_followup(source: str, question: str, kind: str) -> tuple:
    """DeepSeek hỏi lại Gemini ngay trên media đã gửi → (ok, answer, error).

    Tool call đi qua HTTP nội bộ nên giới hạn ~240s/lần (mặc định) để không bị
    client cắt trước khi Gemini trả lời."""
    cap = int(os.getenv("AISTV_VISION_FOLLOWUP_TIMEOUT", "240") or 240)
    timeout = min(_vision_timeout(kind), cap)
    rc, out, err = _watch_cli(_vision_cli_args(source, question, kind), timeout)
    if rc != 0:
        lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
        return False, "", _redact_secrets(lines[-1] if lines else f"lỗi không rõ (mã {rc})")
    text, _model = _vision_parse(out)
    if not text:
        lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
        return False, "", _redact_secrets(lines[-1] if lines else "Gemini không trả lời")
    return True, text, ""


def _vision_handoff_prompt(kind: str, source: str, question: str, report: str, model: str) -> str:
    label = "ẢNH" if kind == "image" else "VIDEO"
    try:
        shown = _rel(source) if Path(source).is_file() else source
    except Exception:
        shown = str(source)
    q = (question or "").strip() or "(không có — hãy phân tích theo hướng dẫn mặc định)"
    return (
        f"## {label} NGƯỜI DÙNG VỪA GỬI — GEMINI ĐÃ ĐỌC\n"
        f"- File/nguồn: {shown}\n"
        f"- Model thị giác: {model}\n"
        f"- Câu hỏi/yêu cầu của người dùng: {q}\n\n"
        "### BÁO CÁO THỊ GIÁC CỦA GEMINI (bằng chứng thô, có thể sai)\n"
        "```text\n" + report[:14000].replace("```", "ʼʼʼ") + "\n```\n\n"
        "### CÁCH PHỐI HỢP (bắt buộc)\n"
        "- Bạn là **model chính** và là người trả lời người dùng; Gemini chỉ là mắt + tai, "
        "không phải người trả lời cuối cùng.\n"
        "- Đối chiếu báo cáo với câu hỏi: chỗ nào mâu thuẫn, thiếu hoặc chưa chắc thì nói rõ mức độ chắc chắn.\n"
        "- Nếu thiếu chi tiết quan trọng, gọi tool `ask_gemini` để hỏi lại đúng điểm đó (tối đa vài lần), "
        "rồi mới kết luận.\n"
        "- Bạn không đọc được file ảnh/video trực tiếp — đừng dùng Read cho media; muốn xem thêm thì "
        "luôn dùng `ask_gemini`.\n"
        "- Trả lời trực tiếp cho người dùng; không kể lể quy trình, không dán nguyên báo cáo. "
        "Video thì kèm mốc thời gian [mm:ss].\n"
        "- Không bịa chi tiết không có trong báo cáo hoặc trong câu trả lời của `ask_gemini`.\n"
        "- Nếu báo cáo không đủ để trả lời, nói thẳng giới hạn đó thay vì đoán."
    )


async def gemini_media_reply(message, context, chat_id: int, source, question: str,
                             kind: str) -> bool:
    """Gemini đọc ảnh/video → DeepSeek (model chính) đối chiếu, hỏi lại nếu cần → trả lời."""
    label = "ảnh" if kind == "image" else "video"
    status = await message.reply_text(f"👁️ <i>Gemini đang đọc {label}…</i>", parse_mode=HTML)
    ask = _vision_question(kind, question)
    async with GEMINI_MEDIA_LOCK:
        rc, out, err = await asyncio.to_thread(
            _watch_cli, _vision_cli_args(source, ask, kind), _vision_timeout(kind))
    if rc != 0:
        lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
        detail = _redact_secrets(lines[-1] if lines else "lỗi không rõ")
        try:
            await status.edit_text(
                f"⚠️ Gemini chưa đọc được {label}.\n<code>{esc(detail[:1800])}</code>",
                parse_mode=HTML)
        except Exception:
            pass
        return True
    text, model = _vision_parse(out)
    if not text:
        lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
        detail = _redact_secrets(lines[-1] if lines else "không có nội dung trả về")
        try:
            await status.edit_text(f"⚠️ Gemini không trả lời.\n<code>{esc(detail[:1800])}</code>",
                                   parse_mode=HTML)
        except Exception:
            pass
        return True

    # Lưu media gần nhất để tool ask_gemini hỏi lại đúng file này.
    LAST_MEDIA[chat_id] = {"source": str(source), "kind": kind, "model": model}
    VISION_FOLLOWUP_LEFT[chat_id] = VISION_FOLLOWUPS

    if not VISION_HANDOFF:
        # Chế độ cũ: Gemini trả lời trực tiếp (AISTV_VISION_HANDOFF=0).
        try:
            await status.delete()
        except Exception:
            pass
        footer = f"<i>👁️ {esc(model)}</i>"
        try:
            await send_rich(message, text, footer)
        except Exception:
            await message.reply_text(text[:3900])
        stored_q = f"[{label}] {question}".strip()
        append_history(chat_id, "user", stored_q)
        append_history(chat_id, "assistant", text[:6000])
        log_daily(stored_q, text)
        return True

    try:
        await status.delete()
    except Exception:
        pass
    prompt = _vision_handoff_prompt(kind, source, question, text, model)
    asked = (question or "").strip() or (VISION_ASK_IMAGE if kind == "image" else VISION_ASK_VIDEO)
    try:
        name = Path(source).name if Path(source).is_file() else str(source)
    except Exception:
        name = str(source)
    stored = f"[{label}: {oneline(name, 120)}] {asked}"
    await respond(message, context, chat_id, prompt, quoted_msg=message, store_text=stored)
    # Giữ media + nạp lại lượt hỏi để tin nhắn tiếp theo vẫn hỏi lại Gemini được.
    VISION_FOLLOWUP_LEFT[chat_id] = VISION_FOLLOWUPS
    return True


# ── Tạo ảnh / sơ đồ tư duy ───────────────────────────────────────────
async def generate_image_job(prompt: str, style: str = "", aspect: str = "1:1",
                             kind: str = "image", ref: str = "", model: str = "",
                             provider: str = "", timeout: int = 0) -> dict:
    if kind == "mindmap":
        args = ["--mindmap", prompt]
    elif kind == "infographic":
        args = ["--infographic", prompt]
    elif kind == "chart":
        args = ["--chart", prompt]
    else:
        kind = "image"
        args = [prompt]
        if style:
            args += ["--style", style]
        if aspect:
            args += ["--aspect", aspect]
        if ref:
            args += ["--ref", ref]
        if model:
            args += ["--model", model]
    if provider:
        args += ["--provider", provider]
    args.append("--json")
    timeout = timeout or int(os.getenv("AISTV_GEN_IMAGE_TIMEOUT", "300"))
    rc, out, err = await asyncio.to_thread(_image_cli, args, timeout)
    data = {}
    for line in reversed([x.strip() for x in (out or "").splitlines() if x.strip()]):
        try:
            data = json.loads(line)
            break
        except Exception:
            continue
    if rc == 0 and data.get("ok"):
        return data
    detail = data.get("error") or ""
    if not detail:
        lines = [x.strip() for x in (err or out or "").splitlines() if x.strip()]
        detail = lines[-1] if lines else f"lỗi không rõ (mã {rc})"
    raise RuntimeError(_redact_secrets(detail)[:1200])


def _photo_for_telegram(path: Path) -> Path:
    """Ảnh > 9MB → thu nhỏ sang JPEG (photo Telegram tối đa 10MB)."""
    try:
        if path.stat().st_size <= 9 * 1024 * 1024:
            return path
        from PIL import Image
        img = Image.open(path).convert("RGB")
        img.thumbnail((2048, 2048))
        out = path.with_suffix(".jpg")
        img.save(out, "JPEG", quality=90)
        return out
    except Exception:
        return path


def _provider_label(name: str) -> str:
    low = str(name or "").strip().lower()
    for prefix, label in (("web2api", "Gemini"), ("pollinations", "Miễn phí"),
                          ("ai+pil", "AI STV"), ("gemini", "Gemini API"),
                          ("cloudflare", "Cloudflare"), ("together", "Together"),
                          ("hf", "HuggingFace")):
        if low == prefix or low.startswith(prefix + "/"):
            return label
    return str(name or "")


def _image_caption(data: dict) -> str:
    bits = []
    prompt = str(data.get("prompt") or "").strip()
    if prompt:
        bits.append(f"🎨 <b>{esc(_clip(prompt, 400))}</b>")
    meta = []
    kind_label = {"mindmap": "sơ đồ tư duy", "infographic": "infographic",
                  "chart": "biểu đồ"}.get(str(data.get("kind") or ""))
    if kind_label:
        meta.append(kind_label)
    elif data.get("style"):
        meta.append(esc(str(data["style"])))
    if data.get("provider"):
        meta.append(esc(_provider_label(str(data["provider"]))))
    if meta:
        bits.append("<i>" + " · ".join(meta) + "</i>")
    return "\n".join(bits)[:1000] or "🎨 Ảnh đã tạo"


async def send_generated_image(chat_id: int, data: dict, reply_to: int = None,
                               message_thread_id: int = None) -> None:
    path = Path(str(data.get("path") or ""))
    if not path.is_file():
        raise RuntimeError("file ảnh không còn tồn tại")
    ready = await asyncio.to_thread(_photo_for_telegram, path)
    caption = _image_caption(data)
    kw = {}
    if reply_to:
        kw["reply_to_message_id"] = reply_to
    if message_thread_id:
        kw["message_thread_id"] = message_thread_id
    try:
        with open(ready, "rb") as f:
            await BOT_OBJ.send_photo(chat_id, photo=f, caption=caption, parse_mode="HTML", **kw)
    except Exception:
        with open(ready, "rb") as f:
            await BOT_OBJ.send_document(chat_id, document=f, caption=caption, parse_mode="HTML", **kw)


# ── Lời giải dài → các trang ảnh A4 có số trang ─────────────────────
def _math_for_pages(m, dollar: bool = False) -> str:
    raw = m.group(1) if m.group(1) is not None else m.group(2)
    if dollar and m.group(1) is not None and not _looks_math(raw):
        return m.group(0)
    return latex_to_unicode(raw)


def pages_plain_text(md: str) -> str:
    """Markdown cho ảnh: đổi công thức sang Unicode, giữ nguyên code block."""
    stash: list = []

    def hold(s: str) -> str:
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    text = _FENCE.sub(lambda m: hold(m.group(0)), str(md or ""))
    text = _ICODE.sub(lambda m: hold(m.group(0)), text)
    text = _MATH_BLOCK.sub(_math_for_pages, text)
    text = _MATH_INLINE.sub(lambda m: _math_for_pages(m, dollar=True), text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def render_pages_ready(md: str, title: str = "") -> dict:
    import aistv_image
    return aistv_image.render_text_pages(pages_plain_text(md), title=title)


async def _send_page_images(chat_id: int, paths: list, title: str,
                            as_document: bool = False, reply_to: int = None,
                            message_thread_id: int = None) -> None:
    from telegram import InputMediaDocument, InputMediaPhoto
    total = len(paths)
    head = esc(_clip(title, 160))
    kw = {}
    if reply_to:
        kw["reply_to_message_id"] = reply_to
    if message_thread_id:
        kw["message_thread_id"] = message_thread_id
    for start in range(0, total, 10):
        chunk = paths[start:start + 10]
        handles, media = [], []
        try:
            for offset, path in enumerate(chunk):
                idx = start + offset + 1
                caption = f"📄 <b>Trang {idx}/{total}</b>"
                if idx == 1 and head:
                    caption += "\n" + head
                fh = path.open("rb")
                handles.append(fh)
                cls = InputMediaDocument if as_document else InputMediaPhoto
                extra = {"filename": path.name} if as_document else {}
                media.append(cls(fh, caption=caption, parse_mode=HTML, **extra))
            await BOT_OBJ.send_media_group(chat_id, media, **kw)
        except Exception as e:
            log.warning("Gửi nhóm trang lỗi (%s) — gửi từng ảnh", oneline(str(e), 160))
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass
            handles = []
            for offset, path in enumerate(chunk):
                idx = start + offset + 1
                caption = f"📄 <b>Trang {idx}/{total}</b>"
                try:
                    with path.open("rb") as fh:
                        if as_document:
                            await BOT_OBJ.send_document(chat_id, document=fh, filename=path.name,
                                                        caption=caption, parse_mode=HTML, **kw)
                        else:
                            await BOT_OBJ.send_photo(chat_id, photo=fh, caption=caption,
                                                     parse_mode=HTML, **kw)
                except Exception as e2:
                    log.warning("Gửi trang %s lỗi: %s", idx, oneline(str(e2), 160))
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass


async def _tool_pages_job(chat_id: int, md: str, title: str = "", fmt: str = "photo",
                          reply_to: int = None, message_thread_id: int = None) -> dict:
    if BOT_OBJ is None:
        return {"ok": False, "error": "bot chưa sẵn sàng"}
    try:
        result = await asyncio.to_thread(render_pages_ready, md, title)
    except Exception as e:
        log.warning("render_pages lỗi: %s", oneline(str(e), 200))
        return {"ok": False,
                "error": oneline(_redact_secrets(str(e)), 400) or "không dựng được ảnh"}
    paths = [Path(p) for p in (result.get("pages") or []) if Path(p).is_file()]
    if not paths:
        return {"ok": False, "error": "không dựng được trang nào"}
    try:
        await _send_page_images(chat_id, paths, str(result.get("title") or title),
                                fmt == "document", reply_to=reply_to,
                                message_thread_id=message_thread_id)
    except Exception as e:
        log.warning("Gửi trang ảnh lỗi: %s", oneline(str(e), 200))
        return {"ok": False, "error": oneline(str(e), 300)}
    return {"ok": True, "count": len(paths)}


async def _tool_image_job(chat_id: int, prompt: str, style: str = "",
                          aspect: str = "1:1", kind: str = "image",
                          model: str = "") -> None:
    """Chạy nền khi agent gọi tool generate_image (HTTP nội bộ)."""
    if BOT_OBJ is None:
        return
    label = {"mindmap": "sơ đồ tư duy", "infographic": "infographic",
             "chart": "biểu đồ"}.get(kind, "ảnh")
    try:
        status = await BOT_OBJ.send_message(chat_id, f"🎨 <i>Đang tạo {label}…</i>", parse_mode="HTML")
    except Exception:
        return
    try:
        data = await generate_image_job(prompt, style, aspect, kind, model=model)
        await send_generated_image(chat_id, data)
        try:
            await status.delete()
        except Exception:
            pass
    except Exception as e:
        try:
            await status.edit_text(
                f"❌ Không tạo được {label}.\n<code>{esc(oneline(str(e), 1000))}</code>",
                parse_mode="HTML")
        except Exception:
            pass


async def _download_telegram_file(message, file_obj, name: str, mime: str = "",
                                  folder: Optional[Path] = None) -> Optional[Path]:
    if getattr(file_obj, "file_size", None) and file_obj.file_size > 20 * 1024 * 1024:
        await message.reply_text("⚠️ File quá lớn (giới hạn 20MB của Telegram Bot API).")
        return None
    safe = re.sub(r"[^\w.\- ]", "_", name or f"file_{getattr(file_obj, 'file_unique_id', int(time.time()))}")
    ext = Path(safe).suffix.lower()
    if mime.startswith("image/") and ext not in IMAGE_EXTS:
        safe += mimetypes.guess_extension(mime) or ".jpg"
    elif mime.startswith("video/") and ext not in VIDEO_EXTS:
        safe += ".mp4"
    base = Path(folder) if folder else INBOX
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"{int(time.time())}_{safe}"
    await (await file_obj.get_file()).download_to_drive(dest)
    return dest


@guard(allow_guest=True)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.photo:
        return
    chat, user = update.effective_chat, update.effective_user
    photo = msg.photo[-1]
    if not authorized(user.id, chat.type):
        await _guest_media_read(update, context, "image", photo,
                                f"photo_{photo.file_unique_id}.jpg", "image/jpeg")
        return
    if chat.type != "private":
        return
    dest = await _download_telegram_file(msg, photo, f"photo_{photo.file_unique_id}.jpg", "image/jpeg")
    if not dest:
        return
    caption = (msg.caption or "").strip()
    if vision_ready():
        await gemini_media_reply(msg, context, update.effective_chat.id, str(dest), caption, "image")
        return
    prompt = caption or "Hãy cho tôi biết nội dung chính của ảnh này."
    await respond(msg, context, update.effective_chat.id,
                  f"{prompt}\n\n(Người dùng vừa gửi ảnh, đã lưu tại: inbox/{dest.name}. "
                  "Chưa có GEMINI_API_KEY và Gemini chưa bật media nên không đọc ảnh được.)",
                  quoted_msg=msg)


@guard(allow_guest=True)
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    media = msg.video or msg.video_note or msg.animation
    if not media:
        return
    chat, user = update.effective_chat, update.effective_user
    mime = getattr(media, "mime_type", "") or "video/mp4"
    name = getattr(media, "file_name", "") or f"video_{getattr(media, 'file_unique_id', int(time.time()))}.mp4"
    if not authorized(user.id, chat.type):
        await _guest_media_read(update, context, "video", media, name, mime)
        return
    if chat.type != "private":
        return
    dest = await _download_telegram_file(msg, media, name, mime)
    if not dest:
        return
    caption = (msg.caption or "").strip()
    if vision_ready():
        await gemini_media_reply(msg, context, update.effective_chat.id, str(dest), caption, "video")
        return
    prompt = caption or "Hãy xem video này và tóm tắt nội dung chính kèm mốc thời gian."
    await respond(msg, context, update.effective_chat.id,
                  f"{prompt}\n\n(Người dùng vừa gửi video, đã lưu tại: inbox/{dest.name}. "
                  "Dùng skill watch với aistv_watch.py để xem; chưa có GEMINI_API_KEY/Gemini media nên ưu tiên "
                  "transcript + frames.)",
                  quoted_msg=msg)


@guard(allow_guest=True)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.document:
        return
    chat, user = update.effective_chat, update.effective_user
    doc = msg.document
    mime = (doc.mime_type or "").lower()
    name = doc.file_name or f"file_{doc.file_unique_id}"
    ext = Path(name).suffix.lower()
    is_image = mime.startswith("image/") or ext in IMAGE_EXTS
    is_video = mime.startswith("video/") or ext in VIDEO_EXTS
    if not authorized(user.id, chat.type):
        if is_image:
            await _guest_media_read(update, context, "image", doc, name, mime or "image/jpeg")
        elif is_video:
            await _guest_media_read(update, context, "video", doc, name, mime or "video/mp4")
        return
    if chat.type != "private":
        return
    dest = await _download_telegram_file(msg, doc, name, mime)
    if not dest:
        return
    caption = (msg.caption or "").strip()
    if vision_ready() and is_image:
        await gemini_media_reply(msg, context, update.effective_chat.id, str(dest), caption, "image")
        return
    if vision_ready() and is_video:
        await gemini_media_reply(msg, context, update.effective_chat.id, str(dest), caption, "video")
        return
    prompt = caption or "Hãy đọc file này và tóm tắt nội dung chính."
    await respond(msg, context, update.effective_chat.id,
                  f"{prompt}\n\n(Người dùng vừa gửi file, đã lưu tại: inbox/{dest.name})",
                  quoted_msg=msg)


async def _cmd_gemini_media(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    msg = update.effective_message
    args = list(context.args or [])
    label = "ảnh" if kind == "image" else "video"
    if not args:
        example = ("/image inbox/anh.jpg mô tả ảnh này" if kind == "image"
                   else "/video https://youtu.be/... tóm tắt video")
        await msg.reply_text(f"Dùng: <code>{example}</code>", parse_mode=HTML)
        return
    if not vision_ready():
        await msg.reply_text(
            "⚠️ Chưa có nguồn đọc ảnh/video.\n"
            "Thêm <code>GEMINI_API_KEY</code> vào <code>.env</code>, hoặc bật Gemini đã có media:\n"
            "<code>/gemini restart</code> (không tốn request API).", parse_mode=HTML)
        return
    source = _resolve_media_source(args[0])
    question = " ".join(args[1:]).strip()
    if not re.match(r"^https?://", source, re.I) and not Path(source).is_file():
        await msg.reply_text(f"❌ Không tìm thấy {label}: <code>{esc(source)}</code>", parse_mode=HTML)
        return
    await gemini_media_reply(msg, context, update.effective_chat.id, source, question, kind)


IMAGE_USAGE = (
    "🎨 <b>Tạo ảnh</b>\n"
    "<code>/image mèo phi hành gia</code>\n"
    "<code>/image --style realistic --aspect 16:9 thành phố tương lai</code>\n"
    "<code>/image --model flux-2-dev ảnh chân dung chân thực</code>\n"
    "<code>/image --mindmap Kế hoạch học Python</code>\n"
    "<code>/image --infographic 5 lợi ích của việc đọc sách</code>\n"
    "<code>/image --chart doanh thu 2021: 120, 2022: 150, 2023: 180</code>\n"
    "Reply vào một ảnh rồi gõ <code>/image --style anime ...</code> để vẽ lại theo ảnh đó.\n"
    "Phong cách: anime, 3d, realistic, watercolor, oil, pixel, minimal, comic, "
    "sketch, cyberpunk, poster, logo, infographic, cartoon, fantasy.\n"
    "Model Cloudflare: flux-2-dev (đẹp nhất), flux-2-klein-9b (cân bằng), flux-1-schnell (nhanh).\n"
    "Tỉ lệ: 1:1, 16:9, 9:16, 4:3, 3:4."
)


def _parse_image_args(args):
    style, aspect, kind, model = "", "1:1", "image", ""
    out = []
    i = 0
    while i < len(args):
        a = str(args[i])
        low = a.lower()
        if low in ("--mindmap", "-m") or low == "mindmap":
            kind = "mindmap"
            i += 1
            continue
        if low in ("--infographic", "-i"):
            kind = "infographic"
            i += 1
            continue
        if low in ("--chart", "-c"):
            kind = "chart"
            i += 1
            continue
        if low == "--model" and i + 1 < len(args):
            model = str(args[i + 1])
            i += 2
            continue
        if low.startswith("--model="):
            model = a.split("=", 1)[1]
            i += 1
            continue
        if low in ("--style", "-s") and i + 1 < len(args):
            style = str(args[i + 1])
            i += 2
            continue
        if low.startswith("--style="):
            style = a.split("=", 1)[1]
            i += 1
            continue
        if low in ("--aspect", "-a") and i + 1 < len(args):
            aspect = str(args[i + 1])
            i += 2
            continue
        if low.startswith("--aspect="):
            aspect = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1

    text = " ".join(out).strip()
    m = re.match(r"^(mindmap|sơ đồ tư duy|so do tu duy|infographic|chart|biểu đồ|bieu do)\s*:\s*(.+)$",
                 text, re.I | re.S)
    if m:
        key = m.group(1).lower()
        kind = ("mindmap" if "mindmap" in key or "sơ đồ" in key or "so do" in key
                else "chart" if "chart" in key or "biểu đồ" in key or "bieu do" in key
                else "infographic")
        text = m.group(2).strip()
    elif not style and ":" in text:
        cand, rest = text.split(":", 1)
        try:
            import aistv_image as _img
            resolved = _img.resolve_style(cand)
            if resolved:
                style, text = resolved, rest.strip()
        except Exception:
            pass
    return text, style, aspect, kind, model


async def _image_generate_reply(update, prompt: str, style: str = "", aspect: str = "1:1",
                                kind: str = "image", model: str = "", provider: str = ""):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    ref = ""
    rt = msg.reply_to_message
    if kind == "image" and rt and rt.photo:
        photo = rt.photo[-1]
        dest = await _download_telegram_file(msg, photo, f"ref_{photo.file_unique_id}.jpg",
                                             "image/jpeg")
        if dest:
            ref = str(dest)
    label = {"mindmap": "sơ đồ tư duy", "infographic": "infographic",
             "chart": "biểu đồ"}.get(kind, "ảnh")
    status = await msg.reply_text(f"🎨 <i>Đang tạo {label}…</i>", parse_mode=HTML)
    try:
        data = await generate_image_job(prompt, style, aspect, kind, ref, model,
                                        provider=provider)
        await send_generated_image(chat_id, data, reply_to=msg.message_id, **_thread_kw(msg))
        try:
            await status.delete()
        except Exception:
            pass
    except Exception as e:
        try:
            await status.edit_text(
                f"❌ Không tạo được {label}.\n<code>{esc(oneline(str(e), 1200))}</code>",
                parse_mode="HTML")
        except Exception:
            pass


@guard(allow_guest=True)
async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mặc định tạo ảnh; nếu tham số đầu là file/URL ảnh thì đọc ảnh (như cũ)."""
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    args = list(context.args or [])
    if not authorized(user.id, chat.type):
        if not GUEST_CHAT:
            await _deny_guest(update, context)
            return
        prompt, style, aspect, kind, _model = _parse_image_args(args)
        if not prompt:
            await msg.reply_text(
                "Dùng: <code>/image vẽ một con mèo</code> · "
                "<code>/image --mindmap Kế hoạch học Python</code>", parse_mode=HTML)
            return
        await _guest_media_reply(msg, context, chat, user, prompt, kind=kind,
                                 prompt=prompt, style=style, aspect=aspect)
        return
    first = str(args[0]).strip() if args else ""
    if first and not first.startswith("-"):
        if re.match(r"^https?://", first, re.I) or Path(_resolve_media_source(first)).is_file():
            await _cmd_gemini_media(update, context, "image")
            return
    prompt, style, aspect, kind, model = _parse_image_args(args)
    if not prompt:
        await msg.reply_text(IMAGE_USAGE, parse_mode="HTML")
        return
    await _image_generate_reply(update, prompt, style, aspect, kind, model)


@guard()
async def cmd_see(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_gemini_media(update, context, "image")


@guard(allow_guest=True)
async def cmd_mindmap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    topic = " ".join(context.args or []).strip()
    if not topic:
        await msg.reply_text(
            "Dùng: <code>/mindmap Kế hoạch học Python</code>", parse_mode=HTML)
        return
    if not authorized(user.id, chat.type):
        if not GUEST_CHAT:
            await _deny_guest(update, context)
            return
        await _guest_media_reply(msg, context, chat, user, topic, kind="mindmap", prompt=topic)
        return
    await _image_generate_reply(update, topic, "", "1:1", "mindmap")


@guard()
async def cmd_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dựng tin nhắn dài (hoặc nội dung gõ kèm) thành ảnh từng trang A4."""
    msg = update.effective_message
    if msg is None:
        return
    text = " ".join(context.args or []).strip()
    reply = msg.reply_to_message
    if not text and reply is not None:
        text = (reply.text or reply.caption or "").strip()
    if not text:
        await msg.reply_text(
            "Dùng: trả lời tin nhắn dài rồi gửi <code>/pages</code>, hoặc "
            "<code>/pages &lt;nội dung&gt;</code> — bot dựng thành ảnh từng trang có số trang.",
            parse_mode=HTML)
        return
    if len(text) > 120_000:
        await msg.reply_text("Nội dung quá dài (giới hạn 120.000 ký tự).", parse_mode=HTML)
        return
    status = await msg.reply_text("📄 <i>Đang dựng thành ảnh từng trang…</i>", parse_mode=HTML)
    title = oneline(next((ln.strip("#*_•- ") for ln in text.splitlines() if ln.strip()), ""), 70)
    res = await _tool_pages_job(msg.chat_id, text, title, "photo",
                                reply_to=msg.message_id, message_thread_id=_thread_kw(msg).get(
                                    "message_thread_id"))
    try:
        await status.delete()
    except Exception:
        pass
    if not res.get("ok"):
        await msg.reply_text(
            f"⚠️ Không dựng được ảnh: {esc(res.get('error') or 'lỗi không rõ')}",
            parse_mode=HTML)


@guard()
async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _cmd_gemini_media(update, context, "video")


async def _on_ask_button(q, data: str) -> None:
    try:
        _, ask_id, choice = data.split(":", 2)
    except ValueError:
        return
    with ASK_LOCK:
        rec = ASK_REQUESTS.get(ask_id)
    if not rec:
        await q.answer("Câu hỏi đã hết hạn.")
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    head = f"❓ {esc(_clip(rec['question'], 1500))}"
    if choice == "free":
        await q.answer("Hãy nhắn câu trả lời của bạn.")
        try:
            await q.edit_message_text(f"{head}\n\n✍️ <i>Hãy nhắn câu trả lời…</i>", parse_mode=HTML)
        except Exception:
            pass
        return
    if choice == "skip":
        _ask_pop(ask_id, cancelled=True)
        await q.answer("Đã bỏ qua")
        result = "⏭ Bỏ qua"
    else:
        try:
            option = rec["options"][int(choice)]
        except Exception:
            await q.answer("Lựa chọn không hợp lệ.")
            return
        _ask_pop(ask_id, option)
        await q.answer(f"Đã chọn: {option}"[:190])
        result = f"✅ {option}"
    try:
        await q.edit_message_text(f"{head}\n\n<b>{esc(result)}</b>", parse_mode=HTML)
    except Exception:
        pass


async def _on_gh_repo_button(q, data: str) -> None:
    chat_id = q.message.chat_id
    if not (q.from_user and is_owner(q.from_user.id)):
        await q.answer("Chỉ chủ bot dùng được.", show_alert=True)
        return
    tok = github_token()
    if not tok:
        await q.answer("Chưa kết nối GitHub.", show_alert=True)
        return
    parts = data.split(":")
    act = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    if act == "cur":
        await q.answer()
        slug = current_repo_slug()
        if not slug:
            await q.message.reply_text("Chưa đặt repo đích. Bấm “🗂 Chọn / đổi repo”.",
                                       parse_mode=HTML,
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("🗂 Chọn / đổi repo",
                                                                  callback_data="ghr:r")]]))
            return
        meta = await asyncio.to_thread(gh_repo_meta, slug, tok)
        perms = (meta or {}).get("permissions") or {}
        origin = repo_remote_slug()
        lines = [f"📦 <b>Repo đích</b> <code>{esc(slug)}</code>",
                 f"• Quyền: {'đẩy code' if perms.get('push') else 'chỉ đọc'}",
                 f"• Origin máy này: <code>{esc(origin or 'chưa có')}</code>"]
        rows = [[InlineKeyboardButton("🗂 Chọn / đổi repo", callback_data="ghr:r")]]
        if perms.get("push") and repo_dir():
            rows.append([InlineKeyboardButton("⬆️ Đẩy code lên repo này",
                                              callback_data="ghr:upc")])
        await q.edit_message_text("\n".join(lines), parse_mode=HTML,
                                  reply_markup=InlineKeyboardMarkup(rows))
        return

    if act == "upc":
        slug = current_repo_slug()
        if not slug:
            await q.answer("Chưa đặt repo đích.", show_alert=True)
            return
        await q.answer("Đang đẩy code…")
        try:
            out = await asyncio.to_thread(gh_push_code, slug)
            await q.edit_message_text(
                f"⬆️ Đã đẩy code lên <code>{esc(slug)}</code>\n<pre>{esc(out[-700:])}</pre>",
                parse_mode=HTML)
        except Exception as e:
            await q.answer(oneline(str(e), 180), show_alert=True)
        return

    if act == "new":
        await q.answer()
        await q.message.reply_text(
            "➕ <b>Tạo repo mới</b>\n"
            "<code>/github repo create ten-repo</code> — public\n"
            "<code>/github repo create ten-repo private</code> — private\n"
            "Bot tạo xong sẽ tự đẩy code lên.", parse_mode=HTML)
        return

    if act in ("r", "p"):
        await q.answer("Đang quét…")
        page = int(arg) if act == "p" and arg.isdigit() else 0
        try:
            text, kb = await asyncio.to_thread(gh_repo_picker, chat_id, tok, page, act == "r")
            await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
        except Exception as e:
            await q.answer(oneline(str(e), 180), show_alert=True)
        return

    if act in ("s", "o", "up") and arg.isdigit():
        idx = int(arg)
        if act == "s":
            await q.answer()
            try:
                text, kb = await asyncio.to_thread(gh_repo_detail, chat_id, idx)
                await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
            except Exception as e:
                await q.answer(oneline(str(e), 180), show_alert=True)
            return
        slugs = GH_REPO_PICK.get(chat_id) or []
        if not (0 <= idx < len(slugs)):
            await q.answer("Danh sách đã cũ — quét lại nhé.", show_alert=True)
            return
        slug = slugs[idx]
        set_repo_slug(slug)
        await q.answer("Đang chạy…")
        try:
            if act == "o":
                out = await asyncio.to_thread(gh_switch_repo, slug)
                note = "🔀 Đã đổi origin và cập nhật từ repo mới."
            else:
                out = await asyncio.to_thread(gh_push_code, slug)
                note = "⬆️ Đã đẩy code lên repo đích."
            await q.edit_message_text(
                f"{note}\n• Repo: <code>{esc(slug)}</code>\n<pre>{esc(out[-700:])}</pre>",
                parse_mode=HTML)
        except Exception as e:
            await q.edit_message_text(
                f"⚠️ {esc(oneline(str(e), 700))}\n\n"
                f"Repo đích vẫn là <code>{esc(slug)}</code>. Thử /github repos để chọn repo khác.",
                parse_mode=HTML)
        return


@guard(allow_guest=True)
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q is None or not q.data:
        return
    chat_id = q.message.chat_id if q.message else (q.from_user.id if q.from_user else 0)
    data = q.data
    user = q.from_user
    chat = update.effective_chat
    if not (user and chat and authorized(user.id, chat.type)):
        if data.startswith("vm:g"):          # khách: chỉ nút máy ảo của chính họ
            await _on_guest_vm_button(q, data)
        else:
            await _deny_guest(update, context)
        return
    if data.startswith("plan:"):
        await _on_plan_button(q, data)
        return
    if data.startswith("work:"):
        await _on_work_button(q, data)
        return
    if data.startswith("up:"):
        await _on_review_button(q, data)
        return
    if data.startswith("ghr:"):
        await _on_gh_repo_button(q, data)
        return
    if data.startswith("vm:"):
        if data.startswith("vm:g"):
            await _on_guest_vm_button(q, data)
        else:
            await _on_vm_button(q, data)
        return
    if data.startswith("ask:"):
        await _on_ask_button(q, data)
        return
    if data.startswith("done:"):
        rid = data.split(":", 1)[1]
        REMINDERS.pop(rid, None)
        await rem_save()
        await q.answer("Đã xoá nhắc việc")
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    if data == "stop":
        uid = q.from_user.id if q.from_user else 0
        if not is_owner(uid):
            await q.answer("Chỉ chủ bot được huỷ tác vụ.", show_alert=True)
            return
        proc = RUNNING.get(chat_id)
        if proc and proc.returncode is None:
            CANCELLED.add(chat_id)
            if chat_id in PLAN_BUSY:
                PLAN_CANCEL.add(chat_id)
            proc.kill()
            await q.answer("🛑 Đang huỷ tác vụ…")
        else:
            await q.answer("Không có tác vụ nào đang chạy.")
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    await q.answer()
    if data == "status":
        await q.message.reply_text(build_status(chat_id), parse_mode=HTML)
    elif data == "skills":
        await _reply_skills(q.message)
    elif data == "memory":
        await q.message.reply_text(build_memory(), parse_mode=HTML)
    elif data == "new":
        archive_history(chat_id)
        await q.message.reply_text("🧹 <b>Đã bắt đầu cuộc trò chuyện mới.</b>", parse_mode=HTML)
    elif data == "regen":
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        last = pop_last_exchange(chat_id)
        if last:
            if not await respond(q.message, context, chat_id, last[0]):
                append_history(chat_id, "user", last[0])         # viết lại thất bại → trả lại cặp cũ, không mất ngữ cảnh
                append_history(chat_id, "assistant", last[1])
        else:
            await q.message.reply_text("Không có câu trả lời nào để viết lại.")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        print("⚠️ Có phiên bot khác đang chạy cùng token (ô Colab cũ?). Hãy dừng ô cũ rồi chạy lại.")
    else:
        log.error("Lỗi không xử lý được: %s", context.error)


# ════════════════════════════════════════════════════════════════════
# 8b. TRÍ NHỚ ĐÁM MÂY · TÓM TẮT TỰ ĐỘNG · NHẮC VIỆC · THEO DÕI
#     Firebase RTDB giữ MEMORY.md, lịch sử chat, nhắc việc và watch
#     → restart bot / Colab reset vẫn còn nguyên.
# ════════════════════════════════════════════════════════════════════
CLOUD_NS = CLOUD_NS_BASE
CLOUD_STAT = {"ok": None, "at": 0.0, "err": 0, "up": 0, "last": ""}
MEM_DIRTY = False
HIST_DIRTY: dict = {}
SUMMARY_BUSY: set = set()
SUMMARY_PENDING: set = set()
REMINDERS: dict = {}
WATCHES: dict = {}
REMIND_FILE = HOME / "reminders.json"
WATCH_FILE = HOME / "watches.json"
_ERROR_RX = re.compile(r"(?i)\b(error|exception|traceback|critical|fatal|panic|failed)\b")
_UNITS = {"s": 1, "giây": 1, "giay": 1, "m": 60, "phút": 60, "phut": 60, "p": 60,
          "h": 3600, "giờ": 3600, "gio": 3600, "g": 3600,
          "d": 86400, "ngày": 86400, "ngay": 86400, "n": 86400}


def _cloud_path(path: str) -> str:
    return f"{CLOUD_NS}/{path.strip('/')}".strip("/")


def _fb_url(path: str) -> str:
    url = f"{FIREBASE_URL}/{_cloud_path(path)}.json"
    if FIREBASE_SECRET:
        url += "?auth=" + urllib.parse.quote(FIREBASE_SECRET)
    return url


# Dữ liệu cá nhân (lịch sử chat, trí nhớ, nhắc việc, watch, tóm tắt) mã hoá
# toàn bộ trước khi ghi lên cloud: DB public cũng không đọc được nội dung.
PERSONAL_CLOUD_ROOTS = {"mem", "hist", "summary", "rem", "watch",
                        "vmverify", "vmverify_pending"}
ENC_MARK = "_enc"
_CLOUD_MIGRATED = False


def _personal_path(path: str) -> bool:
    return path.strip("/").split("/")[0] in PERSONAL_CLOUD_ROOTS


def _is_sealed(value) -> bool:
    return (isinstance(value, dict) and bool(value.get(ENC_MARK))
            and isinstance(value.get("blob"), str))


def _seal_node(data):
    if data is None:
        return None
    return {ENC_MARK: 1, "at": int(time.time()), "blob": _seal(data)}


def _open_node(value):
    """Giải mã node; dữ liệu thô kiểu cũ (trước khi mã hoá) trả nguyên trạng."""
    if _is_sealed(value):
        try:
            return _open(str(value["blob"]))
        except Exception as e:
            log.warning("Không giải mã được node cloud: %s", oneline(str(e), 120))
            return None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _is_sealed(v):
                dec = _open_node(v)
                if dec is not None:
                    out[k] = dec
            else:
                out[k] = v
        return out
    return value


def fb_call(method: str, path: str, data=None, timeout: int = 20, raw: bool = False):
    """REST tới Firebase RTDB (đồng bộ). Không bao giờ ném lỗi ra ngoài."""
    if not CLOUD_ENABLED:
        return None
    personal = _personal_path(path)
    if personal and not raw and data is not None:
        try:
            data = _seal_node(data)
        except Exception as e:
            # Không mã hoá được thì KHÔNG ghi thô lên cloud.
            log.warning("Không mã hoá được /%s: %s", _cloud_path(path), oneline(str(e), 120))
            return None
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(_fb_url(path), data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8", "replace")
        CLOUD_STAT.update(ok=True, at=time.time())
        if method in ("PUT", "POST", "PATCH"):
            CLOUD_STAT["up"] += 1
        CLOUD_STAT["last"] = f"{method} /{_cloud_path(path)}"
        result = json.loads(raw_body) if raw_body.strip() and raw_body.strip() != "null" else None
        if personal and not raw:
            result = _open_node(result)
        return result
    except Exception as e:
        CLOUD_STAT.update(ok=False, err=CLOUD_STAT["err"] + 1)
        log.warning("Firebase %s /%s: %s", method, _cloud_path(path), oneline(str(e), 160))
        return None


async def fb(method: str, path: str, data=None):
    return await asyncio.to_thread(fb_call, method, path, data)


async def fb_raw_get(path: str):
    """GET nguyên bản (không giải mã) — dùng để phát hiện node cũ còn dạng thô."""
    return await asyncio.to_thread(fb_call, "GET", path, None, 20, True)


async def cloud_encrypt_existing() -> int:
    """Mã hoá các node cá nhân bản cũ còn nằm dạng thô trên cloud (mỗi phiên 1 lần)."""
    global _CLOUD_MIGRATED
    if not CLOUD_ENABLED or _CLOUD_MIGRATED:
        return 0
    _CLOUD_MIGRATED = True
    if os.getenv("AISTV_CLOUD_ENCRYPT_MIGRATE", "1") == "0":
        return 0
    moved = 0
    for path in ("mem/items", "rem", "watch"):
        value = await fb_raw_get(path)
        if value is None or _is_sealed(value):
            continue
        await fb("PUT", path, value)
        moved += 1
    for root in ("hist", "summary"):
        data = await fb_raw_get(root)
        if not isinstance(data, dict):
            continue
        for child, value in data.items():
            if value is None or _is_sealed(value):
                continue
            await fb("PUT", f"{root}/{child}", value)
            moved += 1
    if moved:
        log.info("Mã hoá %d nhóm dữ liệu cloud cũ (lịch sử/trí nhớ/nhắc việc)", moved)
    return moved


def _save_json(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:
        log.warning("Không ghi được %s: %s", path.name, e)


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ── Bí mật đồng bộ qua cloud, mã hoá bằng token bot ─────────────────
# Database Firebase đang để public nên KHÔNG bao giờ ghi token/key ở dạng thô:
# blob = nonce(16) + HMAC-SHA256(32) + ciphertext (XOR với keystream HMAC).
def _secret_master_key() -> bytes:
    tok = (globals().get("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").encode("utf-8")
    if not tok:
        raise RuntimeError("thiếu bot token để mã hoá")
    return hashlib.pbkdf2_hmac("sha256", tok, b"aistv-secrets-v1", 120_000)


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = bytearray()
    block = 0
    while len(out) < size:
        out += hmac.new(key, nonce + block.to_bytes(8, "big"), hashlib.sha256).digest()
        block += 1
    return bytes(out[:size])


def _seal(data) -> str:
    master = _secret_master_key()
    enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"mac", hashlib.sha256).digest()
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(raw, _keystream(enc_key, nonce, len(raw))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + ct).decode("ascii")


def _open(blob: str):
    raw = base64.b64decode(blob)
    if len(raw) < 48:
        raise ValueError("dữ liệu quá ngắn")
    nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
    master = _secret_master_key()
    enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"mac", hashlib.sha256).digest()
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("sai khoá hoặc dữ liệu bị sửa")
    plain = bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))
    return json.loads(plain.decode("utf-8"))


def encrypt_secrets(data: dict) -> str:
    return _seal(data)


def decrypt_secrets(blob: str) -> dict:
    data = _open(blob)
    return data if isinstance(data, dict) else {}


def _local_secret_values() -> dict:
    data = {}
    for name in SECRET_SYNC_KEYS:
        val = get_secret(name)
        if val:
            data[name] = val
    gh = github_token() or (get_secret("AISTV_CONFIG_TOKEN") or "").strip()
    if gh:
        data["GITHUB_TOKEN"] = gh
    vm = load_vm_creds()
    # Luôn gửi cả khoá rỗng để xoá creds cũ trên cloud khi người dùng bấm Xoá.
    data["AISTV_VM_PAT"] = str(vm.get("pat") or "")
    data["AISTV_VM_TSKEY"] = str(vm.get("tailscale_key") or "")
    data["AISTV_VM_WINDOWS"] = str(vm.get("windows") or "")
    data["AISTV_VM_MINUTES"] = str(vm.get("minutes") or "")
    if mail:
        try:
            cfg = mail.load()
            if cfg.get("address") and cfg.get("password"):
                data.setdefault("AISTV_EMAIL_ADDRESS", cfg["address"])
                data.setdefault("AISTV_EMAIL_PASSWORD", cfg["password"])
        except Exception:
            pass
    return data


async def cloud_push_secrets() -> bool:
    global SECRETS_DIRTY
    if not CLOUD_ENABLED:
        return False
    try:
        data = await asyncio.to_thread(_local_secret_values)
    except Exception as e:
        log.warning("Không đọc được bí mật cục bộ: %s", oneline(str(e), 120))
        return False
    if not data:
        return False
    try:
        blob = encrypt_secrets(data)
    except Exception as e:
        log.warning("Không mã hoá được bí mật: %s", oneline(str(e), 120))
        return False
    await fb("PUT", "secrets", {"v": 1, "at": int(time.time()), "blob": blob})
    SECRETS_DIRTY = False
    # Giữ kho cấu hình của aistv_config.py đồng bộ: máy mới mở kho là có ngay
    # key vừa đổi bằng /key (không phải nhập lại / không chạy device login).
    if config_lib:
        try:
            await asyncio.to_thread(config_lib.vault_push, data)
        except Exception as e:
            log.warning("Không cập nhật được kho cấu hình: %s", oneline(str(e), 120))
    # Giữ blob khởi động khớp token bot hiện tại: đổi token mà không cập nhật
    # blob thì máy trắng đọc blob cũ sẽ không mở được kho cấu hình.
    try:
        import aistv_boot
        await asyncio.to_thread(aistv_boot.boot_push, data,
                                os.getenv("TELEGRAM_BOT_TOKEN", ""))
    except Exception as e:
        log.warning("Không cập nhật được blob khởi động: %s", oneline(str(e), 120))
    return True


async def cloud_restore_secrets() -> int:
    """Máy mới: giải mã bí mật trên cloud và ghi vào config.env (không ghi đè cái đã có)."""
    global ENV_ALLOWED, GEMINI_READY
    if not CLOUD_ENABLED:
        return 0
    payload = await fb("GET", "secrets")
    if not isinstance(payload, dict) or not payload.get("blob"):
        return 0
    try:
        data = decrypt_secrets(str(payload["blob"]))
    except Exception as e:
        log.warning("Bí mật trên cloud không giải mã được (đổi bot token?): %s",
                    oneline(str(e), 120))
        return 0
    SECRETS_CLOUD_KEYS.clear()
    SECRETS_CLOUD_KEYS.update(str(k) for k in data)
    restored = 0
    for name, value in data.items():
        if str(name).startswith("AISTV_VM_"):
            continue                     # xử lý riêng bên dưới (ghi vào vm_creds.json)
        value = str(value or "").strip()
        if not value:
            continue
        if name == "GITHUB_TOKEN":
            if github_token():
                continue
            try:
                await asyncio.to_thread(save_github_token, value)
                restored += 1
            except Exception as e:
                log.warning("Không khôi phục được GitHub token: %s", oneline(str(e), 120))
            continue
        if get_secret(name):
            continue
        try:
            save_env_var(name, value)
            restored += 1
        except Exception:
            continue
    cloud_vm = _vm_creds_from_cloud(data)
    if cloud_vm:
        local_vm = load_vm_creds()
        merged = dict(local_vm)
        for field, value in cloud_vm.items():
            if not merged.get(field):    # giữ creds đã có trên máy này
                merged[field] = value
        if merged != local_vm:
            _write_vm_creds(merged)
            restored += 1
            log.info("Khôi phục thông tin máy ảo từ cloud")
    if restored:
        ids = [int(x) for x in re.findall(r"\d+", get_secret("ALLOWED_USER_IDS"))]
        if ids:
            ENV_ALLOWED = ids
        if get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY"):
            GEMINI_READY = True
        if mail:
            try:
                mail.load(force=True)
            except Exception:
                pass
        log.info("Khôi phục %d bí mật từ cloud (%s)", restored, ", ".join(sorted(data)))
    return restored


# ── Trí nhớ dài hạn + lịch sử hội thoại đồng bộ 2 chiều ─────────────
async def cloud_merge_memory() -> str:
    """Gộp MEMORY.md cục bộ với bản trên cloud (giữ thứ tự, không trùng)."""
    global MEM_DIRTY
    if not CLOUD_ENABLED:
        return "tắt"
    remote = await fb("GET", "mem/items")
    remote = [str(x).strip() for x in remote] if isinstance(remote, list) else []
    remote = [x if x.startswith("- ") else "- " + x for x in remote if x]
    merged, added = list(memory_items()), 0
    for it in remote:
        if it not in merged:
            merged.append(it)
            added += 1
    if added:
        write_memory(merged)
    elif merged:
        MEM_DIRTY = True                     # bản cục bộ mới hơn → đẩy lên
    return f"{len(merged)} mục (+{added} từ cloud)"


async def cloud_push_memory() -> None:
    if CLOUD_ENABLED:
        await fb("PUT", "mem/items", memory_items())


async def cloud_push_history(chat_id: int) -> None:
    if CLOUD_ENABLED:
        await fb("PUT", f"hist/{chat_id}", load_history(chat_id)[-HIST_KEEP_REMOTE:])


async def cloud_pull_history(chat_id: int) -> int:
    if not CLOUD_ENABLED:
        return 0
    items = await fb("GET", f"hist/{chat_id}")
    if isinstance(items, list) and items:
        clean = [x for x in items if isinstance(x, dict) and x.get("role")]
        if clean:
            rewrite_history(chat_id, clean)
            return len(clean)
    return 0


async def ensure_history(chat_id: int) -> None:
    """Máy mới / Colab reset: lấy lại hội thoại của chat này từ cloud."""
    if not CLOUD_ENABLED or load_history(chat_id):
        return
    n = await cloud_pull_history(chat_id)
    if n:
        log.info("Khôi phục %d lượt hội thoại từ cloud (chat %s)", n, chat_id)


async def cloud_restore_all() -> None:
    if not CLOUD_ENABLED:
        log.info("Cloud: tắt (AISTV_CLOUD=0)")
        return
    try:
        await cloud_encrypt_existing()
    except Exception as e:
        log.warning("Mã hoá dữ liệu cloud cũ lỗi: %s", oneline(str(e), 120))
    try:
        mem = await cloud_merge_memory()
    except Exception as e:
        mem = "lỗi: " + oneline(str(e), 80)
    restored = 0
    hist = await fb("GET", "hist")
    if isinstance(hist, dict):
        for cid, items in hist.items():
            try:
                cid_i = int(cid)
            except (TypeError, ValueError):
                continue
            if load_history(cid_i) or not isinstance(items, list) or not items:
                continue
            clean = [x for x in items if isinstance(x, dict) and x.get("role")]
            if clean:
                rewrite_history(cid_i, clean)
                restored += 1
    await rem_restore()
    await watch_restore()
    log.info("Cloud sẵn sàng (%s) · trí nhớ: %s · %d hội thoại · %d nhắc việc · %d theo dõi",
             CLOUD_NS, mem, restored, len(REMINDERS), len(WATCHES))


async def cloud_loop() -> None:
    """Gom thay đổi rồi đẩy lên Firebase (tránh gọi mạng mỗi lần append)."""
    global MEM_DIRTY
    await asyncio.sleep(3)
    while True:
        try:
            if SECRETS_DIRTY:
                await cloud_push_secrets()
            if MEM_DIRTY:
                MEM_DIRTY = False
                await cloud_push_memory()
            for cid, ts in list(HIST_DIRTY.items()):
                if time.time() - ts >= HIST_PUSH_DELAY:
                    HIST_DIRTY.pop(cid, None)
                    await cloud_push_history(cid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("cloud_loop: %s", oneline(str(e), 160))
        await asyncio.sleep(2)


# ── Tự tóm tắt hội thoại dài → MEMORY.md ────────────────────────────
def add_memory_lines(lines: list) -> int:
    items, added = memory_items(), 0
    for raw in lines:
        line = (raw or "").strip().lstrip("-*• ").strip()
        if not line:
            continue
        entry = "- " + line[:400]
        if entry not in items:
            items.append(entry)
            added += 1
    if added:
        if len(items) > 400:                       # chỉ dọn mục auto cũ, giữ mục người dùng tự ghi
            autos = [i for i, x in enumerate(items) if x.startswith("- [tóm tắt ")]
            drop = set(autos[:max(0, len(items) - 400)])
            items = [x for i, x in enumerate(items) if i not in drop]
        write_memory(items)
    return added


async def ask_model_once(prompt: str, timeout: int = 300) -> tuple:
    """Gọi OpenCode 1 lần, không tool, không đụng state hội thoại."""
    if not OPENCODE_BIN:
        return False, "chưa có OpenCode"
    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)
    env.update(NO_COLOR="1", TERM="dumb")
    cmd = [OPENCODE_BIN, "run", "--model", opencode_model(), "--auto"]
    try:
        p = await asyncio.to_thread(subprocess.run, cmd, cwd=str(WORKSPACE), env=env,
                                    input=prompt[:MAX_PROMPT_BYTES - 2000],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=timeout)
    except Exception as e:
        return False, oneline(str(e), 200)
    if p.returncode != 0:
        return False, (p.stdout or "")[-400:] or f"mã lỗi {p.returncode}"
    out = clean_output(p.stdout or "")
    if _is_error_payload(out) or _is_opencode_error_output(out):
        return False, _pretty_error(out)
    return True, out


async def summarize_chat(chat_id: int, force: bool = False) -> Optional[str]:
    """Cô đọng các lượt cũ thành gạch đầu dòng trong MEMORY.md rồi cắt lịch sử."""
    if chat_id in SUMMARY_BUSY:
        return None
    items = load_history(chat_id)
    if len(items) < (6 if force else SUMMARY_MIN_ITEMS):
        return None
    SUMMARY_BUSY.add(chat_id)
    try:
        keep_n = max(SUMMARY_KEEP_ITEMS, 4)
        old, keep = items[:-keep_n], items[-keep_n:]
        convo = "\n".join(
            f"{'Người dùng' if i.get('role') == 'user' else 'AI STV'}: {oneline(i.get('content', ''), 400)}"
            for i in old)[-20000:]
        prompt = ("Bạn là bộ phận ghi nhớ của một trợ lý. Tóm tắt hội thoại dưới đây thành tối đa 10 dòng, "
                  "mỗi dòng bắt đầu bằng '- '. Chỉ giữ: sự kiện, quyết định, sở thích, thông tin cá nhân, "
                  "đường dẫn/tên file, mốc thời gian, việc còn dang dở. Bỏ lời chào, câu hỏi lặp, chi tiết vụn. "
                  "Không thêm lời dẫn, không dùng markdown đậm.\n\n" + convo)
        ok, txt = await ask_model_once(prompt, SUMMARY_TIMEOUT)
        if not ok:
            log.warning("Tóm tắt chat %s thất bại: %s", chat_id, oneline(txt, 200))
            return None
        lines = [l.strip() for l in txt.splitlines() if l.strip().startswith(("-", "*", "•"))]
        if not lines:
            lines = ["- " + oneline(txt, 300)]
        lines = [f"[tóm tắt {now():%d/%m %H:%M}] " + l.lstrip("-*• ").strip() for l in lines[:10]]
        added = add_memory_lines(lines)
        rewrite_history(chat_id, keep)
        if CLOUD_ENABLED:
            await cloud_push_memory()                  # lưu ngay, không chờ vòng nền
            await fb("PUT", f"summary/{chat_id}", {"at": int(time.time()), "items": len(old), "added": added})
            HIST_DIRTY.pop(chat_id, None)
            await cloud_push_history(chat_id)
        log.info("Tóm tắt chat %s: %d lượt → %d mục trí nhớ", chat_id, len(old), added)
        return f"đã cô đọng {len(old)} lượt cũ thành {added} mục trí nhớ"
    finally:
        SUMMARY_BUSY.discard(chat_id)


def maybe_schedule_summary(chat_id: int) -> None:
    if not AUTO_SUMMARY or chat_id in SUMMARY_BUSY or chat_id in SUMMARY_PENDING:
        return
    if len(load_history(chat_id)) < SUMMARY_MIN_ITEMS:
        return
    SUMMARY_PENDING.add(chat_id)

    async def runner():
        try:
            for _ in range(60):                   # chờ khi bot rảnh (tối đa ~10 phút)
                if not RUNNING and not LOCKS[chat_id].locked():
                    break
                await asyncio.sleep(10)
            await summarize_chat(chat_id)
        except Exception as e:
            log.warning("Auto-summary chat %s lỗi: %s", chat_id, oneline(str(e), 200))
        finally:
            SUMMARY_PENDING.discard(chat_id)

    try:
        asyncio.create_task(runner())
    except RuntimeError:
        SUMMARY_PENDING.discard(chat_id)


# ── Nhắc việc / việc định kỳ ────────────────────────────────────────
def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(3)


def _when_str(ts) -> str:
    try:
        dt = datetime.fromtimestamp(float(ts), TZ) if TZ else datetime.fromtimestamp(float(ts))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "?"


def _in_str(ts) -> str:
    try:
        d = max(0, int(float(ts) - time.time()))
    except Exception:
        return ""
    if d < 60:
        return f"{d}s"
    if d < 3600:
        return f"{d // 60} phút"
    if d < 86400:
        return f"{d // 3600}h{d % 3600 // 60:02d}"
    return f"{d // 86400} ngày"


def _next_at(hh: int, mm: int, add_days: int = 0) -> float:
    base = now().replace(hour=min(max(hh, 0), 23), minute=min(max(mm, 0), 59),
                         second=0, microsecond=0)
    if add_days:
        base += timedelta(days=add_days)
    elif base.timestamp() <= time.time() + 30:
        base += timedelta(days=1)
    return base.timestamp()


def parse_schedule(text: str):
    """Trả (epoch|None, kiểu lặp, phần nội dung còn lại).
    Nhận: +30m · 20:30 · 20h30 · daily 8:00 · mai 8:00 · 25/12 20:00 · 25/12/2026 20:00"""
    t = (text or "").strip()
    if not t:
        return None, "", ""
    m = re.match(r"^\+\s*(\d+)\s*([^\s\d]+)?\s*(.*)$", t)
    if m:
        sec = _UNITS.get((m.group(2) or "m").lower().rstrip("."))
        if sec:
            return time.time() + int(m.group(1)) * sec, "none", m.group(3).strip()
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\s+(?:lúc\s+)?(\d{1,2})[h:.](\d{2})?\s*(.*)$",
                 t, re.I)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else now().year
        if yr < 100:
            yr += 2000
        hh, mm = int(m.group(4)), int(m.group(5) or 0)
        try:
            base = datetime(yr, mo, d, min(hh, 23), min(mm, 59), tzinfo=TZ) if TZ \
                else datetime(yr, mo, d, min(hh, 23), min(mm, 59))
        except ValueError:
            return None, "", t
        return base.timestamp(), "none", m.group(6).strip()
    m = re.match(r"^(?:daily|hằng ngày|hang ngay|mỗi ngày|moi ngay)\s+(\d{1,2})[h:.]?(\d{2})?\s*(.*)$",
                 t, re.I)
    if m:
        return _next_at(int(m.group(1)), int(m.group(2) or 0)), "daily", m.group(3).strip()
    m = re.match(r"^(?:(mai|ngày mai|ngay mai|tomorrow)\s+)?(\d{1,2})[h:.](\d{2})?\s*(.*)$", t, re.I)
    if m:
        hh, mm = int(m.group(2)), int(m.group(3) or 0)
        return _next_at(hh, mm, 1 if m.group(1) else 0), "none", m.group(4).strip()
    return None, "", t


async def rem_save(push: bool = True) -> None:
    _save_json(REMIND_FILE, REMINDERS)
    if CLOUD_ENABLED and push:
        await fb("PUT", "rem", REMINDERS)


def _prune_reminders(records: dict, now_ts: float | None = None) -> dict:
    """Lọc nhắc việc: bỏ mục hỏng, đánh dấu quá hạn, bỏ mục quá cũ (>30 ngày)."""
    now_ts = time.time() if now_ts is None else now_ts
    out = {k: v for k, v in (records or {}).items()
           if isinstance(v, dict) and v.get("when")}
    for key, rec in list(out.items()):
        try:
            when = float(rec.get("when"))
        except (TypeError, ValueError):
            out.pop(key, None)
            continue
        if rec.get("repeat") == "daily" or when >= now_ts - 2 * 86400:
            continue
        if now_ts - when > 30 * 86400:
            out.pop(key, None)              # quá cũ: bỏ hẳn
        else:
            rec["expired"] = True           # quá hạn: báo một lần rồi xoá
    return out


async def rem_restore() -> None:
    data = await fb("GET", "rem") if CLOUD_ENABLED else None
    cloud_ok = isinstance(data, dict) or not CLOUD_ENABLED
    if not isinstance(data, dict):
        data = {}
    for k, v in _load_json(REMIND_FILE).items():
        data.setdefault(k, v)
    REMINDERS.clear()
    REMINDERS.update(_prune_reminders(data))
    await rem_save(push=cloud_ok)          # cloud lỗi thì chỉ ghi cục bộ, tránh xoá dữ liệu cloud


def build_reminders() -> str:
    if not REMINDERS:
        return ("⏰ <b>Chưa có nhắc việc</b>\n"
                "• <code>/remind +30m uống nước</code>\n"
                "• <code>/remind 20:30 họp nhóm</code>\n"
                "• <code>/remind mai 8:00 nộp báo cáo</code>\n"
                "• <code>/remind daily 8:00 điểm danh</code>\n"
                "• <code>/task daily 9:00 kiểm tra repo có lỗi mới</code>")
    rows = []
    for r in sorted(REMINDERS.values(), key=lambda x: float(x.get("when", 0))):
        icon = "🤖" if r.get("kind") == "agent" else "⏰"
        rep = " · mỗi ngày" if r.get("repeat") == "daily" else ""
        flag = "⚠️ quá hạn · " if r.get("expired") else ""
        rows.append(f"{icon} <code>{esc(r.get('id'))}</code> · {flag}{esc(_when_str(r.get('when')))}{rep}"
                    f" <i>({esc(_in_str(r.get('when')))})</i>\n   {esc(oneline(r.get('text', ''), 140))}")
    return ("⏰ <b>Nhắc việc &amp; việc định kỳ</b>\n" + "\n".join(rows)
            + "\n\nXoá: <code>/unremind &lt;mã|all&gt;</code>")


async def send_plain(app, chat_id: int, text: str, html_ok: bool = False, markup=None) -> None:
    text = (text or "").strip()
    if not text:
        return
    parts = [text[i:i + 3800] for i in range(0, len(text), 3800)]
    for i, part in enumerate(parts):
        try:
            await app.bot.send_message(
                chat_id, part,
                parse_mode=HTML if html_ok else None,
                link_preview_options=NO_PREVIEW,
                reply_markup=markup if i == len(parts) - 1 else None)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            log.warning("send_plain tới %s lỗi: %s", chat_id, e)
            return


TASK_RUNNING: set = set()


async def _run_scheduled_task_guarded(app, rec: dict) -> None:
    chat_id = int(rec["chat"])
    if chat_id in TASK_RUNNING:
        return
    TASK_RUNNING.add(chat_id)
    try:
        async with LOCKS[chat_id]:
            await _run_scheduled_task(app, rec)
    except Exception as e:
        log.warning("Việc định kỳ chat %s lỗi: %s", chat_id, oneline(str(e), 200))
    finally:
        TASK_RUNNING.discard(chat_id)


async def _run_scheduled_task(app, rec: dict) -> None:
    chat_id = int(rec["chat"])
    text = rec.get("text", "")
    await send_plain(app, chat_id, f"⏰ <b>Việc định kỳ:</b> {esc(oneline(text, 200))}", html_ok=True)
    ok, ans = await run_agent(chat_id, build_prompt(
        chat_id, f"[TỰ ĐỘNG THEO LỊCH · {now():%d/%m %H:%M}] {text}"))
    if ok:
        append_history(chat_id, "user", f"[tự động] {text}")
        append_history(chat_id, "assistant", ans[:6000])
        maybe_schedule_summary(chat_id)
        await send_plain(app, chat_id, ans)
    else:
        await send_plain(app, chat_id, "⚠️ " + ans)


async def tick_reminders(app) -> None:
    if not REMINDERS:
        return
    changed = False
    for rid, rec in list(REMINDERS.items()):
        try:
            ts = float(rec.get("when", 0))
        except (TypeError, ValueError):
            REMINDERS.pop(rid, None)
            changed = True
            continue
        if ts > time.time():
            continue
        chat_id = int(rec.get("chat") or 0)
        if not chat_id:
            REMINDERS.pop(rid, None)
            changed = True
            continue
        if rec.get("expired"):
            await send_plain(
                app, chat_id,
                f"⚠️ <b>Việc đã quá hạn</b> · {esc(_when_str(ts))}\n{esc(rec.get('text', ''))}\n"
                f"<i>Bot không chạy đúng lúc nên việc này bị lỡ; đã bỏ khỏi danh sách.</i>",
                html_ok=True)
            REMINDERS.pop(rid, None)
            changed = True
            continue
        if rec.get("kind") == "agent":
            if chat_id in RUNNING or chat_id in TASK_RUNNING or LOCKS[chat_id].locked():
                rec["when"] = time.time() + 180          # đang bận → lùi 3 phút
                changed = True
                continue
            try:
                asyncio.create_task(_run_scheduled_task_guarded(app, dict(rec)))
            except RuntimeError:
                rec["when"] = time.time() + 180
                changed = True
                continue
        else:
            await send_plain(
                app, chat_id,
                f"⏰ <b>Nhắc việc</b> · {esc(_when_str(ts))}\n{esc(rec.get('text', ''))}",
                html_ok=True,
                markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Đã xong",
                                                                   callback_data=f"done:{rid}")]]))
        if rec.get("repeat") == "daily":
            dt = datetime.fromtimestamp(ts, TZ) if TZ else datetime.fromtimestamp(ts)
            rec["when"] = _next_at(dt.hour, dt.minute, 1)
        else:
            REMINDERS.pop(rid, None)
        changed = True
    if changed:
        await rem_save()


# ── Theo dõi repo / log / file ──────────────────────────────────────
def _norm_repo(s: str) -> str:
    s = re.sub(r"^(?:https?://|git@)github\.com[:/]", "", (s or "").strip())
    return re.sub(r"\.git$", "", s).strip("/")


def _path_digest(p: Path) -> str:
    h = hashlib.sha256()
    try:
        if p.is_dir():
            for f in sorted(x for x in p.rglob("*") if x.is_file())[:500]:
                h.update(str(f.relative_to(p)).encode())
                h.update(str(f.stat().st_mtime_ns).encode())
        elif p.exists():
            with p.open("rb") as fh:
                h.update(fh.read(2 * 1024 * 1024))
        else:
            return "missing"
    except Exception as e:
        return "err:" + oneline(str(e), 40)
    return h.hexdigest()[:16]


async def watch_save() -> None:
    _save_json(WATCH_FILE, WATCHES)
    if CLOUD_ENABLED:
        await fb("PUT", "watch", WATCHES)


async def watch_restore() -> None:
    data = await fb("GET", "watch") if CLOUD_ENABLED else None
    if not isinstance(data, dict):
        data = {}
    for k, v in _load_json(WATCH_FILE).items():
        data.setdefault(k, v)
    WATCHES.clear()
    WATCHES.update({k: v for k, v in data.items() if isinstance(v, dict) and v.get("kind")})


async def _watch_git(app, w: dict) -> None:
    repo, branch = w.get("repo", ""), w.get("branch") or "main"
    url = (f"https://api.github.com/repos/{repo}/commits/"
           + urllib.parse.quote(branch, safe=""))
    data = await asyncio.to_thread(_gh_http, url, None, github_token(), 25)
    sha = (data or {}).get("sha") or ""
    if not sha:
        return
    w["last"] = time.time()
    if w.get("sha") == sha:
        return
    old, w["sha"] = w.get("sha"), sha
    await watch_save()
    if not old:
        return                                   # lần đầu chỉ ghi nhận
    commit = data.get("commit") or {}
    msg = ((commit.get("message") or "").splitlines() or [""])[0][:200]
    who = (commit.get("author") or {}).get("name") or "?"
    await send_plain(app, int(w["chat"]),
                     f"🔔 <b>Repo có commit mới</b> · <code>{esc(repo)}@{esc(branch)}</code>\n"
                     f"• <code>{sha[:7]}</code> bởi {esc(who)}\n• {esc(msg)}\n"
                     f"{esc(data.get('html_url', ''))}", html_ok=True)


async def _watch_log(app, w: dict) -> None:
    p = Path(os.path.expanduser(w.get("path", "")))
    if not p.is_file():
        return
    size = p.stat().st_size
    off = int(w.get("offset") or 0)
    if size < off:
        off = 0
    if size == off:
        return
    if size - off > 300_000:
        off = size - 300_000
    with p.open("rb") as fh:
        fh.seek(off)
        chunk = fh.read()
    w["offset"], w["last"] = size, time.time()
    rx = re.compile(w.get("regex") or _ERROR_RX.pattern, re.I)
    hits = [l.strip()[:300] for l in chunk.decode("utf-8", "replace").splitlines() if rx.search(l)]
    if not hits:
        await watch_save()
        return
    digest = hashlib.sha1("\n".join(hits).encode()).hexdigest()
    w["digest"] = digest
    if digest == w.get("last_digest") or time.time() - float(w.get("notified") or 0) < 300:
        w["last_digest"] = digest
        await watch_save()
        return
    w["last_digest"], w["notified"] = digest, time.time()
    await watch_save()
    await send_plain(
        app, int(w["chat"]),
        f"🚨 <b>Log có lỗi mới</b>\n<code>{esc(oneline(str(p), 120))}</code>\n"
        + "\n".join(f"• {esc(h)}" for h in hits[-5:]), html_ok=True)


async def _watch_file(app, w: dict) -> None:
    p = Path(os.path.expanduser(w.get("path", "")))
    digest = await asyncio.to_thread(_path_digest, p)
    old, w["digest"], w["last"] = w.get("digest"), digest, time.time()
    await watch_save()
    if old and digest != old and not str(digest).startswith(("missing", "err")):
        await send_plain(app, int(w["chat"]),
                         f"👀 <b>File/thư mục thay đổi</b>\n<code>{esc(oneline(str(p), 160))}</code>",
                         html_ok=True)


async def tick_watches(app) -> None:
    for wid, w in list(WATCHES.items()):
        try:
            default = WATCH_GIT_INTERVAL if w.get("kind") == "git" else WATCH_INTERVAL
            every = int(w["every"]) if w.get("every") is not None else default
            if time.time() - float(w.get("last") or 0) < every:
                continue
            if w.get("kind") == "git":
                await _watch_git(app, w)
            elif w.get("kind") == "log":
                await _watch_log(app, w)
            elif w.get("kind") == "file":
                await _watch_file(app, w)
        except Exception as e:
            log.warning("Watch %s (%s) lỗi: %s", wid, w.get("kind"), oneline(str(e), 160))


def build_watches() -> str:
    if not WATCHES:
        return ("👀 <b>Chưa theo dõi gì</b>\n"
                "• <code>/watch git owner/repo [nhánh]</code> — báo khi có commit mới\n"
                "• <code>/watch log /đường/dẫn.log [regex]</code> — báo dòng lỗi mới\n"
                "• <code>/watch file /đường/dẫn</code> — báo khi file/thư mục thay đổi\n"
                "Bot tự theo dõi log của chính nó để báo lỗi.")
    rows = []
    for w in WATCHES.values():
        icon = {"git": "🐙", "log": "🚨", "file": "📄"}.get(w.get("kind"), "👀")
        target = w.get("repo") or w.get("path") or "?"
        rows.append(f"{icon} <code>{esc(w.get('id'))}</code> · {esc(oneline(target, 120))}"
                    f"\n   chat <code>{esc(w.get('chat'))}</code> · mỗi {int(w.get('every') or 0)}s")
    return ("👀 <b>Đang theo dõi</b>\n" + "\n".join(rows)
            + "\n\nXoá: <code>/watch del &lt;mã|all&gt;</code>")


async def install_self_watch() -> None:
    oid = owner_id()
    if not WATCH_SELF or not PROACTIVE or not oid:
        return
    if any(w.get("kind") == "log" and w.get("path") == str(LOG_FILE) for w in WATCHES.values()):
        return
    wid = _new_id("w")
    WATCHES[wid] = {"id": wid, "kind": "log", "path": str(LOG_FILE), "chat": oid,
                    "every": WATCH_INTERVAL, "last": 0,
                    "offset": LOG_FILE.stat().st_size if LOG_FILE.exists() else 0,
                    "regex": r"(?i)(lỗi không xử lý được|traceback|critical|fatal|panic|unhandled)"}
    await watch_save()
    log.info("Tự theo dõi log bot: %s", LOG_FILE)


async def _scheduler_loop(app) -> None:
    if not PROACTIVE:
        log.info("Chế độ chủ động: tắt (AISTV_PROACTIVE=0)")
        return
    await asyncio.sleep(8)
    while True:
        try:
            await tick_reminders(app)
            await tick_watches(app)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("scheduler_loop: %s", oneline(str(e), 160))
        await asyncio.sleep(REMIND_TICK)


# ── Lệnh Telegram cho 8b ────────────────────────────────────────────
@guard()
async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _add_schedule(update, context, "text")


@guard()
async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _add_schedule(update, context, "agent")


async def _add_schedule(update, context, kind: str) -> None:
    msg = update.effective_message
    text = " ".join(context.args or []).strip()
    when, repeat, body = parse_schedule(text)
    name = "task" if kind == "agent" else "remind"
    if when is None or not body:
        await msg.reply_text(
            f"⏰ Cú pháp: /{name} &lt;thời gian&gt; &lt;nội dung&gt;\n"
            "• <code>+30m</code> · <code>+2h</code> · <code>+1d</code>\n"
            "• <code>20:30</code> (hôm nay, quá giờ thì mai) · <code>mai 8:00</code>\n"
            "• <code>25/12 20:00</code> · <code>daily 8:00</code>", parse_mode=HTML)
        return
    rid = _new_id("r")
    REMINDERS[rid] = {"id": rid, "chat": update.effective_chat.id, "when": float(when),
                      "text": body[:500], "kind": kind, "repeat": repeat,
                      "by": update.effective_user.id if update.effective_user else 0}
    await rem_save()
    rep = " · lặp hằng ngày" if repeat == "daily" else ""
    label = "🤖 Việc định kỳ" if kind == "agent" else "⏰ Nhắc việc"
    await msg.reply_text(
        f"<b>{label} đã hẹn</b>{rep}\n• Lúc: {esc(_when_str(when))} <i>({esc(_in_str(when))})</i>\n"
        f"• Nội dung: {esc(body[:300])}\n• Mã: <code>{rid}</code>", parse_mode=HTML)


@guard()
async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(build_reminders(), parse_mode=HTML)


@guard()
async def cmd_unremind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args[0].strip().lower() if context.args else "")
    if not arg:
        await update.effective_message.reply_text("Dùng: /unremind <mã|all> — xem mã bằng /reminders")
        return
    if arg == "all":
        n = len(REMINDERS)
        REMINDERS.clear()
    else:
        n = 0
        for k in [k for k in REMINDERS if k == arg]:
            REMINDERS.pop(k, None)
            n += 1
    await rem_save()
    await update.effective_message.reply_text(f"🗑 Đã xoá {n} nhắc việc." if n else "Không tìm thấy mã đó.")


@guard()
async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    args = context.args or []
    if not args:
        await msg.reply_text(build_watches(), parse_mode=HTML)
        return
    sub = args[0].lower()
    if sub in ("del", "delete", "xoa", "xoá", "remove", "rm"):
        target = args[1].strip() if len(args) > 1 else ""
        if target == "all":
            n = len(WATCHES)
            WATCHES.clear()
        else:
            n = 0
            for k in [k for k in WATCHES if k == target]:
                WATCHES.pop(k, None)
                n += 1
        await watch_save()
        await msg.reply_text(f"🗑 Đã xoá {n} theo dõi." if n else "Không tìm thấy mã đó.")
        return
    wid = _new_id("w")
    if sub == "git":
        repo = _norm_repo(args[1]) if len(args) > 1 else current_repo_slug()
        branch = args[2] if len(args) > 2 else "main"
        if not repo:
            await msg.reply_text("Dùng: /watch git owner/repo [nhánh]\n"
                                 "(chưa có repo đích — đặt bằng /github repos)")
            return
        if "/" not in repo:
            await msg.reply_text("Repo phải dạng owner/name (ví dụ Phucvncom55/AISTV).")
            return
        WATCHES[wid] = {"id": wid, "kind": "git", "repo": repo, "branch": branch,
                        "chat": chat.id, "every": WATCH_GIT_INTERVAL, "sha": "", "last": 0}
        note = f"🐙 Theo dõi <code>{esc(repo)}@{esc(branch)}</code> · mỗi {WATCH_GIT_INTERVAL}s"
    elif sub in ("log", "file"):
        if len(args) < 2:
            await msg.reply_text(f"Dùng: /watch {sub} <đường dẫn>" + (" [regex]" if sub == "log" else ""))
            return
        path = os.path.expanduser(args[1])
        rec = {"id": wid, "kind": sub, "path": path, "chat": chat.id,
               "every": WATCH_INTERVAL, "last": 0}
        if sub == "log":
            rec["offset"] = os.path.getsize(path) if os.path.isfile(path) else 0
            if len(args) > 2:
                rec["regex"] = " ".join(args[2:])
        else:
            rec["digest"] = _path_digest(Path(path))
        WATCHES[wid] = rec
        note = f"👀 Theo dõi <code>{esc(oneline(path, 120))}</code> · mỗi {WATCH_INTERVAL}s"
    else:
        await msg.reply_text("Loại theo dõi: <code>git</code>, <code>log</code>, <code>file</code>",
                             parse_mode=HTML)
        return
    await watch_save()
    await msg.reply_text(f"{note}\nMã: <code>{wid}</code> · xem: /watch", parse_mode=HTML)


@guard()
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat_id = update.effective_message, update.effective_chat.id
    if len(load_history(chat_id)) < 6:
        await msg.reply_text(f"🧠 Chỉ có {len(load_history(chat_id))} lượt — chưa cần tóm tắt.")
        return
    note = await msg.reply_text("🧠 Đang cô đọng hội thoại vào trí nhớ dài hạn…")
    res = await summarize_chat(chat_id, force=True)
    await note.edit_text("✅ " + (res or "Không có gì mới để tóm tắt."))


def build_cloud(chat_id: int) -> str:
    st = CLOUD_STAT
    if not CLOUD_ENABLED:
        state = "⚪ tắt"
    elif st["ok"] is None:
        state = "🟡 chưa kết nối"
    elif st["ok"]:
        state = "🟢 kết nối"
    else:
        state = "🔴 lỗi"
    at = f"{int(time.time() - st['at'])}s trước" if st["at"] else "—"
    host = urllib.parse.urlparse(FIREBASE_URL).netloc if FIREBASE_URL else "—"
    hint = ("" if CLOUD_ENABLED else
            "Bật: <code>/cloud url https://&lt;db&gt;.firebaseio.com</code>\n")
    return ("☁️ <b>Trí nhớ đám mây (Firebase)</b>\n"
            f"• Trạng thái: {state}\n"
            f"• URL: <code>{esc(host)}</code>\n"
            f"• Namespace: <code>{esc(CLOUD_NS)}</code>\n"
            f"• Lần cuối: {esc(st['last'] or '—')} · {esc(at)}\n"
            f"• Đã đẩy: {st['up']} · Lỗi: {st['err']}\n"
            f"• Trí nhớ dài hạn: {len(memory_items())} mục\n"
            f"• Hội thoại chat này: {len(load_history(chat_id))} lượt\n"
            f"• Nhắc việc: {len(REMINDERS)} · Theo dõi: {len(WATCHES)}\n"
            f"• Bí mật đồng bộ: {sum(1 for n in SECRET_SYNC_KEYS if get_secret(n))} mục (mã hoá bằng token bot)\n"
            "• Máy mới: chỉ cần <code>TELEGRAM_BOT_TOKEN</code> — tự khôi phục, không hỏi mã GitHub\n"
            f"• Tóm tắt tự động: {'bật' if AUTO_SUMMARY else 'tắt'} sau {SUMMARY_MIN_ITEMS} lượt\n\n"
            + hint +
            "Đồng bộ ngay: <code>/cloud sync</code>\n"
            "⚠️ Rules của database đang mở (ai biết URL cũng đọc/ghi được) — nên siết lại.")


@guard()
async def cmd_cloud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global FIREBASE_URL, CLOUD_ENABLED
    msg, chat_id = update.effective_message, update.effective_chat.id
    args = context.args or []
    sub = args[0].lower() if args else ""
    if sub in ("url", "db", "set"):
        if not (update.effective_user and is_owner(update.effective_user.id)):
            await msg.reply_text("Chỉ chủ bot đổi được URL cloud.")
            return
        url = args[1].strip().rstrip("/") if len(args) > 1 else ""
        if not re.match(r"^https://[A-Za-z0-9._-]+\.(?:firebaseio\.com|firebasedatabase\.app)$",
                        url):
            await msg.reply_text(
                "Dùng: <code>/cloud url https://&lt;db&gt;.firebaseio.com</code>",
                parse_mode=HTML)
            return
        FIREBASE_URL = url
        CLOUD_ENABLED = True
        try:
            save_env_var("AISTV_FIREBASE_URL", url)
        except Exception as e:
            log.warning("Không ghi được AISTV_FIREBASE_URL: %s", oneline(str(e), 120))
        restored = await cloud_restore_secrets()
        ok = await cloud_push_secrets()
        await msg.reply_text(
            "☁️ <b>Đã bật đồng bộ Firebase</b>\n"
            f"• URL: <code>{esc(url)}</code>\n"
            + (f"• Khôi phục {restored} mục từ cloud.\n" if restored else "")
            + ("• Đã đẩy bí mật (GitHub token, PAT/key máy ảo, API key) lên cloud."
               if ok else
               "• ⚠️ Chưa đẩy được — kiểm tra mạng/rules rồi gửi /cloud sync."),
            parse_mode=HTML)
        return
    if sub in ("sync", "dong-bo", "đồng-bộ"):
        await cloud_push_memory()
        await cloud_push_history(chat_id)
        await rem_save()
        await watch_save()
        secrets_ok = await cloud_push_secrets()
        await msg.reply_text("☁️ Đã đẩy trí nhớ, hội thoại, nhắc việc & theo dõi lên cloud."
                             + ("\n🔐 Bí mật (token/API key) đã mã hoá và đồng bộ." if secrets_ok else ""))
        return
    await msg.reply_text(build_cloud(chat_id), parse_mode=HTML)


# ── Email (IMAP/SMTP) ────────────────────────────────────────────────
EMAIL_LAST: dict = {}                  # chat_id -> [uid, ...] theo thứ tự đã liệt kê
EMAIL_STAT = {"ok": None, "at": 0.0, "err": "", "fp": ""}


def _email_fp(cfg: dict) -> str:
    """Vân tay cấu hình: đổi email/mật khẩu/host → kết quả test cũ không còn giá trị."""
    raw = "|".join(str(cfg.get(k) or "") for k in
                   ("address", "password", "imap_host", "imap_port", "smtp_host", "smtp_port"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _clean_app_password(parts) -> str:
    """Gmail hiển thị App Password dạng 'abcd efgh ijkl mnop' — bỏ hết khoảng trắng.

    Nếu không gộp, lệnh /email setup chỉ lấy được 4 ký tự đầu (bug cũ).
    """
    return re.sub(r"\s+", "", " ".join(parts or []))


def _email_pw_label(cfg: dict) -> str:
    pw = cfg.get("password") or ""
    if not pw:
        return "⚠️ thiếu"
    if cfg.get("domain") in ("gmail.com", "googlemail.com") and len(pw) != 16:
        return f"⚠️ đã đặt nhưng chỉ {len(pw)} ký tự (Gmail cần đủ 16)"
    return "đã đặt"


def build_email() -> str:
    if not mail:
        return "⚠️ Bản bot này thiếu <code>aistv_email.py</code> nên chưa dùng được email."
    cfg = mail.load(force=True)
    if not cfg.get("address"):
        return mail.HELP
    pw = _email_pw_label(cfg)
    fp = _email_fp(cfg)
    if EMAIL_STAT.get("fp") and EMAIL_STAT["fp"] != fp:
        EMAIL_STAT.update(ok=None, at=0.0, err="", fp="")   # cấu hình đã đổi → bỏ kết quả cũ
    if EMAIL_STAT["ok"] is True:
        login = f"🟢 OK · {int(time.time() - EMAIL_STAT['at'])}s trước"
    elif EMAIL_STAT["ok"] is False:
        login = "🔴 " + esc(oneline(EMAIL_STAT["err"], 120))
    else:
        login = "🟡 chưa kiểm tra — chạy /email test"
    return (
        "📧 <b>Email</b>\n"
        f"• Hộp thư: <code>{esc(cfg['address'])}</code>\n"
        f"• Mật khẩu ứng dụng: {pw}\n"
        f"• IMAP: <code>{esc(cfg['imap_host'])}:{cfg['imap_port']}</code>\n"
        f"• SMTP: <code>{esc(cfg['smtp_host'])}:{cfg['smtp_port']}</code>\n"
        f"• Lần kiểm tra: {login}\n\n"
        "<b>Dùng</b>\n"
        "/email test — kiểm tra kết nối\n"
        "/email inbox [n] — hộp thư · /email unread [n] — chưa đọc\n"
        "/email read &lt;số|uid&gt; — đọc thư\n"
        "/email send a@b.c | Tiêu đề | Nội dung — gửi thư\n"
        "/email setup &lt;email&gt; &lt;app-password&gt; — đổi cấu hình\n"
        "/email reset — xoá cấu hình"
    )


def _parse_email_read(chat_id: int, key: str) -> str:
    key = (key or "").strip()
    if key.lower().startswith("uid"):
        return key[3:].strip(" :#") or key
    if key.isdigit():
        uids = EMAIL_LAST.get(chat_id) or []
        n = int(key)
        if 1 <= n <= len(uids):
            return uids[n - 1]
    return key


@guard()
async def cmd_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat_id = update.effective_message, update.effective_chat.id
    args = context.args or []
    sub = args[0].lower() if args else ""
    owner = is_owner(update.effective_user.id)
    if not mail:
        await msg.reply_text("⚠️ Bản bot này thiếu <code>aistv_email.py</code>.", parse_mode=HTML)
        return
    try:
        if sub in ("", "status", "help"):
            await msg.reply_text(build_email(), parse_mode=HTML)
            return
        if sub == "setup":
            if not owner:
                await msg.reply_text("⛔ Chỉ chủ bot mới đổi được cấu hình email.")
                return
            if len(args) < 3:
                await msg.reply_text(
                    "Dùng: <code>/email setup ban@gmail.com mat-khau-ung-dung</code>\n"
                    "Nên dùng <b>App Password</b> 16 ký tự. Bot sẽ xoá tin nhắn chứa mật khẩu.",
                    parse_mode=HTML)
                return
            cfg = mail.save(args[1], _clean_app_password(args[2:]))
            EMAIL_STAT.update(ok=None, at=0.0, err="", fp="")   # cấu hình mới → chưa kiểm tra
            if CLOUD_ENABLED:
                asyncio.create_task(cloud_push_secrets())
            try:
                await msg.delete()
            except Exception:
                pass
            note = (f"✅ Đã lưu email <code>{esc(cfg['address'])}</code>.\n"
                    "Thử ngay: /email test")
            if cfg.get("domain") in ("gmail.com", "googlemail.com") and len(cfg.get("password") or "") != 16:
                note += ("\n⚠️ App Password Gmail phải đủ <b>16 ký tự</b> — bạn vừa nhập "
                         f"{len(cfg.get('password') or '')}. Tạo tại "
                         "myaccount.google.com/apppasswords rồi dán cả 16 ký tự "
                         "(có khoảng trắng cũng được).")
            if mail.get_secret("AISTV_EMAIL_ADDRESS") or mail.get_secret("AISTV_EMAIL_PASSWORD"):
                note += ("\n⚠️ Biến môi trường/Colab Secrets đang ghi đè cấu hình này — "
                         "xoá secret nếu muốn dùng bản vừa lưu.")
            await msg.reply_text(note, parse_mode=HTML)
            return
        if sub == "reset":
            if not owner:
                await msg.reply_text("⛔ Chỉ chủ bot mới xoá được cấu hình email.")
                return
            removed = mail.clear()
            EMAIL_LAST.pop(chat_id, None)
            EMAIL_STAT.update(ok=None, at=0.0, err="", fp="")
            await msg.reply_text("🗑 Đã xoá cấu hình email đã lưu." if removed
                                 else "ℹ️ Không có cấu hình email nào đã lưu.")
            return
        if sub == "test":
            note = await msg.reply_text("📧 Đang kiểm tra kết nối email…")
            try:
                mail.load(force=True)
                info = await asyncio.to_thread(mail.test)
                EMAIL_STAT.update(ok=True, at=time.time(), err="", fp=_email_fp(mail.load()))
                await note.edit_text(
                    f"✅ <b>Email hoạt động</b>\n"
                    f"• Hộp thư: <code>{esc(info['address'])}</code>\n"
                    f"• INBOX: {info['messages']} thư\n"
                    f"• IMAP <code>{esc(info['imap'])}</code> · SMTP <code>{esc(info['smtp'])}</code>",
                    parse_mode=HTML)
            except Exception as e:
                EMAIL_STAT.update(ok=False, at=time.time(), err=str(e), fp=_email_fp(mail.load()))
                await note.edit_text(f"❌ {esc(str(e))}\n\nXem lại /email.", parse_mode=HTML)
            return
        if sub in ("inbox", "unread"):
            limit = 8
            if len(args) > 1 and args[1].isdigit():
                limit = max(1, min(int(args[1]), 15))
            note = await msg.reply_text("📬 Đang tải hộp thư…")
            rows = await asyncio.to_thread(mail.list_messages, limit, sub == "unread")
            EMAIL_LAST[chat_id] = [r["uid"] for r in rows]
            EMAIL_STAT.update(ok=True, at=time.time(), err="", fp=_email_fp(mail.load()))
            if not rows:
                await note.edit_text("📭 Không có thư nào.")
                return
            lines = [f"📬 <b>{'Thư chưa đọc' if sub == 'unread' else 'Hộp thư'}</b> · {len(rows)} thư"]
            for i, r in enumerate(rows, 1):
                mark = "🟡" if r.get("unread") else "⚪"
                subj = esc(oneline(r["subject"], 80))
                who = esc(oneline(r["from"], 45))
                when = esc(oneline(r["date"], 30))
                lines.append(f"{i}. {mark} <b>{subj}</b>\n   <i>{who}</i> · {when} · <code>{esc(r['uid'])}</code>")
            lines.append("\nĐọc: <code>/email read &lt;số&gt;</code>")
            body = "\n".join(lines)
            await note.edit_text(body[:3900], parse_mode=HTML, link_preview_options=NO_PREVIEW)
            return
        if sub == "read":
            if len(args) < 2:
                await msg.reply_text("Dùng: /email read <số trong danh sách|uid>")
                return
            uid = _parse_email_read(chat_id, args[1])
            note = await msg.reply_text("📖 Đang đọc thư…")
            m = await asyncio.to_thread(mail.read_message, uid)
            body = m["body"][:3200] + ("\n…" if m.get("truncated") or len(m["body"]) > 3200 else "")
            head = (f"📧 <b>{esc(oneline(m['subject'], 150))}</b>\n"
                    f"<i>{esc(oneline(m['from'], 80))}</i> · {esc(oneline(m['date'], 40))}")
            if m.get("attachments"):
                head += "\n📎 " + esc(", ".join(m["attachments"]))
            text = head + f"\n\n<blockquote expandable>{esc(body)}</blockquote>"
            await note.edit_text(text[:3900], parse_mode=HTML, link_preview_options=NO_PREVIEW)
            return
        if sub == "send":
            if not owner:
                await msg.reply_text("⛔ Chỉ chủ bot mới gửi được email.")
                return
            raw = " ".join(args[1:])
            parts = [x.strip() for x in raw.split("|", 2)]
            if len(parts) < 3 or not parts[0] or not parts[2]:
                await msg.reply_text(
                    "Dùng: <code>/email send nguoinhan@example.com | Tiêu đề | Nội dung</code>",
                    parse_mode=HTML)
                return
            note = await msg.reply_text("✉️ Đang gửi…")
            await asyncio.to_thread(mail.send, parts[0], parts[1], parts[2])
            await note.edit_text(f"✅ Đã gửi tới <code>{esc(parts[0])}</code>.", parse_mode=HTML)
            return
        await msg.reply_text(build_email(), parse_mode=HTML)
    except Exception as e:
        await msg.reply_text(f"❌ Email lỗi: {esc(str(e))}", parse_mode=HTML)


async def _web2api_loop():
    """Giữ cookie/server luôn mới: dán cookie.txt là tự chạy, máy mới tự kéo."""
    tick = 0
    while True:
        try:
            if tick == 0:
                await asyncio.to_thread(web2api.auto, True)
            else:
                await asyncio.to_thread(web2api.sync_if_changed)
                if tick % 12 == 0:
                    await asyncio.to_thread(web2api.pull_if_safe)
                if not await asyncio.to_thread(web2api.health):
                    await asyncio.to_thread(web2api.ensure_server)
        except Exception as exc:
            log.debug("Web2API nền: %s", oneline(str(exc), 160))
        tick += 1
        await asyncio.sleep(10)


@guard(owner_only=True)
async def cmd_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bật/tắt và chặn khách khi nhóm spam (chỉ chủ bot)."""
    global GUEST_CHAT
    msg = update.effective_message
    args = [str(a).strip().lower() for a in (context.args or []) if str(a).strip()]
    action = args[0] if args else ""
    if action in ("on", "off") and len(args) == 1:
        GUEST_CHAT = action == "on"
        GUEST_ACTIVE["chat"] = action == "on"
        if not GUEST_CHAT:
            GUEST_ACTIVE["media"] = False
            GUEST_ACTIVE["vision"] = False
        await msg.reply_text(
            f"👥 Khách: <b>{'BẬT' if GUEST_CHAT else 'TẮT'}</b>"
            + ("" if GUEST_CHAT else " (ảnh/sơ đồ, đọc ảnh/video cũng tắt)"), parse_mode=HTML)
        return
    if action in ("images", "media", "anh", "ảnh", "image"):
        sub = args[1] if len(args) > 1 else ""
        if sub not in ("on", "off"):
            await msg.reply_text("Dùng: <code>/guest images on|off</code>", parse_mode=HTML)
            return
        GUEST_ACTIVE["media"] = sub == "on" and GUEST_ACTIVE["chat"]
        await msg.reply_text(
            f"🎨 Tạo ảnh cho khách: <b>{'BẬT' if GUEST_ACTIVE['media'] else 'TẮT'}</b>",
            parse_mode=HTML)
        return
    if action in ("vision", "read", "see", "doc", "media-read"):
        sub = args[1] if len(args) > 1 else ""
        if sub not in ("on", "off"):
            await msg.reply_text("Dùng: <code>/guest vision on|off</code>", parse_mode=HTML)
            return
        GUEST_ACTIVE["vision"] = sub == "on" and GUEST_ACTIVE["chat"]
        await msg.reply_text(
            f"👁️ Đọc ảnh/video cho khách: <b>{'BẬT' if GUEST_ACTIVE['vision'] else 'TẮT'}</b>",
            parse_mode=HTML)
        return
    if action == "ban":
        try:
            uid = int(args[1])
        except (IndexError, ValueError):
            await msg.reply_text("Dùng: <code>/guest ban &lt;user_id&gt; [phút]</code>",
                                 parse_mode=HTML)
            return
        if uid == owner_id():
            await msg.reply_text("⚠️ Không chặn chủ bot.")
            return
        try:
            minutes = int(args[2]) if len(args) > 2 else 60
        except ValueError:
            minutes = 60
        GUEST_BANS[uid] = 0.0 if minutes <= 0 else time.time() + minutes * 60
        for key in [k for k in GUEST_HIST if k[1] == uid]:
            GUEST_HIST.pop(key, None)
        GUEST_MODEL_BY_USER.pop(uid, None)
        await msg.reply_text(
            f"🚫 Đã chặn khách <code>{uid}</code>"
            + (" vĩnh viễn (tới khi restart)." if minutes <= 0 else f" trong {minutes} phút."),
            parse_mode=HTML)
        return
    if action == "unban":
        try:
            uid = int(args[1])
        except (IndexError, ValueError):
            await msg.reply_text("Dùng: <code>/guest unban &lt;user_id&gt;</code>", parse_mode=HTML)
            return
        GUEST_BANS.pop(uid, None)
        await msg.reply_text(f"✅ Đã bỏ chặn <code>{uid}</code>.", parse_mode=HTML)
        return
    if action == "bans":
        if not GUEST_BANS:
            await msg.reply_text("Không có ai bị chặn.")
            return
        now = time.time()
        rows = []
        for uid, until in list(GUEST_BANS.items()):
            if until and until < now:
                GUEST_BANS.pop(uid, None)
                continue
            rows.append(f"• <code>{uid}</code> — "
                        + ("vĩnh viễn" if not until else f"còn {int((until - now) // 60) + 1} phút"))
        await msg.reply_text("🚫 <b>Đang chặn</b>\n" + ("\n".join(rows) or "Không có ai."),
                             parse_mode=HTML)
        return
    if action and action not in ("status", "st"):
        await msg.reply_text(
            "Lệnh: <code>/guest on|off</code> · <code>/guest images on|off</code> · "
            "<code>/guest vision on|off</code> · "
            "<code>/guest ban &lt;id&gt; [phút]</code> · <code>/guest unban &lt;id&gt;</code> · "
            "<code>/guest bans</code>", parse_mode=HTML)
        return
    active_bans = [u for u, t in GUEST_BANS.items() if not t or t > time.time()]
    await msg.reply_text(
        "👥 <b>Chế độ khách</b>\n"
        f"• Chat/code: {'BẬT' if GUEST_CHAT and GUEST_ACTIVE['chat'] else 'TẮT'}\n"
        f"• Tạo ảnh/sơ đồ: {'BẬT' if GUEST_ACTIVE['media'] else 'TẮT'}\n"
        f"• Đọc ảnh/video: {'BẬT' if GUEST_ACTIVE['vision'] else 'TẮT'}\n"
        f"• Model mặc định: <code>{esc(GUEST_MODEL)}</code> "
        f"({len(GUEST_MODEL_OPTIONS)} model cho khách)\n"
        f"• Ngữ cảnh riêng đang giữ: {len(GUEST_HIST)} người\n"
        f"• Đang chặn: {len(active_bans)}\n\n"
        f"Giới hạn: {GUEST_RATE} tin/phút · 1 ảnh/{GUEST_MEDIA_GAP}s · "
        f"{GUEST_MEDIA_RATE} ảnh/giờ mỗi người.",
        parse_mode=HTML)


@guard()
async def cmd_web2api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý Gemini dự phòng (chỉ chủ bot)."""
    msg = update.effective_message
    if web2api is None:
        await msg.reply_text("⚠️ Thiếu module Gemini trong repo.", parse_mode=HTML)
        return
    action = (context.args[0].lower().lstrip("-") if context.args else "status")
    if action in ("status", "st", ""):
        info = await asyncio.to_thread(web2api.status_report)
        lines = [
            "✨ <b>Gemini dự phòng</b>",
            f"• Bật: {'có' if info['enabled'] and WEB2API_FALLBACK else 'không'} · "
            f"model <code>{esc(WEB2API_MODEL)}</code>",
            f"• Server: <code>{esc(info['url'])}</code> "
            f"({'🟢 chạy' if info['running'] else '🔴 không chạy'})",
            f"• Cookie: {'✅ có' if info['cookie'] else '❌ chưa có'} · "
            f"XSRF: {'✅' if info['xsrf'] else '❌'} · "
            f"GitHub: {'✅ đã đồng bộ' if info['synced'] else '⏳ chưa đẩy'}",
            f"• Xem/tạo ảnh: {'✅ sẵn sàng' if info.get('images_ready') else ('⚠️ thiếu curl_cffi' if info.get('images') and not info.get('curl_cffi') else ('⚠️ server chưa chạy' if info.get('images') else '❌ chưa vá — chạy /gemini restart'))}",
            f"• Nghe voice / xem video: {'✅ đã vá' if info.get('media') else '❌ chưa vá — chạy /gemini restart'}"
            f" · {'🟢 server chạy' if info.get('running') else '🔴 server tắt'}",
            f"• File dán cookie: <code>{esc(info['cookie_file'])}</code>",
            f"• Kho đồng bộ: <code>{esc(info['store'])}</code> (nguyên văn, repo private)",
            "",
            "Lệnh: <code>/gemini start|stop|restart|refresh|pull|push|auto</code>",
            "Dán cookie mới: <code>/gemini import __Secure-1PSID=...; SAPISID=...</code>",
        ]
        await msg.reply_text("\n".join(lines), parse_mode=HTML)
        return
    if not is_owner(update.effective_user.id):
        await msg.reply_text("🔒 Chỉ chủ bot được điều khiển Gemini.")
        return
    if action in ("import", "cookie", "set"):
        text = " ".join(context.args[1:]).strip()
        if not text:
            await msg.reply_text("Dùng: <code>/gemini import &lt;chuỗi cookie&gt;</code>",
                                 parse_mode=HTML)
            return
        try:
            await msg.delete()                     # tin nhắn chứa cookie — xoá ngay
        except Exception:
            pass
        note = await msg.chat.send_message("⏳ Đang nạp cookie…")
        try:
            ok, detail = await asyncio.to_thread(web2api.import_text, text)
            await note.edit_text(("✅ " if ok else "❌ ") + esc(str(detail))[:3800])
        except Exception as e:
            await note.edit_text(f"❌ {esc(str(e))}"[:3800])
        return
    note = await msg.reply_text("⏳ Đang xử lý…")
    try:
        if action == "start":
            ok, detail = await asyncio.to_thread(web2api.start)
        elif action == "stop":
            ok, detail = await asyncio.to_thread(web2api.stop)
        elif action == "restart":
            await asyncio.to_thread(web2api.stop)
            ok, detail = await asyncio.to_thread(web2api.start)
        elif action == "refresh":
            ok, detail = await asyncio.to_thread(web2api.refresh_xsrf)
            if ok:
                detail = "đã cập nhật XSRF token"
        elif action == "pull":
            ok, detail = await asyncio.to_thread(web2api.pull_secrets)
            if ok:
                await asyncio.to_thread(web2api.refresh_xsrf, True)
                await asyncio.to_thread(web2api.ensure_server, False)
                detail = "đã tải cookie + làm mới XSRF + bật server"
        elif action == "push":
            ok, detail = await asyncio.to_thread(web2api.push_secrets)
        elif action in ("auto", "sync"):
            ok, detail = await asyncio.to_thread(web2api.auto, False)
        else:
            await note.edit_text("Dùng: <code>/gemini start|stop|restart|refresh|pull|push|auto</code>",
                                 parse_mode=HTML)
            return
        await note.edit_text(("✅ " if ok else "❌ ") + esc(str(detail))[:3800])
    except Exception as e:
        await note.edit_text(f"❌ {esc(str(e))}"[:3800])


# ════════════════════════════════════════════════════════════════════
# 9. KHỞI CHẠY
# ════════════════════════════════════════════════════════════════════
COMMANDS = [
    ("start", "Giới thiệu & menu"), ("new", "Cuộc trò chuyện mới"), ("stop", "Huỷ tác vụ đang chạy"),
    ("plan", "Lập kế hoạch & tự thực thi"), ("undo", "Hoàn tác thay đổi gần nhất"),
    ("tieptuc", "Làm tiếp việc đang dở trên máy khác"),
    ("status", "Trạng thái bot"), ("model", "Xem / đổi model"), ("models", "Danh sách model"),
    ("remember", "Ghi nhớ dài hạn"), ("memory", "Xem trí nhớ"), ("forget", "Xoá trí nhớ"),
    ("skills", "Danh sách skills"), ("skill", "Chạy / thêm skill"),
    ("think", "Bật/tắt hiện suy nghĩ"), ("activity", "Ẩn/hiện chi tiết việc đang làm"),
    ("variant", "Mức reasoning của model"),
    ("remind", "Hẹn nhắc việc"), ("task", "Việc tự chạy theo lịch"), ("reminders", "Danh sách nhắc việc"),
    ("unremind", "Xoá nhắc việc"), ("watch", "Theo dõi repo/log"), ("cloud", "Trí nhớ đám mây"),
    ("image", "Tạo ảnh / sơ đồ tư duy"), ("see", "Đọc ảnh bằng Gemini"),
    ("mindmap", "Vẽ sơ đồ tư duy"), ("pages", "Lời giải dài → ảnh từng trang"),
    ("video", "Xem video bằng Gemini"),
    ("summary", "Tóm tắt hội thoại vào trí nhớ"), ("email", "Đọc / gửi email"),
    ("github", "Kết nối / quản lý GitHub"), ("vm", "Tạo / dừng máy ảo Windows (test)"),
    ("update", "Cập nhật bot từ GitHub"),
    ("push", "Đẩy code lên GitHub (đồng bộ sang Windows)"),
    ("restart", "Khởi động lại bot"),
    ("key", "Xem / đặt API key"),
    ("gemini", "Gemini dự phòng — chat, ảnh, video, sơ đồ"),
    ("ask", "Hỏi trong nhóm không cần @mention"),
    ("guest", "Bật/tắt, chặn khách"),
    ("files", "File trong workspace"), ("get", "Tải file về"), ("help", "Hướng dẫn"),
]


def _merge_env_file(path: Path, text: str) -> int:
    """Thêm các biến còn thiếu từ text vào path; không ghi đè giá trị đang có."""
    existing = set()
    try:
        if path.is_file():
            for line in path.read_text("utf-8", "replace").splitlines():
                s = line.strip()
                if s.startswith("export "):
                    s = s[7:].lstrip()
                if s and not s.startswith("#") and "=" in s:
                    existing.add(s.split("=", 1)[0].strip())
    except Exception:
        pass
    added = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        name = s.split("=", 1)[0].strip()
        if name and name not in existing:
            added.append(s)
            existing.add(name)
    if not added:
        return 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = path.read_bytes() if path.is_file() else b""
        with path.open("ab") as f:
            if prev and not prev.endswith((b"\n", b"\r")):
                f.write(b"\n")
            f.write(("\n".join(added) + "\n").encode("utf-8"))
        try:
            if not IS_WINDOWS:
                path.chmod(0o600)
        except Exception:
            pass
    except Exception:
        return 0
    return len(added)


def _remote_config_text() -> str:
    """Tải config.env từ AISTV_ENV_URL hoặc repo private (dự phòng cho bản cũ)."""
    try:
        if config_lib is not None:
            values, _src = config_lib.read_files()
            remote, _labels = config_lib.fetch_remote(values)
            if remote:
                return "\n".join(f"{k}={v}" for k, v in remote.items())
    except Exception:
        pass
    url = (os.getenv("AISTV_ENV_URL") or "").strip()
    if url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "aistv"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            pass
    repo = (os.getenv("AISTV_CONFIG_REPO") or "Phucvncom55/AISTV-secrets").strip()
    if not repo or repo.lower() in ("0", "off"):
        return ""
    token = ""
    for name in ("AISTV_CONFIG_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        token = (os.getenv(name) or "").strip()
        if token:
            break
    if not token:
        try:
            token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                                   timeout=15).stdout.strip()
        except Exception:
            token = ""
    if not token:
        return ""
    path = (os.getenv("AISTV_CONFIG_PATH") or "config.env").strip() or "config.env"
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github.raw",
                     "User-Agent": "aistv"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return ""


def _bootstrap_remote_config() -> int:
    """Máy mới: tự nạp token/API key từ config.env dùng chung trên GitHub."""
    if get_secret("TELEGRAM_BOT_TOKEN"):
        return 0
    # get_token() đã gọi aistv_config.sync; đây là đường dự phòng cho bản cũ.
    text = _remote_config_text()
    if not text or "=" not in text:
        return 0
    try:
        shared = (config_lib.shared_config_path() if config_lib is not None
                  else Path(os.getenv("AISTV_CONFIG_DIR", "").strip()
                            or (Path.home() / ".config" / "aistv")) / "config.env")
    except Exception:
        shared = Path.home() / ".config" / "aistv" / "config.env"
    added = _merge_env_file(shared, text)
    if added:
        _load_env_path(shared)
        log.info("Nạp %d mục cấu hình từ kho lưu trữ (%s)", added, shared)
    return added


def _valid_bot_token(value: str) -> bool:
    """Token BotFather: 123456789:AAH... — chan dan nham lenh khac vao prompt."""
    return bool(re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", (value or "").strip()))


def _prompt_bot_token() -> str:
    """Hỏi token bot ngay (trước khi đồng bộ) để mở được kho cấu hình mã hoá."""
    try:
        if not sys.stdin.isatty():
            return ""
    except Exception:
        return ""
    os.environ["AISTV_TOKEN_ASKED"] = "1"
    for _attempt in range(3):
        try:
            entered = getpass.getpass("🔑 Dán Telegram Bot Token (lấy từ @BotFather): ").strip()
        except (EOFError, OSError):
            entered = ""
        if not entered:
            break
        if not _valid_bot_token(entered):
            print("❌ Token không đúng định dạng (phải dạng 123456:ABC...). Không lưu.")
            continue
        try:
            path = save_env_var("TELEGRAM_BOT_TOKEN", entered)
            print(f"✅ Đã lưu token vào {path} — lần sau không cần nhập lại.")
        except Exception:
            pass
        return entered
    return ""


def get_token() -> str:
    # Runner (run.bat / run.ps1 / run.sh) đã đồng bộ trước khi chạy bot → bỏ qua.
    if not os.getenv("AISTV_CONFIG_SYNCED"):
        # Hỏi token TRƯỚC khi đồng bộ: kho cấu hình mã hoá chỉ cần token bot,
        # nên không phải đăng nhập GitHub bằng mã trên máy mới.
        if not get_secret("TELEGRAM_BOT_TOKEN") and os.getenv("AISTV_ASK_TOKEN_FIRST", "1") != "0":
            _prompt_bot_token()
        if config_lib is not None:
            try:
                # Chỉ bảo vệ biến do người dùng đặt thật; key đọc từ file thì
                # cho phép GitHub cập nhật (đổi token/key trên web là có hiệu lực).
                protected = set(os.environ) - set(ENV_FROM_FILES)
                result = config_lib.sync(quiet=True, protected=protected)
                for name, value in (result.get("values") or {}).items():
                    if name in ENV_FROM_FILES and value:
                        os.environ[name] = value
                _load_dotenv()
            except Exception:
                pass
        else:
            _bootstrap_remote_config()
            _load_dotenv()
        os.environ["AISTV_CONFIG_SYNCED"] = "1"
    tok = get_secret("TELEGRAM_BOT_TOKEN")
    if not tok and config_lib is None:
        _bootstrap_remote_config()
        _load_dotenv()
        tok = get_secret("TELEGRAM_BOT_TOKEN")
    if tok and not _valid_bot_token(tok):
        print("⚠ TELEGRAM_BOT_TOKEN hiện có sai định dạng — bỏ qua, sẽ hỏi lại.")
        tok = ""
    if not tok:
        tok = _prompt_bot_token()
    if not tok:
        raise SystemExit(
            "❌ Thiếu TELEGRAM_BOT_TOKEN.\n"
            "   • Chạy run.bat / run.ps1 / run.sh — dán token bot một lần, các key còn lại\n"
            "     (GitHub, Gemini, Cloudflare…) tự khôi phục từ kho cấu hình mã hoá.\n"
            "   • Hoặc thêm TELEGRAM_BOT_TOKEN vào Colab Secrets (bật Notebook access).\n"
            "   • Hoặc tạo file .env trong thư mục AISTV với dòng:\n"
            "       TELEGRAM_BOT_TOKEN=123456:ABC...\n"
            "   • Kiểm tra: python aistv_config.py doctor"
        )
    return tok


def _startup_github() -> None:
    tok = github_token()
    if not tok:
        return
    try:
        info = apply_github_config(tok)
        log.info("GitHub sẵn sàng: %s (%s)", info.get("login") or "?", github_token_source())
    except Exception as e:
        log.warning("GitHub token có sẵn nhưng không dùng được: %s", oneline(str(e), 200))


async def post_init(app) -> None:
    global BOT_OBJ
    BOT_OBJ = app.bot
    try:
        start_ask_server()
    except Exception as e:
        log.warning("Không mở được ask_user server: %s", e)
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    me = await app.bot.get_me()
    global CLOUD_NS
    CLOUD_NS = f"{CLOUD_NS_BASE}/{me.id}"      # namespace riêng cho từng bot
    print(f"✅ Bot online: @{me.username}  |  model: {STATE['model']}")
    if CLOUD_ENABLED:
        try:
            await cloud_restore_secrets()          # phải xong trước khi nhận tin nhắn
            local = await asyncio.to_thread(_local_secret_values)
            if any(k not in SECRETS_CLOUD_KEYS for k in local):
                await cloud_push_secrets()         # máy này có bí mật cloud chưa biết (vd. email)
        except Exception as e:
            log.warning("Khôi phục bí mật từ cloud: %s", oneline(str(e), 160))
        asyncio.create_task(cloud_restore_all())
        asyncio.create_task(cloud_loop())
    if PROACTIVE:
        asyncio.create_task(_scheduler_loop(app))
    asyncio.create_task(install_self_watch())
    if WEB2API_FALLBACK and web2api is not None:
        # Giữ server + cookie luôn mới: máy mới tự kéo cookie trên GitHub, dán
        # cookie vào file là tự nạp lại và chạy — không cần lệnh start.
        asyncio.create_task(_web2api_loop())
    if github_token():
        asyncio.create_task(asyncio.to_thread(_startup_github))
    if owner_id():
        print(f"👑 Chủ bot (user id): {owner_id()}")
        try:
            await app.bot.send_message(owner_id(), f"🟢 <b>AI STV đã online</b> · <code>{esc(STATE['model'])}</code>",
                                       parse_mode=HTML)
        except Exception:
            pass                                   # chủ bot chưa từng /start với bot → bỏ qua
    else:
        print("👑 Chưa có chủ bot — người nhắn tin riêng đầu tiên sẽ trở thành chủ bot.")
        print("   💡 Muốn khoá chắc chắn: thêm secret ALLOWED_USER_IDS (user id Telegram của bạn) rồi chạy lại.")
    print(f"📁 Dữ liệu: {HOME}")


def main() -> None:
    global BOT_TOKEN, OPENCODE_BIN, OPENCODE_VERSION
    BOT_TOKEN = get_token()
    OPENCODE_BIN = find_opencode() or ""
    if not OPENCODE_BIN:
        raise SystemExit("❌ Không tìm thấy lệnh opencode.")
    try:
        _r = subprocess.run([OPENCODE_BIN, "--version"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=20)
        OPENCODE_VERSION = (_r.stdout or "").strip().splitlines()[-1]
    except Exception:
        pass
    if _opencode_major(OPENCODE_VERSION) < 2:
        msg = (f"⚠️ OpenCode đang dùng bản cũ ({OPENCODE_VERSION or '?'}): {OPENCODE_BIN}\n"
               "   Dữ liệu phiên bản mới (v2) sẽ không đọc được → lỗi "
               "\"Database is not empty and has no session table\" và /models trống.\n"
               "   Cài bản mới: curl -fsSL https://opencode.ai/v2/install | bash "
               "(hoặc đặt OPENCODE_BIN trỏ tới binary v2) rồi chạy lại bot.")
        print(msg)
        log.warning(msg)

    threading.Thread(target=_headroom_warm, name="headroom-warm", daemon=True).start()

    app = (ApplicationBuilder().token(BOT_TOKEN).post_init(post_init)
           .concurrent_updates(True)          # để /stop hoạt động khi đang xử lý
           .build())
    for names, fn in [(["start"], cmd_start), (["help"], cmd_help), (["new", "reset", "clear"], cmd_new),
                      (["stop"], cmd_stop), (["plan"], cmd_plan), (["undo"], cmd_undo),
                      (["tieptuc", "resume", "continue"], cmd_resume),
                      (["status"], cmd_status), (["model"], cmd_model),
                      (["models"], cmd_models), (["remember"], cmd_remember), (["memory"], cmd_memory),
                      (["forget"], cmd_forget), (["skills"], cmd_skills), (["skill"], cmd_skill),
                      (["think"], cmd_think), (["activity", "progress"], cmd_activity),
                      (["variant"], cmd_variant),
                      (["remind"], cmd_remind), (["task", "cron"], cmd_task),
                      (["reminders", "remindlist"], cmd_reminders), (["unremind"], cmd_unremind),
                      (["watch", "monitor"], cmd_watch), (["cloud"], cmd_cloud),
                      (["image", "img", "draw", "ve", "taoanh"], cmd_image),
                      (["see", "vision", "docanh"], cmd_see),
                      (["mindmap", "sodotuduy"], cmd_mindmap),
                      (["pages", "trang"], cmd_pages),
                      (["video"], cmd_video),
                      (["summary", "summarize"], cmd_summary), (["email", "mail"], cmd_email),
                      (["github"], cmd_github), (["vm"], cmd_vm),
                      (["update"], cmd_update), (["push"], cmd_push),
                      (["restart"], cmd_restart),
                      (["files"], cmd_files), (["get"], cmd_get), (["allow"], cmd_allow), (["deny"], cmd_deny),
                      (["key", "keys"], cmd_key),
                      (["gemini", "web2api", "w2a"], cmd_web2api),
                      (["ask"], cmd_ask),
                      (["guest", "khach"], cmd_guest)]:
        app.add_handler(CommandHandler(names, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO & filters.UpdateType.MESSAGE, handle_photo))
    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.VIDEO_NOTE | filters.ANIMATION) & filters.UpdateType.MESSAGE,
        handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.UpdateType.MESSAGE, handle_document))
    app.add_handler(MessageHandler((filters.VOICE | filters.AUDIO) & filters.UpdateType.MESSAGE,
                                   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, handle_text))
    app.add_error_handler(on_error)

    print("🚀 Đang khởi chạy AI STV Agent… (dừng bằng nút ■ của ô Colab)")
    try:
        # BẮT BUỘC truyền allowed_updates: Telegram ghi nhớ giá trị của lần getUpdates
        # trước đó. Nếu lần trước chỉ đăng ký ["message"] thì mọi callback_query (nút bấm)
        # sẽ KHÔNG bao giờ được gửi tới bot -> bấm nút không có phản ứng gì.
        app.run_polling(allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True, stop_signals=None, close_loop=False)
    except KeyboardInterrupt:
        print("🛑 Bot đã dừng.")


if __name__ == "__main__":
    main()
