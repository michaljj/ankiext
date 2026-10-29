#!/usr/bin/env python3
"""Phase 3 smoke test: dict.cc lookup + plural DB + AnkiConnect addNote.

Adds a small set of cards to the configured deck in the running Anki
(dedup via canAddNotes; idempotent).  Requires Anki + AnkiConnect.

Usage:  python cli_anki_smoke.py [--word WORD --lang en|pl ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anki_connect import AnkiConnect, AnkiConnectError  # noqa: E402
from cards.anki_setup import ensure_deck, ensure_model, note_fields  # noqa: E402
from cards.builder import CardBuilder  # noqa: E402
from config import load_config  # noqa: E402
from dictlookup.lookup import Dictionary  # noqa: E402
from german.plural import PluralDB  # noqa: E402


def main(argv: list[str]) -> int:
    args = _parse(argv)
    cfg = load_config()
    dic = cfg["dictionary"]
    anki_cfg = cfg["anki"]

    d = Dictionary(cfg)
    pdb = PluralDB(dic["plural_db"])

    if args.dry_run and not args.word:
        print("dry-run: no words; use --word to test")
        return 0

    words = []
    if args.word:
        words.append((args.word, args.lang))
    else:
        words = [("house", "en"), ("dog", "en"), ("pies", "pl"), ("kot", "pl")]

    builder = CardBuilder(pdb)
    all_candidates = []
    for w, lang in words:
        hits = d.lookup(w, lang=lang, limit=8)
        cands = builder.enrich_many(hits, lang)
        all_candidates.extend(cands)
        print(f"--- {w!r} ({lang}) -> {len(cands)} candidate(s)")
        for c in cands[:5]:
            print(f"   {c.word_field:20} | plural={c.plural_field:15} | {c.pos or '-'}")

    if args.dry_run:
        print("\n(dry-run: no Anki changes)")
        return 0

    a = AnkiConnect(anki_cfg["host"], anki_cfg["port"])
    try:
        ver = a.version()
        print(f"\nAnkiConnect OK (version {ver})")
    except AnkiConnectError as e:
        print(f"ERROR: {e}")
        return 1

    ensure_deck(a, anki_cfg["deck"])
    ensure_model(a, anki_cfg["model"])
    print(f"deck '{anki_cfg['deck']}' + model '{anki_cfg['model']}' ensured")

    # dedupe with canAddNotes — skip already-present
    fields = [note_fields(c) for c in all_candidates]
    can_add = a.can_add_notes(anki_cfg["deck"], anki_cfg["model"], fields)
    added = 0
    test_tag = ["anki-ext-test"]
    for c, ok in zip(all_candidates, can_add):
        if not ok:
            print(f"   skip (duplicate): {c.source} -> {c.word_field}")
            continue
        nid = a.add_note(anki_cfg["deck"], anki_cfg["model"], note_fields(c), tags=test_tag)
        added += 1
        print(f"   added note {nid}: {c.source} -> {c.word_field} | {c.plural_field}")
    print(f"\nAdded {added} note(s).")
    return 0


def _parse(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--word", default=None)
    p.add_argument("--lang", default="auto", choices=["en", "pl", "auto"])
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv[1:])


if __name__ == "__main__":
    if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))