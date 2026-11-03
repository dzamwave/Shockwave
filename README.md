<p align="center">
  <img src="docs/shockwave.gif" alt="Shockwave">
</p>

# Shockwave

**Shockwave** is an open-source, local-first background voice dictation tool for Windows. It allows you to dictate text completely hands-free via a customizable wake word (powered by Vosk), via a global hotkey, or by clicking the interactive radar button. It automatically normalizes punctuation and tech terminology using an LLM and types/copies the resulting text directly to your focused window.

### Speech Recognition Models:
- **Wake Word Engine (`Vosk`)**: Ultra-lightweight offline model (`vosk-model-small-en-us-0.15`) for continuous background wake word listening with near-zero CPU footprint.
- **Whisper (`large-v3-turbo`)**: Multilingual speech recognition through `faster-whisper`. It is the only speech-to-text engine. Set the spoken language with `whisper_language` under `[Recognition]`, or use `auto` to detect it.

### Text Normalization Engine (LLM):
- **OpenAI-compatible endpoint**: Punctuation, idea structuring, AI-task prompts, and English translation. The address, model, and API key come only from `[LLM]` in `config/config.ini`. A blank model uses `gemini-2.5-flash`.

## Features

* **Hands-Free Wake Word (Vosk):** Fully voice-driven recording. Say the `wake_word` from `config.ini` to start recording, and say it again to stop. The keyword is automatically trimmed from the end of the transcript. Change it with `wake_word` in the `[Wake]` section.
* **Rock-Solid System Hotkey:** Native Win32 `RegisterHotKey` (default `Ctrl + Space`). Never drops out after system sleep, lock screen, or long background sessions. Configurable via `hotkey` in `[Recording]`.
* **Dynamic Dot-Matrix Radar & Flashing Alert:** Sleek 32×32 px square button with a 5×5 LED micro-pixel matrix featuring a real-time rotating radar sweep and glowing trail during active recording. After `warn_record_seconds` (default 150 s, about `00:30` left on a 3-minute timer) the radar switches to a flashing red beacon. Click-to-record supported!
* **Live Countdown Timer & Auto-Stop:** Displays remaining recording time (`03:00` → `00:00`) directly on the floating widget next to the `cancel` button. Automatically finalizes recording and submits it to Whisper at the `max_record_seconds` limit (default 180 s).
* **Widget Quick Toggles:** Eight switches in two rows — Row 1: `LLM norm`, `AI task`, `to EN`, `Idea` / Row 2: `wake`, `alert`, `clip+`, `paste`. `Idea` and `AI task` are mutually exclusive and turn each other off. With `Idea` and `to EN` together, the text is structured first and then translated. If `LLM norm` is also on, punctuation runs before the idea step.
* **Idea Structuring (`Idea`):** Transforms a free-flowing monologue into a ready-to-publish draft: extracts the key insight, removes filler and repetition, preserves the author's voice and style. Returns a hook, a structured summary, and suggested directions for further development.
* **AI Task Prompt Generator (`AI task`):** Transforms conversational stream-of-consciousness speech into structured, crystal-clear instructions/prompts for LLMs without chit-chat or filler words.
* **Instant English Translation (`to EN`):** Translates dictated speech directly into natural English with technical term preservation and punctuation restoration.
* **Combined Super-Mode (`AI task` + `to EN`):** When both toggles are enabled, generates a structured AI prompt from the dictated text in one LLM request.
* **Smart Clipboard Prepend (`clip+`):** When enabled, Shockwave prepends your dictated prompt above existing clipboard content (e.g. copied code, errors, or data) with clean double-newline spacing (`Ctrl+V` pastes the full combined prompt!).
* **Automatic Paste (`paste`, new in 1.1.2):** Enable the widget checkbox to automatically paste the finished text at the input cursor. Disabled by default; works with `clip+`.
* **User Glossary (`glossary.txt`):** Instant word substitutions applied immediately after speech recognition, before any LLM step. Fully customizable for tech stacks, trading terms, or brand names, with hot-reloading on the fly — no restart needed.
* **Lazy Model Loading & Idle Unload:** The STT model is loaded into RAM on demand (on the first recording), not at startup. A background watchdog thread unloads it after `model_idle_timeout` seconds of inactivity (default 300 s; set to 0 to disable). Model preloading starts asynchronously the moment recording begins to minimize post-recording latency.
* **Speech-to-Text:** Whisper `large-v3-turbo` is the only recognition engine. It is a multilingual model and runs locally through `faster-whisper`. The recognition language comes from `whisper_language`.
* **Fully Portable & Compact Storage:** Flat directory structure saves weights locally in `models/` with zero bloat (only ~1.76 GB for speech models).
* **Draggable Floating Widget:** Minimalist on-screen overlay. Drag it by the panel itself. The widget stays off the taskbar; Shockwave remains available from the tray icon.
* **Tray Icon:** The console hides to the tray at startup. The tray menu can show it again.
* **Config file:** Engine, wake word, hotkey, widget, and LLM connection are edited in `config.ini`. The program does not ask for them at startup. Prompts are fully customizable via `config/prompts/*.md` or the `[Prompts]` section.
* **Safe Configuration Separation:** `config/config.ini` is required at startup and is gitignored. Copy it from `config/config.example.ini`. Environment files are not used.
* **Secure LLM Connection:** External LLM servers require HTTPS; HTTP is allowed only on loopback. Redirects (3xx) are blocked. Credentials are never embedded in the URL.
* **Customizable System Prompts:** All five LLM prompts (`normalization`, `translate_en`, `ai_task`, `ai_task_en`, `idea`) are loaded from `config/prompts/*.md` and can be freely edited. Missing files are auto-created with sensible defaults.
* **Audio Notifications & Startup Sound:** A distinct chime plays when the transcription is ready. The Megatron startup voice chime can be toggled independently via `startup_sound` in `config.ini`.
* **Safe Terminal Logging:** The console maintains a real-time transcript history to ensure no dictated text is lost.

## Documentation & Installation
Detailed guides are available below:

**[Setup Guide](docs/shockwave_setup_guide_eng.md)**

---

<p align="center">
  <img src="docs/control_panel.png?v=1.1.1" alt="Control Panel" width="753">
  <br><br>
  <img src="docs/floating_widget.png?v=1.1.1" alt="Floating Widget" width="521">
</p>
