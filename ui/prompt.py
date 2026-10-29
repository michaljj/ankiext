"""Small text-entry dialog (Toplevel) used when nothing was captured.

Lets the user paste / type the term to add, so the global hotkey always gives
visible feedback instead of silently doing nothing when the focused app does
not respond to a synthetic Ctrl+C.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class TTextPromptWindow:
    def __init__(self, master: tk.Tk,
                 on_submit: Callable[[Optional[str]], None],
                 title: str = "AnkiExt — Enter text",
                 topmost: bool = True):
        self.on_submit = on_submit
        self.root = tk.Toplevel(master)
        self.root.title(title)
        self.root.resizable(True, False)
        if topmost:
            self.root.attributes("-topmost", True)
        self.root.transient(master)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self._build()
        self.root.lift()
        self.textbox.focus_force()

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text=(
            "No text was captured. Select text in another app and press the "
            "hotkey, or paste / type the term manually:"
        ), wraplength=360).pack(anchor="w", pady=(0, 6))

        self._text = tk.Text(main, height=3, width=44, wrap="word")
        self._text.pack(fill="both", expand=True, pady=4)

        btns = ttk.Frame(main)
        btns.pack(pady=8)
        ttk.Button(btns, text="Create Card", command=self._submit_text).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=4)

        main.bind("<Control-Return>", lambda _: self._submit_text())
        self.root.bind("<Escape>", lambda _: self.cancel())

    @property
    def textbox(self) -> tk.Text:
        return self._text

    def _submit_text(self) -> None:
        text = self._text.get("1.0", "end-1c").strip()
        self._finish(text or None)

    def cancel(self) -> None:
        self._finish(None)

    def _finish(self, text: Optional[str]) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
        if self.on_submit:
            self.on_submit(text)