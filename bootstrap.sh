#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  AI STV — bootstrap (v8)
#  Tải/cập nhật mã nguồn rồi chạy run.sh trong repo, nhờ vậy không bị
#  kẹt bản run.sh cũ do cache của raw.githubusercontent.com.
#
#  Repo công khai:
#      bash <(curl -fsSL https://raw.githubusercontent.com/<user>/<repo>/main/bootstrap.sh)
#      bash <(curl -fsSL .../bootstrap.sh) https://github.com/<user>/<repo>
#
#  MÁY TRẮNG, KHÔNG NHẬP GÌ (v8): đọc blob mã hoá trên Firebase
#  (aistv/boot.json) → TELEGRAM_BOT_TOKEN → mở kho cấu hình 17 mục →
#  GITHUB_TOKEN → clone repo private. Chỉ cần chạy một lệnh curl.
#  CẢNH BÁO THẬT: khoá giải mã nằm ngay trong file công khai này. Nó chỉ
#  chống công cụ quét token tự động và người xem qua loa, KHÔNG chống được
#  người đọc kỹ. Ai lấy được blob là điều khiển được bot + toàn bộ key.
#  (Muốn chống thật thì phải nhập một bí mật — Colab Secrets hoặc pairing.)
#
#  Token vẫn được tìm theo thứ tự cũ nếu Firebase lỗi:
#      1. $AISTV_GITHUB_TOKEN / $GITHUB_TOKEN / $GH_TOKEN
#      2. Colab Secrets: AISTV_GITHUB_TOKEN, GITHUB_TOKEN, GH_TOKEN
#      3. Kho cấu hình mã hoá (cần token bot từ blob) → GITHUB_TOKEN
#      4. File: /content/stv_agent/.secrets/github_token,
#               ~/.config/aistv/github_token, ~/.aistv_token,
#               /content/drive/MyDrive/aistv/github_token
#      5. gh auth token
#  Token được ghi vào ~/.config/aistv/git-credentials (quyền 600) để
#  git pull/push về sau không cần token nữa. Token KHÔNG BAO GIỜ in ra.
#
#  Token bot Telegram: AISTV_BOOTSTRAP_TOKEN / AISTV_BOT_TOKEN /
#  TELEGRAM_BOT_TOKEN trong dòng lệnh, blob Firebase, file đã lưu, hoặc
#  repo cấu hình private. Tìm thấy thì ghi lại vào ~/.config/aistv/token
#  (và Drive nếu có) để lần sau không hỏi nữa.
#
#  Biến môi trường: AISTV_REPO, AISTV_BRANCH, AISTV_DIR (như run.sh),
#  AISTV_BOOT_URL (đổi Firebase base), AISTV_BOOT_KEY (đổi khoá blob).
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

say "AI STV bootstrap v8"

# ── 1a. Blob khởi động trên Firebase: máy trắng không phải nhập gì ───
valid_bot() { [[ "${1:-}" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{30,}$ ]]; }

BOT_TOKEN=""
pick_bot() {
  if valid_bot "${1:-}"; then BOT_TOKEN="$1"; return 0; fi
  return 1
}

# Giải mã blob Firebase — cùng định dạng với aistv_config.vault_decrypt.
#   $1 = endpoint, $2 = khoá mã hoá. In JSON ra stdout; lỗi → rỗng.
fb_secret() {
  command -v python3 >/dev/null 2>&1 || return 0
  AISTV_FB_URL="$1" AISTV_FB_KEY="$2" python3 - <<'PY' 2>/dev/null || true
import base64, hashlib, hmac, json, os, sys, urllib.request

url = os.environ.get("AISTV_FB_URL", "")
key = os.environ.get("AISTV_FB_KEY", "")
if not url or not key:
    sys.exit(0)
try:
    req = urllib.request.Request(url, headers={"User-Agent": "AISTV-boot/1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    raw = base64.b64decode(str(payload.get("blob") or ""))
    if len(raw) < 49:
        sys.exit(0)
    nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
    master = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), b"aistv-secrets-v1", 120000)
    enc = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac = hmac.new(master, b"mac", hashlib.sha256).digest()
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + ct, hashlib.sha256).digest()):
        sys.exit(0)
    stream = bytearray()
    block = 0
    while len(stream) < len(ct):
        stream += hmac.new(enc, nonce + block.to_bytes(8, "big"), hashlib.sha256).digest()
        block += 1
    plain = bytes(a ^ b for a, b in zip(ct, stream)).decode("utf-8")
    data = json.loads(plain)
    if isinstance(data, dict):
        sys.stdout.write(json.dumps(data, ensure_ascii=False))
except Exception:
    pass
PY
}

json_get() {  # $1 = tên khoá, JSON đọc từ stdin
  command -v python3 >/dev/null 2>&1 || return 0
  python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
sys.stdout.write(str(data.get(sys.argv[1]) or "") if isinstance(data, dict) else "")
' "$1" 2>/dev/null || true
}

