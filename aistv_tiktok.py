#!/usr/bin/env python3
"""AI STV TikTok helper: xem thông tin, tải video không watermark, tìm kiếm.

Hỗ trợ link thường, link rút gọn (vt./vm.) và link TikTok Lite
(lite.tiktok.com/t/...). Link Lite dạng mời/nhận thưởng sẽ được báo rõ
là không phải video.
"""

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
TT_HOSTS = ("tiktok.com", "tiktokv.com")
DROP_PARAMS = {
    "is_from_webapp", "sender_device", "web_id", "u_code", "sharer_language",
    "share_item_id", "share_app_id", "share_link_id", "share_time", "share_type",
    "social_share_type", "utm_source", "utm_medium", "utm_campaign", "utm_content",
    "utm_term", "ref", "refer", "referer", "source", "_r", "_d", "_pia_", "_svg",
    "checksum", "timestamp", "language", "enter_from", "extra_params",
    "redirect_from", "from", "is_copy_url", "is_from_webapp",
}
VIDEO_RE = re.compile(r"/(?:@[^/?#]+/)?video/(\d{6,})")
PHOTO_RE = re.compile(r"/(?:@[^/?#]+/)?photo/(\d{6,})")
OLD_VIDEO_RE = re.compile(r"/v/(\d{6,})\.html")
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
BARE_URL_RE = re.compile(
    r"(?<![\w.-])((?:[\w-]+\.)*(?:tiktok|tiktokv)\.com/[^\s<>\"']*)", re.I
)


class TikTokError(Exception):
    pass


class HttpResult:
    def __init__(self, status, headers, url, content):
        self.status_code = status
        self.headers = {str(k).lower(): v for k, v in dict(headers).items()}
        self.url = url
        self.content = content

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")


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
    cookies = os.environ.get("TIKTOK_COOKIES") or os.environ.get("TT_COOKIES")
    if cookies and Path(cookies).expanduser().is_file():
        cmd += ["--cookies", str(Path(cookies).expanduser())]
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


def _request(url, timeout=30, allow_redirects=True):
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome", timeout=timeout,
                     allow_redirects=allow_redirects,
                     headers={"Accept-Language": "en-US,en;q=0.9"})
        return HttpResult(r.status_code, r.headers, str(r.url), r.content)
    except ImportError:
        pass
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return HttpResult(r.status, r.headers, r.geturl(), r.read())
    except urllib.error.HTTPError as e:
        return HttpResult(e.code, e.headers, e.geturl() or url, e.read())


def _text(url, timeout=60):
    key = os.environ.get("JINA_API_KEY")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/plain"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def extract_url(text):
    raw = (text or "").strip().strip("<>\"'")
    m = URL_RE.search(raw)
    if m:
        raw = m.group(0)
    else:
        m = BARE_URL_RE.search(raw)
        if m:
            raw = "https://" + m.group(1)
    return raw.rstrip(".,;:!?)]}")


def clean_url(url):
    raw = extract_url(url)
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host.startswith("m."):
        host = "www." + host[2:]
    elif host == "tiktok.com":
        host = "www.tiktok.com"
    if host.startswith("lite."):
        probe = parts.path + "?" + parts.query
        if VIDEO_RE.search(probe) or PHOTO_RE.search(probe):
            host = "www.tiktok.com"
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in DROP_PARAMS and not k.startswith("__")]
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    return urllib.parse.urlunsplit(("https", host + (":" + str(parts.port) if parts.port else ""),
                                    path, urllib.parse.urlencode(query), ""))


def is_tt(url):
    host = (urllib.parse.urlsplit(clean_url(url)).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in TT_HOSTS)


def video_id(url):
    parts = urllib.parse.urlsplit(url)
    for regex in (VIDEO_RE, OLD_VIDEO_RE):
        m = regex.search(parts.path)
        if m:
            return m.group(1)
    qs = urllib.parse.parse_qs(parts.query)
    for key in ("item_id", "aweme_id", "video_id"):
        val = (qs.get(key) or [""])[0]
        if val.isdigit():
            return val
    return None


def photo_id(url):
    m = PHOTO_RE.search(urllib.parse.urlsplit(url).path)
    return m.group(1) if m else None


