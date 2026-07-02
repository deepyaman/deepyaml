"""The ${...} interpolation engine and resolver registry."""

from __future__ import annotations

import pytest

from deepyaml import (
    InterpolationError,
    clear_resolvers,
    has_resolver,
    register_resolver,
    resolve,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    clear_resolvers()


class TestReferences:
    def test_dotted_reference(self):
        data = {"db": {"host": "localhost"}, "url": "${db.host}"}
        assert resolve(data)["url"] == "localhost"

    def test_type_preservation_for_full_interpolation(self):
        data = {"a": 1, "b": "${a}", "c": {"x": [1, 2]}, "d": "${c}"}
        resolved = resolve(data)
        assert resolved["b"] == 1
        assert resolved["d"] == {"x": [1, 2]}

    def test_string_concatenation(self):
        data = {"folder": "data", "name": "x", "path": "${folder}/raw/${name}.csv"}
        assert resolve(data)["path"] == "data/raw/x.csv"

    def test_concatenation_stringifies(self):
        assert resolve({"a": 1, "b": "v${a}"})["b"] == "v1"

    def test_chained_references(self):
        data = {"a": "${b}", "b": "${c}", "c": 42}
        assert resolve(data)["a"] == 42

    def test_reference_inside_list(self):
        assert resolve({"a": 1, "xs": ["${a}", "${a}"]})["xs"] == [1, 1]

    def test_missing_key_raises(self):
        with pytest.raises(InterpolationError, match=r"'a\.b' not found"):
            resolve({"x": "${a.b}"})

    def test_cycle_raises(self):
        with pytest.raises(InterpolationError, match=r"[Cc]ircular"):
            resolve({"a": "${b}", "b": "${a}"})

    def test_self_reference_raises(self):
        with pytest.raises(InterpolationError, match=r"[Cc]ircular"):
            resolve({"a": "${a}"})

    def test_escaped_interpolation_is_literal(self):
        assert resolve({"a": "\\${not.a.ref}"})["a"] == "${not.a.ref}"

    def test_non_string_values_untouched(self):
        data = {"a": 1, "b": None, "c": True, "d": [1, "x"]}
        assert resolve(data) == data


class TestResolvers:
    def test_oc_env_builtin(self, monkeypatch):
        monkeypatch.setenv("DEEPYAML_TEST_VAR", "hello")
        assert resolve({"a": "${oc.env:DEEPYAML_TEST_VAR}"})["a"] == "hello"

    def test_oc_env_default(self, monkeypatch):
        monkeypatch.delenv("DEEPYAML_TEST_VAR", raising=False)
        assert resolve({"a": "${oc.env:DEEPYAML_TEST_VAR,fallback}"})["a"] == "fallback"

    def test_oc_env_missing_raises(self, monkeypatch):
        monkeypatch.delenv("DEEPYAML_TEST_VAR", raising=False)
        with pytest.raises(InterpolationError, match="DEEPYAML_TEST_VAR"):
            resolve({"a": "${oc.env:DEEPYAML_TEST_VAR}"})

    def test_registered_resolver(self):
        register_resolver("double", lambda x: x * 2)
        assert resolve({"a": "${double:21}"})["a"] == 42

    def test_register_duplicate_raises_unless_replace(self):
        register_resolver("once", lambda: 1)
        with pytest.raises(ValueError, match="already registered"):
            register_resolver("once", lambda: 2)
        register_resolver("once", lambda: 2, replace=True)
        assert resolve({"a": "${once:}"})["a"] == 2

    def test_has_resolver(self):
        assert has_resolver("oc.env")
        assert not has_resolver("nope")
        register_resolver("nope", lambda: None)
        assert has_resolver("nope")

    def test_explicit_map_overrides_everything(self):
        assert resolve({"a": "${f:1}"}, {"f": lambda x: x + 1})["a"] == 2

    def test_unknown_resolver_raises(self):
        with pytest.raises(InterpolationError, match="Unsupported interpolation type"):
            resolve({"a": "${nope:1}"}, {})

    @pytest.mark.parametrize(
        ("literal", "expected"),
        [
            ("1", 1),
            ("1.5", 1.5),
            ("true", True),
            ("False", False),
            ("null", None),
            ("~", None),
            ("'quoted'", "quoted"),
            ('"1"', "1"),
            ("plain", "plain"),
        ],
    )
    def test_argument_literals_are_typed(self, literal, expected):
        captured = {}
        resolvers = {"grab": lambda x: captured.setdefault("arg", x)}
        resolve({"a": f"${{grab:{literal}}}"}, resolvers)
        assert captured["arg"] == expected
        assert type(captured["arg"]) is type(expected)

    def test_multiple_arguments_with_whitespace(self):
        resolvers = {"join": lambda *args: "-".join(map(str, args))}
        assert resolve({"a": "${join:x, 1, true}"}, resolvers)["a"] == "x-1-True"

    def test_no_arguments(self):
        assert resolve({"a": "${f:}"}, {"f": lambda: "ok"})["a"] == "ok"


class TestRootOverride:
    def test_resolve_against_external_root(self):
        fragment = {"url": "${db.host}"}
        root = {"db": {"host": "h"}}
        assert resolve(fragment, {}, root=root)["url"] == "h"
