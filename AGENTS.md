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
│   ├── analyzers.py          # unified real-morphology facade (spaCy/morfeusz2/DWDSmor)
│   └── morphology.py         # offline light lemmatizer (EN/PL) — fallback
├── german/
│   ├── grammar.py            # extract article/plural from kaikki entries
│   ├── build_plural_db.py    # one-time build of data/plural.db (+ inflections index)
│   ├── plural.py             # query API + reverse_lookup + resolve_form + deverbal_nouns
│   └── dwdsmor.py            # optional DWDSmor FST adapter (real German morphology)
├── cards/
│   ├── builder.py            # TranslationHit -> CardCandidate (+ ranking)
│   └── anki_setup.py         # idempotent deck/model creation
├── ui/
│   ├── preview.py            # grouped candidate tree + editable card fields
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
- **103 tests pass** (99 prior + 4 new) across `test_entities.py`, `test_lookup.py`,
  `test_plural_db.py`, `test_cards.py`, `test_fixes.py`, `test_matching.py`, plus
  the new `test_analyzers.py`, `test_dwdsmor.py`, and `test_fuzzy_dl.py`.
  Real-engine cases use `@skipUnless(HAS_…)` so the suite is green both **with
  and without** spaCy/morfeusz2/dwdsmor installed. Plus headless app-flow tests
  in `research/test_app_flow.py` (not part of default runner).
- Run with: `python tests/run_tests.py` (stdlib unittest, no pip required).
- **Verified smart-match cases:** `went`/`goes` → "gehen" (stem), `drank` →
  "Getränk"/"Trinken", `ran` → "Lauf" (stem), `ging` → **gehen** (infinitive,
  with `das Gehen` as alternative group), `spricht` → **sprechen** ("to
  speak", not "das Sprechen"; `das Sprechen` still reachable), `Häuser` →
  **Haus → house/dom**, `gelaufen` → **laufen** (with `das Laufen` alt),
  `roten` → **rot** (base word, not "Rota"), `bessere`/`besten` → **gut**,
  `laufende` → **laufend** (base-word fix in card preview).
- **New morphology-verified cases (engines installed):** `fuehlen` →
  `fühlen` (orthvar via umlaut-variant), `went` → `gegangen`/`gingen` (exact;
  the diacritic/lemma re-search finds the verb, NOT "das Go"),
  `psami` → `der Hund / die Hunde` (morfeusz2 lemma, capped 0.92),
  `dziewczyny` → `das Mädchen` (morfeusz2), `grosse` → `groß` adj
  (DWDSmor), `Hunden` → `Hund` noun ↔ dog (DWDSmor POS/gender).

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
| exact | 1.00 | CLEANED normalised key present ('Haus' matches 'haus {n} [Gebäude]') |
| accent | 0.95 | diacritics-only difference |
| orthvar | 0.93 | umlaut digraph variants (`fuehlen`→`fühlen`, `ueber`→`über`) |
| lemma/stem | 0.90–0.92 | irregular (went→go), participle (gegangen→gehen), stem (drank→drink); real lemmas from spaCy/morfeusz2/DWDSmor |
| prefix | 0.60–0.80 | clean key that starts with the query |
| fuzzy | 0.50–0.93 | OS-Alignment edit distance (adjacent transposition = 1), length-aware |

**Real morphology engines (optional, per-language):** `dictlookup/analyzers.py`
is a unified lazy facade over three engines, with the old heuristic morphology
as the exact fallback when one is absent:
- **EN → spaCy** (`en_core_web_sm`): `went`→go VERB VBD, `children`→child,
  `better`→well (ADV) *plus* our table supplement `good`. Suffix rules remain
  fallback when the model is missing.
- **PL → morfeusz2**: whole-token lemmas from real Polish tag sets —
  `psami`→pies, `dziewczyny`→dziewczyna, `biegnę`→biec, `domach`→dom.
  Movable-clitic verb forms (which morfeusz2 splits into stem + `-m/-ś/
  -śmy/-ście` aglt segments) are **re-merged into one whole-token reading**,
  so `proponowaliśmy`→`proponować`, `zrobiliście`→`zrobić`,
  `widziałem`→`widzieć`, `poszedłbym`→`pójść` (their `praet` past tags also
  fold the aglt person `pri`/`sec`/`ter` back in).
- **DE → DWDSmor** (`german/dwdsmor.py`, FST): real lemma + POS + gender —
  `ging`→gehen V, `Hunden`→Hund NN Masc Dat Pl, `grosse`→groß ADJ.  Open-edition
  automata ship via PyPI; `_raw_analyses` resolves lemma+POS, `plural_of` in
  generates an NN nominative-plural **only when it actually produces one**.

The facade feeds the matcher's lemma tier (each candidate validated against
the index), `engine.build_candidates` re-searches real lemmas as their own
words, and `engine.german_candidates` uses DWDSmor as the second-chance German
resolver when the kaikki `inflections` index misses a form.  `freq_rank` uses
DWDSmor's tiny `ppm.csv` sample (108 lemmas) as a ranking tie-break.

