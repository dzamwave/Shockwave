"""Win32 marshalling regressions; fake DLLs, no desktop/settings/device access."""
import ctypes
from ctypes import wintypes
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTANCE = 0x123456789ABC
WINDOW = 0x23456789ABCD
ICON = 0x3456789ABCDE
MENU = 0x456789ABCDEF


class Function:
    def __init__(self, result=1):
        self.restype = ctypes.c_int  # ctypes' dangerous default for pointer results.
        self.argtypes = None
        self.result = result
        self.calls = []

    def __call__(self, *args):
        if self.argtypes is not None:
            if len(args) != len(self.argtypes):
                raise AssertionError("Wrong argument count")
            for type_, value in zip(self.argtypes, args):
                type_.from_param(value)  # Actual ctypes argument compatibility.
        self.calls.append(args)
        result = self.result(*args) if callable(self.result) else self.result
        if self.restype is None:
            return None
        return self.restype(result).value


class Library:
    def __init__(self):
        self.functions = {}

    def __getattr__(self, name):
        return self.functions.setdefault(name, Function())


class TrayWin32Tests(unittest.TestCase):
    def setUp(self):
        self.user = Library()
        self.kernel = Library()
        self.shell = Library()
        self.ole = Library()
        self.enterContext(patch.object(ctypes, "windll", types.SimpleNamespace(
            user32=self.user, kernel32=self.kernel, shell32=self.shell)))
        self.enterContext(patch.object(ctypes, "oledll", types.SimpleNamespace(ole32=self.ole)))
        spec = importlib.util.spec_from_file_location("isolated_tray", ROOT / "src" / "tray_manager.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tray = self.module.SystemTrayManager()
        self.kernel.GetModuleHandleW.result = INSTANCE
        self.kernel.GetConsoleWindow.result = WINDOW
        self.user.GetAncestor.result = WINDOW
        self.user.CreateWindowExW.result = WINDOW
        self.user.LoadIconW.result = ICON
        self.user.LoadImageW.result = ICON
        self.user.CreatePopupMenu.result = MENU
        self.user.GetMessageW.result = 0
        self.ole.CoCreateInstance.result = 1  # No real COM interface is created.

    def test_tray_window_and_icon_handles_keep_all_64_bits(self):
        self.tray._run_message_loop()
        self.assertEqual(self.tray.hwnd, WINDOW)
        self.assertEqual(self.tray.hicon, ICON)
        wc = self.user.RegisterClassW.calls[0][0]._obj
        self.assertEqual(wc.hInstance, INSTANCE)
        self.assertEqual(self.user.CreateWindowExW.calls[0][-2], INSTANCE)
        self.assertEqual(self.tray.nid.hWnd, WINDOW)
        self.assertEqual(self.tray.nid.hIcon, ICON)
        self.tray.stop()
        self.assertFalse(self.tray.is_running)
        self.assertEqual([call[0] for call in self.shell.Shell_NotifyIconW.calls], [self.module.NIM_ADD, self.module.NIM_DELETE])
        self.assertEqual(self.user.PostMessageW.calls[-1][0], WINDOW)

    def test_menu_handles_unicode_labels_and_command_dispatch(self):
        shown = []
        self.tray.hwnd = WINDOW
        self.tray.on_show_widget = lambda: shown.append(True)
        self.user.TrackPopupMenu.result = self.module.ID_SHOW_WIDGET
        self.tray._show_context_menu()
        self.assertTrue(shown)
        self.assertEqual(self.user.TrackPopupMenu.calls[0][0], MENU)
        self.assertEqual(self.user.TrackPopupMenu.calls[0][-2], WINDOW)
        self.assertTrue(all(call[0] == MENU for call in self.user.AppendMenuW.calls))
        labels = [call[-1] for call in self.user.AppendMenuW.calls if isinstance(call[-1], str)]
        self.assertIn("Show control panel", labels)
        self.assertTrue(all(label.isascii() for label in labels))
        self.assertEqual(self.user.DestroyMenu.calls[0], (MENU,))

    def test_console_helpers_preserve_window_and_style_bits(self):
        style = 0x123400000000
        self.user.GetWindowLongPtrW.result = style
        self.assertEqual(self.module.get_root_console_hwnd(), WINDOW)
        self.module.hide_console()
        self.module.show_console()
        styles = [call[-1] for call in self.user.SetWindowLongPtrW.calls]
        self.assertEqual(styles, [style | 0x80, style | 0x40000])
        self.assertTrue(all(call[0] == WINDOW for call in self.user.ShowWindow.calls))
        self.assertEqual(self.user.SetForegroundWindow.calls[-1], (WINDOW,))
        self.assertTrue(self.module.is_console_visible())

    def test_loaded_and_default_icon_use_valid_pointer_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "icon.ico"
            path.write_bytes(b"fictional")
            self.tray.icon_path = str(path)
            self.tray._load_icon()
            self.assertEqual(self.tray.hicon, ICON)
            self.assertEqual(self.user.LoadImageW.calls[0][1], str(path))
        self.user.LoadImageW.result = 0
        self.tray.icon_path = None
        self.tray.hicon = None
        self.tray._load_icon()
        self.assertEqual(self.tray.hicon, ICON)
        resource = self.user.LoadIconW.calls[-1][1]
        self.assertEqual(ctypes.cast(resource, ctypes.c_void_p).value, 32512)

    def test_pointer_sized_message_and_handle_signatures(self):
        for name in ("LoadImageW", "LoadIconW", "CreatePopupMenu", "CreateWindowExW", "GetWindowLongPtrW", "DispatchMessageW"):
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(self.user, name).argtypes)
                self.assertEqual(ctypes.sizeof(getattr(self.user, name).restype), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(self.kernel.GetModuleHandleW.argtypes, [wintypes.LPCWSTR])
        self.assertEqual(self.kernel.GetConsoleWindow.argtypes, [])
        self.assertEqual(self.shell.Shell_NotifyIconW.argtypes, [wintypes.DWORD, ctypes.POINTER(self.module.NOTIFYICONDATAW)])
        self.assertEqual(self.user.GetMessageW.restype(-1).value, -1)
        self.assertIsNone(self.user.PostQuitMessage.restype)
        self.assertIsNotNone(self.ole.CoCreateInstance.argtypes)
        self.assertEqual(self.ole.CoInitialize.argtypes, [ctypes.c_void_p])

    def test_widget_window_lookup_and_styles_keep_full_handles(self):
        spec = importlib.util.spec_from_file_location("isolated_widget", ROOT / "src" / "ui.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"config": types.ModuleType("config")}):
            spec.loader.exec_module(module)
        widget = module.WinVoiceUI.__new__(module.WinVoiceUI)
        widget.root = types.SimpleNamespace(winfo_id=lambda: WINDOW, update_idletasks=lambda: None,
                                           lift=lambda: None, attributes=lambda *args: None)
        self.user.GetAncestor.result = 0
        self.user.GetParent.result = WINDOW
        style = 0x12340000
        self.user.GetWindowLongW.result = style
        self.assertEqual(widget.get_window_hwnd(), WINDOW)
        widget.setup_taskbar_style()
        self.assertEqual(self.user.SetWindowLongW.calls[-1][0], WINDOW)
        self.assertEqual(self.user.SetWindowLongW.calls[-1][-1], (style | 0x80) & ~0x40000)
        widget.enforce_topmost(force_foreground=True)
        self.assertEqual(self.user.SetWindowPos.calls[-1][0].value, WINDOW)
        for name in ("GetParent", "GetAncestor", "GetWindowLongW", "SetWindowLongW", "SetWindowPos"):
            self.assertIsNotNone(getattr(self.user, name).argtypes)


if __name__ == "__main__":
    unittest.main()
