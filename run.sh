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

# ── 2. Token: .env → biến môi trường → Colab Secrets → hỏi trực tiếp ─
if [[ -f "$APP_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$APP_DIR/.env"
  set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${ALLOWED_USER_IDS:-}" ]]; then
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
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" && -t 0 ]]; then
  printf '🔑 Dán Telegram Bot Token (Enter để bỏ qua): '
  IFS= read -r TELEGRAM_BOT_TOKEN || true
  TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN// /}"
  if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
    export TELEGRAM_BOT_TOKEN
    touch "$APP_DIR/.env"
    if grep -q '^TELEGRAM_BOT_TOKEN=' "$APP_DIR/.env" 2>/dev/null; then
      "$PY" - "$APP_DIR/.env" "$TELEGRAM_BOT_TOKEN" <<'PY'
import sys, pathlib
p, tok = pathlib.Path(sys.argv[1]), sys.argv[2]
lines = [("TELEGRAM_BOT_TOKEN=" + tok) if l.startswith("TELEGRAM_BOT_TOKEN=") else l
         for l in p.read_text("utf-8").splitlines()]
p.write_text("\n".join(lines) + "\n", "utf-8")
PY
    else
      printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN" >> "$APP_DIR/.env"
    fi
    chmod 600 "$APP_DIR/.env" 2>/dev/null || true
    say "Đã lưu token vào .env (lần sau không cần nhập)."
  fi
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  cat <<'EOF' >&2

✖ Chưa có Telegram Bot Token.
  • Colab: mở 🔑 Secrets (chìa khoá ở cột trái) → thêm
        TELEGRAM_BOT_TOKEN = 123456:ABC...     (bật "Notebook access")
        ALLOWED_USER_IDS   = 123456789        (tuỳ chọn, khoá bot)
    rồi chạy lại đúng lệnh trên.
  • VPS / máy cá nhân: tạo file .env trong thư mục repo:
        TELEGRAM_BOT_TOKEN=123456:ABC...
    hoặc: TELEGRAM_BOT_TOKEN=... bash run.sh

EOF
  exit 1
fi

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
    "$PY" -m venv "$VENV" >/dev/null 2>&1 || say "Không tạo được venv bằng python3 -m venv."
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

say "Cài thư viện Python ($PY)"
install_requirements "$PY" || fail "Cài thư viện thất bại.
  Thử tay: $PY -m pip install -r $APP_DIR/requirements.txt"
"$PY" -c 'import telegram, nest_asyncio' >/dev/null 2>&1 \
  || fail "Đã cài nhưng không import được python-telegram-bot / nest_asyncio. Xem log phía trên."
say "Thư viện Python OK"

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
say "Khởi chạy AI STV… (Ctrl+C để dừng)"
exec env PYTHONUNBUFFERED=1 AISTV_CLEAN_INSTALL="${AISTV_CLEAN_INSTALL:-0}" \
  STV_SKIP_SETUP="${STV_SKIP_SETUP:-0}" \
  "$PY" "$APP_DIR/aistv_bot.py"
