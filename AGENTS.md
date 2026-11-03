# Shockwave — Project Context (Level 1)

> **Local path:** `C:\Users\dzam\Desktop\VibeCoding\Shockwave-ENG`<br>
> **Stack:** Python 3.12, Faster-Whisper, Vosk, SoundDevice, Win32 API (`RegisterHotKey`), PyInstaller<br>
> **Interpreter:** `.\venv\Scripts\python.exe`<br>
> **Application version:** `1.1.2`<br>
> **Configuration:** `config/config.ini` (required working file, gitignored), `config/config.example.ini` (template with blank `endpoint`, `model`, and `api_key`), `config/prompts/*.md` (system prompts)

---

## 1. Purpose and features

Local, hands-free voice dictation for Windows, running in the background:

1. **Hands-free activation (Vosk):** Background wake-word recognition. Set the trigger with `wake_word` under `[Wake]` in `config.ini`. The recognized trailing stop word is removed from the transcript.
2. **System hotkey:** Native Win32 `RegisterHotKey`, default `Ctrl + Space`, designed to survive sleep and screen locking. Configure `hotkey` under `[Recording]`.
3. **Speech recognition (STT):**
   * **Whisper (`large-v3-turbo`):** The only speech engine. Multilingual recognition through `faster-whisper`; the language comes from `whisper_language`.
   * **Lazy loading:** Load the STT model on first use. An idle watchdog unloads it after `model_idle_timeout` seconds (default 300; 0 disables unloading). Asynchronous preloading starts when recording begins.
4. **LLM processing** (OpenAI-compatible endpoint, `[LLM]` in `config.ini`):
   * `LLM norm`: normalize punctuation and technical terminology.
   * `Idea`: structure spoken thoughts into a draft, extracting the main idea and removing filler while preserving the author's voice.
   * `AI task`: turn dictated speech into a clear, structured AI prompt. Mutually exclusive with `Idea`.
   * `to EN`: translate into English. With `AI task`, produce `AI task (EN)` in one request. With `Idea`, translate after structuring.
   * With `LLM norm`, `Idea`, and `to EN` enabled, run normalization, idea structuring, then translation.
   * Connection values come only from `[LLM]` in `config/config.ini`. A blank model uses `gemini-3.5-flash`. Environment files are not read.
   * HTTP is allowed only on loopback. External servers require HTTPS. Redirects (3xx) are rejected. Guardrail phrases detect provider warnings such as deprecation or model-not-found responses.
5. **Interface:** Floating 32×32 px dot-matrix radar widget with a 5×5 LED matrix, eight toggles in two rows, and a system tray icon. Legacy interface language settings are ignored.
6. **Recording watchdog:** After `warn_record_seconds` (default 150), the radar flashes red. At `max_record_seconds` (default 180), recording stops automatically.

---

## 2. Key files

* `src/launcher.py`: Entry point. Print the ANSI banner, read the configured engine, call `model_manager.ensure_configured_model()`, then start `main.WinVoiceApp`.
* `src/main.py`: Coordinate components, UI command queue, recording, LLM processing, clipboard output, and resource cleanup on exit.
* `src/audio_engine.py`: SoundDevice capture, frame buffer, lazy Whisper loading/unloading, idle watchdog, and transcription.
* `src/wake_word.py`: Queue audio chunks for a background Vosk recognition thread and invoke `on_wake_callback`. Controls: `enable`, `disable`, `pause_mic`, `resume_mic`.
* `src/model_manager.py`: Check Whisper weights and offer a y/n download from Hugging Face Hub when missing.
* `src/llm_normalizer.py`: `_processing_steps()` selects pipeline steps; `_apply_step()` sends one request. Validate TLS, loopback, and redirect restrictions. Return `NormalizationResult(text, succeeded, warning)`.
* `src/hotkey_manager.py`: Win32 `RegisterHotKey`, with the `keyboard` library as fallback.
* `src/ui.py`: Tkinter floating overlay using `overrideredirect`. Animate the radar every 35 ms with a rotating sweep and fading trail. Row 0: `LLM norm`, `AI task`, `to EN`, `Idea`; row 1: `wake`, `alert`, `clip+`, `paste`. Include a countdown timer. `WS_EX_TOOLWINDOW` keeps the widget off the taskbar; call `enforce_topmost` every ten queue ticks (about one second).
* `src/tray_manager.py`: Tray icon, show-widget/show-console/hide-console/exit menu, and console visibility controls.
* `src/glossary.py`: Apply `glossary.txt` replacements and reload when the file modification time changes.
* `src/typer.py`: Copy finished text using `pyperclip`. With `clip_prepend=True`, prepend it above existing clipboard content using `\n\n`. With `auto_paste=True`, send `Ctrl+V` after copying to paste into the active input field.
* `src/config.py`: Read INI settings, environment fallback, and defaults. Sections: `[Recording]`, `[Recognition]`, `[Wake]`, `[Text]`, `[LLM]`, `[Prompts]`, `[Widget]`, `[Sound]`, `[Console]`. `save_setting()` writes atomically through a temporary file. `get_prompt()` checks `[Prompts]`, Markdown prompt files, then built-in defaults.
* `src/single_instance.py`: Enforce a single running process using a named Windows mutex.
* `start.bat`: Launch using the virtual environment.
* `build.bat`: Build the executable using PyInstaller.
* `make_shortcuts.py`: Create `Shockwave.lnk`.

