"""ConfigLoader behavior: discovery, layering, resolution, and errors."""

from __future__ import annotations

import pytest

from deepyaml import (
    ConfigLoader,
    DuplicateKeysError,
    InterpolationError,
    MissingConfigError,
    ParseError,
)


class TestDiscovery:
    def test_multiple_files_merge_within_env(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog_a.yml": "a: 1\n", "catalog_b.yml": "b: 2\n"},
                "local": {},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"a": 1, "b": 2}

    def test_files_in_subdirectories_match(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog.yml": "a: 1\n",
                    "catalog_dir/nested.yml": "b: 2\n",  # catalog*/**
                    "pipelines/one/catalog_one.yml": "c: 3\n",  # **/catalog*
                },
                "local": {},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"a": 1, "b": 2, "c": 3}

    def test_non_config_suffixes_ignored(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "a: 1\n", "catalog.txt": "b: 2\n"},
                "local": {},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"a": 1}

    def test_json_files_load(self, make_conf):
        src = make_conf({"base": {"catalog.json": '{"a": {"b": 1}}'}, "local": {}})
        assert ConfigLoader(src)["catalog"] == {"a": {"b": 1}}

    def test_hidden_files_and_dirs_ignored(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog.yml": "a: 1\n",
                    ".catalog_hidden.yml": "b: 2\n",
                    ".ipynb_checkpoints/catalog.yml": "c: 3\n",
                },
                "local": {},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"a": 1}

    def test_ignore_hidden_false_includes_them(self, make_conf):
        # Hidden dirs can hold pattern-matching files (via **/catalog*).
        src = make_conf(
            {
                "base": {"catalog.yml": "a: 1\n", ".hidden/catalog_h.yml": "b: 2\n"},
                "local": {},
            }
        )
        loader = ConfigLoader(src, ignore_hidden=False)
        assert loader["catalog"] == {"a": 1, "b": 2}

    def test_empty_file_is_empty_config(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "# nothing\n"}, "local": {}})
        assert ConfigLoader(src)["catalog"] == {}

    def test_non_mapping_file_raises(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "- 1\n- 2\n"}, "local": {}})
        with pytest.raises(ParseError, match="must be a mapping"):
            ConfigLoader(src)["catalog"]

    def test_unknown_key_raises_keyerror(self, make_conf):
        src = make_conf({"base": {}, "local": {}})
        with pytest.raises(KeyError, match="No config patterns"):
            ConfigLoader(src)["spark"]

    def test_custom_patterns(self, make_conf):
        src = make_conf({"base": {"spark.yml": "a: 1\n"}, "local": {}})
        loader = ConfigLoader(src, config_patterns={"spark": ["spark*"]})
        assert loader["spark"] == {"a": 1}


