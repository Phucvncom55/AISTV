# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════════════╗
║   AI STV AGENT  —  Telegram × OpenCode   (dán 1 ô Colab là chạy)   ║
╚════════════════════════════════════════════════════════════════════╝

CÁCH DÙNG
  • Chạy 1 lệnh từ GitHub (repo public):
      bash <(curl -fsSL https://raw.githubusercontent.com/<USER>/<REPO>/main/run.sh)
  • Trong repo đã clone:
      bash run.sh
  • Trên Colab: dán TOÀN BỘ file này vào MỘT ô code → Run (tự cài đặt),
    hoặc thêm secret TELEGRAM_BOT_TOKEN rồi chạy lệnh run.sh ở trên.
  • Token: đặt TELEGRAM_BOT_TOKEN (env / Colab Secrets / .env). Nếu thiếu, bot sẽ hỏi.
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
import os, sys, re, json, time, html, shutil, asyncio, getpass, logging, subprocess, functools, hashlib
import secrets, shlex, threading, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

CLEAN_INSTALL = os.getenv("AISTV_CLEAN_INSTALL", "1") != "0"   # 0 = giữ bản OpenCode đã cài, không xoá & cài lại
USE_GOOGLE_DRIVE = False        # True = lưu trí nhớ/lịch sử vào Google Drive (sống sót khi Colab reset)
FULL_ACCESS = True              # True = agent được đọc/ghi NGOÀI workspace, chạy lệnh & truy cập web
                                #        không cần hỏi quyền (mọi tool của OpenCode đều được auto-approve)
DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"   # đổi nhanh bằng /model hoặc biến OPENCODE_MODEL
TIMEZONE = "Asia/Ho_Chi_Minh"
MAX_HISTORY = 12                # số lượt hỏi-đáp đưa vào ngữ cảnh
MAX_PARALLEL = 2                # số tiến trình OpenCode chạy cùng lúc
AGENT_TIMEOUT = int(os.getenv("AISTV_AGENT_TIMEOUT", "0") or 0)
                                # 0 = KHÔNG giới hạn thời gian (mặc định, cho dự án lớn)
                                # >0 = số giây tối đa cho 1 yêu cầu
ASK_TIMEOUT = int(os.getenv("AISTV_ASK_TIMEOUT", "0") or 0)
                                # 0 = agent chờ người dùng trả lời không giới hạn
GH_CLIENT_ID = os.getenv("AISTV_GH_CLIENT_ID", "178c6fc778ccc68e1d6a")   # GitHub CLI (public client)
GH_SCOPES = os.getenv("AISTV_GH_SCOPES", "repo workflow read:user")
MAX_PROMPT_BYTES = 110_000      # giới hạn an toàn cho 1 tham số dòng lệnh Linux (128KB)
SPLIT_LIMIT = 3000              # ký tự tối đa mỗi tin nhắn Telegram (trước khi đổi sang HTML)
PROGRESS_DETAIL = 500           # ký tự tối đa cho mỗi đoạn chi tiết (lệnh, code, output) trong tin nhắn tiến độ
PROGRESS_KEEP = 6               # số việc gần nhất hiển thị trong tin nhắn tiến độ


# ════════════════════════════════════════════════════════════════════
# 1. TỰ ĐỘNG CÀI ĐẶT MÔI TRƯỜNG
# ════════════════════════════════════════════════════════════════════
def _sh(cmd: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", "set -o pipefail; " + cmd],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=timeout)


def find_opencode() -> Optional[str]:
    for p in (os.path.expanduser("~/.opencode/bin"), "/root/.opencode/bin"):
        if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
            os.environ["PATH"] += os.pathsep + p
    return os.getenv("OPENCODE_BIN") or shutil.which("opencode")


def setup_environment() -> None:
    print("⏳ [1/3] Kiểm tra thư viện Python (python-telegram-bot, nest_asyncio)...")
    try:
        __import__("telegram")
        __import__("nest_asyncio")
    except ImportError:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                            "python-telegram-bot", "nest_asyncio"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise SystemExit("❌ Thiếu thư viện Python và không cài được.\n"
                             "   Chạy bằng run.sh, hoặc: python3 -m pip install -r requirements.txt")
    print("✅ [1/3] Thư viện Python OK")

    print("⏳ [2/3] Cài OpenCode...")
    if CLEAN_INSTALL or not find_opencode():
        _sh("rm -rf ~/.local/share/opencode ~/.opencode")
        res = _sh("curl -fsSL https://opencode.ai/install | bash")
        if res.returncode != 0:
            print("\n".join(res.stdout.splitlines()[-15:]))
    binary = find_opencode()
    if not binary:
        raise SystemExit("❌ Không cài được OpenCode. Chạy lại ô này hoặc kiểm tra mạng Colab.")
    print(f"✅ [3/3] OpenCode sẵn sàng: {binary}")


if os.getenv("STV_SKIP_SETUP") != "1":
    setup_environment()

import nest_asyncio
nest_asyncio.apply()

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
INBOX = WORKSPACE / "inbox"
SESSIONS = HOME / "sessions"
ARCHIVE = HOME / "archive"
SECRETS_DIR = HOME / ".secrets"
GITHUB_TOKEN_FILE = SECRETS_DIR / "github_token"
STATE_FILE = HOME / "state.json"
for _d in (WORKSPACE, MEMORY_DIR, SKILLS_DIR, INBOX, SESSIONS, ARCHIVE, SECRETS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
try:
    SECRETS_DIR.chmod(0o700)
except Exception:
    pass

START_TIME = time.time()
BOT_TOKEN = ""
OPENCODE_BIN = ""
OPENCODE_VERSION = "?"
RUNNING: dict = {}                 # chat_id -> tiến trình OpenCode đang chạy
CANCELLED: set = set()
LOCKS = defaultdict(asyncio.Lock)  # mỗi chat xử lý tuần tự
SEM = asyncio.Semaphore(MAX_PARALLEL)

BOT_OBJ = None                     # Application.bot (đặt trong post_init)
BOT_LOOP: Optional[asyncio.AbstractEventLoop] = None
ASK_SERVER = None                  # HTTP server nội bộ cho tool ask_user
ASK_URL = ""
ASK_TOKEN = ""
ASK_REQUESTS: dict = {}            # ask_id -> yêu cầu đang chờ người dùng trả lời
ASK_BY_CHAT: dict = {}             # chat_id -> ask_id
ASK_LOCK = threading.Lock()

THINKING: dict = {}                # chat_id -> [các đoạn reasoning model đã trả về]
THINK_TOKENS: dict = {}            # chat_id -> số token reasoning
THINKING_LAST: dict = {}           # chat_id -> thời điểm nhận reasoning gần nhất
GH_TOKEN_CACHE = ""                # token GitHub đang dùng (để che trong log/output)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)       # httpx in URL chứa token → tắt
logging.getLogger("httpcore").setLevel(logging.WARNING)
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
STATE.setdefault("variant", os.getenv("OPENCODE_VARIANT", ""))
STATE.setdefault("show_thinking", True)          # hiện phần "suy nghĩ" của model
STATE.setdefault("show_activity", False)         # hiện chi tiết việc agent đang làm (lệnh, code, output)
STATE.setdefault("github_user", "")


def save_state() -> None:
    STATE_FILE.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), "utf-8")


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


def guard(owner_only: bool = False):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
            if not (user and chat and msg):
                return
            if not authorized(user.id, chat.type):
                if chat.type == "private":
                    await msg.reply_text(
                        f"⛔ Đây là bot riêng tư.\nID của bạn: {user.id}\n"
                        f"Chủ bot có thể cấp quyền bằng: /allow {user.id}")
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
11. `skills/` chứa quy trình chuyên biệt — làm đúng theo skill khi được kích hoạt.
"""

MEMORY_HEADER = "# MEMORY — Trí nhớ dài hạn\n"

SKILL_CODE_REVIEW = """# code-review
Review code nghiêm túc như một senior engineer.

## Quy trình
1. Xác định mục đích đoạn code và ngôn ngữ/framework.
2. Tìm lỗi logic, edge case, bảo mật (secret lộ, injection), hiệu năng, khả năng bảo trì.
3. Trả lời theo mẫu: **Tóm tắt** → **Vấn đề (ưu tiên cao → thấp)** → **Bản sửa đề xuất (code)** → **Gợi ý thêm**.
4. Mỗi vấn đề nêu: ở đâu, vì sao là vấn đề, cách sửa cụ thể.
"""

SKILL_RESEARCH = """# nghien-cuu
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


def bootstrap_workspace() -> None:
    files = {
        WORKSPACE / "SOUL.md": SOUL_MD,
        WORKSPACE / "AGENTS.md": AGENTS_MD,
        WORKSPACE / "MEMORY.md": MEMORY_HEADER,
        SKILLS_DIR / "code-review" / "SKILL.md": SKILL_CODE_REVIEW,
        SKILLS_DIR / "nghien-cuu" / "SKILL.md": SKILL_RESEARCH,
        WORKSPACE / ".opencode" / "tools" / "ask_user.js": ASK_TOOL_JS,
    }
    for path, content in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, "utf-8")
        elif path.name == "ask_user.js":
            try:
                old = path.read_text("utf-8")
            except Exception:
                old = ""
            if old != content:
                path.write_text(content, "utf-8")   # luôn cập nhật tool theo bản bot
    # Cấu hình OpenCode cho workspace (luôn ghi lại để công tắc FULL_ACCESS có hiệu lực)
    cfg = {"$schema": "https://opencode.ai/config.json"}
    if FULL_ACCESS:
        cfg["permission"] = "allow"
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
    body = MEMORY_HEADER + ("\n" + "\n".join(items) + "\n" if items else "")
    (WORKSPACE / "MEMORY.md").write_text(body, "utf-8")


