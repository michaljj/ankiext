#!/usr/bin/env python3
"""CLI for the dict.cc lookup engine — shows real-morphology matches.

Usage:
    python cli_lookup.py house            # auto-detect language
    python cli_lookup.py house en
    python cli_lookup.py pies pl
    python cli_lookup.py strasse          # orthographic variant (straße)
    python cli_lookup.py Huas             # fuzzy (Damerau-Levenshtein -> Haus)
    python cli_lookup.py went             # spaCy lemma -> go
    python cli_lookup.py psami pl         # morfeusz2 -> pies -> der Hund

Displays each candidate with its matching method / confidence.  The optional
real-morphology engines (spaCy / morfeusz2 / DWDSmor) are used automatically
when installed; otherwise it falls back to the built-in heuristics.
"""
from __future__ import annotations

import sys
from pathlib import Path

# allow running from any copied folder without install
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dictlookup.analyzers import Analyzers
from dictlookup.lookup import Dictionary
from german.plural import PluralDB
from cards.builder import CardBuilder
from engine import build_candidates
from config import load_config


def main(argv: list[str]) -> int:
    cfg = load_config()
    plural = PluralDB(cfg["dictionary"]["plural_db"])
    an = Analyzers(cfg.get("morphology"))
    d = Dictionary(cfg, resolve_form=plural.resolve_form, analyzers=an)
    builder = CardBuilder(plural)

    word = argv[1] if len(argv) > 1 else "house"
    lang = argv[2] if len(argv) > 2 else "auto"
    if lang == "auto":
        lang = "pl" if any(ch in word for ch in cfg["languages"]["polish_diacritics"]) else "en"

    cands = build_candidates(word, lang, d, plural, builder, wikt=None,
                             max_candidates=5, total_cap=12, analyzers=an)
    print(f"--- {word!r} ({lang}) via {an.describe()['en']}/{an.describe()['pl']}/{an.describe()['de']} ---")
    if not cands:
        print("  (no match)")
    for c in cands[:10]:
        conf = f"{getattr(c, 'confidence', 1.0) * 100:.0f}%"
        method = getattr(c, "method", "")
        print(f"  {c.word_field:28} | plural={c.plural_field:18} | "
              f"{c.source!r:14} [{method}, {conf}]")
    d.close()
    plural.close()
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))