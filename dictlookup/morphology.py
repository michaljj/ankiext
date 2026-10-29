"""Lightweight, offline morphological normalization for matching.

This is NOT a full part-of-speech lemmatizer.  It is a small deterministic
word-form reducer used to generate *plausible canonical candidates* for a
source term so the dictionary search can resolve inflected forms (plurals,
past tense, present -s, -ing, comparatives) back to the lexeme actually
present in the bilingual index.  Candidates are additionally validated against
the target index by the caller before they reach a card.

Languages:
  - en: English suffix rules + a small irregular table.
  - pl: conservative noun-ending stripping (accepted only if it indexes).
  - de: wired to the kaikki inflected-form index (german.plural), not rules.
"""
from __future__ import annotations

import unicodedata

# Common English irregulars: surface form -> base lexeme.  Deliberately small
# and safe -- a suffix rule may also be tried, and the final candidate must
# exist in the bilingual index to be used.
_IRREGULAR_EN: dict[str, str] = {
    # irregular plurals
    "children": "child", "geese": "goose", "men": "man", "women": "woman",
    "mice": "mouse", "teeth": "tooth", "feet": "foot", "people": "person",
    "oxen": "ox", "cacti": "cactus", "data": "datum",
    # irregular verbs -> base
    "went": "go", "gone": "go", "goes": "go",
    "did": "do", "done": "do", "does": "do",
    "had": "have", "has": "have",
    "was": "be", "were": "be", "been": "be", "is": "be",
    "saw": "see", "seen": "see",
    "took": "take", "taken": "take",
    "bought": "buy", "brought": "bring", "thought": "think",
    "made": "make", "making": "make",
    "ran": "run", "running": "run",
    "caught": "catch", "taught": "teach", "built": "build",
    "felt": "feel", "fell": "fall", "grown": "grow", "grew": "grow",
    "found": "find", "gave": "give", "given": "give", "got": "get",
    "wrote": "write", "written": "write", "spoke": "speak", "spoken": "speak",
    "began": "begin", "begun": "begin", "drank": "drink", "drove": "drive",
    "ate": "eat", "eaten": "eat", "fought": "fight", "flew": "fly",
    "flown": "fly", "sang": "sing", "sung": "sing", "sold": "sell",
    "sent": "send",
    # comparatives / superlatives
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
    "more": "much", "most": "much", "less": "little", "least": "little",
}

# English suffix rules, longest first.  value may be a str (replacement) or a
# tuple of alternative replacements; each is produced and validated later.
_EN_SUFFIX_RULES: tuple[tuple[str, object], ...] = (
    ("ing", ("", "e")),   # sing->sing, making->make
    ("ies", "y"),         # studies->study, flies->fly
    ("ied", "y"),         # studied->study
    ("ed", ("", "")),     # used->use, studied->study (also covered above)
    ("es", ""),           # houses->house, goes->go
    ("s", ""),            # dogs->dog
    ("er", ""),
    ("est", ""),
)

# Common terminal sequences we should NOT blindly stem (Latin/Greek etc.)
_SKIP_TS = ("ss", "us", "is", "os", "as", "ics")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _english_forms(word: str) -> list[str]:
    """Return plausible base candidates for an English surface form."""
    out: list[str] = []
    lw = word.casefold()
    if lw in _IRREGULAR_EN:
        out.append(_IRREGULAR_EN[lw])

    w = word
    if not w or len(w) < 3:
        # don't even try declensional suffixes on tiny tokens
        return _unique(out)

    for suffix, repl in _EN_SUFFIX_RULES:
        if not w.endswith(suffix):
            continue
        base = w[: -len(suffix)]
        if not base or len(base) < 2:
            continue
        if isinstance(repl, str):
            cand = _apply_candidate(base, repl)
            if cand and _valid_candidate(cand):
                out.append(cand)
        else:
            for alt in repl:
                cand = _apply_candidate(base, alt)
                if cand and _valid_candidate(cand):
                    out.append(cand)

    return _unique(out)


def _apply_candidate(base: str, repl: str) -> str:
    """Apply a replacement: '' drops fully (children→child handled via table);
    'y' appends y (studies→study); 'e' appends e (making→make)."""
    if repl == "":
        return base
    if repl == "e":
        return base + "e"
    if repl == "y":
        return base + "y"
    return base + repl


def _valid_candidate(c: str) -> bool:
    if len(c) < 2:
        return False
    if len(c) == 2 and c[-1] in ("y", "e", "s"):
        # "re"/"ly" etc. are often false endings; still surface but the caller
        # will reject them if they don't index.
        pass
    return True


def _unique(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for x in seq:
        k = x.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def english_candidates(word: str) -> list[str]:
    """Public: English base-form candidates (validated downstream)."""
    word = nfc(word or "")
    return _english_forms(word)


def polish_candidates(word: str) -> list[str]:
    """Conservative Polish noun/verb-ending candidates.

    Polish morphology is highly declensional; we only strip the most common
    noun case endings and ONLY when the caller confirms the result indexes.
    """
    w = nfc(word or "").casefold()
    if not w or len(w) < 4:
        return []
    out = []
    for suff in ("ów", "ów", "um", "em", "am", "im", "i", "y", "a", "u", "e", "o"):
        if w.endswith(suff):
            base = w[: -len(suff)]
            if len(base) >= 3:
                out.append(base)
    return _unique(out)


def german_candidates(word: str) -> list[str]:
    """German forms come from the kaikki index (german.py), not suffix rules.

    This is a hook for morphology symmetry; the actual resolution lives in
    PluralDB.resolve_form and is handled by the matcher before this is
    consulted.  Kept here so callers can degrade gracefully with an empty list.
    """
    return []


def candidates(word: str, lang: str | None) -> list[str]:
    """Dispatch to language-specific candidate generators.

    `lang` is the SOURCE language of the dictionary side being searched
    ('en'|'pl'|'de').  German resolved upstream; this returns only generic
    candidates for en/pl.
    """
    if lang == "pl":
        return _unique(polish_candidates(word) + english_candidates(word))
    if lang == "de":
        return german_candidates(word)
    return english_candidates(word)