def list_skills() -> list:
    out = []
    for p in sorted(SKILLS_DIR.iterdir()):
        f = p / "SKILL.md" if p.is_dir() else (p if p.suffix == ".md" else None)
        if f and f.exists():
            desc = next((l.strip() for l in read_text(f).splitlines()[1:] if l.strip() and not l.startswith("#")), "")
            out.append((p.stem if p.is_file() else p.name, oneline(desc, 80)))
    return out


def find_skill(name: str) -> Optional[str]:
    if not re.fullmatch(r"[\w-]+", name):
        return None
    for f in (SKILLS_DIR / name / "SKILL.md", SKILLS_DIR / f"{name}.md"):
        if f.exists():
            return read_text(f)
    return None


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


class _AskHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):        # không in log HTTP (tránh ồn)
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass
        self.close_connection = True

    def do_POST(self):
        if self.path.rstrip("/") != "/ask":
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


def start_ask_server() -> None:
    """Mở HTTP server 127.0.0.1 để tool ask_user gọi vào bot."""
    global ASK_SERVER, ASK_URL, ASK_TOKEN, BOT_LOOP
    if ASK_SERVER is not None:
        return
    BOT_LOOP = asyncio.get_running_loop()
    ASK_TOKEN = secrets.token_urlsafe(24)
    ASK_SERVER = ThreadingHTTPServer(("127.0.0.1", 0), _AskHandler)
    ASK_SERVER.daemon_threads = True
    port = ASK_SERVER.server_address[1]
    threading.Thread(target=ASK_SERVER.serve_forever, daemon=True).start()
    ASK_URL = f"http://127.0.0.1:{port}/ask"
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
        _sh("git config --global credential.helper store", timeout=20)
        cred = Path.home() / ".git-credentials"
        lines = []
        if cred.exists():
            lines = [l for l in cred.read_text("utf-8").splitlines()
                     if l.strip() and "@github.com" not in l]
        safe = urllib.parse.quote(token, safe="")
        lines.append(f"https://x-access-token:{safe}@github.com")
        cred.write_text("\n".join(lines) + "\n", "utf-8")
        cred.chmod(0o600)
        if login:
            _sh(f'git config --global user.name {shlex.quote(login)}', timeout=20)
            _sh(f'git config --global user.email {shlex.quote(email)}', timeout=20)
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
    global GH_TOKEN_CACHE
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Token rỗng.")
    info = apply_github_config(token)
    GITHUB_TOKEN_FILE.write_text(token, "utf-8")
    GITHUB_TOKEN_FILE.chmod(0o600)
    GH_TOKEN_CACHE = token
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
            cred.write_text("\n".join(keep) + ("\n" if keep else ""), "utf-8")
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
        env["STV_SKIP_SETUP"] = "1"
        os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve())] + sys.argv[1:], env)
        return True
    except Exception as e:
        log.error("Không khởi động lại được: %s", e)
        return False


