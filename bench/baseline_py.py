"""Minimal pure-Python config loader — the 'do we even need Rust?' baseline.

Implements the subset of OmegaConfigLoader behaviour our generated configs exercise:
  - load all catalog_*.yml (+ globals/parameters/credentials) via PyYAML
  - deep-merge (later wins, lists replaced, raise on duplicate top-level key across files)
  - eager-resolve `${...}` with a hand-written parser (NO antlr4):
        ${globals:key,default}  ${runtime_params:key,default}  ${oc.env:VAR,default}
        ${a.b.c}                 (same-document dotted reference)
  - return plain dict

Deliberately small: this is what a no-antlr4, no-Rust implementation looks like.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

try:  # libyaml C loader is ~10x faster than the pure-Python SafeLoader
    from yaml import CSafeLoader as _Loader
except ImportError:  # pragma: no cover - e.g. WASM without libyaml
    from yaml import SafeLoader as _Loader

_INTERP = re.compile(r"\$\{([^}]*)\}")


def _yaml_load(text: str):
    return yaml.load(text, Loader=_Loader)


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v  # later wins; lists/scalars replaced
    return dst


def _load_pattern(base: Path, pattern: str) -> dict:
    """Merge all files matching a glob, raising on duplicate top-level keys."""
    merged: dict[str, Any] = {}
    seen: dict[str, str] = {}
    for f in sorted(base.glob(pattern)):
        data = _yaml_load(f.read_text()) or {}
        for key in data:
            if key in seen:
                raise ValueError(f"Duplicate key '{key}' in {f.name} and {seen[key]}")
            seen[key] = f.name
        _deep_merge(merged, data)
    return merged


def _select(tree: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = tree
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _resolve_one(expr: str, *, root: dict, globs: dict, runtime_params: dict) -> Any:
    name, _, rest = expr.partition(":")
    if not _:  # no ':' -> same-document dotted reference, e.g. ${a.b.c}
        return _select(root, name.strip())
    args = rest.split(",", 1)
    key = args[0].strip()
    default = args[1] if len(args) > 1 else None
    if name == "globals":
        return _select(globs, key, default)
    if name == "runtime_params":
        return runtime_params.get(key, default)
    if name in ("oc.env", "env"):
        return os.environ.get(key, default)
    return default


def _resolve_value(val: Any, *, root: dict, globs: dict, runtime_params: dict) -> Any:
    if isinstance(val, dict):
        return {k: _resolve_value(v, root=root, globs=globs, runtime_params=runtime_params)
                for k, v in val.items()}
    if isinstance(val, list):
        return [_resolve_value(v, root=root, globs=globs, runtime_params=runtime_params)
                for v in val]
    if not isinstance(val, str):
        return val
    m = _INTERP.fullmatch(val)
    if m:  # whole string is one interpolation -> preserve resolved type
        res = _resolve_one(m.group(1), root=root, globs=globs, runtime_params=runtime_params)
        return _resolve_value(res, root=root, globs=globs, runtime_params=runtime_params)
    # otherwise string-substitute each occurrence
    return _INTERP.sub(
        lambda mo: str(_resolve_one(mo.group(1), root=root, globs=globs,
                                    runtime_params=runtime_params)),
        val,
    )


def load_config(conf_source: Path, *, env: str = "local", runtime_params: dict | None = None,
                pattern: str = "catalog_*.yml") -> dict:
    runtime_params = runtime_params or {}
    base = conf_source / "base"
    globs = _yaml_load((base / "globals.yml").read_text()) if (base / "globals.yml").exists() else {}
    globs = globs or {}

    merged = _load_pattern(base, pattern)
    return _resolve_value(merged, root=merged, globs=globs, runtime_params=runtime_params)


if __name__ == "__main__":
    import json
    import sys

    out = load_config(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("configs/small"),
                      runtime_params={"bucket": "b", "seed": 1})
    print(json.dumps(dict(list(out.items())[:1]), indent=2))
