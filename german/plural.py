"""Query API for the German plural DB (read-only)."""
from __future__ import annotations

import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path


class PluralDB:
    """Read-only access to the kaikki-derived German noun grammar DB."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None

    def open(self) -> None:
        if self.conn is None:
            # check_same_thread=False: the connection may be opened on the main
            # thread at startup but queried from the lookup worker thread.
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    @staticmethod
    def _norm(word: str) -> str:
        return unicodedata.normalize("NFC", word or "")

    def is_noun(self, word: str) -> bool:
        """True if `word` matches a known German noun lemma or its plural form."""
        if self.conn is None:
            self.open()
        w = self._norm(word)
        row = self.conn.execute(
            "SELECT lemma FROM nouns WHERE lemma=? COLLATE NOCASE LIMIT 1",
            (w,),
        ).fetchone()
        if row is not None:
            return True
        row = self.conn.execute(
            "SELECT lemma FROM nouns WHERE plural=? COLLATE NOCASE LIMIT 1",
            (w,),
        ).fetchone()
        return row is not None

    def lookup_lemma(self, word: str) -> dict | None:
        """Resolve a selected word to a noun row, even if it is the plural form
        (e.g. 'Häuser' -> the 'Haus' row)."""
        if self.conn is None:
            self.open()
        w = self._norm(word)
        row = self.conn.execute(
            "SELECT lemma FROM nouns WHERE lemma=? COLLATE NOCASE LIMIT 1",
            (w,),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT lemma FROM nouns WHERE plural=? COLLATE NOCASE LIMIT 1",
                (w,),
            ).fetchone()
        if row is None:
            return None
        return self.lookup(row[0])

    @lru_cache(maxsize=8192)
    def resolve_info(self, word: str) -> dict | None:
        """Resolve an inflected German surface form to its canonical base.

        Returns an info dict {lemma: <display headword>, lemma_key: <folded>,
        pos: <part of speech>} or None.

        * A capitalized noun lemma is its own base ('Haus', 'Lauf').
        * A known inflected form (in the kaikki `inflections` index) resolves
          to its lemma; a capitalized surface prefers a noun lemma
          ('Häuser' -> 'Haus', 'Hunde' -> 'Hund'), a lowercase surface (an
          adjective/verb declension) prefers a non-noun lemma ('roten' ->
          'rot', not the noun 'Rota'; 'bessere' -> 'gut', not 'bessern').
          Ties break on headword length (a crude frequency heuristic).
        * Otherwise a surface that is itself a dictionary headword (e.g.
          'bereit', 'gut', 'gehen') resolves to its own lemma/pos via
          `lemmas`.
        * None if unrecognised (caller falls back to the noun table/itself).
        """
        if self.conn is None:
            self.open()
        w = self._norm(word)
        if not w:
            return None
        # 1. a capitalized noun that is its own lemma stays the noun
        if w[:1].isupper():
            row = self.conn.execute(
                "SELECT lemma FROM nouns WHERE lemma=? COLLATE NOCASE LIMIT 1",
                (w,),
            ).fetchone()
            if row is not None:
                info = self.lookup(row[0]) or {}
                return {"lemma": info.get("lemma") or row[0],
                        "lemma_key": row[0],
                        "pos": "noun"}
        # 2. known inflected form -> base lemma (+ original case + pos)
        rows = self.conn.execute(
            "SELECT lemma, lemma_display, pos FROM inflections "
            "WHERE inflection=? COLLATE NOCASE",
            (w,),
        ).fetchall()
        if rows:
            upper = w[:1].isupper()
            if upper:
                cands = [r for r in rows if r[2] == "noun"]
            else:
                cands = [r for r in rows if r[2] != "noun"]
            cands = cands or rows
            cands.sort(key=lambda r: (len(r[1]), r[0]))
            lemma, display, pos = cands[0]
            # a lowercase surface that is itself a dictionary headword may be
            # a real inflection (reduce) or a homograph/compound collision
            # (keep the headword itself).  Decide by how the candidate
            # relates to the surface:
            #   - candidate extends surface at the START and shares POS
            #     ('geht' -> 'gehen') => inflectional ending, reduce;
            #   - candidate extends surface at the start with a DIFFERENT POS
            #     ('gut' adj vs 'Gute' noun, 'bereit' vs 'bereiten' verb)
            #     => homograph, keep the headword;
            #   - candidate extends surface at the END (prefix compound:
            #     'laufen' -> 'eislaufen') => derived, surface is the base,
            #     keep the headword;
            #   - no containment ('ging' -> 'gehen') => different stem,
            #     reduce;
            #   - candidate display is multiword => kaikki artifact,
            #     keep the headword.
            if not upper:
                own = self.conn.execute(
                    "SELECT lemma, lemma_display, pos FROM lemmas "
                    "WHERE lemma_display=? LIMIT 1",
                    (w,),
                ).fetchone()
                keep = False
                if own is not None and own[0] != lemma:
                    if " " in display:
                        keep = True
                    else:
                        fdisp = display.casefold()
                        fw = w.casefold()
                        ext_suf = len(fdisp) > len(fw) and fdisp.endswith(fw)
                        ext_pre = len(fdisp) > len(fw) and fdisp.startswith(fw)
                        if ext_suf:
                            keep = True
                        elif ext_pre and own[2] != pos:
                            keep = True
                        # else: ext_pre same-POS (reduce) or no containment (reduce)
                if keep:
                    return {"lemma": own[1], "lemma_key": own[0], "pos": own[2]}
            return {"lemma": display, "lemma_key": lemma, "pos": pos}
        # 3. the surface is itself a dictionary headword (any POS)
        own = self.conn.execute(
            "SELECT lemma, lemma_display, pos FROM lemmas "
            "WHERE lemma_display=? LIMIT 1",
            (w,),
        ).fetchone()
        if own is None:
            own = self.conn.execute(
            "SELECT lemma, lemma_display, pos FROM lemmas "
            "WHERE lemma_display=? COLLATE NOCASE LIMIT 1",
            (w,),
        ).fetchone()
        if own is not None:
            return {"lemma": own[1], "lemma_key": own[0], "pos": own[2]}
        return None

    @lru_cache(maxsize=8192)
    def resolve_form(self, word: str) -> str | None:
        """Resolve an inflected German surface to its canonical display lemma
        ('Haus', 'rot', 'gehen', 'laufend') or None.

        Covers nouns, verbs and adjectives via the kaikki `inflections`
        index: 'ging' -> 'gehen', 'Häuser' -> 'Haus', 'Händen' -> 'Hand'.
        """
        info = self.resolve_info(word)
        return info["lemma"] if info else None

    @lru_cache(maxsize=4096)
    def deverbal_nouns(self, lemma_key: str) -> list[dict]:
        """Noun rows that share a verb's folded lemma key ('sprechen' ->

        ['Sprechen'], 'gehen' -> ['Gehen']).  These are the deverbal-noun
        cards ('das Sprechen') offered as alternatives to the bare verb.
        Empty list means the verb has no known deverbal noun in kaikki.
        """
        if self.conn is None:
            self.open()
        rows = self.conn.execute(
            "SELECT lemma, gender, article, plural, plural_article, has_plural "
            "FROM nouns WHERE lemma=? COLLATE NOCASE",
            (self._norm(lemma_key),),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "lemma": r[0],
                "gender": r[1],
                "article": r[2],
                "plural": r[3],
                "plural_article": r[4],
                "has_plural": bool(r[5]),
            })
        return out

    @lru_cache(maxsize=8192)
    def lookup(self, lemma: str) -> dict | None:
        """Return {lemma, gender, article, plural, plural_article, has_plural} or None.

        Case-insensitive: matches 'haus' to 'Haus'.
        """
        if self.conn is None:
            self.open()
        row = self.conn.execute(
            "SELECT lemma, gender, article, plural, plural_article, has_plural "
            "FROM nouns WHERE lemma=? COLLATE NOCASE",
            (self._norm(lemma),),
        ).fetchone()
        if row is None:
            return None
        return {
            "lemma": row[0],
            "gender": row[1],
            "article": row[2],
            "plural": row[3],
            "plural_article": row[4],
            "has_plural": bool(row[5]),
        }

    @lru_cache(maxsize=4096)
    def reverse_lookup(self, word: str, src_lang: str = "en", limit: int = 8) -> list[dict]:
        """Find German lemmas that translate `word` (from kaikki EN/PL translations).

        Returns the same dict shape as lookup() for each matching German lemma.
        """
        if self.conn is None:
            self.open()
        w = self._norm(word).casefold()
        rows = self.conn.execute(
            "SELECT DISTINCT t.de_lemma FROM trans t WHERE t.src_lang=? AND t.src_word=? COLLATE NOCASE LIMIT ?",
            (src_lang, w, limit),
        ).fetchall()
        out = []
        for (lemma,) in rows:
            info = self.lookup(lemma)
            if info:
                out.append(info)
        return out

    @lru_cache(maxsize=4096)
    def translations_of(self, german_word: str, *, limit: int = 12) -> list[dict]:
        """Given a German word, return its foreign (EN/PL) translations.

        Returns a list of {"lang": "en"|"pl", "word": "..."} for the reverse-
        lookup table, so the user can build a German->foreign card.
        """
        if self.conn is None:
            self.open()
        w = self._norm(german_word).casefold()
        rows = self.conn.execute(
            "SELECT src_lang, src_word FROM trans WHERE de_lemma=? COLLATE NOCASE LIMIT ?",
            (w, limit),
        ).fetchall()
        out = []
        seen = set()
        for lang, word in rows:
            if word and (lang, word) not in seen:
                out.append({"lang": lang, "word": word})
                seen.add((lang, word))
        return out