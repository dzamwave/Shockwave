import tkinter as tk
import queue
import os
import math
import time
import winsound
import ctypes
import ctypes.wintypes as wintypes
import config

# Widget HWNDs must remain pointer-sized even when the tray module is not loaded.
_user32 = ctypes.windll.user32
_user32.GetParent.argtypes = [wintypes.HWND]
_user32.GetParent.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
if ctypes.sizeof(ctypes.c_void_p) == 4:
    _user32.GetWindowLongPtrW = _user32.GetWindowLongW
    _user32.SetWindowLongPtrW = _user32.SetWindowLongW
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
_user32.SetWindowLongW.restype = wintypes.LONG
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL

def play_ready_sound():
    sound_path = config.get_resource_path(os.path.join("alert", "ready.wav"))
    if os.path.exists(sound_path):
        try:
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"Audio playback error: {e}")

def play_startup_sound():
    sound_path = config.get_resource_path(os.path.join("alert", "megatron.wav"))
    if os.path.exists(sound_path):
        try:
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"Startup audio error: {e}")

class WinVoiceUI:
    def __init__(self, message_queue, position="bottom-left", on_trigger=None, on_cancel=None, on_toggle_wake=None):
        self.queue = message_queue
        self.on_trigger = on_trigger
        self.on_cancel = on_cancel
        self.on_toggle_wake = on_toggle_wake
        self.root = tk.Tk()
        
        # Hide window immediately during setup to avoid top-left blank flash
        self.root.withdraw()
        
        # Set window icon (used by Alt-Tab and title bar if visible)
        icon_path = config.get_resource_path(os.path.join("icons", "icon.ico"))
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass
        
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        # Prevent floating overlay from creating a button on the taskbar
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            
            style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass
        
        # Configurable opacity from config.ini
        opacity = getattr(config, "UI_OPACITY", 0.85)
        self.root.attributes("-alpha", opacity)
        self.startup_sound_enabled = getattr(config, "STARTUP_SOUND", True)
        
        # Shockwave deep royal purple palette (configurable in config.ini)
        self.COLOR_BG = getattr(config, "UI_BG_COLOR", "#3b274d")
        self.COLOR_GRIP = getattr(config, "UI_GRIP_COLOR", "#2c1c3b")
        self.COLOR_TEXT = "#ffffff"
        self.COLOR_MUTED = "#c4b0d9"
        
        self.COLOR_INACTIVE_FILL = "#271836"
        self.COLOR_INACTIVE_OUTLINE = "#FFD700"
        self.COLOR_HOVER_FILL = "#53376e"
        self.COLOR_HOVER_OUTLINE = "#FFF59D"
        self.COLOR_ACTIVE_OUTLINE = "#FFD700"
        
        self.root.configure(bg=self.COLOR_BG)
        
        # Dragging handlers (allows grabbing anywhere on the widget bar)
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._drag_widget = None
        self._drag_surfaces = set()
        
        def start_drag(event):
            # A toplevel binding also receives events from child controls.
            # Only a press on a background surface can begin a drag gesture.
            if event.widget not in self._drag_surfaces:
                self._drag_widget = None
                return
            self._drag_widget = event.widget
            self._drag_offset_x = event.x_root - self.root.winfo_x()
            self._drag_offset_y = event.y_root - self.root.winfo_y()
            
        def do_drag(event):
            if self._drag_widget is None or event.widget is not self._drag_widget:
                return
            x = event.x_root - self._drag_offset_x
            y = event.y_root - self._drag_offset_y
            self.root.geometry(f"+{x}+{y}")
            
        def stop_drag(event):
            self._drag_widget = None

        def make_draggable(widget):
            self._drag_surfaces.add(widget)
            widget.bind("<Button-1>", start_drag, add="+")
            widget.bind("<B1-Motion>", do_drag, add="+")
            widget.bind("<ButtonRelease-1>", stop_drag, add="+")

        self.make_draggable = make_draggable
            
        # --- 1. Fixed Shockwave Radar Matrix Column (32px) ---
        self.eye_frame = tk.Frame(self.root, bg=self.COLOR_BG, width=44)
        self.eye_frame.pack(side="left", fill="y", padx=(11, 2))
        self.eye_frame.pack_propagate(False)
        
        self.eye_canvas = tk.Canvas(
            self.eye_frame,
            width=32,
            height=32,
            bg=self.COLOR_BG,
            highlightthickness=0,
            cursor="hand2"
        )
        self.eye_canvas.place(relx=0.5, rely=0.5, anchor="center")
        
        self.is_eye_active = False
        self._radar_after_id = None
        self._radar_angle = 0.0
        self._radar_warning = False
        
        # Square button background & border
        self.matrix_border = self.eye_canvas.create_rectangle(
            2, 2, 30, 30,
            fill=self.COLOR_INACTIVE_FILL,
            outline=self.COLOR_INACTIVE_OUTLINE,
            width=1.5
        )
        
        # 5x5 LED Dot Matrix setup (25 square micro-pixels)
        self.COLOR_DOT_INACTIVE = "#442e56"
        self.COLOR_DOT_HOVER = "#785396"
        self.COLOR_DOT_ACTIVE = "#FFD700"
        self.matrix_dots = []
        
        cx, cy = 16.0, 16.0
        step = 5.0
        half_dot = 1.4
        for row in range(5):
            y = cy + (row - 2) * step
            for col in range(5):
                x = cx + (col - 2) * step
                dx = x - cx
                dy = y - cy
                is_center = (row == 2 and col == 2)
                dot_angle = math.atan2(dy, dx)
                if dot_angle < 0:
                    dot_angle += 2 * math.pi
                    
                dot_id = self.eye_canvas.create_rectangle(
                    x - half_dot, y - half_dot,
                    x + half_dot, y + half_dot,
                    fill=self.COLOR_DOT_INACTIVE,
                    outline=""
                )
                self.matrix_dots.append({
                    "id": dot_id,
                    "angle": dot_angle,
                    "is_center": is_center
                })
        
        # Click handler for Radar Matrix Button
        def on_eye_click(event=None):
            if self.on_trigger:
                self.on_trigger()
                
        # Hover handlers
        def on_eye_enter(event=None):
            if not self.is_eye_active:
                self.eye_canvas.itemconfig(
                    self.matrix_border,
                    fill=self.COLOR_HOVER_FILL,
                    outline=self.COLOR_HOVER_OUTLINE
                )
                for dot in self.matrix_dots:
                    self.eye_canvas.itemconfig(dot["id"], fill=self.COLOR_DOT_HOVER)
                
        def on_eye_leave(event=None):
            if not self.is_eye_active:
                self.eye_canvas.itemconfig(
                    self.matrix_border,
                    fill=self.COLOR_INACTIVE_FILL,
                    outline=self.COLOR_INACTIVE_OUTLINE
                )
                for dot in self.matrix_dots:
                    self.eye_canvas.itemconfig(dot["id"], fill=self.COLOR_DOT_INACTIVE)
                
        self.eye_canvas.bind("<Button-1>", on_eye_click)
        self.eye_canvas.bind("<Enter>", on_eye_enter)
        self.eye_canvas.bind("<Leave>", on_eye_leave)
        
        # --- 2. Right Content Column (Status Text + Controls) ---
        self.right_frame = tk.Frame(self.root, bg=self.COLOR_BG)
        self.right_frame.pack(side="left", fill="both", expand=True, padx=(2, 6), pady=4)
        
        # Header row: Status label + Cancel button
        self.header_frame = tk.Frame(self.right_frame, bg=self.COLOR_BG)
        self.header_frame.pack(fill="x", pady=(2, 2))

        self.idle_text = "what is your command?"
        self.label = tk.Label(
            self.header_frame,
            text=self.idle_text,
            bg=self.COLOR_BG,
            fg=self.COLOR_TEXT,
            font=("Segoe UI", 9),
            anchor="w"
        )
        self.label.pack(side="left")

        # Cancel button (visible only during recording)
        self.cancel_btn = tk.Label(
            self.header_frame,
            text="cancel",
            bg=self.COLOR_BG,
            fg="#FFD700",
            font=("Segoe UI", 9, "italic underline"),
            cursor="hand2"
        )

        # Countdown timer (visible only during recording)
        self.countdown_label = tk.Label(
            self.header_frame,
            text="",
            bg=self.COLOR_BG,
            fg="#FFFFFF",
            font=("Segoe UI", 9),
            anchor="w"
        )
        self._countdown_after_id = None
        self._countdown_end_time = 0.0

        def on_cancel_click(event=None):
            self.stop_radar()
            self.stop_countdown()
            if self.on_cancel:
                self.on_cancel()
            else:
                self.reset_to_idle()

        def on_cancel_enter(event=None):
            self.cancel_btn.config(fg="#FFF59D")

        def on_cancel_leave(event=None):
            self.cancel_btn.config(fg="#FFD700")

        self.cancel_btn.bind("<Button-1>", on_cancel_click)
        self.cancel_btn.bind("<Enter>", on_cancel_enter)
        self.cancel_btn.bind("<Leave>", on_cancel_leave)
        
        # Checkbox controls container (three rows, three columns)
        self.controls_frame = tk.Frame(self.right_frame, bg=self.COLOR_BG)
        self.controls_frame.pack(fill="x", pady=(1, 0))
        
        # --- Column 0 ---
        # Row 0, Col 0: LLM norm checkbox
        self.llm_enabled = getattr(config, "LLM_NORM", False)
        def toggle_llm():
            self.llm_enabled = self.use_llm_var.get()
            
        self.use_llm_var = tk.BooleanVar(value=self.llm_enabled)
        self.chk_llm = tk.Checkbutton(
            self.controls_frame,
            text="LLM norm",
            variable=self.use_llm_var,
            command=toggle_llm,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_llm.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 2))

        # Row 1, Col 0: Wake word checkbox
        self.wake_enabled = getattr(config, "WAKE_WORD_ENABLED", True)
        def toggle_wake():
            self.wake_enabled = self.use_wake_var.get()
            if self.on_toggle_wake:
                self.on_toggle_wake(self.wake_enabled)
            
        self.use_wake_var = tk.BooleanVar(value=self.wake_enabled)
        self.chk_wake = tk.Checkbutton(
            self.controls_frame,
            text="wake",
            variable=self.use_wake_var,
            command=toggle_wake,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_wake.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 2))

        # --- Column 1 ---
        # Row 0, Col 1: AI task checkbox
        # Later columns assign these; declare them first so toggles can clear them.
        self.idea_enabled = False
        self.mk_post_enabled = False
        self.use_idea_var = tk.BooleanVar(value=False)
        self.use_mk_post_var = tk.BooleanVar(value=False)
        self.ai_task_enabled = getattr(config, "AI_TASK_MODE", False)
        def toggle_ai_task():
            self.ai_task_enabled = self.use_ai_task_var.get()
            if self.ai_task_enabled and self.idea_enabled:
                self.idea_enabled = False
                self.use_idea_var.set(False)
            if self.ai_task_enabled and self.mk_post_enabled:
                self.mk_post_enabled = False
                self.use_mk_post_var.set(False)

        self.use_ai_task_var = tk.BooleanVar(value=self.ai_task_enabled)
        self.chk_ai_task = tk.Checkbutton(
            self.controls_frame,
            text="AI task",
            variable=self.use_ai_task_var,
            command=toggle_ai_task,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_ai_task.grid(row=2, column=0, sticky="w", padx=(0, 8))

        # Row 1, Col 1: Alert sound checkbox (aligned strictly under AI task)
        self.alert_enabled = getattr(config, "ALERT_SOUND", True)
        def toggle_alert():
            self.alert_enabled = self.use_alert_var.get()
            
        self.use_alert_var = tk.BooleanVar(value=self.alert_enabled)
        self.chk_alert = tk.Checkbutton(
            self.controls_frame,
            text="alert",
            variable=self.use_alert_var,
            command=toggle_alert,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_alert.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 2))

        # --- Column 2 ---
        # Row 0, Col 2: to EN checkbox
        self.translate_en_enabled = getattr(config, "TRANSLATE_EN", False)
        def toggle_translate_en():
            self.translate_en_enabled = self.use_translate_en_var.get()

        self.use_translate_en_var = tk.BooleanVar(value=self.translate_en_enabled)
        self.chk_to_en = tk.Checkbutton(
            self.controls_frame,
            text="to EN",
            variable=self.use_translate_en_var,
            command=toggle_translate_en,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_to_en.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 2))

        # Row 1, Col 2: Clip+ checkbox (aligned strictly under to EN)
        self.clip_prepend_enabled = getattr(config, "CLIP_PREPEND", False)
        def toggle_clip():
            self.clip_prepend_enabled = self.use_clip_var.get()

        self.use_clip_var = tk.BooleanVar(value=self.clip_prepend_enabled)
        self.chk_clip = tk.Checkbutton(
            self.controls_frame,
            text="clip+",
            variable=self.use_clip_var,
            command=toggle_clip,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_clip.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=(0, 2))

        # --- Row 2 ---
        # Row 2, Col 0: Idea checkbox
        self.idea_enabled = getattr(config, "IDEA_MODE", False)
        if self.idea_enabled and self.ai_task_enabled:
            self.ai_task_enabled = False
            self.use_ai_task_var.set(False)
        self.use_idea_var.set(self.idea_enabled)

        def toggle_idea():
            self.idea_enabled = self.use_idea_var.get()
            if self.idea_enabled and self.ai_task_enabled:
                self.ai_task_enabled = False
                self.use_ai_task_var.set(False)
            if self.idea_enabled and self.mk_post_enabled:
                self.mk_post_enabled = False
                self.use_mk_post_var.set(False)

        self.chk_idea = tk.Checkbutton(
            self.controls_frame,
            text="Idea",
            variable=self.use_idea_var,
            command=toggle_idea,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_idea.grid(row=2, column=1, sticky="w", padx=(0, 8))

        # Row 2, Col 1: mk Post checkbox
        self.mk_post_enabled = getattr(config, "MK_POST_MODE", False)
        if self.mk_post_enabled and (self.ai_task_enabled or self.idea_enabled):
            self.mk_post_enabled = False

        def toggle_mk_post():
            self.mk_post_enabled = self.use_mk_post_var.get()
            if self.mk_post_enabled:
                if self.ai_task_enabled:
                    self.ai_task_enabled = False
                    self.use_ai_task_var.set(False)
                if self.idea_enabled:
                    self.idea_enabled = False
                    self.use_idea_var.set(False)

        self.use_mk_post_var.set(self.mk_post_enabled)
        self.chk_mk_post = tk.Checkbutton(
            self.controls_frame,
            text="mk Post",
            variable=self.use_mk_post_var,
            command=toggle_mk_post,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_mk_post.grid(row=2, column=2, sticky="w")

        # Row 2, Col 2: paste clipboard into the active application
        self.paste_enabled = getattr(config, "AUTO_PASTE", False)
        def toggle_paste():
            self.paste_enabled = self.use_paste_var.get()

        self.use_paste_var = tk.BooleanVar(value=self.paste_enabled)
        self.chk_paste = tk.Checkbutton(
            self.controls_frame,
            text="paste",
            variable=self.use_paste_var,
            command=toggle_paste,
            bg=self.COLOR_BG,
            fg=self.COLOR_MUTED,
            selectcolor=self.COLOR_GRIP,
            activebackground=self.COLOR_BG,
            activeforeground="#ffffff",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=0
        )
        self.chk_paste.grid(row=1, column=2, sticky="w")

        # Recognition mode buttons, right of the checkboxes and centered vertically.
        self.mode_frame = tk.Frame(self.root, bg=self.COLOR_BG)
        self.mode_frame.pack(side="right", padx=(0, 22))

        self.recognition_mode = tk.StringVar(value=getattr(config, "RECOGNITION_MODE", "ru"))

        def choose_recognition_mode(mode):
            if self.recognition_mode.get() == mode:
                self._paint_mode_buttons()
                return
            self.recognition_mode.set(mode)
            config.RECOGNITION_MODE = mode
            self._paint_mode_buttons()
            save_setting = getattr(config, "save_setting", None)
            if save_setting is None:
                return
            try:
                save_setting("RECOGNITION_MODE", mode)
            except Exception as e:
                print(f"[UI] Could not save recognition mode: {e}")

        def add_mode_button(text, mode):
            holder = tk.Frame(self.mode_frame, width=28, height=28, bg=self.COLOR_BG)
            holder.pack_propagate(False)
            button = tk.Button(
                holder, text=text, cursor="hand2",
                font=("Segoe UI", 8, "bold"),
                command=lambda: choose_recognition_mode(mode),
                highlightthickness=0, padx=0, pady=0, borderwidth=1,
            )
            button.pack(fill="both", expand=True)
            return button, holder

        self.btn_ru, self.ru_holder = add_mode_button("RU", "ru")
        self.ru_holder.pack(side="top", pady=(0, 4))
        self.btn_ml, self.ml_holder = add_mode_button("ML", "multi")
        self.ml_holder.pack(side="top")
        self._paint_mode_buttons()

        # Close button in top-right: exits application
        def on_close(event=None):
            self.root.quit()
            
        self.close_btn = tk.Label(self.root, text="×", bg=self.COLOR_BG, fg=self.COLOR_MUTED, font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.close_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-3, y=1)
        self.close_btn.bind("<Button-1>", on_close)
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(fg="#ff5555"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(fg=self.COLOR_MUTED))
        # Bind dragging to all container frames and background labels for seamless whole-bar moving
        for bg_widget in (self.root, self.eye_frame, self.right_frame, self.header_frame, self.label, self.countdown_label, self.controls_frame, self.mode_frame):
            self.make_draggable(bg_widget)
            
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = 340
        height = 102
        
        if position == "bottom-right":
            x = screen_width - width - 20
            y = screen_height - height - 60
        elif position == "bottom-left":
            x = 20
            y = screen_height - height - 60
        elif position == "top-center":
            x = (screen_width - width) // 2
            y = 20
        else:
            x = (screen_width - width) // 2
            y = screen_height - height - 60
            
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
        # Configure permanent taskbar icon style before showing
        self.setup_taskbar_style()
        
        self.reset_id = None
        self._topmost_tick = 0
        self.check_queue()

    def set_eye_active(self, is_active):
        """Switches between active state (solid golden matrix) and inactive state (subtle purple grid)."""
        self.stop_radar()
        self.is_eye_active = is_active
        if is_active:
            self.eye_canvas.itemconfig(
                self.matrix_border,
                fill=self.COLOR_INACTIVE_FILL,
                outline=self.COLOR_ACTIVE_OUTLINE
            )
            for dot in self.matrix_dots:
                self.eye_canvas.itemconfig(
                    dot["id"],
                    fill=self.COLOR_DOT_ACTIVE
                )
        else:
            self.eye_canvas.itemconfig(
                self.matrix_border,
                fill=self.COLOR_INACTIVE_FILL,
                outline=self.COLOR_INACTIVE_OUTLINE
            )
            for dot in self.matrix_dots:
                self.eye_canvas.itemconfig(
                    dot["id"],
                    fill=self.COLOR_DOT_INACTIVE
                )

    def start_radar(self):
        """Starts the rotating radar sweep animation with trailing fade across the dot matrix."""
        self.stop_radar()
        self.is_eye_active = True
        self._radar_warning = False
        self._radar_angle = 0.0
        self.eye_canvas.itemconfig(
            self.matrix_border,
            fill=self.COLOR_INACTIVE_FILL,
            outline=self.COLOR_ACTIVE_OUTLINE
        )
        self._radar_tick()

    def set_radar_warning(self, is_warning: bool = True):
        """Switches radar into flashing red warning state."""
        self._radar_warning = is_warning

    def _radar_tick(self):
        """Calculates beam angle and interpolates dot brightness with trail decay."""
        # 35ms interval (~28 FPS), advance by 0.16 rad per tick (~1.37s per full 360 deg sweep)
        self._radar_angle = (self._radar_angle + 0.16) % (2 * math.pi)
        trail_span = 1.25 * math.pi  # ~225 degrees trail length
        
        if self._radar_warning:
            # Flashing red beacon (~3.5 Hz)
            is_bright = (int(time.time() * 3.5) % 2) == 0
            border_col = "#FF2222" if is_bright else "#551122"
            center_col = "#FF2222" if is_bright else "#551122"
            self.eye_canvas.itemconfig(self.matrix_border, outline=border_col)
            
            for dot in self.matrix_dots:
                if dot["is_center"]:
                    self.eye_canvas.itemconfig(dot["id"], fill=center_col)
                    continue
                    
                diff = (self._radar_angle - dot["angle"]) % (2 * math.pi)
                if diff <= trail_span:
                    factor = 1.0 - (diff / trail_span)
                    intensity = factor ** 1.3
                    if is_bright:
                        r = 255
                        g = int(40 * (1.0 - intensity))
                        b = int(40 * (1.0 - intensity))
                    else:
                        r = int(90 * intensity)
                        g = 15
                        b = 25
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                    self.eye_canvas.itemconfig(dot["id"], fill=hex_color)
                else:
                    self.eye_canvas.itemconfig(dot["id"], fill=self.COLOR_DOT_INACTIVE)
        else:
            self.eye_canvas.itemconfig(self.matrix_border, outline=self.COLOR_ACTIVE_OUTLINE)
            for dot in self.matrix_dots:
                if dot["is_center"]:
                    # Center core dot glows bright gold as the radar axis
                    self.eye_canvas.itemconfig(dot["id"], fill="#FFD700")
                    continue
                    
                diff = (self._radar_angle - dot["angle"]) % (2 * math.pi)
                if diff <= trail_span:
                    factor = 1.0 - (diff / trail_span)
                    intensity = factor ** 1.3
                    
                    if intensity > 0.7:
                        t = (intensity - 0.7) / 0.3
                        r = 255
                        g = int(215 + (250 - 215) * t)
                        b = int(0 + (175 - 0) * t)
                    else:
                        t = intensity / 0.7
                        r = int(68 + (255 - 68) * t)
                        g = int(46 + (215 - 46) * t)
                        b = int(86 + (0 - 86) * t)
                        
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                    self.eye_canvas.itemconfig(dot["id"], fill=hex_color)
                else:
                    self.eye_canvas.itemconfig(dot["id"], fill=self.COLOR_DOT_INACTIVE)
                
        self._radar_after_id = self.root.after(35, self._radar_tick)

    def stop_radar(self):
        """Stops the radar animation and cancels any scheduled timer."""
        self._radar_warning = False
        if self._radar_after_id:
            try:
                self.root.after_cancel(self._radar_after_id)
            except Exception:
                pass
            self._radar_after_id = None

    def start_countdown(self, total_seconds=None):
        """Initializes and runs countdown timer display."""
        if self._countdown_after_id:
            try:
                self.root.after_cancel(self._countdown_after_id)
            except Exception:
                pass
            self._countdown_after_id = None
        if total_seconds is None:
            total_seconds = getattr(config, "MAX_RECORD_SECONDS", 180)
        self._countdown_end_time = time.time() + float(total_seconds)
        self._update_countdown()
        self.countdown_label.pack(side="left", padx=(12, 0))
        self._countdown_tick()

    def _update_countdown(self):
        remaining = max(0, int(math.ceil(self._countdown_end_time - time.time())))
        mins = remaining // 60
        secs = remaining % 60
        self.countdown_label.config(text=f"{mins:02d}:{secs:02d}")
        return remaining

    def _countdown_tick(self):
        remaining = self._update_countdown()
        if remaining > 0:
            self._countdown_after_id = self.root.after(250, self._countdown_tick)
        else:
            self._countdown_after_id = None

    def stop_countdown(self):
        """Cancels running countdown timer and removes the label."""
        if self._countdown_after_id:
            try:
                self.root.after_cancel(self._countdown_after_id)
            except Exception:
                pass
            self._countdown_after_id = None
        self.countdown_label.pack_forget()

    def get_window_hwnd(self):
        try:
            wid = self.root.winfo_id()
            hwnd = ctypes.windll.user32.GetAncestor(wid, 2)  # GA_ROOT
            if not hwnd:
                hwnd = ctypes.windll.user32.GetParent(wid)
            return hwnd if hwnd else wid
        except Exception:
            return self.root.winfo_id()

    def setup_taskbar_style(self):
        """Applies WS_EX_TOOLWINDOW to ensure the floating widget stays hidden from the taskbar."""
        try:
            self.root.update_idletasks()
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            
            hwnd = self.get_window_hwnd()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            self.enforce_topmost()
        except Exception:
            pass

    def enforce_topmost(self, force_foreground=False):
        """Guarantees the window permanently stays above all other windows using 64-bit safe native Win32 API."""
        try:
            hwnd = self.get_window_hwnd()
            HWND_TOPMOST = wintypes.HWND(-1)
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            
            flags = SWP_NOMOVE | SWP_NOSIZE
            if not force_foreground:
                flags |= SWP_NOACTIVATE
                
            ctypes.windll.user32.SetWindowPos(
                wintypes.HWND(hwnd),
                HWND_TOPMOST,
                0, 0, 0, 0,
                flags
            )
            self.root.lift()
            self.root.attributes("-topmost", True)
            if force_foreground:
                ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))
        except Exception:
            pass

    def _paint_mode_buttons(self):
        """Show the selected RU/ML button pressed and the other released."""
        selected = self.recognition_mode.get()
        pairs = ((self.btn_ru, "ru"), (self.btn_ml, "multi"))
        for button, mode in pairs:
            pressed = selected == mode
            button.config(
                bg="#d8c4ef" if pressed else self.COLOR_BG,
                fg="#1d1228" if pressed else self.COLOR_MUTED,
                relief="sunken" if pressed else "flat",
                bd=1,
            )

    def show_window(self, play_sound=True):
        """Displays the ready widget and brings it above all windows."""
        self.root.deiconify()
        self.setup_taskbar_style()
        self.enforce_topmost(force_foreground=True)
        if play_sound and self.startup_sound_enabled:
            play_startup_sound()

    def reset_to_idle(self):
        self.stop_radar()
        self.stop_countdown()
        self.label.config(text=self.idle_text)
        self.cancel_btn.pack_forget()
        self.set_eye_active(False)
        self.reset_id = None

    def check_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                cmd = msg.get("cmd")
                
                if cmd == "show":
                    if self.reset_id:
                        self.root.after_cancel(self.reset_id)
                        self.reset_id = None
                        
                    txt = msg.get("text", "")
                    self.label.config(text=txt)
                    
                    if txt == "record":
                        self.cancel_btn.pack(side="left", padx=(10, 0))
                        self.start_countdown()
                        self.start_radar()
                    elif txt in ["processing", "normalization"]:
                        self.cancel_btn.pack_forget()
                        self.stop_countdown()
                        self.set_eye_active(True)
                    else:
                        self.cancel_btn.pack_forget()
                        self.stop_countdown()
                        self.set_eye_active(False)
                    
                elif cmd == "show_ready":
                    if self.reset_id:
                        self.root.after_cancel(self.reset_id)
                    self.label.config(text="ready")
                    self.cancel_btn.pack_forget()
                    self.stop_countdown()
                    
                    # Becomes inactive on ready
                    self.set_eye_active(False)
                    
                    # Play sound on ready
                    if self.alert_enabled:
                        play_ready_sound()
                        
                    # Return to idle text after 5 seconds
                    self.reset_id = self.root.after(5000, self.reset_to_idle)
                    
                elif cmd == "show_topmost":
                    self.show_window(play_sound=False)
                elif cmd == "radar_warning":
                    self.set_radar_warning(True)
                elif cmd == "quit":
                    self.root.quit()
                    return
        except queue.Empty:
            pass
        finally:
            self._topmost_tick += 1
            if self._topmost_tick >= 10:
                self._topmost_tick = 0
                self.enforce_topmost()
            self.root.after(100, self.check_queue)

    def run(self):
        self.show_window()
        self.root.mainloop()
