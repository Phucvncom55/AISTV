#!/usr/bin/env python3
"""AI STV YouTube helper: search, info, transcript."""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TIMEOUT = 90


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


def run(args, timeout=TIMEOUT):
    cmd = ytdlp() + ["--no-warnings", "--socket-timeout", "15", "--retries", "2"] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "yt-dlp quá thời gian chờ"
    except FileNotFoundError:
        return None, "chưa cài yt-dlp (pip install yt-dlp)"
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip().splitlines()
        msg = err[-1] if err else "yt-dlp lỗi không rõ"
        return None, re.sub(r"^ERROR:\s*", "", msg)
    return p.stdout, None


def load_json(args):
    out, err = run(args)
    if err:
        return None, err
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, "không đọc được dữ liệu từ yt-dlp"


def fmt_duration(sec):
    if not sec and sec != 0:
        return "?"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_views(n):
    if not n:
        return "?"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_date(raw):
    if not raw or len(raw) != 8:
        return ""
    return f"{raw[6:8]}/{raw[4:6]}/{raw[:4]}"


def search(query, limit):
    data, err = load_json(
        ["--flat-playlist", "--playlist-end", str(limit), "--dump-single-json", f"ytsearch{limit}:{query}"]
    )
    if err:
        return None, err
    items = []
    for e in data.get("entries") or []:
        if not e:
            continue
        items.append(
            {
                "id": e.get("id"),
                "title": e.get("title") or "(không tiêu đề)",
                "channel": e.get("channel") or e.get("uploader") or "",
                "duration": e.get("duration"),
                "views": e.get("view_count"),
                "url": f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else "",
            }
        )
    return items, None


def info(url):
    data, err = load_json(["--skip-download", "--no-playlist", "--dump-single-json", url])
    if err:
        return None, err
    return (
        {
            "id": data.get("id"),
            "title": data.get("title"),
            "channel": data.get("channel") or data.get("uploader"),
            "duration": data.get("duration"),
            "views": data.get("view_count"),
            "likes": data.get("like_count"),
            "upload_date": data.get("upload_date"),
            "description": data.get("description") or "",
            "chapters": [
                {"title": c.get("title"), "start": c.get("start_time")}
                for c in (data.get("chapters") or [])
            ],
            "url": data.get("webpage_url") or url,
        },
        None,
    )


def vtt_to_cues(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        start = None
        body = []
        for line in lines:
            if "-->" in line:
                stamp = line.split("-->")[0].strip().split(" ")[0]
                m = re.match(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})", stamp)
                if m:
                    h = int(m.group(1) or 0)
                    start = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                continue
            if start is not None:
                body.append(line)
        if start is None or not body:
            continue
        txt = html.unescape(re.sub(r"<[^>]+>", "", " ".join(body))).strip()
        txt = re.sub(r"\s+", " ", txt)
        if not txt:
            continue
        if cues and txt == cues[-1][1]:
            continue
        if cues and txt.startswith(cues[-1][1]) and len(txt) > len(cues[-1][1]):
            cues[-1] = (cues[-1][0], txt)
            continue
        cues.append((start, txt))
    return cues


def grab_sub(url, lang, workdir):
    cmd = [
        "--skip-download",
        "--no-playlist",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        lang,
        "--sub-format",
        "vtt",
        "-o",
        str(workdir / "sub"),
        url,
    ]
    last = None
    for attempt in range(3):
        out, err = run(cmd, timeout=75)
        files = sorted(workdir.glob("*.vtt"))
        if files:
            raw = files[0].read_text(encoding="utf-8", errors="replace")
            cues = vtt_to_cues(raw)
            if cues:
                return cues, lang, None
        last = err or "không có phụ đề"
        if err and "429" not in err and "Too Many Requests" not in err:
            break
        time.sleep(2 + attempt * 2)
    return None, lang, last


def transcript(url, langs, timestamps, max_chars):
    for lang in langs:
        with tempfile.TemporaryDirectory(prefix="aistv_yt_") as tmp:
            cues, used, err = grab_sub(url, lang, Path(tmp))
        if cues:
            lines = []
            for start, txt in cues:
                if timestamps:
                    h, m, s = start // 3600, (start % 3600) // 60, start % 60
                    stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                    lines.append(f"[{stamp}] {txt}")
                else:
                    lines.append(txt)
            text = "\n".join(lines)
            truncated = False
            if max_chars and len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0] + "\n[... cắt bớt]"
                truncated = True
            return {"lang": used, "chars": len(text), "truncated": truncated, "text": text}, None
        last_err = err
    return None, last_err or "video không có phụ đề"


def main():
    ap = argparse.ArgumentParser(description="Tìm video YouTube, xem thông tin, lấy transcript")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="tìm video")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=5)
    s.add_argument("--json", action="store_true")

    i = sub.add_parser("info", help="thông tin video")
    i.add_argument("url")
    i.add_argument("--full", action="store_true", help="in đầy đủ mô tả")

    t = sub.add_parser("transcript", help="lấy phụ đề/transcript")
    t.add_argument("url")
    t.add_argument("-l", "--langs", default="vi,en", help="thứ tự ưu tiên, mặc định vi,en")
    t.add_argument("--timestamps", action="store_true")
    t.add_argument("--max-chars", type=int, default=12000)
    t.add_argument("--json", action="store_true")

    args = ap.parse_args()

    if args.cmd == "search":
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
                dur = f" [{fmt_duration(it['duration'])}]" if it["duration"] else ""
                views = f" · {fmt_views(it['views'])} lượt xem" if it["views"] else ""
                print(f"{n}. {it['title']}{dur}")
                print(f"   {it['channel']}{views}")
                print(f"   {it['url']}")
        return 0

    if args.cmd == "info":
        data, err = info(args.url)
        if err:
            print(f"Lỗi: {err}", file=sys.stderr)
            return 1
        desc = data["description"] if args.full else data["description"][:1000]
        print(data["title"])
        print(
            f"{data['channel']} · {fmt_duration(data['duration'])} · "
            f"{fmt_views(data['views'])} lượt xem · {fmt_date(data['upload_date'])}"
        )
        print(data["url"])
        if data["chapters"]:
            print("\nChương:")
            for c in data["chapters"]:
                print(f"  {fmt_duration(c['start'])} {c['title']}")
        if desc.strip():
            print("\nMô tả:")
            print(desc.strip())
            if not args.full and len(data["description"]) > 1000:
                print("[...]")
        return 0

    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    data, err = transcript(args.url, langs, args.timestamps, args.max_chars)
    if err:
        print(f"Lỗi: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"# Phụ đề ({data['lang']}, {data['chars']} ký tự)\n")
        print(data["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
