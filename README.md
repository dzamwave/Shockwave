<p align="center">
  <img src="docs/shockwave.gif" alt="Shockwave">
</p>

# Shockwave

**Shockwave** is an open-source, local-first background voice dictation tool for Windows. It allows you to dictate text completely hands-free via a customizable wake word (powered by Vosk), via a global hotkey, or by clicking the interactive radar button. It can normalize punctuation and tech terminology using an LLM, then copies the result to the clipboard. With `paste` enabled, it also sends `Ctrl+V` into the window that currently has the input focus.

<p align="center">
  <img src="docs/floating_widget.png?v=1.1.1" alt="Floating Widget" width="521">
</p>

### Speech Recognition Models:
- **Wake Word Engine (`Vosk`)**: Ultra-lightweight offline listening for the wake phrase, with near-zero CPU footprint. Choose `vosk_model = ru` or `vosk_model = en` under `[Wake]`. Russian and English weights stay in separate folders under `models`.
- **Whisper (`large-v3-turbo`)**: Multilingual speech recognition through `faster-whisper`. Put a Whisper name in `multi_recognition_model` under `[Recognition]`, and set the spoken language with `whisper_language`, or use `auto` to detect it.
- **Parakeet (`nemo-parakeet-tdt-0.6b-v3`)**: Fast multilingual ONNX model for the `multi` radio button. Put its name in `multi_recognition_model`. It ignores `whisper_language`.
- **GigaAM (`gigaam-v3-e2e-rnnt`)**: ONNX model for the `ru` radio button, through `onnx-asr`. Set it with `ru_recognition_model = gigaam-v3-e2e-rnnt`. It recognizes Russian only and uses less memory than Whisper. `int8` is the smaller option; `float32` is full precision.

### Text Normalization Engine (LLM):
- **OpenAI-compatible endpoints**: Punctuation, idea structuring, social posts, AI-task prompts, and English translation. `[LLM]` serves `to EN`, `mk Post`, `Idea`, and `AI task`. `[LLM Normalize]` serves punctuation only when `LLM norm` is the only selected text mode. A blank normalization address uses `[LLM]`. A blank model uses `gemini-3.5-flash`.

## Features