---

## 3. Configuration sections and key settings

| Section | Setting | Default | Description |
|---------|---------|---------|-------------|
| `[Recording]` | `hotkey` | `ctrl+space` | Global hotkey |
| `[Recording]` | `max_record_seconds` | `180` | Recording auto-stop |
| `[Recording]` | `warn_record_seconds` | `150` | Red radar warning |
| `[Recognition]` | `whisper_model` | `large-v3-turbo` | Whisper model name |
| `[Recognition]` | `model_idle_timeout` | `300` | Idle seconds before unloading; 0 disables unloading |
| `[Wake]` | `wake` | `true` | Enable wake-word detection |
| `[Wake]` | `wake_word` | See `src/config.py` | Configured trigger phrase |
| `[Text]` | `llm_norm` | `false` | Normalize punctuation |
| `[Text]` | `ai_task` | `false` | Generate an AI prompt |
| `[Text]` | `to_en` | `false` | Translate into English |
| `[Text]` | `idea` | `false` | Structure ideas |
| `[Text]` | `clip_prepend` | `false` | Prepend above clipboard content |
| `[Text]` | `auto_paste` | `false` | Paste into the active input field |
| `[LLM]` | `endpoint` | `""` | OpenAI-compatible API URL |
| `[LLM]` | `model` | `gemini-3.5-flash` | LLM model |
| `[LLM]` | `api_key` | `""` | API key |
| `[LLM]` | `timeout` | `25` | Request timeout in seconds |
| `[Widget]` | `position` | `bottom-right` | Widget position |
| `[Widget]` | `opacity` | `0.85` | Widget opacity |
| `[Sound]` | `startup_sound` | `true` | Megatron startup greeting |
| `[Sound]` | `alert_sound` | `true` | Text-ready notification |

Legacy `language` and `APP_LANGUAGE` settings are ignored.

Prompt priority: `[Prompts]` in `config.ini`, then `config/prompts/*.md`, then built-in defaults.
Prompt files: `normalization.md`, `translate_en.md`, `ai_task.md`, `ai_task_en.md`, `idea.md`.

---

## 4. Launch and build commands

```bat
start.bat
rem Or launch directly:
python src/launcher.py
rem Build the distribution:
build.bat
```

---

## 5. Project invariants

1. **Configuration separation:** `config/config.ini` is required and gitignored. Copy `config/config.example.ini`, which has blank `endpoint`, `model`, and `api_key`. Do not read `config/.env`. Store prompt text in `config/prompts/*.md`.
2. **Clipboard behavior:** `typer.py` copies text and optionally sends `Ctrl+V` when `paste` is enabled. With `paste` disabled, no keys are sent. Never change the active window.
3. **LLM security:** Allow HTTP only on loopback; require HTTPS for external servers. Reject redirects (3xx). Never embed credentials in URLs.
4. **Exclusive modes:** `Idea` and `AI task` cannot be active together. Enabling one disables the other.
5. **Watchdog and concurrency:** `_audio_lock` (RLock) protects device operations; `lock` (Lock) protects state flags. Callback threads must not hold both simultaneously. `_recording_id` invalidates stale workers.
6. **Agent responses:** Reply concisely.