BOOT_BASE="${AISTV_BOOT_URL:-https://sever-login-ae5cc-default-rtdb.firebaseio.com}"
BOOT_BASE="${BOOT_BASE%/}"
# Khoá nằm trong file CÔNG KHAI — xem cảnh báo ở đầu file.
BOOT_KEY="${AISTV_BOOT_KEY:-aistv-boot|7f2c9d14b6e8a305}"
BOOT_ENDPOINT="$BOOT_BASE/aistv/boot.json"
VAULT_ENDPOINT="$BOOT_BASE/aistv/secrets.json"

BOOT_JSON="$(fb_secret "$BOOT_ENDPOINT" "$BOOT_KEY")"
if [[ -n "$BOOT_JSON" ]]; then
  pick_bot "$(printf '%s' "$BOOT_JSON" | json_get TELEGRAM_BOT_TOKEN)" || true
  say "Đã đọc blob khởi động trên Firebase (mã hoá)"
fi

# ── 1b. Tìm token GitHub (không bắt người dùng nhập) ─────────────────
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

  # 4. Kho cấu hình mã hoá (chỉ cần token bot) → GITHUB_TOKEN
  if [[ -z "$TOKEN" && -n "$BOT_TOKEN" ]]; then
    _vault_json="$(fb_secret "$VAULT_ENDPOINT" "$BOT_TOKEN")"
    if [[ -n "$_vault_json" ]]; then
      pick_token "$(printf '%s' "$_vault_json" | json_get GITHUB_TOKEN)" "kho cấu hình mã hoá" || true
    fi
    unset _vault_json
  fi

  # 5. gh CLI
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

# ── 1c. Token bot Telegram: không bắt người dùng nhập ────────────────
if [[ -z "$BOT_TOKEN" ]]; then
  pick_bot "${AISTV_BOOTSTRAP_TOKEN:-}" \
    || pick_bot "${AISTV_BOT_TOKEN:-}" \
    || pick_bot "${TELEGRAM_BOT_TOKEN:-}" || true
fi

if [[ -z "$BOT_TOKEN" ]]; then
  for path in "$STATE_DIR/token" \
    "${STV_HOME:+$STV_HOME/.secrets/bootstrap_token}" \
    "/content/stv_agent/.secrets/bootstrap_token" \
    "$HOME/.aistv_token" "/content/.aistv_token" \
    "/content/drive/MyDrive/aistv/token"; do
    [[ -n "$path" && -f "$path" ]] || continue
    pick_bot "$(head -n1 "$path" 2>/dev/null | tr -d '[:space:]')" && break
  done
fi

# Chỉ cần GitHub token là đủ: đọc token bot trong repo cấu hình private.
if [[ -z "$BOT_TOKEN" && -n "$TOKEN" ]] && command -v curl >/dev/null 2>&1; then
  _cfg_repo="${AISTV_CONFIG_REPO:-Phucvncom55/AISTV-secrets}"
  _cfg_path="${AISTV_CONFIG_PATH:-config.env}"
  _body="$(curl -fsSL -m 20 -H "Authorization: Bearer $TOKEN" \
    -H 'Accept: application/vnd.github.raw' \
    "https://api.github.com/repos/${_cfg_repo}/contents/${_cfg_path}" 2>/dev/null || true)"
  _cand="$(printf '%s\n' "$_body" | grep -m1 '^[[:space:]]*TELEGRAM_BOT_TOKEN[[:space:]]*=' || true)"
  _cand="${_cand#*=}"
  _cand="${_cand//[[:space:]]/}"
  _cand="${_cand//\"/}"
  _cand="${_cand//\'/}"
  pick_bot "$_cand" || true
  unset _cfg_repo _cfg_path _body _cand
fi

if [[ -n "$BOT_TOKEN" ]]; then
  export TELEGRAM_BOT_TOKEN="$BOT_TOKEN"
  mkdir -p "$STATE_DIR" 2>/dev/null && chmod 700 "$STATE_DIR" 2>/dev/null || true
  for _dst in "$STATE_DIR/token" "/content/drive/MyDrive/aistv/token"; do
    mkdir -p "$(dirname "$_dst")" 2>/dev/null || continue
    printf '%s\n' "$BOT_TOKEN" > "$_dst" 2>/dev/null || continue
    chmod 600 "$_dst" 2>/dev/null || true
  done
  unset _dst
  say "Đã có token bot — không phải nhập tay"
else
  say "Chưa có token bot — đặt AISTV_BOOTSTRAP_TOKEN trong lệnh chạy để khỏi nhập"
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

# Chẩn đoán: chỉ kiểm tra tải được code + token, không chạy bot.
if [[ "${AISTV_BOOTSTRAP_ONLY:-0}" == "1" ]]; then
  say "Chỉ kiểm tra (AISTV_BOOTSTRAP_ONLY=1) — dừng trước run.sh."
  exit 0
fi

exec bash "$APP_DIR/run.sh" "$@"