class TestEnvironmentLayering:
    def test_run_env_overrides_base(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "a: 1\nb: 1\n"},
                "local": {"catalog.yml": "b: 2\n"},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"a": 1, "b": 2}

    def test_destructive_merge_replaces_top_level_keys(self, make_conf):
        # The default strategy replaces whole top-level keys, like
        # OmegaConfigLoader (dict.update), rather than deep-merging.
        src = make_conf(
            {
                "base": {"catalog.yml": "ds:\n  type: csv\n  path: base.csv\n"},
                "local": {"catalog.yml": "ds:\n  path: local.csv\n"},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"ds": {"path": "local.csv"}}

    def test_soft_merge_deep_merges(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "ds:\n  type: csv\n  path: base.csv\n"},
                "local": {"catalog.yml": "ds:\n  path: local.csv\n"},
            }
        )
        loader = ConfigLoader(src, merge_strategy={"catalog": "soft"})
        assert loader["catalog"] == {"ds": {"type": "csv", "path": "local.csv"}}

    def test_unknown_merge_strategy_raises(self, make_conf):
        src = make_conf(
            {"base": {"catalog.yml": "a: 1\n"}, "local": {"catalog.yml": "b: 2\n"}}
        )
        loader = ConfigLoader(src, merge_strategy={"catalog": "override"})
        with pytest.raises(ValueError, match="not supported"):
            loader["catalog"]

    def test_same_run_and_base_env_loads_once(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: 1\n"}})
        loader = ConfigLoader(src, run_env="base")
        assert loader["catalog"] == {"a": 1}

    def test_interpolation_does_not_cross_environments(self, make_conf):
        # Each env resolves against its own merged tree, like OmegaConfigLoader.
        src = make_conf(
            {
                "base": {"catalog.yml": "a: 1\n"},
                "local": {"catalog.yml": "b: ${a}\n"},
            }
        )
        with pytest.raises(InterpolationError, match="not found"):
            ConfigLoader(src)["catalog"]


class TestMissingConfig:
    def test_missing_base_dir_raises(self, tmp_path):
        with pytest.raises(MissingConfigError, match="not a valid directory"):
            ConfigLoader(tmp_path / "nope")["catalog"]

    def test_missing_run_env_dir_raises(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: 1\n"}})
        with pytest.raises(MissingConfigError, match="not a valid directory"):
            ConfigLoader(src)["catalog"]

    def test_no_files_anywhere_raises(self, make_conf):
        src = make_conf({"base": {}, "local": {}})
        with pytest.raises(MissingConfigError, match="No files of YAML or JSON"):
            ConfigLoader(src)["catalog"]

    def test_no_files_ok_when_run_env_is_base_env(self, make_conf):
        src = make_conf({"base": {}})
        assert ConfigLoader(src, run_env="base")["catalog"] == {}

    def test_no_files_ok_for_globals(self, make_conf):
        src = make_conf({"base": {}, "local": {}})
        assert ConfigLoader(src)["globals"] == {}

    def test_files_in_one_env_only_is_fine(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: 1\n"}, "local": {}})
        assert ConfigLoader(src)["catalog"] == {"a": 1}


class TestDuplicates:
    def test_duplicate_top_level_keys_across_files_raise(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog_a.yml": "ds: 1\n", "catalog_b.yml": "ds: 2\n"},
                "local": {},
            }
        )
        with pytest.raises(DuplicateKeysError, match="Duplicate keys"):
            ConfigLoader(src)["catalog"]

    def test_duplicates_across_envs_are_fine(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "ds: 1\n"},
                "local": {"catalog.yml": "ds: 2\n"},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"ds": 2}

    def test_parameters_compare_nested_leaf_paths(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "parameters_a.yml": "model:\n  seed: 1\n",
                    "parameters_b.yml": "model:\n  seed: 2\n",
                },
                "local": {},
            }
        )
        with pytest.raises(DuplicateKeysError, match=r"model\.seed"):
            ConfigLoader(src)["parameters"]

    def test_parameters_sharing_a_branch_are_fine(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "parameters_a.yml": "model:\n  seed: 1\n",
                    "parameters_b.yml": "model:\n  lr: 0.1\n",
                },
                "local": {},
            }
        )
        assert ConfigLoader(src)["parameters"] == {"model": {"seed": 1, "lr": 0.1}}

    def test_catalog_top_level_duplicate_only(self, make_conf):
        # Non-parameters keys compare top-level only: nested overlap is a
        # duplicate ONLY if the top-level key also collides.
        src = make_conf(
            {
                "base": {
                    "catalog_a.yml": "ds_a:\n  type: csv\n",
                    "catalog_b.yml": "ds_b:\n  type: csv\n",
                },
                "local": {},
            }
        )
        assert set(ConfigLoader(src)["catalog"]) == {"ds_a", "ds_b"}

    def test_underscore_keys_may_collide(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog_a.yml": "_anchor: &a\n  type: csv\nds_a:\n  <<: *a\n",
                    "catalog_b.yml": "_anchor: &a\n  type: pq\nds_b:\n  <<: *a\n",
                },
                "local": {},
            }
        )
        catalog = ConfigLoader(src)["catalog"]
        assert catalog == {"ds_a": {"type": "csv"}, "ds_b": {"type": "pq"}}


class TestUnderscoreStripping:
    def test_underscore_keys_stripped_after_resolution(self, make_conf):
        src = make_conf(
            {
                "base": {"catalog.yml": "_type: csv\nds:\n  type: ${_type}\n"},
                "local": {},
            }
        )
        assert ConfigLoader(src)["catalog"] == {"ds": {"type": "csv"}}

    def test_parameters_keep_underscore_keys(self, make_conf):
        src = make_conf(
            {"base": {"parameters.yml": "_private: 1\na: 2\n"}, "local": {}}
        )
        assert ConfigLoader(src)["parameters"] == {"_private": 1, "a": 2}