def is_short(url):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return (host.startswith(("vt.", "vm.", "lite."))
            or parts.path.startswith("/t/")
            or parts.path.startswith("/d/1/"))


def canonical(vid):
    return f"https://www.tiktok.com/@/video/{vid}"


def follow(url, hops=6):
    current = url
    last = None
    for _ in range(hops):
        res = _request(current, allow_redirects=False)
        last = res
        loc = res.headers.get("location")
        if res.status_code in (301, 302, 303, 307, 308) and loc:
            current = urllib.parse.urljoin(current, loc)
            continue
        break
    return current, last


def resolve(url):
    raw = clean_url(url)
    if not is_tt(raw):
        raise TikTokError("chỉ hỗ trợ link TikTok (tiktok.com, vt./vm., lite.tiktok.com)")
    if video_id(raw) or photo_id(raw):
        return raw, None

    parts = urllib.parse.urlsplit(raw)
    host = (parts.hostname or "").lower()
    if not is_short(raw):
        return raw, None

    seg = [x for x in parts.path.split("/") if x]
    code = None
    if len(seg) >= 2 and seg[0] in ("t", "d"):
        code = seg[-1]
    candidates = [raw]
    if code:
        if host.startswith("lite."):
            candidates.append(f"https://www.tiktok.com/t/{code}/")
            candidates.append(f"https://www.tiktok.com/d/1/{code}/")
    final = raw
    for cand in candidates:
        try:
            final, res = follow(cand)
        except Exception:
            continue
        if video_id(final) or photo_id(final):
            return clean_url(final), ("lite" if host.startswith("lite.") else "short")
        if res is not None and "404 not found" in (res.text[:100] if res.content else ""):
            continue

    low = final.lower()
    if host.startswith("lite.") and (
            "/ug/incentive/" in low or "shop.tiktok.com" in low or "?_r=1" in low
            or final.rstrip("/") == "https://www.tiktok.com"):
        raise TikTokError(
            "link TikTok Lite này là link mời/nhận thưởng hoặc đã hết hạn, "
            "không phải video. Mở đúng video rồi chọn Chia sẻ → Sao chép liên kết "
            "(dạng tiktok.com/@tên/video/...)."
        )
    if final != raw and not video_id(final) and not photo_id(final):
        if not host.startswith("lite."):
            return raw, "short"
        raise TikTokError("link rút gọn không mở được video (có thể hết hạn hoặc video riêng tư)")
    return raw, "short"


def friendly_error(msg):
    low = (msg or "").lower()
    if "video not available" in low or "status code 100002" in low:
        return "video không khả dụng (đã xoá, riêng tư hoặc bị chặn theo vùng)"
    if "unexpected response from webpage" in low:
        return ("TikTok chặn truy cập từ IP này. Cài curl_cffi "
                "(pip install curl_cffi) hoặc dùng cookie TIKTOK_COOKIES.")
    if "login" in low and ("required" in low or "needed" in low):
        return "video cần đăng nhập (riêng tư/giới hạn tuổi); có thể dùng TIKTOK_COOKIES"
    if "unsupported url" in low:
        return "link này không phải video TikTok được hỗ trợ"
    return msg


def explain_missing(url):
    parts = urllib.parse.urlsplit(url)
    path = parts.path.lower()
    if "/photo/" in path:
        return "đây là bài ảnh/slideshow TikTok; mình mới hỗ trợ video"
    if path.startswith("/@"):
        if path.rstrip("/").count("/") == 1:
            return "link này là trang kênh, không phải video cụ thể"
        return "link này không phải video cụ thể"
    if path.startswith("/tag/"):
        return "link này là trang hashtag, không phải video cụ thể"
    if path.startswith("/music/"):
        return "link này là trang âm thanh, không phải video cụ thể"
    if path.startswith("/search"):
        return "link này là trang tìm kiếm, không phải video cụ thể"
    if "/live" in path:
        return "link live chưa hỗ trợ tải"
    return "link này không phải video TikTok cụ thể"


