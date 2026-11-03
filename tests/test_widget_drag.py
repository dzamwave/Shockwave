"""Real Tk event routing with stub configuration; no models, mic or API calls."""
import importlib.util
import pathlib
import queue
import sys
import time
import types
import unittest
from unittest.mock import patch


path = pathlib.Path(__file__).resolve().parents[1] / "src" / "ui.py"
spec = importlib.util.spec_from_file_location("drag_ui", path)
UI = importlib.util.module_from_spec(spec)
stub_config = types.ModuleType("config")
stub_config.get_resource_path = lambda relative_path: relative_path
with patch.dict(sys.modules, {"config": stub_config}):
    spec.loader.exec_module(UI)


class WidgetDragTests(unittest.TestCase):
    def setUp(self):
        self.clicks = []
        def delayed_start():
            self.clicks.append(True)
            time.sleep(0.03)  # Pending press/motion/release around a delayed handler.
        with patch.object(UI.WinVoiceUI, "setup_taskbar_style"), patch.object(UI.WinVoiceUI, "enforce_topmost"):
            self.widget = UI.WinVoiceUI(queue.Queue(), on_trigger=delayed_start)
        self.root = self.widget.root
        self.addCleanup(self.close_window)
        # Map outside the desktop; don't move the real cursor or change other apps.
        self.root.geometry("315x80+10000+10000")
        self.root.deiconify()
        self.root.update()
        self.origin = (self.root.winfo_x(), self.root.winfo_y())

    def close_window(self):
        for callback in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(callback)
        self.root.destroy()

    def event(self, widget, sequence, dx=0, dy=0):
        widget.event_generate(sequence, x=5, y=5,
                              rootx=self.origin[0] + 15 + dx,
                              rooty=self.origin[1] + 15 + dy)
        self.root.update_idletasks()

    def position(self):
        return (self.root.winfo_x(), self.root.winfo_y())

    def test_record_click_and_pending_motion_never_move_widget(self):
        self.event(self.widget.eye_canvas, "<ButtonPress-1>")
        self.event(self.widget.eye_canvas, "<B1-Motion>", 150, 70)
        self.event(self.widget.eye_canvas, "<ButtonRelease-1>", 150, 70)
        self.assertEqual(self.clicks, [True])
        self.assertEqual(self.position(), self.origin)

    def test_release_then_motion_cannot_reuse_previous_drag_offsets(self):
        self.event(self.widget.label, "<ButtonPress-1>")
        self.event(self.widget.label, "<ButtonRelease-1>")
        self.event(self.widget.label, "<B1-Motion>", 150, 70)
        self.assertEqual(self.position(), self.origin)

    def test_background_drag_moves_by_cursor_delta_and_preserves_offset(self):
        self.event(self.widget.label, "<ButtonPress-1>")
        self.event(self.widget.label, "<B1-Motion>", 120, 40)
        self.assertEqual(self.position(), (self.origin[0] + 120, self.origin[1] + 40))
        self.event(self.widget.label, "<ButtonRelease-1>", 120, 40)
        self.assertEqual(self.clicks, [])

    def test_motion_without_background_press_does_not_jump(self):
        self.event(self.widget.label, "<B1-Motion>", 150, 70)
        self.assertEqual(self.position(), self.origin)

    def test_idea_checkbox_exists_and_mutually_exclusive_with_ai_task(self):
        self.assertTrue(hasattr(self.widget, "chk_idea"))
        self.widget.chk_ai_task.invoke()
        self.assertTrue(self.widget.ai_task_enabled)
        self.assertFalse(self.widget.idea_enabled)
        self.widget.chk_idea.invoke()
        self.assertTrue(self.widget.idea_enabled)
        self.assertFalse(self.widget.ai_task_enabled)

    def test_paste_checkbox_toggles(self):
        self.assertFalse(self.widget.paste_enabled)
        self.widget.chk_paste.invoke()
        self.assertTrue(self.widget.paste_enabled)
        self.widget.chk_paste.invoke()
        self.assertFalse(self.widget.paste_enabled)

    def test_checkbox_press_does_not_start_window_drag(self):
        self.event(self.widget.chk_ai_task, "<ButtonPress-1>")
        self.event(self.widget.chk_ai_task, "<B1-Motion>", 150, 70)
        self.event(self.widget.chk_ai_task, "<ButtonRelease-1>", 150, 70)
        self.assertEqual(self.position(), self.origin)


if __name__ == "__main__":
    unittest.main()
