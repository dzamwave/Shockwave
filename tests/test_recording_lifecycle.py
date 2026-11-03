"""Offline lifecycle regressions: no secrets, devices, models, or API calls.

Run: venv\\Scripts\\python.exe -B -m unittest discover -s tests -v
"""
import contextlib
import importlib.metadata
import importlib.util
import io
import pathlib
import queue
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = types.ModuleType("config")
CONFIG.APP_LANGUAGE = "en"
CONFIG.WAKE_WORD = "shockwave"
CONFIG.MODELS_DIR = "unused-models"
CONFIG.MAX_RECORD_SECONDS = 180
CONFIG.WARN_RECORD_SECONDS = 150


def load_module(name, filename, dependencies):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename)
    module = importlib.util.module_from_spec(spec)
    # config is replaced before imports: the real .env is never loaded.
    with patch.dict(sys.modules, {"config": CONFIG, **dependencies}):
        spec.loader.exec_module(module)
    return module


with patch.object(importlib.metadata, "version", importlib.metadata.version):
    AUDIO = load_module("test_audio", "audio_engine.py", {})
WAKE = load_module("test_wake", "wake_word.py", {"vosk": types.ModuleType("vosk")})

deps = {"audio_engine": AUDIO, "wake_word": WAKE}
for name, attributes in {
    "ui": ["WinVoiceUI", "play_ready_sound"],
    "llm_normalizer": ["LLMNormalizer"],
    "typer": ["Typer"],
    "hotkey_manager": ["SystemHotkeyManager"],
    "single_instance": ["check_single_instance", "release_single_instance"],
    "tray_manager": ["SystemTrayManager", "hide_console", "show_console"],
    "glossary": ["GlossaryManager"],
}.items():
    module = types.ModuleType(name)
    for attribute in attributes:
        setattr(module, attribute, lambda *args, **kwargs: None)
    deps[name] = module
MAIN = load_module("test_main", "main.py", deps)


class Stream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True
        self.active = False


