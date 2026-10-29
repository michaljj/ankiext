"""German grammar extraction from kaikki Wiktionary entries.

The kaikki German extract (de-extract.jsonl.gz) contains, per German lemma,
its part of speech, gender tags, and inflection forms.  For nouns the
nominative-singular form carries the article verbatim:
  {"form": "Haus",  "tags": ["nominative", "singular"], "article": "das"}
  {"form": "Häuser","tags": ["nominative", "plural"],   "article": "die"}
We use that to answer:  lemma -> (article, gender, plural, plural_article).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class GermanNoun:
    """Grammar info for one German noun lemma."""

    lemma: str
    pos: str = "noun"
    gender: str = ""            # "m" | "f" | "n" | "m|f" | "pl" | ""
    article: str = ""           # "der" | "die" | "das" | "" (derived from gender if missing)
    plural: str = ""            # plural form (e.g. "Häuser") or "" if unknown/uncountable
    plural_article: str = ""    # "die" when plural found
    has_plural: bool = False    # False if no nominative-plural form found


GENDER_ARTICLE = {"m": "der", "f": "die", "n": "das"}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def _gender_from_tags(tags: list) -> str:
    """tags like ['neuter'] / ['masculine'] / ['feminine'] / ['masculine','feminine']."""
    genders = []
    for t in tags or []:
        t = (t or "").lower()
        if t in ("masculine", "m"):
            g = "m"
        elif t in ("feminine", "f"):
            g = "f"
        elif t in ("neuter", "n"):
            g = "n"
        else:
            continue
        if g not in genders:
            genders.append(g)
    if not genders:
        return ""
    return "|".join(genders) if len(genders) > 1 else genders[0]


def extract_noun(entry: dict) -> GermanNoun | None:
    """Extract grammar info from a kaikki entry dict (assumed German, noun)."""
    word = normalize(entry.get("word", ""))
    if not word:
        return None
    tags = entry.get("tags") or []
    gender = _gender_from_tags(tags)

    # walk forms for nominative singular/plural with article
    plural = ""
    plural_article = ""
    nom_sg_article = ""
    for f in entry.get("forms") or []:
        ftags = f.get("tags") or []
        if "nominative" not in ftags:
            continue
        if "plural" in ftags:
            plural = normalize(f.get("form", ""))
            plural_article = f.get("article", "") or "die"
        elif "singular" in ftags:
            sg_art = f.get("article", "")
            if sg_art and not nom_sg_article:
                nom_sg_article = sg_art

    # If no singular article came from forms, fall back to gender mapping
    article = nom_sg_article or GENDER_ARTICLE.get(gender, "")

    return GermanNoun(
        lemma=word,
        gender=gender,
        article=article,
        plural=plural,
        plural_article=plural_article or ("die" if plural else ""),
        has_plural=bool(plural),
    )