"""Windows global-hotkey capture via RegisterHotKey (+ low-level hook fallback).

When the configured combo (default Ctrl+Shift+D) is pressed anywhere, we
simulate Ctrl+C to copy the focused selection, read the clipboard, and
invoke a callback.  No third-party packages required — works with stdlib.

Mechanism: `RegisterHotKey` reserves the combo *system-wide* — Windows then
consumes the keystroke at the OS level, so the focused application (e.g. a
browser) never receives it and its own Ctrl+Shift+D shortcut cannot fire.
If another program already registered the same combo, we fall back to a
WH_KEYBOARD_LL hook that swallows the keydown/keyup itself.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes as wt
from typing import Callable, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Modifier flags for RegisterHotKey
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

HOTKEY_ID = 0xAE02

# Virtual keys
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12

VK_MAP = {
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A, "space": 0x20,
}

user32.RegisterHotKey.argtypes = [wt.HWND, wt.INT, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, wt.INT]
user32.UnregisterHotKey.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL


# --- low-level keyboard hook (fallback) ------------------------------------
LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    wt.LONG, wt.INT, wt.WPARAM, wt.LPARAM
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),  # pointer-sized
    ]


class _Hook:
    """Reserves a global combo; fires callback when it is pressed.

    Runs a background thread with its own GetMessageW loop.  When the combo is
    registered with RegisterHotKey, WM_HOTKEY messages are posted to this
    thread's queue; otherwise a WH_KEYBOARD_LL hook swallows the keystrokes.
    """

    def __init__(self, combo: tuple[str, ...], on_trigger):
        self.combo = [c.lower() for c in combo]
        self.on_trigger = on_trigger
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._handle = None      # LL-hook handle (fallback path)
        self._proc = None        # LL-hook proc (fallback path)
        self._hotkey_registered = False

    # -- combo parsing -----------------------------------------------------
    def _wanted(self) -> tuple[bool, bool, bool, int]:
        ctrl = "ctrl" in self.combo
        shift = "shift" in self.combo
        alt = "alt" in self.combo
        key = self.combo[-1]
        vk = VK_MAP.get(key)
        if vk is None:
            raise ValueError(f"unknown hotkey key: {key!r} (supported: letters a-z or 'space')")
        return ctrl, shift, alt, vk

    def _mods_flags(self) -> int:
        ctrl, shift, alt, _ = self._wanted()
        mods = 0
        if ctrl:
            mods |= MOD_CONTROL
        if shift:
            mods |= MOD_SHIFT
        if alt:
            mods |= MOD_ALT
        return mods

    def _fire(self) -> None:
        now = time.monotonic()
        if getattr(self, "_last_fire", 0) < now - 0.5:
            self._last_fire = now
            threading.Thread(target=self.on_trigger, daemon=True).start()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        # Capture the hook thread's id NOW so stop() can post WM_QUIT to the
        # thread that actually runs the GetMessageW loop.
        self._thread_ident = self._thread.ident
        self._thread.start()

    def _run(self) -> None:
        try:
            self._wanted()  # validate the combo key early (raises ValueError)
        except ValueError:
            self._running = False
            raise
        if self._register_hotkey():
            self._hotkey_loop()
            self._unregister_hotkey()
        else:
            self._ll_fallback_loop()  # combo owned elsewhere -> LL hook

    # -- RegisterHotKey path (primary) -------------------------------------
    def _register_hotkey(self) -> bool:
        _, _, _, vk = self._wanted()
        mods = self._mods_flags() | MOD_NOREPEAT
        ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, mods, vk))
        if ok:
            self._hotkey_registered = True
            return True
        print("[capture] RegisterHotKey failed (combo already reserved by another "
              "app?) — falling back to a low-level keyboard hook", file=sys.stderr)
        return False

    def _unregister_hotkey(self) -> None:
        if self._hotkey_registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._hotkey_registered = False

    def _hotkey_loop(self) -> None:
        msg = wt.MSG()
        try:
            while self._running:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    self._fire()
                    # Don't TranslateMessage/DispatchMessageW: this is our own
                    # thread message, not a window message.
        finally:
            self._unregister_hotkey()

    # -- LL hook path (fallback: combo already registered elsewhere) --------
    def _mods_pressed(self) -> tuple[bool, bool, bool]:
        ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        return ctrl, shift, alt

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode == 0:
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            ctrl_want, shift_want, alt_want, vk_want = self._wanted()
            if info.vkCode == vk_want:
                ctrl, shift, alt = self._mods_pressed()
                if ctrl == ctrl_want and shift == shift_want and alt == alt_want:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._fire()
                    # Swallow BOTH keydown and keyup so no app (browser, IDE,
                    # terminal, ...) ever sees the combo.
                    return 1
        return user32.CallNextHookEx(self._handle, nCode, wParam, lParam)

    def _message_loop(self) -> None:
        self._proc = LowLevelKeyboardProc(self._hook_proc)
        self._handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0
        )
        if not self._handle:
            return
        msg = wt.MSG()
        try:
            while self._running:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(self._handle)
            self._handle = None

    def _ll_fallback_loop(self) -> None:
        # If the LL hook install fails transiently, retry a few times so the
        # hotkey doesn't die silently mid-session.
        attempts = 0
        while self._running:
            self._message_loop()
            if not self._running:
                break
            attempts += 1
            if attempts >= 10:
                self._running = False
                return
            time.sleep(0.5)

    def stop(self) -> None:
        self._running = False
        if getattr(self, "_thread_ident", None):
            # Post WM_QUIT to the hook thread so its GetMessageW loop returns
            # and the finally blocks (unhook/unregister) actually run.
            user32.PostThreadMessageW(self._thread_ident, WM_QUIT, 0, 0)


# -- helpers ------------------------------------------------------------
# Modifier virtual keys (VK_SHIFT/VK_CONTROL/VK_MENU defined at the top of the
# module are the same values; these aliases keep the sequence below readable).
_MOD_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU)


def send_ctrl_c() -> None:
    """Simulate Ctrl+C (copies the current selection to the clipboard).

    The user is usually still holding the hotkey modifiers (e.g. Shift in
    Ctrl+Shift+D) when this runs.  Those modifiers would leak into the
    injected 'C' and the focused app would see Ctrl+Shift+C (Chrome opens
    devtools) instead of a plain copy.  So we temporarily release Shift/Alt,
    inject a clean Ctrl+C, and restore the user's original modifier state.
    """
    keybd_event = user32.keybd_event
    KEYUP = 0x0002

    # Snapshot which modifiers the user is physically holding right now.
    held = {vk: bool(user32.GetAsyncKeyState(vk) & 0x8000) for vk in _MOD_KEYS}

    # 1. Lift everything (we synthesize a clean, controlled sequence below).
    for vk in _MOD_KEYS:
        if held.get(vk):
            keybd_event(vk, 0, KEYUP, 0)

    # 2. Send a plain Ctrl+C (Shift/Alt are up, so the app sees Ctrl+C only).
    try:
        keybd_event(VK_CONTROL, 0, 0, 0)
        time.sleep(0.02)
        keybd_event(0x43, 0, 0, 0)  # 'C'
        time.sleep(0.02)
        keybd_event(0x43, 0, KEYUP, 0)
        keybd_event(VK_CONTROL, 0, KEYUP, 0)
    finally:
        # 3. Restore any modifier the user is STILL physically holding, so the
        # OS doesn't end up in a stuck-keys state while their finger is down.
        for vk in _MOD_KEYS:
            if held.get(vk) and (user32.GetAsyncKeyState(vk) & 0x8000):
                keybd_event(vk, 0, 0, 0)  # re-press
    time.sleep(0.1)


def run_hotkey(combo: tuple[str, ...], on_trigger) -> _Hook:
    hook = _Hook(combo, on_trigger)
    hook.start()
    return hook