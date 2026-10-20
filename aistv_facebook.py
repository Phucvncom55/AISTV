#!/usr/bin/env python3
"""AI STV Facebook helper: đọc bài viết, xem/tải video, tìm kiếm."""

import argparse
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
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TIMEOUT = 90
READER = "https://r.jina.ai/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FB_HOSTS = ("facebook.com", "fb.com", "fb.watch", "fb.me")
DROP_PARAMS = {
    "__cft__", "__tn__", "mibextid", "rdid", "share_url", "sfnsn", "ref", "refid",
    "_rdr", "paipv", "eav", "hc_ref", "fref", "__xts__", "comment_id",
    "reply_comment_id", "notif_id", "notif_t", "acontext",
}
VIDEO_RE = re.compile(
    r"(?:^|/)(?:reel|reels|videos?|video\.php|watch|share/[vr])(?:/|$)|fb\.watch/", re.I
)
LOGIN_MARKERS = (
    "log into facebook",
    "email or mobile number",
    "email or phone number",
    "create new account",
)


def ytdlp():
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    local = Path(sys.executable).with_name("yt-dlp")
    if local.exists():
        return [str(local)]
    here = Path(__file__).resolve().parent
    for rel in (".venv/bin/yt-dlp", ".venv/Scripts/yt-dlp.exe", ".venv/Scripts/yt-dlp"):
        cand = here / rel
        if cand.exists():
            return [str(cand)]
    return [sys.executable, "-m", "yt_dlp"]


def run_yt(args, timeout=TIMEOUT):
    cmd = ytdlp() + ["--no-warnings", "--socket-timeout", "20", "--retries", "2"]
    cookies = os.environ.get("FB_COOKIES")
    if cookies and Path(cookies).is_file():
        cmd += ["--cookies", cookies]
    try:
        p = subprocess.run(cmd + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "yt-dlp quá thời gian chờ"
    except FileNotFoundError:
        return None, "chưa cài yt-dlp (pip install yt-dlp)"
    if p.returncode != 0:
        lines = (p.stderr or p.stdout or "").strip().splitlines()
        msg = lines[-1] if lines else "yt-dlp lỗi không rõ"
        return None, re.sub(r"^ERROR:\s*", "", msg)
    return p.stdout, None


def load_yt_json(args):
    out, err = run_yt(args)
    if err:
        return None, err
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, "không đọc được dữ liệu từ yt-dlp"


def clean_url(url):
    raw = (url or "").strip().strip("<>\"'")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k not in DROP_PARAMS and not k.startswith("__")]
    netloc = parts.netloc.replace("mbasic.", "www.").replace("m.", "www.")
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path,
                                    urllib.parse.urlencode(query), ""))


def is_fb(url):
    host = (urllib.parse.urlsplit(clean_url(url)).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in FB_HOSTS)


def is_video(url):
    parts = urllib.parse.urlsplit(clean_url(url))
    return bool(VIDEO_RE.search(parts.path + "/") or "fb.watch" in parts.netloc.lower())