def fmt_duration(sec):
    if sec is None:
        return "?"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_num(n):
    if n is None:
        return ""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_date(raw):
    if not raw:
        return ""
    if isinstance(raw, (int, float)):
        try:
            return time.strftime("%d/%m/%Y", time.localtime(raw))
        except Exception:
            return ""
    if isinstance(raw, str) and raw.isdigit():
        if len(raw) == 8:
            return f"{raw[6:8]}/{raw[4:6]}/{raw[:4]}"
        try:
            return time.strftime("%d/%m/%Y", time.localtime(int(raw)))
        except Exception:
            return str(raw)
    return str(raw)


def first_line(text, limit=160):
    line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    if len(line) > limit:
        line = line[:limit].rsplit(" ", 1)[0] + "…"
    return line or "(không có mô tả)"


def build_yt(data, url):
    desc = (data.get("description") or data.get("title") or "").strip()
    return {
        "type": "video",
        "id": data.get("id"),
        "title": first_line(desc),
        "description": desc,
        "author": data.get("channel") or data.get("uploader") or "",
        "username": data.get("uploader") or "",
        "duration": data.get("duration"),
        "views": data.get("view_count"),
        "likes": data.get("like_count"),
        "comments": data.get("comment_count"),
        "shares": data.get("repost_count"),
        "saves": data.get("save_count"),
        "upload_date": fmt_date(data.get("upload_date")),
        "music": " — ".join(x for x in (data.get("track"), data.get("artist")) if x),
        "thumbnail": data.get("thumbnail"),
        "url": (f"https://www.tiktok.com/@{data['uploader']}/video/{data['id']}"
                if data.get("uploader") and data.get("id")
                else data.get("webpage_url") or url),
    }


def parse_item_html(text):
    m = re.search(
        r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        text or "", re.S,
    )
    if not m:
        return None, "TikTok không trả dữ liệu (có thể chặn IP hoặc cần đăng nhập)"
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None, "không đọc được dữ liệu video từ TikTok"
    detail = (data.get("__DEFAULT_SCOPE__") or {}).get("webapp.video-detail") or {}
    status = detail.get("statusCode") or 0
    if status:
        msg = {
            10201: "video bị xoá hoặc không tồn tại",
            10202: "video riêng tư hoặc bị hạn chế",
            10205: "video bị chặn theo khu vực",
            10216: "video riêng tư hoặc bị hạn chế",
        }.get(status, detail.get("statusMsg") or f"TikTok báo lỗi {status}")
        return None, msg
    item = (detail.get("itemInfo") or {}).get("itemStruct") or {}
    if not item:
        return None, "không tìm thấy video (có thể đã xoá hoặc riêng tư)"
    return item, None


def web_item(url):
    try:
        res = _request(url, timeout=45)
    except Exception as e:
        return None, f"không tải được trang TikTok: {e}"
    if res.status_code == 404:
        return None, "video không tồn tại hoặc đã bị xoá"
    if res.status_code >= 400:
        return None, f"TikTok trả lỗi HTTP {res.status_code}"
    return parse_item_html(res.text)


def build_item(item, url):
    author = item.get("author") or {}
    stats = item.get("stats") or {}
    video = item.get("video") or {}
    music = item.get("music") or {}
    desc = (item.get("desc") or "").strip()
    images = ((item.get("imagePost") or {}).get("images") or [])
    kind = "photo" if images else "video"
    first_image = None
    if images:
        first_image = (((images[0].get("imageURL") or {}).get("urlList") or [None])[0])
    data = {
        "type": kind,
        "id": item.get("id"),
        "title": first_line(desc or (item.get("imagePost") or {}).get("title") or ""),
        "description": desc,
        "author": author.get("nickname") or "",
        "username": author.get("uniqueId") or "",
        "duration": video.get("duration") if kind == "video" else None,
        "views": stats.get("playCount"),
        "likes": stats.get("diggCount"),
        "comments": stats.get("commentCount"),
        "shares": stats.get("shareCount"),
        "saves": stats.get("collectCount"),
        "upload_date": fmt_date(item.get("createTime")),
        "music": " — ".join(x for x in (music.get("title"), music.get("authorName")) if x),
        "thumbnail": video.get("cover") or video.get("originCover") or first_image,
        "url": clean_url(url),
        "images": len(images) if images else None,
    }
    return data, item