Every derived stem is validated against the target index before it's kept, so a
bad guess never surfaces. German inflected forms come from the kaikki
**`inflections` index** first (built by `german.build_plural_db` into
`data/plural.db`) — `german/plural.py:resolve_form` maps `ging`→`gehen`,
`Häuser`→`Haus`, `Händen`→`Hand` for any POS (noun/verb/adj); DWDSmor backfills
the forms kaikki does not list.

The index now stores `(inflection, lemma, lemma_display, pos)` plus a `lemmas`
table (every German headword → its own pos), so `plural.resolve_info` shows the
**true base word** in the card preview instead of a wrong homograph:
- capitalized surface → prefers a noun base (`Häuser`→`Haus`, `Hunde`→`Hund`,
  `Tagen`→`Tag`); plurals are not themselves noun lemmas, so they reduce.
- lowercase surface (adjective/verb declension) → prefers a non-noun base, so
  `roten`→**rot** (not the noun "Rota"), `bessere`/`besten`→**gut** (not "Gut"),
  `laufende`→**laufend**. Ties break on shorter headword (frequency proxy).
- when the surface is its own headword (any POS) the candidate's relation
  decides: a prefix-compound (`laufen`→`eislaufen`) or same-surface different-
  POS homograph (`gut` adj vs `Gute` noun, `bereit` vs `bereiten`) keeps the
  headword, while an inflectional ending of the same POS (`geht`→`gehen`) or a
  different stem (`ging`→`gehen`, `besten`→`gut`) reduces.
- verbs show the **bare infinitive** as the primary card (`spricht`→`sprechen`
  "to speak", `ging`→`gehen`); a known kaikki deverbal noun becomes an
  alternative card group in the same preview (`das Sprechen` → "speaking",
  `das Gehen`, `das Laufen`), so the user can scroll between "to speak" and
  "speech".  Adjectives/other POS show the bare lowercase base.

