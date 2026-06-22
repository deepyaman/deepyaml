"""The ``${...}`` interpolation engine — antlr4-free, OmegaConf-compatible.

Supports the subset Kedro configs use:

- ``${a.b.c}``                 same-document dotted node reference
- ``${name:arg1,arg2}``        resolver call (``globals``, ``runtime_params``, ``oc.env``, custom)
- string concatenation         ``"${a}/${b}"``, ``"prefix_${x}"``
- type preservation            a value that is *exactly* one ``${...}`` keeps the resolved type
- ``\\${...}``                  escaped — left as a literal ``${...}``

Resolution is eager (whole tree resolved up front), with a cycle guard.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import InterpolationError
from .resolvers import ResolverMap, build_resolver_map

# One non-nested ${...}. Nested interpolation (${a.${b}}) is intentionally unsupported in v1.
_INTERP = re.compile(r"(?<!\\)\$\{([^}]*)\}")
_ESCAPED = re.compile(r"\\(\$\{[^}]*\})")


def _coerce_arg(arg: str) -> Any:
    """Type-infer a literal resolver argument (mirrors OmegaConf's typed literals)."""
    if len(arg) >= 2 and arg[0] in "'\"" and arg[-1] == arg[0]:
        return arg[1:-1]  # quoted -> string
    low = arg.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
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
            raise InterpolationError(f"interpolation key '{dotted}' not found")
    return node


def _eval(expr: str, *, root: Any, resolvers: ResolverMap, seen: frozenset) -> Any:
    expr = expr.strip()
    name, sep, rest = expr.partition(":")
    if not sep:
        # same-document reference: ${a.b.c}
        if expr in seen:
            raise InterpolationError(f"circular interpolation involving '{expr}'")
        value = _select(root, expr)
        return _resolve(value, root=root, resolvers=resolvers, seen=seen | {expr})
    # resolver call: ${name:arg1,arg2}
    try:
        fn = resolvers[name]
    except KeyError:
        raise InterpolationError(f"unknown resolver '{name}' in '${{{expr}}}'") from None
    args = [_coerce_arg(a.strip()) for a in rest.split(",")] if rest else []
    return fn(*args)


def _resolve_str(value: str, *, root: Any, resolvers: ResolverMap, seen: frozenset) -> Any:
    match = _INTERP.fullmatch(value)
    if match:
        # whole string is a single interpolation -> preserve the resolved value's type
        return _eval(match.group(1), root=root, resolvers=resolvers, seen=seen)
    # otherwise substitute each occurrence as a string (concatenation)
    out = _INTERP.sub(
        lambda m: str(_eval(m.group(1), root=root, resolvers=resolvers, seen=seen)),
        value,
    )
    return _unescape(out)


def _unescape(value: str) -> str:
    return _ESCAPED.sub(r"\1", value)


def _resolve(value: Any, *, root: Any, resolvers: ResolverMap, seen: frozenset) -> Any:
    if isinstance(value, dict):
        return {k: _resolve(v, root=root, resolvers=resolvers, seen=seen) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, root=root, resolvers=resolvers, seen=seen) for v in value]
    if isinstance(value, str):
        return _resolve_str(value, root=root, resolvers=resolvers, seen=seen)
    return value


def resolve(data: Any, resolvers: ResolverMap | None = None, *, root: Any = None) -> Any:
    """Return ``data`` with all ``${...}`` interpolations eagerly resolved.

    References (``${a.b}``) are looked up against ``root`` (defaults to ``data`` itself).
    ``resolvers`` defaults to the built-in + registered resolvers (so ``${oc.env:...}``
    works out of the box); pass ``{}`` to disable resolver calls.
    """
    return _resolve(
        data,
        root=data if root is None else root,
        resolvers=build_resolver_map() if resolvers is None else resolvers,
        seen=frozenset(),
    )
