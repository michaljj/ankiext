#!/usr/bin/env python3
"""Build a portable AnkiExt package (folder + single zip).

Pure Python stdlib (no pip required). Assembles a folder with the app sources,
the config, the dict.cc files, and the prebuilt SQLite indexes/plural DB, then
zips it into dist/AnkiExt-portable.zip for copying between computers.

The optional real-morphology engines (spaCy / morfeusz2 / DWDSmor) are NOT
bundled — they are pip-installed site-packages and carry license obligations
(GPL-2.0 for dwdsmor, CC BY-SA for en_core_web_sm).  The portable package runs
on the built-in heuristic morphology out of the box; installing the engines on
the target machine re-enables the improved matching.

Regenerable/heavy files are deliberately omitted:
  - data/de-extract.jsonl.gz  (+288 MB — only needed to REBUILD plural.db)
  - *.zip  (the dict.cc zips; the .txt are what the app actually reads)
  - __pycache__, research/, .venv-tmp, .build-*, probe/tmp folders

Usage:
    python make_portable.py
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
STAGE = DIST / "AnkiExt-portable"
ZIP_PATH = DIST / "AnkiExt-portable.zip"

# Everything that must NOT travel (regenerable, private build junk, huge).
SKIP_DIRS = {"__pycache__", "research", ".venv-tmp", ".pip-tmp", ".build-tmp",
             ".build-venv", ".pylib", ".userbase", ".pycache", ".venv", "venv",
             "node_modules"}
SKIP_NAMES = {"de-extract.jsonl.gz"}
SKIP_SUFFIXES = {".zip", ".pyc", ".pyo", ".log", ".pyproj"}


def _config_paths() -> dict[str, Path]:
    """Resolve dict-file / index / plural paths from config.toml (absolute)."""
    import tomllib
    with open(ROOT / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    dic = cfg["dictionary"]
    dict_dir = Path(dic.get("dict_dir", "dict"))
    if not dict_dir.is_absolute():
        dict_dir = ROOT / dict_dir
    index_dir = Path(dic.get("index_dir", "data"))
    if not index_dir.is_absolute():
        index_dir = ROOT / index_dir
    return {
        "dict_files": [dict_dir / dic["en_de"], dict_dir / dic["de_en"],
                       dict_dir / dic["pl_de"], dict_dir / dic["de_pl"]],
        "index_dir": index_dir,
        "plural_db": _abs(dic.get("plural_db", "data/plural.db")),
    }


def _abs(p):
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def _rel(src: Path) -> Path:
    return src.relative_to(ROOT)


def _copy(src: Path, dst_root: Path, src_root: Path, rel: Path) -> None:
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite something we've already copied / never clash
    if dst.exists():
        return
    shutil.copy2(src, dst)


def main() -> int:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)

    cfg = _config_paths()

    # 1) dictionary txt files (the 4 from config)
    for f in cfg["dict_files"]:
        if not f.exists():
            print(f"WARN: missing dict file {f} — skipping")
            continue
        _copy(f, STAGE, ROOT, _rel(f))

    # 2) prebuilt SQLite index DBs in data/
    idx_dir = cfg["index_dir"]
    if idx_dir.exists():
        for f in sorted(idx_dir.iterdir()):
            if f.name.endswith(".db"):
                _copy(f, STAGE, ROOT, _rel(f))
            else:
                print(f"skip (non-db) in data/: {f.name}")
    else:
        print(f"WARN: index_dir {idx_dir} not found — indexes not carried")

    # 3) plural DB
    if cfg["plural_db"].exists():
        _copy(cfg["plural_db"], STAGE, ROOT, _rel(cfg["plural_db"]))
    else:
        print(f"WARN: plural db {cfg['plural_db']} missing!")

    # 4) app sources + launchers + docs
    for child in sorted(ROOT.iterdir()):
        if child.is_dir():
            if child.name in SKIP_DIRS or child.name == "dist":
                continue
            for f in sorted(child.rglob("*")):
                if not f.is_file():
                    continue
                if any(part in SKIP_DIRS for part in f.parts):
                    continue
                if f.name in SKIP_NAMES or f.suffix in SKIP_SUFFIXES:
                    continue
                _copy(f, STAGE, ROOT, _rel(f))
        elif child.is_file():
            if child.name in SKIP_NAMES or child.suffix in SKIP_SUFFIXES:
                continue
            if child.name == "make_portable.py":
                continue  # not needed on target
            _copy(child, STAGE, ROOT, _rel(child))

    # 5) zip it up
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    shutil.make_archive(str(ZIP_PATH.with_suffix("")), "zip", root_dir=DIST,
                        base_dir="AnkiExt-portable")

    size_mb = ZIP_PATH.stat().st_size / 1048576
    sha = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    print(f"Built {ZIP_PATH.name}  {size_mb:.1f} MB")
    print(f"SHA-256: {sha}")
    print(f"Staged folder: {STAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