def info(url):
    try:
        url, _ = resolve(url)
    except TikTokError as e:
        return None, str(e)
    if not is_tt(url):
        return None, "chỉ hỗ trợ link TikTok"
    vid, pid = video_id(url), photo_id(url)
    if not vid and not pid:
        if is_short(url):
            data, serr = load_yt_json(
                ["--skip-download", "--no-playlist", "--dump-single-json", url]
            )
            if not serr:
                return build_yt(data, url), None
            return None, "link rút gọn không mở được video (có thể hết hạn hoặc video riêng tư)"
        return None, explain_missing(url)

    if vid:
        data, err = load_yt_json(
            ["--skip-download", "--no-playlist", "--dump-single-json", canonical(vid)]
        )
        if not err:
            return build_yt(data, url), None

    item, werr = web_item(url)
    if item:
        data, _ = build_item(item, url)
        return data, None
    if vid:
        return None, friendly_error(err) or werr
    return None, werr


def pick_play_url(item):
    video = item.get("video") or {}
    if video.get("playAddr"):
        return video["playAddr"]
    for b in video.get("bitrateInfo") or []:
        urls = ((b.get("PlayAddr") or {}).get("UrlList") or [])
        if urls:
            return urls[0]
    return None


def direct_download(url, out_dir, max_mb):
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    limit = max_mb * 1024 * 1024 if max_mb and max_mb > 0 else None
    headers = {"User-Agent": UA, "Referer": "https://www.tiktok.com/"}
    total = 0
    item = None
    path = None
    try:
        from curl_cffi import requests as creq
        session = creq.Session(impersonate="chrome")
        try:
            page = session.get(url, timeout=45)
            item, err = parse_item_html(page.text)
            if err:
                return None, err
            play = pick_play_url(item)
            if not play:
                return None, "không lấy được link tải trực tiếp từ TikTok"
            path = out / f"tt_{item.get('id') or 'video'}_direct.mp4"
            r = session.get(play, timeout=60, stream=True,
                            headers={**headers, "Referer": url})
            try:
                if r.status_code >= 400:
                    return None, f"TikTok CDN trả lỗi HTTP {r.status_code}"
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024 * 256):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if limit and total > limit:
                            raise TikTokError(f"video lớn hơn {max_mb}MB")
                        f.write(chunk)
            finally:
                r.close()
        finally:
            session.close()
    except TikTokError as e:
        if item:
            (out / f"tt_{item.get('id') or 'video'}_direct.mp4").unlink(missing_ok=True)
        return None, str(e)
    except ImportError:
        item, err = web_item(url)
        if err:
            return None, err
        play = pick_play_url(item)
        if not play:
            return None, "không lấy được link tải trực tiếp từ TikTok"
        path = out / f"tt_{item.get('id') or 'video'}_direct.mp4"
        req = urllib.request.Request(play, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    total += len(chunk)
                    if limit and total > limit:
                        raise TikTokError(f"video lớn hơn {max_mb}MB")
                    f.write(chunk)
        except TikTokError as e:
            path.unlink(missing_ok=True)
            return None, str(e)
        except Exception as e:
            path.unlink(missing_ok=True)
            return None, str(e)
    except Exception as e:
        if path:
            path.unlink(missing_ok=True)
        return None, str(e)
    if not path or not path.exists() or path.stat().st_size == 0:
        return None, "không tải được video"
    return {
        "path": str(path), "size": path.stat().st_size, "url": url,
        "quality": "direct", "format": "mp4", "fallback": True,
    }, None


def download(url, quality, audio, out_dir, max_mb, prefer_h264=False):
    try:
        url, _ = resolve(url)
    except TikTokError as e:
        return None, str(e)
    if not is_tt(url):
        return None, "chỉ hỗ trợ link TikTok"
    vid, pid = video_id(url), photo_id(url)
    if pid:
        return None, "bài ảnh/slideshow chưa hỗ trợ tải bằng video"
    if not vid and not is_short(url):
        return None, explain_missing(url)

    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in out.iterdir()}
    target = canonical(vid) if vid else url
    args = ["--no-playlist", "--force-overwrites", "--no-mtime"]
    if max_mb and max_mb > 0:
        args += ["--max-filesize", f"{max_mb}M"]

    if audio:
        fmt = "audio/bestaudio/best"
        outtmpl = str(out / "tt_%(id)s_audio.%(ext)s")
    else:
        if quality == "sd":
            fmt = "bv*[height<=1280][format_id!=download]+ba/b[height<=1280][format_id!=download]/b"
        elif quality == "h264" or prefer_h264:
            fmt = "bv*[vcodec^=h264][format_id!=download]+ba/b[format_id!=download]/b"
        else:
            fmt = "bv*[format_id!=download]+ba/b[format_id!=download]/b"
        outtmpl = str(out / "tt_%(id)s_%(format_id)s.%(ext)s")

    args += ["-f", fmt, "-o", outtmpl, target]
    started = time.time()
    output, err = run_yt(args, timeout=600)
    files = [p for p in out.iterdir() if p.is_file() and p.name not in before]
    if not files and vid:
        files = [p for p in out.iterdir()
                 if p.is_file() and p.name.startswith(f"tt_{vid}_")
                 and p.stat().st_mtime >= started - 1]
    if not files and "larger than max-filesize" in (output or "").lower():
        return None, f"video lớn hơn {max_mb}MB (bot Telegram chỉ gửi được file ≤45MB)"
    if not files and err:
        low = err.lower()
        if "larger than max-filesize" in low or "max-filesize" in low:
            return None, f"video lớn hơn {max_mb}MB (bot Telegram chỉ gửi được file ≤45MB)"
        if not audio:
            fallback, ferr = direct_download(url, out, max_mb)
            if fallback:
                return fallback, None
            base = friendly_error(err)
            return None, base if not ferr else f"{base} · {ferr}"
        return None, friendly_error(err)
    if not files:
        return None, "không tải được video"
    path = max(files, key=lambda p: p.stat().st_size)
    size = path.stat().st_size
    data = {
        "path": str(path), "size": size, "url": url, "audio": audio,
        "quality": "audio" if audio else quality,
        "format": path.suffix.lstrip("."),
    }
    if size > 45 * 1024 * 1024:
        data["warning"] = "file lớn hơn 45MB, Telegram bot không gửi được"
    return data, None


