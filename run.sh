#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  AI STV — chạy bot Telegram bằng MỘT lệnh
#
#  Trong repo đã clone:
#      bash run.sh
#
#  Không cần clone trước (Linux / macOS / Colab):
#      bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/run.sh)
#      bash <(curl -fsSL .../run.sh) https://github.com/<user>/<repo>
#
#  Biến môi trường tuỳ chọn:
#      TELEGRAM_BOT_TOKEN=123:abc   token bot (hoặc .env / Colab Secrets)
#      ALLOWED_USER_IDS=123,456     chỉ những user này được dùng bot
#      AISTV_REPO=...               URL repo khác
#      AISTV_DIR=~/AISTV            thư mục clone
#      AISTV_BRANCH=main            nhánh
#      AISTV_VENV=0                 không dùng venv
#      AISTV_CLEAN_INSTALL=1        xoá & cài lại OpenCode (mặc định 0)
#      STV_HOME=...                 nơi lưu workspace/sessions
# ════════════════════════════════════════════════════════════════════
set -euo pipefail
export GIT_TERMINAL_PROMPT=0        # không treo ở prompt đăng nhập git
START_TS=$SECONDS
trap 'printf "\033[1;31m✖ Dừng: bước ngay trên báo lỗi (không treo, không chờ vô hạn).\033[0m\n" >&2' ERR

REPO="${AISTV_REPO:-https://github.com/Phucvncom55/AISTV.git}"
BRANCH="${AISTV_BRANCH:-main}"

