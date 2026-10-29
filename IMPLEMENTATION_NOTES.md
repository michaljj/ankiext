# AnkiExt — Implementation & Project Notes

Comprehensive notes on what was built, how it works, key decisions, verified results, and important caveats. This is the single source of truth for the development session.

---

## 1. Project overview

**Goal:** A free, fully offline Windows tool that turns selected screen text into a proper German Anki card via one hotkey press.

**Flow:** select text → `Ctrl+Shift+D` → preview → **Add to Anki** (via AnkiConnect).

**Languages:** Polish → German and English → German, with the German side always carrying:
- **article / gender** (der/die/das)
- **plural** (plus plural article "die")

**Cost:** 100% free. No paid APIs, no accounts, no private data leaves the PC except into the local Anki.

---

## 2. Verified environment facts (probed live)

These were confirmed during planning and implementation on 2026-08-20:

| Item | Value |
|---|---|
| Python | 3.14.6 |
| tkinter | 8.6 (available, stdlib) |
| Anki | installed & running |
| AnkiConnect addon | id `2055492159`, responding on `http://127.0.0.1:8765` (verified version 6) |
| dict.cc files | 4 provided in `dict/` (user-owned, private-use license, never redistribute) |
| kaikki.org | de-extract + pl-extract available as free downloads |

### dict.cc files (in `dict/`)
| File | Pair | Size | Lines |
|---|---|---|---|
| `cngnfmgfbd-...-798euu.txt` | EN-DE | 73.8 MB | 1,313,662 |
| `cngnfmgbkg-...-798eu8.txt` | DE-EN | 73.8 MB | 1,313,662 |
| `cngnfmgobm-...-798eu9.txt` | PL-DE | 0.9 MB | 19,839 |
| `cngnfmgbbb-...-798eui.txt` | DE-PL | 0.9 MB | 19,839 |

**dict.cc format:** tab-separated `source \t target \t pos \t [subject tags]`, `#`-prefixed headers, HTML entities (`&#945;` = α), gender markers `{m}/{f}/{n}` embedded directly on German terms. The `<...>` notation is abbreviations/alt-forms — **NOT plurals**.

---

## 3. Data sources & strategy

### Hybrid dictionary (the core insight)
1. **dict.cc** (local txt files) → translation + **article** instantly. EN-DE alone is 1.3M pairs.
2. **kaikki German Wiktionary extract** (`de-extract.jsonl.gz`, 302 MB) → **plural** + gender enrichment. Its inflection forms carry the article verbatim:
   ```json
   {"form":"Haus",  "tags":["nominative","singular"],"article":"das"}
   {"form":"Häuser","tags":["nominative","plural"],  "article":"die"}
   ```
3. **kaikki reverse-translation table** (EN/PL → German lemma) → canonical single-word German results when dict.cc only has phrases.

### key URLs
```
https://kaikki.org/dictionary/downloads/de/de-extract.jsonl.gz   (302 MB)
https://kaikki.org/dictionary/downloads/pl/pl-extract.jsonl.gz   (125 MB)
```
Sail: the base path is `https://kaikki.org/dictionary/...` (not `/downloads/` at root).

### sample kaikki German entry (verified)
`Haus`: gender `n`, article `das`, plural `Häuser` (die); also lists English translations (`house`, `home`).

---

## 4. Project structure

