"""Resolvers for ``${name:args}`` interpolations.

A resolver is just a callable taking the (string) interpolation arguments and returning
a value. ``oc.env`` ships built in; ``globals`` and ``runtime_params`` are bound per-load
by the loader (they close over the globals tree / runtime params). Custom resolvers can
be registered globally with :func:`register_resolver`, mirroring
``OmegaConf.register_new_resolver``.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict

from .errors import InterpolationError

Resolver = Callable[..., Any]
ResolverMap = Dict[str, Resolver]

_SENTINEL = object()

#: globally registered custom resolvers (name -> callable)
_CUSTOM: ResolverMap = {}


def register_resolver(name: str, fn: Resolver, *, replace: bool = False) -> None:
    """Register a custom resolver usable as ``${name:...}`` (like OmegaConf's)."""
    if name in _CUSTOM and not replace:
        raise ValueError(f"resolver {name!r} is already registered (use replace=True)")
    _CUSTOM[name] = fn


def has_resolver(name: str) -> bool:
    return name in _CUSTOM or name in _builtins()


def clear_custom_resolvers() -> None:
    """Remove all custom resolvers (mainly for tests)."""
    _CUSTOM.clear()


def _oc_env(name: str, default: Any = _SENTINEL) -> Any:
    """``${oc.env:VAR}`` / ``${oc.env:VAR,default}`` — read an environment variable."""
    try:
        return os.environ[name]
    except KeyError:
        if default is _SENTINEL:
            raise InterpolationError(f"environment variable {name!r} is not set") from None
        return default


def _builtins() -> ResolverMap:
    return {"oc.env": _oc_env}


def build_resolver_map(extra: ResolverMap | None = None) -> ResolverMap:
    """Assemble built-ins + custom + per-load resolvers (``extra`` wins on conflict)."""
    resolvers: ResolverMap = {}
    resolvers.update(_builtins())
    resolvers.update(_CUSTOM)
    if extra:
        resolvers.update(extra)
    return resolvers
