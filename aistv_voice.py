#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aistv_voice.py — Nghe (STT) và nói (TTS) hoàn toàn local.

TTS: Piper (giọng tiếng Việt, tự nhiên) → ffmpeg chuyển OGG/Opus cho Telegram.
STT: faster-whisper (Python) → whisper CLI → whisper.cpp.

Cài
  # Piper (Linux/macOS)
  pip install piper-tts
  mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
  curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx
  curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json

  # STT
  pip install faster-whisper          # nhẹ, tự tải model
  # hoặc: pip install openai-whisper  (nặng hơn, cần ffmpeg)

Dùng
  python aistv_voice.py check
  python aistv_voice.py tts "Xin chào, mình là AI STV" -o out.ogg
  python aistv_voice.py stt voice.ogg --json
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HOME = Path(os.getenv("STV_HOME") or (Path.home() / "stv_agent"))
PIPER_DIR = Path(os.getenv("PIPER_DIR") or (Path.home() / ".local" / "share" / "piper"))
PIPER_MODEL = os.getenv("PIPER_MODEL", "")
WHISPER_MODEL = os.getenv("AISTV_WHISPER_MODEL", "small")
WHISPER_LANG = os.getenv("AISTV_WHISPER_LANG", "vi")


class VoiceError(RuntimeError):
    pass


def _which(name):
    return shutil.which(name) or ""


def _ffmpeg() -> str:
    exe = _which("ffmpeg")
    if exe:
        return exe
    try:                                  # imageio-ffmpeg đã có trong requirements
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def _piper_model() -> Path | None:
    if PIPER_MODEL:
        p = Path(PIPER_MODEL).expanduser()
        if p.is_file():
            return p
    if PIPER_DIR.is_dir():
        for p in sorted(PIPER_DIR.glob("*.onnx")):
            return p
    return None


def check() -> dict:
    return {
        "piper_cli": bool(_which("piper")),
        "piper_module": _importable("piper"),
        "piper_model": bool(_piper_model()),
        "ffmpeg": bool(_ffmpeg()),
        "faster_whisper": _importable("faster_whisper"),
        "whisper_cli": bool(_which("whisper")),
        "whisper_cpp": bool(_which("whisper-cli")),
    }


def _importable(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


# ── TTS ───────────────────────────────────────────────────────────────
def tts(text: str, out: str = "", voice: str = "") -> dict:
    text = (text or "").strip()
    if not text:
        raise VoiceError("thiếu nội dung để đọc")
    model = Path(voice).expanduser() if voice else _piper_model()
    if not model or not Path(model).is_file():
        raise VoiceError(
            "chưa có model Piper. Tải vi_VN-vais1000-medium.onnx vào "
            f"{PIPER_DIR} hoặc đặt PIPER_MODEL=/duong/dan/model.onnx")

    out_path = Path(out).expanduser() if out else Path(tempfile.mkdtemp()) / "tts.ogg"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wav = out_path.with_suffix(".wav")

    piper = _which("piper")
    if piper:
        p = subprocess.run([piper, "-m", str(model), "-f", str(wav)],
                           input=text.encode("utf-8"), capture_output=True)
    else:
        try:                               # piper-tts Python API
            from piper import PiperVoice
            import wave
            v = PiperVoice.load(str(model))
            with wave.open(str(wav), "wb") as w:
                v.synthesize_wav(text, w)
            p = None
        except Exception as e:
            raise VoiceError(f"không chạy được Piper: {e}")
    if p is not None and p.returncode != 0:
        raise VoiceError(f"piper lỗi: {p.stderr.decode('utf-8', 'replace')[:300]}")

    ff = _ffmpeg()
    if ff and out_path.suffix.lower() in (".ogg", ".opus"):
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(wav),
                        "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
                        str(out_path)], check=False)
        wav.unlink(missing_ok=True)
    else:
        out_path = wav
    return {"ok": True, "path": str(out_path), "bytes": out_path.stat().st_size}


# ── STT ───────────────────────────────────────────────────────────────
def stt(path: str, model: str = "") -> dict:
    p = Path(path).expanduser()
    if not p.is_file():
        raise VoiceError(f"không thấy file: {p}")
    model = model or WHISPER_MODEL

    if _importable("faster_whisper"):
        from faster_whisper import WhisperModel
        wm = WhisperModel(model, device="cpu", compute_type="int8")
        segments, info = wm.transcribe(str(p), language=WHISPER_LANG, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"ok": True, "text": text, "engine": f"faster-whisper/{model}",
                "seconds": round(getattr(info, "duration", 0.0), 1)}

    cli = _which("whisper")
    if cli:
        with tempfile.TemporaryDirectory() as tmp:
            p2 = subprocess.run([cli, str(p), "--language", WHISPER_LANG,
                                 "--model", model, "--output_format", "txt",
                                 "--output_dir", tmp], capture_output=True, text=True)
            if p2.returncode != 0:
                raise VoiceError(f"whisper lỗi: {p2.stderr[:300]}")
            txt = Path(tmp) / (p.stem + ".txt")
            text = txt.read_text("utf-8", "replace").strip() if txt.exists() else ""
        return {"ok": True, "text": text, "engine": f"whisper-cli/{model}"}

    raise VoiceError("chưa có bộ nhận dạng giọng nói. Cài: pip install faster-whisper")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TTS/STT local cho AI STV")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("check")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("tts")
    p.add_argument("text")
    p.add_argument("-o", "--out", default="")
    p.add_argument("--voice", default="")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("stt")
    p.add_argument("path")
    p.add_argument("--model", default="")
    p.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "check":
        info = check()
        if args.json:
            print(json.dumps(info, ensure_ascii=False))
        else:
            for k, v in info.items():
                print(f"{'OK ' if v else '---'} {k}")
        return 0
    if args.cmd == "tts":
        try:
            r = tts(args.text, args.out, args.voice)
        except VoiceError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
                  if args.json else f"LỖI: {e}", file=sys.stderr)
            return 1
    elif args.cmd == "stt":
        try:
            r = stt(args.path, args.model)
        except VoiceError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
                  if args.json else f"LỖI: {e}", file=sys.stderr)
            return 1
    else:
        ap.print_help()
        return 2
    print(json.dumps(r, ensure_ascii=False) if args.json else r.get("path") or r.get("text"))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