# Cho phép truyền repo trực tiếp: bash run.sh https://github.com/<user>/<repo>
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  REPO="$1"
fi
REPO="${REPO%/}"
if [[ "$REPO" != *://* && "$REPO" != git@* && "$REPO" != /* && "$REPO" == */* ]]; then
  REPO="https://github.com/${REPO}"                       # dạng tắt: user/repo
fi
[[ "$REPO" == http* && "$REPO" != *.git ]] && REPO="${REPO}.git"

APP_DIR="${AISTV_DIR:-$HOME/AISTV}"
PY="${PYTHON:-python3}"

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

command -v "$PY" >/dev/null 2>&1 || fail "Không tìm thấy python3. Cài Python 3.10+ rồi chạy lại."

# ── 1. Xác định mã nguồn: chạy tại chỗ hay clone từ GitHub ────────────
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/aistv_bot.py" ]]; then
  APP_DIR="$SCRIPT_DIR"
  say "Dùng mã nguồn tại $APP_DIR"
else
  command -v git  >/dev/null 2>&1 || fail "Cần git để tải repo. Cài git rồi chạy lại."
  command -v curl >/dev/null 2>&1 || fail "Cần curl để tải repo. Cài curl rồi chạy lại."
  if [[ -d "$APP_DIR/.git" ]]; then
    say "Cập nhật mã nguồn trong $APP_DIR"
    git -C "$APP_DIR" pull --ff-only || say "Không cập nhật được (bỏ qua), dùng bản hiện có."
  else
    say "Tải mã nguồn từ $REPO"
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR" \
      || fail "Không clone được $REPO — kiểm tra URL repo trong run.sh / AISTV_REPO."
  fi
  [[ -f "$APP_DIR/aistv_bot.py" ]] || fail "Repo thiếu aistv_bot.py."
fi

cd "$APP_DIR"

# ── 2. Bí mật: env → .env của repo → ~/.config/aistv/config.env ──────
# Ưu tiên: biến môi trường > .env trong repo > config.env dùng chung.
# config.env giúp token/key không mất khi clone lại repo hoặc đổi AISTV_DIR,
# nên các lần chạy sau không phải nhập tay lần nào nữa.
CONFIG_DIR="${AISTV_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/aistv}"
# Colab có Google Drive đã mount → để token/key sống qua các phiên.
if [[ -z "${AISTV_CONFIG_DIR:-}" && -d /content/drive/MyDrive ]]; then
  CONFIG_DIR="/content/drive/MyDrive/aistv"
fi
CONFIG_FILE="$CONFIG_DIR/config.env"
ENV_FILE="$APP_DIR/.env"

_ENV_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
_ENV_IDS="${ALLOWED_USER_IDS:-}"
_ENV_GEMINI="${GEMINI_API_KEY:-}"

_load_env_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  . "$f" 2>/dev/null || true
  set +a
}

# ── 2a. Nạp cấu hình từ xa: MỘT implementation dùng chung ─────────────
# aistv_config.py giống hệt run.bat / run.ps1 / aistv_bot.py:
#   AISTV_ENV_URL → repo private AISTV_CONFIG_REPO
#   (AISTV_CONFIG_TOKEN / GH_TOKEN / GITHUB_TOKEN / gh auth token / Colab Secrets).
# Nhờ vậy token đã có trên GitHub thì không hỏi lại ở bất kỳ môi trường nào.
export AISTV_CONFIG_DIR="$CONFIG_DIR"
if [[ -f "$APP_DIR/aistv_config.py" ]]; then
  "$PY" "$APP_DIR/aistv_config.py" sync || true
  export AISTV_CONFIG_SYNCED=1
fi

_load_env_file "$CONFIG_FILE"
_load_env_file "$ENV_FILE"

[[ -n "$_ENV_TOKEN" ]] && TELEGRAM_BOT_TOKEN="$_ENV_TOKEN" && export TELEGRAM_BOT_TOKEN
[[ -n "$_ENV_IDS" ]]   && ALLOWED_USER_IDS="$_ENV_IDS"     && export ALLOWED_USER_IDS
[[ -n "$_ENV_GEMINI" ]] && GEMINI_API_KEY="$_ENV_GEMINI"   && export GEMINI_API_KEY
unset _ENV_TOKEN _ENV_IDS _ENV_GEMINI

# Ghi bí mật vào .env của repo VÀ config.env dùng chung (quyền 600), không in ra.
persist_secret() {
  local name="$1" value="$2" f
  for f in "$ENV_FILE" "$CONFIG_FILE"; do
    AISTV_SECRET="$value" AISTV_NAME="$name" "$PY" - "$f" <<'PY' 2>/dev/null || true
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
name, value = os.environ["AISTV_NAME"], os.environ["AISTV_SECRET"]
path.parent.mkdir(parents=True, exist_ok=True)
lines = path.read_text("utf-8", "replace").splitlines() if path.is_file() else []
out, done = [], False
for line in lines:
    s = line.strip()
    if s.startswith("export "):
        s = s[7:].lstrip()
    if s.startswith(name + "="):
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
PY
  done
}

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${ALLOWED_USER_IDS:-}" || -z "${GEMINI_API_KEY:-}" ]]; then
  _sec() { "$PY" -c "from google.colab import userdata; print(userdata.get('$1') or '', end='')" 2>/dev/null || true; }
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    _tok="$(_sec TELEGRAM_BOT_TOKEN)"
    if [[ -n "$_tok" ]]; then
      TELEGRAM_BOT_TOKEN="$_tok"
      export TELEGRAM_BOT_TOKEN
      say "Đã lấy TELEGRAM_BOT_TOKEN từ Colab Secrets."
    fi
  fi
  if [[ -z "${ALLOWED_USER_IDS:-}" ]]; then
    _ids="$(_sec ALLOWED_USER_IDS)"
    if [[ -n "$_ids" ]]; then
      ALLOWED_USER_IDS="$_ids"
      export ALLOWED_USER_IDS
      say "Đã lấy ALLOWED_USER_IDS từ Colab Secrets."
    fi
  fi
  if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    _gk="$(_sec GEMINI_API_KEY)"
    if [[ -n "$_gk" ]]; then
      GEMINI_API_KEY="$_gk"
      export GEMINI_API_KEY
      say "Đã lấy GEMINI_API_KEY từ Colab Secrets."
    fi
  fi
fi

# Hỏi token một lần, có giới hạn thời gian để không bao giờ treo ở prompt.
ask_token() {
  [[ -t 0 ]] || return 1
  cat <<'EOF'
🔑 Chưa có Telegram Bot Token.
   1) Mở https://t.me/BotFather → gõ /newbot → đặt tên cho bot
   2) Copy token dạng 123456789:AAH... rồi dán vào đây
