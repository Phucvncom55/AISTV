#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_mcp.py — Quản lý MCP server trong opencode.json của workspace.

opencode đã hỗ trợ MCP sẵn; file này chỉ giúp thêm/xoá/liệt kê cho gọn,
giữ nguyên các cấu hình khác trong opencode.json.

Dùng
  python aistv_mcp.py list
  python aistv_mcp.py add notion --command "npx -y @notionhq/notion-mcp-server" \\
      --env NOTION_TOKEN=ntn_xxx
  python aistv_mcp.py add drive --url https://mcp.example.com/sse \\
      --header "Authorization: Bearer xxx"
  python aistv_mcp.py remove notion
  python aistv_mcp.py presets

Sau khi thêm, khởi động lại bot (hoặc opencode) để nạp server mới.
"""
import argparse, json, os, shlex, sys
from pathlib import Path

HOME = Path(os.getenv("STV_HOME") or (Path.home() / "stv_agent"))
WORKSPACE = Path(os.getenv("AISTV_WORKSPACE") or (HOME / "workspace"))
CONFIG = WORKSPACE / "opencode.json"

PRESETS = {
    "notion": {
        "type": "local",
        "command": ["npx", "-y", "@notionhq/notion-mcp-server"],
        "env": {"NOTION_TOKEN": "{env:NOTION_TOKEN}"},
        "enabled": True,
    },
    "filesystem": {
        "type": "local",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem",
                    str(WORKSPACE)],
        "enabled": True,
    },
}


def load() -> dict:
    if CONFIG.is_file():
        try:
            return json.loads(CONFIG.read_text("utf-8"))
        except Exception as e:
            raise SystemExit(f"opencode.json hỏng JSON: {e}")
    return {"$schema": "https://opencode.ai/config.json"}


def save(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", "utf-8")
    tmp.replace(CONFIG)


def servers(cfg: dict) -> dict:
    return cfg.setdefault("mcp", {}).setdefault("servers", {})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Quản lý MCP server cho opencode")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list")
    sub.add_parser("presets")

    p = sub.add_parser("add")
    p.add_argument("name")
    p.add_argument("--url", help="MCP remote (SSE/HTTP)")
    p.add_argument("--command", help="lệnh chạy MCP local")
    p.add_argument("--env", action="append", default=[], metavar="K=V")
    p.add_argument("--header", action="append", default=[], metavar='K: V')
    p.add_argument("--enabled", action="store_true", default=True)

    p = sub.add_parser("remove")
    p.add_argument("name")

    args = ap.parse_args(argv)
    cfg = load()

    if args.cmd == "list":
        items = servers(cfg)
        if not items:
            print("Chưa có MCP server nào.")
        for name, s in items.items():
            kind = s.get("url") or " ".join(s.get("command") or [])
            print(f"· {name}: {kind}")
        return 0

    if args.cmd == "presets":
        for name in PRESETS:
            print(name)
        return 0

    if args.cmd == "add":
        if args.name in PRESETS and not (args.url or args.command):
            srv = PRESETS[args.name]
        elif args.url:
            srv = {"type": "remote", "url": args.url, "enabled": True}
            if args.header:
                hdr = {}
                for h in args.header:
                    k, _, v = h.partition(":")
                    hdr[k.strip()] = v.strip()
                srv["headers"] = hdr
        elif args.command:
            srv = {"type": "local", "command": shlex.split(args.command), "enabled": True}
            if args.env:
                srv["env"] = dict(e.split("=", 1) for e in args.env)
        else:
            print("Cần --url hoặc --command (hoặc dùng preset có sẵn).", file=sys.stderr)
            return 2
        servers(cfg)[args.name] = srv
        save(cfg)
        print(f"Đã thêm MCP '{args.name}' → {CONFIG}")
        print("Khởi động lại bot/opencode để nạp.")
        return 0

    if args.cmd == "remove":
        if servers(cfg).pop(args.name, None) is None:
            print(f"Không có '{args.name}'.")
        else:
            save(cfg)
            print(f"Đã xoá '{args.name}'.")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
