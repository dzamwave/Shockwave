import ctypes
import ctypes.wintypes
import threading

# Win32 Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# Properly declare Win32 function signatures for 64-bit safety
_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.UINT, ctypes.wintypes.UINT]
_user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG), ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.UINT]
_user32.GetMessageW.restype = ctypes.wintypes.BOOL
_user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
_user32.PostThreadMessageW.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
_user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL

VK_MAP = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "enter": 0x0D, "return": 0x0D, "backspace": 0x08,
    "pause": 0x13, "capslock": 0x14, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22
}

# Keys that Windows reserves and RegisterHotKey cannot register
RESERVED_KEYS = {"f12"}


def parse_hotkey_string(hotkey_str):
    """Parses a hotkey string like 'ctrl+space' into (modifiers, vk_code)."""
    parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
    modifiers = MOD_NOREPEAT
    vk = 0

    for part in parts:
        if part in ["ctrl", "control"]:
            modifiers |= MOD_CONTROL
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part in ["win", "windows", "super"]:
            modifiers |= MOD_WIN
        elif part in VK_MAP:
            vk = VK_MAP[part]
        elif len(part) == 1:
            vk = ord(part.upper())

    return modifiers, vk


def _is_reserved(hotkey_str):
    """Returns True if the hotkey is known to be reserved by Windows."""
    key = hotkey_str.strip().lower()
    return key in RESERVED_KEYS


class SystemHotkeyManager:
    """
    Manages a global hotkey using Win32 RegisterHotKey.
    Falls back to the 'keyboard' library (suppress=False) if
    RegisterHotKey fails (e.g. for reserved keys like F12).
    """

    def __init__(self, hotkey_str, callback):
        self.hotkey_str = hotkey_str
        self.callback = callback
        self._thread_id = None
        self._running = False
        self._hotkey_id = 1001
        self._thread = None
        self._method = None        # "register" or "keyboard"
        self._method_lock = threading.Lock()
        self._register_ready = threading.Event()
        self._keyboard_hook = None

        self._start()

    def _start(self):
        if _is_reserved(self.hotkey_str):
            print(f"[Hotkey] '{self.hotkey_str.upper()}' is reserved by Windows Kernel Debugger.")
            self._start_keyboard_fallback()
        else:
            self._start_register_hotkey()

    # ── Primary: Win32 RegisterHotKey ──────────────────────────────

    def _start_register_hotkey(self):
        self._running = True
        self._register_ready.clear()
        self._thread = threading.Thread(target=self._register_msg_loop, daemon=True)
        self._thread.start()
        if not self._register_ready.wait(2.0):
            print("[Hotkey] RegisterHotKey did not answer. Will use fallback.")
        with self._method_lock:
            if self._method != "register":
                self._start_keyboard_fallback()

    def _claim_register(self):
        """Keep a single hook. A late Win32 success must not join the keyboard fallback."""
        with self._method_lock:
            if self._method == "keyboard":
                _user32.UnregisterHotKey(None, self._hotkey_id)
                return False
            self._method = "register"
            return True

    def _register_msg_loop(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        modifiers, vk = parse_hotkey_string(self.hotkey_str)
        if vk == 0:
            print("[Hotkey] Warning: Could not parse key from hotkey string.")
            self._register_ready.set()
            return

        success = _user32.RegisterHotKey(None, self._hotkey_id, modifiers, vk)
        if not success:
            # Retry without MOD_NOREPEAT for older Windows
            modifiers_no_repeat = modifiers & ~MOD_NOREPEAT
            success = _user32.RegisterHotKey(None, self._hotkey_id, modifiers_no_repeat, vk)

        if not success:
            err = ctypes.GetLastError()
            print(f"[Hotkey] RegisterHotKey failed for '{self.hotkey_str.upper()}' (error {err}). Will use fallback.")
            self._register_ready.set()
            return

        if not self._claim_register():
            self._register_ready.set()
            return
        print(f"[Hotkey] Registered '{self.hotkey_str.upper()}' via Win32 RegisterHotKey (rock-solid).")
        self._register_ready.set()

        msg = ctypes.wintypes.MSG()
        while self._running:
            res = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res <= 0:
                break

            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                if self.callback:
                    try:
                        self.callback()
                    except Exception as e:
                        print(f"[Hotkey] Callback error: {e}")

            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        _user32.UnregisterHotKey(None, self._hotkey_id)

    # ── Fallback: keyboard library (suppress=False) ───────────────

    def _start_keyboard_fallback(self):
        try:
            import keyboard
            self._keyboard_hook = keyboard.add_hotkey(
                self.hotkey_str, self.callback, suppress=False
            )
            self._method = "keyboard"
            print(f"[Hotkey] Registered '{self.hotkey_str.upper()}' via keyboard hook (suppress=False).")
        except Exception as e:
            print(f"[Hotkey] CRITICAL: Both RegisterHotKey and keyboard fallback failed: {e}")

    # ── Cleanup ───────────────────────────────────────────────────

    def stop(self):
        self._running = False

        if self._method == "register" and self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

        if self._method == "keyboard" and self._keyboard_hook is not None:
            try:
                import keyboard
                keyboard.remove_hotkey(self._keyboard_hook)
            except Exception:
                pass
