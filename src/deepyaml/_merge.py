"""Deep-merge of mappings, matching OmegaConf/Kedro semantics.

- later sources win
- nested dicts merge recursively
- lists and scalars are *replaced* (not concatenated) — OmegaConf's default
"""

from __future__ import annotations

from typing import Any, Mapping


def deep_merge(dst: dict, src: Mapping) -> dict:
    """Merge ``src`` into ``dst`` in place and return it."""
    for key, value in src.items():
        existing = dst.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            deep_merge(existing, value)
        else:
            dst[key] = value
    return dst


def merge(*sources: Mapping) -> dict:
    """Deep-merge mappings left-to-right into a new dict (later wins)."""
    result: dict[str, Any] = {}
    for source in sources:
        deep_merge(result, source)
    return result