EOF
  local line=""
  printf '   Token (Enter để bỏ qua): '
  if ! IFS= read -r -t "${AISTV_PROMPT_TIMEOUT:-180}" line; then
    printf '\n⏱ Hết thời gian chờ nhập token (%ss).\n' "${AISTV_PROMPT_TIMEOUT:-180}"
    return 1
  fi
  line="${line//[[:space:]]/}"
  [[ -n "$line" ]] || return 1
  TELEGRAM_BOT_TOKEN="$line"
  export TELEGRAM_BOT_TOKEN
  persist_secret TELEGRAM_BOT_TOKEN "$line"
  say "Đã lưu token vào $ENV_FILE và $CONFIG_FILE — lần sau không cần nhập lại."
}

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  ask_token || true
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  cat <<EOF >&2

✖ Chưa có Telegram Bot Token.
  Đã thử: biến môi trường, .env, $CONFIG_FILE, GitHub/URL.
  • Nhanh nhất: mở https://t.me/BotFather → /newbot → copy token, rồi chạy lại:
        TELEGRAM_BOT_TOKEN=123456:ABC... bash run.sh
    Token được lưu vào $CONFIG_FILE cho các lần sau, không phải nhập lại.
  • Máy đã đăng nhập gh: runner tự lấy token từ repo AISTV-secrets.
  • Chưa có gh: đặt AISTV_CONFIG_TOKEN (PAT đọc repo AISTV-secrets) hoặc thêm
    TELEGRAM_BOT_TOKEN vào 🔑 Colab Secrets (bật Notebook access).
  • Kiểm tra nguồn: python aistv_config.py doctor
  • Muốn bỏ bước chờ xác nhận chủ bot: AISTV_PAIR=0 bash run.sh

EOF
  exit 1
fi

# ── 2b. Gemini = mắt + tai cho ảnh/video (tuỳ chọn, KHÔNG bắt buộc) ──
# Mặc định không hỏi: thiếu key thì bot vẫn chạy, chỉ mất phần đọc ảnh.
# Muốn nhập ngay trong terminal: AISTV_ASK_GEMINI=1 bash run.sh
# Cách gọn hơn: nhắn /key gemini <key> cho bot, hoặc thêm vào config.env.
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  say "Chưa có GEMINI_API_KEY — bỏ qua phần đọc ảnh (không hỏi, không chờ)."
  say "  Thêm sau bằng: /key gemini <key> trong chat, hoặc:"
  say "  echo 'GEMINI_API_KEY=<key>' >> $CONFIG_FILE"
fi

if [[ -z "${GEMINI_API_KEY:-}" && "${AISTV_ASK_GEMINI:-0}" == "1" && -t 0 ]]; then
  printf '🧠 Gemini API key (Enter để bỏ qua — lấy tại https://aistudio.google.com/apikey): '
  _gk=""
  if IFS= read -r -t "${AISTV_PROMPT_TIMEOUT:-180}" _gk && [[ -n "${_gk// /}" ]]; then
    GEMINI_API_KEY="${_gk//[[:space:]]/}"
    export GEMINI_API_KEY
    persist_secret GEMINI_API_KEY "$GEMINI_API_KEY"
    say "Đã lưu GEMINI_API_KEY — bot xem được video và đọc được ảnh."
  fi
  unset _gk
fi

# ── 2c. Xác nhận chủ bot: in link → chờ bạn bấm Start → lưu user id ──
# Giống device flow của GitHub: bạn không phải chép id thủ công, script chờ
# tối đa AISTV_PAIR_TIMEOUT giây rồi tự chạy tiếp (không treo vô hạn).
# Chỉ chờ khi có terminal (Colab/DataCamp không nhập được → bỏ qua luôn).
# Ép chờ ở môi trường không có TTY: AISTV_PAIR=1
_pair_wait=0
if [[ -t 0 || "${AISTV_PAIR:-}" == "1" ]]; then
  _pair_wait=1
fi