```
AnkiExt/
├── app.py                    # main entry: tray + hotkey + full pipeline
├── anki_connect.py           # AnkiConnect REST client (stdlib urllib)
├── capture.py                # Windows global hotkey hook (ctypes, no deps)
├── clipboard.py              # clipboard read/write via tkinter
├── detect_lang.py            # PL vs EN detection (diacritics + stopwords + dict hint)
├── config.py                 # config.toml loader
├── config.toml               # all settings (hotkey, deck, model, paths)
├── cli_lookup.py             # CLI lookup demo
├── cli_smoke.py              # CLI: lookup+enrich+add notes to Anki (idempotent)
├── cli_cleanup.py            # CLI: delete test notes from deck
├── dict/                     # user's dict.cc files (gitignored)
├── dictlookup/
│   ├── entities.py           # HTML decode, gender->article, term cleanup
│   ├── search.py             # SQLite index + exact/prefix query
│   ├── lookup.py             # high-level facade (Dictionary)
│   ├── matcher.py            # multi-tier confidence-scored matching
│   └── morphology.py         # offline light lemmatizer (EN/PL)
├── german/
│   ├── grammar.py            # extract article/plural from kaikki entries
│   ├── build_plural_db.py    # one-time build of data/plural.db (+ inflections index)
│   └── plural.py             # query API + reverse_lookup + resolve_form
├── cards/
│   ├── builder.py            # TranslationHit -> CardCandidate (+ ranking)
│   └── anki_setup.py         # idempotent deck/model creation
├── ui/
│   ├── preview.py            # tkinter edit window (+ confidence + weaker toggle)
│   └── tray.py               # tray (pystray) or tk fallback
├── fallback/
│   └── wiktionary_api.py     # optional keyless Wiktionary API (cached)
├── data/                     # local SQLite indexes + de-extract (gitignored)
├── tests/                    # stdlib-unittest suite + discovery runner
├── research/                 # scratch/probe scripts (not shipped)
└── README.md                 # user-facing docs
```

---

## 5. Verification results

### Cross-language lookups (verified end-to-end)

| Source | Lang | German card | Plural |
|---|---|---|---|
| house | en | das Haus | die Häuser |
| dog | en | der Hund | die Hunde |
| pies | pl | der Hund | die Hunde |
| kot | pl | die Katze | die Katzen |
| dom | pl | das Haus | die Häuser |
| okno | pl | das Fenster | die Fenster |
| window | en | das Fenster | die Fenster |
| sun | en | die Sonne | die Sonnen |
| moon | en | der Mond | die Monde |
| book | en | das Buch | die Bücher |

### Test suite
- **57 tests pass** across `test_entities.py`, `test_lookup.py`, `test_plural_db.py`,
  `test_cards.py`, `test_fixes.py`, and `test_matching.py` (new: scoring tiers,
  morphology, engine inflection flow). Plus headless app-flow tests in
  `research/test_app_flow.py` (not part of default runner).
- Run with: `python tests/run_tests.py` (stdlib unittest, no pip required).
- **Verified smart-match cases:** `went`/`goes` → "gehen" (stem), `drank` →
  "Getränk"/"Trinken", `ran` → "Lauf" (stem), `ging` → **Gehen** (inflection),
  `Häuser` → **Haus → house/dom**, `gelaufen` → **Laufen** (inflection).

### Live AnkiConnect smoke test
- Created deck `German::Vocabulary` and model `AnkiExt Card` (fields: `Word`, `Plural`, `Source`, `SourceLang`, `extra`; templates Recognition + Production).
- Added **23 real cards** during testing — all correctly formatted (e.g. `das Haus | die Häuser | house | en`).
- Duplicate detection (`canAddNotes`) works (skips already-present notes).
- Cleanup: `python cli_cleanup.py --all --yes` removes them.

### App startup
- `app.py` launches cleanly, prints `AnkiExt running — press ctrl+shift+d ...`, tray + hotkey hook active. Verified process stays up, then stopped.

---

## 6. Key implementation details & decisions

### Language detection
- Polish diacritics (`ąćęłńóśźż`) → PL.
- Polish stopwords / verb-infinitive endings (`-ać/-eć/-ić/-yć`) → PL.
- **Dictionary hint** for bare words with no diacritics: word has an exact PL-DE match **and** no exact EN-DE match → PL. Fixes `dom`, `okno`, `mleko`, `dziewczyna`.
- Known limitation: collision words present in both languages (e.g. `pies` = EN "pastry" + PL "dog") resolve to EN. Acceptable heuristic tradeoff; user can override in preview.

### Article & plural derivation
- dict.cc gender `{m}/{f}/{n}` → `der/die/das`; `{pl}`-only → `die`; mixed `{f} {m}` → `der/die` (ambiguous → no article prefix).
- kaikki German inflection forms provide plural + plural article directly (authoritative).

### Candidate ranking
- Priority: single-word nouns with article+plural → multi-word nouns with article+plural → nouns with article → nouns → non-nouns.
- **Reverse-translation candidates merged first** so canonical words (e.g. `die Sonne`) beat dict.cc phrase matches (`Sonnenatmosphäre`).
- **Confidence first**: candidates now sort by source-side match confidence, so exact/stem/fuzzy tiers fall out naturally.

