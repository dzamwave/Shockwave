"""Model/settings regressions using temporary files and fictional downloads."""
import contextlib
import importlib.metadata
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from unittest.mock import patch

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_source(name, filename, dependencies, virtual_file=None):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename)
    module = importlib.util.module_from_spec(spec)
    if virtual_file:
        module.__file__ = str(virtual_file)
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shockwave-model-tests-")
        self.addCleanup(self.temp.cleanup)
        self.folder = pathlib.Path(self.temp.name)
        (self.folder / "config").mkdir()
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        # A clean fictional environment prevents any real credentials/profile use.
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.dotenv = types.ModuleType("dotenv")
        self.dotenv.load_dotenv = lambda *args, **kwargs: None
        self.secret_writes = []
        self.dotenv.set_key = lambda *args, **kwargs: self.secret_writes.append(args)
        self.ini = self.folder / "config" / "config.ini"
        self.ini.write_text(
            "# user comment\n[Recognition]\nwhisper_model = large-v3-turbo\n"
            "wake_word = shockwave\n"
            "[Interface]\nlanguage = en\nhotkey = alt+space\n"
            "[Custom]\nuser_setting = keep me\n[Prompts]\nai_task = Keep 100%% of data\n",
            encoding="utf-8",
        )
        self.config = self.reload_config()
        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = lambda **kwargs: None
        self.manager = load_source("settings_manager", "model_manager.py", {
            "config": self.config, "dotenv": self.dotenv, "huggingface_hub": hub,
        })
        self.launcher = load_source("settings_launcher", "launcher.py", {
            "config": self.config, "dotenv": self.dotenv,
        })
        with patch.object(importlib.metadata, "version", importlib.metadata.version):
            self.audio_module = load_source("settings_audio", "audio_engine.py", {"config": self.config, "sounddevice": types.ModuleType("sounddevice")})
        self.wake = load_source("settings_wake", "wake_word.py", {
            "config": self.config, "vosk": types.ModuleType("vosk"), "sounddevice": types.ModuleType("sounddevice"),
        })

    def reload_config(self):
        with patch("os.path.abspath", wraps=os.path.abspath) as absolute:
            # The module sees only a temporary cwd/config, never the project .env.
            absolute.side_effect = lambda value: str(self.folder / "config" / value) if value in ("config.ini", "glossary.txt") else absolute._mock_wraps(value)
            return load_source("settings_config", "config.py", {"dotenv": self.dotenv}, self.folder / "src" / "config.py")

    def test_save_failure_keeps_file_and_active_setting(self):
        original = self.ini.read_bytes()
        with patch("os.replace", side_effect=PermissionError("fictional write failure")):
            with self.assertRaises(PermissionError):
                self.config.save_setting("WAKE_WORD", "shockwave")
        self.assertEqual(self.ini.read_bytes(), original)
        self.assertEqual(self.config.WAKE_WORD, "shockwave")
        self.assertEqual(list(self.folder.glob("tmp*")), [])

    def test_save_supports_flat_and_missing_config(self):
        self.ini.write_text("# flat\nwake_word = shockwave\ncustom = keep\n", encoding="utf-8")
        self.config.save_setting("WAKE_WORD", "start")
        self.assertEqual(self.reload_config().WAKE_WORD, "start")
        self.assertIn("custom = keep", self.ini.read_text(encoding="utf-8"))
        self.ini.unlink()
        self.config.save_setting("APP_LANGUAGE", "en")
        self.assertEqual(self.reload_config().APP_LANGUAGE, "en")

    def test_whisper_model_name_is_read(self):
        self.ini.write_text("[Recognition]\nspeech_recognition_model = small\n", encoding="utf-8")
        reloaded = self.reload_config()
        self.assertEqual(reloaded.STT_ENGINE, "whisper")
        self.assertEqual(reloaded.WHISPER_MODEL, "small")

    def test_missing_engine_stays_on_whisper(self):
        self.ini.write_text("[Recognition]\nwhisper_language = ru\n", encoding="utf-8")
        reloaded = self.reload_config()
        self.assertEqual(reloaded.STT_ENGINE, "whisper")
        self.assertEqual(reloaded.WHISPER_MODEL, "large-v3-turbo")
        self.assertEqual(reloaded.GIGAAM_MODEL, "gigaam-v3-e2e-rnnt")
        self.assertEqual(reloaded.GIGAAM_QUANTIZATION, "int8")
        self.assertTrue(reloaded.ONNX_OPTIMIZE_MEMORY)

    def test_legacy_whisper_model_name_is_still_read(self):
        self.ini.write_text("[Recognition]\nengine = whisper_model\nwhisper_model = small\n", encoding="utf-8")
        reloaded = self.reload_config()
        self.assertEqual(reloaded.STT_ENGINE, "whisper")
        self.assertEqual(reloaded.WHISPER_MODEL, "small")

    def test_gigaam_engine_and_quantization_are_read(self):
        self.ini.write_text(
            "[Recognition]\nspeech_recognition_model = gigaam-v3-e2e-rnnt\n"
            "gigaam_quantization = float32\nonnx_optimize_memory = false\n",
            encoding="utf-8",
        )
        reloaded = self.reload_config()
        self.assertEqual(reloaded.STT_ENGINE, "gigaam")
        self.assertEqual(reloaded.GIGAAM_MODEL, "gigaam-v3-e2e-rnnt")
        self.assertEqual(reloaded.GIGAAM_QUANTIZATION, "float32")
        self.assertFalse(reloaded.ONNX_OPTIMIZE_MEMORY)

    def test_unknown_engine_is_rejected(self):
        self.config.STT_ENGINE = "other"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit):
                self.manager.ensure_configured_model()
        self.assertIn("unknown speech model", output.getvalue())

    def test_gigaam_readiness_requires_int8_parts_and_vocab(self):
        self.config.STT_ENGINE = "gigaam"
        self.config.GIGAAM_MODEL = "gigaam-v3-e2e-rnnt"
        self.config.GIGAAM_QUANTIZATION = "int8"
        target = pathlib.Path(self.config.GIGAAM_DIR)
        target.mkdir(parents=True)
        self.assertFalse(self.manager.is_gigaam_downloaded())
        for name in (
            "v3_e2e_rnnt_encoder.int8.onnx",
            "v3_e2e_rnnt_decoder.int8.onnx",
            "v3_e2e_rnnt_joint.int8.onnx",
            "v3_e2e_rnnt_vocab.txt",
        ):
            (target / name).write_bytes(b"fictional")
        self.assertTrue(self.manager.is_gigaam_downloaded())

    def test_gigaam_transcription_uses_recognize(self):
        calls = []
        model = types.SimpleNamespace(recognize=lambda data: calls.append(data.shape) or "russian text")
        engine = self.audio_module.AudioEngine.__new__(self.audio_module.AudioEngine)
        engine.get_or_load_model = lambda: model
        engine.engine_type = "gigaam"
        engine.audio_data = [np.ones((16000, 1), dtype=np.float32)]
        engine.sample_rate = 16000
        engine._audio_statuses = []
        engine._last_used_time = 0.0
        self.assertEqual(engine.transcribe(), "russian text")
        self.assertEqual(calls, [(16000,)])

    def test_legacy_language_settings_cannot_change_english_interface(self):
        self.ini.write_text("[Console]\nlanguage = en\n[Interface]\nlanguage = en\n", encoding="utf-8")
        os.environ["APP_LANGUAGE"] = "en"
        self.assertEqual(self.reload_config().APP_LANGUAGE, "en")

    def test_model_download_dialog_is_english(self):
        self.config.APP_LANGUAGE = "en"
        output = io.StringIO()
        prompts = []
        with contextlib.redirect_stdout(output), patch.object(self.manager, "is_whisper_downloaded", return_value=False), patch(
            "builtins.input", side_effect=lambda prompt: prompts.append(prompt) or "n"
        ):
            with self.assertRaises(SystemExit):
                self.manager.ensure_configured_model()
        self.assertTrue(output.getvalue().isascii())
        self.assertEqual(prompts, ["Download this model? (y/n): "])

    def test_launcher_is_english(self):
        self.config.APP_LANGUAGE = "en"
        app = types.SimpleNamespace(run=lambda: None)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.dict(sys.modules, {
            "model_manager": types.SimpleNamespace(ensure_configured_model=lambda: None),
            "main": types.SimpleNamespace(WinVoiceApp=lambda: app),
        }), patch.object(self.launcher, "clear_screen"), patch.object(self.launcher, "print_banner"):
            with self.assertRaises(SystemExit):
                self.launcher.start_app()
        self.assertTrue(output.getvalue().isascii())
        self.assertNotIn("Shockwave version:", output.getvalue())

    def test_grouped_sections_keep_current_values(self):
        self.ini.write_text(
            "[Recording]\nhotkey = f9\nmax_record_seconds = 20\nwarn_record_seconds = 10\n"
            "[Wake]\nwake = false\nwake_word = example\n"
            "[Text]\nllm_norm = true\nidea = true\n"
            "[Widget]\nposition = top-center\nopacity = 0.5\nui_bg_color = #112233\n"
            "[Sound]\nalert_sound = false\n"
            "[Console]\nlanguage = en\ncli_banner_pad = 1\n",
            encoding="utf-8",
        )
        reloaded = self.reload_config()
        self.assertEqual(reloaded.HOTKEY, "f9")
        self.assertEqual(reloaded.MAX_RECORD_SECONDS, 20)
        self.assertEqual(reloaded.WARN_RECORD_SECONDS, 10)
        self.assertFalse(reloaded.WAKE_WORD_ENABLED)
        self.assertEqual(reloaded.WAKE_WORD, "example")
        self.assertTrue(reloaded.LLM_NORM)
        self.assertTrue(reloaded.IDEA_MODE)
        self.assertEqual(reloaded.UI_POSITION, "top-center")
        self.assertEqual(reloaded.UI_OPACITY, 0.5)
        self.assertEqual(reloaded.UI_BG_COLOR, "#112233")
        self.assertFalse(reloaded.ALERT_SOUND)
        self.assertEqual(reloaded.APP_LANGUAGE, "en")
        self.assertEqual(reloaded.CLI_BANNER_PAD, 1)

    def test_llm_settings_come_only_from_config_ini(self):
        self.ini.write_text(
            "[LLM]\nendpoint = https://example.test/v1\nmodel = demo-model\ntimeout = 9\napi_key =\n",
            encoding="utf-8",
        )
        os.environ["LLM_ENDPOINT"] = "https://old.example"
        os.environ["LLM_MODEL"] = "old-model"
        os.environ["LLM_API_KEY"] = "secret-from-env"
        os.environ["LLM_TIMEOUT"] = "30"
        reloaded = self.reload_config()
        self.assertEqual(reloaded.LLM_ENDPOINT, "https://example.test/v1")
        self.assertEqual(reloaded.LLM_MODEL, "demo-model")
        self.assertEqual(reloaded.LLM_TIMEOUT, 9)
        self.assertEqual(reloaded.LLM_API_KEY, "")

    def test_save_preserves_crlf_comments_and_multiline_prompts(self):
        content = "[Recognition]\r\nwhisper_model = small\r\n# user note\r\n[Prompts]\r\nai_task = first\r\n    second\r\n"
        self.ini.write_bytes(content.encode("utf-8"))
        self.config.save_setting("WAKE_WORD", "shockwave")
        self.assertIn(b"whisper_model = small", self.ini.read_bytes())
        self.assertIn(b"wake_word = shockwave", self.ini.read_bytes())
        self.assertEqual(self.reload_config().LLM_PROMPT_AI_TASK, "first\nsecond")

    def test_environment_cannot_replace_a_missing_ini_setting(self):
        self.ini.write_text("[Custom]\nkeep = yes\n", encoding="utf-8")
        os.environ["WAKE_WORD"] = "legacy-word"
        reloaded = self.reload_config()
        self.assertEqual(reloaded.WAKE_WORD, "shockwave")

    def test_whisper_readiness_requires_a_model_file(self):
        target = pathlib.Path(self.config.WHISPER_DIR)
        target.mkdir(parents=True)
        self.assertFalse(self.manager.is_whisper_downloaded())
        (target / "model.bin").write_bytes(b"fictional")
        self.assertTrue(self.manager.is_whisper_downloaded())

    def test_whisper_language_uses_config_or_english_default(self):
        self.ini.write_text("[Recognition]\nwhisper_language = de\n", encoding="utf-8")
        self.assertEqual(self.reload_config().WHISPER_LANGUAGE, "de")
        self.ini.write_text("[Recognition]\nwhisper_model = small\n", encoding="utf-8")
        self.assertEqual(self.reload_config().WHISPER_LANGUAGE, "en")

        languages = []
        model = types.SimpleNamespace(transcribe=lambda data, language: languages.append(language) or ([types.SimpleNamespace(text="dictated text")], None))
        engine = self.audio_module.AudioEngine.__new__(self.audio_module.AudioEngine)
        engine.get_or_load_model = lambda: model
        engine.engine_type = "whisper"
        engine.audio_data = [np.ones((16000, 1), dtype=np.float32)]
        engine.sample_rate = 16000
        engine._audio_statuses = []
        self.config.WHISPER_LANGUAGE = "auto"
        self.assertEqual(engine.transcribe(), "dictated text")
        self.assertEqual(languages, [None])

    def make_vosk_files(self, folder):
        for name in ("am/final.mdl", "conf/mfcc.conf", "graph/HCLr.fst", "graph/Gr.fst"):
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fictional model")

    def fake_download(self, url, destination):
        with zipfile.ZipFile(destination, "w") as archive:
            for name in ("am/final.mdl", "conf/mfcc.conf", "graph/HCLr.fst", "graph/Gr.fst"):
                archive.writestr("vosk-model-small-ru-0.22/" + name, b"fictional model")

    def test_vosk_download_populates_existing_placeholder_folder(self):
        target = pathlib.Path(self.config.VOSK_DIR)
        target.mkdir(parents=True)
        (target / ".gitkeep").write_text("placeholder", encoding="utf-8")
        with patch("urllib.request.urlretrieve", side_effect=self.fake_download):
            self.assertEqual(self.wake.ensure_vosk_model(), str(target))
        self.assertTrue((target / "am/final.mdl").is_file())
        self.assertEqual((target / ".gitkeep").read_text(encoding="utf-8"), "placeholder")
        with patch("urllib.request.urlretrieve", side_effect=AssertionError("unneeded download")):
            self.assertEqual(self.wake.ensure_vosk_model(), str(target))

    def test_existing_vosk_files_are_used_without_download(self):
        target = pathlib.Path(self.config.VOSK_DIR)
        self.make_vosk_files(target)
        with patch("urllib.request.urlretrieve", side_effect=AssertionError("unneeded download")):
            self.assertEqual(self.wake.ensure_vosk_model(), str(target))

    def test_empty_custom_vosk_folder_is_populated(self):
        target = self.folder / "custom" / "vosk"
        target.mkdir(parents=True)
        with patch("urllib.request.urlretrieve", side_effect=self.fake_download):
            self.assertEqual(self.wake.ensure_vosk_model(str(target)), str(target))
        self.assertTrue((target / "am/final.mdl").is_file())

    def test_vosk_failed_publication_restores_placeholder(self):
        target = pathlib.Path(self.config.VOSK_DIR)
        target.mkdir(parents=True)
        (target / ".gitkeep").write_bytes(b"keep")
        rename = os.rename
        def fail_publication(source, destination):
            if pathlib.Path(source).name == "vosk-model-small-ru-0.22":
                raise PermissionError("fictional publish failure")
            return rename(source, destination)
        with patch("urllib.request.urlretrieve", side_effect=self.fake_download), patch("os.rename", side_effect=fail_publication):
            self.assertIsNone(self.wake.ensure_vosk_model())
        self.assertEqual((target / ".gitkeep").read_bytes(), b"keep")
        self.assertEqual(list(target.parent.glob(".vosk-download-*")), [])

    def test_invalid_download_is_not_reported_ready(self):
        target = pathlib.Path(self.config.VOSK_DIR)

        def bad_archive(url, destination):
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("vosk-model-small-ru-0.22/README", "not a model")

        with patch("urllib.request.urlretrieve", side_effect=bad_archive):
            self.assertIsNone(self.wake.ensure_vosk_model())
        self.assertFalse((target / "README").exists())

    def test_incomplete_nonempty_vosk_folder_is_preserved(self):
        target = pathlib.Path(self.config.VOSK_DIR)
        target.mkdir(parents=True)
        (target / "user-file.txt").write_text("keep", encoding="utf-8")
        with patch("urllib.request.urlretrieve", side_effect=AssertionError("do not overwrite user files")):
            self.assertIsNone(self.wake.ensure_vosk_model())
        self.assertEqual((target / "user-file.txt").read_text(), "keep")


