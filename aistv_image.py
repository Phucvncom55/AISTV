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
import os, sys, re, json, time, base64, math, random, string, uuid, argparse, mimetypes, unicodedata
import urllib.request, urllib.error, urllib.parse
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
HOME = Path(os.getenv("STV_HOME") or (Path.home() / "stv_agent"))
WORKSPACE = Path(os.getenv("AISTV_WORKSPACE") or (HOME / "workspace"))
OUT_DIR = HOME / "generated"
FONT_DIR = REPO_DIR / "seed" / "fonts"
SECRETS_DIR = REPO_DIR / ".secrets"
GEMINI_BASE = "https://generativelanguage.googleapis.com"

# File bí mật dùng chung với aistv_cloudflare.py (không in ra chat).
SECRET_FILES = {
    "CLOUDFLARE_API_TOKEN": ("cloudflare_token",),
    "CLOUDFLARE_ACCOUNT_ID": ("cloudflare_account_id",),
}

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
    for filename in SECRET_FILES.get(name, ()):
        path = SECRETS_DIR / filename
        try:
            if path.is_file():
                val = path.read_text("utf-8", "replace").strip()
                if val:
                    return val
        except Exception:
            pass
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
        errs = data.get("errors")
        if isinstance(errs, list) and errs:
            first = errs[0]
            msg = str(first.get("message") if isinstance(first, dict) else first)
            low = msg.lower()
            if "daily free allocation" in low or "used up your daily free" in low:
                return ("Cloudflare đã dùng hết 10.000 neurons miễn phí hôm nay "
                        "(reset 00:00 UTC = 07:00 giờ Việt Nam). "
                        "Nâng Workers Paid hoặc thử lại sau.")
            if "neurons" in low and "limit" in low:
                return msg[:300]
            return msg[:300]
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


def gemini_image(prompt: str, aspect: str = "1:1", ref: str = "", size: str = "", **_):
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


# ── Provider: Cloudflare Workers AI ───────────────────────────────────
CF_API = "https://api.cloudflare.com/client/v4"
CF_MODELS = {
    "flux-2-dev": "@cf/black-forest-labs/flux-2-dev",
    "flux-2-klein-9b": "@cf/black-forest-labs/flux-2-klein-9b",
    "flux-2-klein-4b": "@cf/black-forest-labs/flux-2-klein-4b",
    "flux-1-schnell": "@cf/black-forest-labs/flux-1-schnell",
    "sdxl": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "sdxl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
    "phoenix": "@cf/leonardo/phoenix-1.0",
    "lucid": "@cf/leonardo/lucid-origin",
    "dreamshaper": "@cf/lykon/dreamshaper-8-lcm",
}
CF_MODEL_ALIASES = {
    "dev": "flux-2-dev", "flux2": "flux-2-dev", "flux-2": "flux-2-dev",
    "flux 2": "flux-2-dev", "flux2dev": "flux-2-dev",
    "klein": "flux-2-klein-9b", "klein9b": "flux-2-klein-9b",
    "flux-2-klein": "flux-2-klein-9b", "flux2klein": "flux-2-klein-9b",
    "klein4b": "flux-2-klein-4b", "schnell": "flux-1-schnell",
    "flux1": "flux-1-schnell", "flux-1": "flux-1-schnell",
    "flux": "flux-1-schnell", "fast": "flux-1-schnell", "nhanh": "flux-1-schnell",
    "sd-xl": "sdxl", "sdxl-base": "sdxl", "lightning": "sdxl-lightning",
}

CF_PHOTO_HINTS = ("chan that", "photorealistic", "realistic", "anh chup", "buc anh",
                  "chup anh", "chup hinh", "chan dung", "buc hinh", "nhu anh chup",
                  "4k", "8k", "cinematic", "dien anh", "chi tiet cao")
CF_HQ_HINTS = ("sieu thuc", "chat luong cao nhat", "cao cap nhat", "chi tiet nhat",
               "sac net nhat", "8k", "top quality", "best quality")


def _dims(aspect: str):
    w, h = ASPECTS.get(aspect, ASPECTS["1:1"])
    return w, h


def _cf_model_key(value: str) -> str:
    text = _norm(value or "").replace("_", "-")
    if not text:
        return ""
    if text.startswith("@cf/"):
        for key, model_id in CF_MODELS.items():
            if _norm(model_id) == text:
                return key
        return ""
    flat = text.replace(" ", "-")
    if flat in CF_MODELS:
        return flat
    if flat in CF_MODEL_ALIASES:
        return CF_MODEL_ALIASES[flat]
    if text in CF_MODEL_ALIASES:
        return CF_MODEL_ALIASES[text]
    for key in CF_MODELS:
        if flat in key or key in flat:
            return key
    return ""


def _cf_chain(style: str, kind: str, model: str, prompt: str) -> list:
    explicit = (_cf_model_key(model)
                or _cf_model_key(secret("AISTV_CF_IMAGE_MODEL")))
    hint = _norm(prompt)
    if explicit:
        chain = [explicit]
        order = ("flux-2-klein-9b", "flux-1-schnell", "flux-2-dev")
    else:
        photo = any(k in hint for k in CF_PHOTO_HINTS)
        hq = any(k in hint for k in CF_HQ_HINTS)
        if hq:
            first = "flux-2-dev"
            order = ("flux-2-klein-9b", "flux-1-schnell")
        elif style in ("realistic", "poster", "logo") or (style == "" and photo):
            first = "flux-2-klein-9b"
            order = ("flux-1-schnell", "flux-2-dev")
        else:
            first = "flux-1-schnell"
            order = ("flux-2-klein-9b", "flux-2-dev")
        chain = [first]
    for key in order:
        if key not in chain:
            chain.append(key)
    return chain


def _cf_multipart(model: str, fields: dict):
    token = secret("CLOUDFLARE_API_TOKEN")
    acct = secret("CLOUDFLARE_ACCOUNT_ID")
    boundary = "----aistv" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n".encode("utf-8"))
    body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")
    url = f"{CF_API}/accounts/{acct}/ai/run/{model}"
    return _request(url, body, {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }, timeout=300)


def _cf_image_bytes(code: int, raw: bytes, headers: dict):
    ctype = (headers.get("Content-Type") or "").lower()
    if code == 200 and ctype.startswith("image/"):
        return raw, ctype.split(";")[0]
    data = _json_body(raw, code)
    if code != 200:
        raise ImageError(_error_text(data, code))
    result = data.get("result")
    b64 = None
    if isinstance(result, dict):
        b64 = result.get("image") or result.get("img") or result.get("b64_json")
        if not b64 and isinstance(result.get("images"), list) and result["images"]:
            b64 = result["images"][0]
    elif isinstance(result, str) and len(result) > 512:
        b64 = result
    if not b64:
        raise ImageError("Cloudflare không trả ảnh")
    if isinstance(b64, str) and b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        return base64.b64decode(b64), "image/jpeg"
    except Exception as e:
        raise ImageError(f"dữ liệu ảnh hỏng: {e}") from None


