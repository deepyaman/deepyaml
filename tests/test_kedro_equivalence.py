"""Equivalence with Kedro's OmegaConfigLoader (skipped if Kedro/OmegaConf absent)."""

from __future__ import annotations

import pytest

pytest.importorskip("kedro")
pytest.importorskip("omegaconf")

from kedro.config import OmegaConfigLoader  # noqa: E402

from deepyaml.kedro import DeepYAMLConfigLoader  # noqa: E402

RUNTIME_PARAMS = {"bucket": "bench-bucket", "seed": 42, "env": "prod"}

CONF = {
    "base": {
        "globals.yml": "folder: data\nlayer: raw\nkind: pandas.CSVDataset\nsep: ','\n",
        "catalog_a.yml": (
            "_csv: &csv\n  type: ${globals:kind}\n"
            "companies:\n  <<: *csv\n"
            "  filepath: ${globals:folder}/${globals:layer}/companies.csv\n"
            "  load_args:\n    sep: ${globals:sep}\n"
            "  metadata:\n    bucket: ${runtime_params:bucket,default-bucket}\n"
        ),
        "catalog_b.yml": "reviews:\n  type: ${globals:kind}\n  filepath: data/reviews.csv\n",
        "parameters.yml": "model:\n  test_size: 0.2\n  seed: ${runtime_params:seed,3}\n",
    },
    "local": {
        "credentials.yml": "db:\n  user: ${oc.env:DB_USER,admin}\n",
    },
}


@pytest.fixture
def conf_source(make_conf):
    return make_conf(CONF)


@pytest.mark.parametrize("key", ["globals", "catalog", "parameters", "credentials"])
def test_matches_omegaconfigloader(conf_source, key, monkeypatch):
    monkeypatch.delenv("DB_USER", raising=False)
    ocl = OmegaConfigLoader(
        conf_source=str(conf_source), base_env="base",
        default_run_env="local", runtime_params=RUNTIME_PARAMS,
    )
    dyl = DeepYAMLConfigLoader(
        conf_source=str(conf_source), env="local", runtime_params=RUNTIME_PARAMS,
    )
    assert dyl[key] == ocl[key]


def test_missing_key_both_raise_kedro_exception(make_conf):
    # both raise MissingConfigException for a non-globals key with no files (the framework
    # catches it for optional parameters/credentials). local/ created so it's missing *files*.
    from kedro.config import MissingConfigException

    src = make_conf({"base": {"parameters.yml": "a: 1\n"}, "local": {}})
    ocl = OmegaConfigLoader(conf_source=str(src), base_env="base", default_run_env="local")
    dyl = DeepYAMLConfigLoader(conf_source=str(src))
    with pytest.raises(MissingConfigException):
        ocl["catalog"]
    with pytest.raises(MissingConfigException):
        dyl["catalog"]


def test_missing_conf_dir_raises_kedro_exception(tmp_path):
    from kedro.config import MissingConfigException

    dyl = DeepYAMLConfigLoader(conf_source=str(tmp_path / "nope"))
    with pytest.raises(MissingConfigException):
        dyl["catalog"]


def test_adapter_is_kedro_config_loader(conf_source):
    from kedro.config.abstract_config import AbstractConfigLoader

    dyl = DeepYAMLConfigLoader(conf_source=str(conf_source))
    assert isinstance(dyl, AbstractConfigLoader)
    # .get() (Kedro's 3.11-compatible override) routes through our __getitem__
    assert dyl.get("catalog")["reviews"]["type"] == "pandas.CSVDataset"
    assert dyl.get("nonexistent_key", "fallback") == "fallback"