### Smart matching (inflection / fuzzy resolution)
The matching core (`dictlookup/matcher.py` + `morphology.py`) stages several
strategies and scores every candidate with a certainty `0.0–1.0` and a method tag:
| stage | confidence | what it matches |
|---|---|---|
| exact | 1.00 | normalized key present |
| accent | 0.95 | diacritics-only difference |
| lemma/stem | 0.90–0.92 | irregular (went→go), participle (gegangen→gehen), stem (drank→drink) |
| prefix | 0.60–0.80 | key that starts with the query |
| fuzzy | 0.50–1.00 | edit-distance within a bounded prefix window |

Fuzzy matching is bounded to a narrow prefix window (never a full 1.3M-row scan).
`morphology.py` is a lightweight offline lemmatizer: a small English irregular
table (`went→go`, `children→child`, `drank→drink`…) plus suffix rules, and a
conservative Polish noun-ending strip. Every derived stem is validated against
the target index before it's kept, so a bad guess never surfaces.
German inflected forms come from the kaikki **`inflections` index** (built by
`german.build_plural_db` into `data/plural.db`) — `german/plural.py:resolve_form`
maps `ging`→`gehen`, `Häuser`→`Haus`, `Händen`→`Hand` for any POS (noun/verb/adj).

### Candidate tiers in the UI
`build_candidates` returns up to `total_cap` (default 15) candidates, ranked by
confidence. `ui/preview.py` shows the top `ui.max_candidates` (default 5) by
default and exposes a **"Show weaker matches (N)"** toggle to reach the
lower-confidence tail — the "option to view and choose the less matching one".

### Bugs found & fixed during dev
| Bug | Fix |
|---|---|
| `dotmap dotland` config mismatch (flat vs nested TOML) | `Dictionary` accepts both; reads `cfg["dictionary"]` if present |
| Console mojibake (cp1252) | `sys.stdout.reconfigure(encoding="utf-8")` in CLIs |
| `{m}/{f}` gender marker included in index key → exact-match failed | `has_exact` compares cleaned term via `extract_gender` |
| kaikki "blank stub" entries clobbered real nouns (INSERT OR REPLACE) | skip entries with no grammar; keep most-complete per lemma via `_completeness` |
| double article "der der Hund" | `word_field` avoids prefix if term already starts with article; preview `_split_article` |
| mixed article `die/der` → prefixed | skip prefix if article contains `/` |
| `ctypes.wintypes.ULONG_PTR` missing | use `ctypes.c_void_p` in `KBDLLHOOKSTRUCT` |
| AnkiConnect `createModel` template keys must be `Name/Front/Back` (not `name/qfmt/afmt`) | fixed `anki_setup.MODEL_TEMPLATES` |

---

## 7. Anki model / templates

**Model:** `AnkiExt Card` (auto-created via AnkiConnect if missing)
- Fields: `Word`, `Plural`, `Source`, `SourceLang`, `extra`
- CSS: `.card { font-family: Arial; font-size: 20px; text-align: center }`

**Recognition card** (front German):
```
{{Word}}{{#Plural}}<br>({{Plural}}){{/Plural}}
```
**Production card** (front source):
```
{{Source}}
```

**Deck:** `German::Vocabulary` (configurable in `config.toml` under `[anki]`).

---

## 8. Important caveats & known issues

1. **pip is sandbox-blocked in this dev environment** → `keyboard` / `pystray` are not installed. The app runs 100% on stdlib (ctypes hotkey hook + tkinter tray fallback). On a normal machine, `pip install -r requirements.txt` enables the native tray icon.
2. **dict.cc files are private-use only** (license). Never distribute them. They're gitignored (`dict/*.txt`).
3. **kaikki data** is CC BY-SA licensed Wiktionary content — fine for personal use.
4. **A `.venv-tmp/` folder** (leftover from failed pip attempts) could not be fully deleted by the sandbox; it's gitignored and harmless — delete manually via file explorer if desired.
5. **`survey: mleko`/`okno`** detection works via dict hint, `pies`/`kot domowy` collide → EN (override in preview).
6. **German `Mann`** plural in kaikki shows `Mannen` (older form) — for most users `Männer` is expected. This comes directly from data; verify unusual plurals in the preview.
7. **Locale/encodings:** all files read/written as UTF-8; terms NFC-normalized.
8. **`data/plural.db` now carries an `inflections` table** (form→lemma) built from
   kaikki — rebuild required to pick it up (`python -m german.build_plural_db`).
