"""The ``${...}`` interpolation engine: antlr4-free, OmegaConf-compatible.

Supports the subset of OmegaConf's grammar that hierarchical configs (and, in
particular, Kedro projects) actually use:

- ``${a.b.c}``: dotted reference to another node in the same document
- ``${name:arg1,arg2}``: resolver call, with typed literal arguments
  (``${oc.env:VAR,default}``, ``${globals:key}``, ...)
- string concatenation: ``"${a}/${b}"``, ``"prefix_${x}"``
- type preservation: a value that is exactly one ``${...}`` keeps the
  resolved value's type
- ``\\${...}``: escaped; left as a literal ``${...}``

Resolution is eager (the whole tree is resolved up front) with a cycle guard.
Nested interpolations (``${a.${b}}``) are not supported.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import InterpolationError
from .resolvers import ResolverMap, build_resolver_map

_INTERP = re.compile(r"(?<!\\)\$\{([^}]*)\}")
_ESCAPED = re.compile(r"\\(\$\{[^}]*\})")


def _coerce_arg(arg: str) -> Any:
    """Type-infer a literal resolver argument (mirrors OmegaConf's typed literals)."""
    if len(arg) >= 2 and arg[0] in "'\"" and arg[-1] == arg[0]:
        return arg[1:-1]  # quoted -> string
    lowered = arg.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "~"):
        return None
    for cast in (int, float):
        try:
            return cast(arg)
        except ValueError:
            pass
    return arg


def _select(root: Any, dotted: str) -> Any:
    node = root
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise InterpolationError(f"Interpolation key '{dotted}' not found")
    return node


def _eval(expr: str, *, root: Any, resolvers: ResolverMap, seen: frozenset) -> Any:
    expr = expr.strip()
    name, colon, rest = expr.partition(":")
    if not colon:
        # reference to another node: ${a.b.c}
        if expr in seen:
            raise InterpolationError(f"Circular interpolation involving '{expr}'")
        value = _select(root, expr)
        return _resolve(value, root=root, resolvers=resolvers, seen=seen | {expr})
    # resolver call: ${name:arg1,arg2}
    try:
        resolver = resolvers[name]
    except KeyError:
        raise InterpolationError(
            f"Unsupported interpolation type '{name}' in '${{{expr}}}'"
        ) from None
    args = [_coerce_arg(arg.strip()) for arg in rest.split(",")] if rest else []
    return resolver(*args)


def _resolve_str(
    value: str, *, root: Any, resolvers: ResolverMap, seen: frozenset
) -> Any:
    match = _INTERP.fullmatch(value)
    if match:
        # the whole string is one interpolation -> preserve the resolved type
        return _eval(match.group(1), root=root, resolvers=resolvers, seen=seen)
    # otherwise substitute each occurrence as a string (concatenation)
    substituted = _INTERP.sub(
        lambda m: str(_eval(m.group(1), root=root, resolvers=resolvers, seen=seen)),
        value,
    )
    return _ESCAPED.sub(r"\1", substituted)


def _resolve(value: Any, *, root: Any, resolvers: ResolverMap, seen: frozenset) -> Any:
    if isinstance(value, dict):
        return {
            k: _resolve(v, root=root, resolvers=resolvers, seen=seen)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_resolve(v, root=root, resolvers=resolvers, seen=seen) for v in value]
    if isinstance(value, str) and "${" in value:
        return _resolve_str(value, root=root, resolvers=resolvers, seen=seen)
    return value


def resolve(
    data: Any, resolvers: ResolverMap | None = None, *, root: Any = None
) -> Any:
    """Return ``data`` with all ``${...}`` interpolations eagerly resolved.

    References (``${a.b}``) are looked up against ``root``, which defaults to
    ``data`` itself. ``resolvers`` defaults to the built-in plus registered
    resolvers (so ``${oc.env:...}`` works out of the box); pass ``{}`` to
    disable resolver calls.
    """
    return _resolve(
        data,
        root=data if root is None else root,
        resolvers=build_resolver_map() if resolvers is None else resolvers,
        seen=frozenset(),
    )
