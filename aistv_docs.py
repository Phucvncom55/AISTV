#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_docs.py — Đọc PDF / DOCX / ảnh scan (OCR) hoàn toàn LOCAL.

Không gọi Gemini, không tốn quota. Tự hạ cấp khi thiếu công cụ.

CLI
  python aistv_docs.py hop-dong.pdf                  # in text ra stdout
  python aistv_docs.py hop-dong.pdf --out out.txt --json
  python aistv_docs.py anh-chup.jpg --lang vie+eng   # OCR tiếng Việt + Anh
  python aistv_docs.py --check                       # xem máy có gì

Engine (tự chọn theo thứ tự có sẵn)
  PDF : pdftotext (poppler) → PyMuPDF (fitz) → pdfminer.six
  DOCX: python-docx → đọc trực tiếp word/document.xml (không cần thư viện)
  Ảnh : tesseract CLI → pytesseract

Cài trên Debian/Ubuntu (DataCamp/Colab/VPS)
  sudo apt-get update && sudo apt-get install -y poppler-utils tesseract-ocr \
       tesseract-ocr-vie
  pip install pymupdf python-docx pytesseract
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
DOC_EXT = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm", ".rtf"}


class DocError(RuntimeError):
    pass


def _run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _which(name):
    return shutil.which(name) or ""


# ── PDF ───────────────────────────────────────────────────────────────
def _pdf_pdftotext(path: Path) -> tuple[str, str]:
    exe = _which("pdftotext")
    if not exe:
        raise DocError("không có pdftotext")
    p = _run([exe, "-layout", "-enc", "UTF-8", str(path), "-"])
    if p.returncode != 0:
        raise DocError(f"pdftotext lỗi: {p.stderr.strip()[:200]}")
    return p.stdout, "pdftotext"


def _pdf_fitz(path: Path) -> tuple[str, str]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        raise DocError("không có PyMuPDF")
    with fitz.open(str(path)) as doc:
        text = "\n\n".join(page.get_text("text") for page in doc)
    return text, "pymupdf"


def _pdf_pdfminer(path: Path) -> tuple[str, str]:
    try:
        from pdfminer.high_level import extract_text
    except Exception:
        raise DocError("không có pdfminer.six")
    return extract_text(str(path)), "pdfminer"


def pdf_text(path: Path) -> tuple[str, str]:
    errors = []
    for fn in (_pdf_pdftotext, _pdf_fitz, _pdf_pdfminer):
        try:
            text, engine = fn(path)
            if text.strip():
                return text, engine
            errors.append(f"{engine}: không có chữ (PDF scan?)")
        except Exception as e:
            errors.append(str(e))
    raise DocError(" | ".join(errors) or "không đọc được PDF")


def pdf_is_scanned(path: Path) -> bool:
    try:
        text, _ = pdf_text(path)
        return len(text.strip()) < 40
    except Exception:
        return True


# ── DOCX ──────────────────────────────────────────────────────────────
def _docx_python_docx(path: Path) -> tuple[str, str]:
    try:
        import docx  # python-docx
    except Exception:
        raise DocError("không có python-docx")
    d = docx.Document(str(path))
    out = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                out.append(" | ".join(cells))
    return "\n".join(out), "python-docx"