### Candidate tiers in the UI
`build_candidates` returns up to `total_cap` (default 15) candidates, ranked by
confidence. `ui/preview.py` shows them in a **grouped, expandable tree**: one
parent row per German word form (e.g. `das Haus` noun, `sprechen` verb,
`das Sprechen` deverbal noun) with one child row per proposed en-de/pl-de
translation pair — clicking a row fills the card fields, so the German word
switches with the selected match.  A **Show** filter (`all`/`en`/`pl`/`de`)
hides pairs of other languages, and the **"Show weaker matches (N)"** toggle
visibly adds/removes the lower-ranked groups beyond `ui.max_candidates`
(default 5) — the "option to view and choose the less matching one".

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
| German verb inflection rendered the deverbal noun (`spricht`→`das Sprechen` "speech", `ging`→`das Gehen`) | verb branch of `german_candidates` now emits the bare infinitive (`sprechen`/`gehen`) as the primary card; the deverbal noun becomes an alternative group via `plural.deverbal_nouns` |
| "Show weaker matches" toggle appeared dead (same candidate re-rendered) | preview replaced with a grouped tree: the toggle now adds/removes the weak groups, and a Show filter en/pl/de hides pairs of other languages |
| Polish movable-clitic verbs (`proponowaliśmy`, `zrobiliście`, `widziałem`) produced *no* morfeusz2 analysis | `_pl_analyses` dropped every morfeusz2 row whose orth ≠ the whole token; morfeusz2 splits these forms into stem + `-m/-ś/-śmy/-ście` aglt segments. It now re-merges contiguous segments that tile the token into one whole-token reading, and folds the aglt person (`pri`/`sec`/`ter`) back into the tag. `praet`/`imps`/`pant`/`pcon` added to `_PL_TAG_POS` so past-tag verbs read as `verb`, not `other` |

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

1. **`keyboard`/`pystray` were not installed** in the dev environment; the app runs on stdlib (ctypes hotkey hook + tkinter tray fallback). The **optional morphology engines were installed and verified** here (dwdsmor 0.18.0, spaCy en_core_web_sm, morfeusz2). On another machine, `pip install -r requirements.txt` adds the native tray + the three engines.
2. **dict.cc files are private-use only** (license). Never distribute them. They're gitignored (`dict/*.txt`).
3. **kaikki data** is CC BY-SA licensed Wiktionary content — fine for personal use.
4. **A `.venv-tmp/` folder** (leftover from failed pip attempts) could not be fully deleted by the sandbox; it's gitignored and harmless — delete manually via file explorer if desired.
5. **`survey: mleko`/`okno`** detection works via dict hint, `pies`/`kot domowy` collide → EN (override in preview).
6. **German `Mann`** plural in kaikki shows `Mannen` (older form) — for most users `Männer` is expected. This comes directly from data; verify unusual plurals in the preview.
7. **Locale/encodings:** all files read/written as UTF-8; terms NFC-normalized.
8. **`data/plural.db` carries `inflections` (with `lemma_display` + `pos`) and
   a `lemmas` table** (form→lemma + part of speech) built from kaikki — rebuild
   required to pick the new schema up (`python -m german.build_plural_db`). A
   stale pre-rebuild db skips the POS-aware resolution tests in `test_matching.py`.
9. **The dict.cc SQLite indexes (`data/idx_*.db`) now carry a `key_clean` column
   + index and a `schema` meta row.**  The matcher's exact/prefix/fuzzy tiers
   and `has_exact` match against the CLEANED key (`haus`, not `haus {n} [Gebäude]`),
   which restores exact 1.0 for German nouns and makes the fuzzy window reach
   short keys instead of long annotated phrases.  The fingerprint embeds
   `SCHEMA_VERSION`, so a stale old-format db auto-rebuilds on first open
   (one-time, ~15 s).  `strasse`↔`straße` is now handled by casefold, not the
   variant table; the orthvar stage only bridges umlaut digraphs
   (`fuehlen`→`fühlen`), avoiding junk like `messe`→`meße`.
10. **The German route in the app falls back to the forward flow when it
    yields nothing.**  A lowercase English homograph of a German lemma
    (`gas`, `mutter`, `film`) no longer dead-ends on the German gate — it
    gets the correct English→German card.  Language detection also gates the
    morfeusz2 boost behind an English-exact check, so English words are no
    longer misdetected as Polish.
11. **Matching is heuristic, not perfect:** fuzzy/stem guesses are labelled with a
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
- **`inflections` uses `INSERT OR IGNORE` + a POS/length tie-break** — for a
  surface shared by several lemmas, `resolve_info` prefers a noun for capitalized
  surfaces, a non-noun for lowercase ones, and the shorter headword on ties.
