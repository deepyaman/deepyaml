"""Hierarchical loader behaviour (Kedro-free)."""

from __future__ import annotations

import pytest

from deepyaml.errors import MergeError, MissingConfigError
from deepyaml.loader import ConfigLoader


def test_env_layering_local_overrides_base(make_conf):
    src = make_conf({
        "base": {"catalog.yml": "a:\n  x: 1\n  y: 2\n"},
        "local": {"catalog.yml": "a:\n  y: 99\n"},
    })
    assert ConfigLoader(src)["catalog"] == {"a": {"x": 1, "y": 99}}


def test_multiple_files_merged_within_env(make_conf):
    src = make_conf({"base": {
        "catalog_a.yml": "a: {type: A}\n",
        "catalog_b.yml": "b: {type: B}\n",
    }})
    assert ConfigLoader(src)["catalog"] == {"a": {"type": "A"}, "b": {"type": "B"}}


def test_duplicate_key_across_files_raises(make_conf):
    src = make_conf({"base": {
        "catalog_a.yml": "shared: {type: A}\n",
        "catalog_b.yml": "shared: {type: B}\n",
    }})
    with pytest.raises(MergeError):
        ConfigLoader(src)["catalog"]


def test_underscore_keys_stripped_but_usable_as_templates(make_conf):
    src = make_conf({"base": {"catalog.yml":
        "_defaults: &d\n  type: pandas.CSVDataset\n"
        "companies:\n  <<: *d\n  filepath: a.csv\n"
    }})
    out = ConfigLoader(src)["catalog"]
    assert "_defaults" not in out
    assert out["companies"] == {"type": "pandas.CSVDataset", "filepath": "a.csv"}


def test_globals_resolver(make_conf):
    src = make_conf({"base": {
        "globals.yml": "folder: data\nkind: pandas.CSVDataset\n",
        "catalog.yml": "ds:\n  type: ${globals:kind}\n  filepath: ${globals:folder}/x.csv\n",
    }})
    assert ConfigLoader(src)["catalog"] == {
        "ds": {"type": "pandas.CSVDataset", "filepath": "data/x.csv"}
    }


def test_globals_default_when_missing(make_conf):
    src = make_conf({"base": {
        "globals.yml": "folder: data\n",
        "catalog.yml": "ds:\n  sep: ${globals:sep,';'}\n",
    }})
    assert ConfigLoader(src)["catalog"]["ds"]["sep"] == ";"


def test_runtime_params_merged_into_parameters(make_conf):
    src = make_conf({"base": {"parameters.yml": "a: 1\n"}})
    loader = ConfigLoader(src, runtime_params={"b": 2})
    assert loader["parameters"] == {"a": 1, "b": 2}


def test_runtime_params_resolver(make_conf):
    src = make_conf({"base": {"catalog.yml": "ds:\n  bucket: ${runtime_params:bucket,default}\n"}})
    assert ConfigLoader(src, runtime_params={"bucket": "prod"})["catalog"]["ds"]["bucket"] == "prod"


def test_missing_files_raises_in_standard_two_env_setup(make_conf):
    # matches OmegaConfigLoader: a non-globals key with no files (base != run_env) -> raises
    src = make_conf({"base": {"parameters.yml": "a: 1\n"}, "local": {}})
    with pytest.raises(MissingConfigError):
        ConfigLoader(src)["catalog"]


def test_missing_files_single_env_returns_empty(make_conf):
    # when run_env == base_env (single env), OmegaConfigLoader short-circuits to {}
    src = make_conf({"base": {"parameters.yml": "a: 1\n"}})
    assert ConfigLoader(src, run_env="base")["catalog"] == {}


def test_missing_conf_directory_raises(tmp_path):
    with pytest.raises(MissingConfigError):
        ConfigLoader(tmp_path / "does_not_exist")["catalog"]


def test_unknown_key_raises_keyerror(make_conf):
    src = make_conf({"base": {"catalog.yml": "a: 1\n"}})
    with pytest.raises(KeyError):
        ConfigLoader(src)["not_a_pattern"]
