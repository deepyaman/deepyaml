"""Hierarchical config loading with environment layering.

:class:`ConfigLoader` reimplements the load/merge/resolve pipeline of Kedro's
``OmegaConfigLoader`` without OmegaConf or antlr4, returning plain dicts. For
a logical key (``catalog``, ``parameters``, ...) it:

1. globs the key's patterns in the base environment directory, then the run
   environment directory (``conf/base`` and ``conf/local``, in Kedro terms)
2. parses the matched files and deep-merges them per environment, raising if
   files in one environment duplicate a key
3. eagerly resolves ``${...}`` interpolations per environment, against that
   environment's merged tree
4. merges the two environments: "destructive" (top-level keys replaced, the
   default) or "soft" (deep merge), per ``merge_strategy``

Semantics deliberately mirrored from ``OmegaConfigLoader``:

- ``globals`` are loaded once and exposed via ``${globals:...}``;
  ``${runtime_params:...}`` is not allowed inside globals
- runtime params are deep-merged into ``parameters`` (per environment,
  before resolution) and never stripped
- ``${oc.env:...}`` is only available in ``credentials``, where each file is
  resolved individually
- top-level keys starting with ``_`` (templating helpers) are stripped from
  every key except ``parameters``
- duplicate detection compares top-level keys, except for ``parameters``
  where full dotted leaf paths are compared
- a missing environment directory raises :class:`MissingConfigError`, as does
  a key matching no files at all, unless the run env *is* the base env
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from .errors import (
    DuplicateKeysError,
    InterpolationError,
    MissingConfigError,
    ParseError,
)
from .interpolation import resolve
from .merging import merge
from .parsing import SUFFIXES, parse_file
from .resolvers import Resolver, ResolverMap, oc_env, registered_resolvers

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATTERNS: dict[str, list[str]] = {
    "catalog": ["catalog*", "catalog*/**", "**/catalog*"],
    "parameters": ["parameters*", "parameters*/**", "**/parameters*"],
    "credentials": ["credentials*", "credentials*/**", "**/credentials*"],
    "globals": ["globals.yml"],
}

_NO_DEFAULT = object()


# -- file discovery ----------------------------------------------------------


@cache
def _translate(pattern: str) -> re.Pattern[str]:
    """Compile a glob pattern to a regex over posix paths relative to an env dir.

    Follows fsspec's glob dialect (what ``OmegaConfigLoader`` matches with):
    ``*`` and ``?`` never cross ``/``; ``**`` crosses directories, matching
    zero or more of them.
    """
    parts = pattern.split("/")
    regex = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            regex.append(".*" if last else "(?:[^/]+/)*")
        else:
            regex.append(_translate_segment(part) + ("" if last else "/"))
    return re.compile("".join(regex))


def _translate_segment(segment: str) -> str:
    out = []
    i = 0
    while i < len(segment):
        char = segment[i]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = segment.find("]", i + 2)  # "[]a]" has "]" as first member
            if end == -1:
                out.append(re.escape(char))
            else:
                inner = segment[i + 1 : end].replace("!", "^", 1)
                out.append(f"[{inner}]")
                i = end
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


def _find_files(
    env_dir: Path, patterns: list[str], *, ignore_hidden: bool
) -> list[Path]:
    """All config files under ``env_dir`` matching any pattern, sorted."""
    regexes = [_translate(pattern) for pattern in patterns]
    found = []
    for dirpath, dirnames, filenames in os.walk(env_dir):
        if ignore_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if ignore_hidden and filename.startswith("."):
                continue
            path = Path(dirpath, filename)
            if path.suffix not in SUFFIXES:
                continue
            relative = path.relative_to(env_dir).as_posix()
            if any(regex.fullmatch(relative) for regex in regexes):
                found.append(path)
    return sorted(found)


# -- duplicate detection -----------------------------------------------------


def _leaf_keys(tree: Mapping, parent: str = "") -> set[str]:
    keys = set()
    for key, value in tree.items():
        full_key = f"{parent}.{key}" if parent else str(key)
        if isinstance(value, dict):
            keys.update(_leaf_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys


def _check_duplicates(key: str, config_per_file: dict[Path, dict]) -> None:
    """Raise if two files in one directory define the same (non-``_``) key.

    Top-level keys are compared, except for ``parameters`` where full dotted
    leaf paths are compared (matching ``OmegaConfigLoader``).
    """
    if key == "parameters":
        keys_per_file = {
            path: _leaf_keys(config) for path, config in config_per_file.items()
        }
    else:
        keys_per_file = {
            path: {str(k) for k in config} for path, config in config_per_file.items()
        }

    duplicates = []
    paths = list(keys_per_file)
    for i, path1 in enumerate(paths, 1):
        for path2 in paths[i:]:
            overlap = {
                k
                for k in keys_per_file[path1] & keys_per_file[path2]
                if not k.startswith("_")
            }
            if overlap:
                sorted_keys = ", ".join(sorted(overlap))
                if len(sorted_keys) > 100:
                    sorted_keys = sorted_keys[:100] + "..."
                duplicates.append(
                    f"Duplicate keys found in {path1} and {path2}: {sorted_keys}"
                )
    if duplicates:
        raise DuplicateKeysError("\n".join(duplicates))


# -- resolvers bound to loader state -----------------------------------------


def _select_or_default(tree: Mapping, dotted: str, default: Any) -> Any:
    node: Any = tree
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def _runtime_params_not_supported(*_args: Any) -> Any:
    raise InterpolationError(
        "The `runtime_params:` resolver is not supported for globals."
    )


# -- the loader --------------------------------------------------------------


class ConfigLoader:
    """Load, layer, and resolve hierarchical configuration into plain dicts.

    Args:
        conf_source: Root directory containing the environment directories.
        base_env: Environment loaded first (default ``"base"``).
        run_env: Environment layered on top (default ``"local"``).
        config_patterns: Extra/overriding ``{key: [glob, ...]}`` entries on
            top of :data:`DEFAULT_CONFIG_PATTERNS`.
        runtime_params: Extra parameters; deep-merged into ``parameters`` and
            exposed via ``${runtime_params:...}``.
        custom_resolvers: Per-loader ``{name: callable}`` resolvers, on top of
            any process-wide :func:`deepyaml.register_resolver` registrations.
        merge_strategy: ``{key: "destructive" | "soft"}`` for merging the run
            env over the base env; default is destructive (top-level keys
            replaced).
        ignore_hidden: Skip hidden files and directories (default True).
    """

    def __init__(
        self,
        conf_source: str | Path,
        *,
        base_env: str = "base",
        run_env: str = "local",
        config_patterns: Mapping[str, list[str]] | None = None,
        runtime_params: Mapping[str, Any] | None = None,
        custom_resolvers: Mapping[str, Resolver] | None = None,
        merge_strategy: Mapping[str, str] | None = None,
        ignore_hidden: bool = True,
    ) -> None:
        self.conf_source = Path(conf_source)
        self.base_env = base_env
        self.run_env = run_env
        self.runtime_params = dict(runtime_params or {})
        self.custom_resolvers = dict(custom_resolvers or {})
        self.merge_strategy = dict(merge_strategy or {})
        self.ignore_hidden = ignore_hidden
        self.config_patterns = dict(DEFAULT_CONFIG_PATTERNS)
        self.config_patterns.update(config_patterns or {})
        self._globals: dict | None = None
        self._loading_globals = False

    @property
    def globals(self) -> dict:
        """The resolved ``globals`` config backing ``${globals:...}`` (cached)."""
        if self._globals is None:
            self._globals = self.get("globals")
        return self._globals

    @globals.setter
    def globals(self, value: Mapping[str, Any]) -> None:
        self._globals = dict(value)

    def get(self, key: str) -> dict:
        """Load, merge, and resolve all config files for ``key``."""
        if key not in self.config_patterns:
            raise KeyError(
                f"No config patterns were found for '{key}' in your config loader"
            )
        patterns = self.config_patterns[key]
        resolvers = self._resolver_map(key)
        processed_files: set[Path] = set()

        if key == "globals":
            self._loading_globals = True
        try:
            base_path = self.conf_source / self.base_env
            config = self._load_dir(
                base_path, key, patterns, resolvers, processed_files
            )

            if self.run_env == self.base_env:
                return self._cache_globals(key, config)

            env_path = self.conf_source / self.run_env
            env_config = self._load_dir(
                env_path, key, patterns, resolvers, processed_files
            )
            config = self._merge_envs(config, env_config, key, env_path)
        finally:
            self._loading_globals = False

        if not processed_files and key != "globals":
            raise MissingConfigError(
                f"No files of YAML or JSON format found in {base_path} or {env_path} "
                f"matching the glob pattern(s): {patterns}"
            )
        return self._cache_globals(key, config)

    def __getitem__(self, key: str) -> dict:
        return self.get(key)

    def keys(self) -> Any:
        return self.config_patterns.keys()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(conf_source={str(self.conf_source)!r}, "
            f"base_env={self.base_env!r}, run_env={self.run_env!r}, "
            f"config_patterns={self.config_patterns})"
        )

    # -- internals ------------------------------------------------------------

    def _cache_globals(self, key: str, config: dict) -> dict:
        if key == "globals" and self._globals is None:
            self._globals = config
        return config

    def _load_dir(
        self,
        conf_path: Path,
        key: str,
        patterns: list[str],
        resolvers: ResolverMap,
        processed_files: set[Path],
    ) -> dict:
        """Load, merge, and resolve every matching file in one env directory."""
        if not conf_path.is_dir():
            raise MissingConfigError(
                f"Given configuration path either does not exist "
                f"or is not a valid directory: {conf_path}"
            )

        config_per_file: dict[Path, dict] = {}
        for path in _find_files(conf_path, patterns, ignore_hidden=self.ignore_hidden):
            data = parse_file(path) or {}
            if not isinstance(data, dict):
                raise ParseError(
                    f"{path}: top-level config must be a mapping, "
                    f"got {type(data).__name__}"
                )
            if key == "credentials":
                # oc.env is allowed only in credentials, resolved per file.
                data = resolve(data, {"oc.env": oc_env, **resolvers})
            config_per_file[path] = data
            processed_files.add(path)

        _check_duplicates(key, config_per_file)
        if not config_per_file:
            return {}

        merged = merge(*config_per_file.values())
        if key == "parameters":
            # Runtime params join per environment, pre-resolution, unstripped.
            return resolve(merge(merged, self.runtime_params), resolvers)
        # Credentials were already resolved per file.
        resolved = merged if key == "credentials" else resolve(merged, resolvers)
        return {
            k: v
            for k, v in resolved.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }

    def _merge_envs(
        self, config: dict, env_config: dict, key: str, env_path: Path
    ) -> dict:
        strategy = self.merge_strategy.get(key, "destructive")
        if strategy == "destructive":
            overridden = config.keys() & env_config.keys()
            if overridden:
                logger.debug(
                    "Config from path '%s' will override the following "
                    "existing top-level config keys: %s",
                    env_path,
                    ", ".join(sorted(overridden)),
                )
            return {**config, **env_config}
        if strategy == "soft":
            return merge(config, env_config)
        raise ValueError(
            f"Merging strategy {strategy} not supported. The accepted "
            f"merging strategies are ['soft', 'destructive']."
        )

    def _resolver_map(self, key: str) -> ResolverMap:
        resolvers: ResolverMap = registered_resolvers()
        resolvers["globals"] = self._globals_resolver
        resolvers["runtime_params"] = (
            _runtime_params_not_supported
            if key == "globals"
            else self._runtime_params_resolver
        )
        resolvers.update(self.custom_resolvers)
        return resolvers

    def _globals_resolver(self, variable: str, default: Any = _NO_DEFAULT) -> Any:
        if variable.startswith("_"):
            raise InterpolationError(
                "Keys starting with '_' are not supported for globals."
            )
        if self._globals is not None:
            source = self._globals
        elif self._loading_globals:
            source = {}  # globals cannot reference themselves while loading
        else:
            source = self.globals  # first use: lazy-load and cache
        value = _select_or_default(source, variable, default)
        if value is _NO_DEFAULT:
            raise InterpolationError(
                f"Globals key '{variable}' not found and no default value provided."
            )
        return value

    def _runtime_params_resolver(
        self, variable: str, default: Any = _NO_DEFAULT
    ) -> Any:
        value = _select_or_default(self.runtime_params, variable, default)
        if value is _NO_DEFAULT:
            raise InterpolationError(
                f"Runtime parameter '{variable}' not found and no default value "
                f"provided."
            )
        return value
