"""Free Wiktionary fallback: keyless MediaWiki API lookups with disk cache.

Used when the local dict.cc + kaikki combination misses a word.  Queries
en.wiktionary.org or pl.wiktionary.org for a German translation, and
de.wiktionary.org for German grammar (article/plural) when needed.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "anki-ext/0.1 (personal vocabulary tool)"
API = {"en": "https://en.wiktionary.org/w/api.php",
       "pl": "https://pl.wiktionary.org/w/api.php",
       "de": "https://de.wiktionary.org/w/api.php"}


class WiktionaryAPI:
    """Small, cached client for the MediaWiki parse API."""

    def __init__(self, cache_path: Path | str = "data/wikt_cache.sqlite",
                 min_wait: float = 0.5):
        self.min_wait = min_wait
        self._last = 0.0
        self._cache_path = Path(cache_path)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the object may be constructed on the main
        # thread at startup while lookups run on the lookup worker thread.
        self.conn = sqlite3.connect(str(self._cache_path), check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS cache "
                          "(lang TEXT, title TEXT, text TEXT, PRIMARY KEY(lang, title))")

    def _rate_limit(self) -> None:
        wait = self._last + self.min_wait - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def fetch(self, lang: str, title: str) -> str:
        """Return plain wikitext for a page, using the disk cache."""
        key = (lang, title)
        row = self.conn.execute("SELECT text FROM cache WHERE lang=? AND title=?",
                                key).fetchone()
        if row:
            return row[0]
        self._rate_limit()
        url = (API[lang] + "?action=parse&page=" + urllib.parse.quote(title)
               + "&prop=wikitext&format=json&formatversion=2")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            wikitext = data.get("parse", {}).get("wikitext", "") or ""
        except Exception as e:
            print(f"  [wkt] fetch error for {lang}:{title}: {e}", file=__import__("sys").stderr)
            wikitext = ""
        self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                          (lang, title, wikitext))
        self.conn.commit()
        return wikitext

    def close(self) -> None:
        self.conn.close()

    def german_translation(self, word: str, src_lang: str) -> dict | None:
        """Best-effort: translate a foreign word to German via Wiktionary.

        Queries the source-language wiki for `word`, scans its translation
        templates for a German (de) entry, then fetches that German page for
        the article/plural.  Returns a plural-DB-shaped dict
        {lemma, gender, article, plural, plural_article, has_plural} or None.
        Kept rate-limited and disk-cached via fetch().
        """
        if src_lang not in ("en", "pl"):
            return None
        text = self.fetch(src_lang, word)
        if not text:
            return None
        # Translation entries look like {{t|de|Hund}} / {{t+|de|Haus|n|...}}
        m = re.search(r"\{\{t\+?\|de\|([^|}]+)", text)
        if not m:
            return None
        lemma = re.sub(r"\{\{.*?\}\}", "", m.group(1)).split("|")[0].strip()
        if not lemma:
            return None
        de_text = self.fetch("de", lemma)
        decl = parse_german_declension(de_text) if de_text else {}
        return {
            "lemma": lemma,
            "gender": decl.get("gender", ""),
            "article": decl.get("article", ""),
            "plural": decl.get("plural", ""),
            "plural_article": decl.get("plural_article", ""),
            "has_plural": bool(decl.get("plural")),
        }


# --- German grammar extraction from German Wiktionary wikitext -------------
def parse_german_declension(wikitext: str) -> dict:
    """Best-effort parse of article + plural from German noun wikitext."""
    out = {"article": "", "plural": ""}
    if not wikitext:
        return out
    # look for the declension template: {{Deutsch Nomen überblich ...}} or
    # the inflected forms like |Nominativ Singular=der Hund|Nominativ Plural=die Hunde
    m = re.search(r"\{\{Deutsch\s+Nomen\s+überblick[^}]*\}\}", wikitext)
    art_m = re.search(r"\|\s*Artikel\s*=\s*(\{\{[^}]+\}\}|der|die|das)", wikitext)
    if art_m:
        art = art_m.group(1)
        m2 = re.search(r"(der|die|das)\s*$", art)
        if m2:
            out["article"] = m2.group(1)
    # Look for a line: |2=|der Hund   or   {{Nominativ|der|Hund}} ...
    plural_m = re.search(r"\|\s*(?:Plural|Mehrzahl)\s*=\s*([^|\n}]+)", wikitext)
    if not plural_m:
        plural_m = re.search(r"\{\{Nominativ\s*\}\}\s*\|\s*(der|die|das|eine|ein)\s*\|\s*([^}|\n]+)",
                             wikitext)
        if plural_m:
            out["plural"] = plural_m.group(2).strip()
    else:
        out["plural"] = plural_m.group(1).strip()
    # clean template braces from captured values
    for k in out:
        out[k] = re.sub(r"\{\{[^}]*\}\}", "", out[k]).strip()
    return out