import os
import sys

# Enable UTF-8 encoding for console output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ensure modules from src import cleanly
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import config

def hex_to_rgb(hex_str, default_rgb):
    try:
        h = str(hex_str).strip().lstrip("#")
        if len(h) == 6:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return default_rgb

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    ansi_path = config.get_resource_path(os.path.join("icons", "shockwave_transparent.ansi"))
    if os.path.exists(ansi_path):
        try:
            with open(ansi_path, "r", encoding="utf-8") as f:
                lines = f.read().split("\n")
                try:
                    banner_pad_n = int(getattr(config, "CLI_BANNER_PAD", "3"))
                except Exception:
                    banner_pad_n = 3
                pad = " " * max(0, banner_pad_n)
                for line in lines:
                    if line.strip():
                        print(pad + line)
        except Exception:
            pass

    try:
        quote_pad_n = int(getattr(config, "CLI_QUOTE_PAD", "6"))
    except Exception:
        quote_pad_n = 6
    q_pad = " " * max(0, quote_pad_n)

    quote_hex = getattr(config, "CLI_QUOTE_COLOR", "#807785")
    qr, qg, qb = hex_to_rgb(quote_hex, (128, 119, 133))
    tagline = "WHAT IS YOUR COMMAND, MEGATRON?"
    custom_quote = f"\033[1;3;38;2;{qr};{qg};{qb}m{tagline}\033[0m"
    print(f"{q_pad}{custom_quote}\n")

def start_app():
    clear_screen()
    print_banner()

    engine = "whisper"
    stt_display = f"Whisper ({config.WHISPER_MODEL})"

    print(f"Starting Shockwave ({stt_display})...")
    recognition_language = getattr(config, "WHISPER_LANGUAGE", "en").strip().lower() or "en"
    print(f"Recognition language: {recognition_language}")
    print(f"Shockwave version: {config.APP_VERSION}")
    print(f"LLM model: {config.LLM_MODEL}")
    print("Settings are read from config/config.ini.")

    import model_manager
    model_manager.ensure_configured_model()

    print("Control panel minimizing to system tray (next to clock).")

    import main
    app = main.WinVoiceApp()
    app.run()
    sys.exit(0)

if __name__ == "__main__":
    from single_instance import check_single_instance
    if not check_single_instance():
        print("\n[Shockwave] Shockwave is already running!\n")
        import time
        time.sleep(2.0)
        sys.exit(0)

    start_app()