# ════════════════════════════════════════════════════════════════════
# 5. DỰNG PROMPT + CHẠY OPENCODE (ASYNC, KHÔNG CHẶN BOT)
# ════════════════════════════════════════════════════════════════════
def build_prompt(chat_id: int, user_text: str, skill: Optional[tuple] = None) -> str:
    user_text = user_text[:20000]
    head = ["## HỒ SƠ AGENT\n" + read_text(WORKSPACE / "SOUL.md").strip()
            + "\n\n" + read_text(WORKSPACE / "AGENTS.md").strip()]
    mem = "\n".join(memory_items())
    if mem:
        head.append("## TRÍ NHỚ DÀI HẠN (MEMORY.md)\n" + mem[-4000:])
    if skill:
        head.append(f"## SKILL ĐANG KÍCH HOẠT: {skill[0]}\n" + skill[1][:6000])
    head.append(f"## BỐI CẢNH\n- Bây giờ: {now():%d/%m/%Y %H:%M} ({TIMEZONE})\n- Thư mục làm việc: {WORKSPACE}")
    head_s = "\n\n".join(head)
    tail = f"## YÊU CẦU MỚI\n[Người dùng]: {user_text}\n\nHãy trả lời yêu cầu mới ở trên."

    budget = MAX_PROMPT_BYTES - len(head_s.encode()) - len(tail.encode()) - 200
    lines, used = [], 0
    for m in reversed(load_history(chat_id)[-MAX_HISTORY * 2:]):
        c = m["content"]
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


