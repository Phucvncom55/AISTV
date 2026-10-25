# -*- coding: utf-8 -*-
"""Kiểm tra chọn nguồn media cho Web2API (voice/video) và nhận diện patch."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aistv_watch as watch          # noqa: E402
import aistv_web2api as web2api      # noqa: E402


class VoiceEngineOrderTest(unittest.TestCase):
    def test_auto_prefers_web2api(self):
        self.assertEqual(watch.voice_engine_order("auto", True, True, True),
                         ["web2api", "gemini", "local"])

    def test_auto_without_web2api(self):
        self.assertEqual(watch.voice_engine_order("auto", True, False, True),
                         ["gemini", "local"])

    def test_auto_without_any_source(self):
        self.assertEqual(watch.voice_engine_order("auto", False, False, False), [])

    def test_explicit_engine_stays_alone(self):
        self.assertEqual(watch.voice_engine_order("web2api", True, False, True),
                         ["web2api"])


class Web2apiAudioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "voice.bin"
        self.src.write_bytes(b"x" * 2048)

    def tearDown(self):
        for item in self.tmp.iterdir():
            item.unlink()
        self.tmp.rmdir()

    def test_native_small_file_is_sent_as_is(self):
        with mock.patch.object(watch, "_audio_to_mp3") as convert:
            path, mime, err = watch.web2api_audio(self.src, "audio/mpeg")
        self.assertEqual((path, mime, err), (self.src, "audio/mpeg", None))
        convert.assert_not_called()

    def test_ogg_is_converted_to_mp3(self):
        out = self.tmp / "converted.mp3"
        out.write_bytes(b"m" * 2048)
        with mock.patch.object(watch, "_audio_to_mp3", return_value=out) as convert:
            path, mime, err = watch.web2api_audio(self.src, "audio/ogg")
        self.assertEqual((path, mime, err), (out, "audio/mpeg", None))
        convert.assert_called_once_with(self.src)

    def test_missing_ffmpeg_reports_error(self):
        with mock.patch.object(watch, "_audio_to_mp3", return_value=None):
            path, mime, err = watch.web2api_audio(self.src, "audio/ogg")
        self.assertEqual(path, self.src)
        self.assertEqual(mime, "audio/ogg")
        self.assertIn("ffmpeg", err)

    def test_large_native_file_requires_conversion(self):
        with mock.patch.object(watch, "WEB2API_MEDIA_MB", 0):
            with mock.patch.object(watch, "_audio_to_mp3", return_value=None):
                path, mime, err = watch.web2api_audio(self.src, "audio/wav")
        self.assertEqual(path, self.src)
        self.assertIn("MB", err)


class MediaPatchReadyTest(unittest.TestCase):
    def test_marks_ready_only_with_all_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "app" / "gemini_web2api"
            pkg.mkdir(parents=True)
            (pkg / "server.py").write_text("detect_media_mime", encoding="utf-8")
            (pkg / "multimodal.py").write_text("media_filename", encoding="utf-8")
            (pkg / "tools.py").write_text("attachment_label", encoding="utf-8")
            with mock.patch.dict(os.environ, {"WEB2API_DIR": tmp}):
                self.assertTrue(web2api.media_patch_ready())

    def test_missing_marker_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "app" / "gemini_web2api"
            pkg.mkdir(parents=True)
            (pkg / "server.py").write_text("detect_media_mime", encoding="utf-8")
            (pkg / "multimodal.py").write_text("media_filename", encoding="utf-8")
            (pkg / "tools.py").write_text("image.png", encoding="utf-8")
            with mock.patch.dict(os.environ, {"WEB2API_DIR": tmp}):
                self.assertFalse(web2api.media_patch_ready())


if __name__ == "__main__":
    unittest.main()
