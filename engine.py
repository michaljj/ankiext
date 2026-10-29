"""Shared candidate-building pipeline (engine) used by the GUI and the CLIs.

Kept free of tkinter/AnkiConnect so it can run on the GUI worker thread or on
the main thread of a one-shot CLI with identical results.  The forward
(foreign -> German) and reverse (German -> foreign) flows both live here so
`process_text` and `--once` can't drift apart.
"""
from __future__ import annotations

import re
import unicodedata

from cards.builder import CardCandidate, rank_candidate


def clean_source(word: str) -> str:
    """Normalize a raw translation word for display.

    Strips stray kaikki/dict.cc markup (brackets, angle abbrevs, gender
    markers) so a card's Source field never carries `[...]`/`{m}` junk.
    """
    w = unicodedata.normalize("NFC", word or "")
    w = re.sub(r"\[[^\]]*\]", "", w)
    w = re.sub(r"<[^>]*>", "", w)
    w = re.sub(r"\{[^}]*\}", "", w)
    return " ".join(w.split()).strip()


def candidate_from_info(source: str, source_lang: str, info: dict,
                        pos: str = "noun", tags: str = "") -> CardCandidate:
    """Build a CardCandidate from a plural-DB info dict."""
    return CardCandidate(
        source=source,
        source_lang=source_lang,
        german=info.get("lemma") or info.get("de_lemma") or "",
        gender=info.get("gender", ""),
        article=info.get("article", ""),
        plural=info.get("plural", ""),
        plural_article=info.get("plural_article", ""),
        pos=pos,
        tags=tags,
    )


def reverse_candidates(word: str, lang: str, plural, wikt=None) -> list[CardCandidate]:
    """German lemmas that translate `word`; Wiktionary last resort when empty.

    `wikt` is an optional WiktionaryAPI instance (None disables the network
    fallback).  Only consulted when the local reverse-lookup table misses and
    only for langs we can query (en/pl).
    """
    out: list[CardCandidate] = []
    for info in plural.reverse_lookup(word, src_lang=lang, limit=5):
        c = candidate_from_info(source=word, source_lang=lang, info=info)
        if c.german.casefold() not in {x.german.casefold() for x in out}:
            out.append(c)
    if not out and wikt is not None and lang in ("en", "pl"):
        w = wikt.german_translation(word, lang)
        if w:
            c = candidate_from_info(source=word, source_lang=lang, info=w)
            if c.german.casefold() not in {x.german.casefold() for x in out}:
                out.append(c)
    return out


def _german_hit_candidate(h, plural) -> CardCandidate:
    """A German->foreign dict.cc hit turned into a card (german=German word).

    h comes from lookup_german(): h.source is the German term, h.german the
    foreign translation, h.target_lang its language.  Grammar (article/plural)
    is enriched from the plural DB by the German lemma.
    """
    g_word = h.source or h.german_raw
    info = plural.lookup(g_word) or {}
    return CardCandidate(
        source=h.german,                # foreign translation goes on the card
        source_lang=h.target_lang,
        german=g_word,
        gender=info.get("gender", ""),
        article=info.get("article", ""),
        plural=info.get("plural", ""),
        plural_article=info.get("plural_article", ""),
        pos=h.pos,
        tags=h.tags,
    )


def _rank_candidate(c, query: str, freq=None) -> tuple:
    """rank_candidate, but a source that IS the queried word wins ties.

    The user asked about a specific word; a candidate whose source is that
    word is the direct translation and should float above a candidate that
    merely shares the same German lemma.  Confidence always sorts first so
    exact/stem/fuzzy tiers fall out naturally; then query-source exactness
    (a direct translation beats an unrelated noun at equal confidence), then
    the noun/article/plural quality tier.  `freq` (optional callable
    lemma->ppm) breaks remaining ties toward the commoner German word.
    """
    base = rank_candidate(c)
    exact = (c.source or "").casefold() == query.casefold()
    conf = getattr(c, "confidence", 0.0)
    f = 0.0
    if freq is not None:
        f = freq(c.german) or 0.0
    return (-conf, 0 if exact else 1, base, -f)