_TOOL_INFO = {
    "bash": ("⚙️", "Chạy lệnh"),
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
}


def _tool_entry(part: dict) -> Optional[dict]:
    """Đổi 1 sự kiện tool_use của OpenCode thành dòng tiến độ gọn cho Telegram."""
    tool = (part.get("tool") or "").lower()
    st = part.get("state") or {}
    inp = st.get("input") or {}
    icon, label = _TOOL_INFO.get(tool, ("🔧", tool or "Công cụ"))
    target, detail, lang = "", "", ""

    if tool == "bash":
        cmd = _clip(_redact(inp.get("command", "")), PROGRESS_DETAIL)
        out = _clip(_redact(st.get("output", "")), PROGRESS_DETAIL)
        detail = _clip(f"$ {cmd}" + (f"\n{out}" if out else ""))
        lang = "bash"
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
    return {"icon": icon, "label": label, "target": target, "detail": detail,
            "lang": lang, "ok": st.get("status") != "error", "call": part.get("callID")}


def _status_rows(chat_id: int, limit: int = PROGRESS_KEEP) -> list:
    rows = []
    for e in (ACTIVITY.get(chat_id) or [])[-limit:]:
        mark = "" if e.get("ok", True) else "⚠️ "
        line = f"{e['icon']} {mark}<b>{esc(e['label'])}</b>"
        if e.get("target"):
            line += f" <code>{esc(e['target'])}</code>"
        rows.append(line)
        if e.get("detail"):
            rows.append(f"<pre>{esc(e['detail'])}</pre>")
    return rows


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
    return f"{e['icon']} {e['label']}"


def _render_status(chat_id: int, started: float, frame: str = "🧠") -> str:
    secs = int(time.monotonic() - started)
    if not STATE.get("show_activity", False):
        # Chế độ gọn: chỉ 1 dòng, không lệnh / code / output để không chiếm chỗ.
        head = f"{frame} <i>Đang làm việc…</i> {secs}s"
        act = _last_action(chat_id)
        if act:
            head += f" · {esc(act)}"
        return head + " · /stop để huỷ"
    head = f"{frame} <i>Đang suy nghĩ…</i> {secs}s · /stop để huỷ"
    parts = [head]
    think = _thinking_tail(chat_id, 600)
    if think:
        parts += ["", "💭 <b>Suy nghĩ</b>", f"<blockquote>{esc(think)}</blockquote>"]
    rows = _status_rows(chat_id, limit=PROGRESS_KEEP if not think else 3)
    if rows:
        parts += ["", "✅ <b>Việc đã làm</b>"] + rows
    body = "\n".join(parts)
    return body if len(body) <= 3800 else body[:3790] + "\n…"


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
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
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
                    THINKING.setdefault(chat_id, []).append(txt)
                    THINKING_LAST[chat_id] = time.monotonic()
            elif etype == "step_finish":
                try:
                    rt = int(((part.get("tokens") or {}).get("reasoning")) or 0)
                except Exception:
                    rt = 0
                if rt:
                    THINK_TOKENS[chat_id] = THINK_TOKENS.get(chat_id, 0) + rt
            elif etype == "tool_use":
                entry = _tool_entry(part)
                if entry:
                    items = ACTIVITY.setdefault(chat_id, [])
                    call = entry.get("call")
                    if call:
                        for i, old in enumerate(items):          # cùng callID: cập nhật, không lặp
                            if old.get("call") == call:
                                items[i] = entry
                                break
                        else:
                            items.append(entry)
                    else:
                        items.append(entry)
                    del items[:-PROGRESS_KEEP * 3]
            elif etype == "error":
                err = part.get("error") or ev.get("error") or ""
                if isinstance(err, dict):
                    err = json.dumps(err, ensure_ascii=False)
                if err:
                    raw.append(str(err))

    async def watch_err():
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
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


