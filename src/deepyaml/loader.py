"""Hierarchical config loader — the OmegaConfigLoader-equivalent logic, Kedro-free.

For a logical key (``catalog``, ``parameters``, ...), it globs the configured patterns
across environment layers (``base`` then ``local``), parses + deep-merges files within
each env (raising on duplicate top-level keys), eagerly resolves ``${...}``, and returns
a plain dict. Matches Kedro's ``OmegaConfigLoader`` behaviour:

- ``parameters`` get ``runtime_params`` merged in as data; other keys strip top-level
  ``_``-prefixed keys (templating anchors) from the result
- ``globals`` are loaded first and exposed via the ``${globals:...}`` resolver
- ``${runtime_params:...}`` and ``${oc.env:...}`` resolvers are available

The ``kedro`` adapter ([deepyaml.kedro]) is a thin wrapper over this class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ._merge import deep_merge, merge as merge_dicts
from ._parsers import SUFFIXES, parse_file
from .errors import InterpolationError, MergeError, MissingConfigError
from .interpolation import resolve as resolve_tree
from .resolvers import build_resolver_map

DEFAULT_CONFIG_PATTERNS: dict[str, list[str]] = {
    "catalog": ["catalog*", "catalog*/**", "**/catalog*"],
    "parameters": ["parameters*", "parameters*/**", "**/parameters*"],
    "credentials": ["credentials*", "credentials*/**", "**/credentials*"],
    "globals": ["globals.yml"],
}

_NO_DEFAULT = object()


def _select(tree: Any, dotted: str, default: Any = _NO_DEFAULT) -> Any:
    node = tree
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            if default is _NO_DEFAULT:
                raise InterpolationError(
                    f"Globals key '{dotted}' not found and no default value provided."
                )
            return default
    return node


class ConfigLoader:
    def __init__(
        self,
        conf_source: str | Path,
        *,
        base_env: str = "base",
        run_env: str = "local",
        config_patterns: Mapping[str, list[str]] | None = None,
        runtime_params: Mapping[str, Any] | None = None,
        custom_resolvers: Mapping[str, Any] | None = None,
    ) -> None:
        self.conf_source = Path(conf_source)
        self.base_env = base_env
        self.run_env = run_env
        self.runtime_params = dict(runtime_params or {})
        self.custom_resolvers = dict(custom_resolvers or {})
        self.config_patterns = dict(DEFAULT_CONFIG_PATTERNS)
        self.config_patterns.update(config_patterns or {})
        self._globals_cache: dict | None = None

    @property
    def envs(self) -> list[str]:
        envs = [self.base_env]
        if self.run_env and self.run_env != self.base_env:
            envs.append(self.run_env)
        return envs

    # -- file discovery -----------------------------------------------------

    def _find_files(self, env: str, key: str) -> list[Path]:
        env_dir = self.conf_source / env
        if not env_dir.is_dir():
            return []
        found: set[Path] = set()
        for pattern in self.config_patterns[key]:
            for path in env_dir.glob(pattern):
                if (
                    path.is_file()
                    and path.suffix.lower() in SUFFIXES
                    and not path.name.startswith(".")
                ):
                    found.add(path)
        return sorted(found)

    @staticmethod
    def _check_duplicates(config_per_file: dict[Path, dict]) -> None:
        seen: dict[str, Path] = {}
        duplicates = []
        for path, config in config_per_file.items():
            for top_key in config:
                if top_key.startswith("_"):
                    continue
                if top_key in seen:
                    duplicates.append(f"Duplicate key '{top_key}' in {seen[top_key].name} and {path.name}")
                else:
                    seen[top_key] = path
        if duplicates:
            raise MergeError("\n".join(duplicates))

    # -- resolvers ----------------------------------------------------------

    def _load_globals(self) -> dict:
        if self._globals_cache is None:
            self._globals_cache = self._load_key("globals", resolvers={})
        return self._globals_cache

    def _resolvers(self) -> dict:
        globs = self._load_globals()

        def globals_resolver(variable: str, default: Any = _NO_DEFAULT) -> Any:
            if variable.startswith("_"):
                raise InterpolationError("Keys starting with '_' are not supported for globals.")
            return _select(globs, variable, default)

        def runtime_params_resolver(variable: str, default: Any = None) -> Any:
            return self.runtime_params.get(variable, default)

        return build_resolver_map(
            {
                "globals": globals_resolver,
                "runtime_params": runtime_params_resolver,
                **self.custom_resolvers,
            }
        )

    # -- loading ------------------------------------------------------------

    def _load_key(self, key: str, *, resolvers: dict) -> dict:
        per_env: list[dict] = []
        for env in self.envs:
            files = self._find_files(env, key)
            if not files:
                continue
            config_per_file = {path: (parse_file(path) or {}) for path in files}
            self._check_duplicates(config_per_file)
            merged = merge_dicts(*config_per_file.values())
            if key == "parameters":
                deep_merge(merged, self.runtime_params)
                per_env.append(resolve_tree(merged, resolvers))
            else:
                resolved = resolve_tree(merged, resolvers)
                per_env.append({k: v for k, v in resolved.items() if not k.startswith("_")})
        # OmegaConfigLoader raises for a non-globals key with no files across envs (the
        # framework catches it for optional parameters/credentials). It only short-circuits
        # to {} when run_env == base_env (a single env), so mirror that.
        if not per_env and key != "globals" and len(self.envs) > 1:
            raise MissingConfigError(
                f"No YAML or JSON files found for key '{key}' in {self.conf_source} "
                f"matching {self.config_patterns[key]}"
            )
        return merge_dicts(*per_env) if per_env else {}

    def get(self, key: str) -> dict:
        if key not in self.config_patterns:
            raise KeyError(
                f"No config patterns were found for '{key}' in your config loader"
            )
        if not (self.conf_source / self.base_env).is_dir():
            raise MissingConfigError(
                f"Config path '{self.conf_source / self.base_env}' does not exist "
                f"or is not a directory."
            )
        if key == "globals":
            return self._load_globals()
        return self._load_key(key, resolvers=self._resolvers())

    def __getitem__(self, key: str) -> dict:
        return self.get(key)
