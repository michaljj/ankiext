"""Multi-tier, confidence-scored dictionary matching.

The core "smart matching" value of AnkiExt.  Instead of a single exact-hit
with a prefix fallback, this module stages several strategies -- exact →
accent-insensitive → orthographic variant → lemma/stem resolution → prefix →
edit-distance fuzzy -- and scores every surviving candidate with a confidence
in [0, 1] and a `method` tag so the UI can show certainty and let the user
deliberately pick a weaker match.

It is pure logic (no tkinter / Anki) and works against a DictIndex plus an
optional morphology / kaikki resolver.  Fuzzy matching is always bounded to a
narrow prefix window so we never scan the whole 1.3M-row file at runtime.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Callable, Optional

from .analyzers import Analyzers
from .morphology import candidates as morph_candidates
from .search import (DictIndex, TermEntry, normalize_key, strip_accents,
                     clean_key)

# method tags (also used as sort tie-breakers)
EXACT = "exact"
ACCENT = "accent"
ORTHVAR = "orthvar"
LEMMA = "lemma"
STEM = "stem"
PREFIX = "prefix"
FUZZY = "fuzzy"

_METHOD_ORDER = {EXACT: 0, ACCENT: 1, ORTHVAR: 2, LEMMA: 3, STEM: 4, PREFIX: 5, FUZZY: 6}

# minimum SequenceMatcher ratio for a fuzzy candidate to be kept at all
_FUZZY_FLOOR = 0.55
# how many fuzzy candidates we keep at most
_FUZZY_KEEP = 5


@dataclass
class ScoredMatch:
    """One dictionary line that plausibly matches the query, with a score."""

    entry: TermEntry          # resolved dictionary line
    matched_term: str         # the dictionary-side term that actually matched
    confidence: float         # 0.10..1.00
    method: str               # one of the _METHOD tags


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _prefix_confidence(probe: str, matched: str) -> float:
    """Confidence for a prefix match: how much of the key the query covers."""
    query, key = normalize_key(probe), normalize_key(matched)
    if not query or not key or not key.startswith(query):
        return 0.0
    return round(0.62 + 0.20 * (len(query) / len(key)), 3)


def match_scored(index: DictIndex, query: str,
                 lang: str | None = None, *,
                 limit: int = 15,
                 resolve_form: Optional[Callable[[str], Optional[str]]] = None,
                 enable_fuzzy: bool = True,
                 analyzers: Optional[Analyzers] = None) -> list[ScoredMatch]:
    """Score-match `query` against the source side of `index`.

    `lang` is the source language of that index side ('en'|'pl'|'de').  For
    'de', `resolve_form` (e.g. PluralDB.resolve_form) is consulted first to map
    an inflected German surface form to its lemma.  `analyzers` (optional) adds
    real lemmatisation (spaCy / morfeusz2 / DWDSmor) for en/pl/de.

    Always returns a list (possibly empty), ranked best-first, capped to
    `limit`.  If nothing clears even the fuzzy floor, returns [].
    """
    query = (query or "").strip()
    if not query:
        return []
    if index.conn is None:
        index._ensure_index()
    key = normalize_key(query)
    results: list[ScoredMatch] = []
    seen: set[tuple[str, int]] = set()

    def _add(entry: TermEntry, matched: str, conf: float, method: str) -> None:
        if conf <= 0:
            return
        dk = (normalize_key(entry.source), entry.line_no)
        conf = round(min(conf, 1.0), 3)
        # already seen: keep the higher-confidence variant of the same line
        for i, prev in enumerate(results):
            if (normalize_key(prev.entry.source), prev.entry.line_no) == dk:
                if conf > prev.confidence:
                    results[i] = ScoredMatch(entry, matched, conf, method)
                return
        seen.add(dk)
        results.append(ScoredMatch(entry, matched, conf, method))

    # 1. exact hit
    rows = _exact(index, key)
    if rows:
        for e in rows:
            _add(e, e.source or key, 1.0, EXACT)
        return _rank(results, limit)

    # 2. accent-insensitive (diacritics differ only)
    rows = _exact(index, strip_accents(key))
    if rows:
        for e in rows:
            _add(e, e.source or key, 0.95, ACCENT)
        return _rank(results, limit)

    # 2.5 orthographic variants (strasse<->straße, ueber<->über, ...)
    vrows = _variant_exact(index, key)
    if vrows:
        for e in vrows:
            _add(e, e.source or key, 0.93, ORTHVAR)
        return _rank(results, limit)

    # 3. lemma / morphological resolution
    resolved: list[tuple[str, str]] = []   # (candidate, method)
    if lang == "de" and resolve_form is not None:
        lemma = resolve_form(query)
        if lemma and normalize_key(lemma) != key:
            resolved.append((lemma, LEMMA))
    if analyzers is not None:
        # real-lemma candidates (validated against the index below)
        for cand in analyzers.candidates(query, lang or "en"):
            if cand and normalize_key(cand) != key:
                resolved.append((cand, LEMMA))
    for cand in morph_candidates(query, lang):
        if cand and normalize_key(cand) != key:
            resolved.append((cand, STEM))

    for cand, method in resolved:
        ck = normalize_key(cand)
        if not ck or ck == key:
            continue
        rows = _exact(index, ck)
        score = 0.92 if method == LEMMA else 0.90
        for e in rows:
            _add(e, cand, score, method)

    # 4. prefix scan (index-range; matches keys that START with the query)
    for e in _prefix(index, key):
        matched = e.source or key
        _add(e, matched, _prefix_confidence(key, matched), PREFIX)

    # 5. bounded fuzzy: Damerau-Levenshtein within a narrow prefix window
    if enable_fuzzy:
        d = _damerau; d_ok = _fuzzy_ok
        window = _fuzzy_window(index, key)
        best: list[tuple[float, TermEntry]] = []
        for e in window:
            # distance against the CLEANED key ('haus'), not the raw source
            # ('haus {n} [Gebäude]' — 15 edits away from 'Huas').
            probe = clean_key(e.source)
            if not probe:
                continue
            dist = d(query, probe)
            if not d_ok(query, probe, dist):
                continue
            # confidence from edit distance within the fuzzy tier
            conf = 0.50 + 0.30 * (1.0 - dist / max(len(query), len(probe)))
            best.append((conf, e))
        best.sort(key=lambda t: t[0], reverse=True)
        for conf, e in best[:_FUZZY_KEEP]:
            _add(e, e.source or key, conf, FUZZY)

    return _rank(results, limit)


# -- internal helpers (mirrors search.py query internals) --------------------
# Exact/prefix/fuzzy tiers query the CLEANED key column (key_clean): raw dict.cc
# keys carry '{n}'/'[brackets]' junk, so a bare word like 'haus' or 'straße'
# can exact-match 'haus {n} [Gebäude]' instead of falling to prefix.  The
# display term comes from the row's raw source.
_C_KEY = "key_clean"


def _exact(index: DictIndex, key: str, table: Optional[str] = None) -> list[TermEntry]:
    if index.conn is None:
        index._ensure_index()
    t = table or index.table
    cur = index.conn.execute(
        f"SELECT line_no, source, target, pos, tags FROM {t} "
        f"WHERE {_C_KEY}=? LIMIT ?",
        (key, 30),
    )
    return [TermEntry(l, s, tg, p, ta) for (l, s, tg, p, ta) in cur.fetchall()]


# orthographic variant substitutions — UMlAUT DIGRAPHS ONLY (both directions).
# 'ß/ss' is handled by casefold already ('straße'≡'strasse'), and an unguarded
# 'ss'→'ß' invents junk ('messe'→'meße', 'caesar'→'cäsar').
_ORTH_VARIANTS = (
    ("ä", "ae"), ("ae", "ä"),
    ("ö", "oe"), ("oe", "ö"),
    ("ü", "ue"), ("ue", "ü"),
)


def variant_keys(word: str, key: str | None = None) -> list[str]:
    """All orthographic variants of `word` (casefolded), excluding itself.

    'ueber' -> ['über']; 'über' -> ['ueber'].  Handles at most one
    substitution (the common cases).  ß <-> ss is NOT listed: casefold already
    unifies them.
    """
    k = key if key is not None else normalize_key(word)
    if not k:
        return []
    out = []
    for a, b in _ORTH_VARIANTS:
        if a not in k:
            continue
        v = k.replace(a, b)
        if v and v != k and v not in out:
            out.append(v)
    return out


def _exact_raw_key(index: DictIndex, key: str) -> list[TermEntry]:
    """Exact hits on the RAW index key (preserves 'ü' — used by orthvar)."""
    if index.conn is None:
        index._ensure_index()
    cur = index.conn.execute(
        f"SELECT line_no, source, target, pos, tags FROM {index.table} "
        "WHERE key=? LIMIT ?",
        (key, 20),
    )
    return [TermEntry(l, s, tg, p, ta) for (l, s, tg, p, ta) in cur.fetchall()]


def _variant_exact(index: DictIndex, key: str) -> list[TermEntry]:
    """Exact hits for orthographic variants of `key` (ueber->über).

    Queries the RAW key column because a variant like 'über' must match a
    stored raw key 'über' (the cleaned key casefolds it to 'ueber', losing the
    distinction orthvar exists to bridge).
    """
    out: list[TermEntry] = []
    for vk in variant_keys(key, key):
        if not vk:
            continue
        seen: set[int] = {e.line_no for e in out}
        for e in _exact_raw_key(index, normalize_key(vk)):
            if e.line_no not in seen:
                out.append(e)
    return out


def _damerau(a: str, b: str) -> int:
    """Optimal String Alignment distance (restricted Damerau-Levenshtein).

    Adjacent transposition counts as one edit, but each position may be
    edited at most once (OSA), so a few true-DL 2-edit cases (interleaved
    double transposition) read 3 here.  That is the intended trade-off: it is
    O(n*m) in two rows and 100% verified against a full-matrix reference, and
    the 1-edit bands (<=4 and 5-7 chars) agree with unrestricted DL exactly.
    """
    a, b = a.casefold(), b.casefold()
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    # two-row DP over the length of the *shorter* string
    if n > m:
        a, b = b, a
        n, m = m, n
    prev_prev = list(range(m + 1))
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1,            # deletion
                         cur[j - 1] + 1,         # insertion
                         prev[j - 1] + cost)     # substitution
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev_prev[j - 2] + 1)   # transposition
        prev_prev, prev = prev, cur
    return prev[m]


def _fuzzy_ok(query: str, probe: str, dist: int) -> bool:
    """Length-aware fuzzy acceptance policy (DictAlgos thresholds).

    <=4 chars: distance 1 with a first-char match only
    5-7 chars : distance 1
    8+ chars : distance 2 with a 2-char prefix required

    The bands key off the QUERY length (the user's input); the first-char rule
    is deliberately applied to the 5-7 band too (a zero-prefix match there is
    almost always a false positive and cheap to reject).
    """
    q = query.casefold()
    p = (probe or "").casefold()
    if not q or not p:
        return False
    n = len(q)
    # watch asymmetric lengths: a 9-char query vs a 4-char key can't be d<=2
    if abs(n - len(p)) > dist:
        return False
    if n <= 4:
        if dist > 1 or q[0] != p[0]:
            return False
    elif n <= 7:
        if dist > 1 or q[0] != p[0]:
            return False
    else:
        if dist > 2 or q[:2] != p[:2]:
            return False
    return True


def _fuzzy_window(index: DictIndex, key: str) -> list[TermEntry]:
    """Candidate window for fuzzy matching (over CLEANED keys).

    Cleaned keys ('haus', not 'haus {n} [Gebäude]') are short and sort close to
    the probe, so the first-letter range actually contains the words the
    policy accepts — on raw keys the short words sorted beyond the LIMIT and
    the fuzzy tier was dead.  Never a full-table scan.
    """
    if index.conn is None:
        index._ensure_index()
    n = len(key)
    if n >= 8:
        probe, limit = key[:2], 400
    elif n >= 5:
        probe, limit = key[:1], 800
    else:
        probe, limit = key[:1], 1500
    if not probe:
        return []
    nextpfx = probe[:-1] + chr(ord(probe[-1]) + 1)
    cur = index.conn.execute(
        f"SELECT line_no, source, target, pos, tags FROM {index.table} "
        f"WHERE {_C_KEY} >= ? AND {_C_KEY} < ? ORDER BY {_C_KEY} LIMIT ?",
        (probe, nextpfx, limit),
    )
    return [TermEntry(l, s, t, p, ta) for (l, s, t, p, ta) in cur.fetchall()]


def _prefix(index: DictIndex, probe: str, limit: int = 20) -> list[TermEntry]:
    if index.conn is None:
        index._ensure_index()
    key = clean_key(probe)
    if not key:
        return []
    nextpfx = key[:-1] + chr(ord(key[-1]) + 1)
    cur = index.conn.execute(
        f"SELECT line_no, source, target, pos, tags FROM {index.table} "
        f"WHERE {_C_KEY} >= ? AND {_C_KEY} < ? ORDER BY {_C_KEY} LIMIT ?",
        (key, nextpfx, limit),
    )
    return [TermEntry(l, s, t, p, ta) for (l, s, t, p, ta) in cur.fetchall()]


def _rank(results: list[ScoredMatch], limit: int) -> list[ScoredMatch]:
    results.sort(key=lambda m: (round(m.confidence, 3),
                                _METHOD_ORDER[m.method]),
                 reverse=True)
    return results[:limit]