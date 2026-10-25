#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""code_map.py — sinh bản đồ code (CODEMAP) để agent định vị nhanh.

Vì sao: aistv_bot.py hơn 7.000 dòng; đọc cả file tốn context và dễ lạc. CODEMAP
liệt kê module → class/hàm/handler kèm số dòng, kèm mục đích từng module, để
agent grep theo symbol thay vì đọc tuần tự.

Cách dùng:
  python scripts/code_map.py                 # ghi docs/CODEMAP.md
  python scripts/code_map.py --check         # báo lỗi nếu CODEMAP cũ
  python scripts/code_map.py --json          # in JSON cho tool khác
  python scripts/code_map.py --root . --out docs/CODEMAP.md
"""
import argparse
import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
             'seed', 'patches', '.qoder'}

try:  # console Windows mặc định cp1252 → in tiếng Việt sẽ vỡ
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


BOX_CHARS = set('╔╗╚╝║═╠╣╦╩╬┏┓┗┛┃━┳┻╋│─┌┐└┘')


def _docline(node) -> str:
    doc = ast.get_docstring(node, clean=True) or ''
    for line in doc.splitlines():
        text = ' '.join(''.join(ch for ch in line
                                if ch not in BOX_CHARS).split())
        if len(text) >= 8 and sum(c.isalnum() for c in text) >= 6:
            return text[:110]
    return ''


def _signature(node) -> str:
    name = getattr(node, 'name', '?')
    try:
        params = ast.unparse(node.args)
    except Exception:
        params = '...'
    sig = f'{name}({params})'
    if len(sig) > 120:
        sig = sig[:117] + '...'
    return sig


def _decorators(node) -> list:
    out = []
    for dec in getattr(node, 'decorator_list', []) or []:
        try:
            out.append(ast.unparse(dec))
        except Exception:
            pass
    return out


def _outline(path: Path) -> dict:
    try:
        tree = ast.parse(path.read_text('utf-8', 'replace'), filename=str(path))
    except SyntaxError as e:
        return {'error': f'cú pháp lỗi dòng {e.lineno}: {e.msg}', 'items': []}
    items = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append({
                'kind': 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def',
                'name': _signature(node),
                'line': node.lineno,
                'doc': _docline(node),
                'decorators': _decorators(node),
            })
        elif isinstance(node, ast.ClassDef):
            methods = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        'kind': 'async def' if isinstance(sub, ast.AsyncFunctionDef)
                        else 'def',
                        'name': _signature(sub), 'line': sub.lineno,
                        'doc': _docline(sub), 'decorators': _decorators(sub),
                    })
            items.append({
                'kind': 'class', 'name': node.name, 'line': node.lineno,
                'doc': _docline(node), 'decorators': _decorators(node),
                'methods': methods,
            })
    return {'error': '', 'doc': _docline(tree), 'items': items}


def _py_files(root: Path) -> list:
    files = sorted(root.glob('*.py'))
    extra = []
    for sub in ('scripts', 'tests'):
        d = root / sub
        if d.is_dir():
            extra.extend(sorted(d.glob('*.py')))
    return files + extra


def build(root: Path) -> str:
    files = _py_files(root)
    maps = {}
    for f in files:
        maps[f.relative_to(root).as_posix()] = _outline(f)
    total_lines = 0
    for f in files:
        try:
            total_lines += len(f.read_text('utf-8', 'replace').splitlines())
        except OSError:
            pass

    out = ['# CODEMAP — bản đồ code AISTV', '',
           f'> Tự sinh bởi `scripts/code_map.py` · {len(files)} file Python · '
           f'{total_lines} dòng. Đừng sửa tay: chỉnh code rồi chạy lại '
           '`python scripts/code_map.py`.', '',
           '## Cách dùng cho agent', '',
           '1. Đọc bảng module bên dưới để biết file cần mở.',
           '2. `grep -n "def tên_hàm" <file>` để lấy đúng vùng dòng.',
           '3. Chỉ đọc 60–150 dòng quanh symbol, không đọc cả file.',
           '4. Sửa xong chạy `python scripts/verify.py`.', '',
           '## Module', '',
           '| File | Dòng | Mục đích |', '|---|---:|---|']
    for rel, info in maps.items():
        lines = 0
        try:
            lines = len((root / rel).read_text('utf-8', 'replace').splitlines())
        except OSError:
            pass
        purpose = info.get('doc') or info.get('error') or ''
        purpose = purpose.replace('|', '/')
        out.append(f'| `{rel}` | {lines} | {purpose} |')

    for rel, info in maps.items():
        out += ['', f'## {rel}', '']
        if info.get('error'):
            out.append(f'⚠️ {info["error"]}')
            continue
        if info.get('doc'):
            out.append(f'_{info["doc"]}_')
            out.append('')
        items = info.get('items') or []
        if not items:
            out.append('(không có hàm/class cấp module)')
            continue
        out += ['```text']
        for it in items:
            deco = ' '.join('@' + d for d in it.get('decorators') or [])
            prefix = f'{deco} ' if deco else ''
            doc = f'  — {it["doc"]}' if it.get('doc') else ''
            out.append(f'L{it["line"]:<5} {prefix}{it["kind"]} {it["name"]}{doc}')
            for m in it.get('methods') or []:
                mdeco = ' '.join('@' + d for d in m.get('decorators') or [])
                mprefix = f'{mdeco} ' if mdeco else ''
                mdoc = f'  — {m["doc"]}' if m.get('doc') else ''
                out.append(f'  L{m["line"]:<5} {mprefix}{m["kind"]} {m["name"]}{mdoc}')
        out.append('```')
    return '\n'.join(out).rstrip() + '\n'


def main() -> int:
    ap = argparse.ArgumentParser(description='Sinh CODEMAP từ AST.')
    ap.add_argument('--root', default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument('--out', default='docs/CODEMAP.md')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if args.json:
        data = {}
        for f in _py_files(root):
            info = _outline(f)
            info['lines'] = len(f.read_text('utf-8', 'replace').splitlines())
            data[f.relative_to(root).as_posix()] = info
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0

    content = build(root)
    dest = Path(args.out)
    if not dest.is_absolute():
        dest = root / dest
    if args.check:
        try:
            old = dest.read_text('utf-8')
        except OSError:
            old = ''
        if old != content:
            print(f'✖ {dest} đã cũ — chạy: python scripts/code_map.py')
            return 1
        print(f'✓ {dest} khớp code')
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, 'utf-8')
    print(f'✓ Đã ghi {dest} ({len(content.splitlines())} dòng)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