* **Hands-Free Wake Word (Vosk):** Fully voice-driven recording. Say the `wake_word` from `config.ini` to start recording, and say it again to stop. The keyword is automatically trimmed from the end of the transcript. Set `vosk_model` in `[Wake]` to `ru` or `en`, and use a phrase in that language.
* **Rock-Solid System Hotkey:** Native Win32 `RegisterHotKey` (default `Ctrl + Space`). Never drops out after system sleep, lock screen, or long background sessions. Configurable via `hotkey` in `[Recording]`.
* **Dynamic Dot-Matrix Radar & Flashing Alert:** Sleek 32×32 px square button with a 5×5 LED micro-pixel matrix featuring a real-time rotating radar sweep and glowing trail during active recording. After `warn_record_seconds` (default 150 s, about `00:30` left on a 3-minute timer) the radar switches to a flashing red beacon. Click-to-record supported!
* **Live Countdown Timer & Auto-Stop:** Displays remaining recording time (`03:00` → `00:00`) directly on the floating widget next to the `cancel` button. Automatically finalizes recording and submits it to the selected speech engine at the `max_record_seconds` limit (default 180 s).
* **Widget Quick Toggles:** Nine switches in three rows of three — Row 1: `LLM norm`, `to EN`, `clip+` / Row 2: `wake`, `alert`, `paste` / Row 3: `AI task`, `Idea`, `mk Post`. `AI task`, `Idea`, and `mk Post` are mutually exclusive and turn each other off. With `Idea` and `to EN` together, one request writes the idea draft in English. With `mk Post` and `to EN` together, one request writes the post in English. `LLM norm` does not run when `Idea` is on. Row 4 has two buttons: `RU` uses `ru_recognition_model`, `ML` uses `multi_recognition_model`. Pressing one releases the other. The choice is saved as `recognition_mode`.
* **Idea Structuring (`Idea`):** Transforms a free-flowing monologue into a draft: extracts the key ideas, removes filler and repetition, and preserves the author's voice. For each idea it returns a core idea, a refined thought, and open questions worth exploring.
* **Social Post (`mk Post`):** Turns dictated speech into one ready-to-publish social media post in the spoken language. With `to EN`, the same request writes that post in English. It turns off `AI task` and `Idea`.
* **AI Task Prompt Generator (`AI task`):** Transforms conversational stream-of-consciousness speech into structured, crystal-clear instructions/prompts for LLMs without chit-chat or filler words.
* **Instant English Translation (`to EN`):** Translates dictated speech directly into natural English with technical term preservation and punctuation restoration.
* **Combined Super-Mode (`AI task` + `to EN`):** When both toggles are enabled, generates a structured AI prompt from the dictated text in one LLM request.
* **Smart Clipboard Prepend (`clip+`):** When enabled, Shockwave prepends your dictated prompt above existing clipboard content (e.g. copied code, errors, or data) with clean double-newline spacing (`Ctrl+V` pastes the full combined prompt!).
* **Automatic Paste (`paste`):** Enable the widget checkbox to send `Ctrl+V` after copying, so the finished text lands at the input cursor. Disabled by default; works with `clip+`.
* **User Glossary (`glossary.txt`):** Instant word substitutions applied immediately after speech recognition, before any LLM step. Fully customizable for tech stacks, trading terms, or brand names, with hot-reloading on the fly — no restart needed.
* **Lazy Model Loading & Idle Unload:** The STT model is loaded into RAM on demand (on the first recording), not at startup. A background watchdog thread unloads it after `model_idle_timeout` seconds of inactivity (default 300 s; set to 0 to disable). Model preloading starts asynchronously the moment recording begins to minimize post-recording latency.
* **Speech-to-Text:** `ru` uses `ru_recognition_model`, GigaAM `gigaam-v3-e2e-rnnt` by default, on CPU through ONNX Runtime. `multi` uses `multi_recognition_model`: Parakeet `nemo-parakeet-tdt-0.6b-v3` by default, or a Whisper name such as `large-v3-turbo`. Whisper is multilingual through `faster-whisper` and reads `whisper_language`. GigaAM and Parakeet ignore that setting. A long ONNX recording is split at pauses before recognition. Only one model stays in memory; switching the radio button unloads the previous one.
* **Fully Portable & Compact Storage:** Speech weights stay local in `models/`. They are not in the repository. On the first launch Shockwave asks `Download this model? (y/n)` for each missing model and downloads it: about 1.76 GB for Whisper `large-v3-turbo`, about 220 MB for GigaAM `int8`, and the Parakeet `int8` weights plus the small Silero pause detector for ONNX models. Answering anything other than `y` exits without changing `config.ini`.
* **Draggable Floating Widget:** Minimalist 340×120 on-screen overlay. Drag it by the panel itself. The widget stays off the taskbar; Shockwave remains available from the tray icon.
* **Tray Icon:** The console hides to the tray at startup. The tray menu can show it again.
* **Config file:** Engine, wake word, hotkey, widget, and LLM connection are edited in `config.ini`. The program does not ask for them at startup. Prompts are fully customizable via `config/prompts/*.md` or the `[Prompts]` section.
* **Safe Configuration Separation:** `config/config.ini` is required at startup and is gitignored. Copy it from `config/config.example.ini`. Environment files are not used.
* **Secure LLM Connection:** External LLM servers require HTTPS; HTTP is allowed only on loopback. Redirects (3xx) are blocked. Credentials are never embedded in the URL.
* **Customizable System Prompts:** The eight LLM prompts (`normalization`, `translate_en`, `ai_task`, `ai_task_en`, `idea`, `idea_en`, `mk_post`, `mk_post_en`) are loaded from `config/prompts/*.md` and can be freely edited. A missing prompt file is created automatically with its built-in default.
* **Audio Notifications & Startup Sound:** A distinct chime plays when the transcription is ready. The Megatron startup voice chime can be toggled independently via `startup_sound` in `config.ini`.
* **Safe Terminal Logging:** The console maintains a real-time transcript history to ensure no dictated text is lost.

## Documentation & Installation
Detailed guides are available below:

**[Setup Guide](docs/shockwave_setup_guide_eng.md)**

---

<p align="center">
  <img src="docs/control_panel.png?v=1.2.0" alt="Control Panel" width="1253">
</p>