class TestGlobals:
    def test_globals_resolver(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "globals.yml": "folder: data\nnested:\n  kind: csv\n",
                    "catalog.yml": (
                        "ds:\n  path: ${globals:folder}/x.csv\n"
                        "  type: ${globals:nested.kind}\n"
                    ),
                },
                "local": {},
            }
        )
        assert ConfigLoader(src)["catalog"] == {
            "ds": {"path": "data/x.csv", "type": "csv"}
        }

    def test_globals_default_value(self, make_conf):
        src = make_conf(
            {"base": {"catalog.yml": "a: ${globals:missing,fallback}\n"}, "local": {}}
        )
        assert ConfigLoader(src)["catalog"] == {"a": "fallback"}

    def test_globals_missing_key_raises(self, make_conf):
        src = make_conf(
            {"base": {"catalog.yml": "a: ${globals:missing}\n"}, "local": {}}
        )
        with pytest.raises(InterpolationError, match="Globals key 'missing' not found"):
            ConfigLoader(src)["catalog"]

    def test_globals_underscore_key_raises(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: ${globals:_x}\n"}, "local": {}})
        with pytest.raises(InterpolationError, match="not supported for globals"):
            ConfigLoader(src)["catalog"]

    def test_globals_layer_across_envs(self, make_conf):
        src = make_conf(
            {
                "base": {"globals.yml": "a: base\nb: base\n"},
                "local": {"globals.yml": "b: local\n"},
            }
        )
        loader = ConfigLoader(src)
        assert loader["globals"] == {"a": "base", "b": "local"}

    def test_globals_can_interpolate_within_themselves(self, make_conf):
        src = make_conf(
            {"base": {"globals.yml": "root: data\npath: ${root}/raw\n"}, "local": {}}
        )
        assert ConfigLoader(src)["globals"]["path"] == "data/raw"

    def test_runtime_params_not_allowed_in_globals(self, make_conf):
        src = make_conf(
            {"base": {"globals.yml": "a: ${runtime_params:x}\n"}, "local": {}}
        )
        loader = ConfigLoader(src, runtime_params={"x": 1})
        with pytest.raises(InterpolationError, match="not supported for globals"):
            loader["globals"]

    def test_globals_settable(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: ${globals:x}\n"}, "local": {}})
        loader = ConfigLoader(src)
        loader.globals = {"x": 42}
        assert loader["catalog"] == {"a": 42}


class TestRuntimeParams:
    def test_merged_into_parameters(self, make_conf):
        src = make_conf(
            {"base": {"parameters.yml": "model:\n  lr: 0.1\n  seed: 1\n"}, "local": {}}
        )
        loader = ConfigLoader(src, runtime_params={"model": {"seed": 42}})
        assert loader["parameters"] == {"model": {"lr": 0.1, "seed": 42}}

    def test_not_merged_into_other_keys(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: 1\n"}, "local": {}})
        loader = ConfigLoader(src, runtime_params={"b": 2})
        assert loader["catalog"] == {"a": 1}

    def test_resolver_with_dotted_path_and_default(self, make_conf):
        src = make_conf(
            {
                "base": {
                    "catalog.yml": (
                        "a: ${runtime_params:model.seed}\n"
                        "b: ${runtime_params:missing,7}\n"
                    )
                },
                "local": {},
            }
        )
        loader = ConfigLoader(src, runtime_params={"model": {"seed": 42}})
        assert loader["catalog"] == {"a": 42, "b": 7}

    def test_resolver_missing_without_default_raises(self, make_conf):
        src = make_conf(
            {"base": {"catalog.yml": "a: ${runtime_params:x}\n"}, "local": {}}
        )
        with pytest.raises(InterpolationError, match="Runtime parameter 'x' not found"):
            ConfigLoader(src)["catalog"]


class TestCredentialsAndOcEnv:
    def test_oc_env_available_in_credentials(self, make_conf, monkeypatch):
        monkeypatch.setenv("DEEPYAML_DB_USER", "admin")
        src = make_conf(
            {
                "base": {
                    "credentials.yml": "db:\n  user: ${oc.env:DEEPYAML_DB_USER}\n"
                },
                "local": {},
            }
        )
        assert ConfigLoader(src)["credentials"] == {"db": {"user": "admin"}}

    def test_oc_env_not_available_elsewhere(self, make_conf, monkeypatch):
        monkeypatch.setenv("DEEPYAML_DB_USER", "admin")
        src = make_conf(
            {"base": {"catalog.yml": "a: ${oc.env:DEEPYAML_DB_USER}\n"}, "local": {}}
        )
        with pytest.raises(InterpolationError, match="Unsupported interpolation type"):
            ConfigLoader(src)["catalog"]

    def test_credentials_resolve_per_file(self, make_conf):
        # A reference to a key in a *different* credentials file fails, because
        # credentials resolve file by file (matching OmegaConfigLoader).
        src = make_conf(
            {
                "base": {
                    "credentials_a.yml": "user: admin\n",
                    "credentials_b.yml": "other: ${user}\n",
                },
                "local": {},
            }
        )
        with pytest.raises(InterpolationError, match="not found"):
            ConfigLoader(src)["credentials"]


class TestCustomResolvers:
    def test_per_loader_resolver(self, make_conf):
        src = make_conf({"base": {"catalog.yml": "a: ${add:1,2}\n"}, "local": {}})
        loader = ConfigLoader(src, custom_resolvers={"add": lambda x, y: x + y})
        assert loader["catalog"] == {"a": 3}

    def test_process_wide_resolver(self, make_conf):
        from deepyaml import clear_resolvers, register_resolver

        register_resolver("triple", lambda x: x * 3)
        try:
            src = make_conf({"base": {"catalog.yml": "a: ${triple:5}\n"}, "local": {}})
            assert ConfigLoader(src)["catalog"] == {"a": 15}
        finally:
            clear_resolvers()
