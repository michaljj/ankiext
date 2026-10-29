#!/usr/bin/env python3
"""Remove test notes created during development from the AnkiExt deck.

Usage:
    python cli_cleanup.py                # dry-run: list what would be deleted
    python cli_cleanup.py --yes          # actually delete them
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anki_connect import AnkiConnect  # noqa: E402
from config import load_config  # noqa: E402


def main(argv) -> int:
    cfg = load_config()
    a = AnkiConnect(cfg["anki"]["host"], cfg["anki"]["port"])
    deck = cfg["anki"]["deck"]
    model = cfg["anki"]["model"]
    if "--all" in argv:
        # delete ALL notes of the AnkiExt model in the deck (all created by dev tests)
        notes = a.find_notes(f'deck:"{deck}" note:"{model}"')
        infos = a.notes_info(notes)
        if not infos:
            print(f"no '{model}' notes in deck '{deck}'")
            return 0
        print(f"found {len(infos)} '{model}' notes in '{deck}':")
        for info in infos:
            f = info.get("fields", {})
            src = f.get("Source", {}).get("value", "")
            word = f.get("Word", {}).get("value", "")
            print(f"  [{info.get('noteId')}]: {src!r} -> {word!r}")
        if "--yes" in argv:
            a._request("deleteNotes", {"notes": [i["noteId"] for i in infos]})
            print(f"\ndeleted {len(infos)} note(s)")
        else:
            print("\n(dry-run — pass --yes to delete)")
        return 0
    # default: tagged test notes only
    notes = a.find_notes(f'deck:"{deck}" tag:anki-ext-test')
    infos = a.notes_info(notes)
    if not infos:
        print(f"no tagged test notes found in deck '{deck}' (dry-run safe)")
    for info in infos:
        f = info.get("fields", {})
        src = f.get("Source", {}).get("value", "")
        word = f.get("Word", {}).get("value", "")
        print(f"  would delete [{info.get('noteId')}]: {src!r} -> {word!r}")
    if "--yes" in argv and infos:
        a._request("deleteNotes", {"notes": [i["noteId"] for i in infos]})
        print(f"\ndeleted {len(infos)} note(s)")
    elif infos:
        print("\n(dry-run — pass --yes to delete)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))