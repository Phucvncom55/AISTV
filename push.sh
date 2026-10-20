#!/usr/bin/env bash
# Đưa dự án lên GitHub và in ra lệnh chạy bot 1 dòng.
#
# Dùng:
#   bash push.sh                      # quét repo của tài khoản → chọn repo (hoặc tạo mới)
#   bash push.sh owner/repo           # dùng đúng repo đó (hỏi tạo nếu chưa có)
#   bash push.sh ten-repo private     # repo thuộc tài khoản đang dùng token
#
# Token lấy theo thứ tự: GITHUB_TOKEN / GH_TOKEN → .secrets/github_token
# (STV_HOME, ~/stv_agent, ~) → gh CLI nếu có. Không cần cài gh.
set -euo pipefail
cd "$(dirname "$0")"

REPO_ARG="${1:-}"
VISIBILITY="${2:-public}"
[[ "$VISIBILITY" == "public" || "$VISIBILITY" == "private" ]] \
  || { echo "Tham số thứ 2 phải là public hoặc private"; exit 1; }

command -v git >/dev/null 2>&1 || { echo "✖ Chưa có git."; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "✖ Chưa có curl."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "✖ Chưa có python3."; exit 1; }

# ── Token GitHub (không in ra) ──
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "$TOKEN" ]]; then
  for f in "${STV_HOME:-}/.secrets/github_token" \
           "/content/stv_agent/.secrets/github_token" \
           "$HOME/stv_agent/.secrets/github_token" \
           "$HOME/.secrets/github_token"; do
    if [[ -n "$f" && -f "$f" ]]; then TOKEN="$(tr -d '\r\n' < "$f")"; break; fi
  done
fi
if [[ -z "$TOKEN" ]] && command -v gh >/dev/null 2>&1; then
  TOKEN="$(gh auth token 2>/dev/null || true)"
fi
[[ -n "$TOKEN" ]] || {
  echo "✖ Chưa có token GitHub."
  echo "  Cách 1: /github login trong bot rồi chạy lại."
  echo "  Cách 2: export GITHUB_TOKEN=... (PAT có quyền repo) rồi chạy lại."
  exit 1
}

TMP="$(mktemp)"; CRED="$(mktemp)"
chmod 600 "$TMP" "$CRED"
trap 'rm -f "$TMP" "$CRED"' EXIT

