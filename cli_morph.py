#!/usr/bin/env python3
"""CLI: show the real-morphology engine output for a word (any language).

Usage:
    python cli_morph.py ging              # German via DWDSmor
    python cli_morph.py went en           # English via spaCy
    python cli_morph.py psami pl          # Polish via morfeusz2
    python cli_morph.py grosse --all      # full analysis dump

Prints the lemmatisation + morphosyntactic analysis each engine produced, and
which engines are available.  Engines are optional (see requirements.txt).
"""
from __future__ import annotations

import sys
from pathlib import Path

# allow running from any copied folder without install
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dictlookup.analyzers import Analyzers   # noqa: E402


def main(argv: list[str]) -> int:
    if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    a = Analyzers()
    print("engines:", a.describe())
    if len(argv) < 2:
        print("usage: python cli_morph.py <word> [en|pl|de] [--all]")
        return 1

    word = argv[1]
    lang = argv[2] if len(argv) > 2 and argv[2] in ("en", "pl", "de") else None
    show_all = "--all" in argv

    if lang is None:
        # route: German signal -> de; Polish diacritics -> pl; else en
        if a.is_german(word):
            lang = "de"
        elif any(ch in word for ch in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"):
            lang = "pl"
        else:
            lang = "en"
    print(f"--- {word!r} as {lang} ---")

    if not a.available.get(lang):
        print(f"  engine for {lang!r} not installed — "
              f"pip install {'dwdsmor' if lang == 'de' else ('morfeusz2' if lang == 'pl' else 'spacy en_core_web_sm')}")
        return 1

    analyses = a.analyze(word, lang)
    if not analyses:
        print("  (no analysis — engine installed but word unknown)")
        return 0
    for d in analyses:
        lemma = d.get("lemma", "?")
        pos = d.get("pos", "?")
        extra = "  ".join(f"{k}={v}" for k, v in d.items()
                          if k not in ("word", "lemma", "pos") and v)
        print(f"  lemma={lemma!r:20} pos={pos:10} {extra}")
        if show_all:
            print(f"      full={d}")
    print(f"candidates: {list(a.candidates(word, lang))}")
    if lang == "de":
        print(f"  gender={a.de_gender(word)!r} article={a.de_article(word)!r} "
              f"plural={a.de_plural(word)!r} freq={a.de_freq(word)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))