async def run_agent(chat_id: int, prompt: str, retries: int = 1) -> tuple:
    """Trả về (ok, text).
    Lần 1: `--format json` + prompt qua stdin → đọc được từng tool call để hiện tiến độ.
    Lần 2 (nếu lần 1 trống): chế độ cũ (prompt qua tham số dòng lệnh)."""
    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)          # không để agent nhìn thấy token
    env.update(NO_COLOR="1", TERM="dumb", PWD=str(WORKSPACE), AISTV_CHAT_ID=str(chat_id))
    err_text = ""
    for attempt in range(retries + 1):
        via_stdin = attempt == 0
        cmd = [OPENCODE_BIN, "run", "--dir", str(WORKSPACE), "--model", STATE["model"],
               "--auto", "--thinking"]
        if STATE.get("variant"):
            cmd += ["--variant", STATE["variant"]]
        if via_stdin:
            cmd += ["--format", "json"]
        else:
            cmd.append(prompt)
        ACTIVITY[chat_id] = []
        THINKING[chat_id] = []
        THINK_TOKENS[chat_id] = 0
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(WORKSPACE), env=env, limit=2 ** 20,
            stdin=asyncio.subprocess.PIPE if via_stdin else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        RUNNING[chat_id] = proc
        err_lines: list = []
        try:
            coro = _talk(proc, prompt.encode("utf-8") if via_stdin else None, chat_id, err_lines)
            out = (await asyncio.wait_for(coro, timeout=AGENT_TIMEOUT)
                   if AGENT_TIMEOUT > 0 else await coro)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, f"⏱ Yêu cầu vượt quá {AGENT_TIMEOUT} giây nên đã bị dừng. Hãy chia nhỏ yêu cầu rồi thử lại."
        finally:
            RUNNING.pop(chat_id, None)
            _cancel_chat_asks(chat_id)
        if chat_id in CANCELLED:
            CANCELLED.discard(chat_id)
            return False, "🛑 Đã huỷ tác vụ."
        text = clean_output(out)
        if text:
            return True, text
        err_text = "\n".join(err_lines)
        log.warning("OpenCode không trả kết quả (lần %d, rc=%s): %s", attempt + 1, proc.returncode, err_text[-300:])
    return False, "⚠️ OpenCode không trả về phản hồi." + (f"\n\n{err_text[-1200:]}" if err_text else "")


_SKIP_DIRS = {"memory", "skills", "inbox", "node_modules", "__pycache__"}
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

    md = _FENCE.sub(fence, md)
    md = _TABLE.sub(lambda m: keep(f"<pre>{esc(m.group(0).strip())}</pre>"), md)
    md = _ICODE.sub(lambda m: keep(f"<code>{esc(m.group(1))}</code>"), md)
    md = _LINK.sub(link, md)              # cất link trước để _ và * trong URL không bị biến thành nghiêng/đậm
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
MENU_KB = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Trạng thái", callback_data="status"),
                                 InlineKeyboardButton("🧩 Skills", callback_data="skills"),
                                 InlineKeyboardButton("🧠 Trí nhớ", callback_data="memory")],
                                [InlineKeyboardButton("🧹 Chat mới", callback_data="new")]])


async def _ticker(bot, chat_id: int, status, started: float, stop: asyncio.Event) -> None:
    frames, i, last = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", 0, ""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        body = _render_status(chat_id, started, frames[i % len(frames)])
        if body != last:
            try:
                await status.edit_text(body, parse_mode=HTML, link_preview_options=NO_PREVIEW)
                last = body
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception:
                pass
        i += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
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
    ACTIVITY.pop(chat_id, None)


async def send_new_files(message, before: dict) -> None:
    after = snapshot()
    changed = [k for k, v in after.items() if before.get(k) != v and 0 < v[1] < 45 * 1024 * 1024]
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


async def respond(message, context, chat_id: int, text: str, skill: Optional[tuple] = None) -> bool:
    lock = LOCKS[chat_id]
    if lock.locked():
        await message.reply_text("⏳ Tôi đang xử lý yêu cầu trước — yêu cầu này đã được xếp hàng.")
    async with lock:
        async with SEM:
            status = await message.reply_text("🧠 <i>Đang làm việc…</i>", parse_mode=HTML)
            started = time.monotonic()
            prompt = build_prompt(chat_id, text, skill)
            before = snapshot()
            stop = asyncio.Event()
            ticker = asyncio.create_task(_ticker(context.bot, chat_id, status, started, stop))
            try:
                ok, answer = await run_agent(chat_id, prompt)
            finally:
                stop.set()
                await ticker
            await _finish_status(status, chat_id, started, ok)
            if ok:
                append_history(chat_id, "user", text)
                append_history(chat_id, "assistant", answer[:6000])
                log_daily(text, answer)
                if STATE.get("show_thinking", True):
                    await send_thinking(message, chat_id)
            think_tok = THINK_TOKENS.get(chat_id, 0)
            foot = f"⏱ {time.monotonic() - started:.1f}s · {esc(STATE['model'].split('/')[-1])}"
            if think_tok:
                foot += f" · 🧠 {think_tok} tok"
            footer = f"<i>{foot}</i>"
            await send_rich(message, answer, footer if ok else "", ANSWER_KB if ok else None)
            if ok:
                await send_new_files(message, before)
            THINKING.pop(chat_id, None)
            THINK_TOKENS.pop(chat_id, None)
            return ok


