"""Equivalence with Kedro's OmegaConfigLoader, scenario by scenario.

Every test builds one conf tree, loads it through Kedro's real
``OmegaConfigLoader`` and through ``DeepYAMLConfigLoader``, and asserts the
outputs are identical (including scalar types) or that both fail. Skipped if
Kedro/OmegaConf are not installed.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from deepyaml import InterpolationError

pytest.importorskip("kedro")
pytest.importorskip("omegaconf")

from kedro.config import MissingConfigException, OmegaConfigLoader

from deepyaml.kedro import DeepYAMLConfigLoader

DEFAULT_KEYS = ["globals", "catalog", "parameters", "credentials"]


def loaders(conf_source, **kwargs):
    common = {
        "conf_source": str(conf_source),
        "base_env": "base",
        "default_run_env": "local",
        **kwargs,
    }
    return OmegaConfigLoader(**common), DeepYAMLConfigLoader(**common)


def assert_identical(ours, theirs, path="$"):
    assert type(ours) is type(theirs), (
        f"{path}: {type(ours).__name__} != {type(theirs).__name__}"
    )
    if isinstance(ours, dict):
        assert ours.keys() == theirs.keys(), f"{path}: {ours.keys()} != {theirs.keys()}"
        for k in ours:
            assert_identical(ours[k], theirs[k], f"{path}.{k}")
    elif isinstance(ours, list):
        assert len(ours) == len(theirs), f"{path}: lengths differ"
        for i, (x, y) in enumerate(zip(ours, theirs, strict=True)):
            assert_identical(x, y, f"{path}[{i}]")
    else:
        assert ours == theirs, f"{path}: {ours!r} != {theirs!r}"


def assert_equivalent(conf_source, keys=DEFAULT_KEYS, **kwargs):
    reference, ours = loaders(conf_source, **kwargs)
    for key in keys:
        assert_identical(ours[key], reference[key], path=key)


class TestFullProject:
    """A spaceflights-style project exercising most features at once."""

    LAYOUT: ClassVar = {
        "base": {
            "globals.yml": (
                "folder: data\n"
                "datasets:\n  csv: pandas.CSVDataset\n  pq: pandas.ParquetDataset\n"
            ),
            "catalog_a.yml": (
                "_csv: &csv\n"
                "  type: ${globals:datasets.csv}\n"
                "  load_args:\n    sep: ','\n"
                "companies:\n"
                "  <<: *csv\n"
                "  filepath: ${globals:folder}/01_raw/companies.csv\n"
                "  metadata:\n    bucket: ${runtime_params:bucket,default-bucket}\n"
            ),
            "catalog_b.yml": (
                "reviews:\n"
                "  type: ${globals:datasets.pq}\n"
                "  filepath: ${globals:folder}/02_intermediate/reviews.pq\n"
            ),
            "pipelines/ds/catalog_ds.yml": (
                "model:\n  type: pickle.PickleDataset\n  filepath: data/model.pkl\n"
            ),
            "parameters.yml": (
                "model_options:\n  test_size: 0.2\n"
                "  random_state: ${runtime_params:seed,3}\n"
            ),
            "parameters_ds.yml": "features:\n- engines\n- crew\n",
        },
        "local": {
            "catalog_a.yml": (
                "companies:\n  type: pandas.CSVDataset\n"
                "  filepath: local/companies.csv\n"
            ),
            "credentials.yml": (
                "db:\n  user: ${oc.env:DEEPYAML_EQ_USER,guest}\n  pass: ${_secret}\n"
                "_secret: hunter2\n"
            ),
        },
    }

    @pytest.fixture
    def conf_source(self, make_conf):
        return make_conf(self.LAYOUT)

    def test_all_keys_identical(self, conf_source, monkeypatch):
        monkeypatch.delenv("DEEPYAML_EQ_USER", raising=False)
        assert_equivalent(
            conf_source, runtime_params={"bucket": "s3://prod", "seed": 42}
        )

    def test_with_env_var_set(self, conf_source, monkeypatch):
        monkeypatch.setenv("DEEPYAML_EQ_USER", "admin")
        assert_equivalent(conf_source, keys=["credentials"])

    def test_without_runtime_params(self, conf_source):
        assert_equivalent(conf_source)


class TestScalarTyping:
    def test_yaml_11_typing_matches(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "parameters.yml": (
                        "bool_no: no\n"
                        "bool_on: on\n"
                        "sexagesimal: 12:30\n"
                        "octal: 0777\n"
                        "exp_float: 1e3\n"
                        "date: 2024-01-01\n"
                        "timestamp: 2024-01-01T00:00:00\n"
                        "infinity: .inf\n"
                        "nothing: null\n"
                    )
                },
                "local": {},
            }
        )
        assert_equivalent(src, keys=["parameters"])

    def test_interpolation_type_preservation_matches(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "parameters.yml": (
                        "seed: 42\n"
                        "ratio: 0.5\n"
                        "copy_of_seed: ${seed}\n"
                        "as_string: seed_${seed}\n"
                        "combined: ${seed}_${ratio}\n"
                        "nested:\n  deep: ${copy_of_seed}\n"
                    )
                },
                "local": {},
            }
        )
        assert_equivalent(src, keys=["parameters"])

    def test_escaped_interpolation_matches(self, make_conf):
        src = make_conf(
            {"base": {"parameters.yml": "literal: \\${not.a.ref}\n"}, "local": {}}
        )
        assert_equivalent(src, keys=["parameters"])

    def test_json_matches(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.json": '{"ds": {"type": "csv", "n": 1}}'},
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"])


class TestEnvironmentMerging:
    PARTIAL_OVERRIDE: ClassVar = {
        "base": {"catalog.yml": "ds:\n  type: csv\n  filepath: base.csv\nother: 1\n"},
        "local": {"catalog.yml": "ds:\n  filepath: local.csv\n"},
    }

    def test_destructive_default_replaces_top_level(self, make_conf):
        assert_equivalent(make_conf(self.PARTIAL_OVERRIDE), keys=["catalog"])

    def test_soft_merge_strategy(self, make_conf):
        assert_equivalent(
            make_conf(self.PARTIAL_OVERRIDE),
            keys=["catalog"],
            merge_strategy={"catalog": "soft"},
        )

    def test_key_only_in_run_env(self, make_conf):
        src = make_conf({"base": {}, "local": {"catalog.yml": "ds: 1\n"}})
        assert_equivalent(src, keys=["catalog"])

    def test_run_env_equals_base_env(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "ds: 1\n"}})
        reference, ours = loaders(src, env="base")
        assert_identical(ours["catalog"], reference["catalog"])

    def test_run_env_equals_base_env_no_files_returns_empty(self, make_conf):
        src = make_conf({"base": {}})
        reference, ours = loaders(src, env="base")
        assert_identical(ours["catalog"], reference["catalog"])

    def test_underscore_keys_stripped_identically(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "_t: csv\nds:\n  type: ${_t}\n"},
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"])

    def test_parameters_keep_underscores_identically(self, make_conf):
        src = make_conf({"base": {"parameters.yml": "_p: 1\na: ${_p}\n"}, "local": {}})
        assert_equivalent(src, keys=["parameters"])


class TestErrors:
    def test_missing_files_raise_missing_config_exception(self, make_conf):
        src = make_conf({"base": {"parameters.yml": "a: 1\n"}, "local": {}})
        reference, ours = loaders(src)
        with pytest.raises(MissingConfigException):
            reference["catalog"]
        with pytest.raises(MissingConfigException):
            ours["catalog"]

    def test_missing_run_env_dir_raises(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: 1\n"}})
        reference, ours = loaders(src)
        with pytest.raises(MissingConfigException):
            reference["catalog"]
        with pytest.raises(MissingConfigException):
            ours["catalog"]

    def test_unknown_key_raises_keyerror(self, make_conf):
        src = make_conf({"base": {}, "local": {}})
        reference, ours = loaders(src)
        with pytest.raises(KeyError):
            reference["spark"]
        with pytest.raises(KeyError):
            ours["spark"]

    def test_duplicate_top_level_keys_raise_valueerror(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog_a.yml": "ds: 1\n", "catalog_b.yml": "ds: 2\n"},
                "local": {},
            }
        )
        reference, ours = loaders(src)
        with pytest.raises(ValueError, match="Duplicate keys"):
            reference["catalog"]
        with pytest.raises(ValueError, match="Duplicate keys"):
            ours["catalog"]

    def test_nested_parameter_duplicates_raise_valueerror(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "parameters_a.yml": "model:\n  seed: 1\n",
                    "parameters_b.yml": "model:\n  seed: 2\n",
                },
                "local": {},
            }
        )
        reference, ours = loaders(src)
        with pytest.raises(ValueError, match=r"model\.seed"):
            reference["parameters"]
        with pytest.raises(ValueError, match=r"model\.seed"):
            ours["parameters"]

    def test_oc_env_outside_credentials_raises_in_both(self, make_conf, monkeypatch):
        monkeypatch.setenv("DEEPYAML_EQ_USER", "admin")
        src = make_conf(
            {"base": {"catalog.yml": "a: ${oc.env:DEEPYAML_EQ_USER}\n"}, "local": {}}
        )
        reference, ours = loaders(src)
        with pytest.raises(Exception, match=r"oc\.env"):
            reference["catalog"]
        with pytest.raises(InterpolationError, match=r"oc\.env"):
            ours["catalog"]

    def test_runtime_params_in_globals_raises_in_both(self, make_conf):
        src = make_conf(
            {"base": {"globals.yml": "a: ${runtime_params:x}\n"}, "local": {}}
        )
        message = "The `runtime_params:` resolver is not supported for globals."
        with pytest.raises(Exception, match=message):
            OmegaConfigLoader(
                conf_source=str(src),
                base_env="base",
                default_run_env="local",
                runtime_params={"x": 1},
            )["globals"]
        with pytest.raises(InterpolationError, match=message):
            DeepYAMLConfigLoader(
                conf_source=str(src),
                base_env="base",
                default_run_env="local",
                runtime_params={"x": 1},
            )["globals"]


class TestResolvers:
    def test_globals_defaults_and_dotted_lookup(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "globals.yml": "nested:\n  deep:\n    value: 7\n",
                    "catalog.yml": (
                        "a: ${globals:nested.deep.value}\n"
                        "b: ${globals:absent,fallback}\n"
                    ),
                },
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"])

    def test_runtime_params_dotted_and_default(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog.yml": (
                        "a: ${runtime_params:model.seed}\n"
                        "b: ${runtime_params:no.pe,9}\n"
                    )
                },
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"], runtime_params={"model": {"seed": 42}})

    def test_custom_resolvers(self, make_conf):
        from omegaconf import OmegaConf

        src = make_conf(
            {"base": {"catalog.yml": "a: ${deepyaml_eq_add:1,2}\n"}, "local": {}}
        )
        try:
            assert_equivalent(
                src,
                keys=["catalog"],
                custom_resolvers={"deepyaml_eq_add": lambda x, y: x + y},
            )
        finally:
            OmegaConf.clear_resolver("deepyaml_eq_add")

    def test_globals_layer_across_envs(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "globals.yml": "a: base\nb: base\n",
                    "catalog.yml": "x: ${globals:a}\ny: ${globals:b}\n",
                },
                "local": {"globals.yml": "b: local\n"},
            }
        )
        assert_equivalent(src, keys=["globals", "catalog"])


class TestDiscoveryParity:
    def test_subdirectory_layouts(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog.yml": "a: 1\n",
                    "catalog_dir/one.yml": "b: 2\n",
                    "catalog_dir/sub/two.yml": "c: 3\n",
                    "pipelines/x/catalog_x.yml": "d: 4\n",
                    "not_matching.yml": "e: 5\n",
                    "catalog_wrong_suffix.txt": "f: 6\n",
                },
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"])

    def test_hidden_files_ignored_in_both(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog.yml": "a: 1\n",
                    ".ipynb_checkpoints/catalog.yml": "b: 2\n",
                },
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"])

    def test_empty_files_in_both(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "# empty\n", "catalog_b.yml": "a: 1\n"},
                "local": {},
            }
        )
        assert_equivalent(src, keys=["catalog"])