def build_candidates(word: str, lang: str, dictionary, plural, builder,
                     wikt=None, max_candidates: int = 5,
                     total_cap: int = 18,
                     analyzers=None) -> list[CardCandidate]:
    """Foreign -> German candidates, searching ALL local indexes.

    We do not trust the detected language or the routing heuristic alone:
    the same string is searched as (1) an English word, (2) a Polish word,
    (3) a German word (DE-EN/DE-PL), and (4) through the kaikki reverse table.
    Candidates are merged, de-duplicated by German lemma (preferring the
    direct translation), and ranked by source-side confidence first.  Returns
    the best `max_candidates` plus any weaker-but-plausible candidates up to
    `total_cap`, each tagged with `.confidence` / `.method` so the UI can show
    certainty and let the user pick a deliberately weaker match.
    Wiktionary is consulted last if nothing local hit.
    """
    word = (word or "").strip()
    if not word:
        return []
    limit = max(max_candidates * 3, 12)
    cands: list[CardCandidate] = []
    seen: dict[str, CardCandidate] = {}   # german.casefold() -> candidate

    def _add(c: CardCandidate) -> None:
        if not c or not c.german:
            return
        k = c.german.casefold()
        prev = seen.get(k)
        if prev is None:
            seen[k] = c
            return
        # same German lemma twice: keep the higher-confidence source, but a
        # source that IS the query still wins outright.
        q = (word or "").casefold()
        if (c.source or "").casefold() == q and (prev.source or "").casefold() != q:
            seen[k] = c
        elif getattr(c, "confidence", 0.0) > getattr(prev, "confidence", 0.0):
            seen[k] = c

    # 1. foreign -> German (English and Polish indexes both)
    for lng in ("en", "pl"):
        for h in dictionary.lookup(word, lang=lng, limit=limit):
            _add(builder.enrich(h, lng))

    # 1b. real-morphology lemmas (spaCy / morfeusz2) re-searched as their own
    #     words: 'psami' -> morfeusz2 'pies' -> dict.cc/reverse 'pies'.  This
    #     is what lets an inflected Polish/English surface find the entry
    #     whose key is the base form.
    if analyzers is not None:
        for lng in ("en", "pl"):
            for lemma in analyzers.candidates(word, lng):
                if lemma.casefold() == word.casefold():
                    continue
                for h in dictionary.lookup(lemma, lang=lng, limit=limit):
                    c = builder.enrich(h, lng)
                    c.confidence = min(c.confidence, 0.92)
                    c.method = "lemma"
                    _add(c)
                for c in reverse_candidates(lemma, lng, plural, wikt=None):
                    # reverse-table hits reached ONLY via a morphologised lemma
                    # are guesses, not exact matches — cap them so they can't
                    # masquerade as 100%-confidence cards ('went' -> 'go' must
                    # NOT promote 'das Go' the board game above a real verb).
                    c.confidence = min(c.confidence, 0.92)
                    c.method = "lemma"
                    _add(c)

    # 2. the same string as a GERMAN word (DE-EN and DE-PL merged) — this is
    #    how lowercase German words and German words that missed routing are
    #    found: the indexes are keyed by casefolded text, so "geschichte"
    #    matches the "Geschichte {f}" entries.
    for h in dictionary.lookup_german(word, limit=limit):
        _add(_german_hit_candidate(h, plural))

    # 3. kaikki reverse-translation table
    for lng in ("en", "pl"):
        for c in reverse_candidates(word, lng, plural, wikt=None):
            _add(c)

    # 4. Wiktionary last resort (only when the local merge came up empty)
    if not cands and wikt is not None and lang in ("en", "pl"):
        for c in reverse_candidates(word, lang, plural, wikt):
            _add(c)

    ranked = sorted(seen.values(), key=lambda c: _rank_candidate(c, word,
                      (analyzers.de_freq if analyzers is not None else None)))
    # never return more than total_cap; max_candidates is handled at the UI
    # layer (strong tier = first max_candidates by confidence).
    return ranked[:total_cap]


