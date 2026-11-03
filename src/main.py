import threading
import queue
import time
import sys
import os
import re
from datetime import datetime

import config

from ui import WinVoiceUI, play_ready_sound
from audio_engine import AudioEngine
from llm_normalizer import LLMNormalizer
from typer import Typer
from hotkey_manager import SystemHotkeyManager
from single_instance import check_single_instance, release_single_instance
from tray_manager import SystemTrayManager, hide_console, show_console
from wake_word import WakeWordDetector
from glossary import GlossaryManager

class WinVoiceApp:
    def __init__(self):
        # 1. Single-Instance Protection: Prevent multiple instances running simultaneously
        if not check_single_instance():
            print("\n[Shockwave] Shockwave is already running!")
            time.sleep(1.5)
            sys.exit(0)

        self.q = queue.Queue()
        self.audio = AudioEngine()
        self.llm = LLMNormalizer()
        self.typer = Typer()
        self.glossary = GlossaryManager(getattr(config, "GLOSSARY_PATH", None))
        
        self.is_recording = False
        self.is_processing = False
        self._recording_id = 0
        self.lock = threading.Lock()
        # Device operations may wait for callbacks; never hold the state lock there.
        self._audio_lock = threading.RLock()
        self._shutting_down = False
        
        # 2. Wake Word Detector (Vosk)
        self.wake_detector = WakeWordDetector(on_wake_callback=self.on_wake_trigger)
        self.audio.on_audio_chunk = self.wake_detector.feed_audio
        
        # Initialize UI with click-to-trigger handler, cancel handler and wake word toggle
        self.ui = WinVoiceUI(
            self.q,
            position=config.UI_POSITION,
            on_trigger=self.toggle_recording,
            on_cancel=self.cancel_recording,
            on_toggle_wake=self.on_toggle_wake
        )
        
        # Activate wake word listener if enabled in settings
        if self.ui.wake_enabled:
            self.wake_detector.enable()
        else:
            print("[Shockwave] Wake word detection is disabled in config. Vosk model not loaded.")
        
        # 3. System Tray Manager: Place Shockwave icon next to clock with toggle & exit menu
        icon_path = config.get_resource_path(os.path.join("icons", "icon.ico"))
        self.tray = SystemTrayManager(
            icon_path=icon_path,
            tooltip=f"Shockwave v{getattr(config, 'APP_VERSION', '1.1.2')}",
            on_quit=self.quit_app,
            on_show_widget=self.show_widget_topmost
        )
        self.tray.start()
        
        # 4. Register permanent system-level hotkey via Win32 RegisterHotKey
        self.hotkey_mgr = SystemHotkeyManager(config.HOTKEY, self.toggle_recording)
        yellow_radar = "\033[38;2;255;215;0m\033[1mRadar\033[0m"
        wake_keyword = getattr(config, "WAKE_WORD", "shockwave")
        if self.ui.wake_enabled:
            print(f"Shockwave started. Press {config.HOTKEY.upper()}, click {yellow_radar} or say '{wake_keyword.capitalize()}' to record.")
        else:
            print(f"Shockwave started. Press {config.HOTKEY.upper()} or click {yellow_radar} to record (Wake word disabled).")
        
        # Hide console window to system tray smoothly
        hide_console()

    def show_widget_topmost(self):
        """Signals UI queue to display floating widget and bring it topmost above all windows."""
        self.q.put({"cmd": "show_topmost"})

    def on_toggle_wake(self, is_enabled):
        if is_enabled:
            print("[Shockwave] Wake word detection enabled.")
            with self._audio_lock:
                with self.lock:
                    busy = self.is_recording or self.is_processing or self._shutting_down
                self.wake_detector.enable(start_mic=not busy)
        else:
            print("[Shockwave] Wake word detection disabled.")
            with self._audio_lock:
                self.wake_detector.disable()

    def on_wake_trigger(self):
        """Called automatically when the configured wake word is detected."""
        self._toggle_recording(is_wake_word=True)

    def cancel_recording(self):
        """Discards active recording immediately and resets UI state."""
        with self.lock:
            if not self.is_recording:
                return
            print("Cancelling recording upon user request...")
            self.is_recording = False
            self.is_processing = True
            # Invalidate the start worker before waiting for device cleanup.
            self._recording_id += 1
            rec_id = self._recording_id
            self.q.put({"cmd": "show", "text": "cancelling"})
        threading.Thread(target=self._cancel_recording_thread, args=(rec_id,), daemon=True).start()

    def _cancel_recording_thread(self, rec_id):
        try:
            with self._audio_lock:
                self.audio.cancel_recording()
            self.q.put({"cmd": "show", "text": "what is your command?"})
        except Exception as e:
            self._report_error("cancel", e)
        finally:
            self._finish_recording(rec_id)

    def toggle_recording(self):
        self._toggle_recording(is_wake_word=False)

    def _toggle_recording(self, is_wake_word):
        with self.lock:
            if self.is_processing or self._shutting_down:
                return
                
            if not self.is_recording:
                self.is_recording = True
                self._recording_id += 1
                rec_id = self._recording_id
                self.q.put({"cmd": "show", "text": "record"})
                worker = threading.Thread(
                    target=self.start_recording_thread,
                    args=(rec_id, is_wake_word), daemon=True
                )
            else:
                self.is_recording = False
                self.is_processing = True
                rec_id = self._recording_id
                worker = threading.Thread(
                    target=self.process_audio_thread,
                    kwargs={"is_wake_word": is_wake_word, "rec_id": rec_id}, daemon=True
                )
        worker.start()

    def _recording_watchdog(self, rec_id):
        warn_seconds = getattr(config, "WARN_RECORD_SECONDS", 150)
        max_seconds = getattr(config, "MAX_RECORD_SECONDS", 180)
        warned = False
        start_time = time.monotonic()
        
        while True:
            time.sleep(0.25)
            with self.lock:
                if not self.is_recording or self._recording_id != rec_id or self._shutting_down:
                    break
                
                elapsed = time.monotonic() - start_time
                if not warned and elapsed >= warn_seconds:
                    warned = True
                    self.q.put({"cmd": "radar_warning"})
                    
                if elapsed >= max_seconds:
                    yellow_auto = "\033[38;2;255;180;50m\033[1m[Auto-Stop]\033[0m"
                    print(f"\n{yellow_auto} Reached {max_seconds}s limit. Stopping recording automatically...")
                    self.is_recording = False
                    self.is_processing = True
                    threading.Thread(
                        target=self.process_audio_thread,
                        kwargs={"rec_id": rec_id}, daemon=True
                    ).start()
                    break

    def start_recording_thread(self, rec_id, is_wake_word=False):
        try:
            with self._audio_lock:
                with self.lock:
                    if self._recording_id != rec_id or not self.is_recording or self._shutting_down:
                        # Stop won before the microphone opened: this session has no samples.
                        if self._recording_id == rec_id and not self._shutting_down:
                            self.audio.audio_data = []
                        return
                self.wake_detector.pause_mic()
                if is_wake_word and self.ui.alert_enabled:
                    play_ready_sound()
                start_time = datetime.now().strftime("%H:%M:%S")
                print(f"\nStarted recording {start_time}. ", end="", flush=True)
                self.audio.start_recording()
                with self.lock:
                    same_session = self._recording_id == rec_id and not self._shutting_down
                    still_recording = same_session and self.is_recording
                if not same_session:
                    self.audio.cancel_recording()
                    return
                if not still_recording:
                    # Stop is already waiting to transcribe these samples.
                    return
            threading.Thread(target=self._recording_watchdog, args=(rec_id,), daemon=True).start()
        except Exception as e:
            self._report_error("microphone", e, rec_id)
            self._finish_recording(rec_id)

    def _report_error(self, stage, error, rec_id=None):
        print(f"[Shockwave] {stage} error: {error}")
        with self.lock:
            if not self._shutting_down and (rec_id is None or self._recording_id == rec_id):
                self.q.put({"cmd": "show", "text": f"error: {stage}"})

    def _finish_recording(self, rec_id):
        # Keep processing=True until device restoration finishes, so a new start
        # cannot race with the previous operation's resume_mic().
        with self._audio_lock:
            with self.lock:
                if self._recording_id != rec_id or self._shutting_down:
                    return
                self.is_recording = False
                self.is_processing = True
            try:
                try:
                    # Also discard the completed buffer, preventing a very fast
                    # next start/stop from transcribing the previous dictation.
                    self.audio.cancel_recording()
                except Exception as e:
                    self._report_error("microphone cleanup", e, rec_id)
                try:
                    self.wake_detector.resume_mic()
                except Exception as e:
                    self._report_error("wake microphone", e, rec_id)
            finally:
                with self.lock:
                    if self._recording_id == rec_id:
                        self.is_processing = False

    def process_audio_thread(self, is_wake_word=False, rec_id=None):
        if rec_id is None:
            rec_id = self._recording_id
        try:
            self._process_audio(is_wake_word, rec_id)
        except Exception as e:
            self._report_error("processing", e, rec_id)
        finally:
            self._finish_recording(rec_id)

    def _process_audio(self, is_wake_word, rec_id):
        print("Stopping recording.")
        self.q.put({"cmd": "show", "text": "processing"})
        
        with self._audio_lock:
            with self.lock:
                if self._recording_id != rec_id or self._shutting_down:
                    return
            # Keep all audio: a fixed cut may remove the last useful word or number.
            self.audio.stop_recording(trim_seconds=0.0)
        raw_text = self.audio.transcribe()
        if raw_text and is_wake_word:
            keyword = self.wake_detector.keyword.strip()
            if keyword:
                # Remove only the recognized command at the end, before glossary/LLM.
                pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)[\s.!?,;:…]*$"
                raw_text = re.sub(pattern, "", raw_text, flags=re.IGNORECASE).rstrip()
        
        if raw_text:
            warnings = []
            # Apply user glossary substitutions
            try:
                processed_text = self.glossary.apply(raw_text)
            except Exception as e:
                print(f"[Glossary] Processing error: {e}. Original text preserved.")
                processed_text = raw_text
                warnings.append("glossary")
            if processed_text != raw_text:
                cyan_glossary = "\033[38;2;100;200;255m\033[1m[Glossary]\033[0m"
                print(f"{cyan_glossary} {processed_text}")
            raw_text = processed_text

            # Check if LLM processing is requested by any mode toggle
            needs_llm = self.ui.llm_enabled or self.ui.ai_task_enabled or self.ui.translate_en_enabled or getattr(self.ui, "idea_enabled", False)
            # If glossary processing failed, preserve the original instead of
            # applying further transformations and claiming it was saved unchanged.
            if needs_llm and not warnings:
                self.q.put({"cmd": "show", "text": "normalization"})
                try:
                    result = self.llm.normalize_result(
                        raw_text,
                        translate_en=self.ui.translate_en_enabled,
                        ai_task=self.ui.ai_task_enabled,
                        idea=getattr(self.ui, "idea_enabled", False),
                        normalize=self.ui.llm_enabled,
                    )
                    final_text = result.text if result.succeeded else raw_text
                    if not result.succeeded:
                        print(f"[Shockwave] {result.warning} Original text preserved.")
                        warnings.append("LLM")
                except Exception as e:
                    print(f"[Shockwave] LLM processing error: {e}. Original text preserved.")
                    final_text = raw_text
                    warnings.append("LLM")
            else:
                final_text = raw_text
                
            yellow_final = "\033[38;2;255;215;0m\033[1mFinal text:\033[0m"
            print(f"{yellow_final} {final_text}")
            with self._audio_lock:
                with self.lock:
                    if self._recording_id != rec_id or self._shutting_down:
                        return
                if getattr(self.ui, "paste_enabled", False):
                    self.typer.type_text(final_text, prepend_clipboard=self.ui.clip_prepend_enabled, auto_paste=True)
                else:
                    self.typer.type_text(final_text, prepend_clipboard=self.ui.clip_prepend_enabled)
                if warnings:
                    stage = "/".join(warnings)
                    text = f"{stage} failed: original saved"
                    self.q.put({"cmd": "show", "text": text})
                else:
                    self.q.put({"cmd": "show_ready"})
        else:
            print("Warning: Transcription was empty or failed. Skipping.")
            self.q.put({"cmd": "show", "text": "what is your command?"})
        
    def quit_app(self):
        """Cleanly signals UI to quit."""
        with self.lock:
            self._shutting_down = True
            self.is_recording = False
            self._recording_id += 1
        self.q.put({"cmd": "quit"})

    def cleanup(self):
        with self.lock:
            self._shutting_down = True
            self.is_recording = False
            self._recording_id += 1
        with self._audio_lock:
            for name in ("wake_detector", "audio"):
                component = getattr(self, name, None)
                if component is not None:
                    try:
                        if name == "wake_detector":
                            component.disable()
                        else:
                            component.cleanup()
                    except Exception as e:
                        print(f"[Shockwave] {name} shutdown error: {e}")
        for name in ("tray", "hotkey_mgr"):
            component = getattr(self, name, None)
            if component is not None:
                try:
                    component.stop()
                except Exception as e:
                    print(f"[Shockwave] {name} shutdown error: {e}")
        release_single_instance()

    def run(self):
        try:
            self.ui.run()
        finally:
            self.cleanup()

if __name__ == "__main__":
    app = WinVoiceApp()
    app.run()
