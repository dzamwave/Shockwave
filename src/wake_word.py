import os
import sys
import json
import re
import time
import queue
import threading
import sounddevice as sd
import numpy as np

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import vosk
except ImportError:
    vosk = None

import config

def _valid_vosk_model(folder):
    required = ("am/final.mdl", "conf/mfcc.conf")
    graphs = (("graph/HCLr.fst", "graph/Gr.fst"), ("graph/HCLG.fst",))
    def present(name):
        path = os.path.join(folder, name)
        return os.path.isfile(path) and os.path.getsize(path) > 0
    return all(present(name) for name in required) and any(
        all(present(name) for name in group) for group in graphs
    )


def ensure_vosk_model(model_dir=None):
    """Validate locally, then stage downloads before publishing into an empty folder."""
    import shutil
    import tempfile
    import urllib.request
    import zipfile

    target_dir = model_dir or getattr(config, "VOSK_MODEL_PATH", None) or config.VOSK_DIR
    if _valid_vosk_model(target_dir):
        return target_dir

    def placeholder_only():
        return os.path.isdir(target_dir) and all(
            name == ".gitkeep" and os.path.isfile(os.path.join(target_dir, name))
            for name in os.listdir(target_dir)
        )

    if os.path.lexists(target_dir) and not placeholder_only():
        print(f"[WakeWord] Incomplete Vosk model at {target_dir}; existing files preserved.")
        return None
    mirrors = []
    for url in (getattr(config, "VOSK_MODEL_URLS", ()) or (getattr(config, "VOSK_MODEL_URL", None),)):
        if url and url not in mirrors:
            mirrors.append(url)
    staging = backup = None
    try:
        parent = os.path.dirname(os.path.abspath(target_dir))
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".vosk-download-", dir=parent)
        archive_path = os.path.join(staging, "model.zip")
        extracted = os.path.join(staging, "unpacked")
        for url in mirrors:
            try:
                print(f"[WakeWord] Downloading Vosk model from: {url} ...")
                urllib.request.urlretrieve(url, archive_path)
                with zipfile.ZipFile(archive_path) as archive:
                    for member in archive.infolist():
                        destination = os.path.abspath(os.path.join(extracted, member.filename))
                        if os.path.commonpath((os.path.abspath(extracted), destination)) != os.path.abspath(extracted):
                            raise ValueError("Archive path outside staging directory")
                    archive.extractall(extracted)
                model = os.path.join(extracted, config.VOSK_MODEL_NAME)
                if not _valid_vosk_model(model):
                    raise ValueError("Archive does not contain a complete Vosk model")
                break
            except Exception as err:
                print(f"[WakeWord] Mirror failed: {err}. Trying next mirror...")
                if os.path.isdir(extracted):
                    shutil.rmtree(extracted)
        else:
            print("[WakeWord] Error: Could not download a complete Vosk model.")
            return None
        # Recheck after download: never overwrite files added in the meantime.
        if os.path.lexists(target_dir):
            if not placeholder_only():
                raise ValueError("Destination changed during download; files preserved")
            backup = os.path.join(staging, "original")
            os.rename(target_dir, backup)
            placeholder = os.path.join(backup, ".gitkeep")
            if os.path.isfile(placeholder):
                shutil.copy2(placeholder, os.path.join(model, ".gitkeep"))
        os.rename(model, target_dir)
        if backup:
            shutil.rmtree(backup)
            backup = None
        return target_dir
    except Exception as err:
        print(f"[WakeWord] Model preparation failed: {err}")
        if backup and os.path.exists(backup):
            try:
                os.rename(backup, target_dir)
                backup = None
            except OSError as restore_error:
                print(f"[WakeWord] Original folder retained at {backup}: {restore_error}")
        return None
    finally:
        if staging and not backup:
            shutil.rmtree(staging, ignore_errors=True)

