#!/usr/bin/env python3
"""AI STV GitHub docs helper: xem repo, cây tệp, đọc README/tài liệu, tìm trong docs và mã."""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
UA = "AISTV-github-docs/1.0"
TIMEOUT = 30
MAX_FILE_BYTES = 900_000
try:
    CACHE_TTL = int(os.getenv("AISTV_DOCS_TTL", "300"))
except ValueError:
    CACHE_TTL = 300
CACHE_DIR = Path(os.getenv("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "aistv-github-docs"
REFRESH = False

DOC_EXTS = {".md", ".mdx", ".rst", ".adoc", ".asciidoc", ".txt", ".org"}
CODE_EXTS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala", ".sh",
    ".bash", ".zsh", ".ps1", ".sql", ".html", ".css", ".scss", ".vue", ".svelte",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json", ".dockerfile", ".tf",
}
SPECIAL_DOCS = {
    "readme", "contributing", "changelog", "changes", "history", "architecture",
    "security", "code_of_conduct", "faq", "install", "usage", "upgrading",
}
CONFIG_DOCS = {
    "mkdocs.yml", "mkdocs.yaml", "docusaurus.config.js", "docusaurus.config.ts",
    ".vitepress/config.js", ".vitepress/config.ts", ".vitepress/config.mjs",
    "book.toml", "conf.py", ".readthedocs.yaml", ".readthedocs.yml",
}
SKIP_DIRS = {
    "node_modules", ".git", "vendor", "dist", "build", "site", ".venv", "venv",
    "__pycache__", "target", "coverage", ".next", "out", ".tox", ".mypy_cache",
    ".pytest_cache", ".idea", ".vscode", "bower_components",
}
LOCALE_DIRS = {
    "i18n", "i18n-pt_br", "locales", "locale", "translations", "translation",
    "lang", "languages", "docs-translations",
}


class Target:
    def __init__(self, owner, repo, ref="", path=""):
        self.owner = owner
        self.repo = repo
        self.ref = ref
        self.path = path

    @property
    def slug(self):
        return f"{self.owner}/{self.repo}"


def err(msg):
    return None, str(msg).strip()


def oneline(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def fmt_num(n):
    try:
        n = int(n or 0)
    except Exception:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


def fmt_size(n):
    try:
        n = int(n or 0)
    except Exception:
        return "?"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def fmt_date(raw):
    if not raw:
        return "?"
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except Exception:
        return str(raw)[:10]


def token_fingerprint(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else "anon"


def load_token():
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    homes = []
    if os.getenv("STV_HOME"):
        homes.append(Path(os.environ["STV_HOME"]))
    homes += [Path("/content/stv_agent"), Path.home() / "stv_agent", Path.home()]
    for home in homes:
        p = home / ".secrets" / "github_token"
        try:
            if p.is_file():
                val = p.read_text("utf-8").strip()
                if val:
                    return val
        except Exception:
            pass
    exe = shutil.which("gh")
    if exe:
        try:
            out = subprocess.run([exe, "auth", "token", "--hostname", "github.com"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            pass
    return ""


TOKEN = load_token()


def configured_repo():
    for name in ("AISTV_GITHUB_REPO", "AISTV_REPO"):
        val = (os.getenv(name) or "").strip()
        if "/" in val:
            return val
    if os.getenv("STV_HOME"):
        homes = [Path(os.environ["STV_HOME"])]
    else:
        homes = []
    homes += [Path("/content/stv_agent"), Path.home() / "stv_agent", Path.home()]
    for home in homes:
        p = home / ".secrets" / "github_repo"
        try:
            if p.is_file():
                val = p.read_text("utf-8").strip()
                if "/" in val:
                    return val
        except Exception:
            pass
    try:
        out = subprocess.run(["git", "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$",
                          out.stdout.strip())
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def parse_target(raw, ref_override=""):
    s = (raw or "").strip().strip("<>\"'")
    if not s:
        return err("thiếu repo (dạng owner/name hoặc link GitHub)")
    if s.lower() in ("self", "."):
        s = configured_repo()
        if not s:
            return err("chưa cấu hình repo đích — nhập owner/name")
    s = re.sub(r"^git@github\.com:", "https://github.com/", s)
    s = re.sub(r"^git\+", "", s)
    if s.startswith("github.com/") or s.startswith("www.github.com/"):
        s = "https://" + s
    if "://" not in s:
        s = "https://github.com/" + s
    u = urllib.parse.urlsplit(s)
    host = (u.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in ("github.com", "raw.githubusercontent.com"):
        return err("chỉ hỗ trợ link github.com hoặc raw.githubusercontent.com")
    parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
    ref = (ref_override or "").strip()
    path = ""
    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            return err("link raw không hợp lệ (cần owner/repo/ref/đường-dẫn)")
        owner, repo, ref = parts[0], parts[1], parts[2]
        path = "/".join(parts[3:])
    else:
        if len(parts) < 2:
            return err("link GitHub không hợp lệ (cần owner/repo)")
        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if len(parts) >= 3 and parts[2] in ("blob", "tree", "raw"):
            rest = parts[3:]
            if ref:
                path = "/".join(rest[1:]) if rest else ""
            elif rest:
                ref = rest[0]
                path = "/".join(rest[1:])
        elif len(parts) > 2:
            path = "/".join(parts[2:])
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner or "") or \
            not re.fullmatch(r"[A-Za-z0-9_.-]+", repo or ""):
        return err("owner/repo không hợp lệ")
    return Target(owner, repo, ref, path), None


def cache_file(url, accept):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CACHE_DIR.chmod(0o700)
    except Exception:
        pass
    key = url + "\n" + accept + "\n" + token_fingerprint(TOKEN)
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def cache_read(path):
    if REFRESH:
        return None
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text("utf-8"))
        if time.time() - float(raw.get("t") or 0) > CACHE_TTL:
            return None
        return raw
    except Exception:
        return None


def cache_write(path, **kw):
    try:
        path.write_text(json.dumps({"t": int(time.time()), **kw}, ensure_ascii=False),
                        "utf-8")
    except Exception:
        pass


def api_url(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def http_get(url, headers, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), dict(r.headers), None
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()[:600]
        except Exception:
            pass
        return None, dict(e.headers or {}), (e.code, body.decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        return None, {}, (0, str(e.reason))
    except Exception as e:
        return None, {}, (0, str(e))


def api_get(path, params=None, accept="application/vnd.github+json", raw=False):
    url = api_url(path, params)
    cf = cache_file(url, accept)
    cached = cache_read(cf)
    if cached is not None:
        return (cached.get("text") if raw else cached.get("data")), None

    headers = {
        "Accept": accept,
        "User-Agent": UA,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    body, hdrs, problem = http_get(url, headers)
    if problem:
        code, detail = problem
        if code == 401:
            return err("token GitHub không hợp lệ hoặc đã hết hạn — dùng /github login lại")
        if code == 403:
            remaining = str(hdrs.get("X-RateLimit-Remaining", "")).strip()
            if remaining == "0":
                reset = str(hdrs.get("X-RateLimit-Reset", "")).strip()
                when = ""
                if reset.isdigit():
                    when = datetime.fromtimestamp(int(reset)).strftime("%H:%M:%S")
                return err(f"hết hạn mức GitHub API{f' — thử lại sau {when}' if when else ''}")
            return err(f"GitHub từ chối (403): {oneline(detail, 220)}")
        if code == 404:
            return err("không tìm thấy repo/tệp (private cần token, hoặc sai tên/đường dẫn)")
        if code == 0:
            return err(f"không kết nối được GitHub: {oneline(detail, 200)}")
        return err(f"GitHub trả lỗi HTTP {code}: {oneline(detail, 220)}")

    text = (body or b"").decode("utf-8", "replace")
    if raw:
        cache_write(cf, text=text)
        return text, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return err("GitHub trả dữ liệu không phải JSON")
    cache_write(cf, data=data)
    return data, None


def repo_info(t):
    data, problem = api_get(f"/repos/{t.owner}/{t.repo}")
    if problem:
        return None, problem
    lic = data.get("license") or {}
    return {
        "slug": data.get("full_name") or t.slug,
        "owner": t.owner,
        "repo": t.repo,
        "description": data.get("description") or "",
        "default_branch": data.get("default_branch") or "main",
        "private": bool(data.get("private")),
        "archived": bool(data.get("archived")),
        "stars": data.get("stargazers_count") or 0,
        "forks": data.get("forks_count") or 0,
        "watchers": data.get("subscribers_count") or 0,
        "language": data.get("language") or "",
        "license": lic.get("spdx_id") or lic.get("name") or "",
        "topics": data.get("topics") or [],
        "updated_at": data.get("updated_at") or "",
        "created_at": data.get("created_at") or "",
        "homepage": data.get("homepage") or "",
        "clone_url": data.get("clone_url") or f"https://github.com/{t.slug}.git",
        "html_url": data.get("html_url") or f"https://github.com/{t.slug}",
        "size": data.get("size") or 0,
    }, None


def default_ref(t):
    if t.ref:
        return t.ref, None
    info, problem = repo_info(t)
    if problem:
        return None, problem
    return info["default_branch"], None


def get_tree(t, ref):
    data, problem = api_get(f"/repos/{t.owner}/{t.repo}/git/trees/{urllib.parse.quote(ref, safe='')}",
                            {"recursive": "1"})
    if problem:
        return None, problem
    entries = []
    for item in data.get("tree") or []:
        entries.append({
            "path": item.get("path") or "",
            "type": item.get("type") or "",
            "size": item.get("size") or 0,
            "sha": item.get("sha") or "",
        })
    return {"entries": entries, "truncated": bool(data.get("truncated"))}, None


def fetch_raw(url):
    body, _, problem = http_get(url, {"User-Agent": UA})
    if problem:
        code, detail = problem
        if code == 404:
            return None, "không thấy tệp"
        return None, f"HTTP {code}: {oneline(detail, 160)}"
    return (body or b"").decode("utf-8", "replace"), None


def file_url(t, ref, path):
    return (f"https://github.com/{t.slug}/blob/"
            f"{urllib.parse.quote(ref, safe='/')}/{urllib.parse.quote(path, safe='/')}")


def fetch_file(t, path, ref):
    info, problem = repo_info(t)
    if problem:
        return None, problem
    text = None
    src = ""
    if not info["private"] and "/" not in ref:
        url = (f"{RAW}/{t.owner}/{t.repo}/{urllib.parse.quote(ref, safe='/')}/"
               f"{urllib.parse.quote(path, safe='/')}")
        text, raw_problem = fetch_raw(url)
        if text is not None:
            src = url
        elif raw_problem and raw_problem != "không thấy tệp":
            return None, raw_problem

    meta = {}
    if text is None:
        data, problem = api_get(
            f"/repos/{t.owner}/{t.repo}/contents/{urllib.parse.quote(path, safe='/')}",
            {"ref": ref})
        if problem:
            return None, problem
        if isinstance(data, list):
            return None, "đường dẫn là thư mục, không phải tệp"
        meta = data
        content = data.get("content")
        if content:
            try:
                text = base64.b64decode(content).decode("utf-8", "replace")
            except Exception:
                return None, "không giải mã được nội dung tệp"
        elif data.get("download_url"):
            text, raw_problem = fetch_raw(data["download_url"])
            if text is None:
                return None, (f"tệp quá lớn để đọc qua API ({fmt_size(data.get('size'))})"
                              f"{' — ' + raw_problem if raw_problem else ''}")
        else:
            return None, f"tệp quá lớn để đọc qua API ({fmt_size(data.get('size'))})"

    if "\x00" in (text or "")[:4000]:
        return None, "tệp nhị phân — không đọc được dạng văn bản"
    return {
        "text": text,
        "path": path,
        "ref": ref,
        "size": meta.get("size") or len(text.encode("utf-8")),
        "sha": meta.get("sha") or "",
        "url": meta.get("html_url") or file_url(t, ref, path),
        "source": src,
    }, None


def parse_headings(text):
    out = []
    in_fence = False
    for i, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m:
            out.append({"level": len(m.group(1)), "title": m.group(2).strip(), "line": i + 1})
    return out


def norm_heading(s):
    return re.sub(r"[`*_#:]+", " ", (s or "").strip().lower()).strip()


def section_text(text, name):
    headings = parse_headings(text)
    want = norm_heading(name)
    found = None
    for idx, h in enumerate(headings):
        got = norm_heading(h["title"])
        if got == want or want in got:
            found = idx
            break
    if found is None:
        names = [h["title"] for h in headings[:30]]
        return None, None, names
    start = headings[found]["line"] - 1
    level = headings[found]["level"]
    end = len(text.splitlines())
    for h in headings[found + 1:]:
        if h["level"] <= level:
            end = h["line"] - 1
            break
    lines = text.splitlines()
    return "\n".join(lines[start:end]).strip(), headings[found]["title"], None


def truncate_text(text, limit):
    if not limit or limit <= 0 or len(text) <= limit:
        return text, False
    cut = text[:limit]
    nl = cut.rfind("\n")
    if nl > limit * 0.6:
        cut = cut[:nl]
    rest = len(text) - len(cut)
    return cut + f"\n\n[... cắt bớt — còn {rest:,} ký tự]", True


def is_probably_dir(path):
    if path.endswith("/"):
        return True
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return "." not in last


def list_dir(t, path, ref):
    data, problem = api_get(
        f"/repos/{t.owner}/{t.repo}/contents/{urllib.parse.quote(path.strip('/'), safe='/')}",
        {"ref": ref})
    if problem:
        return None, problem
    if not isinstance(data, list):
        return None, "đường dẫn là tệp, không phải thư mục"
    return data, None


def pick_doc_in_dir(items):
    names = {str(it.get("name") or "").lower(): it for it in items if it.get("type") == "file"}
    for cand in ("readme.md", "readme.mdx", "readme.rst", "readme.txt", "index.md",
                 "index.mdx", "index.rst", "intro.md", "introduction.md"):
        if cand in names:
            return names[cand].get("path")
    readmes = sorted(
        (name, it) for name, it in names.items()
        if name.startswith("readme") and Path(name).suffix in DOC_EXTS)
    if readmes:
        for name, it in readmes:
            if name in ("readme_en.md", "readme_vi.md", "readme_vi_vn.md"):
                return it.get("path")
        return readmes[0][1].get("path")
    return None


def read_target(t, path, ref):
    if not path:
        data, problem = api_get(f"/repos/{t.owner}/{t.repo}/readme", {"ref": ref})
        if problem:
            return err(problem)
        content = data.get("content") or ""
        text = None
        if content:
            try:
                text = base64.b64decode(content).decode("utf-8", "replace")
            except Exception:
                return err("không giải mã được README")
        elif data.get("download_url"):
            text, problem = fetch_raw(data["download_url"])
            if text is None:
                return err(f"README quá lớn để đọc qua API ({fmt_size(data.get('size'))})")
        else:
            return err(f"README quá lớn để đọc qua API ({fmt_size(data.get('size'))})")
        if "\x00" in text[:4000]:
            return err("README là tệp nhị phân — không đọc được")
        return {
            "text": text,
            "path": data.get("path") or "README.md",
            "ref": ref,
            "size": data.get("size") or len(text.encode("utf-8")),
            "sha": data.get("sha") or "",
            "url": data.get("html_url") or file_url(t, ref, data.get("path") or "README.md"),
            "source": "",
        }, None

    path = path.strip("/")
    picked = path
    if is_probably_dir(path):
        items, problem = list_dir(t, path, ref)
        if problem:
            if "là tệp" in problem:
                return fetch_file(t, path, ref)
            return err(problem)
        picked = pick_doc_in_dir(items)
        if not picked:
            names = ", ".join(it.get("name") or "" for it in items[:20])
            return err(f"thư mục không có README/index — có: {names}")
    data, problem = fetch_file(t, picked, ref)
    if not problem:
        return data, None
    if not is_probably_dir(path):
        items, list_problem = list_dir(t, path, ref)
        if not list_problem:
            picked = pick_doc_in_dir(items)
            if picked:
                return fetch_file(t, picked, ref)
    return err(problem)


def doc_files(entries, prefix="", include_all=False):
    prefix = (prefix or "").strip("/")
    out = []
    for it in entries:
        if it["type"] != "blob":
            continue
        path = it["path"]
        if prefix and path != prefix and not path.startswith(prefix + "/"):
            continue
        low = path.lower()
        parts = low.split("/")
        if any(p in SKIP_DIRS for p in parts[:-1]):
            continue
        if not include_all and any(p in LOCALE_DIRS for p in parts[:-1]):
            continue
        name = parts[-1]
        ext = Path(name).suffix
        base = name.rsplit(".", 1)[0]
        is_doc = ext in DOC_EXTS or name in CONFIG_DOCS or \
            (path.count("/") == 0 and base in SPECIAL_DOCS)
        if not include_all and not is_doc:
            continue
        if include_all and ext not in DOC_EXTS | CODE_EXTS and name not in CONFIG_DOCS:
            continue
        out.append(it)
    return out


def doc_rank(item):
    path = item["path"]
    low = path.lower()
    name = low.rsplit("/", 1)[-1]
    base = name.rsplit(".", 1)[0]
    score = path.count("/")
    if path.count("/") == 0 and (name.startswith("readme") or base in SPECIAL_DOCS
                                 or name in CONFIG_DOCS):
        score -= 80
    if name.startswith("readme"):
        score -= 300
    elif base in ("index", "intro", "introduction", "overview"):
        score -= 110
    elif base in SPECIAL_DOCS:
        score -= 80
    if low.startswith(("docs/", "doc/", "documentation/", "website/docs/")):
        score -= 60
    if low.startswith(("examples/", "test/", "tests/", "fixtures/")):
        score += 40
    if name in CONFIG_DOCS:
        score += 30
    if name.endswith((".txt", ".rst")):
        score += 5
    return (score, path)


def search_files(t, ref, items, query, max_matches, context, case_sensitive, workers=8):
    matches = []
    failed = 0
    scanned = 0
    needle = query if case_sensitive else query.lower()
    terms = [x for x in re.split(r"\s+", needle) if x]

    def scan(item):
        path = item["path"]
        if item.get("size") and item["size"] > MAX_FILE_BYTES:
            return path, None, "quá lớn"
        data, problem = fetch_file(t, path, ref)
        if problem:
            return path, None, problem
        lines = data["text"].splitlines()
        found = []
        for i, line in enumerate(lines):
            hay = line if case_sensitive else line.lower()
            hit = needle in hay or (len(terms) > 1 and all(x in hay for x in terms))
            if not hit:
                continue
            start = max(0, i - context)
            end = min(len(lines), i + context + 1)
            snippet = "\n".join(lines[start:end])
            found.append({"line": i + 1, "text": oneline(line.strip(), 300), "snippet": snippet})
            if len(found) >= max_matches:
                break
        return path, data["text"], found

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan, it): it for it in items}
        for fut in as_completed(futures):
            try:
                path, text, found = fut.result()
            except Exception:
                failed += 1
                continue
            if text is None:
                failed += 1
                continue
            scanned += 1
            for m in found or []:
                matches.append({"path": path, **m})
                if len(matches) >= max_matches:
                    break
    matches.sort(key=lambda m: (m["path"], m["line"]))
    return matches[:max_matches], scanned, failed


def parse_lines(value):
    raw = (value or "").strip()
    m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+)?)?", raw)
    if not m:
        raise argparse.ArgumentTypeError("dùng dạng 10-80, 10 hoặc 10-")
    start = int(m.group(1))
    if m.group(2):
        end = int(m.group(2))
    elif "-" in raw:
        end = None
    else:
        end = start
    if start < 1 or (end is not None and end < start):
        raise argparse.ArgumentTypeError("khoảng dòng không hợp lệ")
    return start, end


def print_info(info):
    print(f"# {info['slug']}")
    if info["description"]:
        print(info["description"])
    print()
    stats = [f"{fmt_num(info['stars'])} sao", f"{fmt_num(info['forks'])} fork"]
    if info["watchers"]:
        stats.append(f"{fmt_num(info['watchers'])} theo dõi")
    if info["language"]:
        stats.append(info["language"])
    print("- " + " · ".join(stats))
    print(f"- Nhánh mặc định: {info['default_branch']} · Cập nhật: {fmt_date(info['updated_at'])}")
    if info["license"]:
        print(f"- Giấy phép: {info['license']}")
    if info["topics"]:
        print("- Chủ đề: " + ", ".join(info["topics"][:12]))
    flags = []
    if info["private"]:
        flags.append("private")
    if info["archived"]:
        flags.append("đã lưu trữ")
    if flags:
        print("- Trạng thái: " + ", ".join(flags))
    if info["homepage"]:
        print(f"- Trang chủ: {info['homepage']}")
    print(f"- Repo: {info['html_url']}")
    print(f"- Clone: {info['clone_url']}")
    print(f"- Xem tài liệu: python3 aistv_github_docs.py docs {info['slug']}")


def print_tree(entries, base, max_lines):
    base = (base or "").strip("/")
    shown = 0
    for it in entries:
        path = it["path"]
        if base and path != base and not path.startswith(base + "/"):
            continue
        rel = path[len(base):].lstrip("/") if base else path
        if not rel:
            continue
        depth = rel.count("/")
        name = rel.rsplit("/", 1)[-1]
        pad = "  " * depth
        if it["type"] == "tree":
            print(f"{pad}{name}/")
        else:
            size = f"  ({fmt_size(it['size'])})" if it["size"] else ""
            print(f"{pad}{name}{size}")
        shown += 1
        if shown >= max_lines:
            break
    return shown


def main():
    global REFRESH
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="xuất JSON")
    common.add_argument("--refresh", action="store_true", help="bỏ qua cache")

    ap = argparse.ArgumentParser(
        prog="aistv_github_docs.py",
        description="Đọc tài liệu GitHub: repo, cây tệp, README, docs, tìm kiếm.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", parents=[common], help="thông tin repo")
    p.add_argument("target", help="owner/repo hoặc link GitHub")

    p = sub.add_parser("tree", parents=[common], help="cây tệp/thư mục")
    p.add_argument("target")
    p.add_argument("-p", "--path", default="", help="thư mục con")
    p.add_argument("-d", "--depth", type=int, default=2, help="độ sâu (0 = tất cả)")
    p.add_argument("--ref", default="", help="nhánh/tag/commit")
    p.add_argument("--max", type=int, default=500, help="số dòng tối đa")

    p = sub.add_parser("read", parents=[common], help="đọc README/tệp tài liệu")
    p.add_argument("target")
    p.add_argument("path", nargs="?", default="", help="đường dẫn tệp/thư mục (bỏ trống = README)")
    p.add_argument("--ref", default="")
    p.add_argument("--max-chars", type=int, default=12000, help="0 = không cắt")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--outline", action="store_true", help="chỉ liệt kê tiêu đề")
    mode.add_argument("--section", default="", help="chỉ lấy một mục theo tiêu đề")
    mode.add_argument("--lines", type=parse_lines, help="chỉ lấy khoảng dòng, vd 10-80")

    p = sub.add_parser("docs", parents=[common], help="liệt kê tệp tài liệu")
    p.add_argument("target")
    p.add_argument("-p", "--path", default="", help="chỉ trong thư mục này")
    p.add_argument("--ref", default="")
    p.add_argument("-n", "--limit", type=int, default=60)
    p.add_argument("--all", action="store_true", help="gồm cả mã nguồn")

    p = sub.add_parser("search", parents=[common], help="tìm trong tài liệu")
    p.add_argument("target")
    p.add_argument("query")
    p.add_argument("--ref", default="")
    p.add_argument("-n", "--max", type=int, default=30, help="số kết quả tối đa")
    p.add_argument("--files", type=int, default=60, help="số tệp quét tối đa")
    p.add_argument("-C", "--context", type=int, default=0, help="số dòng ngữ cảnh")
    p.add_argument("--case", action="store_true", help="phân biệt hoa thường")
    p.add_argument("--all", action="store_true", help="quét cả mã nguồn")

    p = sub.add_parser("code", parents=[common], help="tìm trong mã (GitHub code search)")
    p.add_argument("target")
    p.add_argument("query")
    p.add_argument("-n", "--limit", type=int, default=20)

    p = sub.add_parser("find", parents=[common], help="tìm repo trên GitHub")
    p.add_argument("query")
    p.add_argument("-n", "--limit", type=int, default=8)
    p.add_argument("--owner", default="", help="giới hạn theo user/org")

    p = sub.add_parser("repos", parents=[common], help="repo của tài khoản đã kết nối")
    p.add_argument("-n", "--limit", type=int, default=30)

    p = sub.add_parser("releases", parents=[common], help="bản phát hành gần đây")
    p.add_argument("target")
    p.add_argument("-n", "--limit", type=int, default=5)

    args = ap.parse_args()
    REFRESH = bool(args.refresh)
    if args.cmd in ("search", "code", "find") and not args.query.strip():
        print("Lỗi: từ khoá không được để trống", file=sys.stderr)
        return 1

    if args.cmd == "info":
        t, problem = parse_target(args.target)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        info, problem = repo_info(t)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print_info(info)
        return 0

    if args.cmd == "tree":
        t, problem = parse_target(args.target, args.ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        ref, problem = default_ref(t)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        tree, problem = get_tree(t, ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        entries = tree["entries"]
        base = (args.path or t.path).strip("/")
        if base and any(e["type"] == "blob" and e["path"] == base for e in entries):
            print(f"Lỗi: “{base}” là tệp — dùng lệnh read để đọc", file=sys.stderr)
            return 1
        if base and not any(e["path"] == base or e["path"].startswith(base + "/")
                            for e in entries):
            print(f"Lỗi: không thấy thư mục “{base}” trong {t.slug}@{ref}", file=sys.stderr)
            return 1
        selected = []
        for e in entries:
            path = e["path"]
            if base and path != base and not path.startswith(base + "/"):
                continue
            rel = path[len(base):].lstrip("/") if base else path
            if not rel:
                continue
            if args.depth > 0:
                depth = rel.count("/")
                if e["type"] == "tree" and depth >= args.depth:
                    continue
                if e["type"] == "blob" and depth > args.depth:
                    continue
            selected.append(e)
        total = len(selected)
        shown = min(total, max(1, args.max))
        if args.json:
            print(json.dumps({"repo": t.slug, "ref": ref, "path": base,
                              "entries": selected[:shown], "total": total,
                              "truncated": total > shown or tree["truncated"]},
                             ensure_ascii=False, indent=2))
        else:
            print(f"# {t.slug} @ {ref}" + (f" · {base}/" if base else ""))
            print_tree(selected[:shown], base, shown)
            if total > shown:
                print(f"\n[... hiển thị {shown}/{total} mục — tăng --max hoặc dùng --path]")
            elif tree["truncated"]:
                print("\n[GitHub cắt bớt danh sách vì repo quá lớn]")
        return 0

    if args.cmd == "read":
        t, problem = parse_target(args.target, args.ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        if args.path:
            t.path = args.path
        ref, problem = default_ref(t)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        data, problem = read_target(t, t.path, ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        text = data["text"]
        result = {
            "repo": t.slug,
            "ref": ref,
            "path": data["path"],
            "url": data["url"],
            "size": data["size"],
            "sha": data["sha"],
        }
        if args.outline:
            items = parse_headings(text)
            if args.json:
                result["outline"] = items
                result["text"] = text
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"# Cấu trúc: {data['path']} ({t.slug}@{ref})")
                for h in items:
                    print(f"{h['line']:>5}  {'  ' * (h['level'] - 1)}{'#' * h['level']} {h['title']}")
                print(f"\nNguồn: {data['url']}")
            return 0

        if args.section:
            picked, title, names = section_text(text, args.section)
            if picked is None:
                hint = ", ".join(names[:12]) if names else "không có tiêu đề"
                print(f"Lỗi: không thấy mục “{args.section}”. Có: {hint}", file=sys.stderr)
                return 1
            text = picked
            result["section"] = title

        if args.lines:
            start, end = args.lines
            lines = text.splitlines()
            if start > len(lines):
                print(f"Lỗi: tệp chỉ có {len(lines)} dòng", file=sys.stderr)
                return 1
            stop = min(end or len(lines), len(lines))
            text = "\n".join(lines[start - 1:stop])
            result["lines"] = [start, stop]

        original_len = len(text)
        text, truncated = truncate_text(text, args.max_chars)
        result.update({"text": text, "chars": len(text), "full_chars": original_len,
                       "truncated": truncated})
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(text)
            print(f"\nNguồn: {data['url']} ({ref})")
        return 0

    if args.cmd == "docs":
        t, problem = parse_target(args.target, args.ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        ref, problem = default_ref(t)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        tree, problem = get_tree(t, ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        prefix = args.path or t.path
        items = doc_files(tree["entries"], prefix, args.all)
        items.sort(key=doc_rank)
        items = items[: max(1, args.limit)]
        out = [{"path": it["path"], "size": it["size"]} for it in items]
        if args.json:
            print(json.dumps({"repo": t.slug, "ref": ref, "path": prefix,
                              "items": out}, ensure_ascii=False, indent=2))
        else:
            print(f"# Tài liệu {t.slug} @ {ref}" + (f" · {prefix}/" if prefix else ""))
            if not out:
                print("Không tìm thấy tệp tài liệu. Thử --all hoặc dùng tree.")
            for it in out:
                print(f"- {it['path']}" + (f" ({fmt_size(it['size'])})" if it["size"] else ""))
            print(f"\nĐọc: python3 aistv_github_docs.py read {t.slug} <đường-dẫn>")
        return 0

    if args.cmd == "search":
        t, problem = parse_target(args.target, args.ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        ref, problem = default_ref(t)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        tree, problem = get_tree(t, ref)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        items = doc_files(tree["entries"], t.path, args.all)
        items.sort(key=doc_rank)
        items = items[: max(1, args.files)]
        matches, scanned, failed = search_files(
            t, ref, items, args.query, max(1, args.max), max(0, args.context), args.case)
        if args.json:
            print(json.dumps({"repo": t.slug, "ref": ref, "query": args.query,
                              "path": t.path,
                              "matches": matches, "files_scanned": scanned,
                              "files_failed": failed}, ensure_ascii=False, indent=2))
        else:
            print(f"# Tìm “{args.query}” trong {t.slug} @ {ref}"
                  + (f" · {t.path}/" if t.path else ""))
            print(f"Đã quét {scanned} tệp" + (f" ({failed} tệp lỗi)" if failed else "") + ".")
            if not matches:
                print("\nKhông thấy kết quả. Thử thêm --all (quét cả mã) hoặc lệnh code.")
            for m in matches:
                print(f"\n{m['path']}:{m['line']}")
                if args.context:
                    for line in m["snippet"].splitlines():
                        print(f"    {oneline(line, 240)}")
                else:
                    print(f"    {m['text']}")
            print(f"\nNguồn: https://github.com/{t.slug}/tree/{ref}")
        return 0

    if args.cmd == "code":
        if not TOKEN:
            print("Lỗi: tìm trong mã cần token GitHub — dùng /github login trước.", file=sys.stderr)
            return 1
        t, problem = parse_target(args.target)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        q = f"{args.query} repo:{t.slug}"
        data, problem = api_get("/search/code", {
            "q": q, "per_page": max(1, min(args.limit, 50))},
            accept="application/vnd.github.text-match+json")
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        out = []
        for item in data.get("items") or []:
            frags = []
            for tm in item.get("text_matches") or []:
                frag = tm.get("fragment") or ""
                if frag:
                    frags.append(oneline(frag, 500))
            out.append({
                "path": item.get("path") or "",
                "url": item.get("html_url") or "",
                "fragments": frags[:3],
            })
        if args.json:
            print(json.dumps({"repo": t.slug, "query": args.query,
                              "total": data.get("total_count") or 0, "items": out},
                             ensure_ascii=False, indent=2))
        else:
            print(f"# Mã khớp “{args.query}” trong {t.slug}")
            print(f"Tổng: {data.get('total_count') or 0} · hiển thị {len(out)}")
            if not out:
                print("\nKhông thấy. Thử search (tài liệu) hoặc từ khoá ngắn hơn.")
            for it in out:
                print(f"\n{it['path']}")
                for frag in it["fragments"]:
                    print(f"    {frag}")
                if it["url"]:
                    print(f"    {it['url']}")
        return 0

    if args.cmd == "find":
        q = args.query.strip()
        if args.owner:
            q += f" user:{args.owner.strip()}"
        data, problem = api_get("/search/repositories", {
            "q": q, "sort": "stars", "order": "desc",
            "per_page": max(1, min(args.limit, 50))})
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        out = []
        for r in data.get("items") or []:
            out.append({
                "repo": r.get("full_name") or "",
                "description": r.get("description") or "",
                "stars": r.get("stargazers_count") or 0,
                "language": r.get("language") or "",
                "updated_at": r.get("updated_at") or "",
                "url": r.get("html_url") or "",
                "private": bool(r.get("private")),
            })
        if args.json:
            print(json.dumps({"query": args.query, "items": out}, ensure_ascii=False, indent=2))
        else:
            print(f"# Repo cho “{args.query}”")
            if not out:
                print("Không tìm thấy repo nào.")
            for n, it in enumerate(out, 1):
                bits = [f"{fmt_num(it['stars'])} sao"]
                if it["language"]:
                    bits.append(it["language"])
                print(f"\n{n}. {it['repo']} · " + " · ".join(bits))
                if it["description"]:
                    print(f"   {oneline(it['description'], 220)}")
                print(f"   {it['url']}")
        return 0

    if args.cmd == "repos":
        if not TOKEN:
            print("Lỗi: cần token GitHub — dùng /github login trước.", file=sys.stderr)
            return 1
        data, problem = api_get("/user/repos", {
            "per_page": max(1, min(args.limit, 100)), "sort": "updated",
            "affiliation": "owner,collaborator,organization_member"})
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        out = []
        for r in data if isinstance(data, list) else []:
            out.append({
                "repo": r.get("full_name") or "",
                "description": r.get("description") or "",
                "stars": r.get("stargazers_count") or 0,
                "language": r.get("language") or "",
                "updated_at": r.get("updated_at") or "",
                "url": r.get("html_url") or "",
                "private": bool(r.get("private")),
            })
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("# Repo của tài khoản")
            if not out:
                print("Không có repo nào.")
            for n, it in enumerate(out, 1):
                bits = [f"{fmt_num(it['stars'])} sao"]
                if it["language"]:
                    bits.append(it["language"])
                if it["private"]:
                    bits.append("private")
                print(f"\n{n}. {it['repo']} · " + " · ".join(bits))
                if it["description"]:
                    print(f"   {oneline(it['description'], 200)}")
                print(f"   {it['url']}")
        return 0

    if args.cmd == "releases":
        t, problem = parse_target(args.target)
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        data, problem = api_get(f"/repos/{t.owner}/{t.repo}/releases",
                                {"per_page": max(1, min(args.limit, 30))})
        if problem:
            print(f"Lỗi: {problem}", file=sys.stderr)
            return 1
        out = []
        for r in data if isinstance(data, list) else []:
            out.append({
                "tag": r.get("tag_name") or "",
                "name": r.get("name") or "",
                "published_at": r.get("published_at") or "",
                "prerelease": bool(r.get("prerelease")),
                "url": r.get("html_url") or "",
                "body": oneline(r.get("body") or "", 1500),
            })
        if args.json:
            print(json.dumps({"repo": t.slug, "releases": out}, ensure_ascii=False, indent=2))
        else:
            print(f"# Bản phát hành {t.slug}")
            if not out:
                print("Chưa có bản phát hành nào.")
            for r in out:
                flags = " [prerelease]" if r["prerelease"] else ""
                print(f"\n## {r['tag']}{flags} — {r['name'] or ''}".rstrip(" —"))
                print(f"{fmt_date(r['published_at'])} · {r['url']}")
                if r["body"]:
                    print(r["body"][:1200])
        return 0

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
