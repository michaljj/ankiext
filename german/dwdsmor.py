"""DWDSmor adapter: real German morphology (FST) as an optional layer.

Wraps the `dwdsmor` PyPI package (open edition; GPL-2.0) so AnkiExt gets
genuine lemmatisation and morphosyntactic analysis for German:

    ging      -> gehen        V
    Hunden    -> Hund         NN Masc Dat Pl
    grosse    -> groß         ADJ  (grammar-normalized)

Every public method fails soft: if `dwdsmor`/`sfst_transduce` is not
installed, or an automaton is missing, the adapter reports `available=False`
and returns None/[] so callers keep their current behavior exactly.  Loading
is lazy (the automata take a moment to load) and guarded by a lock; all
traversals are read-only after load.
"""
from __future__ import annotations

import functools
import threading
from typing import Optional

# POS tag -> coarse category used by the card engine (noun/verb/adjective/...)
_POS_MAP = {
    "V": "verb",
    "NN": "noun",
    "NPROP": "noun",
    "ADJ": "adjective",
    "ADV": "adverb",
    "ART": "determiner",
    "CONJ": "conjunction",
    "PREP": "preposition",
    "POSS": "determiner",
    "PPRO": "pronoun",
    "PROADV": "adverb",
    "PTCL": "particle",
    "CARD": "numeral",
    "ORD": "numeral",
    "FRAC": "numeral",
    "DEM": "determiner",
    "INDEF": "determiner",
    "REL": "pronoun",
    "WPRO": "pronoun",
    "INTJ": "interjection",
    "PUNCT": "punctuation",
    "PREPART": "particle",
    "POSTP": "postposition",
}

_GENDER_MAP = {"Masc": "m", "Fem": "f", "Neut": "n", "UnmGend": ""}
_ARTICLE = {"m": "der", "f": "die", "n": "das"}