def _docx_raw_xml(path: Path) -> tuple[str, str]:
    """Không cần python-docx: đọc trực tiếp word/document.xml."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            root = ET.parse(f).getroot()
    lines = []
    for p in root.iter(f"{ns}p"):
        line = "".join(t.text or "" for t in p.iter(f"{ns}t"))
        if line.strip():
            lines.append(line)
    return "\n".join(lines), "docx-xml"


def docx_text(path: Path) -> tuple[str, str]:
    errors = []
    for fn in (_docx_python_docx, _docx_raw_xml):
        try:
            text, engine = fn(path)
            if text.strip():
                return text, engine
            errors.append(f"{engine}: rỗng")
        except Exception as e:
            errors.append(str(e))
    raise DocError(" | ".join(errors) or "không đọc được DOCX")


# ── OCR ───────────────────────────────────────────────────────────────
def ocr_image(path: Path, lang: str = "vie+eng") -> tuple[str, str]:
    exe = _which("tesseract")
    if not exe:
        raise DocError(
            "không có tesseract. Cài: sudo apt-get install -y tesseract-ocr "
            "tesseract-ocr-vie  (Windows: winget install UB-Mannheim.TesseractOCR)")
    p = _run([exe, str(path), "stdout", "-l", lang, "--psm", "3"], timeout=600)
    if p.returncode != 0:
        # thiếu gói ngôn ngữ -> thử eng
        p2 = _run([exe, str(path), "stdout", "-l", "eng", "--psm", "3"], timeout=600)
        if p2.returncode == 0 and p2.stdout.strip():
            return p2.stdout, f"tesseract(eng; thiếu {lang})"
        raise DocError(f"tesseract lỗi: {p.stderr.strip()[:200]}")
    return p.stdout, f"tesseract({lang})"


# ── Điều phối ─────────────────────────────────────────────────────────
def extract(path: str | Path, lang: str = "vie+eng") -> dict:
    p = Path(path).expanduser()
    if not p.is_file():
        raise DocError(f"không thấy file: {p}")
    ext = p.suffix.lower()
    if ext == ".pdf":
        text, engine = pdf_text(p)
        if len(text.strip()) < 40:                 # PDF scan -> OCR từng trang
            raise DocError("PDF không có lớp chữ (bản scan). Hãy chuyển sang ảnh rồi OCR, "
                           "hoặc cài ocrmypdf: apt-get install -y ocrmypdf")
    elif ext in (".docx", ".doc"):
        if ext == ".doc":
            raise DocError("định dạng .doc cũ: hãy lưu lại thành .docx")
        text, engine = docx_text(p)
    elif ext in IMAGE_EXT:
        text, engine = ocr_image(p, lang)
    else:
        text, engine = p.read_text("utf-8", "replace"), "plain"
    return {"ok": True, "path": str(p), "engine": engine, "ext": ext,
            "chars": len(text), "text": text}


def check() -> dict:
    return {
        "pdftotext": bool(_which("pdftotext")),
        "tesseract": bool(_which("tesseract")),
        "tesseract_vie": _has_tessdata("vie"),
        "pymupdf": _importable("fitz"),
        "python_docx": _importable("docx"),
        "pdfminer": _importable("pdfminer"),
        "ffmpeg": bool(_which("ffmpeg")),
    }


def _importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _has_tessdata(lang: str) -> bool:
    exe = _which("tesseract")
    if not exe:
        return False
    try:
        p = _run([exe, "--list-langs"], timeout=20)
        return lang in (p.stdout or "").split()
    except Exception:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Đọc PDF/DOCX/ảnh local (không tốn API)")
    ap.add_argument("path", nargs="?", help="file cần đọc")
    ap.add_argument("--out", "-o", help="ghi text ra file")
    ap.add_argument("--lang", default="vie+eng", help="ngôn ngữ OCR (mặc định vie+eng)")
    ap.add_argument("--json", action="store_true", help="in JSON")
    ap.add_argument("--check", action="store_true", help="kiểm tra công cụ có sẵn")
    args = ap.parse_args(argv)

    if args.check:
        info = check()
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=1))
        else:
            for k, v in info.items():
                print(f"{'OK ' if v else '---'} {k}")
        return 0

    if not args.path:
        ap.print_help()
        return 2

    try:
        res = extract(args.path, args.lang)
    except DocError as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"LỖI: {e}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).expanduser().write_text(res["text"], "utf-8")
        res["out"] = str(Path(args.out).expanduser())
        if args.json:
            res.pop("text", None)

    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    elif args.out:
        print(f"OK · {res['engine']} · {res['chars']} ký tự → {res['out']}")
    else:
        print(res["text"])
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
