"""Language detection for captured selection text (PL vs EN)."""
from __future__ import annotations

import re

POLISH_DIACRITICS = "ąćęłńóśźż"


def detect_language(text: str, polish_diacritics: str = POLISH_DIACRITICS,
                    dict_hint=None, analyzers=None, dict_hint_en=None) -> str:
    """Return 'pl' or 'en' for a selected text.

    Heuristic (fast, no model), with optional real-morphology analysis:
      1. Polish diacritics (ą ę ł ń ś ź ż ó) -> pl.
      2. Polish stopword / verb-infinitive signals -> pl.
      3. Dictionary hint for bare words: unambiguous PL exact hit (and no
         English exact) -> pl.
      4. morfeusz2 boost -> pl — ONLY when the word has no English exact
         match (morfeusz2's lexicon contains English borrowings like
         'house'/'film', so raw analysis is a false-positive machine).
      5. Else -> en.
    """
    if not text:
        return "en"
    t = text.strip()
    for ch in t:
        if ch in polish_diacritics:
            return "pl"
    # stopword check on lowercased words.
    # Only tokens that are unambiguously Polish are used; bare words that
    # collide with English/German ("w","z","to","do","na",...) are excluded so
    # a lone English "to" isn't misdetected as Polish. Bare-word disambiguation
    # is left to the dict_hint (PL-DE exact hit) path below.
    words = re.findall(r"[\w']+", t.lower())
    if not words:
        return "en"
    strong_pl = {"się", "nie", "jest", "jestem", "był", "była", "byli", "były",
                 "mam", "masz", "mają", "mamy", "przez", "który", "która",
                 "które", "którego", "tego", "tej", "tym", "został", "została",
                 "będzie", "będą", "dla"}   # unambiguous Polish-only signals
    hits = sum(1 for w in words if w in strong_pl)
    verb_hits = sum(1 for w in words if w.endswith(("ać", "eć", "ić", "yć")))
    if hits >= 1 or verb_hits >= 1:
        return "pl"
    # dictionary hint for bare words (single token with no strong signals)
    if dict_hint is not None and len(words) == 1:
        w = words[0]
        if dict_hint(w):
            return "pl"
    # real-morphology boost: a Polish surface recognized by morfeusz2 is Polish
    # — but only when the word is NOT an exact English dictionary word
    # (borrowings like 'house'/'film'/'go' would be misflagged Polish).
    if analyzers is not None and analyzers.available.get("pl") and len(words) == 1:
        w = words[0]
        if dict_hint_en is not None and dict_hint_en(w):
            return "en"
        if analyzers.analyze(w, "pl"):
            return "pl"
    return "en"