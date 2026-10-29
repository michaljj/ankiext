"""Idempotent Anki deck/model setup via AnkiConnect."""
from __future__ import annotations

from anki_connect import AnkiConnect

MODEL_FIELDS = ["Word", "Plural", "Source", "SourceLang", "extra"]

MODEL_TEMPLATES = [
    {
        "Name": "Recognition",
        "Front": "{{Word}}{{#Plural}}<br>({{Plural}}){{/Plural}}",
        "Back": "{{FrontSide}}<hr id=answer>{{Source}}{{#extra}}<br><i>{{extra}}</i>{{/extra}}",
    },
    {
        "Name": "Production",
        "Front": "{{Source}}",
        "Back": "{{FrontSide}}<hr id=answer>{{Word}}{{#Plural}}<br>({{Plural}}){{/Plural}}{{#extra}}<br><i>{{extra}}</i>{{/extra}}",
    },
]

MODEL_CSS = """
.card { font-family: Arial; font-size: 20px; text-align: center; color: black; background: white; }
.front { font-weight: bold; }
"""

# Deck/model names verified once per process: the deck and note type don't
# change at runtime, so we avoid a deckNames()/modelNames() round-trip on
# every card submission. Cache key is (host, port, name).
_ensured_decks: set[tuple] = set()
_ensured_models: set[tuple] = set()


def ensure_deck(anki: AnkiConnect, deck: str) -> None:
    key = (anki.base, deck)
    if key in _ensured_decks:
        return
    if deck not in anki.deck_names():
        anki.create_deck(deck)
    _ensured_decks.add(key)


def ensure_model(anki: AnkiConnect, model: str) -> None:
    key = (anki.base, model)
    if key in _ensured_models:
        return
    if model not in anki.model_names():
        anki.create_model(model, MODEL_FIELDS, MODEL_TEMPLATES, css=MODEL_CSS)
    _ensured_models.add(key)


def note_fields(c: "CardCandidate") -> dict[str, str]:
    """Map a CardCandidate to Anki note fields.

    Keys use the exact MODEL_FIELDS casing so every consumer (AnkiConnect,
    cli_cleanup, tests) agrees on the same names.
    """
    return {
        "Word": c.word_field,
        "Plural": c.plural_field,
        "Source": c.source,
        "SourceLang": c.source_lang,
        "extra": c.note,
    }