# -*- coding: utf-8 -*-
"""Cài / quản lý Agent Skills cho AISTV.

Chuẩn hỗ trợ: một thư mục có ``SKILL.md`` với YAML frontmatter
(``name``, ``description``) và các thư mục tuỳ chọn ``scripts/``,
``references/``, ``assets/``, ``agents/``.

Nguồn cài đặt:
  - owner/repo
  - owner/repo/path/to/skill
  - owner/repo@branch (hoặc --ref branch)
  - https://github.com/owner/repo
  - https://github.com/owner/repo/tree/<ref>/<path>
  - https://github.com/owner/repo/blob/<ref>/<path>/SKILL.md
  - https://raw.githubusercontent.com/owner/repo/<ref>/<path>/SKILL.md
  - https://.../skill.zip

Ví dụ:
  python aistv_skills.py install mattpocock/skills/skills/engineering/tdd
  python aistv_skills.py install anthropics/skills/skills/skill-creator --force
  python aistv_skills.py list

Không chạy script của skill khi cài. Chỉ tải file, kiểm tra đường dẫn và
giới hạn dung lượng. Chỉ chủ bot nên cài skill từ nguồn tin cậy.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

USER_AGENT = "AISTV-Skills/1.0 (+https://github.com/Phucvncom55/AISTV)"
MAX_ZIP_BYTES = 60 * 1024 * 1024
MAX_RAW_BYTES = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 4000
MAX_EXTRACT_BYTES = 150 * 1024 * 1024
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_SKILL_BYTES = 20 * 1024 * 1024
MAX_SKILL_FILES = 400
MAX_SKILLS_PER_INSTALL = 40
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Tên thiết bị dành riêng trên Windows (không thể dùng làm tên thư mục).
WINDOWS_RESERVED = {"con", "prn", "aux", "nul",
                    *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}
# Các skill tài liệu của Anthropic dùng giấy phép source-available, không phải Apache-2.0.
RESTRICTED_SKILLS = {"docx", "pdf", "pptx", "xlsx"}

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", "__MACOSX",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "venv",
    "dist", "build",
}
IGNORE_SUFFIXES = {".pyc", ".pyo", ".DS_Store"}
TEMPLATE_DIRS = {"template", "templates", "deprecated", "in-progress"}


class SkillError(Exception):
    """Lỗi cài skill với thông báo thân thiện."""


# ────────────────────────────────────────────────────────────────────
# Frontmatter / tên / mô tả
# ────────────────────────────────────────────────────────────────────
def oneline(text: str, limit: int = 0) -> str:
    text = re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Đọc YAML frontmatter đơn giản (không cần PyYAML).

    Trả về ``(metadata, body)``. Nếu không có frontmatter hợp lệ thì
    metadata rỗng và body là toàn bộ văn bản.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    meta: dict[str, str] = {}
    fm = lines[1:end]
    i = 0
    while i < len(fm):
        raw = fm[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw.startswith((" ", "\t")) or ":" not in raw:
            i += 1
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            i += 1
            continue
        value = value.strip()

        # Block scalar: description: > / | / >- ...
        if value in ("|", "|-", "|+", ">", ">-", ">+"):
            block: list[str] = []
            i += 1
            while i < len(fm):
                line = fm[i]
                if line.strip() == "":
                    block.append("")
                    i += 1
                    continue
                if not line.startswith((" ", "\t")):
                    break
                block.append(line.strip())
                i += 1
            if value.startswith(">"):
                value = " ".join(part for part in block if part)
            else:
                value = "\n".join(block).strip("\n")
            meta[key] = value
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace('\\"', '"').replace("\\\\", "\\")
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        meta[key] = value
        i += 1
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def description_of(text: str) -> str:
    meta, body = parse_frontmatter(text)
    desc = oneline(meta.get("description", ""))
    if desc:
        return desc
    for line in body.splitlines():
        s = line.strip()
        if not s or s == "---" or s.startswith("#") or s.startswith("```"):
            continue
        return oneline(s)
    return ""


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:64].strip("-")


def choose_name(meta: dict, folder: str) -> str:
    raw = (meta.get("name") or "").strip()
    name = slugify(raw) if raw else ""
    if not name:
        name = slugify(folder)
    if not name:
        name = "skill"
    if name.lower() in WINDOWS_RESERVED:
        name = ("s-" + name)[:64].strip("-")
    if not NAME_RE.match(name):
        name = ("s-" + name)[:64].strip("-")
    return name or "skill"


# ────────────────────────────────────────────────────────────────────
# Tải & giải nén an toàn
# ────────────────────────────────────────────────────────────────────
def _http_get(url: str, timeout: int = 45, max_bytes: int = MAX_ZIP_BYTES,
              token: Optional[str] = None) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        raise SkillError("Chỉ hỗ trợ nguồn http(s).")
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if token:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if (host in ("api.github.com", "github.com", "raw.githubusercontent.com", "codeload.github.com")
                or host.endswith(".githubusercontent.com")):
            headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise SkillError(f"Nguồn quá lớn ({int(length) / 1048576:.1f} MB).")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(1024 * 128)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise SkillError(f"Nguồn vượt quá {max_bytes / 1048576:.0f} MB.")
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SkillError("Không tìm thấy nguồn (HTTP 404). Kiểm tra owner/repo/nhánh/đường dẫn.") from exc
        if exc.code in (401, 403):
            raise SkillError(f"GitHub từ chối truy cập (HTTP {exc.code}). Có thể cần token hoặc đã hết giới hạn.") from exc
        raise SkillError(f"Tải nguồn thất bại (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise SkillError(f"Không kết nối được tới nguồn: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SkillError("Tải nguồn quá lâu (timeout).") from exc


def _github_default_branch(owner: str, repo: str, token: Optional[str]) -> Optional[str]:
    try:
        data = _http_get(
            f"https://api.github.com/repos/{owner}/{repo}",
            timeout=20, max_bytes=2 * 1024 * 1024, token=token,
        )
        info = json.loads(data.decode("utf-8", "replace"))
        branch = str(info.get("default_branch") or "").strip()
        return branch or None
    except Exception:
        return None


def _github_zip(owner: str, repo: str, ref: Optional[str], token: Optional[str]) -> tuple[bytes, str]:
    tried: list[str] = []
    if ref:
        # Người dùng chỉ định ref: không tự fallback sang nhánh khác.
        candidates = [ref]
    else:
        candidates = []
        for candidate in (_github_default_branch(owner, repo, token), "main", "master"):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    for candidate in candidates:
        tried.append(candidate)
        url = (f"https://codeload.github.com/{owner}/{repo}/zip/"
               f"{urllib.parse.quote(candidate, safe='')}")
        try:
            return _http_get(url, timeout=60), candidate
        except SkillError as exc:
            if "404" not in str(exc):
                raise
    if ref:
        raise SkillError(f"Không tìm thấy nhánh/tag/commit “{ref}” trong {owner}/{repo}.")
    raise SkillError(
        "Không tải được repo GitHub. Đã thử nhánh: " + ", ".join(tried or ["(mặc định)"])
    )


def _zip_root(tmpdir: Path, zf: zipfile.ZipFile) -> tuple[Path, list[str]]:
    """Giải nén zip, chặn path traversal và file quá lớn."""
    tmpdir = tmpdir.resolve()
    skipped: list[str] = []
    total = 0
    tops: set[str] = set()
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise SkillError(f"Zip có quá nhiều file ({len(infos)}), giới hạn {MAX_ZIP_ENTRIES}.")

    for info in infos:
        raw_name = (info.filename or "").replace("\\", "/").lstrip("/")
        if not raw_name or raw_name.endswith("/"):
            continue
        parts = [p for p in raw_name.split("/") if p not in ("", ".")]
        if not parts or parts[0] == "__MACOSX":
            continue
        if any(p == ".." for p in parts) or re.match(r"^[A-Za-z]:", parts[0]):
            skipped.append(raw_name)
            continue
        if info.flag_bits & 0x1:          # zip có mật khẩu
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:              # symlink
            continue
        if info.file_size > MAX_FILE_BYTES:
            skipped.append(raw_name)
            continue
        target = (tmpdir / Path(*parts)).resolve()
        try:
            target.relative_to(tmpdir)
        except ValueError:
            skipped.append(raw_name)
            continue
        total += info.file_size
        if total > MAX_EXTRACT_BYTES:
            raise SkillError(f"Zip giải nén vượt quá {MAX_EXTRACT_BYTES / 1048576:.0f} MB.")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 128)
            file_mode = (info.external_attr >> 16) & 0o777
            if file_mode and os.name != "nt":
                os.chmod(target, file_mode | 0o600)
        except Exception:
            skipped.append(raw_name)
        tops.add(parts[0])

    if not tops:
        raise SkillError("Zip rỗng hoặc không có file hợp lệ.")
    root = tmpdir
    if len(tops) == 1:
        first = tmpdir / next(iter(tops))
        if first.is_dir():
            root = first
    return root, skipped


def _extract_zip(data: bytes, tmpdir: Path) -> tuple[Path, list[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SkillError("File tải về không phải zip hợp lệ.") from exc
    with zf:
        return _zip_root(tmpdir, zf)


# ────────────────────────────────────────────────────────────────────
# Phân tích nguồn
# ────────────────────────────────────────────────────────────────────
def parse_source(source: str, ref: Optional[str] = None) -> dict:
    raw = (source or "").strip().replace("\\", "/")
    if not raw:
        raise SkillError("Thiếu nguồn skill.")
    if re.match(r"^[A-Za-z]:/", raw):
        raise SkillError("Chỉ hỗ trợ owner/repo hoặc URL GitHub, không hỗ trợ đường dẫn cục bộ.")
    if raw.lower().startswith(("github.com/", "www.github.com/")):
        raw = "https://" + raw

    # owner/repo[/path][@ref]
    if "://" not in raw:
        inline_ref = None
        if "@" in raw:
            raw, inline_ref = raw.rsplit("@", 1)
        parts = [p for p in raw.split("/") if p]
        if len(parts) < 2:
            raise SkillError("Nguồn phải có dạng owner/repo hoặc URL GitHub.")
        return {
            "kind": "github",
            "owner": parts[0],
            "repo": parts[1].removesuffix(".git"),
            "ref": ref or inline_ref,
            "path": "/".join(parts[2:]),
            "url": None,
            "display": source.strip(),
        }

    parsed = urllib.parse.urlparse(raw)
    host = (parsed.netloc or "").lower().split(":")[0].removeprefix("www.")
    segments = [p for p in parsed.path.split("/") if p]

    if host == "github.com" and (parsed.path or "").lower().endswith(".zip"):
        # Link "Download ZIP" của GitHub (archive/refs/heads/...).
        return {
            "kind": "zip_url",
            "owner": segments[0] if segments else "",
            "repo": segments[1].removesuffix(".zip") if len(segments) > 1 else "",
            "ref": ref,
            "path": "",
            "url": raw,
            "display": source.strip(),
        }

    if host == "github.com":
        if len(segments) < 2:
            raise SkillError("URL GitHub không hợp lệ.")
        owner, repo = segments[0], segments[1].removesuffix(".git")
        path = ""
        use_ref = ref
        if len(segments) >= 4 and segments[2] in ("tree", "blob", "raw"):
            use_ref = use_ref or segments[3]
            path = "/".join(segments[4:])
        elif len(segments) > 2:
            path = "/".join(segments[2:])
        return {
            "kind": "github",
            "owner": owner,
            "repo": repo,
            "ref": use_ref,
            "path": path,
            "url": None,
            "display": source.strip(),
        }

    if host == "raw.githubusercontent.com":
        if len(segments) < 4:
            raise SkillError("URL raw GitHub không hợp lệ.")
        return {
            "kind": "raw",
            "owner": segments[0],
            "repo": segments[1],
            "ref": ref or segments[2],
            "path": "/".join(segments[3:]),
            "url": raw,
            "display": source.strip(),
        }

    if host == "codeload.github.com":
        return {
            "kind": "zip_url",
            "owner": segments[0] if len(segments) > 1 else "",
            "repo": segments[1] if len(segments) > 1 else "",
            "ref": ref,
            "path": "",
            "url": raw,
            "display": source.strip(),
        }

    suffix = (parsed.path or "").lower()
    if suffix.endswith((".zip", ".md")):
        return {
            "kind": "raw" if suffix.endswith(".md") else "zip_url",
            "owner": "", "repo": "", "ref": ref, "path": "", "url": raw,
            "display": source.strip(),
        }
    raise SkillError("Chưa hỗ trợ nguồn này. Dùng owner/repo[/path] hoặc URL GitHub.")


def _raw_url(info: dict) -> str:
    owner, repo = info["owner"], info["repo"]
    path = urllib.parse.quote(info["path"], safe="/")
    ref = urllib.parse.quote(info["ref"] or "main", safe="/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


def _ignored(path: Path) -> bool:
    return any(part in IGNORE_DIRS or part.startswith(".") for part in path.parts)


def _find_candidates(base: Path, whole_repo: bool = False) -> list[Path]:
    if base.is_file():
        return [base] if base.name == "SKILL.md" else []
    if not base.is_dir():
        raise SkillError(f"Không thấy đường dẫn trong repo: {base.name}")
    direct = base / "SKILL.md"
    if direct.is_file():
        return [direct]

    found: list[Path] = []
    for path in base.rglob("SKILL.md"):
        rel = path.relative_to(base)
        if _ignored(rel):
            continue
        if whole_repo and any(part in TEMPLATE_DIRS for part in rel.parts):
            continue
        found.append(path)

    if whole_repo and found:
        under_skills = [p for p in found if "skills" in p.relative_to(base).parts]
        if under_skills:
            found = under_skills

    found.sort(key=lambda p: (len(p.parts), str(p).lower()))
    # Bỏ skill lồng trong skill khác.
    unique: list[Path] = []
    seen_dirs: list[Path] = []
    for path in found:
        parent = path.parent.resolve()
        if any(parent == d or parent.is_relative_to(d) for d in seen_dirs):
            continue
        seen_dirs.append(parent)
        unique.append(path)
    if len(unique) > MAX_SKILLS_PER_INSTALL:
        raise SkillError(
            f"Repo có {len(unique)} skill; giới hạn {MAX_SKILLS_PER_INSTALL}. "
            "Hãy trỏ tới một thư mục con cụ thể."
        )
    return unique


# ────────────────────────────────────────────────────────────────────
# Cài đặt
# ────────────────────────────────────────────────────────────────────
def _copy_skill(skill_file: Path, dest: Path, *, force: bool,
                info: dict, used_names: set[str], repo_license: Optional[Path] = None,
                notice: Optional[Path] = None, forced_name: Optional[str] = None,
                allow_restricted: bool = False) -> dict:
    text = skill_file.read_text("utf-8", "replace")
    meta, _ = parse_frontmatter(text)
    folder = skill_file.parent.name
    if forced_name and (not NAME_RE.match(forced_name) or forced_name.lower() in WINDOWS_RESERVED):
        raise SkillError("Tên skill không hợp lệ (chỉ dùng a-z, 0-9, _ và -, tối đa 64 ký tự; không dùng tên thiết bị Windows).")
    name = forced_name or choose_name(meta, folder)
    if not NAME_RE.match(name):
        name = choose_name({}, folder)
    if (name in RESTRICTED_SKILLS or folder in RESTRICTED_SKILLS) and not allow_restricted:
        return {
            "name": name,
            "status": "skipped",
            "reason": "skill tài liệu Anthropic dùng giấy phép source-available; "
                      "chỉ cài khi thật sự cần và tự tuân thủ điều khoản (--allow-restricted)",
        }
    if name in used_names:
        suffix = 2
        while f"{name}-{suffix}" in used_names:
            suffix += 1
        name = f"{name}-{suffix}"

    skill_dir = skill_file.parent
    target = dest / name
    if target.exists() and not force:
        return {"name": name, "status": "exists", "reason": "đã tồn tại (dùng --force để ghi đè)"}

    files: list[Path] = []
    total = 0
    for path in sorted(skill_dir.rglob("*")):
        rel = path.relative_to(skill_dir)
        if any(part in IGNORE_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in IGNORE_SUFFIXES or path.suffix.lower() in (".pyc", ".pyo"):
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise SkillError(
                f"Skill “{name}” có file quá lớn: {rel.as_posix()} "
                f"({size / 1048576:.1f} MB, giới hạn {MAX_FILE_BYTES / 1048576:.0f} MB)."
            )
        if len(files) >= MAX_SKILL_FILES:
            raise SkillError(f"Skill “{name}” có quá nhiều file (>{MAX_SKILL_FILES}).")
        total += size
        if total > MAX_SKILL_BYTES:
            raise SkillError(f"Skill “{name}” quá lớn (>{MAX_SKILL_BYTES / 1048576:.0f} MB).")
        files.append(path)

    if not files:
        raise SkillError(f"Skill “{name}” không có file nào.")

    tmp = dest / f".tmp-{name}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        for src in files:
            rel = src.relative_to(skill_dir)
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)

        # Giữ giấy phép / notice của repo gốc nếu skill chưa có.
        if (repo_license and repo_license.is_file()
                and not any((tmp / c).is_file() for c in ("LICENSE.txt", "LICENSE", "LICENSE.md", "COPYING"))):
            shutil.copy2(repo_license, tmp / "LICENSE.txt")
        if notice and notice.is_file() and not (tmp / "THIRD_PARTY_NOTICES.md").exists():
            shutil.copy2(notice, tmp / "THIRD_PARTY_NOTICES.md")

        license_name = ""
        for candidate in ("LICENSE.txt", "LICENSE", "LICENSE.md", "COPYING"):
            p = tmp / candidate
            if p.is_file():
                license_name = candidate
                break
        repo_slug = f"{info.get('owner', '')}/{info.get('repo', '')}".strip("/")
        source_md = (
            "# Nguồn skill\n\n"
            f"- Nguồn: {info.get('display', '')}\n"
            f"- Repo: {repo_slug}\n"
            f"- Nhánh/ref: {info.get('ref') or '(mặc định)'}\n"
            f"- Đường dẫn: {info.get('installed_from', '')}\n"
            f"- Giấy phép: {license_name or 'xem file LICENSE kèm theo (nếu có)'}\n"
            f"- Cài lúc: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            "\nSkill này do bên thứ ba cung cấp. Chỉ cài từ nguồn tin cậy.\n"
        )
        (tmp / "SOURCE.md").write_text(source_md, "utf-8")
        metadata = {
            "name": name,
            "description": description_of(text),
            "source": info.get("display", ""),
            "repo": f"{info.get('owner', '')}/{info.get('repo', '')}".strip("/"),
            "ref": info.get("ref"),
            "path": info.get("installed_from", ""),
            "license": license_name,
            "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (tmp / ".aistv-skill.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )

        dest.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        tmp.rename(target)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    used_names.add(name)
    final_files = [p for p in target.rglob("*") if p.is_file()]
    return {
        "name": name,
        "status": "installed",
        "description": description_of(text),
        "license": license_name,
        "path": str(target),
        "files": len(final_files),
        "bytes": sum(p.stat().st_size for p in final_files),
    }


def _install_raw(text: str, dest: Path, info: dict, force: bool,
                 forced_name: Optional[str], used_names: set[str],
                 allow_restricted: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="aistv-skill-") as td:
        tmp = Path(td)
        meta, _ = parse_frontmatter(text)
        name = forced_name or choose_name(meta, "skill")
        tmp_skill = tmp / (name or "skill")
        tmp_skill.mkdir(parents=True, exist_ok=True)
        (tmp_skill / "SKILL.md").write_text(text, "utf-8")
        info = dict(info)
        info.setdefault("installed_from", info.get("path", ""))
        return _copy_skill(
            tmp_skill / "SKILL.md", dest, force=force, info=info,
            used_names=used_names, forced_name=name,
            allow_restricted=allow_restricted,
        )


def install(source: str, dest: str | Path, *, force: bool = False,
            name: Optional[str] = None, ref: Optional[str] = None,
            token: Optional[str] = None, allow_restricted: bool = False) -> dict:
    """Cài một hoặc nhiều skill. Trả về dict tóm tắt (không raise nếu chỉ skip)."""
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if name and (not NAME_RE.match(name) or name.lower() in WINDOWS_RESERVED):
        raise SkillError("Tên skill không hợp lệ (chỉ dùng a-z, 0-9, _ và -, tối đa 64 ký tự; không dùng tên thiết bị Windows).")
    info = parse_source(source, ref=ref)
    token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    used_names: set[str] = set()
    installed: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []
    extracted_skipped: list[str] = []

    if info["kind"] == "raw" and (info.get("url") or "").lower().split("?", 1)[0].endswith(".md"):
        data = _http_get(info["url"], timeout=30, max_bytes=MAX_RAW_BYTES, token=token)
        text = data.decode("utf-8", "replace")
        result = _install_raw(text, dest, info, force, name, used_names, allow_restricted)
        if result.get("status") == "installed":
            installed.append(result)
        else:
            skipped.append(result)
        return {
            "ok": True, "source": info["display"], "ref": info.get("ref"),
            "installed": installed, "skipped": skipped, "warnings": warnings,
            "dest": str(dest),
        }

    if info["kind"] == "zip_url":
        data = _http_get(info["url"], timeout=90, max_bytes=MAX_ZIP_BYTES)
        with tempfile.TemporaryDirectory(prefix="aistv-skill-") as td:
            root, extracted_skipped = _extract_zip(data, Path(td))
            candidates = _find_candidates(root, whole_repo=True)
            if not candidates:
                raise SkillError("Không tìm thấy SKILL.md trong zip.")
            if name and len(candidates) > 1:
                raise SkillError("Nguồn có nhiều skill; --name chỉ dùng khi cài một skill.")
            license_path = next(
                (p for p in (root / "LICENSE", root / "LICENSE.txt", root / "LICENSE.md",
                             root / "COPYING")
                 if p.is_file()), None
            )
            notice = next(
                (p for p in (root / "THIRD_PARTY_NOTICES.md", root / "NOTICE")
                 if p.is_file()), None
            )
            for skill_file in candidates:
                info2 = dict(info)
                info2["installed_from"] = str(skill_file.parent.relative_to(root)).replace("\\", "/")
                try:
                    result = _copy_skill(
                        skill_file, dest, force=force, info=info2, used_names=used_names,
                        repo_license=license_path, notice=notice, forced_name=name,
                        allow_restricted=allow_restricted,
                    )
                except SkillError as exc:
                    skipped.append({"name": skill_file.parent.name, "status": "skipped", "reason": str(exc)})
                    continue
                (installed if result.get("status") == "installed" else skipped).append(result)
                if result.get("status") == "installed" and not result.get("license"):
                    warnings.append(
                        f"Skill “{result['name']}” không kèm LICENSE.txt — kiểm tra điều khoản trước khi dùng."
                    )
    else:
        # GitHub: nếu trỏ đúng file SKILL.md thì tải raw, ngược lại tải zip.
        path = info.get("path") or ""
        if path.endswith("SKILL.md") and info["kind"] == "github":
            use_ref = info.get("ref") or _github_default_branch(info["owner"], info["repo"], token) or "main"
            info = dict(info)
            info["ref"] = use_ref
            data = _http_get(_raw_url(info), timeout=30, max_bytes=MAX_RAW_BYTES, token=token)
            text = data.decode("utf-8", "replace")
            result = _install_raw(text, dest, info, force, name, used_names, allow_restricted)
            (installed if result.get("status") == "installed" else skipped).append(result)
        else:
            data, used_ref = _github_zip(info["owner"], info["repo"], info.get("ref"), token)
            info = dict(info)
            info["ref"] = used_ref
            with tempfile.TemporaryDirectory(prefix="aistv-skill-") as td:
                root, extracted_skipped = _extract_zip(data, Path(td))
                base = root / path if path else root
                if not base.exists():
                    raise SkillError(f"Không thấy đường dẫn trong repo: {path}")
                candidates = _find_candidates(base, whole_repo=not path)
                if not candidates:
                    raise SkillError(
                        "Không tìm thấy SKILL.md. Kiểm tra đường dẫn (ví dụ: skills/engineering/tdd)."
                    )
                if name and len(candidates) > 1:
                    raise SkillError("Nguồn có nhiều skill; --name chỉ dùng khi cài một skill.")
                license_path = next(
                    (p for p in (root / "LICENSE", root / "LICENSE.txt", root / "LICENSE.md",
                                 root / "COPYING")
                     if p.is_file()), None
                )
                notice = next(
                    (p for p in (root / "THIRD_PARTY_NOTICES.md", root / "NOTICE")
                     if p.is_file()), None
                )
                for skill_file in candidates:
                    info2 = dict(info)
                    info2["installed_from"] = str(skill_file.parent.relative_to(root)).replace("\\", "/")
                    try:
                        result = _copy_skill(
                            skill_file, dest, force=force, info=info2, used_names=used_names,
                            repo_license=license_path, notice=notice, forced_name=name,
                            allow_restricted=allow_restricted,
                        )
                    except SkillError as exc:
                        skipped.append({"name": skill_file.parent.name, "status": "skipped", "reason": str(exc)})
                        continue
                    (installed if result.get("status") == "installed" else skipped).append(result)
                    if result.get("status") == "installed" and not result.get("license"):
                        warnings.append(
                            f"Skill “{result['name']}” không kèm LICENSE.txt — kiểm tra điều khoản trước khi dùng."
                        )

    if extracted_skipped:
        warnings.append(f"Bỏ qua {len(extracted_skipped)} file không an toàn/quá lớn trong zip.")
    return {
        "ok": True,
        "source": info.get("display", source),
        "ref": info.get("ref"),
        "installed": installed,
        "skipped": skipped,
        "warnings": warnings,
        "dest": str(dest),
    }


# ────────────────────────────────────────────────────────────────────
# Liệt kê / CLI
# ────────────────────────────────────────────────────────────────────
def default_dest() -> Path:
    home = os.getenv("STV_HOME")
    if not home:
        home = "/content/stv_agent" if Path("/content").exists() else str(Path.home() / "stv_agent")
    return Path(home) / "workspace" / "skills"


def list_installed(dest: str | Path) -> list[dict]:
    dest = Path(dest).expanduser()
    out: list[dict] = []
    if not dest.is_dir():
        return out
    for skill_file in sorted(dest.rglob("SKILL.md")):
        rel = skill_file.relative_to(dest)
        if _ignored(rel):
            continue
        text = skill_file.read_text("utf-8", "replace")
        meta, _ = parse_frontmatter(text)
        files = [p for p in skill_file.parent.rglob("*") if p.is_file()]
        out.append({
            "name": choose_name(meta, skill_file.parent.name),
            "description": description_of(text),
            "path": str(skill_file.parent),
            "files": len(files),
            "bytes": sum(p.stat().st_size for p in files),
        })
    return out


def _human(result: dict) -> str:
    lines = []
    if result["installed"]:
        lines.append(f"✅ Đã cài {len(result['installed'])} skill vào {result['dest']}")
        for item in result["installed"]:
            lines.append(
                f"• {item['name']} — {oneline(item.get('description', ''), 100)} "
                f"({item.get('files', 0)} file, {item.get('bytes', 0) / 1024:.0f} KB)"
            )
    if result["skipped"]:
        lines.append(f"⚠️ Bỏ qua {len(result['skipped'])} skill:")
        for item in result["skipped"]:
            lines.append(f"• {item.get('name', '?')}: {item.get('reason', '')}")
    for warning in result.get("warnings", []):
        lines.append(f"ℹ️ {warning}")
    if not result["installed"] and not result["skipped"]:
        lines.append("Không có skill nào được cài.")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Cài Agent Skills vào AISTV")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ins = sub.add_parser("install", help="Cài skill từ GitHub/zip")
    ins.add_argument("source", help="owner/repo[/path], URL GitHub, raw SKILL.md hoặc zip")
    ins.add_argument("--dest", default=str(default_dest()), help="Thư mục skills đích")
    ins.add_argument("--force", action="store_true", help="Ghi đè skill đã có")
    ins.add_argument("--name", help="Đặt tên khác cho skill (chỉ khi cài 1 skill)")
    ins.add_argument("--ref", help="Nhánh/tag/commit")
    ins.add_argument("--allow-restricted", action="store_true",
                     help="Cho phép cài skill tài liệu Anthropic (docx/pdf/pptx/xlsx, giấy phép source-available)")
    ins.add_argument("--json", action="store_true", help="In JSON")

    ls = sub.add_parser("list", help="Liệt kê skill đã cài")
    ls.add_argument("--dest", default=str(default_dest()), help="Thư mục skills")
    ls.add_argument("--json", action="store_true", help="In JSON")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "install":
            result = install(
                args.source, args.dest, force=args.force,
                name=args.name, ref=args.ref,
                allow_restricted=args.allow_restricted,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(_human(result))
            return 0 if (result["installed"] or result["skipped"]) else 1
        items = list_installed(args.dest)
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            if not items:
                print(f"Chưa có skill nào trong {args.dest}")
            for item in items:
                print(f"• {item['name']} — {oneline(item['description'], 100)} ({item['files']} file)")
        return 0
    except SkillError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"❌ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