class Threads:
    def __init__(self):
        self.items = []

    def Thread(self, *args, **kwargs):
        thread = threading.Thread(*args, **kwargs)
        self.items.append(thread)
        return thread

    def join(self):
        # Workers can create the watchdog or a processing worker.
        for thread in self.items:
            thread.join(2)
            if thread.is_alive():
                raise AssertionError("recording worker did not finish")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.threads = Threads()
        self.thread_patch = patch.object(
            MAIN, "threading", types.SimpleNamespace(Thread=self.threads.Thread, Lock=threading.Lock)
        )
        self.thread_patch.start()
        self.streams = []

        def make_stream(**kwargs):
            stream = Stream(**kwargs)
            self.streams.append(stream)
            return stream

        self.stream_patch = patch.object(AUDIO.sd, "InputStream", make_stream)
        self.stream_patch.start()
        self.audio = AUDIO.AudioEngine.__new__(AUDIO.AudioEngine)
        self.audio.stream = None
        self.audio.audio_data = []
        self.audio.sample_rate = 16000
        self.audio.is_recording = False
        self.audio.on_audio_chunk = None
        self.audio.preload_model_async = lambda: None
        self.audio.transcribe = lambda: "dictated text"
        self.app = MAIN.WinVoiceApp.__new__(MAIN.WinVoiceApp)
        self.app.lock = threading.Lock()
        self.app._audio_lock = threading.RLock()
        self.app._shutting_down = False
        self.app._recording_id = 0
        self.app.is_recording = False
        self.app.is_processing = False
        self.app.q = queue.Queue()
        self.app.audio = self.audio
        self.resumed = []
        self.app.wake_detector = types.SimpleNamespace(
            keyword=CONFIG.WAKE_WORD, pause_mic=lambda: None, resume_mic=lambda: self.resumed.append(True)
        )
        self.app.ui = types.SimpleNamespace(
            alert_enabled=False, llm_enabled=False, ai_task_enabled=False,
            translate_en_enabled=False, clip_prepend_enabled=False,
        )
        self.app.glossary = types.SimpleNamespace(apply=lambda text: text)
        self.copied = []
        self.app.typer = types.SimpleNamespace(
            type_text=lambda text, **kwargs: self.copied.append(text)
        )

    def tearDown(self):
        self.app.is_recording = False
        self.threads.join()
        self.audio.cancel_recording()
        self.stream_patch.stop()
        self.thread_patch.stop()
        self.output.__exit__(None, None, None)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("worker did not reach expected state")
            time.sleep(0.005)

    def messages(self):
        result = []
        while not self.app.q.empty():
            result.append(self.app.q.get_nowait())
        return result

    def test_audio_diagnostics_report_levels_and_stream_status(self):
        self.audio.start_recording()
        self.audio._audio_callback(np.full((16000, 1), 0.25, dtype=np.float32), 16000, None, "input overflow")
        self.audio.stop_recording()
        self.audio.engine_type = "whisper"
        self.audio.get_or_load_model = lambda: types.SimpleNamespace(
            transcribe=lambda data, language: ([], None)
        )
        self.assertEqual(AUDIO.AudioEngine.transcribe(self.audio), "")
        output = self.output._new_target.getvalue()
        self.assertIn("duration=1.00s", output)
        self.assertIn("rms=0.250000", output)
        self.assertIn("peak=0.250000", output)
        self.assertIn("input overflow", output)
        self.assertIn("Whisper output (en):", output)

    def test_cancel_during_startup_leaves_no_active_microphone(self):
        entered, proceed = threading.Event(), threading.Event()

        def slow_preload():
            entered.set()
            if not proceed.wait(2):
                raise RuntimeError("test startup gate timed out")

        self.audio.preload_model_async = slow_preload
        self.app.toggle_recording()
        self.assertTrue(entered.wait(2))
        # Cancel must change intent without waiting for microphone startup.
        caller = threading.Thread(target=self.app.cancel_recording, daemon=True)
        caller.start()
        self.wait_for(lambda: not self.app.is_recording)
        proceed.set()
        caller.join(2)
        self.threads.join()
        self.assertFalse(self.audio.is_recording)
        self.assertFalse(any(stream.active for stream in self.streams))
        self.assertFalse(self.app.is_processing)
        self.assertEqual(self.copied, [])
        self.assertTrue(self.resumed)

    def test_stop_during_startup_does_not_leave_a_late_stream_running(self):
        entered, proceed = threading.Event(), threading.Event()

        def slow_preload():
            entered.set()
            if not proceed.wait(2):
                raise RuntimeError("test startup gate timed out")

        def start_recording():
            self.audio.audio_data = [np.ones((8, 1), dtype=np.float32)]
            self.audio.is_recording = True
            entered.set()
            if not proceed.wait(2):
                raise RuntimeError("test startup gate timed out")

        self.audio.start_recording = start_recording
        seen = []
        self.audio.transcribe = lambda: seen.append(len(self.audio.audio_data)) or "dictated text"
        self.app.toggle_recording()
        self.assertTrue(entered.wait(2))
        self.app.toggle_recording()
        proceed.set()
        self.threads.join()
        self.assertEqual(seen, [1])
        self.assertEqual(self.copied, ["dictated text"])
        self.assertFalse(self.audio.is_recording)
        self.assertFalse(any(stream.active for stream in self.streams))
        self.assertFalse(self.app.is_processing)

    def test_microphone_open_failure_recovers_and_reports_error(self):
        with patch.object(AUDIO.sd, "InputStream", side_effect=RuntimeError("device unavailable")):
            self.app.toggle_recording()
            self.wait_for(lambda: not self.app.is_recording)
            self.threads.join()
        self.assertFalse(self.audio.is_recording)
        self.assertFalse(self.app.is_processing)
        self.assertTrue(self.resumed)
        self.assertTrue(any("error" in msg.get("text", "").lower() for msg in self.messages()))

    def test_clipboard_failure_does_not_block_the_next_dictation(self):
        def fail(*args, **kwargs):
            raise RuntimeError("clipboard busy")

        self.app.typer.type_text = fail
        self.app.is_processing = True
        try:
            self.app.process_audio_thread()
        except RuntimeError:
            pass  # Assert state even against the old uncaught-exception implementation.
        self.assertFalse(self.app.is_processing)
        self.assertTrue(self.resumed)
        self.assertNotIn({"cmd": "show_ready"}, self.messages())
        self.app.typer.type_text = lambda text, **kwargs: self.copied.append(text)
        self.app.toggle_recording()
        self.wait_for(lambda: self.audio.stream is not None)
        self.app.toggle_recording()
        self.threads.join()
        self.assertEqual(self.copied, ["dictated text"])

    def test_processing_exceptions_always_restore_idle(self):
        def fail(*args, **kwargs):
            raise RuntimeError("processing failed")

        for stage in ("transcribe", "glossary", "llm"):
            with self.subTest(stage=stage):
                self.app.is_processing = True
                self.audio.transcribe = fail if stage == "transcribe" else lambda: "text"
                self.app.glossary.apply = fail if stage == "glossary" else lambda text: text
                self.app.ui.llm_enabled = stage == "llm"
                self.app.llm = types.SimpleNamespace(normalize_result=fail)
                try:
                    self.app.process_audio_thread()
                except RuntimeError:
                    pass
                self.assertFalse(self.app.is_processing)
                self.assertFalse(self.app.is_recording)
                self.assertNotIn({"cmd": "show_ready"}, self.messages())

    def test_successful_processing_preserves_normalization_and_clip_option(self):
        self.app.is_processing = True
        self.app.ui.llm_enabled = True
        self.app.ui.translate_en_enabled = True
        self.app.ui.ai_task_enabled = True
        self.app.ui.clip_prepend_enabled = True
        self.app.glossary.apply = lambda text: "corrected text"

        def normalize(text, translate_en, ai_task, **kwargs):
            self.assertEqual(text, "corrected text")
            self.assertTrue(translate_en and ai_task)
            self.assertFalse(kwargs.get("idea"))
            return types.SimpleNamespace(text="normalized text", succeeded=True, warning="")

        self.app.llm = types.SimpleNamespace(normalize_result=normalize)
        result = []
        self.app.typer.type_text = lambda text, prepend_clipboard: result.append((text, prepend_clipboard))
        self.app.process_audio_thread()
        self.assertEqual(result, [("normalized text", True)])
        self.assertIn({"cmd": "show_ready"}, self.messages())
        self.assertFalse(self.app.is_processing)

    def test_stream_start_failure_closes_resource_and_clears_recording(self):
        stream = Stream(callback=lambda *args: None)
        stream.start = lambda: (_ for _ in ()).throw(RuntimeError("start failed"))
        with patch.object(AUDIO.sd, "InputStream", return_value=stream):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                self.audio.start_recording()
        self.assertTrue(stream.closed)
        self.assertIsNone(self.audio.stream)
        self.assertFalse(self.audio.is_recording)

    def test_stop_failure_still_closes_stream_and_preserves_error(self):
        stream = Stream(callback=lambda *args: None)
        stream.active = True
        stream.stop = lambda: (_ for _ in ()).throw(RuntimeError("stop failed"))
        self.audio.stream = stream
        self.audio.is_recording = True
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            self.audio.stop_recording()
        self.assertTrue(stream.closed)
        self.assertFalse(stream.active)
        self.assertIsNone(self.audio.stream)
        self.assertFalse(self.audio.is_recording)

    def test_completed_processing_discards_previous_audio(self):
        self.app.is_processing = True
        self.audio.audio_data = [np.ones((16000, 1), dtype=np.float32)]
        self.app.process_audio_thread()
        self.assertEqual(self.audio.audio_data, [])

    def test_failed_close_cannot_be_overwritten_by_a_new_stream(self):
        old_stream = Stream(callback=lambda *args: None)
        old_stream.active = True
        old_stream.close = lambda: (_ for _ in ()).throw(RuntimeError("close failed"))
        self.audio.stream = old_stream
        self.audio.is_recording = True
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            self.audio.cancel_recording()
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            self.audio.start_recording()
        self.assertIs(self.audio.stream, old_stream)
        self.assertEqual(self.streams, [])
        old_stream.close = lambda: setattr(old_stream, "closed", True)

    def test_empty_next_session_does_not_replay_completed_dictation(self):
        self.app.is_processing = True
        self.audio.audio_data = [np.ones((16000, 1), dtype=np.float32)]
        self.audio.engine_type = "whisper"
        self.audio.get_or_load_model = lambda: types.SimpleNamespace(
            transcribe=lambda data, language: ([types.SimpleNamespace(text="previous recording")], None)
        )
        self.audio.transcribe = lambda: AUDIO.AudioEngine.transcribe(self.audio)
        self.app.process_audio_thread()
        self.assertEqual(self.copied, ["previous recording"])
        # The next stop worker can run before its start worker opens a stream.
        self.app._recording_id += 1
        self.app.is_processing = True
        self.app.process_audio_thread()
        self.assertEqual(self.copied, ["previous recording"])

    def test_wake_enable_cannot_race_with_recording_device_start(self):
        entered, proceed = threading.Event(), threading.Event()
        applied = []

        def enable(start_mic=True):
            entered.set()
            proceed.wait(2)
            applied.append(start_mic)

        self.app.wake_detector.enable = enable
        caller = threading.Thread(target=lambda: self.app.on_toggle_wake(True), daemon=True)
        caller.start()
        self.assertTrue(entered.wait(2))
        self.app.toggle_recording()
        # Enable owns device serialization until it has applied the setting.
        self.assertFalse(self.audio.is_recording)
        proceed.set()
        caller.join(2)
        self.wait_for(lambda: self.audio.is_recording)
        self.app.cancel_recording()
        self.threads.join()
        self.assertEqual(applied, [True])

    def test_stale_start_error_does_not_close_a_new_recording(self):
        self.app.is_recording = True
        self.app._recording_id = 1

        def fail():
            raise RuntimeError("old startup failed")

        self.audio.start_recording = fail

        def new_operation(stage, error, rec_id=None):
            # Another worker completed recovery while error reporting yielded.
            self.app._recording_id = 2
            self.app.is_recording = True
            self.audio.stream = Stream(callback=lambda *args: None)
            self.audio.stream.start()
            self.audio.is_recording = True

        self.app._report_error = new_operation
        self.app.start_recording_thread(1)
        self.assertTrue(self.audio.is_recording)
        self.assertTrue(self.audio.stream.active)
        self.assertTrue(self.app.is_recording)

    def test_cleanup_continues_after_wake_shutdown_failure(self):
        def fail():
            raise RuntimeError("wake close failed")

        self.app.wake_detector.disable = fail
        self.audio._stop_watchdog = False
        self.audio.unload_model = lambda: None
        self.audio.stream = Stream(callback=lambda *args: None)
        self.audio.stream.start()
        self.audio.is_recording = True
        stopped = []
        self.app.tray = types.SimpleNamespace(stop=lambda: stopped.append("tray"))
        self.app.hotkey_mgr = types.SimpleNamespace(stop=lambda: stopped.append("hotkey"))
        with patch.object(MAIN, "release_single_instance", lambda: stopped.append("mutex")):
            try:
                self.app.cleanup()
            except RuntimeError:
                pass
        self.assertIsNone(self.audio.stream)
        self.assertTrue(self.audio._stop_watchdog)
        self.assertEqual(stopped, ["tray", "hotkey", "mutex"])

    def test_shutdown_during_processing_skips_copy_and_microphone_resume(self):
        self.app.is_processing = True

        def transcribe():
            self.app.quit_app()
            return "text after close"

        self.audio.transcribe = transcribe
        self.app.process_audio_thread()
        self.assertEqual(self.copied, [])
        self.assertEqual(self.resumed, [])

    def test_autostop_processes_once_and_releases_microphone(self):
        self.app.toggle_recording()
        self.wait_for(lambda: self.audio.is_recording)
        with patch.object(CONFIG, "MAX_RECORD_SECONDS", 0):
            self.threads.join()
        self.assertFalse(self.app.is_recording)
        self.assertFalse(self.app.is_processing)
        self.assertFalse(self.audio.is_recording)
        self.assertEqual(self.copied, ["dictated text"])

    def test_old_watchdog_cannot_stop_new_recording(self):
        self.app._recording_id = 2
        self.app.is_recording = True
        with patch.object(CONFIG, "MAX_RECORD_SECONDS", 0):
            self.app._recording_watchdog(1)
        self.assertTrue(self.app.is_recording)
        self.assertFalse(self.app.is_processing)
        self.assertEqual(self.copied, [])

    def test_wake_start_stop_preserves_full_audio_and_start_sound(self):
        sounds = []
        self.app.ui.alert_enabled = True
        self.audio.audio_data = [np.ones((32000, 1), dtype=np.float32)]
        with patch.object(MAIN, "play_ready_sound", lambda: sounds.append(True)):
            self.app.on_wake_trigger()
            self.wait_for(lambda: self.audio.is_recording)
            self.audio._audio_callback(np.ones((32000, 1), dtype=np.float32), 32000, None, None)
            sizes = []
            self.audio.transcribe = lambda: sizes.append(len(np.concatenate(self.audio.audio_data))) or "text"
            self.app.on_wake_trigger()
            self.threads.join()
        self.assertEqual(sounds, [True])
        self.assertEqual(sizes, [32000])  # Group 4 preserves the end of the recording.
        self.assertEqual(self.copied, ["text"])


class WakeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.wake = WAKE.WakeWordDetector()
        self.wake._is_enabled = True
        self.wake.model = object()
        self.wake.recognizer = None

    def test_pause_allows_inflight_callback_to_complete(self):
        entered, advance, finished = threading.Event(), threading.Event(), threading.Event()
        actual_process = self.wake._process_pcm

        def pending_callback(data):
            entered.set()
            advance.wait(2)
            actual_process(data)

        self.wake._process_pcm = pending_callback
        self.wake._is_listening_mic = True

        def callback():
            self.wake._audio_callback(b"audio", 0, None, None)
            finished.set()

        thread = threading.Thread(target=callback, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(2))
        timed_out = []
        stream = Stream(callback=callback)

        def stop():
            advance.set()
            timed_out.append(not finished.wait(0.25))

        stream.stop = stop
        self.wake.stream = stream
        self.wake.pause_mic()
        thread.join(2)
        self.assertEqual(timed_out, [False])
        self.assertTrue(stream.closed)
        self.assertIsNone(self.wake.stream)

    def test_pending_listener_start_cannot_reopen_a_paused_microphone(self):
        self.wake.recognizer = object()
        self.wake.pause_mic()
        opened = []

        def make_stream(**kwargs):
            opened.append(Stream(**kwargs))
            return opened[-1]

        with patch.object(WAKE.sd, "RawInputStream", make_stream):
            self.wake.start_mic()  # A worker previously queued by enable().
        self.assertEqual(opened, [])
        self.assertIsNone(self.wake.stream)

    def test_pending_listener_start_cannot_reopen_a_disabled_microphone(self):
        self.wake.recognizer = object()
        self.wake._is_enabled = False
        opened = []
        with patch.object(WAKE.sd, "RawInputStream", side_effect=lambda **kw: opened.append(kw)):
            self.wake.start_mic()
        self.assertEqual(opened, [])

    def test_listener_start_failure_closes_created_stream(self):
        self.wake.recognizer = object()
        stream = Stream(callback=lambda *args: None)
        stream.start = lambda: (_ for _ in ()).throw(RuntimeError("start failed"))
        with patch.object(WAKE.sd, "RawInputStream", return_value=stream):
            self.wake.start_mic()
        self.assertTrue(stream.closed)
        self.assertIsNone(self.wake.stream)
        self.assertFalse(self.wake._is_listening_mic)

    def test_resume_reopens_listener_after_pause(self):
        self.wake.recognizer = object()
        self.wake.pause_mic()
        opened = []

        def make_stream(**kwargs):
            opened.append(Stream(**kwargs))
            return opened[-1]

        with patch.object(WAKE.sd, "RawInputStream", make_stream):
            self.wake.resume_mic()
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].active)
        self.wake.pause_mic()

    def test_disabling_during_listener_start_leaves_no_active_stream(self):
        self.wake.recognizer = object()
        entered, proceed = threading.Event(), threading.Event()
        stream = Stream(callback=lambda *args: None)

        def slow_start():
            entered.set()
            if not proceed.wait(2):
                raise RuntimeError("test gate timed out")
            stream.active = True

        stream.start = slow_start
        with patch.object(WAKE.sd, "RawInputStream", return_value=stream):
            starter = threading.Thread(target=self.wake.start_mic, daemon=True)
            starter.start()
            self.assertTrue(entered.wait(2))
            disabler = threading.Thread(target=self.wake.disable, daemon=True)
            disabler.start()
            deadline = time.monotonic() + 2
            while self.wake._is_enabled and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertFalse(self.wake._is_enabled)
            proceed.set()
            starter.join(2)
            disabler.join(2)
        self.assertFalse(starter.is_alive() or disabler.is_alive())
        self.assertFalse(stream.active)
        self.assertTrue(stream.closed)
        self.assertIsNone(self.wake.stream)

    def test_resume_recovers_after_a_transient_close_failure(self):
        self.wake.recognizer = object()
        old_stream = Stream(callback=lambda *args: None)
        old_stream.active = True
        self.wake.stream = old_stream
        self.wake._is_listening_mic = True
        attempts = []

        def close():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("transient close failure")
            old_stream.closed = True

        old_stream.close = close
        with self.assertRaisesRegex(RuntimeError, "transient close failure"):
            self.wake.pause_mic()
        new_stream = Stream(callback=self.wake._audio_callback)
        with patch.object(WAKE.sd, "RawInputStream", return_value=new_stream):
            self.wake.resume_mic()
        self.assertTrue(old_stream.closed)
        self.assertTrue(new_stream.active)
        self.assertTrue(self.wake._is_listening_mic)
        self.assertIs(self.wake.stream, new_stream)
        self.wake.pause_mic()


class WakeRecognitionTests(unittest.TestCase):
    def _recognizer(self, partial):
        class Recognizer:
            def __init__(self):
                self.fed = []

            def AcceptWaveform(self, data):
                self.fed.append(data)
                return False

            def PartialResult(self):
                return '{"partial": "%s"}' % partial

            def Result(self):
                return '{"text": ""}'

            def Reset(self):
                pass

        return Recognizer()

    def test_cooldown_still_feeds_the_recognizer(self):
        wake = WAKE.WakeWordDetector(keyword="shockwave")
        wake.recognizer = self._recognizer("shockwave")
        started = wake._last_trigger_time = time.time()
        wake._process_pcm(b"pcm")
        self.assertEqual(wake.recognizer.fed, [b"pcm"])
        self.assertEqual(wake._last_trigger_time, started)

    def test_partial_matches_a_multiword_phrase(self):
        hit = threading.Event()
        wake = WAKE.WakeWordDetector(on_wake_callback=hit.set, keyword="tiger trade")
        wake.recognizer = self._recognizer("this is tiger trade")
        wake._process_pcm(b"pcm")
        self.assertTrue(hit.wait(1))

    def test_microphone_callback_returns_without_recognition(self):
        wake = WAKE.WakeWordDetector()
        wake._is_enabled = True
        wake._is_listening_mic = True
        wake._process_pcm = lambda data: time.sleep(0.4)
        started = time.monotonic()
        wake._audio_callback(b"audio", 0, None, None)
        self.assertLess(time.monotonic() - started, 0.2)
        wake.disable()


if __name__ == "__main__":
    unittest.main()
