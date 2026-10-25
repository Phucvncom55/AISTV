#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py — một lệnh kiểm chứng repo trước khi báo "xong".

Chạy:
  python scripts/verify.py            # tóm tắt PASS/FAIL
  python scripts/verify.py --json     # kết quả máy đọc
  python scripts/verify.py --fast     # bỏ unittest (chỉ compile + lint + bash)

Các bước: biên dịch toàn bộ .py → CODEMAP còn khớp? → unittest → ruff (nếu có)
→ `bash -n` cho script .sh (nếu bash chạy được). Không cài gì thêm.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'seed',
             'patches', '.qoder'}
BASH = os.getenv('AISTV_VERIFY_BASH', '')

try:  # console Windows mặc định cp1252 → in tiếng Việt sẽ vỡ
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _walk(suffix: str) -> list:
    out = []
    for p in ROOT.rglob('*' + suffix):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith('.') for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def _python() -> str:
    return sys.executable or 'python3'


def _run(cmd, timeout=180) -> tuple:
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, f'hết thời gian sau {timeout}s'
    except Exception as e:  # noqa
        return 1, str(e)


def check_compile() -> dict:
    errors = []
    files = _walk('.py')
    for f in files:
        try:
            src = f.read_text('utf-8', 'replace')
            compile(src, str(f), 'exec')
        except SyntaxError as e:
            errors.append(f'{f.relative_to(ROOT)}:{e.lineno}: {e.msg}')
        except OSError as e:
            errors.append(f'{f.relative_to(ROOT)}: {e}')
    return {'name': 'compile', 'ok': not errors, 'detail': '\n'.join(errors[:20]),
            'count': len(files)}


def check_codemap() -> dict:
    script = ROOT / 'scripts' / 'code_map.py'
    if not script.exists():
        return {'name': 'codemap', 'ok': True, 'detail': 'bỏ qua (chưa có script)'}
    rc, out = _run([_python(), str(script), '--check'], timeout=120)
    return {'name': 'codemap', 'ok': rc == 0, 'detail': out.strip()[-1200:]}


def check_tests() -> dict:
    tests = ROOT / 'tests'
    if not tests.is_dir():
        return {'name': 'tests', 'ok': True, 'detail': 'bỏ qua (chưa có tests/)'}
    rc, out = _run([_python(), '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                   timeout=180)
    return {'name': 'tests', 'ok': rc == 0, 'detail': out.strip()[-2000:]}


def check_ruff() -> dict:
    exe = shutil.which('ruff')
    if exe:
        cmd = [exe, 'check', '--no-cache', '--select', 'E9,F63,F7,F82', '.']
    else:
        rc, _ = _run([_python(), '-m', 'ruff', '--version'], timeout=20)
        if rc != 0:
            return {'name': 'ruff', 'ok': True, 'detail': 'bỏ qua (chưa cài ruff)'}
        cmd = [_python(), '-m', 'ruff', 'check', '--no-cache', '--select',
               'E9,F63,F7,F82', '.']
    rc, out = _run(cmd, timeout=180)
    return {'name': 'ruff', 'ok': rc == 0, 'detail': out.strip()[-2000:]}


def check_bash() -> dict:
    files = _walk('.sh')
    if not files:
        return {'name': 'bash', 'ok': True, 'detail': 'bỏ qua (không có .sh)'}
    bash = BASH or shutil.which('bash')
    if not bash:
        return {'name': 'bash', 'ok': True, 'detail': 'bỏ qua (không có bash)'}
    rc, _ = _run([bash, '-c', 'exit 0'], timeout=15)
    if rc != 0:
        return {'name': 'bash', 'ok': True, 'detail': 'bỏ qua (bash không chạy được)'}
    errors = []
    for f in files:
        rc, out = _run([bash, '-n', str(f)], timeout=30)
        if rc != 0:
            errors.append(f'{f.relative_to(ROOT)}: {out.strip()[:400]}')
    return {'name': 'bash', 'ok': not errors, 'detail': '\n'.join(errors[:10]),
            'count': len(files)}


def main() -> int:
    ap = argparse.ArgumentParser(description='Kiểm chứng repo AISTV.')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--fast', action='store_true')
    args = ap.parse_args()

    started = time.monotonic()
    checks = [check_compile(), check_codemap()]
    if not args.fast:
        checks.append(check_tests())
    checks += [check_ruff(), check_bash()]
    failed = [c for c in checks if not c['ok']]
    elapsed = time.monotonic() - started
    if args.json:
        print(json.dumps({'ok': not failed, 'elapsed': round(elapsed, 2),
                          'checks': checks}, ensure_ascii=False, indent=1))
        return 1 if failed else 0

    for c in checks:
        icon = '✓' if c['ok'] else '✖'
        count = f' ({c["count"]})' if c.get('count') else ''
        print(f'{icon} {c["name"]}{count}')
        if not c['ok'] and c.get('detail'):
            for line in c['detail'].splitlines()[:12]:
                print('   ' + line)
    print(f'\n{"PASS" if not failed else "FAIL"} — {len(checks) - len(failed)}/'
          f'{len(checks)} bước · {elapsed:.1f}s')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
