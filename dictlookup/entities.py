"""HTML entity decoding and gender-marker handling for dict.cc files.

dict.cc formats:
  - Lines are tab-separated:  source \t target \t pos \t [subject tags]
  - `#` prefix = header/comment
  - German nouns carry gender markers embedded in the term:  `Haus {n} [Gebäude]`,
    `(der) Hund {m}`, `Auto {n} <Autos>` (the <...> is an abbreviation/alt, not plural)
  - HTML entities appear: `&#945;-Keratin {n}` == "α-Keratin"
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Optional

# Gender markers: {m} masculine, {f} feminine, {n} neuter; occasionally "{m} {f}" (variable)
_GENDER_RE = re.compile(r"\{([mnf])\}")
# Any {braced} notation (gender, {sg}, {pl}, {Akk.} ...)
_BRACE_RE = re.compile(r"\{[^}]*\}")
# Bracket annotations not part of the word: [Gebäude], [ugs.], [zool.] ...
_BRACKET_RE = re.compile(r"\[[^]]*\]")
# Angle-bracket abbreviations: <Autos>, <Gew.-%> (NOT plurals)
_ANGLE_RE = re.compile(r"<[^>]*>")
# Leading parenthetical article hint: (der), (das), (die)
_LEADING_ART_RE = re.compile(r"^\(\s*(?:der|die|das)\s*\)\s*")

GENDER_TO_ARTICLE = {
    "m": "der",
    "f": "die",
    "n": "das",
}
PLURAL_ARTICLE = "die"  # nominative plural article is always "die" in German


@dataclass
class GenderInfo:
    """Extracted gender marker(s) from a German term."""

    genders: list = field(default_factory=list)  # e.g. ["m"], ["m","f"], ["n"]
    article: str = ""  # "der"/"die"/"das"/"der/die" for variable gender


def _dedup(seq):
    seen = []
    for x in seq:
        if x not in seen:
            seen.append(x)
    return seen


def decode_html(text: str) -> str:
    """Decode HTML entities (&amp;, &#945;, &nbsp; ...) to real characters."""
    return html.unescape(text) if text else text


def extract_gender(term: str) -> tuple[str, GenderInfo]:
    """Extract gender marker(s) + article from a German term.

    Returns (cleaned_term, GenderInfo).  Gender markers like "{m}" are removed
    from the term; article ("der"/"die"/"das" or "der/die" for mixed) is filled.
    Brackets, angle abbreviations and HTML entities are stripped from the term.
    """
    term = decode_html(term)
    genders: list = []
    for m in _GENDER_RE.finditer(term):
        g = m.group(1)
        if g not in genders:
            genders.append(g)
    # "{pl}"-only nouns get the "die" article; record them as "pl" pseudo-gender
    if not genders and re.search(r"\{pl\}", term):
        genders.append("pl")

    info = GenderInfo(genders=genders)
    if genders:
        arts = []
        for g in genders:
            if g == "pl":
                a = "die"
            else:
                a = GENDER_TO_ARTICLE.get(g, "")
            if a and a not in arts:
                arts.append(a)
        info.article = "/".join(arts) if len(arts) > 1 else (arts[0] if arts else "")

    cleaned = _BRACE_RE.sub(" ", term)
    cleaned = _BRACKET_RE.sub(" ", cleaned)
    cleaned = _ANGLE_RE.sub(" ", cleaned)
    cleaned = _LEADING_ART_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, info


def clean_term(term: str) -> str:
    """Full cleanup pipeline for a dictionary term (either language side)."""
    term = decode_html(term)
    term = _LEADING_ART_RE.sub("", term)
    term = _BRACKET_RE.sub(" ", term)
    term = _ANGLE_RE.sub(" ", term)
    term = _BRACE_RE.sub(" ", term)
    term = re.sub(r"\s+", " ", term).strip()
    return term


def split_line(line: str) -> tuple[str, str, str, str]:
    """Split a dict.cc line into (source, target, pos, tags).

    Header lines (starting with '#') return pos='' and tags=''.
    """
    if line.startswith("#"):
        return "", "", "", ""
    parts = line.rstrip("\n").split("\t")
    source = parts[0].strip() if len(parts) > 0 else ""
    target = parts[1].strip() if len(parts) > 1 else ""
    pos = parts[2].strip() if len(parts) > 2 else ""
    tags = parts[3].strip() if len(parts) > 3 else ""
    return source, target, pos, tags