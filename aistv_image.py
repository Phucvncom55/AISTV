#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aistv_image.py — Tạo ảnh & sơ đồ tư duy cho bot AI STV.

CLI
  python aistv_image.py "mèo phi hành gia" --style anime --aspect 16:9 --json
  python aistv_image.py --mindmap "Kế hoạch học Python" --json
  python aistv_image.py --list-styles

Provider (tự chọn theo key có sẵn, theo thứ tự):
  1. Gemini  — AISTV_IMAGE_MODEL (mặc định gemini-3.1-flash-image)
               LƯU Ý: API free tier hiện cấp 0 lượt tạo ảnh → cần bật billing.
  2. Cloudflare Workers AI — CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN (có free tier)
  3. Together AI — TOGETHER_API_KEY (model FLUX.1-schnell-Free)
  4. Hugging Face — HF_TOKEN / HUGGINGFACE_API_KEY
"""
import os, sys, re, json, time, base64, random, string, argparse, mimetypes, unicodedata
import urllib.request, urllib.error, urllib.parse
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
HOME = Path(os.getenv("STV_HOME") or (Path.home() / "stv_agent"))
WORKSPACE = Path(os.getenv("AISTV_WORKSPACE") or (HOME / "workspace"))
OUT_DIR = HOME / "generated"
FONT_DIR = REPO_DIR / "seed" / "fonts"
GEMINI_BASE = "https://generativelanguage.googleapis.com"

try:                                     # Windows console mặc định cp1252 → lỗi tiếng Việt
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_MODEL = "gemini-3.1-flash-image"
DEFAULT_FALLBACKS = "gemini-3-pro-image,gemini-2.5-flash-image"


class ImageError(RuntimeError):
    pass


# ── Cấu hình: đọc secret từ env / .env / config.env ───────────────────
def _env_paths():
    override = os.getenv("AISTV_ENV_FILE", "").strip()
    if override:
        return [Path(override).expanduser()]
    cfg = Path(os.getenv("AISTV_CONFIG_DIR", "").strip()
               or (Path.home() / ".config" / "aistv"))
    paths = [REPO_DIR / ".env", Path.cwd() / ".env", cfg / "config.env"]
    if os.getenv("STV_HOME"):
        paths.append(Path(os.environ["STV_HOME"]) / ".env")
    return paths


def _file_value(path: Path, name: str) -> str:
    try:
        if not path.is_file():
            return ""
        for line in path.read_text("utf-8", "replace").splitlines():
            s = line.strip()
            if s.startswith("export "):
                s = s[7:].lstrip()
            if s.startswith(name + "="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def secret(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if val:
        return val
    for path in _env_paths():
        val = _file_value(path, name)
        if val:
            return val
    return ""


def gemini_key() -> str:
    return secret("GEMINI_API_KEY") or secret("GOOGLE_API_KEY")


# ── Phong cách ────────────────────────────────────────────────────────
STYLES = {
    "anime": "anime style, cel shading, vibrant colors, clean line art, detailed background",
    "3d": "3D render, octane render, soft studio lighting, depth of field, high detail",
    "realistic": "photorealistic, natural lighting, sharp focus, 50mm lens, high detail",
    "watercolor": "watercolor painting, soft washes, paper texture, delicate brush strokes",
    "oil": "oil painting, visible brush strokes, rich colors, canvas texture",
    "pixel": "pixel art, 16-bit style, crisp pixels, limited palette",
    "minimal": "minimalist flat design, simple shapes, generous negative space, clean palette",
    "comic": "comic book style, bold ink outlines, halftone shading, dynamic composition",
    "sketch": "pencil sketch, hand-drawn, cross hatching, monochrome",
    "cyberpunk": "cyberpunk, neon lights, futuristic city, teal and magenta palette",
    "poster": "graphic poster design, strong typography layout, bold contrast, print ready",
    "logo": "flat vector logo, simple geometric mark, centered, plain background, no text",
    "infographic": "clean infographic illustration, flat icons, clear visual hierarchy, white background",
    "cartoon": "cartoon illustration, exaggerated shapes, playful, thick outlines",
    "fantasy": "fantasy art, epic lighting, rich atmosphere, highly detailed",
}

STYLE_ALIASES = {
    "hoạt hình": "anime", "hoat hinh": "anime", "manga": "anime",
    "3d": "3d", "ba chiều": "3d",
    "chân thực": "realistic", "chan thuc": "realistic", "thực tế": "realistic", "real": "realistic",
    "màu nước": "watercolor", "mau nuoc": "watercolor", "watercolour": "watercolor",
    "sơn dầu": "oil", "son dau": "oil",
    "pixel": "pixel", "8bit": "pixel", "8-bit": "pixel",
    "tối giản": "minimal", "toi gian": "minimal", "flat": "minimal",
    "truyện tranh": "comic", "truyen tranh": "comic",
    "ký họa": "sketch", "ky hoa": "sketch", "phác thảo": "sketch",
    "tương lai": "cyberpunk", "tuong lai": "cyberpunk", "sci-fi": "cyberpunk",
    "áp phích": "poster", "ap phich": "poster",
    "biểu tượng": "logo", "bieu tuong": "logo",
    "đồ họa thông tin": "infographic", "do hoa thong tin": "infographic",
    "hoạt họa": "cartoon", "hoat hoa": "cartoon",
    "giả tưởng": "fantasy", "gia tuong": "fantasy",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def resolve_style(value: str) -> str:
    if not value:
        return ""
    key = _norm(value)
    if key in STYLES:
        return key
    if key in STYLE_ALIASES:
        return STYLE_ALIASES[key]
    for alias, canon in STYLE_ALIASES.items():
        if _norm(alias) == key:
            return canon
    return ""


ASPECTS = {
    "1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344),
    "4:3": (1152, 864), "3:4": (864, 1152), "3:2": (1248, 832), "2:3": (832, 1248),
}


def build_prompt(prompt: str, style: str = "", kind: str = "image") -> str:
    prompt = (prompt or "").strip()
    extra = STYLES.get(style, "")
    if kind == "infographic":
        tail = "Clean infographic, well organized, readable layout, white background, no watermark."
    elif kind == "mindmap":
        tail = "Mind map diagram, clear hierarchy, readable labels, clean design, white background."
    else:
        tail = "High quality, well composed, sharp details, no watermark, no logo."
    parts = [prompt]
    if extra:
        parts.append(extra)
    parts.append(tail)
    return ". ".join(p.strip(". ") for p in parts if p).strip() + "."


# ── HTTP ──────────────────────────────────────────────────────────────
def _request(url: str, data=None, headers=None, timeout=180, method=None):
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json", **(headers or {})}
        elif isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except Exception as e:
        raise ImageError(f"{type(e).__name__}: {e}") from e


def _json_body(raw: bytes, code: int):
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        text = raw.decode("utf-8", "replace")[:400]
        raise ImageError(f"HTTP {code}: {text}") from None


def _error_text(data, code: int) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or "")
            if "limit: 0" in msg:
                return ("Gemini API free tier KHÔNG cấp lượt tạo ảnh (limit 0). "
                        "Bật billing cho project hoặc dùng provider khác.")
            return msg[:300] or json.dumps(err, ensure_ascii=False)[:300]
        if err:
            return str(err)[:300]
        if data.get("detail"):
            return str(data["detail"])[:300]
    return f"HTTP {code}"


def _save(raw: bytes, mime: str = "", out: str = "") -> Path:
    if out:
        path = Path(out).expanduser()
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        rnd = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(4))
        ext = mimetypes.guess_extension((mime or "").split(";")[0].strip()) or ".png"
        if ext == ".jpe":
            ext = ".jpg"
        path = OUT_DIR / f"img_{stamp}_{rnd}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


# ── Provider: Gemini ──────────────────────────────────────────────────
def _gemini_models() -> list:
    first = secret("AISTV_IMAGE_MODEL") or DEFAULT_MODEL
    fallbacks = secret("AISTV_IMAGE_FALLBACKS") or DEFAULT_FALLBACKS
    models = [first] + [m.strip() for m in fallbacks.split(",") if m.strip()]
    return list(dict.fromkeys(models))


def gemini_image(prompt: str, aspect: str = "1:1", ref: str = "", size: str = ""):
    key = gemini_key()
    if not key:
        raise ImageError("chưa có GEMINI_API_KEY")
    dims = ASPECTS.get(aspect)
    parts = []
    if ref:
        p = Path(ref).expanduser()
        if not p.is_file():
            raise ImageError(f"không thấy ảnh tham chiếu: {ref}")
        mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime,
                                      "data": base64.b64encode(p.read_bytes()).decode("ascii")}})
    parts.append({"text": prompt})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    image_cfg = {}
    if aspect and aspect in ASPECTS and aspect != "1:1":
        image_cfg["aspectRatio"] = aspect
    if size:
        image_cfg["imageSize"] = size
    if image_cfg:
        body["generationConfig"]["imageConfig"] = image_cfg

    last_err = ""
    for model in _gemini_models():
        url = f"{GEMINI_BASE}/v1beta/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
        code, raw, _ = _request(url, body, timeout=240)
        data = _json_body(raw, code)
        if code == 400 and image_cfg and "imageConfig" in str(data):
            body["generationConfig"].pop("imageConfig", None)
            code, raw, _ = _request(url, body, timeout=240)
            data = _json_body(raw, code)
        if code == 404:
            last_err = f"{model}: không có quyền/không tồn tại"
            continue
        if code != 200:
            last_err = f"{model}: {_error_text(data, code)}"
            if code == 429:
                # Hết quota model này → thử model kế tiếp (nếu có)
                continue
            continue
        cands = (data.get("candidates") or [{}])[0]
        content = cands.get("content") or {}
        images = []
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                images.append((base64.b64decode(inline["data"]), mime))
        if images:
            return images[0][0], images[0][1], model
        reason = cands.get("finishReason") or "không có ảnh trả về"
        last_err = f"{model}: {reason}"
    raise ImageError(last_err or "Gemini không trả ảnh")


# ── Provider: Cloudflare / Together / Hugging Face ────────────────────
def _dims(aspect: str):
    w, h = ASPECTS.get(aspect, ASPECTS["1:1"])
    return w, h


def cloudflare_image(prompt: str, aspect: str = "1:1", **_):
    acct = secret("CLOUDFLARE_ACCOUNT_ID")
    token = secret("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        raise ImageError("thiếu CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN")
    model = secret("AISTV_CF_IMAGE_MODEL") or "@cf/black-forest-labs/flux-1-schnell"
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    code, raw, headers = _request(url, {"prompt": prompt, "steps": 4},
                                  {"Authorization": f"Bearer {token}"}, timeout=180)
    ctype = (headers.get("Content-Type") or "").lower()
    if code == 200 and ctype.startswith("image/"):
        return raw, ctype.split(";")[0], model
    data = _json_body(raw, code)
    if code != 200 or not data.get("success", True):
        raise ImageError(_error_text(data, code))
    result = data.get("result") or {}
    b64 = result.get("image") if isinstance(result, dict) else None
    if not b64:
        raise ImageError("Cloudflare không trả ảnh")
    if isinstance(b64, str) and b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    return base64.b64decode(b64), "image/jpeg", model


def together_image(prompt: str, aspect: str = "1:1", **_):
    key = secret("TOGETHER_API_KEY")
    if not key:
        raise ImageError("thiếu TOGETHER_API_KEY")
    model = secret("AISTV_TOGETHER_IMAGE_MODEL") or "black-forest-labs/FLUX.1-schnell-Free"
    w, h = _dims(aspect)
    body = {"model": model, "prompt": prompt, "width": w, "height": h,
            "steps": 4, "n": 1, "response_format": "b64_json"}
    code, raw, _ = _request("https://api.together.xyz/v1/images/generations", body,
                            {"Authorization": f"Bearer {key}"}, timeout=180)
    data = _json_body(raw, code)
    if code != 200:
        raise ImageError(_error_text(data, code))
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), "image/png", model
    if item.get("url"):
        code2, raw2, hdr2 = _request(item["url"], timeout=120)
        if code2 == 200:
            return raw2, (hdr2.get("Content-Type") or "image/jpeg").split(";")[0], model
    raise ImageError("Together không trả ảnh")


def hf_image(prompt: str, aspect: str = "1:1", **_):
    key = secret("HF_TOKEN") or secret("HUGGINGFACE_API_KEY")
    if not key:
        raise ImageError("thiếu HF_TOKEN")
    model = secret("AISTV_HF_IMAGE_MODEL") or "black-forest-labs/FLUX.1-schnell"
    w, h = _dims(aspect)
    url = f"https://router.huggingface.co/hf-inference/models/{model}"
    code, raw, headers = _request(url, {"inputs": prompt, "parameters": {"width": w, "height": h}},
                                  {"Authorization": f"Bearer {key}", "Accept": "image/png"},
                                  timeout=180)
    if code == 400:              # một số model không nhận parameters kích thước
        code, raw, headers = _request(url, {"inputs": prompt},
                                      {"Authorization": f"Bearer {key}", "Accept": "image/png"},
                                      timeout=180)
    ctype = (headers.get("Content-Type") or "").lower()
    if code == 200 and (ctype.startswith("image/") or raw[:4] in (b"\x89PNG", b"\xff\xd8")):
        return raw, ctype.split(";")[0] if ctype.startswith("image/") else "image/png", model
    data = _json_body(raw, code) if raw[:1] in (b"{", b"[") else {}
    raise ImageError(_error_text(data, code) if data else f"HTTP {code}: {raw[:200]!r}")


PROVIDERS = {
    "gemini": (gemini_image, lambda: bool(gemini_key())),
    "cloudflare": (cloudflare_image,
                   lambda: bool(secret("CLOUDFLARE_ACCOUNT_ID") and secret("CLOUDFLARE_API_TOKEN"))),
    "together": (together_image, lambda: bool(secret("TOGETHER_API_KEY"))),
    "hf": (hf_image, lambda: bool(secret("HF_TOKEN") or secret("HUGGINGFACE_API_KEY"))),
}


def generate(prompt: str, style: str = "", aspect: str = "1:1", ref: str = "",
             provider: str = "", out: str = "", size: str = "") -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageError("thiếu nội dung ảnh")
    style_key = resolve_style(style) if style else ""
    full = build_prompt(prompt, style_key, "image")
    wanted = (provider or secret("AISTV_IMAGE_PROVIDER") or "auto").strip().lower()
    if wanted in ("", "auto"):
        order = [name for name, (_, ready) in PROVIDERS.items() if ready()]
        if not order:
            raise ImageError(
                "Chưa có nguồn tạo ảnh nào. Chọn 1 cách:\n"
                "• Bật billing cho Gemini API (dùng đúng model Gemini), hoặc\n"
                "• Thêm CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN (free tier), hoặc\n"
                "• Thêm TOGETHER_API_KEY (FLUX.1-schnell-Free), hoặc\n"
                "• Thêm HF_TOKEN.")
    else:
        order = [wanted]

    errors = []
    for name in order:
        fn, ready = PROVIDERS.get(name, (None, None))
        if not fn:
            errors.append(f"{name}: provider không hợp lệ")
            continue
        if not ready():
            errors.append(f"{name}: chưa cấu hình")
            continue
        try:
            raw, mime, model = fn(full, aspect=aspect, ref=ref, size=size)
            path = _save(raw, mime, out)
            return {"ok": True, "path": str(path), "provider": name, "model": model,
                    "prompt": prompt, "styled": full, "style": style_key,
                    "aspect": aspect, "bytes": len(raw)}
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise ImageError("Không tạo được ảnh. " + " | ".join(errors))


# ── Sơ đồ tư duy: nhờ Gemini lập dàn ý, Pillow vẽ (chữ Việt sắc nét) ──
MINDMAP_PROMPT = """Tạo dàn ý sơ đồ tư duy bằng tiếng Việt cho chủ đề sau:

