#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_memory_index.py — Tìm kiếm trí nhớ & lịch sử chat bằng SQLite FTS5.

Vì sao: MEMORY.md cứ dài ra, agent đọc lại toàn bộ mỗi lượt -> lặp, tốn token,
không tra được câu cũ. Index này cho phép tra cứu tức thì, có xếp hạng.

CLI
  python aistv_memory_index.py index            # cập nhật index (nhanh, chỉ file đổi)
  python aistv_memory_index.py search "bạc liêu" -n 8
  python aistv_memory_index.py stats
  python aistv_memory_index.py clear

Tự index: MEMORY.md, memory/**/*.md trong workspace, và lịch sử chat trong
$STV_HOME/history/*.json (nếu có).
"""
import argparse, hashlib, json, os, re, sqlite3, sys, time
from pathlib import Path

HOME = Path(os.getenv("STV_HOME") or (Path.home() / "stv_agent"))
WORKSPACE = Path(os.getenv("AISTV_WORKSPACE") or (HOME / "workspace"))
DB_PATH = Path(os.getenv("AISTV_MEMORY_DB") or (HOME / "memory.db"))
CHUNK = 900
MAX_CHUNKS_PER_FILE = 4000


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            source UNINDEXED, seq UNINDEXED, text,
            tokenize='unicode61 remove_diacritics 2'
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY, mtime REAL, size INTEGER, digest TEXT, indexed_at REAL
        )""")
    return con


def sources() -> list[Path]:
    out: list[Path] = []
    p = WORKSPACE / "MEMORY.md"
    if p.is_file():
        out.append(p)
    mem_dir = WORKSPACE / "memory"
    if mem_dir.is_dir():
        out += sorted(mem_dir.rglob("*.md"))
    hist = HOME / "history"
    if hist.is_dir():
        out += sorted(hist.glob("*.json"))
    out += sorted(WORKSPACE.glob("*.md"))
    # bỏ trùng, giữ thứ tự
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def _read_chunks(path: Path) -> list[str]:
    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text("utf-8", "replace"))
            lines = []
            if isinstance(data, list):
                for it in data:
                    if isinstance(it, dict):
                        role = it.get("role") or it.get("r") or ""
                        content = it.get("content") or it.get("text") or it.get("c") or ""
                        if content:
                            lines.append(f"[{role}] {content}")
                    elif isinstance(it, str):
                        lines.append(it)
            text = "\n".join(lines)
        else:
            text = path.read_text("utf-8", "replace")
    except Exception:
        return []

    # cắt theo đoạn, gộp đến ~CHUNK ký tự
    parts, buf = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= CHUNK:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            if buf:
                parts.append(buf)
            while len(para) > CHUNK:
                parts.append(para[:CHUNK])
                para = para[CHUNK:]
            buf = para
        if len(parts) >= MAX_CHUNKS_PER_FILE:
            break
    if buf:
        parts.append(buf)
    return parts


def cmd_index(args) -> int:
    con = db()
    stats = {"files": 0, "changed": 0, "chunks": 0, "removed": 0}
    seen_files = set()
    for path in sources():
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path.resolve())
        seen_files.add(key)
        digest = hashlib.sha1(
            f"{st.st_mtime_ns}:{st.st_size}:{path.name}".encode()).hexdigest()
        row = con.execute("SELECT digest FROM files WHERE path=?", (key,)).fetchone()
        if row and row[0] == digest and not args.force:
            stats["files"] += 1
            continue
        chunks = _read_chunks(path)
        con.execute("DELETE FROM chunks WHERE source=?", (key,))
        con.executemany(
            "INSERT INTO chunks(source, seq, text) VALUES(?,?,?)",
            [(key, i, c) for i, c in enumerate(chunks)])
        con.execute(
            "INSERT INTO files(path, mtime, size, digest, indexed_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size, "
            "digest=excluded.digest, indexed_at=excluded.indexed_at",
            (key, st.st_mtime, st.st_size, digest, time.time()))
        stats["files"] += 1
        stats["changed"] += 1
        stats["chunks"] += len(chunks)

    for (key,) in con.execute("SELECT path FROM files").fetchall():
        if key not in seen_files:
            con.execute("DELETE FROM chunks WHERE source=?", (key,))
            con.execute("DELETE FROM files WHERE path=?", (key,))
            stats["removed"] += 1
    con.commit()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False))
    else:
        print(f"Đã index {stats['files']} file · {stats['changed']} thay đổi · "
              f"{stats['chunks']} đoạn mới · xoá {stats['removed']} · DB {DB_PATH}")
    return 0


def _fts_query(q: str) -> str:
    """Biến câu người dùng thành truy vấn FTS5 an toàn."""
    words = re.findall(r"[\wÀ-ỹ]+", q, flags=re.U)
    if not words:
        return '""'
    return " OR ".join(f'"{w}"*' for w in words)


def cmd_search(args) -> int:
    con = db()
    rows = con.execute(
        "SELECT source, seq, snippet(chunks, 2, '«', '»', '…', 24), rank "
        "FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?",
        (_fts_query(args.query), args.n)).fetchall()
    hits = []
    for source, seq, snip, rank in rows:
        rel = source
        for base in (str(WORKSPACE), str(HOME)):
            if source.startswith(base):
                rel = source[len(base):].lstrip("\\/")
                break
        hits.append({"source": rel, "chunk": seq, "snippet": snip, "score": rank})
    if args.json:
        print(json.dumps({"ok": True, "query": args.query, "hits": hits},
                         ensure_ascii=False))
    elif not hits:
        print("Không tìm thấy.")
    else:
        for h in hits:
            print(f"■ {h['source']} #{h['chunk']}\n  {h['snippet']}\n")
    return 0


def cmd_stats(args) -> int:
    con = db()
    n_chunks = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    n_files = con.execute("SELECT count(*) FROM files").fetchone()[0]
    size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    info = {"files": n_files, "chunks": n_chunks, "db": str(DB_PATH), "bytes": size}
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
    else:
        print(f"{n_files} file · {n_chunks} đoạn · {size/1024:.0f} KB · {DB_PATH}")
    return 0


def cmd_clear(args) -> int:
    con = db()
    con.execute("DELETE FROM chunks")
    con.execute("DELETE FROM files")
    con.commit()
    print("Đã xoá index.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Index + tìm kiếm trí nhớ (FTS5)")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("index", help="cập nhật index")
    p.add_argument("--force", action="store_true", help="index lại tất cả")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("search", help="tìm kiếm")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("stats", help="thống kê")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("clear", help="xoá index")
    p.set_defaults(fn=cmd_clear)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
