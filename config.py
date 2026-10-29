"""Config loader for AnkiExt.

Reads config.toml into a plain dict.  Relative paths resolve against the
repo root (the directory containing this file's parent), so lookups work no
matter which CWD the app is launched from.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# `dictionary.*` keys that hold file/dir paths and must be resolved against
# REPO_ROOT when they are relative (dict.cc txt files, index/plural DBs).
_PATH_KEYS = ("dict_dir", "index_dir", "plural_db", "kaikki_de_gz", "wikt_cache")


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else REPO_ROOT / "config.toml"
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    _resolve_paths(cfg)
    return cfg


def _resolve_paths(cfg: dict) -> None:
    """Rewrite relative `dictionary.*` paths to absolute against REPO_ROOT.

    Absolute values are left untouched.  `dict_dir`/`index_dir` are given
    defaults here (they are not always present in config.toml) so consumers
    never fall back to CWD-relative paths.  In-place; returns nothing.
    """
    dic = cfg.get("dictionary")
    if not isinstance(dic, dict):
        return
    dic.setdefault("dict_dir", "dict")
    dic.setdefault("index_dir", "data")
    for key in _PATH_KEYS:
        val = dic.get(key)
        if not isinstance(val, str) or not val.strip():
            continue
        p = Path(val)
        if not p.is_absolute():
            dic[key] = str(REPO_ROOT / p)