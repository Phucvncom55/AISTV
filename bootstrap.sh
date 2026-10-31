#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  AI STV — bootstrap (v6)
#  Tải/cập nhật mã nguồn rồi chạy run.sh trong repo, nhờ vậy không bị
#  kẹt bản run.sh cũ do cache của raw.githubusercontent.com.
#
#  Repo công khai:
#      bash <(curl -fsSL https://raw.githubusercontent.com/<user>/<repo>/main/bootstrap.sh)
#      bash <(curl -fsSL .../bootstrap.sh) https://github.com/<user>/<repo>
#
#  Repo RIÊNG TƯ: cần token GitHub đọc được repo. Script tự tìm token,
#  không hỏi, không chặn, theo thứ tự:
#      1. $AISTV_GITHUB_TOKEN / $GITHUB_TOKEN / $GH_TOKEN
#      2. Colab Secrets: AISTV_GITHUB_TOKEN, GITHUB_TOKEN, GH_TOKEN
#      3. File: $STV_HOME/.secrets/github_token,
#               /content/stv_agent/.secrets/github_token,
#               ~/.config/aistv/github_token, ~/.aistv_token,
#               /content/drive/MyDrive/aistv/github_token
#      4. gh auth token
#  Token được ghi vào ~/.config/aistv/git-credentials (quyền 600) để
#  git pull/push về sau không cần token nữa. Token KHÔNG BAO GIỜ in ra.
#
#  Biến môi trường: AISTV_REPO, AISTV_BRANCH, AISTV_DIR (như run.sh).
# ════════════════════════════════════════════════════════════════════
set -euo pipefail
export GIT_TERMINAL_PROMPT=0        # không treo ở prompt đăng nhập git
umask 077                           # file tạo ra chỉ chủ đọc được

REPO="${AISTV_REPO:-https://github.com/Phucvncom55/AISTV.git}"
BRANCH="${AISTV_BRANCH:-main}"
APP_DIR="${AISTV_DIR:-$HOME/AISTV}"
STATE_DIR="${AISTV_CONFIG_DIR:-$HOME/.config/aistv}"
CRED_FILE="$STATE_DIR/git-credentials"

