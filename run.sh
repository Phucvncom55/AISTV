#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  AI STV — chạy bot Telegram bằng MỘT lệnh
#
#  Cách 1 (trong repo đã clone):
#      bash run.sh
#
#  Cách 2 (không cần clone trước):
#      bash <(curl -fsSL https://raw.githubusercontent.com/USER/AISTV/main/run.sh)
#
#  Biến môi trường tuỳ chọn:
#      TELEGRAM_BOT_TOKEN=123:abc   token bot (hoặc điền vào .env)
#      ALLOWED_USER_IDS=123,456     chỉ những user này được dùng bot
#      AISTV_REPO=...               URL repo khác
#      AISTV_DIR=~/AISTV            thư mục clone
#      AISTV_BRANCH=main            nhánh
#      AISTV_VENV=0                 không dùng venv
#      AISTV_CLEAN_INSTALL=0        không xoá & cài lại OpenCode mỗi lần chạy
#      STV_HOME=...                 nơi lưu workspace/sessions
# ════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="${AISTV_REPO:-https://github.com/USER/AISTV.git}"
BRANCH="${AISTV_BRANCH:-main}"
APP_DIR="${AISTV_DIR:-$HOME/AISTV}"
PY="${PYTHON:-python3}"

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

command -v "$PY" >/dev/null 2>&1 || fail "Không tìm thấy python3. Cài Python 3.10+ rồi chạy lại."
command -v curl >/dev/null 2>&1 || fail "Không tìm thấy curl. Cài curl rồi chạy lại."

# ── 1. Xác định mã nguồn: chạy tại chỗ hay clone từ GitHub ────────────
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/aistv_bot.py" ]]; then
  APP_DIR="$SCRIPT_DIR"
  say "Dùng mã nguồn tại $APP_DIR"
else
  command -v git >/dev/null 2>&1 || fail "Cần git để tải repo. Cài git rồi chạy lại."
  if [[ -d "$APP_DIR/.git" ]]; then
    say "Cập nhật mã nguồn trong $APP_DIR"
    git -C "$APP_DIR" pull --ff-only || say "Không cập nhật được (bỏ qua), dùng bản hiện có."
  else
    say "Tải mã nguồn từ $REPO"
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR" \
      || fail "Không clone được $REPO — kiểm tra lại URL repo trong run.sh / AISTV_REPO."
  fi
  [[ -f "$APP_DIR/aistv_bot.py" ]] || fail "Repo thiếu aistv_bot.py."
fi

cd "$APP_DIR"

# ── 2. Nạp .env (token, user id…) nếu có ─────────────────────────────
if [[ -f "$APP_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$APP_DIR/.env"
  set +a
fi

# ── 3. Môi trường Python riêng (venv) ────────────────────────────────
if [[ "${AISTV_VENV:-1}" != "0" && -z "${VIRTUAL_ENV:-}" ]]; then
  if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    say "Tạo môi trường ảo .venv"
    "$PY" -m venv "$APP_DIR/.venv" 2>/dev/null || say "Không tạo được venv, dùng Python hệ thống."
  fi
  [[ -x "$APP_DIR/.venv/bin/python" ]] && PY="$APP_DIR/.venv/bin/python"
fi

say "Cài thư viện Python"
"$PY" -m pip install -q -U pip >/dev/null 2>&1 || true
"$PY" -m pip install -q -U -r "$APP_DIR/requirements.txt" \
  || fail "Cài thư viện thất bại. Thử: $PY -m pip install -r requirements.txt"

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
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  say "Chưa có TELEGRAM_BOT_TOKEN — bot sẽ hỏi token khi khởi động."
  say "Muốn lần sau không phải nhập: tạo file .env với dòng TELEGRAM_BOT_TOKEN=..."
fi

say "Khởi chạy AI STV… (Ctrl+C để dừng)"
exec env PYTHONUNBUFFERED=1 "$PY" "$APP_DIR/aistv_bot.py"
