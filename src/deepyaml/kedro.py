"""Kedro integration: a drop-in ``AbstractConfigLoader`` backed by deepyaml.

Use it by pointing Kedro's ``CONFIG_LOADER_CLASS`` (in ``settings.py``) at
``deepyaml.kedro.DeepYAMLConfigLoader``. Importing this module requires Kedro
(``pip install deepyaml[kedro]``); the rest of deepyaml does not.
"""

from __future__ import annotations

from typing import Any, KeysView, Mapping

try:
    from kedro.config.abstract_config import AbstractConfigLoader
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "DeepYAMLConfigLoader requires Kedro. Install it with `pip install deepyaml[kedro]`."
    ) from exc

from .loader import ConfigLoader


class DeepYAMLConfigLoader(AbstractConfigLoader):
    """A Kedro ``AbstractConfigLoader`` that loads config via deepyaml.

    Mirrors ``OmegaConfigLoader``'s public behaviour for the common path: environment
    layering (``base`` then run env), the default ``catalog``/``parameters``/
    ``credentials``/``globals`` patterns, ``${globals:...}`` / ``${runtime_params:...}``
    / ``${oc.env:...}`` resolvers, runtime params merged into ``parameters``, and
    top-level ``_``-key stripping — without OmegaConf/antlr4.
    """

    def __init__(
        self,
        conf_source: str,
        env: str | None = None,
        runtime_params: dict[str, Any] | None = None,
        *,
        config_patterns: Mapping[str, list[str]] | None = None,
        base_env: str = "base",
        default_run_env: str = "local",
        custom_resolvers: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(conf_source=conf_source, env=env, runtime_params=runtime_params)
        self._loader = ConfigLoader(
            conf_source,
            base_env=base_env,
            run_env=env or default_run_env,
            config_patterns=config_patterns,
            runtime_params=self.runtime_params,
            custom_resolvers=custom_resolvers,
        )
        self.config_patterns = self._loader.config_patterns

    def __getitem__(self, key: str) -> dict:
        return self._loader[key]

    def keys(self) -> KeysView:
        return KeysView(self.config_patterns)

    def __repr__(self) -> str:
        return (
            f"DeepYAMLConfigLoader(conf_source={self.conf_source!r}, env={self.env!r}, "
            f"config_patterns={self.config_patterns})"
        )