if [[ $# -ge 1 && -n "${1:-}" && "${1}" != -* ]]; then
  REPO="$1"
  shift
fi
REPO="${REPO%/}"
if [[ "$REPO" != *://* && "$REPO" != git@* && "$REPO" != /* && "$REPO" == */* ]]; then
  REPO="https://github.com/${REPO}"
fi
[[ "$REPO" == http* && "$REPO" != *.git ]] && REPO="${REPO}.git"

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "Cần git. Debian/Ubuntu: sudo apt-get install -y git"

say "AI STV bootstrap v6"

# ── 1. Tìm token GitHub (không bắt người dùng nhập) ──────────────────
valid_token() {
  local t="${1:-}"
  [[ ${#t} -ge 20 ]] || return 1
  [[ "$t" != *" "* && "$t" != *$'\n'* && "$t" != *$'\r'* && "$t" != *$'\t'* ]] || return 1
  return 0
}

colab_secret_token() {
  command -v python3 >/dev/null 2>&1 || return 0
  python3 - <<'PY' 2>/dev/null || true
import sys
try:
    from google.colab import userdata
except Exception:
    sys.exit(0)
for name in ("AISTV_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
    try:
        value = (userdata.get(name) or "").strip()
    except Exception:
        continue
    if value:
        sys.stdout.write(value)
        break
PY
}

TOKEN=""
TOKEN_SRC=""

pick_token() {
  local value="${1:-}"
  if valid_token "$value"; then
    TOKEN="${value//[$'\r\n\t ']/}"
    TOKEN_SRC="$2"
    return 0
  fi
  return 1
}

if [[ "$REPO" == git@* || "$REPO" == ssh://* ]]; then
  :   # SSH: dùng khoá ssh, không cần token
else
  # 1. biến môi trường
  pick_token "${AISTV_GITHUB_TOKEN:-}" "biến môi trường AISTV_GITHUB_TOKEN" \
    || pick_token "${GITHUB_TOKEN:-}" "biến môi trường GITHUB_TOKEN" \
    || pick_token "${GH_TOKEN:-}" "biến môi trường GH_TOKEN" \
    || true

  # 2. Colab Secrets
  if [[ -z "$TOKEN" ]]; then
    pick_token "$(colab_secret_token)" "Colab Secrets" || true
  fi

  # 3. file token đặt sẵn
  if [[ -z "$TOKEN" ]]; then
    for path in \
      "${STV_HOME:+$STV_HOME/.secrets/github_token}" \
      "/content/stv_agent/.secrets/github_token" \
      "$STATE_DIR/github_token" \
      "$HOME/.aistv_token" \
      "/content/drive/MyDrive/aistv/github_token" \
      "$APP_DIR/.secrets/github_token"
    do
      [[ -n "$path" && -f "$path" ]] || continue
      pick_token "$(head -n 1 "$path" 2>/dev/null || true)" "file $(basename "$(dirname "$path")")/$(basename "$path")" && break
    done
  fi

  # 4. gh CLI
  if [[ -z "$TOKEN" ]] && command -v gh >/dev/null 2>&1; then
    pick_token "$(gh auth token 2>/dev/null || true)" "gh auth token" || true
  fi
fi

if [[ -n "$TOKEN" ]]; then
  mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR" 2>/dev/null || true
  printf 'https://x-access-token:%s@github.com\n' "$TOKEN" > "$CRED_FILE" 2>/dev/null || true
  chmod 600 "$CRED_FILE" 2>/dev/null || true
  # Dùng credential helper qua biến môi trường: không ghi token vào .git/config,
  # không lộ trong `git remote -v`, log hay thông báo lỗi.
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0="credential.helper"
  export GIT_CONFIG_VALUE_0="store --file=$CRED_FILE"
  say "Đã có token GitHub ($TOKEN_SRC) — dùng cho repo riêng tư"
else
  say "Không thấy token GitHub — thử tải công khai"
fi

# ── 2. Tải / cập nhật mã nguồn ──────────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
  say "Cập nhật mã nguồn trong $APP_DIR"
  if git -C "$APP_DIR" pull --ff-only >/dev/null 2>&1; then
    :
  elif [[ -n "$(git -C "$APP_DIR" status --porcelain 2>/dev/null)" ]]; then
    say "Có thay đổi chưa commit — dùng bản hiện có (không reset để tránh mất code)."
  else
    say "Không fast-forward được — lấy đúng bản $BRANCH trên GitHub."
    git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH" >/dev/null 2>&1 \
      || fail "Không tải được $REPO (nhánh $BRANCH)."
    git -C "$APP_DIR" reset --hard FETCH_HEAD >/dev/null 2>&1 \
      || fail "Không cập nhật được $APP_DIR."
  fi
else
  say "Tải mã nguồn từ $REPO"
  if ! git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR"; then
    if [[ -n "$TOKEN" ]]; then
      fail "Không clone được $REPO dù đã có token — PAT có thể hết hạn, hoặc chưa cấp quyền Contents: Read cho repo này."
    else
      fail "Không clone được $REPO. Nếu repo đang để riêng tư: thêm PAT vào Colab Secrets với tên GITHUB_TOKEN (quyền Contents: Read) rồi chạy lại."
    fi
  fi
fi

# Giữ credential helper trong repo để /update, git pull, git push về sau
# vẫn chạy được kể cả khi bot khởi động lại không qua bootstrap.
if [[ -n "$TOKEN" && -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" config credential.helper "store --file=$CRED_FILE" 2>/dev/null || true
fi

[[ -f "$APP_DIR/run.sh" ]] || fail "Repo thiếu run.sh."
[[ -f "$APP_DIR/aistv_bot.py" ]] || fail "Repo thiếu aistv_bot.py."

export AISTV_REPO="$REPO"
export AISTV_BRANCH="$BRANCH"
export AISTV_DIR="$APP_DIR"

exec bash "$APP_DIR/run.sh" "$@"
