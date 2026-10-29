"""Unified morphology layer: real lemmatisation for EN / PL / DE.

One lazy facade over the three optional engines, with the old heuristic
morphology as an exact-behavior fallback:

    EN -> spaCy (en_core_web_sm):   went->go VERB VBD, children->child ...
    PL -> morfeusz2:                psami->pies, lepszym->dobry:A, biec ...
    DE -> DWDSmor (FST):            ging->gehen V, Hunden->Hund NN ...

Every engine is optional: if its package or model is missing, `available[lang]`
is False and `candidates()` degrades to the existing suffix-rule / irregular-
table logic from `morphology.py`, so a machine without any of these keeps the
app's current behavior byte-for-byte.  Loading is lazy and guarded (spaCy's
model takes a couple of seconds on first use; the DWDSmor automata likewise).
All results are cached.
"""
from __future__ import annotations

import functools
import threading
import types
import unicodedata
from typing import Callable, Optional

from .morphology import (nfc,
                         candidates as _heuristic_candidates,
                         english_candidates as _heuristic_en)

_GENDER_MAP = {"Masc": "m", "Fem": "f", "Neut": "n", "UnmGend": ""}
_ARTICLE = {"m": "der", "f": "die", "n": "das"}


def _frozen(inner) -> tuple:
    """Read-only view of analysis dicts so the lru_cache can't be poisoned."""
    return tuple(types.MappingProxyType(dict(d)) for d in inner)


# spaCy morphologizer keys we keep (sparse, useful for confidence/labels)
_SPACY_MORPH_KEYS = ("Tense", "Number", "Degree", "VerbForm", "Person", "Gender", "Case")

# English comparatives spaCy mislemmatises for a dictionary lookup
# ("better" -> ADV "well"): keep our table as an extra candidate.
_EN_OVERRIDES_LEMMA = {"better": "good", "best": "good", "worse": "bad", "worst": "bad"}

_PL_TAG_POS = {
    "subst": "noun", "depr": "noun", "ger": "noun",
    "verb": "verb", "fin": "verb", "winien": "verb", "pact": "verb", "ppas": "verb",
    "inf": "verb", "bedzie": "verb", "aglt": "verb",
    "praet": "verb", "imps": "verb", "pant": "verb", "pcon": "verb",
    "adj": "adjective", "adja": "adjective", "adjp": "adjective", "adjc": "adjective",
    "adv": "adverb",
    "prep": "preposition",
    "ppron": "pronoun", "pron": "pronoun", "siebie": "pronoun",
    "num": "numeral",
    "conj": "conjunction",
    "interj": "interjection",
    "part": "particle",
    "burk": "other",
    "xxx": "other",
}