api() { curl -fsSL -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" -H "User-Agent: AISTV-push" "$@"; }
api_code() { curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" -H "User-Agent: AISTV-push" "$@"; }

LOGIN="$(api https://api.github.com/user | python3 -c 'import sys,json; print(json.load(sys.stdin).get("login") or "")')"
[[ -n "$LOGIN" ]] || { echo "✖ Token GitHub không hợp lệ."; exit 1; }

# ── Repo đang trỏ tới (nếu đã clone) ──
CUR_ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
CUR_SLUG="$(printf '%s' "$CUR_ORIGIN" | sed -E 's#^(https?://|git@)github\.com[:/]##; s#\.git$##')"

# Repo đã chọn trong bot (/github repos) — dùng làm mặc định
CFG_SLUG=""
for f in "${STV_HOME:-}/.secrets/github_repo" \
         "/content/stv_agent/.secrets/github_repo" \
         "$HOME/stv_agent/.secrets/github_repo" \
         "$HOME/.secrets/github_repo"; do
  if [[ -n "$f" && -f "$f" ]]; then CFG_SLUG="$(tr -d '\r\n' < "$f")"; break; fi
done

# ── Chọn repo: tham số → danh sách → repo hiện tại ──
slug_from_arg() {
  local a="$1"
  if [[ "$a" == */* ]]; then printf '%s' "${a%/}"; else printf '%s/%s' "$LOGIN" "$a"; fi
}

SLUG=""
if [[ -n "$REPO_ARG" ]]; then
  SLUG="$(slug_from_arg "$REPO_ARG")"
else
  echo "👤 Tài khoản: $LOGIN"
  api 'https://api.github.com/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member' > "$TMP"
  mapfile -t REPOS < <(python3 - "$TMP" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = []
for r in data if isinstance(data, list) else []:
    print(f"{r.get('full_name')}\t{'private' if r.get('private') else 'public'}")
PY
)
  echo "🔎 Repo hiện có:"
  if [[ ${#REPOS[@]} -eq 0 ]]; then
    echo "  (chưa có repo nào)"
  else
    i=1
    for r in "${REPOS[@]}"; do
      printf '  %2d) %s\n' "$i" "$(printf '%s' "$r" | awk -F'\t' '{print $1 "  [" $2 "]"}')"
      i=$((i + 1))
    done
  fi
  echo
  if [[ -t 0 ]]; then
    echo "Chọn số thứ tự, nhập owner/repo, gõ 'n' để tạo repo mới, Enter để dùng ${CFG_SLUG:-${CUR_SLUG:-repo đầu tiên}}."
    read -r -p "→ " CHOICE || CHOICE=""
  else
    CHOICE=""
  fi
  if [[ "$CHOICE" =~ ^[0-9]+$ ]] && (( CHOICE >= 1 && CHOICE <= ${#REPOS[@]} )); then
    SLUG="$(printf '%s' "${REPOS[$((CHOICE - 1))]}" | cut -f1)"
  elif [[ "$CHOICE" == "n" || "$CHOICE" == "N" ]]; then
    read -r -p "Tên repo mới: " NEW_NAME || NEW_NAME=""
    [[ -n "$NEW_NAME" ]] || { echo "✖ Chưa nhập tên repo."; exit 1; }
    SLUG="$LOGIN/$NEW_NAME"
  elif [[ -n "$CHOICE" ]]; then
    SLUG="$(slug_from_arg "$CHOICE")"
  elif [[ -n "$CFG_SLUG" ]]; then
    SLUG="$CFG_SLUG"
  elif [[ -n "$CUR_SLUG" ]]; then
    SLUG="$CUR_SLUG"
  elif [[ ${#REPOS[@]} -gt 0 ]]; then
    SLUG="$(printf '%s' "${REPOS[0]}" | cut -f1)"
  fi
fi

[[ -n "$SLUG" && "$SLUG" == */* ]] || { echo "✖ Chưa chọn được repo (dạng owner/name)."; exit 1; }
OWNER="${SLUG%%/*}"; REPO_NAME="${SLUG#*/}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY-RUN · tài khoản=$LOGIN · repo=$SLUG · visibility=$VISIBILITY"
  exit 0
fi

# ── Tạo repo nếu chưa tồn tại (không tự đoán tên repo) ──
if [[ "$(api_code "https://api.github.com/repos/$SLUG")" == "200" ]]; then
  echo "📦 Dùng repo có sẵn: $SLUG"
else
  CREATE="y"
  if [[ -t 0 ]]; then
    read -r -p "Repo $SLUG chưa có. Tạo mới ($VISIBILITY)? [Y/n] " CREATE || CREATE="y"
  fi
  if [[ "$CREATE" =~ ^[nN]$ ]]; then
    echo "↩︎ Không tạo. Chọn repo khác: bash push.sh owner/repo"
    exit 1
  fi
  PRIV="false"; [[ "$VISIBILITY" == "private" ]] && PRIV="true"
  echo "➕ Đang tạo $SLUG ($VISIBILITY)…"
  if [[ "$OWNER" == "$LOGIN" ]]; then
    api -X POST https://api.github.com/user/repos \
      -d "{\"name\":\"$REPO_NAME\",\"private\":$PRIV,\"auto_init\":false,\"description\":\"AI STV — Telegram × OpenCode\"}" >/dev/null
  else
    api -X POST "https://api.github.com/orgs/$OWNER/repos" \
      -d "{\"name\":\"$REPO_NAME\",\"private\":$PRIV,\"auto_init\":false,\"description\":\"AI STV — Telegram × OpenCode\"}" >/dev/null
  fi
fi

URL="https://github.com/$SLUG"
REMOTE="https://github.com/$SLUG.git"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -b main >/dev/null
fi

git config user.name  >/dev/null 2>&1 || git config user.name  "$LOGIN"
git config user.email >/dev/null 2>&1 || git config user.email "$LOGIN@users.noreply.github.com"

# ── Trỏ origin về đúng repo đã chọn (không đẩy nhầm repo cũ) ──
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi

# ── Ghi URL repo thật vào run.sh + bootstrap.sh + README ──
python3 - "$SLUG" "$CUR_SLUG" <<'PY'
import sys, pathlib, re
slug, old = sys.argv[1], sys.argv[2]
for fn in ("run.sh", "bootstrap.sh", "README.md"):
    p = pathlib.Path(fn)
    if not p.exists():
        continue
    s = p.read_text("utf-8")
    if old and old != slug:
        s = s.replace(old, slug)
    s = s.replace("https://github.com/USER/AISTV.git", f"https://github.com/{slug}.git")
    s = s.replace("https://raw.githubusercontent.com/USER/AISTV/main/", f"https://raw.githubusercontent.com/{slug}/main/")
    s = s.replace("<USER>/<REPO>", slug)
    s = s.replace("<tên-repo>", slug.split("/")[-1])
    s = re.sub(r"(https://raw\.githubusercontent\.com/)[^/\s'\"]+/[^/\s'\"]+/main/",
               rf"\g<1>{slug}/main/", s)
    s = re.sub(r"https://github\.com/[^/\s'\"]+/[^/\s'\"]+\.git",
               f"https://github.com/{slug}.git", s)
    p.write_text(s, "utf-8")
PY

git add -A
if ! git diff --cached --quiet; then
  git commit -m "AI STV — bot Telegram chạy OpenCode" >/dev/null
fi

# Token chỉ nằm trong file tạm 600, không lộ ra lệnh/ps
printf 'https://x-access-token:%s@github.com\n' "$TOKEN" > "$CRED"
if ! git -c credential.helper= -c "credential.helper=store --file=$CRED" push -u origin HEAD; then
  echo
  echo "✖ Push thất bại. Nguyên nhân thường gặp:"
  echo "  • Repo đã có lịch sử khác (không fast-forward) → chọn repo trống khác."
  echo "  • Token không có quyền ghi repo này → chọn repo khác trong danh sách."
  echo "  • Repo private của tài khoản khác → dùng token của tài khoản sở hữu."
  exit 1
fi

RAW="https://raw.githubusercontent.com/$SLUG/main/bootstrap.sh?v=3"

echo
echo "✅ Repo: $URL"
if [[ "$VISIBILITY" == "public" ]]; then
  echo "▶ Chạy bot (Linux / macOS / Colab) — luôn lấy bản mới nhất:"
  echo
  echo "   bash <(curl -fsSL '$RAW')"
  echo
  echo "▶ Colab (dán vào ô code):"
  echo
  echo "   !bash <(curl -fsSL '$RAW')"
else
  echo "▶ Repo private — chạy từ bản clone:"
  echo
  echo "   git clone $URL.git && cd $REPO_NAME && bash run.sh"
fi
