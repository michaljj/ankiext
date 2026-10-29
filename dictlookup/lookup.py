"""High-level lookup: source text -> German translation candidates.

Uses the dict.cc EN-DE and PL-DE files for instant offline translation +
German gender/article; the German plural DB (kaikki) enriches plurals later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import sys
from typing import Optional

from .entities import extract_gender
from .search import DictIndex, TermEntry, normalize_key


@dataclass
class TranslationHit:
    """A single candidate translation with German-side grammar where known."""

    source: str                 # cleaned source term
    source_raw: str              # raw source term (pre-cleanup)
    german: str                  # cleaned German term (gender markers stripped)
    german_raw: str              # raw German term (pre-cleanup)
    pos: str
    tags: str
    line_no: int
    gender: list = field(default_factory=list)   # ['n'], ['m','f'], ...
    article: str = ""            # der/die/das or der/die ("" if unknown)
    # filled in later by german.plural lookup
    plural: str = ""
    plural_article: str = ""
    # language of the "target" side: 'de' for EN-DE/PL-DE, 'en'/'pl' for DE-*
    target_lang: str = "de"
    # how confident the source-side match was (exact=1.0, declining through
    # accent/lemma/stem/prefix/fuzzy).  1.0 default preserves old callers.
    confidence: float = 1.0
    # matching strategy that produced this hit (matcher method tag)
    method: str = "exact"


class Dictionary:
    """Facade over the dict.cc files for one or both source languages."""

    def __init__(self, config: dict | None = None, resolve_form=None,
                 analyzers=None):
        cfg = config or {}
        # accept both flat dicts and the nested config.toml structure
        if "dictionary" in cfg:
            cfg = cfg["dictionary"]
        dict_dir = Path(cfg.get("dict_dir", "dict"))
        en_de = cfg.get("en_de")
        pl_de = cfg.get("pl_de")
        de_en = cfg.get("de_en")
        de_pl = cfg.get("de_pl")
        db_dir = Path(cfg.get("index_dir", "data"))

        self._loaded = []
        # Optional callable(inflected_german) -> canonical German lemma, used
        # when searching German-side indexes so "ging" -> "gehen" resolves.
        self._resolve_form = resolve_form
        # Optional real-morphology facade (spaCy/morfeusz2/DWDSmor).
        self._analyzers = analyzers
        self._en_de = self._load(dict_dir, db_dir, en_de)
        self._pl_de = self._load(dict_dir, db_dir, pl_de)
        self._de_en = self._load(dict_dir, db_dir, de_en)
        self._de_pl = self._load(dict_dir, db_dir, de_pl)

    def close(self) -> None:
        for idx in self._loaded:
            idx.close()

    def _load(self, dict_dir: Path, db_dir: Path, fname: str | None) -> Optional[DictIndex]:
        if not fname:
            return None
        txt = dict_dir / fname
        if not txt.exists():
            # Surface missing dict files instead of silently returning no hits
            # (which made lookups fail with no error when run from the wrong CWD).
            print(f"[dictlookup] warning: configured dict file not found: {txt}", file=sys.stderr)
            return None
        idx = DictIndex(txt, db_dir / f"idx_{Path(fname).stem}.db")
        self._loaded.append(idx)
        return idx

    def has_exact(self, word: str, lang: str) -> bool:
        """True if `word` has an exact (source-side) match in the given dict.

        Compares against the CLEANED source key (gender markers stripped),
        e.g. 'dom {m}' -> 'dom'.  Uses the index's key_clean column so a bare
        word matches annotated entries ('Haus' matches 'haus {n} [Gebäude]').
        """
        index = self._pl_de if lang == "pl" else self._en_de
        if index is None:
            return False
        from .search import clean_key
        target = clean_key(word)
        if not target:
            return False
        return any(clean_key(e.source) == target
                   for e in index.query_clean(word, lang=lang, limit=25))

    # -- lookups ---------------------------------------------------------
    @lru_cache(maxsize=4096)
    def lookup(self, word: str, lang: str = "auto", *, limit: int = 15) -> list[TranslationHit]:
        """Look up a source word; returns German translation candidates.

        lang: 'pl' or 'en' (or auto → tries pl then en).
        """
        if lang == "pl":
            return self._lookup_in(self._pl_de, word, lang="pl", limit=limit,
                                   analyzers=self._analyzers)
        hits = self._lookup_in(self._en_de, word, lang="en", limit=limit,
                               analyzers=self._analyzers)
        if hits or lang != "auto":
            return hits
        return self._lookup_in(self._pl_de, word, lang="pl", limit=limit,
                               analyzers=self._analyzers)

    def lookup_german(self, word: str, *, limit: int = 15) -> list[TranslationHit]:
        """German → English/Polish, merged across BOTH German-side indexes.

        Searches DE-EN and DE-PL and merges their hits (each tagged with its
        target language) so a German word surfaces its English *and* Polish
        translations together instead of only whichever index wins.
        """
        out = self._lookup_in(self._de_en, word, lang="de", limit=limit,
                              target_lang="en", resolve_form=self._resolve_form,
                              analyzers=self._analyzers)
        out += self._lookup_in(self._de_pl, word, lang="de", limit=limit,
                               target_lang="pl", resolve_form=self._resolve_form,
                               analyzers=self._analyzers)
        # de-dup by (source, target) keeping the first occurrence
        seen: set[tuple[str, str, str]] = set()
        merged = []
        for h in out:
            key = (h.source.casefold(), h.german.casefold(), h.target_lang)
            if key in seen:
                continue
            seen.add(key)
            merged.append(h)
        return merged

    @staticmethod
    def _lookup_in(index: Optional[DictIndex], word: str, *, limit: int,
                   target_lang: str = "de", lang: str | None = None,
                   resolve_form: Optional[callable] = None,
                   analyzers=None) -> list[TranslationHit]:
        if index is None:
            return []
        scored = index.query_scored(word, lang=lang, limit=limit,
                                    resolve_form=resolve_form,
                                    analyzers=analyzers)
        hits = []
        for sm in scored:
            e = sm.entry
            source_clean, _ = extract_gender(e.source)
            target_clean, t_info = extract_gender(e.target)
            if not target_clean:
                continue
            hits.append(TranslationHit(
                source=source_clean or e.source,
                source_raw=e.source,
                german=target_clean,
                german_raw=e.target,
                pos=e.pos,
                tags=e.tags,
                line_no=e.line_no,
                gender=t_info.genders,
                article=t_info.article,
                target_lang=target_lang,
                confidence=sm.confidence,
                method=sm.method,
            ))
        return hits