def cloudflare_image(prompt: str, aspect: str = "1:1", style: str = "",
                     kind: str = "image", model: str = "", **_):
    acct = secret("CLOUDFLARE_ACCOUNT_ID")
    token = secret("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        raise ImageError("thiếu CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN")
    w, h = _dims(aspect)
    errors = []
    for key in _cf_chain(style, kind, model, prompt):
        model_id = CF_MODELS[key]
        try:
            if key.startswith("flux-2"):
                fields = {"prompt": prompt, "width": str(w), "height": str(h)}
                if key == "flux-2-dev":
                    steps = int(secret("AISTV_CF_STEPS") or 20)
                    fields["steps"] = str(max(4, min(50, steps)))
                code, raw, headers = _cf_multipart(model_id, fields)
            else:
                payload = {"prompt": prompt}
                if key == "flux-1-schnell":
                    payload["steps"] = 4
                else:
                    payload.update({"width": w, "height": h, "num_steps": 20})
                url = f"{CF_API}/accounts/{acct}/ai/run/{model_id}"
                code, raw, headers = _request(
                    url, payload, {"Authorization": f"Bearer {token}"}, timeout=300)
            image, mime = _cf_image_bytes(code, raw, headers)
            return image, mime, model_id
        except Exception as e:
            message = str(e)
            errors.append(f"{key}: {message}")
            if "10.000 neurons" in message:
                break          # hết hạn mức chung -> các model CF khác cũng lỗi
    raise ImageError("Cloudflare: " + " | ".join(errors))


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


def pollinations_image(prompt: str, aspect: str = "1:1", **_):
    """Pollinations.ai — miễn phí, KHÔNG cần API key (lưới an toàn cuối cùng)."""
    w, h = _dims(aspect)
    model = secret("AISTV_POLLINATIONS_MODEL") or "flux"
    q = urllib.parse.urlencode({"width": w, "height": h, "model": model,
                                "nologo": "true", "enhance": "false", "private": "true"})
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt[:1800])}?{q}"
    last = ""
    for attempt in range(3):
        try:
            code, raw, headers = _request(url, timeout=120)
        except ImageError as e:
            last = str(e)
            time.sleep(5)
            continue
        ctype = (headers.get("Content-Type") or "").lower()
        if code == 200 and (ctype.startswith("image/") or raw[:4] in (b"\x89PNG", b"\xff\xd8")):
            return raw, (ctype.split(";")[0] if ctype.startswith("image/") else "image/jpeg"), f"pollinations/{model}"
        detail = raw.decode("utf-8", "replace")[:300]
        last = f"HTTP {code}: {detail}"
        if attempt < 2:
            # Free tier: 1 ảnh / 45 giây / IP -> đọc "Retry after Ns" nhưng không chờ quá lâu
            m = re.search(r"[Rr]etry after (\d+)\s*s", detail)
            time.sleep(min(int(m.group(1)) + 2, 12) if m else 5 * (attempt + 1))
    raise ImageError(f"Pollinations không trả ảnh ({last[:180]})")


PROVIDERS = {
    # Cloudflare đứng đầu: flux-2 cho ảnh đúng mô tả, có free tier.
    "cloudflare": (cloudflare_image,
                   lambda: bool(secret("CLOUDFLARE_ACCOUNT_ID") and secret("CLOUDFLARE_API_TOKEN"))),
    "gemini": (gemini_image, lambda: bool(gemini_key())),
    "together": (together_image, lambda: bool(secret("TOGETHER_API_KEY"))),
    "hf": (hf_image, lambda: bool(secret("HF_TOKEN") or secret("HUGGINGFACE_API_KEY"))),
    # Không cần key -> luôn sẵn sàng, đứng cuối để làm lưới an toàn.
    "pollinations": (pollinations_image, lambda: True),
}


def generate(prompt: str, style: str = "", aspect: str = "1:1", ref: str = "",
             provider: str = "", out: str = "", size: str = "",
             kind: str = "image", model: str = "") -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageError("thiếu nội dung ảnh")
    style_key = resolve_style(style) if style else ""
    full = build_prompt(prompt, style_key, kind)
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
            raw, mime, used_model = fn(full, aspect=aspect, ref=ref, size=size,
                                       style=style_key, kind=kind, model=model)
            path = _save(raw, mime, out)
            return {"ok": True, "path": str(path), "provider": name, "model": used_model,
                    "prompt": prompt, "styled": full, "style": style_key,
                    "aspect": aspect, "kind": kind, "bytes": len(raw)}
        except Exception as e:
            errors.append(f"{name}: {e}")
    joined = " | ".join(errors)
    if "10.000 neurons" in joined:
        raise ImageError(
            "Hết hạn mức miễn phí Cloudflare hôm nay (10.000 neurons, "
            "reset 07:00 giờ Việt Nam). Nâng Workers Paid hoặc thêm "
            "TOGETHER_API_KEY / HF_TOKEN để dùng nguồn khác.")
    raise ImageError("Không tạo được ảnh. " + joined[:1200])


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


def _gemini_text(prompt: str) -> str:
    key = gemini_key()
    if not key:
        raise ImageError("chưa có GEMINI_API_KEY")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
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
            if text.strip():
                return text
        except Exception as e:
            last = f"{model}: {e}"
    raise ImageError(last or "Gemini không trả lời")


