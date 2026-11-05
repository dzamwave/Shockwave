import numpy as np
import sounddevice as sd
import time
import os
import threading

import config

import importlib.metadata
_original_version = importlib.metadata.version
def _safe_version(pkg_name):
    try:
        return _original_version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        if "onnx" in pkg_name or "asr" in pkg_name:
            return "0.12.0"
        raise
importlib.metadata.version = _safe_version

class AudioEngine:
    def __init__(self):
        self.stream = None
        self.audio_data = []
        self.sample_rate = 16000
        self.is_recording = False
        self.on_audio_chunk = None
        self._audio_statuses = []
        
        self.engine_type = getattr(config, "STT_ENGINE", "whisper").lower()
        self.model = None
        self.vad = None
        self._loaded_engine = None
        self._model_lock = threading.Lock()
        self._is_loading_model = False
        self._last_used_time = 0.0
        self._stop_watchdog = False

        # Background watchdog to unload model from memory after idle timeout
        self._watchdog_thread = threading.Thread(target=self._idle_watchdog, daemon=True)
        self._watchdog_thread.start()

    def active_engine(self):
        """The recognizer for the current widget choice.

        ru always uses GigaAM. multi uses the Parakeet or Whisper model
        named in config.ini.
        """
        mode = str(getattr(config, "RECOGNITION_MODE", "ru")).strip().lower()
        if mode == "multi":
            return str(getattr(config, "MULTI_ENGINE", "parakeet")).strip().lower()
        return "gigaam"

    def _onnx_session_options(self):
        if not getattr(config, "ONNX_OPTIMIZE_MEMORY", True):
            return None
        try:
            import onnxruntime as ort
            sess_options = ort.SessionOptions()
            sess_options.enable_cpu_mem_arena = False
            sess_options.enable_mem_pattern = False
            sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            sess_options.intra_op_num_threads = min(4, os.cpu_count() or 4)
            sess_options.inter_op_num_threads = 1
            print("[AudioEngine] ONNX memory optimizations applied (arena=False, pattern=False).")
            return sess_options
        except Exception as e:
            print(f"[AudioEngine] Could not configure ONNX session options: {e}")
            return None

    def _load_onnx_model(self, model_name, folder):
        import onnx_asr
        quant = None if config.GIGAAM_QUANTIZATION in ("", "float32") else config.GIGAAM_QUANTIZATION
        sess_options = self._onnx_session_options()
        if os.path.isdir(folder) and os.listdir(folder):
            print(f"[AudioEngine] Loading from local path: {folder}")
            return onnx_asr.load_model(model_name, path=folder, quantization=quant, sess_options=sess_options)
        return onnx_asr.load_model(model_name, quantization=quant, sess_options=sess_options)

    def _segment_text(self, model, audio_np):
        """Recognize one recording, splitting it at pauses when a VAD is loaded."""
        vad = getattr(self, "vad", None)
        if vad is None:
            text = model.recognize(audio_np)
            return text.strip() if isinstance(text, str) else str(text).strip()
        parts = []
        for segment in model.with_vad(vad).recognize(audio_np, sample_rate=self.sample_rate):
            text = getattr(segment, "text", "")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return " ".join(parts).strip()

    def get_or_load_model(self):
        """Loads the recognizer selected by the widget into memory on demand."""
        with self._model_lock:
            engine = self.active_engine()
            if self.model is not None and self._loaded_engine == engine:
                return self.model
            if self.model is not None:
                print(f"[AudioEngine] Switching recognizer from {self._loaded_engine} to {engine}.")
                self.model = None
                self.vad = None

            self.engine_type = engine
            self._loaded_engine = engine
            print(f"\n[AudioEngine] Loading STT model ({engine}) into memory...")
            start_t = time.time()

            if engine == "whisper":
                try:
                    from faster_whisper import WhisperModel
                    whisper_path = config.WHISPER_MODEL_PATH if config.WHISPER_MODEL_PATH else config.WHISPER_DIR
                    cpu_threads = min(4, os.cpu_count() or 4)
                    if os.path.exists(whisper_path) and os.path.exists(os.path.join(whisper_path, "model.bin")):
                        print(f"[AudioEngine] Loading Whisper model from local path: {whisper_path} ...")
                        self.model = WhisperModel(whisper_path, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
                    else:
                        model_name = config.WHISPER_MODEL
                        print(f"[AudioEngine] Loading Whisper model by name: {model_name} ...")
                        self.model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=whisper_path, cpu_threads=cpu_threads)
                    print(f"[AudioEngine] Whisper model loaded successfully in {time.time() - start_t:.2f}s.")
                except Exception as e:
                    print(f"[AudioEngine] Error loading Whisper: {e}")
                    self.model = None
            else:
                try:
                    model_name = config.GIGAAM_MODEL if engine == "gigaam" else config.MULTI_MODEL
                    folder = config.GIGAAM_DIR if engine == "gigaam" else config.PARAKEET_DIR
                    label = "GigaAM" if engine == "gigaam" else "Parakeet"
                    print(f"[AudioEngine] Loading {label} model: {model_name} ...")
                    self.model = self._load_onnx_model(model_name, folder)
                    print(f"[AudioEngine] {label} model loaded successfully in {time.time() - start_t:.2f}s.")
                    self._load_vad()
                except Exception as e:
                    print(f"[AudioEngine] Error loading {engine}: {e}")
                    self.model = None

            self._last_used_time = time.time()
            return self.model

    def _load_vad(self):
        """Load the pause detector used to split a long recording. Optional."""
        try:
            import onnx_asr
            folder = config.VAD_DIR
            if os.path.isdir(folder) and os.listdir(folder):
                self.vad = onnx_asr.load_vad("silero", path=folder)
            else:
                self.vad = onnx_asr.load_vad("silero")
            print("[AudioEngine] Pause detection loaded.")
        except Exception as e:
            self.vad = None
            print(f"[AudioEngine] Pause detection unavailable, using the whole recording: {e}")

    def preload_model_async(self):
        """Starts loading STT model in background while recording audio to minimize transcription latency."""
        if self.model is None and not self._is_loading_model:
            def _loader():
                self._is_loading_model = True
                try:
                    self.get_or_load_model()
                finally:
                    self._is_loading_model = False
            threading.Thread(target=_loader, daemon=True).start()

    def unload_model(self):
        """Unloads STT model and frees memory back to the operating system."""
        with self._model_lock:
            if self.model is None:
                return
            print(f"\n[AudioEngine] Idle timeout reached. Unloading STT model ({self.engine_type}) from memory...")
            self.model = None
            self.vad = None
            self._loaded_engine = None
            import gc
            gc.collect()
            try:
                import ctypes
                h_proc = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.psapi.EmptyWorkingSet(h_proc)
            except Exception:
                pass
            print("[AudioEngine] STT model unloaded successfully. Memory freed.")

    def _idle_watchdog(self):
        """Monitors model inactivity and unloads when idle timeout is exceeded."""
        while not self._stop_watchdog:
            time.sleep(5)
            timeout = getattr(config, "MODEL_IDLE_TIMEOUT", 300)
            if timeout <= 0:
                continue
            if self.is_recording:
                continue
            if self.model is not None and not self._is_loading_model:
                if (time.time() - self._last_used_time) >= timeout:
                    self.unload_model()

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each audio block."""
        if self.is_recording:
            if status:
                status_text = str(status)
                if status_text not in self._audio_statuses:
                    self._audio_statuses.append(status_text)
            self.audio_data.append(indata.copy())
            if self.on_audio_chunk:
                self.on_audio_chunk(indata)

    def start_recording(self):
        # Retain and retry any stream whose previous close failed; never lose
        # its handle by replacing it with another microphone stream.
        self.is_recording = False
        self._close_stream()
        model_state = "ready" if getattr(self, "model", None) is not None else "not loaded"
        print(f"[AudioEngine] Model at recording start: {model_state}.")
        # Asynchronously load/warm up STT model during speech to avoid post-recording latency
        self.preload_model_async()
        self.audio_data = []
        self._audio_statuses = []
        self.is_recording = True
        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='float32',
                callback=self._audio_callback
            )
            self.stream.start()
        except Exception:
            self.is_recording = False
            try:
                self._close_stream()
            except Exception as e:
                print(f"[AudioEngine] Cleanup after start failure: {e}")
            self.audio_data = []
            raise

    def _close_stream(self):
        """Always attempt close, even when stop fails; preserve the first error."""
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
            self.stream = None
        if error is not None:
            raise error

    def stop_recording(self, trim_seconds=0.0):
        self.is_recording = False
        self._close_stream()
            
        if trim_seconds > 0.0 and self.audio_data:
            samples_to_trim = int(trim_seconds * self.sample_rate)
            audio_np = np.concatenate(self.audio_data, axis=0).flatten()
            if len(audio_np) > samples_to_trim:
                trimmed_np = audio_np[:-samples_to_trim]
                self.audio_data = [trimmed_np.reshape(-1, 1)]
                print(f"[AudioEngine] Trimmed last {trim_seconds}s from recording.")

    def cancel_recording(self):
        """Immediately stops the stream and flushes all audio buffers without saving."""
        self.is_recording = False
        try:
            self._close_stream()
        finally:
            self.audio_data = []
            self._last_used_time = time.time()

    def transcribe(self) -> str:
        model_wait_start = time.monotonic()
        model = self.get_or_load_model()
        print(f"[AudioEngine] Model wait after recording: {time.monotonic() - model_wait_start:.2f}s.")
        statuses = getattr(self, "_audio_statuses", [])
        print(f"[AudioEngine] Input status: {', '.join(statuses) if statuses else 'OK'}.")
        if not model:
            print("Error: No STT model loaded.")
            return ""
            
        if not self.audio_data:
            print("Error: No audio data recorded.")
            return ""
            
        # Concatenate audio chunks and flatten to 1D array
        audio_np = np.concatenate(self.audio_data, axis=0).flatten()
        duration = len(audio_np) / self.sample_rate
        rms = np.sqrt(np.mean(np.square(audio_np, dtype=np.float64))) if audio_np.size else 0.0
        peak = np.max(np.abs(audio_np)) if audio_np.size else 0.0
        print(f"[AudioEngine] Audio: duration={duration:.2f}s, rms={rms:.6f}, peak={peak:.6f}.")
        
        if duration < 0.5:
            print("Error: Audio too short!")
            return ""
        
        try:
            if self.engine_type == "whisper":
                text = self._whisper_text(model, audio_np)
            else:
                recognition_start = time.monotonic()
                text = self._segment_text(model, audio_np)
                label = "GigaAM" if self.engine_type == "gigaam" else "Parakeet"
                print(f"[AudioEngine] {label} recognition time={time.monotonic() - recognition_start:.2f}s.")
                print(f"{label} output: {text}")
            self._last_used_time = time.time()
            return text
        except Exception as e:
            print(f"Transcription exception: {e}")
            return ""

    def _whisper_text(self, model, audio_np):
        configured_language = getattr(config, "WHISPER_LANGUAGE", "en").strip().lower()
        whisper_lang = None if configured_language in ("", "auto", "detect") else configured_language
        segments, info = model.transcribe(audio_np, language=whisper_lang)
        text = " ".join([segment.text for segment in segments])
        detected_language = whisper_lang or getattr(info, "language", None) or "auto"
        print(f"Whisper output ({detected_language}): {text}")
        return text.strip()

    def cleanup(self):
        """Stops background watchdog, halts recording, and unloads model."""
        self._stop_watchdog = True
        try:
            self.cancel_recording()
        finally:
            self.unload_model()
