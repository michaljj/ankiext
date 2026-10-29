# AnkiExt — Free, Offline PL/EN → German Anki Card Maker

Turn selected text on your screen into a proper Anki card **in one hotkey press**:
`Ctrl+Shift+D` → preview → **Add to Anki**.

The German side always includes the **article (der/die/das) + plural** automatically.
100% free: no paid APIs, no accounts. Your dictionary data stays on your PC (except
into your local Anki); the only optional network call is a disableable Wiktionary
last resort for words that miss locally (see **Offline mode**).

---

## Features

- **Offline by default** — all lookups run from local dict.cc + kaikki data; a
  rare-word miss can optionally consult Wiktionary over the network (disable in
  `config.toml` to stay fully offline).
- **Polish → German** and **English → German**.
- Automatic **article + gender + plural** for German nouns
  (e.g. `house` → **das Haus / die Häuser**, `pies` → **der Hund / die Hunde**,
  `kot` → **die Katze / die Katzen**).
- **Smart matching** resolves inflected / near-miss word forms — plurals, past
  tense, conjugations, German declensions, and typos — back to the dictionary
  lemma (`went`→**gehen**, `dogs`→**Hund**, `ging`→**gehen**, `Häuser`→**Haus**).
  Every candidate carries a **certainty %** so you can judge the match.
- Global hotkey captures any selected text (browsers, PDFs, Word, YouTube subtitles…).
- Preview window to pick among multiple translations (dict.cc often has several),
  to **toggle weaker / lower-confidence matches**, and to edit fields before adding.
- Duplicate detection (`canAddNotes`) — no identical cards.
- Creates its own **Anki note type** + **deck** on first use
  (`German::Vocabulary`, templates: Recognition + Production).

## Requirements

