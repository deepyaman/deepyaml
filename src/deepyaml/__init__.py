"""deepyaml — fast, antlr4-free hierarchical configuration loading.

A focused, pure-Python alternative to OmegaConf for the subset Kedro's
``OmegaConfigLoader`` relies on: load YAML/JSON, deep-merge environment layers,
eagerly resolve ``${...}`` interpolations/resolvers, and return plain dicts.

See ``bench/RESULTS.md`` for the measurements behind the pure-Python design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._merge import merge
from ._parsers import parse, parse_file, register_format
from .errors import (
    DeepYAMLError,
    InterpolationError,
    MergeError,
    MissingConfigError,
)
from .interpolation import resolve
from .resolvers import has_resolver, register_resolver

__version__ = "0.1.0"


def loads(text: str, fmt: str = "yaml") -> Any:
    """Parse a single config document from a string (no interpolation)."""
    return parse(text, fmt)


def load(path: str | Path) -> Any:
    """Parse a single config file by path (format from its extension)."""
    return parse_file(Path(path))


__all__ = [
    "__version__",
    "load",
    "loads",
    "merge",
    "resolve",
    "register_format",
    "register_resolver",
    "has_resolver",
    "DeepYAMLError",
    "InterpolationError",
    "MergeError",
    "MissingConfigError",
]