def _cf_text(prompt: str, max_tokens: int = 1600, temperature: float = 0.45) -> str:
    acct = secret("CLOUDFLARE_ACCOUNT_ID")
    token = secret("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        raise ImageError("thiếu CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN")
    models = [m.strip() for m in (secret("AISTV_CF_TEXT_MODEL")
              or "@cf/zai-org/glm-5.3-flash,@cf/qwen/qwen3-30b-a3b-fp8").split(",") if m.strip()]
    payload = {"messages": [{"role": "user", "content": prompt}],
               "temperature": temperature, "max_tokens": max_tokens}
    last = ""
    for model in models:
        url = f"{CF_API}/accounts/{acct}/ai/run/{model}"
        code, raw, _ = _request(url, payload,
                                {"Authorization": f"Bearer {token}"}, timeout=150)
        data = _json_body(raw, code)
        if code != 200:
            last = _error_text(data, code)
            continue
        result = data.get("result")
        text = ""
        if isinstance(result, dict):
            text = result.get("response") or result.get("text") or ""
        elif isinstance(result, str):
            text = result
        if isinstance(text, str) and text.strip():
            return text
        last = "không có nội dung"
    raise ImageError(last or "Cloudflare text không trả lời")


def _outline_json(prompt_text: str, cleaner, subject: str) -> dict:
    errors = []
    for name, fn in (("gemini", _gemini_text), ("cloudflare", _cf_text)):
        try:
            return cleaner(subject, _extract_json(fn(prompt_text)))
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise ImageError("Không lập được dàn ý (" + " | ".join(errors) + ")")


def mindmap_outline(subject: str) -> dict:
    return _outline_json(MINDMAP_PROMPT.format(subject=subject), _clean_outline, subject)


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
    if len(lines) >= 2 and len(lines[-1].split()) == 1 and len(lines[-2].split()) > 1:
        prev = lines[-2].split()
        trial_prev = " ".join(prev[:-1])
        trial_last = prev[-1] + " " + lines[-1]
        if (draw.textlength(trial_prev, font=font) <= max_width
                and draw.textlength(trial_last, font=font) <= max_width):
            lines[-2] = trial_prev
            lines[-1] = trial_last
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
    return {"ok": True, "path": str(path), "kind": "mindmap", "provider": "ai+pil",
            "model": "pillow", "title": outline["title"], "prompt": subject,
            "branches": outline["branches"], "bytes": path.stat().st_size}


# ── Infographic + biểu đồ: dàn ý bằng AI, chữ Việt vẽ bằng Pillow ─────
INFO_PROMPT = """Bạn là chuyên gia thiết kế infographic. Tạo nội dung infographic tiếng Việt cho chủ đề:

{subject}

Trả về DUY NHẤT JSON đúng cấu trúc:
{{"title": "tiêu đề ngắn", "subtitle": "một dòng phụ đề", "sections": [{{"heading": "tên mục", "text": "giải thích", "metric": ""}}]}}

Quy tắc: 4-6 mục; heading tối đa 6 từ; text 12-24 từ, cụ thể và khác nhau; metric chỉ điền khi có số liệu ấn tượng (vd "80%", "3 bước"), nếu không để chuỗi rỗng.
"""

CHART_PROMPT = """Từ nội dung sau, trích xuất dữ liệu để vẽ một biểu đồ tiếng Việt:

{subject}

Trả về DUY NHẤT JSON đúng cấu trúc:
{{"title": "tiêu đề", "type": "bar|line|pie", "unit": "đơn vị", "labels": ["mốc 1", "mốc 2"], "series": [{{"name": "tên chuỗi", "values": [1, 2]}}], "note": ""}}

Quy tắc:
- labels và values phải cùng độ dài; values là số, không kèm đơn vị hay dấu %.
- pie chỉ dùng khi các phần là thành phần của một tổng.
- Nếu người dùng không nêu số liệu cụ thể, hãy tạo số liệu minh họa hợp lý và ghi note = "Số liệu minh họa".
- Nếu người dùng nêu số liệu, note để chuỗi rỗng.
"""

PALETTE = ["#2563eb", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]


def _clean_infographic(subject: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ImageError("nội dung infographic không hợp lệ")
    title = str(data.get("title") or subject).strip()[:90] or "Infographic"
    subtitle = str(data.get("subtitle") or "").strip()[:140]
    sections = []
    for item in (data.get("sections") or [])[:6]:
        if isinstance(item, str):
            item = {"heading": item, "text": ""}
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or "").strip()[:60]
        text = str(item.get("text") or "").strip()[:220]
        metric = str(item.get("metric") or "").strip()[:14]
        if heading or text:
            sections.append({"heading": heading, "text": text, "metric": metric})
    if len(sections) < 2:
        raise ImageError("infographic cần ít nhất 2 mục")
    return {"title": title, "subtitle": subtitle, "sections": sections}


def _num(value) -> float:
    if isinstance(value, bool):
        raise ValueError("bool")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace(" ", "")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        raise ValueError(f"không phải số: {value!r}")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except Exception:
        raise ValueError(f"không phải số: {value!r}") from None


def _clean_chart(subject: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ImageError("dữ liệu biểu đồ không hợp lệ")
    labels = [str(x).strip()[:40] for x in (data.get("labels") or []) if str(x).strip()]
    series = []
    for item in (data.get("series") or [])[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "Giá trị").strip()[:40]
        values = []
        for v in (item.get("values") or []):
            try:
                values.append(_num(v))
            except Exception:
                values.append(0.0)
        if values:
            series.append({"name": name, "values": values})
    if not labels or not series:
        raise ImageError("không đủ nhãn/số liệu để vẽ biểu đồ")
    count = min([len(labels)] + [len(s["values"]) for s in series])
    if count < 2:
        raise ImageError("biểu đồ cần ít nhất 2 mốc dữ liệu")
    labels = labels[:count]
    series = [{"name": s["name"], "values": s["values"][:count]} for s in series]
    ctype = _norm(str(data.get("type") or "bar"))
    if ctype not in ("bar", "line", "pie"):
        ctype = "bar"
    if ctype == "pie":
        series = series[:1]
        if sum(abs(v) for v in series[0]["values"]) <= 0:
            raise ImageError("biểu đồ tròn cần tổng dương")
    return {
        "title": str(data.get("title") or subject).strip()[:90] or "Biểu đồ",
        "type": ctype,
        "unit": str(data.get("unit") or "").strip()[:24],
        "labels": labels,
        "series": series,
        "note": str(data.get("note") or "").strip()[:120],
    }


def _gradient_bg(img, top="#f7f9ff", bottom="#e9f0fb"):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    t = tuple(int(top.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(bottom.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    h = img.height
    for y in range(h):
        f = y / max(1, h - 1)
        color = tuple(int(t[i] + (b[i] - t[i]) * f) for i in range(3))
        draw.line([(0, y), (img.width, y)], fill=color)
    return draw


def render_infographic(data: dict, out: str = "") -> Path:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        raise ImageError("cần cài Pillow: pip install pillow") from None

    W, M, GAP = 1600, 72, 32
    card_w = (W - 2 * M - GAP) // 2
    pad = 32
    f_kicker = _font(22, True)
    f_title = _font(56, True)
    f_sub = _font(27)
    f_head = _font(32, True)
    f_body = _font(23)
    f_metric = _font(44, True)
    f_num = _font(22, True)
    f_foot = _font(19)

    title = data["title"]
    subtitle = data.get("subtitle") or ""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title_lines = _wrap(probe, title, f_title, W - 2 * M)[:3]
    sub_lines = _wrap(probe, subtitle, f_sub, W - 2 * M - 40)[:2] if subtitle else []

    cards = []
    for i, section in enumerate(data["sections"]):
        metric = section.get("metric") or ""
        metric_font = f_metric
        metric_w = 0
        if metric:
            metric_w = probe.textlength(metric, font=f_metric)
            if metric_w > 230:
                metric_font = _font(32, True)
                metric_w = probe.textlength(metric, font=metric_font)
        reserve = metric_w + 44 if metric else 0
        head_w = card_w - 2 * pad - 70 - reserve
        head_lines = _wrap(probe, section["heading"], f_head, max(120, head_w))[:2]
        body_lines = _wrap(probe, section["text"], f_body, card_w - 2 * pad)[:4] if section["text"] else []
        head_h = max(52, len(head_lines) * 38)
        body_y = pad + head_h + 20
        height = body_y + len(body_lines) * 31 + 26
        cards.append({
            "color": PALETTE[i % len(PALETTE)], "num": i + 1,
            "heading": head_lines, "body": body_lines, "metric": metric,
            "metric_font": metric_font, "metric_w": metric_w,
            "h": max(200, height), "body_y": body_y,
        })

    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    row_hs = [max(c["h"] for c in row) for row in rows]
    header_h = 180 + len(title_lines) * 72 + (len(sub_lines) * 38 + 22 if sub_lines else 0)
    H = header_h + sum(row_hs) + GAP * max(0, len(rows) - 1) + 120

    img = Image.new("RGB", (W, H), "#f7f9ff")
    draw = _gradient_bg(img)

    draw.ellipse([W - 260, -120, W + 120, 260], fill="#dbeafe")
    draw.ellipse([-110, H - 200, 130, H + 40], fill="#e0f2fe")

    draw.text((M, 54), "AI STV", font=f_kicker, fill="#2563eb")
    kw = draw.textlength("AI STV", font=f_kicker)
    draw.text((M + kw + 12, 54), "•  INFOGRAPHIC", font=f_kicker, fill="#64748b")

    y = 96
    for line in title_lines:
        draw.text((M, y), line, font=f_title, fill="#0f172a")
        y += 72
    y += 6
    for line in sub_lines:
        draw.text((M, y), line, font=f_sub, fill="#475569")
        y += 38

    y = header_h
    for row, row_h in zip(rows, row_hs):
        for col, card in enumerate(row):
            x = M + col * (card_w + GAP)
            draw.rounded_rectangle([x + 6, y + 8, x + card_w + 6, y + row_h + 8],
                                   radius=24, fill="#dbe4f0")
            draw.rounded_rectangle([x, y, x + card_w, y + row_h],
                                   radius=24, fill="#ffffff")
            draw.rounded_rectangle([x, y, x + 10, y + row_h], radius=5, fill=card["color"])

            bx, by = x + pad, y + pad
            draw.rounded_rectangle([bx, by, bx + 52, by + 52], radius=14, fill=card["color"])
            num = str(card["num"])
            nw = draw.textlength(num, font=f_num)
            draw.text((bx + 26 - nw / 2, by + 26), num, font=f_num, fill="#ffffff", anchor="mm")

            head_x = bx + 70
            ty = by + 4
            for line in card["heading"]:
                draw.text((head_x, ty), line, font=f_head, fill="#0f172a")
                ty += 38

            if card["metric"]:
                draw.text((x + card_w - pad - card["metric_w"], by - 2), card["metric"],
                          font=card["metric_font"], fill=card["color"])

            ty = y + card["body_y"] + 4
            for line in card["body"]:
                draw.text((x + pad, ty), line, font=f_body, fill="#334155")
                ty += 31
        y += row_h + GAP

    draw.text((M, H - 58), "Tạo bởi AI STV", font=f_foot, fill="#94a3b8")
    foot = data.get("footer") or ""
    if foot:
        fw = draw.textlength(foot, font=f_foot)
        draw.text((W - M - fw, H - 58), foot, font=f_foot, fill="#94a3b8")

    if out:
        path = Path(out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"infographic_{time.strftime('%Y%m%d_%H%M%S')}_{''.join(random.choice('abcdef0123456789') for _ in range(4))}.png"
    img.save(path, "PNG", optimize=True)
    return path


def _nice_scale(value: float):
    if value <= 0:
        return 10.0, 5
    rough = value / 5
    exp = 10 ** math.floor(math.log10(rough))
    step = 10 * exp
    for mult in (1, 2, 2.5, 5, 10):
        if mult * exp >= rough:
            step = mult * exp
            break
    ticks = max(2, int(math.ceil(value / step - 1e-9)))
    return step * ticks, ticks


def _fmt_num(value: float, unit: str = "") -> str:
    if abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", ".")
    else:
        text = f"{value:.1f}".replace(".", ",")
    return text + unit


def render_chart(data: dict, out: str = "") -> Path:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        raise ImageError("cần cài Pillow: pip install pillow") from None

    W, H = 1600, 1000
    M = 90
    f_kicker = _font(22, True)
    f_title = _font(52, True)
    f_note = _font(24)
    f_tick = _font(21)
    f_label = _font(19)
    f_val = _font(19, True)
    f_legend = _font(20)

    img = Image.new("RGB", (W, H), "#ffffff")
    draw = _gradient_bg(img, "#ffffff", "#f4f7fd")
    draw.text((M, 46), "AI STV", font=f_kicker, fill="#2563eb")
    kw = draw.textlength("AI STV", font=f_kicker)
    draw.text((M + kw + 12, 46), "•  BIỂU ĐỒ", font=f_kicker, fill="#64748b")

    title_lines = _wrap(draw, data["title"], f_title, W - 2 * M)[:2]
    ty = 86
    for line in title_lines:
        draw.text((M, ty), line, font=f_title, fill="#0f172a")
        ty += 60
    note = data.get("note") or ""
    if note:
        draw.text((M, ty + 2), note, font=f_note, fill="#b45309")
        ty += 38
    unit = data.get("unit") or ""
    top = ty + 64
    if unit:
        ux = W - M - draw.textlength("Đơn vị: " + unit, font=f_tick)
        draw.text((ux, top - 42), "Đơn vị: " + unit, font=f_tick, fill="#64748b")

    ctype = data["type"]
    series = data["series"]
    labels = data["labels"]
    bottom = H - 130
    left = M + 70
    right = W - M

    if ctype == "pie":
        values = series[0]["values"]
        total = sum(abs(v) for v in values)
        cx, cy, radius = 520, (top + bottom) // 2 + 10, 265
        start = -90.0
        for i, value in enumerate(values):
            extent = 360.0 * abs(value) / total
            color = PALETTE[i % len(PALETTE)]
            draw.pieslice([cx - radius, cy - radius, cx + radius, cy + radius],
                          start=start, end=start + extent, fill=color,
                          outline="#ffffff", width=3)
            if extent > 14:
                mid = math.radians(start + extent / 2)
                tx = cx + math.cos(mid) * radius * 0.62
                ty = cy + math.sin(mid) * radius * 0.62
                pct = f"{abs(value) / total * 100:.0f}%"
                pw = draw.textlength(pct, font=f_val)
                draw.text((tx - pw / 2, ty), pct, font=f_val, fill="#ffffff", anchor="mm")
            start += extent

        lx = cx + radius + 90
        ly = cy - (len(labels) * 58) // 2
        for i, label in enumerate(labels):
            color = PALETTE[i % len(PALETTE)]
            draw.rounded_rectangle([lx, ly + 3, lx + 22, ly + 25], radius=5, fill=color)
            draw.text((lx + 36, ly), label, font=f_legend, fill="#0f172a")
            val = series[0]["values"][i]
            draw.text((lx + 36, ly + 27), _fmt_num(val, unit), font=f_tick, fill="#64748b")
            ly += 58
    else:
        values_all = [v for s in series for v in s["values"]]
        low = min(0.0, min(values_all))
        high, ticks = _nice_scale(max(values_all) if values_all else 10)
        if high <= low:
            high = low + 10
        plot_w = right - left
        plot_h = bottom - top

        def y_of(v):
            return bottom - (v - low) / (high - low) * plot_h

        for i in range(ticks + 1):
            value = low + (high - low) * i / ticks
            gy = y_of(value)
            draw.line([(left, gy), (right, gy)], fill="#e2e8f0", width=2)
            text = _fmt_num(value)
            tw = draw.textlength(text, font=f_tick)
            draw.text((left - 18 - tw, gy - 12), text, font=f_tick, fill="#64748b")

        draw.line([(left, top), (left, bottom)], fill="#94a3b8", width=2)
        draw.line([(left, bottom), (right, bottom)], fill="#94a3b8", width=2)

        if series and len(series) > 1:
            lx = M
            for i, s in enumerate(series):
                label = s["name"]
                draw.rounded_rectangle([lx, top - 44, lx + 18, top - 26], radius=4,
                                       fill=PALETTE[i % len(PALETTE)])
                draw.text((lx + 26, top - 48), label, font=f_legend, fill="#334155")
                lx += draw.textlength(label, font=f_legend) + 54

        group_w = plot_w / len(labels)
        if ctype == "bar":
            bar_w = max(10, group_w * 0.68 / len(series))
            for si, s in enumerate(series):
                color = PALETTE[si % len(PALETTE)]
                for i, value in enumerate(s["values"]):
                    x0 = left + i * group_w + (group_w - bar_w * len(series)) / 2 + si * bar_w
                    y0 = y_of(max(0, value))
                    height = abs(y_of(value) - y_of(0))
                    draw.rounded_rectangle([x0, y0, x0 + bar_w, y0 + height],
                                           radius=6, fill=color)
                    text = _fmt_num(value, unit)
                    tw = draw.textlength(text, font=f_val)
                    draw.text((x0 + bar_w / 2 - tw / 2, y0 - 28), text,
                              font=f_val, fill="#0f172a")
        else:
            for si, s in enumerate(series):
                color = PALETTE[si % len(PALETTE)]
                points = []
                for i, value in enumerate(s["values"]):
                    points.append((left + i * group_w + group_w / 2, y_of(value)))
                if len(points) > 1:
                    draw.line(points, fill=color, width=5, joint="curve")
                for (px, py), value in zip(points, s["values"]):
                    draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill="#ffffff",
                                 outline=color, width=5)
                    text = _fmt_num(value, unit)
                    tw = draw.textlength(text, font=f_val)
                    draw.text((px - tw / 2, py - 34), text, font=f_val, fill="#0f172a")

        for i, label in enumerate(labels):
            cx = left + i * group_w + group_w / 2
            lines = _wrap(draw, label, f_label, max(60, group_w - 12))[:2]
            ly = bottom + 16
            for line in lines:
                lw = draw.textlength(line, font=f_label)
                draw.text((cx - lw / 2, ly), line, font=f_label, fill="#334155")
                ly += 26

    draw.text((M, H - 54), "Tạo bởi AI STV", font=_font(19), fill="#94a3b8")

    if out:
        path = Path(out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"chart_{time.strftime('%Y%m%d_%H%M%S')}_{''.join(random.choice('abcdef0123456789') for _ in range(4))}.png"
    img.save(path, "PNG", optimize=True)
    return path


def make_infographic(subject: str, out: str = "") -> dict:
    outline = _outline_json(INFO_PROMPT.format(subject=subject), _clean_infographic, subject)
    path = render_infographic(outline, out)
    return {"ok": True, "path": str(path), "kind": "infographic", "provider": "ai+pil",
            "model": "pillow", "title": outline["title"], "prompt": subject,
            "sections": outline["sections"], "bytes": path.stat().st_size}


def make_chart(subject: str, out: str = "") -> dict:
    outline = _outline_json(CHART_PROMPT.format(subject=subject), _clean_chart, subject)
    path = render_chart(outline, out)
    return {"ok": True, "path": str(path), "kind": "chart", "provider": "ai+pil",
            "model": "pillow", "title": outline["title"], "prompt": subject,
            "chart_type": outline["type"], "labels": outline["labels"],
            "series": outline["series"], "bytes": path.stat().st_size}


def main():
    ap = argparse.ArgumentParser(description="Tạo ảnh / sơ đồ / biểu đồ cho AI STV")
    ap.add_argument("prompt", nargs="?", default="", help="mô tả ảnh hoặc chủ đề")
    ap.add_argument("--mindmap", metavar="TOPIC", default="", help="vẽ sơ đồ tư duy cho chủ đề")
    ap.add_argument("--infographic", metavar="TOPIC", default="", help="vẽ infographic cho chủ đề")
    ap.add_argument("--chart", metavar="DATA", default="", help="vẽ biểu đồ từ dữ liệu/mô tả")
    ap.add_argument("--style", default="", help="anime, 3d, watercolor, pixel, minimal, ...")
    ap.add_argument("--aspect", default="1:1", help="1:1, 16:9, 9:16, 4:3, 3:4")
    ap.add_argument("--ref", default="", help="ảnh tham chiếu (chỉ Gemini)")
    ap.add_argument("--size", default="", help="1K / 2K / 4K (Gemini 3)")
    ap.add_argument("--model", default="", help="flux-2-dev | flux-2-klein-9b | flux-1-schnell | ...")
    ap.add_argument("--provider", default="", help="cloudflare | gemini | together | hf | auto")
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
        elif args.infographic:
            res = make_infographic(args.infographic, args.out)
        elif args.chart:
            res = make_chart(args.chart, args.out)
        elif args.prompt:
            res = generate(args.prompt, args.style, args.aspect, args.ref,
                           args.provider, args.out, args.size, model=args.model)
        else:
            ap.error("cần mô tả ảnh, hoặc dùng --mindmap / --infographic / --chart")
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