{subject}

Trả về DUY NHẤT JSON đúng cấu trúc:
{{"title": "tên chủ đề ngắn", "branches": [{{"title": "nhánh", "children": ["ý 1", "ý 2"]}}]}}

Quy tắc: 4-7 nhánh; mỗi nhánh 2-4 ý; mỗi ý tối đa 8 từ; ngắn gọn, khác nhau, đúng trọng tâm.
"""


def _text_models() -> list:
    first = (secret("AISTV_TEXT_MODEL") or secret("WATCH_GEMINI_MODEL")
             or "gemini-3-flash-preview")
    fb = secret("WATCH_GEMINI_FALLBACKS") or "gemini-3.1-flash-lite,gemini-2.5-flash"
    return list(dict.fromkeys([first] + [m.strip() for m in fb.split(",") if m.strip()]))


def _extract_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def mindmap_outline(subject: str) -> dict:
    key = gemini_key()
    if not key:
        raise ImageError("cần GEMINI_API_KEY để lập dàn ý sơ đồ tư duy")
    body = {"contents": [{"role": "user", "parts": [{"text": MINDMAP_PROMPT.format(subject=subject)}]}],
            "generationConfig": {"temperature": 0.5, "responseMimeType": "application/json"}}
    last = ""
    for model in _text_models():
        url = f"{GEMINI_BASE}/v1beta/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
        code, raw, _ = _request(url, body, timeout=120)
        data = _json_body(raw, code)
        if code != 200:
            last = _error_text(data, code)
            continue
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            outline = _extract_json(text)
            return _clean_outline(subject, outline)
        except Exception as e:
            last = f"{model}: JSON lỗi ({e})"
    raise ImageError(last or "không lập được dàn ý")


def _clean_outline(subject: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ImageError("dàn ý không hợp lệ")
    title = str(data.get("title") or subject).strip()[:70]
    branches = []
    for b in (data.get("branches") or [])[:8]:
        if isinstance(b, str):
            b = {"title": b, "children": []}
        if not isinstance(b, dict):
            continue
        bt = str(b.get("title") or "").strip()[:45]
        if not bt:
            continue
        kids = []
        for c in (b.get("children") or [])[:4]:
            cs = str(c).strip()[:52]
            if cs:
                kids.append(cs)
        branches.append({"title": bt, "children": kids})
    if not branches:
        raise ImageError("dàn ý không có nhánh")
    return {"title": title, "branches": branches}


def _font(size: int, bold: bool = False):
    try:
        from PIL import ImageFont
    except Exception:
        raise ImageError("cần cài Pillow: pip install pillow") from None
    names = (["NotoSans-Bold.ttf", "NotoSans-Regular.ttf"] if bold
             else ["NotoSans-Regular.ttf", "NotoSans-Bold.ttf"])
    candidates = [FONT_DIR / n for n in names]
    candidates += [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ]
    for p in candidates:
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list:
    words = str(text or "").split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        trial = cur + " " + w
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines[:3]


def _mix(hex_color: str, white: float) -> tuple:
    c = hex_color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    r = int(r + (255 - r) * white)
    g = int(g + (255 - g) * white)
    b = int(b + (255 - b) * white)
    return (r, g, b)


def _bezier(p0, p1, p2, p3, steps=28):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def render_mindmap(outline: dict, out: str = "") -> Path:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        raise ImageError("cần cài Pillow: pip install pillow") from None

    title = outline.get("title") or "Sơ đồ tư duy"
    branches = outline.get("branches") or []
    palette = ["#2563eb", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]

    f_root = _font(40, True)
    f_branch = _font(26, True)
    f_child = _font(20, False)

    probe = Image.new("RGB", (10, 10))
    d0 = ImageDraw.Draw(probe)

    BR_W, CH_W = 330, 250
    PAD_X, PAD_Y = 18, 12
    LINE_B = 34
    LINE_C = 27

    def box(text, font, width, line_h):
        lines = _wrap(d0, text, font, width - 2 * PAD_X)
        h = len(lines) * line_h + 2 * PAD_Y
        return {"text": text, "lines": lines, "font": font, "w": width, "h": h, "line_h": line_h}

    root = box(title, f_root, 380, 46)
    items = []
    for i, b in enumerate(branches[:8]):
        br = box(b["title"], f_branch, BR_W, LINE_B)
        kids = [box(c, f_child, CH_W, LINE_C) for c in (b.get("children") or [])]
        kids_total = sum(k["h"] for k in kids) + 16 * max(0, len(kids) - 1)
        block_h = max(br["h"], kids_total)
        items.append({"color": palette[i % len(palette)], "branch": br, "kids": kids,
                      "kids_total": kids_total, "block_h": block_h})

    right = items[0::2]
    left = items[1::2]

    def side_height(side):
        return sum(x["block_h"] for x in side) + 70 * max(0, len(side) - 1)

    content_h = max(760, max(side_height(right), side_height(left)) + 220)
    W = 2200
    H = content_h
    img = Image.new("RGB", (W, H), "#f8fafc")
    draw = ImageDraw.Draw(img)

    cx, cy = W // 2, H // 2
    root_x = cx - root["w"] // 2
    root_y = cy - root["h"] // 2

    # nền lưới nhẹ
    for gx in range(0, W, 50):
        draw.line([(gx, 0), (gx, H)], fill="#eef2f7")
    for gy in range(0, H, 50):
        draw.line([(0, gy), (W, gy)], fill="#eef2f7")

    def draw_box(x, y, node, fill, outline, text_color, radius=18):
        draw.rounded_rectangle([x + 3, y + 4, x + node["w"] + 3, y + node["h"] + 4],
                               radius=radius, fill="#e2e8f0")
        draw.rounded_rectangle([x, y, x + node["w"], y + node["h"]],
                               radius=radius, fill=fill, outline=outline, width=3)
        ty = y + PAD_Y
        for line in node["lines"]:
            draw.text((x + node["w"] // 2, ty), line, font=node["font"],
                      fill=text_color, anchor="ma")
            ty += node["line_h"]

    def draw_side(side, sign):
        if not side:
            return
        gap = 70
        total = side_height(side)
        y = cy - total // 2
        for item in side:
            br, kids = item["branch"], item["kids"]
            bx = (cx + 430) if sign > 0 else (cx - 430 - br["w"])
            by = y + item["block_h"] // 2 - br["h"] // 2
            # nối root → branch
            start = (root_x + root["w"] if sign > 0 else root_x, cy)
            end = (bx if sign > 0 else bx + br["w"], by + br["h"] // 2)
            c1 = (start[0] + sign * 120, start[1])
            c2 = (end[0] - sign * 120, end[1])
            draw.line(_bezier(start, c1, c2, end), fill=item["color"], width=5, joint="curve")
            draw_box(bx, by, br, item["color"], item["color"], "#ffffff")
            # children
            ky = y + item["block_h"] // 2 - item["kids_total"] // 2
            for kid in kids:
                kx = (cx + 820) if sign > 0 else (cx - 820 - kid["w"])
                s2 = (bx + br["w"] if sign > 0 else bx, by + br["h"] // 2)
                e2 = (kx if sign > 0 else kx + kid["w"], ky + kid["h"] // 2)
                col = _mix(item["color"], 0.45)
                draw.line(_bezier(s2, (s2[0] + sign * 80, s2[1]), (e2[0] - sign * 80, e2[1]), e2),
                          fill=col, width=3, joint="curve")
                draw_box(kx, ky, kid, "#ffffff", col, "#0f172a", radius=14)
                ky += kid["h"] + 16
            y += item["block_h"] + gap

    draw_side(right, 1)
    draw_side(left, -1)
    draw_box(root_x, root_y, root, "#0f172a", "#0f172a", "#ffffff", radius=24)

    if out:
        path = Path(out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"mindmap_{time.strftime('%Y%m%d_%H%M%S')}_{''.join(random.choice('abcdef0123456789') for _ in range(4))}.png"
    img.save(path, "PNG", optimize=True)
    return path


def make_mindmap(subject: str, out: str = "") -> dict:
    outline = mindmap_outline(subject)
    path = render_mindmap(outline, out)
    return {"ok": True, "path": str(path), "kind": "mindmap", "provider": "gemini+pil",
            "model": "pillow", "title": outline["title"], "prompt": subject,
            "branches": outline["branches"], "bytes": path.stat().st_size}


def main():
    ap = argparse.ArgumentParser(description="Tạo ảnh / sơ đồ tư duy cho AI STV")
    ap.add_argument("prompt", nargs="?", default="", help="mô tả ảnh hoặc chủ đề")
    ap.add_argument("--mindmap", metavar="TOPIC", default="", help="vẽ sơ đồ tư duy cho chủ đề")
    ap.add_argument("--style", default="", help="anime, 3d, watercolor, pixel, minimal, ...")
    ap.add_argument("--aspect", default="1:1", help="1:1, 16:9, 9:16, 4:3, 3:4")
    ap.add_argument("--ref", default="", help="ảnh tham chiếu (chỉ Gemini)")
    ap.add_argument("--size", default="", help="1K / 2K / 4K (Gemini 3)")
    ap.add_argument("--provider", default="", help="gemini | cloudflare | together | hf | auto")
    ap.add_argument("--out", default="", help="đường dẫn file kết quả")
    ap.add_argument("--json", action="store_true", help="in JSON")
    ap.add_argument("--list-styles", action="store_true", help="liệt kê phong cách")
    args = ap.parse_args()

    if args.list_styles:
        for name, desc in STYLES.items():
            print(f"{name:12s} {desc}")
        return 0

    try:
        if args.mindmap:
            res = make_mindmap(args.mindmap, args.out)
        elif args.prompt:
            res = generate(args.prompt, args.style, args.aspect, args.ref,
                           args.provider, args.out, args.size)
        else:
            ap.error("cần mô tả ảnh, hoặc dùng --mindmap <chủ đề>")
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"❌ {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(res["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
