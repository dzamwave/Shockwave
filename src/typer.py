import pyperclip
import keyboard

class Typer:
    def type_text(self, text, prepend_clipboard=False, auto_paste=False):
        if not text:
            return
            
        if prepend_clipboard:
            try:
                old_clip = pyperclip.paste()
                if old_clip and old_clip.strip():
                    text = f"{text}\n\n{old_clip}"
            except Exception as e:
                print(f"[Typer] Clipboard read error: {e}")

        # Copy first so an optional paste includes the combined clipboard text.
        pyperclip.copy(text)
        if auto_paste:
            keyboard.send("ctrl+v")
