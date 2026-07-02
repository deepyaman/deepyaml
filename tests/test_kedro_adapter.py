"""The Kedro AbstractConfigLoader adapter (skipped if Kedro is absent)."""

from __future__ import annotations

import pytest

kedro = pytest.importorskip("kedro")

from kedro.config.abstract_config import (  # noqa: E402
    AbstractConfigLoader,
    MissingConfigException,
)

from deepyaml.kedro import DeepYAMLConfigLoader  # noqa: E402


@pytest.fixture
def conf_source(make_conf):
    return make_conf(
        {
            "base": {
                "globals.yml": "kind: pandas.CSVDataset\n",
                "catalog.yml": "reviews:\n  type: ${globals:kind}\n",
                "parameters.yml": "test_size: 0.2\n",
            },
            "local": {"credentials.yml": "db:\n  user: admin\n"},
        }
    )


def make_loader(conf_source, **kwargs):
    kwargs.setdefault("base_env", "base")
    kwargs.setdefault("default_run_env", "local")
    return DeepYAMLConfigLoader(conf_source=str(conf_source), **kwargs)


def test_is_an_abstract_config_loader(conf_source):
    assert isinstance(make_loader(conf_source), AbstractConfigLoader)


def test_loads_all_default_keys(conf_source):
    loader = make_loader(conf_source)
    assert loader["catalog"] == {"reviews": {"type": "pandas.CSVDataset"}}
    assert loader["parameters"] == {"test_size": 0.2}
    assert loader["credentials"] == {"db": {"user": "admin"}}
    assert loader["globals"] == {"kind": "pandas.CSVDataset"}


def test_missing_config_translates_to_kedro_exception(make_conf):
    src = make_conf({"base": {"parameters.yml": "a: 1\n"}, "local": {}})
    loader = make_loader(src)
    with pytest.raises(MissingConfigException):
        loader["catalog"]


def test_missing_conf_source_translates_too(tmp_path):
    loader = make_loader(tmp_path / "nope")
    with pytest.raises(MissingConfigException):
        loader["catalog"]


def test_construction_survives_missing_conf_source(tmp_path):
    # OmegaConfigLoader tolerates a missing conf dir at construction (globals
    # default to {}); errors surface on key access.
    make_loader(tmp_path / "nope")


def test_kedro_get_override_routes_through_getitem(conf_source):
    loader = make_loader(conf_source)
    assert loader.get("parameters") == {"test_size": 0.2}
    assert loader.get("nonexistent_key", "fallback") == "fallback"


def test_explicitly_set_items_bypass_loading(conf_source):
    loader = make_loader(conf_source)
    loader["catalog"] = {"overridden": True}
    assert loader["catalog"] == {"overridden": True}


def test_setting_globals_updates_the_resolver(conf_source):
    loader = make_loader(conf_source)
    loader["globals"] = {"kind": "polars.LazyFrame"}
    assert loader["catalog"] == {"reviews": {"type": "polars.LazyFrame"}}


def test_env_argument_beats_default_run_env(make_conf):
    src = make_conf(
        {
            "base": {"catalog.yml": "a: base\n"},
            "local": {"catalog.yml": "a: local\n"},
            "prod": {"catalog.yml": "a: prod\n"},
        }
    )
    assert make_loader(src, env="prod")["catalog"] == {"a": "prod"}


def test_default_envs_are_empty_like_omegaconfigloader(make_conf):
    # Without base_env/default_run_env, OmegaConfigLoader reads the conf
    # source itself as the single environment.
    src = make_conf({".": {"catalog.yml": "a: 1\n"}})
    loader = DeepYAMLConfigLoader(conf_source=str(src))
    assert loader["catalog"] == {"a": 1}


def test_runtime_params_reach_parameters(conf_source):
    loader = make_loader(conf_source, runtime_params={"test_size": 0.5})
    assert loader["parameters"] == {"test_size": 0.5}


def test_keys_reflect_config_patterns(conf_source):
    assert set(make_loader(conf_source).keys()) == {
        "catalog",
        "parameters",
        "credentials",
        "globals",
    }