def search_one(query, want):
    target = READER + "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote_plus(query)
    text = None
    err = None
    for attempt in range(2):
        try:
            text = _text(target)
            break
        except Exception as e:
            err = str(e)
            time.sleep(2 + attempt * 2)
    if not text:
        return None, err or "không tìm được"

    items, current = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\.\s*\[(.*?)\]\((\S+)\)\s*$", line)
        if m:
            if current:
                items.append(current)
            link = m.group(2)
            if "duckduckgo.com/l/" in link:
                qs = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)
                link = (qs.get("uddg") or [link])[0]
            current = {
                "title": m.group(1).replace("****", " ").replace("**", "").strip(),
                "url": clean_url(link),
                "snippet": "",
            }
            continue
        if current is not None and line.strip() and not line.startswith("["):
            if not current["snippet"] and not line.strip().startswith("http"):
                current["snippet"] = line.replace("****", " ").replace("**", "").strip()
    if current:
        items.append(current)
    return items, None


def search(query, limit):
    q = query.strip()
    items, err = search_one(f'site:tiktok.com "@" {q} video', limit)
    if err and not items:
        return None, err
    found = []
    seen = set()
    for it in items or []:
        url = it["url"]
        if not is_tt(url):
            continue
        vid, pid = video_id(url), photo_id(url)
        if not vid and not pid:
            continue
        key = vid or pid
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "id": key,
            "type": "photo" if pid else "video",
            "title": it["title"] or "(không tiêu đề)",
            "snippet": (it["snippet"] or "")[:220],
            "url": url,
        })
        if len(found) >= limit:
            break
    if len(found) < min(limit, 3):
        more, _ = search_one(f"site:tiktok.com {q} video", limit)
        for it in more or []:
            url = it["url"]
            vid, pid = video_id(url), photo_id(url)
            if not (vid or pid):
                continue
            key = vid or pid
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "id": key,
                "type": "photo" if pid else "video",
                "title": it["title"] or "(không tiêu đề)",
                "snippet": (it["snippet"] or "")[:220],
                "url": url,
            })
            if len(found) >= limit:
                break
    return found[:limit], None


