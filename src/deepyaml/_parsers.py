"""Format parsers: text -> plain Python data (dict/list/scalars).

A small pluggable registry keyed by format name. ``OmegaConfigLoader`` supports only
YAML and JSON, so those ship by default; the registry keeps adding formats (e.g. TOML
via ``tomllib``) a few lines away, and interpolation runs on the parsed tree so it is
format-agnostic.

YAML uses libyaml (``CSafeLoader``) when available — ~10x faster than the pure-Python
loader and byte-for-byte the same YAML 1.1 scalar typing OmegaConf produces.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import yaml

try:  # libyaml C loader; falls back to pure-Python (e.g. on WASM without libyaml)
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _YamlLoader


def parse_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_YamlLoader)


def parse_json(text: str) -> Any:
    return json.loads(text)


#: format name -> parser. Extend with e.g. ``register_format("toml", tomllib.loads)``.
PARSERS: dict[str, Callable[[str], Any]] = {
    "yaml": parse_yaml,
    "json": parse_json,
}

#: file suffix -> format name
SUFFIXES: dict[str, str] = {
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
}


def register_format(name: str, parser: Callable[[str], Any], *suffixes: str) -> None:
    """Register a new format parser (and optionally file suffixes for it)."""
    PARSERS[name] = parser
    for suffix in suffixes:
        SUFFIXES[suffix] = name


def parse(text: str, fmt: str = "yaml") -> Any:
    try:
        parser = PARSERS[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}; known: {sorted(PARSERS)}") from None
    return parser(text)


def parse_file(path: Path) -> Any:
    fmt = SUFFIXES.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"unsupported config extension {path.suffix!r} ({path})")
    return parse(path.read_text(), fmt)