def fetch(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/plain"})
    key = os.environ.get("JINA_API_KEY")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return None, f"HTTP {e.code} {body}".strip()
    except Exception as e:
        return None, str(e)


def read_reader(page_url):
    err = None
    for attempt in range(2):
        text, err = fetch(READER + clean_url(page_url))
        if text:
            return text, None
        if err and ("429" in err or "403" in err or "timed out" in err):
            time.sleep(2 + attempt * 2)
            continue
        return None, err
    return None, err


def unwrap_links(text):
    def repl(m):
        label, url = m.group(1).strip(), m.group(2).strip()
        url = re.sub(r"[?&](?:__cft__|__tn__)[^\s&)]*", "", url)
        if not label:
            return ""
        if url.startswith("/") or "facebook.com" in url or "fb.watch" in url:
            return label
        if url in label:
            return label
        return f"{label} ({url})"

    return re.sub(r"\[([^\]]*)\]\(([^)]*)\)", repl, text)


def clean_body(body):
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s).strip()
        if not s or re.match(r"^\[?\]\([^)]*\)$", s):
            continue
        if re.match(r"^#{1,3} .*'s Post$", s):
            continue
        if s in {"* * *", "---", "·", "Follow", "See more", "See more on Facebook",
                 "Log In", "Password", "Email or phone number", "Email or mobile number",
                 "Like", "Comment", "Sorry, we're having trouble playing this video.",
                 "Learn more", "All reactions:", "Log In", "Forgot Account?", "Forgot password?"}:
            continue
        if re.match(r"^\[(?:Log In|Forgot Account\?|Forgot password\?|Learn more)\]\([^)]*\)$", s):
            continue
        lines.append(re.sub(r"\s*·\s*$", "", s))

    text = "\n".join(lines)
    text = unwrap_links(text)
    text = re.sub(r"\[([^\]]*)\]\((?:https?:)?//[^)]*\)", r"\1", text)
    text = re.sub(r"https?://(?:www\.|m\.|web\.)?facebook\.com/[^\s)\]]*?"
                  r"(?:[?&](?:__cft__|__tn__))[^\s)\]]*", "", text)
    text = re.sub(r"\(https?://(?:www\.|m\.)?facebook\.com/[^)]*\)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(\d[\d.,]*[KMB]?)\n\n(\d[\d.,]*[KMB]? comments)\n\n(\d[\d.,]*[KMB]? shares)",
                  r"\1 · \2 · \3", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_reader(raw, page_url, comments=False):
    title, body = "", raw
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Title:"):
            title = line[6:].strip()
        elif line.startswith("Markdown Content:"):
            body = "\n".join(lines[i + 1:])
            break
    low = body.lower()
    wall = sum(1 for m in LOGIN_MARKERS if m in low) >= 2
    text = clean_body(body)
    if wall and len(text) < 500:
        return None, ("Facebook chặn xem khi chưa đăng nhập (trang cá nhân, nhóm, feed). "
                      "Chỉ đọc được bài/video công khai.")
    if not comments:
        for marker in ("\nMost relevant\n", "\nComments\n"):
            idx = text.find(marker)
            if idx > 0:
                text = text[:idx].rstrip()
                break
    if not text:
        return None, "không đọc được nội dung (bài bị xoá, riêng tư hoặc Facebook chặn)"
    generic = (not title or title == "Facebook" or title.endswith(("'s Post", "'s post")))
    if generic:
        content = [l.strip() for l in text.splitlines()
                   if l.strip() and not l.startswith("#")
                   and not re.match(r"^(?:\w+ \d{1,2}, \d{4}|\d{1,2}/\d{1,2}/\d{4}|\d+ \w+ \d{4})$",
                                    l.strip().rstrip(" ·"))]
        title = content[0][:120] if content else "Facebook"
        if content:
            text = "\n".join(
                l for l in text.splitlines()
                if l.strip() != content[0] and not re.match(r"^#{1,3} .*'s Post$", l.strip())
            ).strip()
    return {"url": clean_url(page_url), "title": title, "text": text}, None


def fmt_duration(sec):
    if not sec:
        return "?"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_views(n):
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def video_info(url):
    data, err = load_yt_json(["--skip-download", "--no-playlist", "--dump-single-json", url])
    if err:
        return None, err
    title = re.sub(r"^\s*[\d.,]+[KMB]?\s*views\s*·\s*[\d.,]+[KMB]?\s*reactions\s*\|\s*",
                   "", data.get("title") or "", flags=re.I)
    uploader = data.get("uploader") or data.get("channel") or ""
    if uploader and title.endswith(" | " + uploader):
        title = title[:-len(" | " + uploader)]
    return {
        "type": "video",
        "id": data.get("id"),
        "title": title or data.get("title") or "(không tiêu đề)",
        "uploader": uploader,
        "duration": data.get("duration"),
        "views": data.get("view_count"),
        "likes": data.get("like_count"),
        "comments": data.get("comment_count"),
        "description": (data.get("description") or "").strip(),
        "thumbnail": data.get("thumbnail"),
        "url": clean_url(data.get("webpage_url") or url),
    }, None


def info(url):
    if not is_fb(url):
        return None, "chỉ hỗ trợ link Facebook (facebook.com, fb.watch, fb.com)"
    if is_video(url):
        data, err = video_info(url)
        if not err:
            return data, None
    page, err = read_reader(url)
    if err:
        return None, err
    data, err = parse_reader(page, url)
    if err:
        return None, err
    data["type"] = "post"
    return data, None


def search(query, limit, site):
    q = query.strip()
    if site and "site:" not in q.lower():
        q = f"site:facebook.com {q}"
    target = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote_plus(q)
    raw, err = None, None
    for attempt in range(2):
        raw, err = fetch(READER + target)
        if raw:
            break
        time.sleep(2 + attempt * 2)
    if not raw:
        return None, err or "không tìm được"
    items, current = [], None
    for line in raw.splitlines():
        m = re.match(r"^\s*\d+\.\s*\[(.*?)\]\((\S+)\)\s*$", line)
        if m:
            if current:
                items.append(current)
            link = m.group(2)
            if "duckduckgo.com/l/" in link:
                qs = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)
                link = (qs.get("uddg") or [link])[0]
            current = {"title": m.group(1).replace("****", " ").replace("**", "").strip(),
                       "url": link, "snippet": ""}
            continue
        if current is not None and line.strip() and not line.startswith("["):
            if not current["snippet"] and not line.strip().startswith("http"):
                current["snippet"] = line.replace("****", " ").replace("**", "").strip()
    if current:
        items.append(current)
    items = [x for x in items if is_fb(x["url"])][:limit]
    return items, None