# ════════════════════════════════════════════════════════════════════
# 8. LỆNH & TRÌNH XỬ LÝ TELEGRAM
# ════════════════════════════════════════════════════════════════════
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
        f"• Giới hạn 1 yêu cầu: {to}\n"
        f"• Hội thoại: {len(load_history(chat_id)) // 2} lượt đã lưu\n"
        f"• Trí nhớ dài hạn: {len(memory_items())} mục\n"
        f"• Skills: {len(list_skills())}\n"
        f"• File trong workspace: {len(snapshot())}\n"
        f"• Tác vụ: {'🟢 đang chạy' if chat_id in RUNNING else '⚪ rảnh'}\n"
        f"• Hoạt động: {up // 3600}h {up % 3600 // 60}m"
    )


def build_skills() -> str:
    sk = list_skills()
    if not sk:
        return "🧩 Chưa có skill nào. Tạo file <code>skills/&lt;tên&gt;/SKILL.md</code> trong workspace."
    rows = "\n".join(f"• <code>{esc(n)}</code> — {esc(d)}" for n, d in sk)
    return f"🧩 <b>Skills</b>\n{rows}\n\nDùng: <code>/skill &lt;tên&gt; &lt;yêu cầu&gt;</code>"


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
        "• Trí nhớ dài hạn — /remember, /memory\n"
        "• Đọc file bạn gửi, tạo file và tự gửi lại cho bạn\n"
        "• <b>Không giới hạn 10 phút</b> — dự án lớn chạy tới khi xong (/stop để huỷ)\n"
        "• Kết nối GitHub 1 lần — /github login; tự cập nhật — /update\n\n"
        "Gửi câu hỏi hoặc yêu cầu để bắt đầu 👇"
    )


HELP_TEXT = (
    "💡 <b>Hướng dẫn</b>\n"
    "Nhắn trực tiếp yêu cầu (hỏi đáp, viết/sửa code, phân tích, tạo file…).\n\n"
    "<b>Hội thoại</b>\n/new — cuộc trò chuyện mới\n/stop — huỷ tác vụ đang chạy\n/status — trạng thái\n\n"
    "<b>Trí nhớ &amp; Skills</b>\n/remember &lt;nội dung&gt; — ghi nhớ dài hạn\n/memory — xem trí nhớ\n"
    "/forget &lt;số|all&gt; — xoá trí nhớ\n/skills — danh sách skills\n/skill &lt;tên&gt; &lt;yêu cầu&gt; — chạy theo skill\n\n"
    "<b>File</b>\nGửi file cho bot → lưu vào <code>inbox/</code> để agent đọc\n/files — file trong workspace\n/get &lt;đường dẫn&gt; — tải file về\n\n"
    "<b>Suy nghĩ &amp; hỏi đáp</b>\n/think on|off — hiện/tắt phần suy nghĩ của model\n"
    "/activity on|off — hiện/tắt chi tiết lệnh &amp; sửa code khi đang chạy (mặc định tắt)\n"
    "/variant [high|max|off] — mức reasoning của model\n"
    "Agent tự dùng nút bấm khi cần bạn chọn/xác nhận.\n\n"
    "<b>GitHub &amp; tự cập nhật (chủ bot)</b>\n/github login — kết nối GitHub bằng mã, lưu lâu dài\n"
    "/github token &lt;PAT&gt; · /github status · /github repo · /github logout\n"
    "/update — pull bản mới trên GitHub rồi khởi động lại\n/restart — khởi động lại bot\n\n"
    "<b>Hệ thống (chủ bot)</b>\n/model [provider/tên] — xem/đổi model\n/models — danh sách model\n/allow &lt;id&gt; · /deny &lt;id&gt; — cấp/thu hồi quyền"
)


@guard()
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(welcome_text(), parse_mode=HTML, reply_markup=MENU_KB)


