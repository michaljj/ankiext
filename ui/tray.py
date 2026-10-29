"""System tray integration for AnkiExt (native pystray, run on a background thread).

When pystray is installed we show a native tray icon and run its event loop on
a background thread.  The main UI thread keeps its own Tk root purely as the
host for the preview / prompt dialogs (there is no cross-thread Tk).  When
pystray is missing, `available()` is False and `ui.appui.AppUI` shows its
floating control panel instead.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


def _try_import_pystray():
    try:
        import pystray  # noqa: F401
        return True
    except Exception:
        return False


class TrayIcon:
    @staticmethod
    def available() -> bool:
        return _try_import_pystray()

    def __init__(self, on_create: Callable[[], None],
                 on_quit: Callable[[], None],
                 title: str = "AnkiExt",
                 hotkey_label: str = "Ctrl+Shift+D"):
        self.on_create = on_create
        self.on_quit = on_quit
        self.title = title
        self.hotkey_label = hotkey_label
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._icon is not None:
            return
        # pystray's run() blocks until icon.stop(), so it must live on its own
        # thread and must NOT own any Tk objects.
        self._thread = threading.Thread(target=self._run_pystray, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass

    def _run_pystray(self):
        import pystray
        from PIL import Image, ImageDraw

        def make_image():
            img = Image.new("RGB", (64, 64), (40, 40, 40))
            d = ImageDraw.Draw(img)
            d.ellipse((12, 12, 52, 52), fill=(255, 215, 0))
            d.text((22, 26), "A", fill=(0, 0, 0))
            return img

        menu = pystray.Menu(
            pystray.MenuItem(f"Add Card ({self.hotkey_label})", self.on_create),
            pystray.MenuItem("Quit", self.on_quit),
        )
        self._icon = pystray.Icon(self.title, make_image(), "AnkiExt", menu)
        self._icon.run()
        return self._icon