if [[ -z "${ALLOWED_USER_IDS:-}" && "$_pair_wait" == "1" \
      && "${AISTV_PAIR:-1}" != "0" && -f "$APP_DIR/aistv_pair.py" ]]; then
  say "Xác nhận chủ bot qua Telegram (tối đa ${AISTV_PAIR_TIMEOUT:-180}s, Ctrl+C để bỏ qua)…"
  if "$PY" "$APP_DIR/aistv_pair.py" --timeout "${AISTV_PAIR_TIMEOUT:-180}"; then
    _load_env_file "$CONFIG_FILE"
    _load_env_file "$ENV_FILE"
    [[ -n "${ALLOWED_USER_IDS:-}" ]] && export ALLOWED_USER_IDS
  else
    say "Chưa xác nhận — bot vẫn chạy, người nhắn đầu tiên sẽ thành chủ bot."
  fi
fi
unset _pair_wait

# ── 2d. Bí mật đến từ biến môi trường → lưu lại cho lần chạy sau ────
_have_secret() {
  local name="$1"
  grep -hsE "^[[:space:]]*(export[[:space:]]+)?${name}=.+" "$ENV_FILE" "$CONFIG_FILE" 2>/dev/null | grep -q .
}

for _pair in "TELEGRAM_BOT_TOKEN:${TELEGRAM_BOT_TOKEN:-}" "GEMINI_API_KEY:${GEMINI_API_KEY:-}"; do
  _name="${_pair%%:*}"
  _value="${_pair#*:}"
  if [[ -n "$_value" ]] && ! _have_secret "$_name"; then
    persist_secret "$_name" "$_value"
    say "Đã lưu $_name vào $CONFIG_FILE — lần sau không cần nhập."
  fi
done
unset _pair _name _value

# ── 3. Môi trường Python: venv → Python hệ thống → uv ────────────────
say "AI STV runner v3"

have_pip() { "$1" -m pip --version >/dev/null 2>&1; }

# Python thiếu ensurepip (bản build từ source, Debian tối giản…) vẫn có thể
# lấy pip bằng get-pip.py. Trả về 0 nếu sau đó "$1 -m pip" chạy được.
ensure_pip() {
  local py="$1" tmp
  have_pip "$py" && return 0
  "$py" -m ensurepip --upgrade >/dev/null 2>&1 || true
  have_pip "$py" && return 0
  say "Python thiếu pip — thử cài pip bằng get-pip.py"
  tmp="$(mktemp -d)"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 90 https://bootstrap.pypa.io/get-pip.py -o "$tmp/get-pip.py" 2>/dev/null || true
  elif command -v wget >/dev/null 2>&1; then
    wget -qT 90 -O "$tmp/get-pip.py" https://bootstrap.pypa.io/get-pip.py 2>/dev/null || true
  fi
  if [[ -s "$tmp/get-pip.py" ]]; then
    "$py" "$tmp/get-pip.py" --quiet --disable-pip-version-check >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
  have_pip "$py"
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return 0; fi
  local p
  for p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [[ -x "$p" ]]; then printf '%s\n' "$p"; return 0; fi
  done
  return 1
}

ensure_uv() {
  UV="$(find_uv || true)"
  [[ -n "$UV" ]] && return 0
  say "Đang tải uv (trình quản lý gói Python)…"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf --max-time 120 https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
  fi
  UV="$(find_uv || true)"
  [[ -n "$UV" ]] || fail "Không cài được pip lẫn uv.
  • Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y python3-pip python3-venv
  • Hoặc: curl -LsSf https://astral.sh/uv/install.sh | sh
  • Rồi chạy lại lệnh trên."
}

# Cài requirements: chịu được thiếu pip và PEP 668 (externally-managed).
install_requirements() {
  local py="$1"
  if have_pip "$py"; then
    "$py" -m pip install -q -U pip >/dev/null 2>&1 || true
    "$py" -m pip install -q -U -r "$APP_DIR/requirements.txt" >/dev/null 2>&1 && return 0
    "$py" -m pip install -q -U --break-system-packages -r "$APP_DIR/requirements.txt" >/dev/null 2>&1 && return 0
    say "pip lỗi — thử lại bằng uv."
  fi
  ensure_uv
  "$UV" pip install --python "$py" -q -U -r "$APP_DIR/requirements.txt" >/dev/null 2>&1
}

VENV="$APP_DIR/.venv"
BASE_PY="$PY"

if [[ "${AISTV_VENV:-1}" != "0" && -z "${VIRTUAL_ENV:-}" ]]; then
  if [[ -e "$VENV" ]] && ! "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then
    say "venv cũ không chạy được — đổi tên thành .venv.broken"
    mv "$VENV" "$VENV.broken.$(date +%s)" 2>/dev/null || true
  fi
  if [[ ! -x "$VENV/bin/python" ]]; then
    say "Tạo môi trường ảo .venv"
    "$PY" -m venv --without-pip "$VENV" >/dev/null 2>&1 \
      || "$PY" -m venv "$VENV" >/dev/null 2>&1 \
      || say "Không tạo được venv bằng python3 -m venv."
  fi
  if [[ -x "$VENV/bin/python" ]] && ensure_pip "$VENV/bin/python"; then
    PY="$VENV/bin/python"
  else
    say "venv không có pip — chuyển sang Python hệ thống."
    [[ -e "$VENV" ]] && mv "$VENV" "$VENV.broken.$(date +%s)" 2>/dev/null || true
    PY="$BASE_PY"
  fi
fi

# Python đang dùng vẫn không có pip (kể cả sau get-pip) → tạo venv bằng uv.
if ! have_pip "$PY" && ! ensure_pip "$PY"; then
  say "Python hiện tại thiếu pip — dùng uv để tạo môi trường."
  ensure_uv
  [[ -e "$VENV" ]] && mv "$VENV" "$VENV.broken.$(date +%s)" 2>/dev/null || true
  "$UV" venv --python "$BASE_PY" "$VENV" >/dev/null 2>&1 \
    || "$UV" venv --seed --python "$BASE_PY" "$VENV" >/dev/null 2>&1 \
    || fail "uv không tạo được môi trường Python."
  PY="$VENV/bin/python"
fi

REQ_FILE="$APP_DIR/requirements.txt"
REQ_HASH="$("$PY" - "$REQ_FILE" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()[:16])
PY
)"
DEP_MARK="$CONFIG_DIR/deps-$REQ_HASH-$(printf '%s' "$PY" | cksum | cut -d' ' -f1).ok"

if [[ -f "$DEP_MARK" ]] && "$PY" -c 'import telegram, nest_asyncio' >/dev/null 2>&1; then
  say "Thư viện Python đã có — bỏ qua pip cho nhanh"
else
  say "Cài thư viện Python ($PY) — lần đầu mất 1–2 phút"
  install_requirements "$PY" || fail "Cài thư viện thất bại.
  Thử tay: $PY -m pip install -r $APP_DIR/requirements.txt"
  "$PY" -c 'import telegram, nest_asyncio' >/dev/null 2>&1 \
    || fail "Đã cài nhưng không import được python-telegram-bot / nest_asyncio. Xem log phía trên."
  mkdir -p "$CONFIG_DIR" 2>/dev/null || true
  : > "$DEP_MARK" 2>/dev/null || true
  say "Thư viện Python OK"
fi

# ── 4. Seed workspace lần đầu (SOUL, AGENTS, skills) ─────────────────
if [[ -d "$APP_DIR/seed" ]]; then
  if [[ -n "${STV_HOME:-}" ]]; then
    WS="$STV_HOME/workspace"
  elif [[ -d /content ]]; then
    WS="/content/stv_agent/workspace"
  else
    WS="$HOME/stv_agent/workspace"
  fi
  mkdir -p "$WS"
  cp -Rn "$APP_DIR/seed/." "$WS/" 2>/dev/null || true
fi

# ── 5. Chạy bot ──────────────────────────────────────────────────────
say "Sẵn sàng sau $((SECONDS - START_TS))s — khởi chạy AI STV… (Ctrl+C để dừng)"
exec env PYTHONUNBUFFERED=1 AISTV_CLEAN_INSTALL="${AISTV_CLEAN_INSTALL:-0}" \
  STV_SKIP_SETUP="${STV_SKIP_SETUP:-0}" \
  OPENCODE_VARIANT="${OPENCODE_VARIANT:-max}" \
  AISTV_AGENT_TIMEOUT=0 \
  "$PY" "$APP_DIR/aistv_bot.py"