class DwdsmorMorph:
    """Lazy, optional wrapper around the dwdsmor Python library."""

    def __init__(self, automata_dir: str = ""):
        self.automata_dir = automata_dir or None
        self.available = False
        self._an = None        # analyzer("lemma")
        self._gen = None       # generator("index") — plural paradigm generation
        self._lemm = None      # lemmatizer() with ppm disambiguation
        self._freqs: dict = {}  # lemma -> ppm
        self._lock = threading.Lock()
        try:
            import dwdsmor  # noqa: F401  (also pulls in sfst_transduce)
            self._mod = dwdsmor
            self.available = True
        except Exception:
            self._mod = None

    # -- lazy loading ----------------------------------------------------
    def _ensure(self) -> None:
        """Load analyzer/generator/lemmatizer once.  Caller holds no lock.

        Once a load fails (`available` flips False) we stop retrying — the
        failure is permanent for the process lifetime.
        """
        if self._an is not None or not self.available:
            return
        with self._lock:
            if self._an is not None or not self.available:
                return
            mod = self._mod
            if mod is None:
                self.available = False
                return
            kwargs = {}
            if self.automata_dir:
                kwargs["automata_dir"] = self.automata_dir
            try:
                self._an = mod.analyzer("lemma", **kwargs)
            except Exception:
                self.available = False
                return
            try:
                self._gen = mod.generator("index", **kwargs)
            except Exception:
                self._gen = None
            try:
                self._lemm = mod.lemmatizer("lemma", **kwargs)
                self._freqs = mod.lemma_freqs(kwargs.get("automata_dir", mod.default_automata_dir))
            except Exception:
                self._lemm = None
                self._freqs = {}

    # -- analysis --------------------------------------------------------
    @functools.lru_cache(maxsize=8192)
    def _raw_analyses(self, word: str) -> tuple:
        """Return dedup'd (analysis, pos_tag, morph_tags) tuples for `word`.

        Non-str / blank input short-circuits BEFORE touching the native
        transducer: sfst raises an access violation (0xC0000005), not a
        catchable Python exception, for None.
        """
        if not isinstance(word, str) or not (word or "").strip():
            return ()
        self._ensure()
        if not self.available or self._an is None:
            return ()
        out = []
        seen = set()
        try:
            for t in self._an.analyze(word):
                lemma = (t.analysis or "").strip()
                pos = t.pos or ""
                # key includes the morph features so gender homographs
                # (der Band / das Band / die Band) are all kept, not collapsed
                key = (lemma.casefold(), pos, t.gender or "",
                       t.number or "", t.case or "")
                if not lemma or key in seen:
                    continue
                seen.add(key)
                out.append((lemma, pos, t))
                if len(out) >= 8:
                    break
        except Exception:
            return ()
        return tuple(out)

    def analyze(self, word: str) -> list[dict]:
        """Morphosyntactic analyses of `word`.

        Each dict: {word, lemma, pos (coarse), pos_tag (dwdsmor tag),
        gender, number, case, nonfinite, auxiliary, tense, degree,
        metainfo, spec}.  Empty list when dwdsmor is unavailable or the
        word is out of the open-edition lexicon.
        """
        out = []
        for lemma, pos_tag, t in self._raw_analyses(word):
            d = {
                "word": word,
                "lemma": lemma,
                "pos": _POS_MAP.get(pos_tag, "other"),
                "pos_tag": pos_tag,
                "gender": _GENDER_MAP.get(t.gender or "", ""),
                "number": t.number or "",
                "case": t.case or "",
                "nonfinite": t.nonfinite or "",
                "auxiliary": t.auxiliary or "",
                "tense": t.tense or "",
                "degree": t.degree or "",
                "metainfo": t.metainfo or "",
                "spec": t.spec,
            }
            out.append(d)
        return out

    def lemma_of(self, word: str) -> Optional[str]:
        """Canonical lemma (ppm-weighted via lemmatizer when available)."""
        self._ensure()
        if not self.available:
            return None
        if not isinstance(word, str) or not (word or "").strip():
            return None
        if self._lemm is not None:
            try:
                t = self._lemm(word)
                if t is not None:
                    return (t.analysis or "").strip() or None
            except Exception:
                pass
        raw = self._raw_analyses(word)
        return raw[0][0] if raw else None

    def pos_of(self, word: str) -> Optional[str]:
        """Coarse POS of the first / lemmatizer-chosen analysis (noun/verb/...)."""
        self._ensure()
        if not self.available:
            return None
        if not isinstance(word, str) or not (word or "").strip():
            return None
        if self._lemm is not None:
            try:
                t = self._lemm(word)
                if t is not None and t.pos:
                    return _POS_MAP.get(t.pos, "other")
            except Exception:
                pass
        raw = self._raw_analyses(word)
        if not raw:
            return None
        return _POS_MAP.get(raw[0][1], "other")

    def is_german(self, word: str) -> bool:
        """True if dwdsmor recognizes `word` as a German word form at all."""
        if not isinstance(word, str) or not (word or "").strip():
            return False
        return bool(self._raw_analyses(word))

    # -- noun grammar (best effort) -------------------------------------
    @functools.lru_cache(maxsize=4096)
    def _noun_genders(self, lemma: str) -> tuple:
        """Gender letters (m/f/n) dwdsmor assigns to `lemma` as a noun."""
        self._ensure()
        if not self.available:
            return ()
        genders = []
        for l, pos_tag, t in self._raw_analyses(lemma):
            if pos_tag != "NN" or not t.gender or t.gender == "UnmGend":
                continue
            g = _GENDER_MAP.get(t.gender)
            if g and g not in genders:
                genders.append(g)
        return tuple(genders)

    def gender_of(self, lemma: str) -> Optional[str]:
        """First gender letter, preferring a nominative-singular reading."""
        gs = self._noun_genders(lemma)
        return gs[0] if gs else None

    @functools.lru_cache(maxsize=4096)
    def plural_of(self, lemma: str) -> Optional[str]:
        """Nominative-plural form generated by the FST, else None.

        Best effort only: returns a plural ONLY when the open-edition
        generator actually produces an NN nominative-plural surface for the
        lemma.  It never invents one — an empty result means "no plural
        known", and the caller shows none.
        """
        self._ensure()
        if not self.available or self._gen is None or self._an is None:
            return None
        if not isinstance(lemma, str) or not (lemma or "").strip():
            return None
        from dwdsmor.tag import boundary_tags, get_taggings, lexeme_tags  # local: optional

        specs = set()
        for t in self._an.analyze(lemma):
            if t.pos != "NN":
                continue
            seg = t.reparse(visible_boundaries=boundary_tags)
            ls = seg.analysis
            for lt in lexeme_tags:
                v = getattr(t, lt)
                if v is not None:
                    ls += f"<{v}>"
            specs.add(ls)
        if not specs:
            return None
        forms = []
        for spec in specs:
            for tagging in get_taggings("NN"):
                if "Nom" not in tagging or "Pl" not in tagging:
                    continue
                full = spec + "".join(f"<{tg}>" for tg in tagging)
                try:
                    for g in self._gen.generate(full):
                        surface = (g.surface or "").strip()
                        if not surface:
                            surface = full
                        if surface and surface != lemma:
                            forms.append(surface)
                except Exception:
                    pass
        if not forms:
            return None
        # deterministic tie-break (no reliance on set iteration order)
        return min(set(forms), key=lambda s: (-forms.count(s), s))

    def article_of(self, lemma: str) -> str:
        """Article from a dwdsmor-known gender ('' when unknown)."""
        g = self.gender_of(lemma)
        return _ARTICLE.get(g, "")

    # -- frequency -------------------------------------------------------
    def freq(self, lemma: str) -> Optional[float]:
        """Corpus frequency (ppm) for `lemma`, or None.

        ppm.csv keys are exact-case headwords ('Akt', 'Band'...), so try the
        exact form, the casefolded form (defensive), and the title-cased form
        before giving up.
        """
        self._ensure()
        if not self._freqs or not isinstance(lemma, str) or not lemma.strip():
            return None
        return (self._freqs.get(lemma)
                or self._freqs.get(lemma.casefold())
                or self._freqs.get(lemma.title()))

    def close(self) -> None:
        """No-op placeholder (transducers are read-only process-wide)."""