def download(url, quality, out_dir, max_mb):
    if not is_fb(url):
        return None, "chỉ hỗ trợ link Facebook"
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    fmt = "hd/best" if quality == "hd" else "sd/best[height<=480]/best"
    before = {p.name for p in out.iterdir()}
    args = [
        "--no-playlist", "-f", fmt, "--max-filesize", f"{max_mb}M",
        "--force-overwrites", "--no-mtime", "-o", str(out / "fb_%(id)s_%(format_id)s.%(ext)s"), url,
    ]
    _, err = run_yt(args, timeout=600)
    files = [p for p in out.iterdir() if p.is_file() and p.name not in before]
    if not files and err:
        return None, err
    if not files:
        return None, "không tải được video"
    path = max(files, key=lambda p: p.stat().st_size)
    size = path.stat().st_size
    data = {"path": str(path), "size": size, "url": clean_url(url)}
    if size > 45 * 1024 * 1024:
        data["warning"] = "file lớn hơn 45MB, Telegram bot không gửi được"
    return data, None


def print_post(data, limit=None):
    print(data["title"])
    print(data["url"])
    print()
    text = data["text"]
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "\n[... cắt bớt]"
    print(text)


def main():
    ap = argparse.ArgumentParser(description="Đọc bài viết, xem/tải video, tìm kiếm trên Facebook")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("info", help="thông tin bài viết/video")
    i.add_argument("url")
    i.add_argument("--json", action="store_true")

    r = sub.add_parser("read", help="đọc nội dung bài viết")
    r.add_argument("url")
    r.add_argument("-n", "--max-chars", type=int, default=12000)
    r.add_argument("--comments", action="store_true", help="kèm bình luận")
    r.add_argument("--json", action="store_true")

    d = sub.add_parser("download", help="tải video/reel")
    d.add_argument("url")
    d.add_argument("-q", "--quality", choices=("sd", "hd"), default="sd")
    d.add_argument("-o", "--out", default=".")
    d.add_argument("--max-mb", type=int, default=40)
    d.add_argument("--json", action="store_true")

    s = sub.add_parser("search", help="tìm bài/video Facebook")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=8)
    s.add_argument("--all", action="store_true", help="tìm cả web, không giới hạn facebook.com")
    s.add_argument("--json", action="store_true")

    args = ap.parse_args()

    if args.cmd == "info":
        data, err = info(args.url)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        elif data["type"] == "video":
            print(data["title"])
            bits = [data["uploader"]]
            if data["duration"]:
                bits.append(fmt_duration(data["duration"]))
            if data["views"]:
                bits.append(f"{fmt_views(data['views'])} lượt xem")
            print(" · ".join(x for x in bits if x))
            print(data["url"])
            if data["description"]:
                print("\nMô tả:")
                print(data["description"][:1500])
        else:
            print_post(data, limit=1500)
        return 0

    if args.cmd == "read":
        if not is_fb(args.url):
            print("Lỗi: chỉ hỗ trợ link Facebook", file=sys.stderr)
            return 1
        page, err = read_reader(args.url)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        data, err = parse_reader(page, args.url, comments=args.comments)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        text = data["text"]
        truncated = False
        if args.max_chars and len(text) > args.max_chars:
            text = text[:args.max_chars].rsplit(" ", 1)[0] + "\n[... cắt bớt]"
            truncated = True
        if args.json:
            print(json.dumps({**data, "text": text, "truncated": truncated},
                             ensure_ascii=False, indent=2))
        else:
            print(f"# {data['title']}\n")
            print(text)
        return 0

    if args.cmd == "download":
        data, err = download(args.url, args.quality, args.out, args.max_mb)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            mb = data["size"] / (1024 * 1024)
            print(f"Đã tải: {data['path']} ({mb:.1f} MB)")
            if data.get("warning"):
                print(f"Lưu ý: {data['warning']}")
        return 0

    items, err = search(args.query, args.limit, site=not args.all)
    if err:
        print(f"Lỗi: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        if not items:
            print("Không tìm thấy kết quả nào.")
            return 0
        for n, it in enumerate(items, 1):
            print(f"{n}. {it['title']}")
            if it["snippet"]:
                print(f"   {it['snippet'][:180]}")
            print(f"   {it['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
