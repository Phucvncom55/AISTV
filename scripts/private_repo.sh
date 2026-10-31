#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  AI STV — chuyển sang mô hình "code riêng tư, lệnh công khai"
#
#  Kết quả:
#    • Repo công khai  <owner>/aistv-boot : CHỈ có bootstrap.sh (+ README)
#    • Repo code       <owner>/AISTV      : đổi sang Private
#    • Lệnh chạy vẫn một dòng, không cần nhập mã:
#        bash <(curl -fsSL https://raw.githubusercontent.com/<owner>/aistv-boot/main/bootstrap.sh)
#
#  Dùng:
#      bash scripts/private_repo.sh                 # hỏi trước khi đổi private
#      bash scripts/private_repo.sh --yes           # không hỏi
#      bash scripts/private_repo.sh --keep-public   # chỉ tạo repo launcher
#      bash scripts/private_repo.sh --dry-run       # chỉ in việc sẽ làm
#
#  Cần: gh đã đăng nhập (gh auth status) và quyền tạo repo.
#  KHÔNG in token ra màn hình.
# ════════════════════════════════════════════════════════════════════
set -euo pipefail

OWNER="${AISTV_OWNER:-}"
CODE_REPO="${AISTV_CODE_REPO:-AISTV}"
BOOT_REPO="${AISTV_BOOT_REPO:-aistv-boot}"
BRANCH="${AISTV_BRANCH:-main}"
YES=0
MAKE_PRIVATE=1
DRY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="${2:?thiếu giá trị}"; shift 2 ;;
    --code-repo) CODE_REPO="${2:?thiếu giá trị}"; shift 2 ;;
    --boot-repo) BOOT_REPO="${2:?thiếu giá trị}"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --keep-public) MAKE_PRIVATE=0; shift ;;
    --dry-run|-n) DRY=1; shift ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Tham số lạ: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }
run()  { if [[ $DRY == 1 ]]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }

command -v gh >/dev/null 2>&1 || fail "Chưa có gh CLI. Cài: https://cli.github.com"
gh auth status >/dev/null 2>&1 || fail "gh chưa đăng nhập. Chạy: gh auth login"
[[ -f "$ROOT/bootstrap.sh" ]] || fail "Không thấy bootstrap.sh trong $ROOT"

OWNER="${OWNER:-$(gh api user --jq .login)}"
command -v base64 >/dev/null 2>&1 || fail "Thiếu base64."

say "Chủ repo: $OWNER"
say "Repo code: $OWNER/$CODE_REPO · repo launcher: $OWNER/$BOOT_REPO"

# ── 0. Kiểm tra repo code tồn tại ──────────────────────────────────
CODE_PRIVATE="$(gh api "repos/$OWNER/$CODE_REPO" --jq .private 2>/dev/null || echo "missing")"
[[ "$CODE_PRIVATE" != "missing" ]] || fail "Không thấy repo $OWNER/$CODE_REPO (hoặc token không đủ quyền)."
say "Repo $CODE_REPO hiện tại: $([[ "$CODE_PRIVATE" == "true" ]] && echo private || echo public)"

confirm() {
  [[ $YES == 1 || $DRY == 1 ]] && return 0
  local ans
  read -r -p "$1 [y/N] " ans || return 1
  [[ "$ans" == "y" || "$ans" == "Y" ]]
}

# ── 1. Tạo repo launcher công khai ─────────────────────────────────
if gh api "repos/$OWNER/$BOOT_REPO" >/dev/null 2>&1; then
  say "Repo $BOOT_REPO đã có — cập nhật nội dung"
else
  say "Tạo repo công khai $OWNER/$BOOT_REPO"
  run gh repo create "$OWNER/$BOOT_REPO" --public \
    --description "AI STV — bootstrap launcher (mã nguồn ở repo riêng tư)"
fi

put_file() {  # put_file <path-trong-repo> <file-nguồn>
  local path="$1" src="$2" sha content
  sha="$(gh api "repos/$OWNER/$BOOT_REPO/contents/$path" --jq .sha 2>/dev/null || true)"
  content="$(base64 < "$src" | tr -d '\n')"
  if [[ $DRY == 1 ]]; then
    printf '  [dry-run] PUT %s (%s)\n' "$path" "$(wc -c < "$src") byte"
    return 0
  fi
  if [[ -n "$sha" ]]; then
    gh api -X PUT "repos/$OWNER/$BOOT_REPO/contents/$path" \
      -f message="AI STV: cập nhật $path" -f content="$content" -f sha="$sha" >/dev/null
  else
    gh api -X PUT "repos/$OWNER/$BOOT_REPO/contents/$path" \
      -f message="AI STV: thêm $path" -f content="$content" >/dev/null
  fi
}

TMP_README="$(mktemp)"
trap 'rm -f "$TMP_README"' EXIT
cat > "$TMP_README" <<EOF
# AI STV — bootstrap

Repo này chỉ chứa **bootstrap.sh**. Toàn bộ mã nguồn nằm ở repo riêng tư \`$OWNER/$CODE_REPO\`.

\`\`\`bash
bash <(curl -fsSL https://raw.githubusercontent.com/$OWNER/$BOOT_REPO/$BRANCH/bootstrap.sh)
\`\`\`

Cần token GitHub đọc được repo riêng tư (fine-grained PAT, quyền **Contents: Read**), đặt một lần vào 🔑 Colab Secrets với tên \`GITHUB_TOKEN\` — các lần sau không phải nhập lại.
EOF

say "Đẩy bootstrap.sh lên $BOOT_REPO"
put_file "bootstrap.sh" "$ROOT/bootstrap.sh"
put_file "README.md" "$TMP_README"

# ── 2. Đổi repo code sang private ──────────────────────────────────
if [[ $MAKE_PRIVATE == 1 && "$CODE_PRIVATE" != "true" ]]; then
  warn "Sau khi private: Actions tính phút (Windows runner gấp đôi), fork/raw URL cũ không còn công khai."
  if confirm "Đổi $OWNER/$CODE_REPO sang PRIVATE?"; then
    run gh repo edit "$OWNER/$CODE_REPO" --visibility private --accept-visibility-change-consequences
    [[ $DRY == 1 ]] || say "Đã đổi $CODE_REPO sang private"
  else
    warn "Giữ nguyên public — chỉ mới tạo repo launcher"
  fi
else
  say "Không đổi visibility (đã private hoặc bạn chọn --keep-public)"
fi

# ── 3. In lệnh mới ─────────────────────────────────────────────────
echo
say "Lệnh chạy mới (dán vào Colab, giữ nguyên một dòng):"
printf '\n  !bash <(curl -fsSL https://raw.githubusercontent.com/%s/%s/%s/bootstrap.sh)\n\n' \
  "$OWNER" "$BOOT_REPO" "$BRANCH"
say "Nhớ lưu PAT vào Colab Secrets tên GITHUB_TOKEN (Contents: Read) — một lần cho mỗi tài khoản Google."