- **`has_key`/morphology acceptance** depends on the index's key coverage; stems that
  don't index are safely dropped (occasionally less recall).
- **Verb cards split the German word across groups** — the bare infinitive
  (`sprechen`) and any deverbal noun (`das Sprechen`) are distinct preview
  groups, so a source pair like "speaking" lands on the noun group; the verb
  group defaults to dict.cc verb rows.  Verbs without a kaikki deverbal noun
  stay a single infinitive group (kaikki senses merged in so the card never
  empties).

### Optional-engine residual risks (added with the morphology layer)
- **DWDSmor open-edition coverage is partial** — common nouns like
  `Fenster`/`Auto`/`Zug` are *absent* from the open grammar, and plural
  *generation* is best-effort only (`Haus`→`Häuser` yes; `Hund`, though
  analysable, yields nothing).  Kaikki stays the authoritative plural source;
  DWDSmor only fills kaikki gaps.  `plural_of` never invents a plural.
- **spaCy `better`→`well` (ADV)** — the model picks the adverb for
  comparatives; the EN override table (`better`→`good`, etc.) is merged as a
  supplement so both readings surface.
- **morfeusz2 qualifier/interp rows** — only whole-token analyses are used;
  multi-token compounds are profiled, not decomposed (out of scope).
- **First load is lazy and can be slow** (spaCy model + DWDSmor automata take
  a couple of seconds). All calls are `lru_cache`-d and run on the worker
  thread, so the UI never stalls.
- **Licenses** — the engines stay optional and are never bundled into the
  portable zip (dwdsmor GPL-2.0, spaCy model CC BY-SA 4.0, morfeusz2 BSD), so
  AnkiExt's own sources stay clean for redistribution.

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
python cli_lookup.py house          # offline lookup demo (en, uses real engines)
python cli_lookup.py pies pl        # offline lookup demo (pl, uses real engines)
python cli_lookup.py strasse        # orthographic variant (straße)
python cli_lookup.py Huas           # fuzzy / Damerau-Levenshtein demo
python cli_morph.py ging            # show DWDSmor German morphology (lemma+POS)
python cli_morph.py psami pl        # show morfeusz2 Polish morphology
python cli_smoke.py --dry-run       # show candidates without adding
python cli_smoke.py                 # add sample cards (idempotent)
python cli_cleanup.py --all --yes   # delete the AnkiExt-model test notes
python tests/run_tests.py           # full self-test suite (green with/without engines)
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
| `morphology.en_spacy/pl_morfeusz/dwdsmor` | enable optional real-morphology engines | `true` |
| `morphology.automata_dir` | DWDSmor automata dir (empty = package's) | `""` |
| `morphology.freq_rank` | DWDSmor lemma-frequency ranking tie-break | `true` |
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

## 12. Maintenance rule (must follow after every code edit)

After **any** change to source, config, tests, or docs:

1. **Keep this file current** — update the affected sections above (verification
   results, bugs table, morphology notes, phase table, footer) so AGENTS.md stays
   the single source of truth.
2. **Rebuild the portable package** so anyone pulling the folder/zip gets the fix:
   ```bash
   python make_portable.py
   ```
   This (re)stages `dist/AnkiExt-portable/` and rewrites `dist/AnkiExt-portable.zip`
   from the current sources + index DBs. Verify the build line and, if it matters,
   confirm the staged copy (or zip entry) matches the fixed source via SHA-256.
3. **Re-run the test suite** when code changed (`python tests/run_tests.py`) and
   confirm the count in §5 matches reality.

The zip is a snapshot of the working tree — it silently goes stale the moment a
source file changes, so treat the rebuild as part of every edit, not an afterthought.

---

*Notes compiled 2026-08-20; updated 2026-08-22 for the Polish movable-clitic morfeusz2 fix
(`proponowaliśmy`→`proponować` etc.), the new clitic regression tests (103 total), and the
"rebuild the portable zip after every edit" maintenance rule.*
