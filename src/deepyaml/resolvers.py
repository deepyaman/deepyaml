"""Resolvers for ``${name:args}`` interpolations.

A resolver is a callable that takes the interpolation's (already
type-coerced) arguments and returns a value. ``oc.env`` ships built in.
Custom resolvers can be registered process-wide with
:func:`register_resolver` (the analogue of
``OmegaConf.register_new_resolver``) or passed per-loader via
``ConfigLoader(custom_resolvers=...)``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .errors import InterpolationError

Resolver = Callable[..., Any]
ResolverMap = dict[str, Resolver]

_NO_DEFAULT = object()

#: process-wide custom resolvers (name -> callable)
_registry: ResolverMap = {}


def register_resolver(name: str, resolver: Resolver, *, replace: bool = False) -> None:
    """Register a custom resolver usable as ``${name:...}``."""
    if name in _registry and not replace:
        raise ValueError(f"resolver {name!r} is already registered (pass replace=True)")
    _registry[name] = resolver


def has_resolver(name: str) -> bool:
    return name in _registry or name in BUILTIN_RESOLVERS


def clear_resolvers() -> None:
    """Remove all registered custom resolvers (built-ins are unaffected)."""
    _registry.clear()


def registered_resolvers() -> ResolverMap:
    """A snapshot of the process-wide custom resolver registry."""
    return dict(_registry)


def oc_env(name: str, default: Any = _NO_DEFAULT) -> Any:
    """``${oc.env:VAR}`` / ``${oc.env:VAR,default}``: read an environment variable."""
    try:
        return os.environ[name]
    except KeyError:
        if default is _NO_DEFAULT:
            raise InterpolationError(
                f"Environment variable '{name}' not found"
            ) from None
        return default


BUILTIN_RESOLVERS: ResolverMap = {"oc.env": oc_env}


def build_resolver_map(extra: ResolverMap | None = None) -> ResolverMap:
    """Assemble built-ins + registered + ``extra`` resolvers (later wins)."""
    resolvers = dict(BUILTIN_RESOLVERS)
    resolvers.update(_registry)
    if extra:
        resolvers.update(extra)
    return resolvers
