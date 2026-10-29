"""AnkiExt main app: single-UI-thread controller + global hotkey -> card preview -> Anki.

All tkinter windows (control panel, preview, manual-entry prompt) are owned by
ONE UI thread (the main thread) via the AppUI queue-pump, so the hotkey hook
running on a background thread can never touch Tk.  This makes the preview
render reliably and the hotkey respond consistently.

File/dictionary/plural lookups run on a dedicated WORKER thread (they can
block on SQLite or network) that posts results back to the UI queue, so the
UI thread never stalls on disk or network I/O.

Usage:
    python app.py              # run tray/control + hotkey listener (default)
    python app.py --once       # single-shot: process the clipboard once
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

# Make this app importable from any folder it is copied to (portable).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk  # noqa: E402

from capture import run_hotkey, send_ctrl_c                              # noqa: E402
from cards.builder import CardBuilder                                    # noqa: E402
from cards.anki_setup import ensure_deck, ensure_model, note_fields      # noqa: E402
from clipboard import read_clipboard                                     # noqa: E402
from config import load_config                                           # noqa: E402
from detect_lang import detect_language                                  # noqa: E402
from dictlookup.analyzers import Analyzers                               # noqa: E402
from dictlookup.lookup import Dictionary                                 # noqa: E402
from german.plural import PluralDB                                       # noqa: E402
from anki_connect import AnkiConnect, AnkiConnectError                   # noqa: E402
from engine import build_candidates, german_candidates                   # noqa: E402
from fallback.wiktionary_api import WiktionaryAPI                       # noqa: E402

from ui.appui import AppUI          # noqa: E402
from ui.preview import PreviewWindow  # noqa: E402
from ui.prompt import TTextPromptWindow  # noqa: E402
from ui.tray import TrayIcon        # noqa: E402


class AnkiExtApp:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        dic = cfg["dictionary"]
        self.plural = PluralDB(dic["plural_db"])
        # Optional real morphology engines (spaCy / morfeusz2 / DWDSmor).
        self.analyzers = Analyzers(cfg.get("morphology"))
        # German inflected-form -> lemma resolver shared by dict matching.
        self.dict = Dictionary(cfg, resolve_form=self.plural.resolve_form,
                               analyzers=self.analyzers)
        self.builder = CardBuilder(self.plural)
        self.anki = AnkiConnect(cfg["anki"]["host"], cfg["anki"]["port"])
        self.hotkey = cfg["hotkey"]["combos"][0] if cfg["hotkey"]["combos"] else "ctrl+shift+d"
        # Optional Wiktionary network last resort (disable in config to stay offline).
        if cfg.get("fallback", {}).get("wiktionary", True):
            self.wikt = WiktionaryAPI(dic.get("wikt_cache", "data/wikt_cache.sqlite"))
        else:
            self.wikt = None
        self._hook = None
        self._ui = None
        self._work_q: "queue.Queue[object]" = queue.Queue()
        self._worker = None

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        combo = tuple(self.hotkey.split("+"))
        # Hotkey fires on a background thread; it only POSTS to the UI queue.
        self._hook = run_hotkey(combo, self._post_capture)
        self._ui = AppUI(on_capture=self.capture,
                         on_quit=self.stop_and_exit,
                         on_result=self._show_result,
                         hotkey_label=self.hotkey)
        # Lookups run on a worker thread and post results to the UI queue.
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        print(f"AnkiExt running — press {self.hotkey} to create a card.\n"
              "Ctrl+C in another app first also works; if nothing is captured "
              "a text-entry dialog appears.", flush=True)
        if TrayIcon.available():
            # Native tray runs on its own thread; the control panel's root is
            # still the host for preview/prompt dialogs on the main thread.
            self._tray = TrayIcon(on_create=self._post_capture,
                                  on_quit=self.stop_and_exit,
                                  hotkey_label=self.hotkey)
            self._tray.start()  # background thread
            self._ui.root.withdraw()  # native tray replaces the control panel
        self._ui.run()  # mainloop on the main thread (the only Tk thread)

    def stop(self) -> None:
        if self._hook:
            self._hook.stop()
        if getattr(self, "_tray", None):
            self._tray.stop()
        # Let the worker idle out before closing connections it may be using.
        if self._worker is not None:
            self._work_q.put(None)  # sentinel: end the worker loop
            self._worker.join(timeout=5.0)
        self.dict.close()
        self.plural.close()
        if getattr(self, "wikt", None) is not None:
            try:
                self.wikt.close()
            except Exception:
                pass

    def stop_and_exit(self) -> None:
        import os
        self.stop()
        # Let teardown (finally blocks, db close) run; fall back to a hard exit
        # if the UI thread doesn't settle quickly.
        try:
            if self._ui is not None:
                self._ui.root.destroy()
        except Exception:
            pass
        try:
            sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            os._exit(0)

    # -- capture (runs on the UI thread via the queue) -------------------
    def _post_capture(self) -> None:
        """Hotkey-thread entry: ask the UI thread to capture now."""
        if self._ui:
            self._ui.post("capture")

    def capture(self, manual_text: str | None = None) -> None:
        """Capture selection/clipboard and open the preview. UI thread only."""
        text = (manual_text or "").strip()
        if not text:
            before = self._clipboard_text()
            send_ctrl_c()
            after = self._clipboard_text()
            # Prefer the freshly-copied selection; fall back to prior clipboard.
            text = (after or before).strip()
        if not text:
            # Nothing captured → let the user paste / type instead of failing
            # silently. This dialog itself runs on the UI thread.
            self._ui.status("No text captured — enter it manually below.")
            TTextPromptWindow(self._ui.root, self.capture)
            return
        self._ui.status(f"Looking up {text!r} …")
        self.process_text(text)

    def _clipboard_text(self) -> str:
        """Read the clipboard via the shared root (must be UI thread)."""
        try:
            return self._ui.root.clipboard_get().strip()
        except tk.TclError:
            return ""

    # -- worker (lookups happen off the UI thread) -----------------------
    def process_text(self, text: str) -> None:
        """Enqueue a lookup; results are rendered via _show_result (UI thread)."""
        self._work_q.put(text)

    def _worker_loop(self) -> None:
        while True:
            text = self._work_q.get()
            if text is None:
                return
            try:
                self._run_lookup(text)
            except Exception as e:  # keep the worker alive across errors
                print(f"[engine] lookup error: {e!r}", file=sys.stderr)
                self._post_result([], f"Lookup error: {e}")

    def _run_lookup(self, text: str) -> None:
        """Route captured text: German -> reverse card, else foreign -> German.

        The German gate is a HINT, not a verdict: a lowercase English word
        ('mutter', 'gas', 'was') can be a German lemma/inflection too, and the
        German route may come back empty or wrong.  When it yields nothing we
        fall through to the forward (English/Polish) flow instead of showing
        "No German data" or a misleading card.
        """
        w = text.strip()
        if self._german_candidate(w):
            cands_g, info = german_candidates(w, self.plural, dictionary=self.dict,
                                              analyzers=self.analyzers)
            if cands_g:
                lemma = info.get("lemma") or w
                self._post_result(cands_g,
                                  f"German word {lemma!r}: showing {len(cands_g)} meaning(s)")
                return
            # fall through: the German route was empty -> try foreign flow
        lang = detect_language(w, self.cfg["languages"]["polish_diacritics"],
                               dict_hint=self.dictionary_has_polish,
                               dict_hint_en=self.dictionary_has_english,
                               analyzers=self.analyzers)
        cands = build_candidates(w, lang, self.dict, self.plural, self.builder,
                                 wikt=self.wikt,
                                 max_candidates=self._strong_count(),
                                 total_cap=self._total_cap(),
                                 analyzers=self.analyzers)
        if not cands:
            self._post_result([], f"No automated suggestion for {w!r} — edit manually.")
            return
        self._post_result(cands, f"Showing {len(cands)} candidate(s) for {w!r}")

    def _strong_count(self) -> int:
        return int(self.cfg.get("ui", {}).get("max_candidates", 5))

    def _total_cap(self) -> int:
        return int(self.cfg.get("matching", {}).get("total_cap", self._strong_count() * 3))

    def _post_result(self, cands: list, status: str) -> None:
        if self._ui is not None:
            self._ui.post("result", cands=cands, status=status,
                          strong_count=self._strong_count())

    def _show_result(self, cands: list, status: str, strong_count: int | None = None) -> None:
        """Render lookup results on the UI thread (called from the pump)."""
        self._status(status)
        PreviewWindow(cands, on_submit=self.on_submit, master=self._ui_master(),
                      strong_count=strong_count)

    # -- German reverse flow --------------------------------------------
    def _german_candidate(self, text: str) -> bool:
        """True if `text` is most likely a German noun the plural DB knows.

        Heuristic, because a bare word has no reliable language signal:
          - Strong signal: the word contains a German umlaut/ß.
          - Strong signal: the word is a known German inflected form (verb
            past/participle, declension, plural...) in the kaikki index, e.g.
            'ging', 'gelaufen', 'Händen' — even when lowercase.
          - Strong signal: DWDSmor recognizes the form (real German FST) even
            when the kaikki index misses it (novel inflections, compounds).
          - Strong signal: the word is capitalised *and* is a known German
            noun lemma/plural.
          - Weak/off: lowercase known nouns without umlauts usually resolve to
            a plain English/Polish word and fall through.
        Phrases return False (normal forward lookup / manual edit).
        """
        w = text.strip()
        if not w or " " in w:
            return False
        if any(ch in w for ch in "äöüßÄÖÜẞ"):
            return True
        # A known German inflected form (verb inflection, declension) is a
        # clear German signal independent of case / noun-ness.
        try:
            if self.plural.resolve_form(w) is not None:
                return True
        except Exception:
            pass
        # DWDSmor real-morphology signal: even forms kaikki doesn't know
        # ('grosse', novel compounds) are confidently German.
        try:
            if self.analyzers.available.get("de") and self.analyzers.is_german(w):
                return True
        except Exception:
            pass
        if not self.plural.is_noun(w):
            return False
        if w[:1].isupper():
            # Capitalised & known German noun: almost certainly German.
            return True
        # Lowercase is ambiguous; let the normal dictionary flow decide.
        return False

    def _status(self, msg: str) -> None:
        if self._ui is not None:
            self._ui.status(msg)

    def _ui_master(self):
        return self._ui.root if self._ui is not None else None

    def dictionary_has_polish(self, word: str) -> bool:
        return self.dict.has_exact(word, "pl") and not self.dict.has_exact(word, "en")

    def dictionary_has_english(self, word: str) -> bool:
        return self.dict.has_exact(word, "en")

    # -- add to Anki -----------------------------------------------------
    def on_submit(self, cand) -> None:
        if cand is None:
            self._status("Cancelled.")
            return
        a = self.cfg["anki"]
        try:
            self.anki.version()
        except AnkiConnectError as e:
            self._status(f"ERROR: {e}")
            return
        ensure_deck(self.anki, a["deck"])
        ensure_model(self.anki, a["model"])
        fields = note_fields(cand)
        ok = self.anki.can_add_notes(a["deck"], a["model"], [fields])[0]
        if not ok:
            self._status(f"Duplicate — skipped: {cand.source} -> {cand.word_field}")
            return
        nid = self.anki.add_note(a["deck"], a["model"], fields)
        self._status(f"Added note {nid}: {cand.source} -> {cand.word_field}")


def _once(cfg: dict) -> int:
    """CLI single-shot: print the proposed card(s) for the current clipboard."""
    app = AnkiExtApp(cfg)
    text = read_clipboard().strip()
    if not text:
        print("clipboard empty")
        app.stop()
        return 1
    lang = detect_language(text, cfg["languages"]["polish_diacritics"],
                           dict_hint=app.dictionary_has_polish,
                           dict_hint_en=app.dictionary_has_english,
                           analyzers=app.analyzers)
    cands = build_candidates(text, lang, app.dict, app.plural, app.builder,
                             wikt=app.wikt,
                             max_candidates=app._strong_count(),
                             total_cap=app._total_cap(),
                             analyzers=app.analyzers)
    print(f"{text!r} -> {len(cands)} candidate(s):")
    for c in cands:
        conf = f"{getattr(c, 'confidence', 1.0) * 100:.0f}%"
        print(f"   {c.word_field:25} | plural={c.plural_field:18} | {c.pos or '-'} | {conf}")
    app.stop()
    return 0


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config()
    if "--once" in argv:
        return _once(cfg)
    app = AnkiExtApp(cfg)
    app.start()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))