class WakeWordDetector:
    def __init__(self, on_wake_callback=None, model_path=None, keyword=None):
        self.on_wake_callback = on_wake_callback
        self.keyword = (keyword or getattr(config, "WAKE_WORD", "shockwave")).lower().strip()

        default_model = getattr(config, "VOSK_MODEL_PATH", None) or os.path.join(config.MODELS_DIR, "vosk-model-small-ru")
        self.model_path = model_path or default_model
        
        self.model = None
        self.recognizer = None
        self.stream = None
        
        self._is_enabled = False
        self._is_listening_mic = False
        self._last_trigger_time = 0.0
        self._lock = threading.Lock()
        self._stream_lock = threading.RLock()
        self._mic_paused = False
        self._audio_q = queue.Queue(maxsize=50)
        self._worker = None
        self._worker_stop = threading.Event()
        self._worker_lock = threading.Lock()

        # Deferred loading: Vosk model is loaded only when enable() / start_mic() is invoked.

    def _init_model(self):
        if self.model and self.recognizer:
            return
        if not vosk:
            print("[WakeWord] Error: Vosk library is not installed.")
            return

        candidate_path = ensure_vosk_model(self.model_path)
        if not candidate_path:
            return
        if not os.path.exists(candidate_path):
            candidate_path = config.get_resource_path(candidate_path)
            
        if not os.path.exists(candidate_path):
            print(f"[WakeWord] Vosk model not found at {candidate_path}.")
            return

        try:
            # Suppress excessive Vosk log spam
            vosk.SetLogLevel(-1)
            self.model = vosk.Model(candidate_path)
            # Use full language model vocabulary so Vosk accurately distinguishes all words
            self.recognizer = vosk.KaldiRecognizer(self.model, 16000)
        except Exception as e:
            print(f"[WakeWord] Model init error: {e}")

    def _ensure_worker(self):
        with self._worker_lock:
            if not self._is_enabled:
                return
            if self._worker and self._worker.is_alive():
                return
            self._worker_stop.clear()
            self._worker = threading.Thread(target=self._pcm_worker, name="wake-pcm", daemon=True)
            self._worker.start()

    def _stop_worker(self):
        self._worker_stop.set()
        try:
            self._audio_q.put_nowait(None)
        except queue.Full:
            pass
        worker = self._worker
        if worker and worker.is_alive() and threading.current_thread() is not worker:
            worker.join(timeout=1.0)
        while True:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break

    def _pcm_worker(self):
        while not self._worker_stop.is_set():
            try:
                pcm_bytes = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if pcm_bytes:
                self._process_pcm(pcm_bytes)

    def _enqueue(self, pcm_bytes):
        if not pcm_bytes:
            return
        self._ensure_worker()
        try:
            self._audio_q.put_nowait(pcm_bytes)
        except queue.Full:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                return
            try:
                self._audio_q.put_nowait(pcm_bytes)
            except queue.Full:
                pass

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice.RawInputStream for each audio buffer."""
        if status:
            pass
        if self._is_listening_mic and self._is_enabled:
            self._enqueue(bytes(indata))

    def feed_audio(self, pcm_data):
        """Allows feeding audio chunks directly from an external stream (e.g. AudioEngine)."""
        if not self._is_enabled or not self.recognizer:
            return

        if isinstance(pcm_data, np.ndarray):
            # Convert float32 [-1.0, 1.0] to int16 bytes
            pcm_bytes = (pcm_data * 32767).astype(np.int16).tobytes()
        elif isinstance(pcm_data, (bytes, bytearray)):
            pcm_bytes = bytes(pcm_data)
        else:
            return

        self._enqueue(pcm_bytes)

    def _process_pcm(self, pcm_bytes):
        with self._lock:
            if not self.recognizer:
                return

            cooling = time.time() - self._last_trigger_time < 2.0
            detected = False
            kw_clean = self.keyword.strip().lower()
            pattern = r'(?:\b|^)' + re.escape(kw_clean) + r'(?:\b|$)'

            if self.recognizer.AcceptWaveform(pcm_bytes):
                res = json.loads(self.recognizer.Result())
                text = res.get("text", "").lower().strip()
                if text and (kw_clean in text.split() or re.search(pattern, text)):
                    detected = True
            else:
                pres = json.loads(self.recognizer.PartialResult())
                ptext = pres.get("partial", "").lower().strip()
                if ptext and re.search(pattern, ptext):
                    detected = True

            if not detected:
                return
            self.recognizer.Reset()
            if cooling:
                return
            self._last_trigger_time = time.time()
            print(f"\n[WakeWord] Exact trigger word detected: '{self.keyword}'!")
            callback = self.on_wake_callback
        if callback:
            threading.Thread(target=callback, daemon=True).start()

    def start_mic(self):
        """Starts background microphone stream for wake word detection."""
        with self._stream_lock:
            with self._lock:
                if not self._is_enabled or self._mic_paused:
                    return
                if not self.model or not self.recognizer:
                    self._init_model()
                    if not self.model or not self.recognizer:
                        return
                if self.stream is not None and self._is_listening_mic:
                    return

            try:
                # A failed close keeps its handle for retry. It is not an
                # active listener and must not prevent subsequent recovery.
                self._close_mic_stream()
                stream = sd.RawInputStream(
                    samplerate=16000,
                    blocksize=4000,
                    dtype='int16',
                    channels=1,
                    callback=self._audio_callback
                )
                with self._lock:
                    self.stream = stream
                    self._is_listening_mic = True
                stream.start()
                with self._lock:
                    cancelled = not self._is_enabled or self._mic_paused
                if cancelled:
                    self._close_mic_stream()
            except Exception as e:
                print(f"[WakeWord] Failed to open microphone stream: {e}")
                try:
                    self._close_mic_stream()
                except Exception as cleanup_error:
                    print(f"[WakeWord] Microphone cleanup error: {cleanup_error}")

    def _close_mic_stream(self):
        # Caller holds _stream_lock. The callback only needs _lock, which
        # must remain free while PortAudio waits for that callback to finish.
        with self._lock:
            self._is_listening_mic = False
            stream = self.stream
        if stream is None:
            return
        error = None
        try:
            stream.stop()
        except Exception as e:
            error = e
        try:
            stream.close()
        except Exception as e:
            if error is None:
                error = e
        else:
            with self._lock:
                self.stream = None
        if error is not None:
            raise error

    def pause_mic(self):
        """Temporarily halts internal mic capture (e.g. when main recording stream is active)."""
        with self._lock:
            self._mic_paused = True
            self._is_listening_mic = False
        with self._stream_lock:
            self._close_mic_stream()

    def resume_mic(self):
        """Resumes internal mic capture if wake word is enabled."""
        with self._lock:
            self._mic_paused = False
            enabled = self._is_enabled
        if enabled:
            self.start_mic()

    def enable(self, start_mic=True):
        """Enables wake word detection and starts listening."""
        with self._lock:
            self._is_enabled = True
            self._mic_paused = not start_mic
        self._ensure_worker()
        if start_mic:
            threading.Thread(target=self.start_mic, daemon=True).start()

    def unload_model(self):
        """Unloads Vosk model and recognizer from memory and releases OS pages."""
        with self._lock:
            if self.model is None and self.recognizer is None:
                return
            print("[WakeWord] Unloading Vosk model from memory...")
            self.recognizer = None
            self.model = None
            import gc
            gc.collect()
            try:
                import ctypes
                h_proc = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.psapi.EmptyWorkingSet(h_proc)
            except Exception:
                pass
            print("[WakeWord] Vosk model unloaded successfully. Memory freed.")

    def disable(self):
        """Disables wake word detection, closes microphone stream, and unloads model."""
        with self._lock:
            self._is_enabled = False
        try:
            self.pause_mic()
        finally:
            self._stop_worker()
            with self._stream_lock:
                self.unload_model()
