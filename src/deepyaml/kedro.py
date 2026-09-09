"""Kedro integration: a drop-in ``AbstractConfigLoader`` backed by deepyaml.

Point ``CONFIG_LOADER_CLASS`` in your project's ``settings.py`` at
:class:`DeepYAMLConfigLoader`::

    from deepyaml.kedro import DeepYAMLConfigLoader

    CONFIG_LOADER_CLASS = DeepYAMLConfigLoader

Importing this module requires Kedro (``pip install deepyaml[kedro]``); the
rest of deepyaml does not.
"""

from __future__ import annotations

from collections.abc import Callable, KeysView
from pathlib import Path
from typing import Any

try:
    from kedro.config.abstract_config import (
        AbstractConfigLoader,
        MissingConfigException,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "DeepYAMLConfigLoader requires Kedro. "
        "Install it with `pip install deepyaml[kedro]`."
    ) from exc

from .errors import MissingConfigError
from .loader import ConfigLoader


class DeepYAMLConfigLoader(AbstractConfigLoader):
    """``OmegaConfigLoader``'s behavior, backed by deepyaml instead of OmegaConf.

    Mirrors the constructor signature and semantics of Kedro's
    ``OmegaConfigLoader`` for local config sources, including its defaults:
    ``base_env`` and ``default_run_env`` fall back to ``""`` (the conf source
    itself) when used directly, and are normally supplied by Kedro's
    ``CONFIG_LOADER_ARGS`` (``"base"`` / ``"local"``).
    """

    def __init__(
        self,
        conf_source: str | Path,
        env: str | None = None,
        runtime_params: dict[str, Any] | None = None,
        *,
        config_patterns: dict[str, list[str]] | None = None,
        base_env: str | None = None,
        default_run_env: str | None = None,
        custom_resolvers: dict[str, Callable] | None = None,
        merge_strategy: dict[str, str] | None = None,
        ignore_hidden: bool = True,
    ) -> None:
        self.base_env = base_env or ""
        self.default_run_env = default_run_env or ""
        # Built before ``super().__init__``, which assigns ``runtime_params``
        # through the property below.
        self._loader = ConfigLoader(
            conf_source,
            base_env=self.base_env,
            run_env=env or self.default_run_env,
            config_patterns=config_patterns,
            runtime_params=runtime_params,
            custom_resolvers=custom_resolvers,
            merge_strategy=merge_strategy,
            ignore_hidden=ignore_hidden,
        )
        super().__init__(
            conf_source=str(conf_source), env=env, runtime_params=runtime_params
        )
        self.config_patterns = self._loader.config_patterns
        # Like OmegaConfigLoader, load globals eagerly; missing config dirs
        # leave them empty rather than failing construction.
        try:
            _ = self._loader.globals
        except MissingConfigError:
            self._loader.globals = {}

    # ``OmegaConfigLoader`` keeps these as plain attributes and reads them when
    # a key is loaded, so reassigning one after construction takes effect.
    # Proxying keeps the wrapped loader as the single source of truth.

    @property
    def runtime_params(self) -> dict[str, Any]:
        return self._loader.runtime_params

    @runtime_params.setter
    def runtime_params(self, value: dict[str, Any] | None) -> None:
        self._loader.runtime_params = value or {}

    @property
    def merge_strategy(self) -> dict[str, str]:
        return self._loader.merge_strategy

    @merge_strategy.setter
    def merge_strategy(self, value: dict[str, str] | None) -> None:
        self._loader.merge_strategy = value or {}

    def __getitem__(self, key: str) -> dict[str, Any]:
        # Explicitly set values (``loader["catalog"] = {...}``) win, matching
        # OmegaConfigLoader's bypass of pattern loading.
        if key in self:
            return super().__getitem__(key)  # type: ignore[no-any-return]
        try:
            return self._loader.get(key)
        except MissingConfigError as exc:
            # Kedro's framework catches MissingConfigException to make
            # parameters/credentials optional; translate so it keeps working.
            raise MissingConfigException(str(exc)) from exc

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "globals":
            self._loader.globals = value
        super().__setitem__(key, value)

    def keys(self) -> KeysView:
        return KeysView(self.config_patterns)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(conf_source={self.conf_source!r}, "
            f"env={self.env!r}, config_patterns={self.config_patterns})"
        )
