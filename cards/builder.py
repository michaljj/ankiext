"""Card building: merge dict.cc hits + German plural DB into Anki note fields."""
from __future__ import annotations

from dataclasses import dataclass, field

from dictlookup.lookup import TranslationHit
from german.plural import PluralDB


@dataclass
class CardCandidate:
    """A single card proposal (one German translation + grammar)."""

    source: str                 # "pies" / "dog"
    source_lang: str            # "pl" / "en"
    german: str                 # "Hund"
    gender: str = ""            # "m" / "f" / "n" / "m|f"
    article: str = ""           # "der"
    plural: str = ""            # "Hunde"
    plural_article: str = ""    # "die"
    pos: str = ""
    tags: str = ""
    note: str = ""              # gloss / extra (may be filled by UI)
    confidence: float = 1.0     # 0..1 source-side match certainty
    method: str = "exact"       # matcher method tag (exact/lemma/stem/prefix/fuzzy)

    @property
    def word_field(self) -> str:
        """German side with article: 'der Hund' (no double article)."""
        g = (self.german or "").strip()
        if not g:
            return ""
        if self.article and "/" not in self.article:
            # avoid 'der der Hund' if article already embedded by the user
            if g.startswith(self.article + " "):
                return g
            return f"{self.article} {g}"
        return g

    @property
    def plural_field(self) -> str:
        if self.plural:
            pa = self.plural_article or "die"
            return f"{pa} {self.plural}"
        return ""

    @property
    def gender_letter(self) -> str:
        """Single-letter gender for display/debug: m/f/n."""
        return (self.gender or "").split("|")[0]


def rank_candidate(c) -> tuple:
    """Rank a CardCandidate: single-word nouns with article+plural first."""
    is_noun = c.pos == "noun"
    has_art = bool(c.article and "/" not in c.article)
    has_pl = bool(c.plural)
    single = " " not in (c.german or "").strip()
    return (0 if is_noun and has_art and has_pl and single else
            1 if is_noun and has_art and has_pl else
            2 if is_noun and has_art else
            3 if is_noun else 4)


class CardBuilder:
    def __init__(self, plural_db: PluralDB | None = None):
        self.plural_db = plural_db

    def enrich(self, hit: TranslationHit, source_lang: str) -> CardCandidate:
        """Merge a dict.cc hit with plural DB grammar."""
        cand = CardCandidate(
            source=hit.source or hit.source_raw,
            source_lang=source_lang,
            german=hit.german,
            gender="",
            article=hit.article,
            pos=hit.pos,
            tags=hit.tags,
            confidence=getattr(hit, "confidence", 1.0),
            method=getattr(hit, "method", "exact"),
        )
        # plural DB is authoritative for gender/article/plural when it knows the lemma
        if self.plural_db is not None and hit.german:
            info = self.plural_db.lookup(hit.german)
            if info:
                cand.gender = info.get("gender", "")
                if not cand.article:
                    cand.article = info.get("article", "")
                cand.plural = info.get("plural", "")
                cand.plural_article = info.get("plural_article", "")
        return cand

    def enrich_many(self, hits: list[TranslationHit], source_lang: str) -> list[CardCandidate]:
        cands = [self.enrich(h, source_lang) for h in hits]
        return sorted(cands, key=rank_candidate)