- Windows 10/11
- Python 3.10+ (tested on 3.14)
- [Anki](https://apps.ankiweb.net/) running with the
  [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (id `2055492159`).
- The **dict.cc** vocabulary files in `dict/` (you provided them — they are used
  locally and never redistributed; see License notes below).

The core app works on the **Python standard library alone**.  Installing the
optional **real-morphology engines** substantially improves matching for
inflected / unseen word forms in all three languages:

| Engine | Language | What it adds |
|---|---|---|
| `dwdsmor` (FST) | German | true lemma + POS + gender (FST), e.g. `grosse→groß`, `Hunden→Hund` |
| `spacy` + `en_core_web_sm` | English | real lemmatisation, e.g. `went→go`, `children→child` |
| `morfeusz2` | Polish | real Polish lemmatisation, e.g. `psami→pies`, `dziewczyny→dziewczyna` |

Each is optional and independent: with none installed the app falls back to the
built-in heuristic morphology and behaves exactly as before.

## Setup

1. **Install Python** (any recent 3.x) and ensure `python` is on your PATH.
2. **Start Anki** and make sure AnkiConnect is enabled (`Tools ▸ Add-ons ▸ AnkiConnect ▸ Enable`).
3. **Place your dict.cc files** in `dict/` with the names from `config.toml`
   (EN-DE, PL-DE, DE-EN, DE-PL — you already downloaded these).
4. **Install dependencies** (all free & open-source):
   ```
   python -m pip install -r requirements.txt
   ```
   (If pip is unavailable/unwilling, the core app works with stdlib only; the
   `keyboard`/`pystray` packages are optional extras for the hotkey/tray.)
5. **Optionally install the real-morphology engines** for noticeably better
   matching (each independent, see table above):
   ```
   python -m pip install dwdsmor                  # German (GPL-2.0)
   python -m pip install morfeusz2                # Polish (BSD)
   python -m pip install spacy && python -m spacy download en_core_web_sm  # English
   ```
   Toggle any of them off in `config.toml` under `[morphology]`.

## Build the German plural DB (one-time)

Downloads the free kaikki.org German Wiktionary extract (~300 MB) and builds a
local SQLite index of German noun articles + plurals *and* an inflected-form →
lemma index that drives German form matching (`ging`→`gehen`,
`Häuser`→`Haus`):
```
python -m german.build_plural_db
```
This is the only download; it is cached afterwards and runs fully offline.

## Run

```
python app.py
```
Then select text anywhere and press **Ctrl+Shift+D** (configurable in `config.toml`).

First run creates the Anki deck + note type automatically.

## CLI / testing

```
python cli_lookup.py house        # English lookup
python cli_lookup.py pies pl      # Polish lookup
python cli_lookup.py strasse      # orthographic variant (straße)
python cli_lookup.py Huas         # fuzzy / Damerau-Levenshtein
python cli_morph.py ging          # show DWDSmor German morphology (lemma+POS)
python cli_morph.py psami pl      # show morfeusz2 Polish morphology
python cli_smoke.py --dry-run     # show what a lookup+enrich card would look like
python cli_smoke.py               # actually add a few test cards (idempotent)
python tests/run_tests.py         # run the whole self-test suite
```

## Portable transfer (move between computers)

The whole app — source, config, dict.cc files, prebuilt lookup indexes and the
plural DB — can be packaged into **one portable zip** and unzipped on any
Windows PC with Python 3.10+.

**Build the zip** (run in the repo root; needs only Python's stdlib, no pip):

```
python make_portable.py
```

This writes `dist/AnkiExt-portable.zip` (~155 MB; carries your 4 dict.cc files
plus the prebuilt `data/*.db` and `plural.db`). The 288 MB kaikki download is
not included because `plural.db` is already built and carried.

**On the new machine:**

1. Extract `AnkiExt-portable.zip` anywhere.
2. Copy the folder to where you want it (e.g. a USB drive or network share).
3. Double-click **`run.bat`** to run — no installation. (First use the optional
   packages via **`setup.bat`** once if you want the global hotkey / tray; the
   core app works on the Python standard library alone.)

> The app uses only relative paths, so it works from any folder — no hardcoded
> drive letters.

## Configuration (`config.toml`)

| key | meaning |
|---|---|
| `hotkey.combos` | global hotkey (default `ctrl+shift+d`) |
| `dictionary.*` | paths to the 4 dict.cc txt files |
| `dictionary.kaikki_de_url/gz` | kaikki German download source |
| `dictionary.plural_db` | where the plural index is written |
| `dictionary.wikt_cache` | Wiktionary last-resort disk cache location |
| `fallback.wiktionary` | `true`/`false` — enables the network Wiktionary last resort |
| `morphology.en_spacy/pl_morfeusz/dwdsmor` | enable the optional real-morphology engines (`false` to force heuristics) |
| `morphology.automata_dir` | DWDSmor automata dir if not using the installed package's |
| `morphology.freq_rank` | use DWDSmor lemma-frequency as a ranking tie-break |
| `anki.deck` / `anki.model` | destination deck + card model |
| `ui.max_candidates` | how many high-confidence candidates to show by default |
| `matching.total_cap` | total candidates built (strong + weaker behind a toggle) |

## Offline mode

To stay 100% offline (no network calls at all), set `fallback.wiktionary = false`
in `config.toml`. With it `true` (the default), a word that misses every local
source triggers a rate-limited, disk-cached Wiktionary page fetch — the first
occurrence needs the network; results are cached in `data/wikt_cache.sqlite`.

## How it works (very short)

```
selected text ──► Ctrl+C (copied by hotkey)
      │
      ▼
language detect (PL if Polish diacritics/stopwords / PL-DE hit / morfeusz2;
 DE if kaikki-inflected-form / DWDSmor match; else EN)
      │
      ▼
smart-matched dictionary lookup ──► German translation + {m}/{f}/{n} article
  (exact → accent-insensitive → orthographic-variant [straße/strasse, ueber/über]
   → lemma/stem [via spaCy/morfeusz2/DWDSmor when installed] → prefix →
   Damerau-Levenshtein fuzzy, each scored with a certainty %; inflected forms
   resolve to the dictionary lemma)
      │
      ▼
kaikki German index ──► plural + plural article ("die Hunde")
  (also resolves German inflected forms like "ging" → "gehen"; DWDSmor covers
   forms kaikki misses → real German POS + gender + best-effort plural)
      │
      ▼
(Wiktionary last resort, optional — only when local sources miss)
      │
      ▼
tkinter preview (confidence % per candidate, show/lower-confidence toggle,
  edit / pick)  ──► AnkiConnect addNote (dedup)
```

## License notes

- The **dict.cc** files are **private-use only** — do not publish or share them.
  This tool never redistributes them; they stay on your machine.
- The **kaikki** data comes from Wiktionary (CC BY-SA) — fine for personal use.
- Optional morphology engines: **dwdsmor** is GPL-2.0 (open-edition grammar +
  lexicon); **spaCy** is MIT but the `en_core_web_sm` model is CC BY-SA 4.0;
  **morfeusz2** is BSD-3-Clause.  AnkiExt keeps these **optional** and does not
  bundle them into the portable zip, so the rest of the app stays clean for
  redistribution.
- **This project itself is free software**, licensed under the
  [GNU Affero General Public License v3.0](LICENSE.md). You may use, modify and
  redistribute it freely; if you run a modified version as a network service you
  must offer its source to users. No warranty.

## Troubleshooting

- **"cannot reach AnkiConnect"** → start Anki, enable the add-on, and check the
  Custom SyncServer port is 8765 (AnkiConnect default).
- **pip errors about permission/temp** → install with
  `pip install --user` or a virtualenv, or run `python -m pip install --no-cache-dir`.
- **No translation for a word** → the preview lets you fill it manually; you can
  also type a German example in the note field.