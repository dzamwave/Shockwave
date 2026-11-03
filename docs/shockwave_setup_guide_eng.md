# Shockwave — Setup & User Guide

Version 1.1.2. Windows only.

Shockwave is a background dictation tool. Speech is recognized locally. The result is copied to the clipboard, and can optionally be pasted into the window that currently has the input focus.

There are three ways to record:

- Press the global hotkey, `Ctrl + Space` by default.
- Click the radar on the floating widget.
- Say the wake word when the `wake` switch is on. Say it again to stop.

---

## Quick start (no Python required)

1. Download the latest `Shockwave-v1.1.2-Windows-x64.zip` from [GitHub Releases](https://github.com/dzamwave/shockwave/releases).
2. Extract it to any folder, for example `C:\Shockwave`.
3. Edit `config\config.ini`. The packaged release already contains a working file; the template is `config\config.example.ini`.
4. Run `Shockwave.exe` from the `Shockwave` folder. The executable is not placed directly in `dist`.
5. If the selected speech model is missing, Shockwave asks `Download this model? (y/n)`. Answering `y` downloads it and does not change `config.ini`. Answering anything else exits.
6. The console then hides to the system tray. A purple widget appears.
7. Press `Ctrl + Space` to start, speak, and press it again to finish. Paste the result with `Ctrl + V`, unless `paste` is enabled.

A second launch prints `Shockwave is already running!` and exits. A Windows mutex prevents two copies from running.

---

## Build and run from source

Requirements:

- Windows 10 or 11
- Python 3.12
- Git, optional

```bat
git clone https://github.com/dzamwave/shockwave.git
cd shockwave

python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
```

Copy `config\config.example.ini` to `config\config.ini` before the first source launch. The working file is excluded from Git.

- Run from source with `start.bat`, or with `python src\launcher.py` after activating `venv`.
- Build the portable application with `build.bat`. It closes a running `Shockwave.exe`, then uses PyInstaller in onedir mode. The result is `dist\Shockwave\Shockwave.exe`, plus a `Shockwave.lnk` shortcut in the project root.

The shortcut starts the console. Shockwave then hides that console to the tray itself.

---

## LLM setup

Shockwave sends text to one OpenAI-compatible chat-completions endpoint. Put the connection in `[LLM]`:

```ini
[LLM]
endpoint = https://example.com/v1/chat/completions
model = gemini-2.5-flash
timeout = 25
api_key =
```

A blank `model` uses `gemini-2.5-flash`. A blank timeout uses 25 seconds. A blank `endpoint` disables LLM processing. Values are not read from `config\.env` or environment variables.

| Provider | Endpoint | Example model | Key |
| :--- | :--- | :--- | :--- |
| Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` | `gemini-2.5-flash` | [aistudio.google.com](https://aistudio.google.com/) |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` | [platform.openai.com](https://platform.openai.com/) |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | `google/gemini-2.5-flash` | [openrouter.ai](https://openrouter.ai/) |
| Ollama on this computer | `http://127.0.0.1:11434/v1/chat/completions` | `qwen2.5:7b` | Not required |

Connection rules:

- External servers must use HTTPS.
- HTTP is accepted only for `localhost`, `127.0.0.1`, and `::1`. An HTTP address of another computer is rejected.
- Credentials must not be embedded in the URL. The key is sent as a Bearer token.
- Redirects are rejected. Use the final URL.
- A local HTTP request is sent directly and does not use a proxy configured in the environment.

If the endpoint is empty, the URL is rejected, the request fails, or the response is empty, truncated, or not confirmed with `finish_reason: stop`, Shockwave copies the text from before LLM processing. The widget then shows `LLM failed: original saved` instead of `ready`. A glossary failure shows `glossary failed: original saved` and skips the LLM. `Saved` means copied to the clipboard, not written to a file.

---

## `config.ini`

`config\config.ini` is required. If it is missing, Shockwave stops and tells you to copy `config\config.example.ini`. Settings are read from the named section, then `[DEFAULT]`, then the built-in default. Environment variables and `config\.env` are not used. Startup does not rewrite the file. Widget checkboxes change behavior only until Shockwave exits; edit `config.ini` to keep a choice.

The built-in defaults differ from the values shipped in `config.example.ini`.

| Section | Setting | Built-in default | In `config.example.ini` | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `[Recording]` | `hotkey` | `ctrl+space` | `ctrl+space` | Global hotkey |
| `[Recording]` | `max_record_seconds` | `180` | `180` | Automatic stop, in seconds |
| `[Recording]` | `warn_record_seconds` | `150` | `150` | Red radar warning |
| `[Recognition]` | `whisper_model` | `large-v3-turbo` | `large-v3-turbo` | Whisper model |
| `[Recognition]` | `model_idle_timeout` | `300` | `300` | Idle seconds before unloading; `0` disables it |
| `[Wake]` | `wake` | `true` | `false` | Background wake-word listening |
| `[Wake]` | `wake_word` | `shockwave` | `shockwave` | Trigger phrase |
| `[Text]` | `llm_norm` | `false` | `true` | Punctuation normalization |
| `[Text]` | `ai_task` | `false` | `false` | AI-prompt mode |
| `[Text]` | `to_en` | `false` | `false` | English translation |
| `[Text]` | `idea` | `false` | `false` | Idea structuring |
| `[Text]` | `clip_prepend` | `false` | `false` | Put dictated text above clipboard content |
| `[Text]` | `auto_paste` | `false` | `false` | Paste into the focused input |
| `[LLM]` | `timeout` | `25` | blank, so `25` | Request timeout, in seconds |
| `[Widget]` | `position` | `bottom-right` | `bottom-right` | `bottom-right`, `bottom-left`, or `top-center` |
| `[Widget]` | `opacity` | `0.85` | `0.85` | Window opacity from 0.0 to 1.0 |
| `[Widget]` | `ui_bg_color` | `#3b274d` | `#3b274d` | Widget background |
| `[Widget]` | `ui_grip_color` | `#2c1c3b` | `#2c1c3b` | Darker widget color |
| `[Sound]` | `startup_sound` | `true` | `false` | Megatron greeting |
| `[Sound]` | `alert_sound` | `true` | `true` | Ready chime |

`[Console]` controls only the startup banner: `cli_title_color`, `cli_quote_color`, `cli_banner_pad`, `cli_quote_pad`, and `cli_title_pad`. It does not select a language. Old `language` and `APP_LANGUAGE` settings are ignored. Interface and console text are always English; this does not change the recognition language.

Each `[Section]` heading must be on its own line. Older names in `[Recognition]`, `[Interface]`, `[Toggles]`, and `[Theme]` are still read when the current setting is absent.

### Hotkey

Use a modifier plus a key, such as `ctrl+space`, `alt+space`, `ctrl+alt+f8`, or a function key such as `f8`, `f9`, `f10`, or `pause`. Win32 `RegisterHotKey` is used first, so the hotkey survives sleep and screen locking. If registration fails, Shockwave falls back to a keyboard hook that does not suppress the key.

`f12` is reserved by Windows and cannot use the primary method. `f11` and `f5` can conflict with the focused application, so avoid them.

### Speech models

- **Whisper** (`large-v3-turbo`) is the only speech engine. It uses faster-whisper on CPU in `int8` and always recognizes English.
- Known Whisper downloads are `large-v3-turbo`, `large-v3`, `medium`, `small`, `base`, and `tiny`.
- The model loads on the first recording, not at startup. Loading begins in the background when recording starts. After `model_idle_timeout` idle seconds it is unloaded; `0` keeps it loaded.
- Weights are stored under `models\whisper` and `models\vosk-model-small-en-us`.

### Wake word

With `wake = true`, Vosk listens in the background using `vosk-model-small-en-us-0.15`. If that model is missing, Shockwave downloads it automatically when wake listening starts. It does not ask first.

The phrase comes from `[Wake] wake_word`. The built-in phrase and the example file both use `shockwave`. Matching is case-insensitive. A repeated detection is ignored for two seconds.

Stopping by wake word keeps the whole recording. Only a recognized wake word at the very end of the transcript is removed. If it is not at the end, the transcript stays unchanged. While the main recording is active, the separate wake microphone is paused and resumes afterward.

### Glossary

`glossary.txt` is applied immediately after recognition and before any LLM step. Each rule has the form `pattern = replacement`. Matching is case-insensitive and covers the whole word or phrase. Longer phrases are replaced before shorter ones. Blank lines and lines starting with `#` are ignored.

If the file does not exist, Shockwave creates a template containing development and trading examples. Edits are reloaded automatically when the file's modification time changes. No restart is needed.

### Prompts

Five prompts are available: `normalization.md`, `translate_en.md`, `ai_task.md`, `ai_task_en.md`, and `idea.md`.

The priority is `[Prompts]` in `config.ini`, then the Markdown file in `config\prompts`, then the built-in text. A missing Markdown file is created with that built-in text on launch. Put a long prompt in its Markdown file rather than on one `config.ini` line.

---

## Text processing

Processing order:

1. Local speech recognition.
2. Removal of a trailing wake word, when the recording was stopped by it.
3. `glossary.txt`.
4. The selected LLM steps.
5. Copy to the clipboard. With `paste`, Shockwave then sends `Ctrl+V`.

LLM steps:

- No processing mode selected: the transcript is copied unchanged.
- `LLM norm`: punctuation and technical terminology.
- `AI task`: a structured prompt in the spoken language. Shockwave does not answer the request.
- `to EN`: an English translation.
- `AI task` + `to EN`: one request produces `AI task (EN)`.
- `Idea`: a draft with a hook, a cleaned-up first-person summary, and possible directions to develop. The author's language and voice are preserved.
- `LLM norm` + `Idea`: punctuation first, then idea structuring.
- `Idea` + `to EN`: structuring first, then translation.
- `LLM norm` + `Idea` + `to EN`: punctuation, structuring, then translation.

`Idea` and `AI task` cannot be active together. Enabling one turns the other off. If both are set at startup, `AI task` is turned off.

`clip+` places the finished text above existing clipboard text, separated by one blank line. It can be combined with `paste`.

---

## Widget and tray

The widget is a borderless 370×80 window. It stays above other windows and is hidden from the taskbar. Drag its background to move it; the radar, checkboxes, and close button do not start a drag.

The left control is a 32×32 radar with a 5×5 LED matrix. Click it to start or stop. During recording it shows a rotating gold sweep. After `warn_record_seconds`, the sweep turns into a flashing red warning. At `max_record_seconds`, recording stops and is transcribed.

The status line shows `what is your command?` when idle, then `record`, `processing`, and `normalization` when an LLM step is running. Success shows `ready` for five seconds. Cancellation shows `cancelling` and discards the audio without transcription. A failure can show `error: microphone`, `error: processing`, or the `original saved` message.

The countdown beside `cancel` starts at `max_record_seconds`, normally `03:00`, and reaches `00:00`.

Row 1: `LLM norm`, `AI task`, `to EN`, `Idea`.

Row 2: `wake`, `alert`, `clip+`, `paste`.

- `wake` starts or stops background listening. Turning it off unloads Vosk.
- `alert` plays the ready chime. It also plays when a wake word starts recording.
- `startup_sound` is separate and plays the Megatron greeting when the widget appears.
- `paste` sends `Ctrl+V` after copying. It is off by default.
- `×` exits Shockwave.

The tray icon is beside the clock. A left click or double-click shows the widget. The right-click menu contains:

- `Show widget on top`
- `Show control panel`
- `Hide control panel to tray`
- `Exit Shockwave`

The finished transcript is also printed in the control panel, so it remains visible after the widget returns to its idle text.
