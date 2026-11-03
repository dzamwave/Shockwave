"""Clipboard and automatic paste behavior without sending real keystrokes."""
import importlib.util
import pathlib
import unittest
from unittest.mock import Mock, call, patch

spec = importlib.util.spec_from_file_location("paste_typer", pathlib.Path(__file__).resolve().parents[1] / "src" / "typer.py")
typer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(typer)


class AutoPasteTests(unittest.TestCase):
    def test_paste_happens_after_copy_including_clip_prepend(self):
        actions = Mock()
        with patch.object(typer.pyperclip, "paste", return_value="existing"), \
             patch.object(typer.pyperclip, "copy", side_effect=actions.copy), \
             patch.object(typer.keyboard, "send", side_effect=actions.send):
            typer.Typer().type_text("new", prepend_clipboard=True, auto_paste=True)
        self.assertEqual(actions.mock_calls, [call.copy("new\n\nexisting"), call.send("ctrl+v")])

    def test_paste_disabled_or_empty_text_sends_no_keys(self):
        with patch.object(typer.pyperclip, "copy"), patch.object(typer.keyboard, "send") as send:
            typer.Typer().type_text("new")
            typer.Typer().type_text("", auto_paste=True)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