class Analyzers:
    """Lazy per-language morphology engines behind one small API."""

    def __init__(self, cfg_morphology: dict | None = None):
        cfg = cfg_morphology or {}
        self.enable_en = bool(cfg.get("en_spacy", True))
        self.enable_pl = bool(cfg.get("pl_morfeusz", True))
        self.enable_de = bool(cfg.get("dwdsmor", True))
        self.spacy_model = cfg.get("spacy_model", "en_core_web_sm")
        self.automata_dir = cfg.get("automata_dir", "")
        self.freq_enabled = bool(cfg.get("freq_rank", True))

        # lazy handles (set on first use, guarded by _lock)
        self._nlp = None        # spaCy pipeline
        self._morfeusz = None   # Morfeusz instance
        self._dwdsmor = None    # DwdsmorMorph

        # availability probes: cheap import checks up front, AND the config
        # enable flags actually gate them (so dwdsmor=false etc. disengages
        # the engine completely, not just adds latency).
        self.available: dict[str, bool] = {"en": False, "pl": False, "de": False}
        if self.enable_en:
            try:
                import spacy  # noqa: F401
                self.available["en"] = True
            except Exception:
                pass
        if self.enable_pl:
            try:
                import morfeusz2  # noqa: F401
                self.available["pl"] = True
            except Exception:
                pass
        if self.enable_de:
            try:
                import dwdsmor  # noqa: F401
                self.available["de"] = True
            except Exception:
                pass
        self._lock = threading.Lock()

    # -- lazy accessors -------------------------------------------------
    def _ensure_en(self):
        if self._nlp is not None or not self.available["en"]:
            return self._nlp
        with self._lock:
            if self._nlp is None and self.available["en"]:
                try:
                    import spacy
                    self._nlp = spacy.load(self.spacy_model)
                except Exception:
                    self.available["en"] = False
        return self._nlp

    def _ensure_pl(self):
        if self._morfeusz is not None or not self.available["pl"]:
            return self._morfeusz
        with self._lock:
            if self._morfeusz is None and self.available["pl"]:
                try:
                    import morfeusz2
                    self._morfeusz = morfeusz2.Morfeusz(generate=False)
                except Exception:
                    self.available["pl"] = False
        return self._morfeusz

    def _ensure_de(self):
        if self._dwdsmor is not None:
            return self._dwdsmor
        with self._lock:
            if self._dwdsmor is None and self.available["de"]:
                from german.dwdsmor import DwdsmorMorph
                self._dwdsmor = DwdsmorMorph(self.automata_dir)
        return self._dwdsmor

    # -- per-language candidate lemmas ---------------------------------
    @functools.lru_cache(maxsize=8192)
    def analyze(self, word: str, lang: str) -> tuple:
        """Analyses of `word` for `lang`; each is a dict (see engines).

        Returns a tuple of read-only (MappingProxyType) dicts (cached), each
        with at least 'lemma' and 'pos'; engine details vary.  Input is
        NFC-normalized so composed/decomposed forms hit the same cache entry
        and the engines see canonical text.
        """
        word = nfc((word or "").strip())
        if not word:
            return ()
        if lang == "de":
            m = self._ensure_de()
            if m is not None and m.available:
                return _frozen(m.analyze(word))
            return ()
        if lang == "pl":
            m = self._ensure_pl()
            if m is not None:
                try:
                    return _frozen(self._pl_analyses(m, word))
                except Exception:
                    return ()
            return ()
        # default: english
        nlp = self._ensure_en()
        if nlp is not None:
            try:
                return _frozen(self._en_analyses(nlp, word))
            except Exception:
                return ()
        return ()

    @staticmethod
    def _en_analyses(nlp, word: str):
        doc = nlp(word)
        # whole-token only: 'New York' -> 'New' would be a bogus lemma
        if len(doc) != 1 or doc[0].text.casefold() != word.casefold():
            return []
        t = doc[0]
        morph = {}
        for k, v in t.morph.to_dict().items():
            if k in _SPACY_MORPH_KEYS:
                morph[k] = v
        out = [{"lemma": t.lemma_, "pos": t.pos_.lower(), "tag": t.tag_, "morph": morph}]
        # supplement: our irregular/override table (better->good etc.)
        lw = word.casefold()
        if lw in _EN_OVERRIDES_LEMMA and _EN_OVERRIDES_LEMMA[lw] != t.lemma_:
            out.append({"lemma": _EN_OVERRIDES_LEMMA[lw], "pos": "adj", "tag": "", "morph": {}})
        return out

    @staticmethod
    def _pl_analyses(m, word: str):
        out = []
        seen = set()
        lw = word.casefold()
        if any(ch.isspace() for ch in word):
            return []  # single-word API: multi-token input has no whole-token reading
        rows = list(m.analyse(word))
        # morfeusz2 row: (start, end, (orth, lemma_tag, tag_str, interps, quals)).
        # Walk rows into analysis paths: output is listed per span in order,
        # so a new path begins whenever `start` stops strictly increasing
        # (an alternative reading at the same span, or the next token).
        groups: list[list] = []
        cur: list = []
        prev = None
        for row in rows:
            start = row[0]
            if prev is not None and start <= prev:
                groups.append(cur)
                cur = []
            cur.append(row)
            prev = start
        if cur:
            groups.append(cur)
        for group in groups:
            if not group:
                continue
            joined = "".join(r[2][0] for r in group)
            if joined.casefold() != lw:
                continue  # covers only part of the token (or several tokens)
            first = group[0][2]
            lemma = first[1].split(":")[0] if ":" in first[1] else first[1]
            base_tag = first[2].split(":")[0]
            pos = _PL_TAG_POS.get(base_tag, "other")
            merged_tag, person = first[2], None
            if len(group) > 1:
                # Fold the movable personal ending (aglt: -m/-ś/-śmy/-ście)
                # into the tag: its person code (pri/sec/ter) sits at index 2.
                for row in group[1:]:
                    tag = row[2][2]
                    if tag.split(":")[0] == "aglt":
                        parts = tag.split(":")
                        if len(parts) > 2 and parts[2]:
                            person = parts[2]
                if person and person not in merged_tag:
                    merged_tag = f"{merged_tag}:{person}"
            key = (lemma.casefold(), pos)
            if key in seen:
                continue
            seen.add(key)
            morph = {"tag": merged_tag}
            if person:
                morph["person"] = person
            out.append({"lemma": lemma, "pos": pos, "tag": merged_tag, "morph": morph})
            if len(out) >= 5:
                break
        return out

    @functools.lru_cache(maxsize=8192)
    def candidates(self, word: str, lang: str) -> tuple:
        """Plausible lemma candidates for `word` in `lang` (dedup, max 6).

        Validated against the dictionary index by the caller before use.
        Falls back to the heuristic morphology when an engine is absent or
        returns nothing (the heuristic path is returned uncapped, exactly as
        the standalone morphology would).
        """
        word = nfc((word or "").strip())
        if not word:
            return ()
        out: list[str] = []
        for a in self.analyze(word, lang):
            lemma = (a.get("lemma") or "").strip()
            if lemma and lemma.casefold() != word.casefold() and lemma not in out:
                out.append(lemma)
        if not out:
            # engine missing/unhelpful -> old heuristic path (exact behavior)
            return tuple(_heuristic_candidates(word, lang))
        return tuple(out[:6])

    def lemma_of(self, word: str, lang: str) -> Optional[str]:
        """Best single lemma, or None."""
        word = nfc((word or "").strip())
        if not word:
            return None
        for c in self.candidates(word, lang):
            return c
        return None

    # -- German-specific helpers ----------------------------------------
    def is_german(self, word: str) -> bool:
        """True if DWDSmor recognizes `word` as German (any analysis)."""
        if not isinstance(word, str) or not (word or "").strip():
            return False
        m = self._ensure_de()
        if m is None or not m.available:
            return False
        return bool(m.is_german(word))

    def de_gender(self, lemma: str) -> Optional[str]:
        if not isinstance(lemma, str) or not (lemma or "").strip():
            return None
        m = self._ensure_de()
        if m is None or not m.available:
            return None
        return m.gender_of(lemma)

    def de_article(self, lemma: str) -> str:
        if not isinstance(lemma, str) or not (lemma or "").strip():
            return ""
        m = self._ensure_de()
        if m is None or not m.available:
            return ""
        return m.article_of(lemma)

    def de_plural(self, lemma: str) -> Optional[str]:
        """Best-effort FST plural (None when generation is unreliable)."""
        if not isinstance(lemma, str) or not (lemma or "").strip():
            return None
        m = self._ensure_de()
        if m is None or not m.available:
            return None
        return m.plural_of(lemma)

    def de_freq(self, lemma: str) -> Optional[float]:
        if not isinstance(lemma, str) or not (lemma or "").strip():
            return None
        m = self._ensure_de()
        if m is None or not m.available or not self.freq_enabled:
            return None
        return m.freq(lemma)

    # -- convenience -----------------------------------------------------
    def describe(self) -> dict:
        """Engine availability for the CLI / status line."""
        return {
            "en": "spacy" if self.available["en"] else "heuristics",
            "pl": "morfeusz2" if self.available["pl"] else "heuristics",
            "de": "dwdsmor" if self.available["de"] else "kaikki/heuristics",
        }


# keep a module-level alias used by matcher to keep call sites short
def make_analyzers(cfg_morphology: dict | None = None) -> Analyzers:
    return Analyzers(cfg_morphology)