#!/usr/bin/env bash
# Đưa dự án lên GitHub và in ra lệnh chạy bot 1 dòng.
# Dùng: gh auth login   (một lần)   →   bash push.sh [tên-repo] [public|private]
set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="${1:-AISTV}"
VISIBILITY="${2:-public}"
[[ "$VISIBILITY" == "public" || "$VISIBILITY" == "private" ]] || { echo "Tham số thứ 2 phải là public hoặc private"; exit 1; }

command -v gh  >/dev/null 2>&1 || { echo "✖ Chưa có GitHub CLI. Cài: https://cli.github.com"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "✖ Chưa có git."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "✖ Chưa đăng nhập GitHub. Chạy: gh auth login"; exit 1; }

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -b main >/dev/null
fi

LOGIN="$(gh api user -q .login)"
SLUG="$LOGIN/$REPO_NAME"

git config user.name  >/dev/null 2>&1 || git config user.name  "$LOGIN"
git config user.email >/dev/null 2>&1 || git config user.email "$LOGIN@users.noreply.github.com"

# Ghi URL repo thật vào run.sh + README để lệnh 1 dòng không cần sửa tay
python3 - "$SLUG" "$REPO_NAME" <<'PY'
import sys, pathlib
slug, repo = sys.argv[1], sys.argv[2]
raw = f"https://raw.githubusercontent.com/{slug}/main/run.sh"
for fn in ("run.sh", "README.md"):
    p = pathlib.Path(fn)
    if not p.exists():
        continue
    s = p.read_text("utf-8")
    s = s.replace("https://github.com/USER/AISTV.git", f"https://github.com/{slug}.git")
    s = s.replace("https://raw.githubusercontent.com/USER/AISTV/main/run.sh", raw)
    s = s.replace("<USER>/<REPO>", slug)
    s = s.replace("<tên-repo>", repo)
    p.write_text(s, "utf-8")
PY

git add -A
if ! git diff --cached --quiet; then
  git commit -m "AI STV — bot Telegram chạy OpenCode" >/dev/null
fi

if git remote get-url origin >/dev/null 2>&1; then
  git push -u origin HEAD
else
  gh repo create "$REPO_NAME" "--$VISIBILITY" --source=. --remote=origin --push
fi

URL="https://github.com/$SLUG"
RAW="https://raw.githubusercontent.com/$SLUG/main/run.sh"

echo
echo "✅ Repo: $URL"
if [[ "$VISIBILITY" == "public" ]]; then
  echo "▶ Chạy bot (Linux / macOS / Colab):"
  echo
  echo "   bash <(curl -fsSL $RAW)"
  echo
  echo "▶ Colab (dán vào ô code):"
  echo
  echo "   !bash <(curl -fsSL $RAW)"
else
  echo "▶ Repo private — clone rồi chạy:"
  echo
  echo "   git clone $URL.git && cd $REPO_NAME && bash run.sh"
fi