class RecognitionModeTests(ModelSettingsTests):
    def test_russian_mode_stays_on_gigaam_even_when_multi_names_parakeet(self):
        self.ini.write_text(
            "[Recognition]\nspeech_recognition_model = nemo-parakeet-tdt-0.6b-v3\nrecognition_mode = ru\n",
            encoding="utf-8",
        )
        reloaded = self.reload_config()
        self.assertEqual(reloaded.RECOGNITION_MODE, "ru")
        self.assertEqual(reloaded.MULTI_ENGINE, "parakeet")
        self.assertEqual(reloaded.MULTI_MODEL, "nemo-parakeet-tdt-0.6b-v3")

    def test_whisper_name_selects_whisper_for_multi(self):
        self.ini.write_text(
            "[Recognition]\nspeech_recognition_model = large-v3-turbo\nrecognition_mode = multi\n",
            encoding="utf-8",
        )
        reloaded = self.reload_config()
        self.assertEqual(reloaded.MULTI_ENGINE, "whisper")
        self.assertEqual(reloaded.MULTI_MODEL, "large-v3-turbo")

    def test_gigaam_name_keeps_multi_on_parakeet(self):
        self.ini.write_text(
            "[Recognition]\nspeech_recognition_model = gigaam-v3-e2e-rnnt\nrecognition_mode = multi\n",
            encoding="utf-8",
        )
        reloaded = self.reload_config()
        self.assertEqual(reloaded.MULTI_ENGINE, "parakeet")
        self.assertEqual(reloaded.MULTI_MODEL, "nemo-parakeet-tdt-0.6b-v3")

    def test_unknown_mode_falls_back_to_russian(self):
        self.ini.write_text(
            "[Recognition]\nspeech_recognition_model = large-v3-turbo\nrecognition_mode = both\n",
            encoding="utf-8",
        )
        self.assertEqual(self.reload_config().RECOGNITION_MODE, "ru")

    def test_radio_choice_is_written_back(self):
        self.config.save_setting("RECOGNITION_MODE", "multi")
        self.assertEqual(self.reload_config().RECOGNITION_MODE, "multi")


class PauseSplitTests(unittest.TestCase):
    def test_long_recording_is_joined_from_pause_segments(self):
        stub_config = types.SimpleNamespace(RECOGNITION_MODE="multi", MULTI_ENGINE="parakeet")
        stub_sounddevice = types.ModuleType("sounddevice")
        engine = load_source("pause_engine", "audio_engine.py", {"config": stub_config, "sounddevice": stub_sounddevice})
        audio = engine.AudioEngine.__new__(engine.AudioEngine)
        audio.sample_rate = 16000
        audio.vad = object()

        class Segment:
            def __init__(self, text):
                self.text = text

        class SplitModel:
            def __init__(self):
                self.calls = 0

            def with_vad(self, vad):
                self.calls += 1
                return self

            def recognize(self, waveform, sample_rate=None):
                return iter([Segment("first phrase"), Segment("  "), Segment("second phrase")])

        model = SplitModel()
        text = audio._segment_text(model, np.zeros(16000, dtype=np.float32))
        self.assertEqual(model.calls, 1)
        self.assertEqual(text, "first phrase second phrase")


if __name__ == "__main__":
    unittest.main()
