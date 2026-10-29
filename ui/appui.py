"""Single-UI-thread controller for AnkiExt.

Tkinter is not thread-safe and must be driven from exactly one thread.  This
controller owns one Tk root and a queue-pumped event loop, so the hotkey hook
(a background thread) and any tray/button handlers can safely ask the GUI to
show a preview or quit — without touching Tk from another thread.  This fixes
the earlier bug where the preview window was built on the hotkey's thread and
rendered blank / unreliably.

The root also doubles as the tiny control panel used when pystray is not
installed (always-on-top, "capture" and "quit" buttons).
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class AppUI:
    """Owns the one tkinter root + the after()-pumped command queue."""

    def __init__(self, on_capture: Callable[[Optional[str]], None],
                 on_quit: Callable[[], None],
                 on_result: Optional[Callable[[list, str, int | None], None]] = None,
                 title: str = "AnkiExt",
                 hotkey_label: str = "Ctrl+Shift+D"):
        self._on_capture = on_capture
        self._on_quit = on_quit
        self._on_result = on_result or (lambda _c, _s, _sc: None)
        self.hotkey_label = hotkey_label
        self.q: "queue.Queue[tuple[str, dict]]" = queue.Queue()

        self.root = tk.Tk()
        self.root.title(title)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.status_var = tk.StringVar(value="Ready")
        self._build()

        self.root.protocol("WM_DELETE_WINDOW", self._request_quit)
        self.root.after(30, self._pump)

    # -- control panel (acts as the tray fallback) ----------------------
    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="AnkiExt", font=("Arial", 12, "bold")).pack(pady=2)
        ttk.Label(frame, text=f"Hotkey: {self.hotkey_label}").pack(pady=2)
        ttk.Label(frame, textvariable=self.status_var,
                  foreground="#555", wraplength=260).pack(pady=2)

        btns = ttk.Frame(frame)
        btns.pack(pady=6)
        ttk.Button(btns, text="Add Card", command=self._request_capture
                   ).pack(side="left", padx=4)
        ttk.Button(btns, text="Quit", command=self._request_quit
                   ).pack(side="left", padx=4)

    # -- API --------------------------------------------------------------
    def post(self, cmd: str, **kw) -> None:
        """Schedule a command on the UI thread (safe from any thread)."""
        self.q.put((cmd, dict(kw)))

    def status(self, msg: str) -> None:
        self.status_var.set(msg)

    def run(self) -> None:
        self.root.mainloop()

    # -- queue pump (runs on the UI thread, via after) ------------------
    def _pump(self) -> None:
        try:
            while True:
                cmd, kw = self.q.get_nowait()
                self._dispatch(cmd, kw)
        except queue.Empty:
            pass
        self.root.after(30, self._pump)

    def _dispatch(self, cmd: str, kw: dict) -> None:
        if cmd == "quit":
            self._do_quit()
        elif cmd == "capture":
            self._on_capture(kw.get("text"))
        elif cmd == "result":
            # A worker thread finished a lookup; render its candidates here on
            # the UI thread (never touch Tk off the main thread).
            self._on_result(kw.get("cands") or [], kw.get("status") or "",
                            kw.get("strong_count") or 5)

    # -- actions ----------------------------------------------------------
    def _request_capture(self) -> None:
        self._on_capture(None)

    def _request_quit(self) -> None:
        self.post("quit")

    def _do_quit(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
        if self._on_quit:
            self._on_quit()