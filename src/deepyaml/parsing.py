"""Format parsers: text -> plain Python data (dicts, lists, scalars).

A small registry keyed by format name. YAML and JSON ship by default (the two
formats Kedro's ``OmegaConfigLoader`` accepts); :func:`register_format` makes
adding another (e.g. TOML via ``tomllib``) a one-liner, and interpolation runs
on the parsed tree, so it is format-agnostic.

The YAML loader is libyaml-backed (``CSafeLoader``, ~10x faster than the
pure-Python loader, with a pure-Python fallback for platforms without libyaml,
such as WASM) and reproduces OmegaConf's scalar typing exactly:

- YAML 1.1 resolvers (``no`` -> ``False``, ``12:30`` -> ``750``), like OmegaConf
- plus OmegaConf's extra float resolver, so ``1e3`` parses as ``1000.0``
- minus the timestamp resolver, so dates/datetimes stay strings
- duplicate keys within one mapping are an error, not silently last-wins
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .errors import ParseError

try:  # libyaml; falls back to pure Python (e.g. on WASM without libyaml)
    from yaml import CSafeLoader as _BaseLoader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _BaseLoader  # type: ignore[assignment]


class _YamlLoader(_BaseLoader):
    """SafeLoader with OmegaConf's typing tweaks (see module docstring)."""

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> Any:
        keys = set()
        for key_node, _ in node.value:
            if key_node.tag != yaml.resolver.BaseResolver.DEFAULT_SCALAR_TAG:
                continue
            if key_node.value in keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key_node.value}",
                    key_node.start_mark,
                )
            keys.add(key_node.value)
        return super().construct_mapping(node, deep=deep)


# OmegaConf accepts exponent-only floats (`1e3`), which YAML 1.1 does not.
_YamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"""^(?:
         [-+]?[0-9]+(?:_[0-9]+)*\.[0-9_]*(?:[eE][-+]?[0-9]+)?
        |[-+]?[0-9]+(?:_[0-9]+)*(?:[eE][-+]?[0-9]+)
        |\.[0-9]+(?:_[0-9]+)*(?:[eE][-+][0-9]+)?
        |[-+]?[0-9]+(?:_[0-9]+)*(?::[0-5]?[0-9])+\.[0-9_]*
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
        re.X,
    ),
    list("-+0123456789."),
)
# OmegaConf drops the timestamp resolver: dates stay strings.
_YamlLoader.yaml_implicit_resolvers = {
    first_char: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]
    for first_char, resolvers in _YamlLoader.yaml_implicit_resolvers.items()
}


def parse_yaml(text: str) -> Any:
    try:
        return yaml.load(text, Loader=_YamlLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ParseError(f"invalid YAML{where}: {exc.problem or exc}") from exc


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


#: format name -> parser
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
    """Register a parser (and optionally file suffixes) for a new format."""
    PARSERS[name] = parser
    for suffix in suffixes:
        SUFFIXES[suffix] = name


def parse(text: str, fmt: str = "yaml") -> Any:
    try:
        parser = PARSERS[fmt]
    except KeyError:
        raise ValueError(
            f"unknown format {fmt!r}; known formats: {sorted(PARSERS)}"
        ) from None
    return parser(text)


def parse_file(path: str | Path) -> Any:
    path = Path(path)
    fmt = SUFFIXES.get(path.suffix)
    if fmt is None:
        raise ValueError(f"unsupported config file extension {path.suffix!r}: {path}")
    try:
        return parse(path.read_text(), fmt)
    except ParseError as exc:
        raise ParseError(f"{path}: {exc}") from exc.__cause__
