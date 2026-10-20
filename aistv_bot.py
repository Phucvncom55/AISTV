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
import os, sys, re, json, time, html, shutil, asyncio, getpass, logging, subprocess, functools
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

CLEAN_INSTALL = os.getenv("AISTV_CLEAN_INSTALL", "1") != "0"   # 0 = giữ bản OpenCode đã cài, không xoá & cài lại
USE_GOOGLE_DRIVE = False        # True = lưu trí nhớ/lịch sử vào Google Drive (sống sót khi Colab reset)
FULL_ACCESS = False             # True = agent được đọc/ghi NGOÀI workspace và không bị chặn quyền
                                #        (mặc định `opencode run` tự từ chối mọi thao tác cần hỏi quyền)
DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"   # đổi nhanh bằng /model hoặc biến OPENCODE_MODEL
TIMEZONE = "Asia/Ho_Chi_Minh"
MAX_HISTORY = 12                # số lượt hỏi-đáp đưa vào ngữ cảnh
MAX_PARALLEL = 2                # số tiến trình OpenCode chạy cùng lúc
AGENT_TIMEOUT = 600             # giây tối đa cho 1 yêu cầu
MAX_PROMPT_BYTES = 110_000      # giới hạn an toàn cho 1 tham số dòng lệnh Linux (128KB)
SPLIT_LIMIT = 3000              # ký tự tối đa mỗi tin nhắn Telegram (trước khi đổi sang HTML)


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
STATE_FILE = HOME / "state.json"
for _d in (WORKSPACE, MEMORY_DIR, SKILLS_DIR, INBOX, SESSIONS, ARCHIVE):
    _d.mkdir(parents=True, exist_ok=True)

START_TIME = time.time()
BOT_TOKEN = ""
OPENCODE_BIN = ""
OPENCODE_VERSION = "?"
RUNNING: dict = {}                 # chat_id -> tiến trình OpenCode đang chạy
CANCELLED: set = set()
LOCKS = defaultdict(asyncio.Lock)  # mỗi chat xử lý tuần tự
SEM = asyncio.Semaphore(MAX_PARALLEL)

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
6. Tuyệt đối không in ra hay gửi đi token, API key, mật khẩu hoặc biến môi trường.
7. `MEMORY.md` chứa thông tin lâu dài về người dùng — dùng khi liên quan, đừng lặp lại vô cớ.
8. Khi người dùng bảo "hãy nhớ…" hoặc nêu một sở thích/quy tắc lâu dài, hãy thêm MỘT dòng mới bắt đầu bằng `- ` vào cuối
   `MEMORY.md` (ví dụ `- [20/10/2026] Thích trả lời ngắn gọn`). Không xoá hay sửa các dòng cũ trừ khi được yêu cầu.
9. `memory/YYYY-MM-DD.md` là nhật ký theo ngày — chỉ mở khi người dùng hỏi về những gì đã làm trước đây.
10. `skills/` chứa quy trình chuyên biệt — làm đúng theo skill khi được kích hoạt.
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


def bootstrap_workspace() -> None:
    files = {
        WORKSPACE / "SOUL.md": SOUL_MD,
        WORKSPACE / "AGENTS.md": AGENTS_MD,
        WORKSPACE / "MEMORY.md": MEMORY_HEADER,
        SKILLS_DIR / "code-review" / "SKILL.md": SKILL_CODE_REVIEW,
        SKILLS_DIR / "nghien-cuu" / "SKILL.md": SKILL_RESEARCH,
    }
    for path, content in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, "utf-8")
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


def clean_output(s: str) -> str:
    s = _ANSI.sub("", s or "").replace("\r", "").strip()
    s = _HEADER.sub("", s).strip()
    return s.replace(BOT_TOKEN, "***") if BOT_TOKEN else s


PROGRESS: dict = {}                # chat_id -> dòng hoạt động mới nhất của agent (đọc từ stderr)


async def _talk(proc, data: Optional[bytes], chat_id: int, err_lines: list) -> bytes:
    """Gửi prompt qua stdin, đọc stdout trọn vẹn, đọc stderr từng dòng để hiện tiến độ."""
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
                    PROGRESS[chat_id] = oneline(t, 60)
        except Exception:
            pass

    out, _, _ = await asyncio.gather(proc.stdout.read(), feed(), watch_err())
    await proc.wait()
    return out


