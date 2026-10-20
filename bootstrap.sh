#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  AI STV — bootstrap
#  Luôn tải/cập nhật repo rồi mới chạy run.sh trong repo, nhờ vậy không
#  bị kẹt bản run.sh cũ do cache của raw.githubusercontent.com.
#
#      bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh)
#      bash <(curl -fsSL .../bootstrap.sh) https://github.com/<user>/<repo>
#
#  Biến môi trường: AISTV_REPO, AISTV_BRANCH, AISTV_DIR (như run.sh).
# ════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="${AISTV_REPO:-https://github.com/Phucvncom55/AISTV.git}"
BRANCH="${AISTV_BRANCH:-main}"
APP_DIR="${AISTV_DIR:-$HOME/AISTV}"

if [[ $# -ge 1 && -n "${1:-}" ]]; then
  REPO="$1"
  shift
fi
REPO="${REPO%/}"
if [[ "$REPO" != *://* && "$REPO" != git@* && "$REPO" != /* && "$REPO" == */* ]]; then
  REPO="https://github.com/${REPO}"
fi
[[ "$REPO" == http* && "$REPO" != *.git ]] && REPO="${REPO}.git"

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "Cần git. Debian/Ubuntu: sudo apt-get install -y git"

say "AI STV bootstrap v3"

if [[ -d "$APP_DIR/.git" ]]; then
  say "Cập nhật mã nguồn trong $APP_DIR"
  if git -C "$APP_DIR" pull --ff-only >/dev/null 2>&1; then
    :
  else
    say "Không fast-forward được — lấy đúng bản $BRANCH trên GitHub."
    git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH" >/dev/null 2>&1 \
      || fail "Không tải được $REPO (nhánh $BRANCH)."
    git -C "$APP_DIR" reset --hard FETCH_HEAD >/dev/null 2>&1 \
      || fail "Không cập nhật được $APP_DIR."
  fi
else
  say "Tải mã nguồn từ $REPO"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR" \
    || fail "Không clone được $REPO — kiểm tra URL / nhánh $BRANCH."
fi

[[ -f "$APP_DIR/run.sh" ]] || fail "Repo thiếu run.sh."
[[ -f "$APP_DIR/aistv_bot.py" ]] || fail "Repo thiếu aistv_bot.py."

exec bash "$APP_DIR/run.sh" "$@"
