"""Keyed SQLite index + query over dict.cc txt files.

dict.cc files are huge (EN-DE: 1.3M lines) and only *roughly* sorted, so we do
not binary-search them directly.  Instead we build a cached SQLite index
keyed by a normalized source term (NFC + casefold) once per file, then query
it exactly.  The index lives under data/ and is rebuilt if the file changes.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .entities import GenderInfo, extract_gender, split_line, clean_term

_ACCENT_RE = re.compile(r"[\u0300-\u036f]")

# Schema version written into meta['schema']: bump when the index layout
# changes (columns/tables) so a stale db with an unchanged source file is
# rebuilt instead of reused and crashing with 'no such table/column'.
SCHEMA_VERSION = "v2:entries-key-clean"


def normalize_key(text: str) -> str:
    """Normalize a term for exact-match keying: NFC + casefold."""
    return unicodedata.normalize("NFC", text or "").casefold()


def clean_key(text: str) -> str:
    """Normalized CLEAN key for a source term (gender/brackets/angles removed).

    dict.cc raw keys carry gender markers and annotations ('haus {n} [Gebäude]');
    a bare word like 'Haus' could never exact-match them.  This produces the
    stripped key ('haus') that the matcher's exact/prefix/fuzzy tiers and
    has_exact use, restoring exact 1.0 for German nouns and making the fuzzy
    window see short keys instead of long annotated phrases.
    """
    return normalize_key(clean_term(text or ""))


def strip_accents(text: str) -> str:
    """Remove diacritics (used as a fuzzy fallback for English only)."""
    return _ACCENT_RE.sub("", unicodedata.normalize("NFD", text or ""))


@dataclass
class TermEntry:
    """One parsed dict.cc line + cleaned fields."""

    line_no: int
    source: str       # raw source term (still contains gender markers / brackets)
    target: str       # raw target term
    pos: str
    tags: str
    source_clean: str = ""
    target_clean: str = ""
    target_gender: list = field(default_factory=list)  # ['n'], ['m','f'], ...
    target_article: str = ""  # "der"/"die"/"das"/"der/die" ("" if unknown)

    @classmethod
    def from_line(cls, line: str, line_no: int) -> Optional["TermEntry"]:
        source, target, pos, tags = split_line(line)
        if not source and not target:
            return None
        t_clean, t_info = extract_gender(target)
        s_clean, _ = extract_gender(source)
        return cls(
            line_no=line_no,
            source=source,
            target=target,
            pos=pos,
            tags=tags,
            source_clean=s_clean,
            target_clean=t_clean,
            target_gender=t_info.genders,
            target_article=t_info.article,
        )


# Column the matcher/has_exact use for exact/prefix/fuzzy (cleaned keys).
_C_KEY = "key_clean"


class DictIndex:
    """Index over one dict.cc txt file, backed by a cached SQLite database."""

    def __init__(self, txt_path, db_path=None, table="entries"):
        self.txt_path = Path(txt_path)
        self.db_path = Path(db_path) if db_path else None
        self.table = table
        self.conn: Optional[sqlite3.Connection] = None
        if self.db_path is None:
            default_db = Path("data") / f"idx_{self.txt_path.stem}.db"
            self.db_path = default_db
        self._ensure_index()

    # -- lifecycle -------------------------------------------------------
    def _fingerprint(self) -> str:
        st = self.txt_path.stat()
        return f"{SCHEMA_VERSION}:{st.st_size}:{int(st.st_mtime)}"

    def _index_uptodate(self) -> bool:
        if not self.db_path.exists():
            return False
        try:
            with sqlite3.connect(self.db_path) as c:
                row = c.execute(
                    "SELECT value FROM meta WHERE key=?",
                    (f"fingerprint:{self.txt_path.name}",),
                ).fetchone()
                schema = c.execute(
                    "SELECT value FROM meta WHERE key='schema'",
                ).fetchone()
            return bool(row and row[0] == self._fingerprint()
                        and schema and schema[0] == SCHEMA_VERSION)
        except sqlite3.DatabaseError:
            return False

    def _build(self) -> None:
        print(f"Indexing {self.txt_path.name} ...", file=sys.stderr)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.db_path.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()
        conn = sqlite3.connect(tmp)
        conn.execute(
            f"CREATE TABLE {self.table} ("
            "key TEXT, key_clean TEXT, line_no INTEGER, source TEXT, target TEXT, "
            "pos TEXT, tags TEXT)"
        )
        conn.execute(f"CREATE INDEX idx_{self.table}_key ON {self.table}(key)")
        conn.execute(f"CREATE INDEX idx_{self.table}_key_clean ON {self.table}(key_clean)")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        batch = []
        with open(self.txt_path, encoding="utf-8", errors="replace") as f:
            line_no = 0
            for raw in f:
                line_no += 1
                if raw.startswith("#") or not raw.strip():
                    continue
                source, target, pos, tags = split_line(raw)
                if not source:
                    continue
                key = normalize_key(source)
                key_clean = clean_key(source)
                batch.append((key, key_clean, line_no, source, target, pos, tags))
                if len(batch) >= 20000:
                    conn.executemany(
                        f"INSERT INTO {self.table} "
                        "(key, key_clean, line_no, source, target, pos, tags) "
                        "VALUES (?,?,?,?,?,?,?)",
                        batch,
                    )
                    batch = []
            if batch:
                conn.executemany(
                    f"INSERT INTO {self.table} "
                    "(key, key_clean, line_no, source, target, pos, tags) "
                    "VALUES (?,?,?,?,?,?,?)",
                    batch,
                )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?)",
            (f"fingerprint:{self.txt_path.name}", self._fingerprint()),
        )
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema', ?)",
                     (SCHEMA_VERSION,))
        conn.commit()
        conn.close()
        tmp.replace(self.db_path)
        print(f"Indexed {self.txt_path.name} -> {self.db_path}", file=sys.stderr)

    def _ensure_index(self) -> None:
        if not self._index_uptodate():
            self._build()
        # check_same_thread=False because lookups run on the worker thread
        # while the index is (re)built/opened on the main thread at startup.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # -- query -----------------------------------------------------------
    def has_key(self, candidate: str, *, clean: bool = True) -> bool:
        """True if `candidate` exists as a source key.

        By default, matches against the CLEANED key (gender markers/brackets
        stripped), so 'Haus' matches 'haus {n} [Gebäude]'.  Pass clean=False
        for the raw normalized key.
        """
        if self.conn is None:
            self._ensure_index()
        ck = clean_key(candidate) if clean else normalize_key(candidate)
        if not ck:
            return False
        col = "key_clean" if clean else "key"
        row = self.conn.execute(
            f"SELECT 1 FROM {self.table} WHERE {col}=? LIMIT 1", (ck,)
        ).fetchone()
        return row is not None

    def query_scored(self, word: str, *, lang: str | None = None, limit: int = 15,
                     resolve_form=None, enable_fuzzy: bool = True,
                     analyzers=None):
        """Score-matched query, returning matcher.ScoredMatch entries.

        Backing store stays the same index; all fuzzy work is bounded.  See
        dictlookup.matcher.match_scored for the staging/score semantics.
        """
        from .matcher import match_scored
        return match_scored(self, word, lang, limit=limit,
                            resolve_form=resolve_form,
                            enable_fuzzy=enable_fuzzy,
                            analyzers=analyzers)

    def query_clean(self, word: str, *, lang: str | None = None, limit: int = 25) -> list[TermEntry]:
        """Lookup by CLEANED key: matches any row whose stripped source equals
        `word` ('Haus' -> rows for 'haus {n} [Gebäude]').  Used by has_exact.
        """
        if self.conn is None:
            self._ensure_index()
        ck = clean_key(word)
        if not ck:
            return []
        cur = self.conn.execute(
            f"SELECT line_no, source, target, pos, tags FROM {self.table} "
            f"WHERE {_C_KEY}=? LIMIT ?", (ck, limit),
        )
        return [TermEntry(l, s, t, p, ta) for (l, s, t, p, ta) in cur.fetchall()]

    def query(self, word: str, *, fuzzy_accents: bool = False, limit: int = 15) -> list[TermEntry]:
        """Look up `word` (source side); return TermEntry matches.

        Strategy: exact match on the normalized key first; else a prefix scan
        (covers inflected forms like "dogs" or "houses" without exact keys).
        """
        if self.conn is None:
            self._ensure_index()
        key = normalize_key(word)
        cur = self.conn.execute(
            f"SELECT line_no, source, target, pos, tags FROM {self.table} WHERE key=? LIMIT ?",
            (key, limit),
        )
        out = [TermEntry(line_no, s, t, p, tg) for (line_no, s, t, p, tg) in cur.fetchall()]
        if out:
            return out
        # prefix scan (inflections / related forms): stored keys are already
        # NFC + casefolded, so a range scan uses the BINARY index instead of an
        # unindexed `LIKE` full-table scan.
        nextpfx = key[:-1] + chr(ord(key[-1]) + 1)
        cur = self.conn.execute(
            f"SELECT line_no, source, target, pos, tags FROM {self.table} "
            "WHERE key >= ? AND key < ? ORDER BY key LIMIT ?",
            (key, nextpfx, limit),
        )
        return [TermEntry(line_no, s, t, p, tg) for (line_no, s, t, p, tg) in cur.fetchall()]