async def run_agent(chat_id: int, prompt: str, retries: int = 1) -> tuple:
    """Trả về (ok, text).
    Lần 1: đưa prompt qua stdin (không dính giới hạn độ dài tham số, không bị CLI bọc thêm dấu ngoặc kép).
    Lần 2 (nếu lần 1 trống): đưa prompt qua tham số dòng lệnh như cách cũ."""
    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)          # không để agent nhìn thấy token
    env.update(NO_COLOR="1", TERM="dumb")
    err_text = ""
    for attempt in range(retries + 1):
        via_stdin = attempt == 0
        cmd = [OPENCODE_BIN, "run", "--model", STATE["model"]] + ([] if via_stdin else [prompt])
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(WORKSPACE), env=env, limit=2 ** 20,
            stdin=asyncio.subprocess.PIPE if via_stdin else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        RUNNING[chat_id] = proc
        err_lines: list = []
        try:
            out = await asyncio.wait_for(
                _talk(proc, prompt.encode("utf-8") if via_stdin else None, chat_id, err_lines),
                timeout=AGENT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, f"⏱ Yêu cầu vượt quá {AGENT_TIMEOUT // 60} phút nên đã bị dừng. Hãy chia nhỏ yêu cầu rồi thử lại."
        finally:
            RUNNING.pop(chat_id, None)
            PROGRESS.pop(chat_id, None)
        if chat_id in CANCELLED:
            CANCELLED.discard(chat_id)
            return False, "🛑 Đã huỷ tác vụ."
        text = clean_output(out.decode("utf-8", "replace"))
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
        dirs[:] = [d for d in dirs if not d.startswith(".") and not (rel_root == Path(".") and d in _SKIP_DIRS)]
        for fn in files:
            rel = (rel_root / fn).as_posix()
            if fn.startswith(".") or rel in _SYSTEM_FILES:
                continue
            try:
                st = (Path(root) / fn).stat()
            except OSError:
                continue
            snap[rel] = (st.st_mtime_ns, st.st_size)
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
    frames, i = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", 0
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
            break
        except asyncio.TimeoutError:
            pass
        i += 1
        if i % 2 == 0:
            act = PROGRESS.get(chat_id)
            line2 = f"\n<code>{esc(act)}</code>" if act else ""
            try:
                await status.edit_text(
                    f"{frames[(i // 2) % len(frames)]} <i>Đang xử lý… {int(time.monotonic() - started)}s</i>  ·  /stop để huỷ{line2}",
                    parse_mode=HTML)
            except Exception:
                pass


async def send_new_files(message, before: dict) -> None:
    after = snapshot()
    changed = [k for k, v in after.items() if before.get(k) != v and v[1] > 0 and v[1] < 45 * 1024 * 1024]
    for rel in changed[:5]:
        try:
            with (WORKSPACE / rel).open("rb") as fh:
                await message.reply_document(fh, filename=Path(rel).name, caption=f"📎 {rel}")
        except Exception as e:
            log.warning("Không gửi được %s: %s", rel, e)
    if len(changed) > 5:
        await message.reply_text(f"📂 Còn {len(changed) - 5} file khác — dùng /files và /get <tên> để tải.")


async def respond(message, context, chat_id: int, text: str, skill: Optional[tuple] = None) -> bool:
    lock = LOCKS[chat_id]
    if lock.locked():
        await message.reply_text("⏳ Tôi đang xử lý yêu cầu trước — yêu cầu này đã được xếp hàng.")
    async with lock:
        async with SEM:
            status = await message.reply_text("🧠 <i>Đang suy nghĩ…</i>", parse_mode=HTML)
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
            try:
                await status.delete()
            except Exception:
                pass
            if ok:
                append_history(chat_id, "user", text)
                append_history(chat_id, "assistant", answer[:6000])
                log_daily(text, answer)
            footer = f"<i>⏱ {time.monotonic() - started:.1f}s · {esc(STATE['model'].split('/')[-1])}</i>"
            await send_rich(message, answer, footer if ok else "", ANSWER_KB if ok else None)
            if ok:
                await send_new_files(message, before)
            return ok


# ════════════════════════════════════════════════════════════════════
# 8. LỆNH & TRÌNH XỬ LÝ TELEGRAM
# ════════════════════════════════════════════════════════════════════
def build_status(chat_id: int) -> str:
    up = int(time.time() - START_TIME)
    return (
        "📊 <b>Trạng thái AI STV</b>\n"
        f"• Model: <code>{esc(STATE['model'])}</code>\n"
        f"• OpenCode: <code>{esc(OPENCODE_VERSION)}</code>\n"
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
        "• Nhớ hội thoại bền vững, kể cả khi bot khởi động lại\n"
        "• Trí nhớ dài hạn — /remember, /memory\n"
        "• Đọc file bạn gửi, tạo file và tự gửi lại cho bạn\n"
        "• Skills tuỳ chỉnh — /skills\n"
        "• Chạy nền, huỷ bất cứ lúc nào bằng /stop\n\n"
        "Gửi câu hỏi hoặc yêu cầu để bắt đầu 👇"
    )


HELP_TEXT = (
    "💡 <b>Hướng dẫn</b>\n"
    "Nhắn trực tiếp yêu cầu (hỏi đáp, viết/sửa code, phân tích, tạo file…).\n\n"
    "<b>Hội thoại</b>\n/new — cuộc trò chuyện mới\n/stop — huỷ tác vụ đang chạy\n/status — trạng thái\n\n"
    "<b>Trí nhớ &amp; Skills</b>\n/remember &lt;nội dung&gt; — ghi nhớ dài hạn\n/memory — xem trí nhớ\n"
    "/forget &lt;số|all&gt; — xoá trí nhớ\n/skills — danh sách skills\n/skill &lt;tên&gt; &lt;yêu cầu&gt; — chạy theo skill\n\n"
    "<b>File</b>\nGửi file cho bot → lưu vào <code>inbox/</code> để agent đọc\n/files — file trong workspace\n/get &lt;đường dẫn&gt; — tải file về\n\n"
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


@guard()
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id, data = q.message.chat_id, q.data
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
    ("files", "File trong workspace"), ("get", "Tải file về"), ("help", "Hướng dẫn"),
]


def get_token() -> str:
    tok = get_secret("TELEGRAM_BOT_TOKEN")
    if not tok:
        tok = getpass.getpass("🔑 Dán Telegram Bot Token (lấy từ @BotFather): ").strip()
    if not tok:
        raise SystemExit("❌ Thiếu TELEGRAM_BOT_TOKEN.")
    return tok


async def post_init(app) -> None:
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    me = await app.bot.get_me()
    print(f"✅ Bot online: @{me.username}  |  model: {STATE['model']}")
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
