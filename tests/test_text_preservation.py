"""Offline regressions for dictation preservation; no real configs or services."""
import contextlib
import importlib.util
import io
import os
import pathlib
import queue
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import test_llm_transport as transport
import test_recording_lifecycle as lifecycle


LLM = transport.LLM
CONFIG = transport.CONFIG
MAIN = lifecycle.MAIN
path = pathlib.Path(__file__).resolve().parents[1] / "src" / "glossary.py"
spec = importlib.util.spec_from_file_location("preservation_glossary", path)
GLOSSARY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GLOSSARY)


class ResponsePreservationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(CONFIG, "LLM_ENDPOINT", "https://provider.example/v1"))
        self.reply = Mock(ok=True, status_code=200)
        self.reply.json.return_value = {"choices": [{"message": {"content": "edited"}, "finish_reason": "stop"}]}
        self.post = self.enterContext(patch.object(LLM.requests, "post", return_value=self.reply))
        self.normalizer = LLM.LLMNormalizer()
        self.original = "Entry condition, risk 100 USDT, and an important final limit."

    def test_truncated_response_returns_entire_original(self):
        self.reply.json.return_value["choices"][0]["finish_reason"] = "length"
        self.assertEqual(self.normalizer.normalize(self.original), self.original)

    def test_only_confirmed_completed_text_is_successful(self):
        for reason in ("length", "content_filter", "tool_calls", "function_call", None, "unknown"):
            with self.subTest(reason=reason):
                self.reply.json.return_value = {"choices": [{"message": {"content": "partial"}, "finish_reason": reason}]}
                result = self.normalizer.normalize_result(self.original)
                self.assertEqual(result.text, self.original)
                self.assertFalse(result.succeeded)
                self.assertTrue(result.warning)

    def test_valid_result_keeps_selected_mode_and_text(self):
        result = self.normalizer.normalize_result(self.original, translate_en=True, ai_task=True)
        self.assertEqual(result.text, "edited")
        self.assertTrue(result.succeeded)
        self.assertEqual(result.warning, "")
        self.assertEqual(self.post.call_args.kwargs["json"]["messages"][0]["content"], CONFIG.DEFAULT_AI_TASK_EN_PROMPT)

    def test_valid_result_idea_mode_uses_idea_prompt_and_tokens(self):
        CONFIG.DEFAULT_IDEA_PROMPT = "idea prompt"
        result = self.normalizer.normalize_result(self.original, idea=True)
        self.assertEqual(result.text, "edited")
        self.assertTrue(result.succeeded)
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][0]["content"], "idea prompt")
        self.assertEqual(payload["max_tokens"], 2048)

    def test_bad_http_and_malformed_responses_preserve_original(self):
        for data in ({"choices": []}, {"choices": None}, {"choices": [{}]}, {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]}, {"choices": [{"finish_reason": "stop", "message": {"content": ["not plain text"]}}]}):
            with self.subTest(data=data):
                self.reply.json.return_value = data
                result = self.normalizer.normalize_result(self.original)
                self.assertFalse(result.succeeded)
                self.assertEqual(result.text, self.original)
        self.reply.ok = False
        self.reply.status_code = 503
        result = self.normalizer.normalize_result(self.original)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.text, self.original)

    def test_timeout_connection_and_invalid_json_preserve_original(self):
        for error in (LLM.requests.exceptions.Timeout("fictional"), LLM.requests.exceptions.ConnectionError("fictional")):
            with self.subTest(error=error):
                self.post.side_effect = error
                result = self.normalizer.normalize_result(self.original)
                self.assertFalse(result.succeeded)
                self.assertEqual(result.text, self.original)
        self.post.side_effect = None
        self.reply.json.side_effect = ValueError("fictional invalid JSON")
        result = self.normalizer.normalize_result(self.original)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.text, self.original)


class DictationPreservationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(CONFIG, "LLM_ENDPOINT", "https://provider.example/v1"))
        self.app = MAIN.WinVoiceApp.__new__(MAIN.WinVoiceApp)
        self.app.lock = threading.Lock()
        self.app._audio_lock = threading.RLock()
        self.app._shutting_down = False
        self.app._recording_id = 1
        self.app.is_recording = False
        self.app.is_processing = True
        self.app.q = queue.Queue()
        self.stop = Mock()
        self.transcript = "Risk 100 USDT, stop 42"
        self.app.audio = types.SimpleNamespace(stop_recording=self.stop, transcribe=lambda: self.transcript, cancel_recording=Mock())
        self.app.wake_detector = types.SimpleNamespace(keyword="shockwave", resume_mic=Mock())
        self.app.glossary = types.SimpleNamespace(apply=lambda text: text)
        self.app.ui = types.SimpleNamespace(llm_enabled=False, ai_task_enabled=False, translate_en_enabled=False, clip_prepend_enabled=False)
        self.copy = Mock()
        self.app.typer = types.SimpleNamespace(type_text=self.copy)
        self.app.llm = LLM.LLMNormalizer()

    def messages(self):
        return list(self.app.q.queue)

    def test_voice_stop_keeps_full_audio_and_removes_only_trailing_keyword(self):
        self.transcript += ", Shockwave!"
        self.app.process_audio_thread(is_wake_word=True)
        self.stop.assert_called_once_with(trim_seconds=0.0)
        self.copy.assert_called_once_with("Risk 100 USDT, stop 42,", prepend_clipboard=False)
        self.assertIn({"cmd": "show_ready"}, self.messages())

    def test_keyword_inside_text_or_unrecognized_stop_is_preserved(self):
        for transcript in ("Shockwave volume, stop 42", "final number 42", "shockwavebyte 42"):
            with self.subTest(transcript=transcript):
                self.transcript = transcript
                self.copy.reset_mock()
                self.app.process_audio_thread(is_wake_word=True)
                self.copy.assert_called_once_with(transcript, prepend_clipboard=False)

    def test_hotkey_stop_does_not_remove_dictated_keyword(self):
        self.transcript = "I need shockwave"
        self.app.process_audio_thread(is_wake_word=False)
        self.copy.assert_called_once_with(self.transcript, prepend_clipboard=False)

    def test_paste_toggle_passes_clipboard_and_paste_options(self):
        self.app.ui.paste_enabled = True
        self.app.ui.clip_prepend_enabled = True
        self.app.process_audio_thread(is_wake_word=False)
        self.copy.assert_called_once_with(self.transcript, prepend_clipboard=True, auto_paste=True)

    def test_custom_multiword_keyword_only_removed_at_end(self):
        self.app.wake_detector.keyword = "code stop"
        self.transcript = "Level 42. Code stop."
        self.app.process_audio_thread(is_wake_word=True)
        self.copy.assert_called_once_with("Level 42.", prepend_clipboard=False)

    def test_llm_failure_copies_original_and_warns_instead_of_ready(self):
        self.app.ui.translate_en_enabled = True
        self.app.ui.clip_prepend_enabled = True
        with patch.object(LLM.requests, "post", side_effect=LLM.requests.exceptions.Timeout("fictional")):
            self.app.process_audio_thread()
        self.copy.assert_called_once_with(self.transcript, prepend_clipboard=True)
        self.assertNotIn({"cmd": "show_ready"}, self.messages())
        self.assertTrue(any("original saved" in msg.get("text", "") for msg in self.messages()))
        self.assertFalse(self.app.is_processing)
        self.app.wake_detector.resume_mic.assert_called_once()

    def test_truncated_llm_result_never_reaches_clipboard(self):
        self.app.ui.llm_enabled = True
        reply = Mock(ok=True, status_code=200)
        reply.json.return_value = {"choices": [{"finish_reason": "length", "message": {"content": "lost ending"}}]}
        with patch.object(LLM.requests, "post", return_value=reply):
            self.app.process_audio_thread()
        self.copy.assert_called_once_with(self.transcript, prepend_clipboard=False)
        self.assertNotIn({"cmd": "show_ready"}, self.messages())

    def test_glossary_error_does_not_lose_transcript(self):
        self.app.glossary.apply = Mock(side_effect=RuntimeError("fictional dictionary failure"))
        self.app.process_audio_thread()
        self.copy.assert_called_once_with(self.transcript, prepend_clipboard=False)
        self.assertNotIn({"cmd": "show_ready"}, self.messages())
        self.assertFalse(self.app.is_processing)

    def test_glossary_failure_saves_original_without_further_llm_changes(self):
        self.app.glossary.apply = Mock(side_effect=RuntimeError("fictional dictionary failure"))
        self.app.ui.translate_en_enabled = True
        self.app.llm = types.SimpleNamespace(normalize_result=Mock(return_value=types.SimpleNamespace(
            text="translated", succeeded=True, warning="")))
        self.app.process_audio_thread()
        self.copy.assert_called_once_with(self.transcript, prepend_clipboard=False)
        self.app.llm.normalize_result.assert_not_called()
        self.assertNotIn({"cmd": "show_ready"}, self.messages())


    def test_idea_toggle_passes_idea_mode_to_llm(self):
        self.app.ui.idea_enabled = True
        normalized = []
        def normalize_result(text, **kwargs):
            normalized.append((text, kwargs))
            return types.SimpleNamespace(text="structured idea", succeeded=True, warning="")
        self.app.llm = types.SimpleNamespace(normalize_result=normalize_result)
        self.app.process_audio_thread()
        self.copy.assert_called_once_with("structured idea", prepend_clipboard=False)
        self.assertEqual(normalized, [(self.transcript, {
            "translate_en": False, "ai_task": False, "idea": True, "normalize": False,
        })])


class GlossaryPreservationTests(unittest.TestCase):
    def test_generated_glossary_has_english_instructions_and_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "glossary.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                glossary = GLOSSARY.GlossaryManager(str(path))
            comments = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
            self.assertTrue(comments)
            self.assertTrue(all(line.isascii() for line in comments))
            self.assertEqual(glossary.apply("docker"), "Docker")

    def test_backslashes_and_group_like_replacements_are_literal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "glossary.txt"
            path.write_text("logs = C:\\logs\ngroup = \\1\\name\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                glossary = GLOSSARY.GlossaryManager(str(path))
                self.assertEqual(glossary.apply("Logs and group"), "C:\\logs and \\1\\name")

    def test_failed_reread_does_not_stick(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "glossary.txt"
            path.write_text("word = replacement\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                glossary = GLOSSARY.GlossaryManager(str(path))
            self.assertEqual(glossary.apply("word"), "replacement")
            path.write_text("word = updated\n", encoding="utf-8")
            os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
            real_open = open
            failed = {"once": False}

            def flaky(file, mode="r", *args, **kwargs):
                if str(file) == str(path) and "r" in mode and not failed["once"]:
                    failed["once"] = True
                    raise OSError("busy")
                return real_open(file, mode, *args, **kwargs)

            with patch("builtins.open", flaky), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(glossary.apply("word"), "replacement")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(glossary.apply("word"), "updated")


if __name__ == "__main__":
    unittest.main()