9. **Matching is heuristic, not perfect:** fuzzy/stem guesses are labelled with a
   confidence %, and the "Show weaker matches" toggle makes the trade-off
   explicit. Low-confidence suggestions can still be wrong — verify before adding.

### Smart-matching residual risks (tracked)
- **Confidence is heuristic, not calibrated** — a `0.9` stem guess can still be wrong
  (e.g. `ran` is both EN "run/past" *and* PL "wound"). Mitigated by the visible % and
  the weaker-toggle; sanity-check low-confidence cards.
- **English irregular table is hand-maintained & open-ended** — `went→go`, etc. expand
  coverage but don't cover every verb; the stem + fuzzy tiers are the safety net.
- **German lowercase-verb routing** relies on `resolve_form` in `_german_candidate`;
  a lowercase string that is also a German inflected form can still misroute to the
  forward flow. Mitigated by the all-index fallback in `build_candidates`.
- **`inflections` uses `INSERT OR IGNORE`** — for a surface form shared by several
  lemmas, the first-seen lemma wins; `resolve_form` prefers a noun-lemma when present.
- **`has_key`/morphology acceptance** depends on the index's key coverage; stems that
  don't index are safely dropped (occasionally less recall).

---

## 9. How to run (quick reference)

```bash
# 1. Build the German plural DB (one-time; downloads 302 MB, takes ~10 min)
python -m german.build_plural_db

# 2. Run the tool
python app.py

# 3. Select text anywhere, press Ctrl+Shift+D → preview → Add to Anki
```

```bash
# Utilities
python cli_lookup.py house          # offline lookup demo (en)
python cli_lookup.py pies pl        # offline lookup demo (pl)
python cli_smoke.py --dry-run       # show candidates without adding
python cli_smoke.py                 # add sample cards (idempotent)
python cli_cleanup.py --all --yes   # delete the AnkiExt-model test notes
python tests/run_tests.py           # full self-test suite
```

---

## 10. config.toml settings

| Key | Purpose | Default |
|---|---|---|
| `hotkey.combos` | global hotkey | `["ctrl+shift+d"]` |
| `dictionary.dict_dir` | dict.cc folder | `dict` |
| `dictionary.en_de/pl_de/de_en/de_pl` | the 4 txt filenames | (see file) |
| `dictionary.kaikki_de_url/gz` | kaikki download source | (see file) |
| `dictionary.plural_db` | plural index path | `data/plural.db` |
| `anki.host/port` | AnkiConnect endpoint | `127.0.0.1:8765` |
| `anki.deck` | destination deck | `German::Vocabulary` |
| `anki.model` | card model | `AnkiExt Card` |
| `languages.polish_diacritics` | PL detection chars | `ąćęłńóśźżĄĆĘŁŃÓŚŹŻ` |
| `ui.max_candidates` | strong candidates shown by default | `5` |
| `matching.total_cap` | total candidates built (strong + weaker tail) | `15` |

---

## 11. Phase completion status

| Phase | Description | Status |
|---|---|---|
| 1 | dict.cc loader + gender→article + tests | ✅ done |
| 2 | kaikki plural DB (120,164 nouns + EN/PL reverse index) + tests | ✅ done |
| 3 | card builder + AnkiConnect client + live smoke test | ✅ done |
| 4 | capture/UI (hotkey, clipboard, detect, preview, tray) | ✅ done |
| 5 | reverse-translation fallback + Wiktionary API optional | ✅ done |
| 6 | smart matching (inflection/fuzzy resolution + confidence tiers) | ✅ done |
| 7 | e2e verification + README.md | ✅ done |

**Remaining future work (optional):**
- Package as `.exe` via pyinstaller (`--onefile --noconsole`).
- Polish multi-word disambiguation (currently defaults to EN on collisions).
- Verify `Mann`-style irregular plurals against preferred forms.
- Add audio (the "German Forvo" addon is already installed in Anki for that).
- Tune fuzzy threshold / per-language morphology as real-word coverage grows.

---

*Notes compiled 2026-08-20, updated for smart matching, into a single reference file.*