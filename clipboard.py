"""Clipboard helpers: read text from the OS clipboard (stdlib tkinter)."""
from __future__ import annotations

import tkinter as tk


def read_clipboard() -> str:
    """Return the current clipboard text, if any ('' otherwise)."""
    root = tk.Tk()
    root.withdraw()  # hidden
    try:
        try:
            root.update()  # allow clipboard retrieval
        except tk.TclError:
            pass
        try:
            return root.clipboard_get().strip()
        except tk.TclError:
            return ""
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass