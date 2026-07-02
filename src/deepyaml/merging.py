"""Deep-merge of mappings, matching OmegaConf's merge semantics.

- later sources win
- nested dicts merge recursively
- lists and scalars are replaced, not concatenated
- a dict on either side is replaced wholesale by a non-dict on the other
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


def deep_merge(dst: dict, src: Mapping) -> dict:
    """Merge ``src`` into ``dst`` in place and return ``dst``.

    A low-level primitive: ``src``'s values are inserted by reference, so
    ``dst`` may share nested objects with ``src`` afterwards. Use
    :func:`merge` for an isolated copy.
    """
    for key, value in src.items():
        existing = dst.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            deep_merge(existing, value)
        else:
            dst[key] = value
    return dst


def merge(*sources: Mapping) -> dict:
    """Deep-merge mappings left to right into a new dict (later wins).

    Inputs are never mutated, and the result shares no mutable state with
    them.
    """
    result: dict[str, Any] = {}
    for source in sources:
        deep_merge(result, copy.deepcopy(dict(source)))
    return result