@guard()
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=HTML)


@guard()
async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    archive_history(update.effective_chat.id)
    await update.effective_message.reply_text("🧹 <b>Đã bắt đầu cuộc trò chuyện mới.</b> Trí nhớ dài hạn vẫn được giữ.", parse_mode=HTML)


@guard()
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    proc = RUNNING.get(chat_id)
    if proc and proc.returncode is None:
        CANCELLED.add(chat_id)
        proc.kill()
        await update.effective_message.reply_text("🛑 Đang huỷ tác vụ…")
    else:
        await update.effective_message.reply_text("Hiện không có tác vụ nào đang chạy.")


@guard()
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(build_status(update.effective_chat.id), parse_mode=HTML)


@guard()
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
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
    lines = [l.strip() for l in clean_output(out.decode("utf-8", "replace")).splitlines() if "/" in l]
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
    await msg.reply_text(
        f"💭 Hiển thị suy nghĩ (reasoning): <b>{'BẬT' if on else 'TẮT'}</b>\n"
        "Model có reasoning sẽ hiện phần này khi đang chạy và gửi kèm sau khi xong.",
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
        + ("Đang bật: tin nhắn tiến độ hiện từng lệnh/sửa file và giữ lại khi xong."
           if on else
           "Đang tắt: chỉ 1 dòng trạng thái ngắn và tự xoá khi xong, không chiếm chỗ."),
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
            "✅ <b>Đã kết nối GitHub</b>\n"
            f"• Tài khoản: <b>{esc(login)}</b>\n"
            "• Đã cấu hình <code>git</code> + <code>gh</code>\n"
            f"• Lưu tại: <code>{esc(GITHUB_TOKEN_FILE)}</code>\n\n"
            "Lần sau (kể cả Colab khác) bot tự dùng lại. Để chắc chắn 100%, thêm secret "
            "<code>GITHUB_TOKEN</code> trong Colab Secrets hoặc bật Google Drive.",
            parse_mode=HTML)
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
        return

    if sub == "repo":
        rd = repo_dir()
        if not rd:
            await msg.reply_text("⚠️ Không tìm thấy thư mục repo (.git).")
            return
        _, remote = _git(["remote", "-v"], rd)
        _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], rd)
        _, head = _git(["log", "-1", "--oneline"], rd)
        await msg.reply_text(
            f"📦 <b>Repo bot</b>\n• Thư mục: <code>{esc(rd)}</code>\n"
            f"• Nhánh: <code>{esc(branch)}</code>\n• Commit: <code>{esc(head)}</code>\n"
            f"<pre>{esc(remote[:1200])}</pre>",
            parse_mode=HTML)
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
    rd = repo_dir()
    if rd:
        _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], rd)
        _, head = _git(["log", "-1", "--oneline"], rd)
        lines.append(f"• Repo: <code>{esc(rd)}</code> · {esc(branch)} · {esc(head[:80])}")
    lines += ["", "<b>Lệnh</b>",
              "/github login — kết nối bằng mã (khuyến nghị)",
              "/github token &lt;PAT&gt; — dán token có sẵn",
              "/github repo — xem repo/nhánh/commit",
              "/github logout — ngắt kết nối",
              "/update — pull bản mới + khởi động lại"]
    await msg.reply_text("\n".join(lines), parse_mode=HTML)


@guard(owner_only=True)
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rd = repo_dir()
    if not rd:
        await msg.reply_text("⚠️ Không tìm thấy repo (.git) để cập nhật.")
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
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🔄 Đang khởi động lại bot…")
    await asyncio.sleep(0.5)
    if not restart_bot():
        await update.effective_message.reply_text(
            "ℹ️ Không thể tự khởi động lại trong notebook Colab. Hãy dừng ô và chạy lại lệnh run.")


@guard()
async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = oneline(" ".join(context.args), 500)
    if not text:
        await update.effective_message.reply_text("Dùng: /remember <điều cần nhớ>")
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


@guard()
async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(build_skills(), parse_mode=HTML)


@guard()
async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if len(context.args) < 2:
        await msg.reply_text("Dùng: /skill <tên> <yêu cầu>  (xem /skills)")
        return
    name, task = context.args[0], " ".join(context.args[1:])
    body = find_skill(name)
    if body is None:
        await msg.reply_text(f"⚠️ Không tìm thấy skill “{name}”. Xem /skills.")
        return
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