def german_candidates(text: str, plural, dictionary=None, *, limit: int = 12,
                      analyzers=None) -> tuple[list[CardCandidate], dict]:
    """Build cards from a selected German word (lemma or inflected form).

    Translations come from the kaikki reverse table first; if fewer than a
    handful were found, the dict.cc DE-EN/DE-PL indexes are merged in too.
    Inflected surface forms ('ging', 'Häuser') are resolved to their canonical
    lemma — the kaikki index first, and when kaikki does not know the form,
    the DWDSmor FST (`analyzers`) backfills lemma + real POS + gender (and a
    best-effort plural for nouns).
    Returns the candidate list and the resolved lemma info dict (possibly {}).
    """
    w = text.strip()
    base = plural.resolve_info(w)
    info: dict = {}
    # Ordered German forms to card, each (display lemma, grammar dict, pos):
    #   noun  -> itself with article/plural ('Haus' -> 'das Haus')
    #   verb  -> bare infinitive first ('spricht' -> 'sprechen'), then any
    #            kaikki deverbal noun ('das Sprechen') as alternative group
    #   other -> bare lowercase base ('roten' -> 'rot', 'bessere' -> 'gut')
    forms: list[tuple[str, dict, str]] = []
    if base is None:
        # kaikki does not know this form — ask DWDSmor before heuristics.
        lemma = (plural.lookup_lemma(w) or {}).get("lemma") or w
        gram = plural.lookup(lemma) or {}
        used_dwds = False
        if not gram and analyzers is not None and analyzers.available.get("de"):
            # derive lemma + POS from the SAME analysis row so the lemmatizer
            # and the analyzer can't disagree ('groß' adj vs 'groß' verb).
            g_an = analyzers.analyze(w, "de")
            if g_an:
                g_lemma = g_an[0].get("lemma") or lemma
                g_pos = g_an[0].get("pos") or None
            else:
                g_lemma = analyzers.lemma_of(w, "de") or lemma
                g_pos = None
            if g_pos == "noun":
                g_pl = analyzers.de_plural(g_lemma)
                gram = {"gender": analyzers.de_gender(g_lemma) or "",
                        "article": analyzers.de_article(g_lemma),
                        "plural": g_pl or "",
                        "plural_article": "die" if g_pl else "",
                        "has_plural": bool(g_pl)}
                lemma = g_lemma
                forms.append((lemma, gram, "noun"))
            elif g_pos == "verb":
                forms.append((g_lemma, {}, "verb"))
                info = {"lemma": g_lemma}
            elif g_pos:
                forms.append((g_lemma, {}, g_pos))
                info = {"lemma": g_lemma}
            # else: dwds analysed but as an unknown/unsupported POS — leave
            # forms empty so the caller's fill logic decides; never fabricate
            # a bare 'noun' card for an unknown word.
            used_dwds = True
        if not used_dwds and not forms:
            forms.append((gram.get("lemma") or lemma, gram, "noun"))
        info = gram or info
    elif base["pos"] == "noun":
        # a noun base -> full noun grammar (article + plural): 'das Haus'
        gram = plural.lookup(base["lemma"]) or {}
        lemma = gram.get("lemma") or base["lemma"]
        forms.append((lemma, gram, "noun"))
        info = gram
    elif base["pos"] == "verb":
        # a verb -> the bare infinitive is the primary card ('spricht' ->
        # 'sprechen' "to speak"); a known kaikki deverbal noun ('das
        # Sprechen', 'das Gehen') becomes a further scrollable group.
        key = base.get("lemma_key") or base["lemma"]
        infinitive = base["lemma"]
        forms.append((infinitive, {}, "verb"))
        for nr in plural.deverbal_nouns(key):
            forms.append((nr["lemma"], nr, "noun"))
        info = {"lemma": infinitive}
    else:
        # adjective / adverb / other -> bare lowercase base word
        # ('roten' -> 'rot', 'bessere' -> 'gut', 'laufende' -> 'laufend')
        lemma = base.get("lemma") or w
        forms.append((lemma, {}, base["pos"]))
        info = {"lemma": lemma}
    if not forms:
        # dwdsmor analysed an unknown word with no usable POS — do NOT card a
        # phantom noun.  Caller falls back to the forward flow (app gate).
        return [], info
    primary = forms[0][0]
    conf = 0.92 if primary.casefold() != w.casefold() else 1.0
    groups_out: list[list[CardCandidate]] = [[] for _ in forms]
    claimed: set[tuple[str, str]] = set()
    has_deverbal = any(f[2] == "noun" for f in forms)

    def _place(gi: int, word: str, lang: str, *, h_pos: str = "",
               tags: str = "", h_conf: float = 1.0,
               h_method: str | None = None) -> None:
        """Add one candidate to group gi unless its (lang, source) is taken."""
        k = (lang, word.casefold())
        if k in claimed:
            return
        claimed.add(k)
        g_lemma, g_info, g_pos = forms[gi]
        pos = ("noun" if h_pos == "noun" else (h_pos or g_pos))
        groups_out[gi].append(CardCandidate(
            source=word,
            source_lang=lang,
            german=g_lemma,
            gender=g_info.get("gender", ""),
            article=g_info.get("article", ""),
            plural=g_info.get("plural", ""),
            plural_article=g_info.get("plural_article", ""),
            pos=pos,
            tags=tags,
            confidence=min(conf, h_conf),
            method=h_method or ("lemma" if conf < 1.0 else "exact"),
        ))

    # Claim order: noun groups first, so a shared kaikki sense ('speaking')
    # lands on 'das Sprechen' rather than the infinitive; verb/adjective
    # groups then take dict.cc plus whatever kaikki senses remain.
    order = ([i for i, f in enumerate(forms) if f[2] == "noun"] +
             [i for i, f in enumerate(forms) if f[2] != "noun"])
    for gi in order:
        g_lemma, g_info, g_pos = forms[gi]
        key = g_lemma.casefold()
        # the infinitive group skips kaikki when a deverbal group exists so
        # its sources never duplicate the noun card ('to speak' vs 'speaking')
        use_kaikki = bool(g_info) or not has_deverbal
        if use_kaikki:
            for t in plural.translations_of(key, limit=limit):
                word = clean_source(t["word"])
                if word:
                    _place(gi, word, t["lang"], h_pos=g_pos)
        if dictionary is not None and len(groups_out[gi]) < 4:
            for h in dictionary.lookup_german(key, limit=limit * 2):
                if g_pos == "verb" and h.pos != "verb":
                    continue
                if g_pos == "noun" and h.pos == "verb":
                    continue
                word = clean_source(h.german)
                if word:
                    _place(gi, word, h.target_lang, h_pos=h.pos,
                           tags=h.tags,
                           h_conf=getattr(h, "confidence", 1.0),
                           h_method=getattr(h, "method", None))
        # self row: the German word itself, only when it has grammar to show
        if g_info:
            _place(gi, g_lemma, "de", h_pos=g_pos)
    # safety: an empty infinitive group (no dict.cc rows, no leftover kaikki)
    # still shows the bare verb with its kaikki senses
    if not groups_out[0] and forms[0][2] == "verb":
        for t in plural.translations_of(forms[0][0].casefold(), limit=limit):
            word = clean_source(t["word"])
            if word:
                groups_out[0].append(CardCandidate(
                    source=word,
                    source_lang=t["lang"],
                    german=forms[0][0],
                    gender="", article="", plural="", plural_article="",
                    pos="verb", tags="", confidence=conf,
                    method="lemma" if conf < 1.0 else "exact"))
    return [c for group in groups_out for c in group], info