def print_info(data):
    print(data["title"])
    who = "@" + data["username"] if data["username"] else (data["author"] or "")
    if data["author"] and data["username"] and data["author"] != data["username"]:
        who += f" · {data['author']}"
    if who:
        print(who)
    bits = []
    if data["type"] == "video":
        if data["duration"] is not None:
            bits.append(fmt_duration(data["duration"]))
    else:
        bits.append(f"bài ảnh ({data.get('images') or '?'} ảnh)")
    d = fmt_date(data.get("upload_date"))
    if d:
        bits.append(d)
    if data.get("views"):
        bits.append(f"{fmt_num(data['views'])} lượt xem")
    for key, label in (("likes", "thích"), ("comments", "bình luận"),
                       ("shares", "chia sẻ"), ("saves", "lưu")):
        if data.get(key):
            bits.append(f"{fmt_num(data[key])} {label}")
    if bits:
        print(" · ".join(bits))
    if data.get("music"):
        print(f"Nhạc: {data['music']}")
    print(data["url"])
    desc = (data.get("description") or "").strip()
    if desc and desc != data["title"]:
        print("\nMô tả:")
        print(desc[:1500])


def main():
    ap = argparse.ArgumentParser(description="Xem thông tin, tải video và tìm kiếm TikTok")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("info", help="thông tin video")
    i.add_argument("url")
    i.add_argument("--json", action="store_true")

    d = sub.add_parser("download", help="tải video (không watermark) hoặc âm thanh")
    d.add_argument("url")
    d.add_argument("-q", "--quality", choices=("hd", "sd", "h264"), default="hd")
    d.add_argument("-a", "--audio", action="store_true", help="chỉ tải âm thanh")
    d.add_argument("--h264", action="store_true", help="ưu tiên H.264 (tương thích máy cũ)")
    d.add_argument("-o", "--out", default=".")
    d.add_argument("--max-mb", type=int, default=40)
    d.add_argument("--json", action="store_true")

    s = sub.add_parser("search", help="tìm video TikTok theo từ khoá")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=8)
    s.add_argument("--json", action="store_true")

    r = sub.add_parser("resolve", help="mở link rút gọn / TikTok Lite")
    r.add_argument("url")
    r.add_argument("--json", action="store_true")

    args = ap.parse_args()

    if args.cmd == "info":
        data, err = info(args.url)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print_info(data)
        return 0

    if args.cmd == "download":
        data, err = download(args.url, args.quality, args.audio, args.out,
                             args.max_mb, args.h264)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            mb = data["size"] / (1024 * 1024)
            print(f"Đã tải: {data['path']} ({mb:.1f} MB)")
            if data.get("fallback"):
                print("Nguồn: tải trực tiếp từ TikTok (không watermark)")
            if data.get("warning"):
                print(f"Lưu ý: {data['warning']}")
        return 0

    if args.cmd == "resolve":
        try:
            url, note = resolve(args.url)
        except TikTokError as e:
            print(f"Lỗi: {e}", file=sys.stderr)
            return 1
        data = {
            "url": url,
            "type": "photo" if photo_id(url) else ("video" if video_id(url) else "unknown"),
            "id": video_id(url) or photo_id(url),
            "source": note or "direct",
        }
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(data["url"])
            if data["id"]:
                print(f"{data['type']} · id {data['id']} · {data['source']}")
            elif data["source"] == "short":
                print("Lỗi: link rút gọn không mở được video (có thể hết hạn hoặc riêng tư)",
                      file=sys.stderr)
                return 1
            else:
                print("Không tìm thấy ID video (link mời, trang kênh hoặc đã hết hạn)")
        return 0

    items, err = search(args.query, args.limit)
    if err:
        print(f"Lỗi: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        if not items:
            print("Không tìm thấy video nào.")
            return 0
        for n, it in enumerate(items, 1):
            print(f"{n}. {it['title']}")
            if it["snippet"]:
                print(f"   {it['snippet']}")
            print(f"   {it['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
