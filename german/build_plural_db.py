"""Build the German plural DB from the kaikki German Wiktionary extract.

Downloads de-extract.jsonl.gz (if missing) and streams it into a SQLite DB:
  plural_db(lemma TEXT PRIMARY KEY, gender TEXT, article TEXT,
            plural TEXT, plural_article TEXT, has_plural INT)

Usage:  python -m german.build_plural_db
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from pathlib import Path

from .grammar import extract_noun

DEFAULT_URL = "https://kaikki.org/dictionary/downloads/de/de-extract.jsonl.gz"


def normalize_lemma(text: str) -> str:
    """Normalize a translation word / surface form for keying.

    Strips junk ([...], <...>, {...}, HTML entities), strips trailing
    punctuation from declined forms (e.g. 'bitte!'), NFC, casefolds.
    """
    text = unicodedata.normalize("NFC", text or "").strip()
    text = re.sub(r"\[[^]]*\]", "", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"[!?.,;:]+$", "", text)
    text = text.strip()
    return text.strip().casefold()


def clean_word(text: str) -> str:
    """Clean a headword for *display*, like normalize_lemma but WITHOUT
    case-folding (so 'Haus' stays 'Haus' and 'laufen' stays 'laufen')."""
    text = unicodedata.normalize("NFC", text or "").strip()
    text = re.sub(r"\[[^]]*\]", "", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"[!?.,;:]+$", "", text)
    return text.strip()


def _completeness(row: tuple) -> int:
    """Score how complete a noun row is (lemma, gender, article, plural,...)."""
    return sum(1 for x in row[1:5] if x)


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"using cached {dest} ({dest.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
        return
    print(f"downloading {url} ...", file=sys.stderr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "anki-ext/0.1"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="", file=sys.stderr)
    print("\ndownload complete", file=sys.stderr)
    return dest


def build(gz_path: Path, db_path: Path, gz_url: str = DEFAULT_URL) -> int:
    # download the kaikki extract if not already present
    if not gz_path.exists():
        download(gz_url, gz_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE nouns ("
        "lemma TEXT PRIMARY KEY, gender TEXT, article TEXT, "
        "plural TEXT, plural_article TEXT, has_plural INT)"
    )
    conn.execute("CREATE INDEX idx_nouns_lemma ON nouns(lemma)")
    # reverse-lookup table: source word (EN/PL) -> German lemma
    conn.execute("CREATE TABLE trans ("
                 "src_lang TEXT, src_word TEXT, de_lemma TEXT, PRIMARY KEY(src_lang, src_word, de_lemma))")
    conn.execute("CREATE INDEX idx_trans_src ON trans(src_lang, src_word)")
    # inflected-form index: surface form (noun/verb/adjective...) -> lemma.
    # This is what lets us resolve "ging" → "gehen" / "Häuser" → "Haus".
    # lemma is the case-folded key; lemma_display is the original-case headword
    # and pos tells us noun vs adjective/verb so an inflected adjective resolves
    # to its base ('roten' → "rot", not the noun "Rota") rather than a homograph.
    conn.execute("CREATE TABLE inflections ("
                 "inflection TEXT, lemma TEXT, lemma_display TEXT, pos TEXT, "
                 "PRIMARY KEY(inflection, lemma, pos))")
    conn.execute("CREATE INDEX idx_infl_lookup ON inflections(inflection)")
    # every German headword (any POS) -> own lemma/pos, so a surface that is
    # itself a dictionary headword (e.g. "bereit", "rot", "gut") resolves to
    # itself instead of being redirected to a spurious inflection row.
    conn.execute("CREATE TABLE lemmas ("
                 "lemma TEXT, lemma_display TEXT, pos TEXT, "
                 "PRIMARY KEY(lemma, lemma_display))")

    count = 0
    nouns = 0
    seen: dict[str, tuple] = {}
    translations_batch: list[tuple] = []
    infl_batch: list[tuple] = []
    lemmas_batch: list[tuple] = []
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("lang_code") != "de":
                continue
            lemma = normalize_lemma(obj.get("word", ""))
            if not lemma:
                continue
            pos = obj.get("pos", "")
            lemma_display = clean_word(obj.get("word", "")) or lemma
            lemmas_batch.append((lemma, lemma_display, pos))
            if len(lemmas_batch) >= 50000:
                _insert_lemmas(conn, lemmas_batch)
            # collect translations (EN + PL) for the reverse index
            if pos == "noun":
                for t in obj.get("translations", []) or []:
                    tc = t.get("lang_code")
                    tw = normalize_lemma(t.get("word", ""))
                    if tc in ("en", "pl") and tw:
                        translations_batch.append((tc, tw, lemma))
                if len(translations_batch) >= 20000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO trans (src_lang, src_word, de_lemma) VALUES (?,?,?)",
                        translations_batch,
                    )
                    translations_batch = []

            # inflected-form index: map every non-identical surface form back
            # to its lemma (only single-token-ish surface forms, not phrases).
            _inflected_entry(conn, infl_batch, obj, lemma, lemma_display, pos)

            if pos != "noun":
                continue
            info = extract_noun(obj)
            if not info:
                continue
            # skip completely-empty entries (e.g. a stub that would clobber the real noun)
            if not (info.gender or info.article or info.plural):
                continue
            row = (info.lemma, info.gender, info.article,
                   info.plural, info.plural_article, int(info.has_plural))
            # keep the most complete entry per lemma
            cur = seen.get(info.lemma)
            if cur is None:
                seen[info.lemma] = row
            elif _completeness(row) > _completeness(cur):
                seen[info.lemma] = row
            nouns += 1
            if count % 500_000 == 0:
                print(f"  processed {count:,} lines, {nouns:,} nouns", file=sys.stderr)
    if translations_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO trans (src_lang, src_word, de_lemma) VALUES (?,?,?)",
            translations_batch,
        )
    if infl_batch:
        _insert_inflections(conn, infl_batch)
    if lemmas_batch:
        _insert_lemmas(conn, lemmas_batch)
    batch = list(seen.values())
    conn.executemany(
        "INSERT OR REPLACE INTO nouns "
        "(lemma, gender, article, plural, plural_article, has_plural) "
        "VALUES (?,?,?,?,?,?)",
        batch,
    )
    conn.commit()
    inf_cnt = conn.execute("SELECT COUNT(*) FROM inflections").fetchone()[0]
    conn.close()
    print(f"done: {count:,} lines -> {len(batch):,} noun entries, "
          f"{inf_cnt:,} inflection mappings in {db_path}", file=sys.stderr)
    return len(batch)


def _inflected_entry(conn, batch, obj, lemma, lemma_display, pos):
    """Append surface-form->lemma rows from one kaikki `forms[]` array."""
    for f in obj.get("forms") or []:
        form = normalize_lemma(f.get("form", ""))
        # skip phrases / multiword forms and self-references
        if not form or " " in form or form == lemma or len(form) > 48:
            continue
        batch.append((form, lemma, lemma_display, pos))
        if len(batch) >= 20000:
            _insert_inflections(conn, batch)


def _insert_inflections(conn, batch) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO inflections "
        "(inflection, lemma, lemma_display, pos) VALUES (?,?,?,?)",
        batch,
    )
    batch.clear()


def _insert_lemmas(conn, batch) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO lemmas (lemma, lemma_display, pos) VALUES (?,?,?)",
        batch,
    )
    batch.clear()


if __name__ == "__main__":
    from config import load_config

    cfg = load_config()
    dic = cfg["dictionary"]
    url = dic.get("kaikki_de_url", DEFAULT_URL)
    gz = Path(dic.get("kaikki_de_gz", "data/de-extract.jsonl.gz"))
    db = Path(dic.get("plural_db", "data/plural.db"))
    build(gz, db, url)