@guard()
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    text = (msg.text or "").strip()
    if not text:
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
    if chat.type != "private":                       # trong nhóm: chỉ trả lời khi được nhắc tên / reply
        uname = "@" + (context.bot.username or "")
        replied = bool(msg.reply_to_message and msg.reply_to_message.from_user
                       and msg.reply_to_message.from_user.id == context.bot.id)
        if uname.lower() not in text.lower() and not replied:
            return
        text = re.sub(re.escape(uname), "", text, flags=re.I).strip()
    await respond(msg, context, chat.id, text)


@guard()
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if update.effective_chat.type != "private" or not msg.document:
        return
    doc = msg.document
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await msg.reply_text("⚠️ File quá lớn (giới hạn 20MB của Telegram Bot API).")
        return
    name = re.sub(r"[^\w.\- ]", "_", doc.file_name or f"file_{doc.file_unique_id}")
    dest = INBOX / f"{int(time.time())}_{name}"
    await (await doc.get_file()).download_to_drive(dest)
    caption = (msg.caption or "").strip() or "Hãy đọc file này và tóm tắt nội dung chính."
    await respond(msg, context, update.effective_chat.id,
                  f"{caption}\n\n(Người dùng vừa gửi file, đã lưu tại: inbox/{dest.name})")


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


@guard()
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat_id, data = q.message.chat_id, q.data
    if data.startswith("ask:"):
        await _on_ask_button(q, data)
        return
    await q.answer()
    if data == "status":
        await q.message.reply_text(build_status(chat_id), parse_mode=HTML)
    elif data == "skills":
        await q.message.reply_text(build_skills(), parse_mode=HTML)
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
# 9. KHỞI CHẠY
# ════════════════════════════════════════════════════════════════════
COMMANDS = [
    ("start", "Giới thiệu & menu"), ("new", "Cuộc trò chuyện mới"), ("stop", "Huỷ tác vụ đang chạy"),
    ("status", "Trạng thái bot"), ("model", "Xem / đổi model"), ("models", "Danh sách model"),
    ("remember", "Ghi nhớ dài hạn"), ("memory", "Xem trí nhớ"), ("forget", "Xoá trí nhớ"),
    ("skills", "Danh sách skills"), ("skill", "Chạy theo skill"),
    ("think", "Bật/tắt hiện suy nghĩ"), ("activity", "Ẩn/hiện chi tiết việc đang làm"),
    ("variant", "Mức reasoning của model"),
    ("github", "Kết nối / quản lý GitHub"), ("update", "Cập nhật bot từ GitHub"),
    ("restart", "Khởi động lại bot"),
    ("files", "File trong workspace"), ("get", "Tải file về"), ("help", "Hướng dẫn"),
]


def get_token() -> str:
    tok = get_secret("TELEGRAM_BOT_TOKEN")
    if not tok:
        tok = getpass.getpass("🔑 Dán Telegram Bot Token (lấy từ @BotFather): ").strip()
    if not tok:
        raise SystemExit("❌ Thiếu TELEGRAM_BOT_TOKEN.")
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
    print(f"✅ Bot online: @{me.username}  |  model: {STATE['model']}")
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
        OPENCODE_VERSION = _sh(f'"{OPENCODE_BIN}" --version', timeout=20).stdout.strip().splitlines()[-1]
    except Exception:
        pass

    app = (ApplicationBuilder().token(BOT_TOKEN).post_init(post_init)
           .concurrent_updates(True)          # để /stop hoạt động khi đang xử lý
           .build())
    for names, fn in [(["start"], cmd_start), (["help"], cmd_help), (["new", "reset", "clear"], cmd_new),
                      (["stop"], cmd_stop), (["status"], cmd_status), (["model"], cmd_model),
                      (["models"], cmd_models), (["remember"], cmd_remember), (["memory"], cmd_memory),
                      (["forget"], cmd_forget), (["skills"], cmd_skills), (["skill"], cmd_skill),
                      (["think"], cmd_think), (["activity", "progress"], cmd_activity),
                      (["variant"], cmd_variant),
                      (["github"], cmd_github), (["update"], cmd_update), (["restart"], cmd_restart),
                      (["files"], cmd_files), (["get"], cmd_get), (["allow"], cmd_allow), (["deny"], cmd_deny)]:
        app.add_handler(CommandHandler(names, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.UpdateType.MESSAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, handle_text))
    app.add_error_handler(on_error)

    print("🚀 Đang khởi chạy AI STV Agent… (dừng bằng nút ■ của ô Colab)")
    try:
        app.run_polling(drop_pending_updates=True, stop_signals=None, close_loop=False)
    except KeyboardInterrupt:
        print("🛑 Bot đã dừng.")


if __name__ == "__main__":
    main()
