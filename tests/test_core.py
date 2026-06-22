"""Core engine: parsing, merge, interpolation, resolvers."""

from __future__ import annotations

import pytest

import deepyaml as d
from deepyaml.errors import InterpolationError
from deepyaml.resolvers import build_resolver_map, clear_custom_resolvers


def test_loads_yaml_and_json():
    assert d.loads("a: 1\nb: [1, 2]") == {"a": 1, "b": [1, 2]}
    assert d.loads('{"a": 1, "b": [1, 2]}', "json") == {"a": 1, "b": [1, 2]}


def test_yaml_11_scalar_typing():
    # libyaml/PyYAML are YAML 1.1 (matches OmegaConf): Norway problem, octal, sexagesimal
    cfg = d.loads("a: yes\nb: no\nc: 017\ndd: 12:30")
    assert cfg == {"a": True, "b": False, "c": 15, "dd": 750}


def test_merge_later_wins_and_replaces_lists():
    a = {"x": {"a": 1, "b": 2}, "l": [1, 2]}
    b = {"x": {"b": 3}, "l": [9]}
    assert d.merge(a, b) == {"x": {"a": 1, "b": 3}, "l": [9]}


def test_merge_does_not_mutate_inputs():
    a = {"x": {"a": 1}}
    b = {"x": {"b": 2}}
    result = d.merge(a, b)
    result["x"]["a"] = 999
    assert a == {"x": {"a": 1}}  # unchanged
    assert b == {"x": {"b": 2}}  # unchanged


def test_resolve_uses_builtin_resolvers_by_default(monkeypatch):
    monkeypatch.setenv("DEEPYAML_Y", "ok")
    # no resolvers passed -> oc.env still works
    assert d.resolve(d.loads("a: ${oc.env:DEEPYAML_Y}")) == {"a": "ok"}


def test_interpolation_reference_and_concat():
    cfg = d.loads("base: data\nlayer: raw\npath: ${base}/${layer}/f.csv")
    assert d.resolve(cfg)["path"] == "data/raw/f.csv"


def test_interpolation_preserves_type():
    cfg = d.loads("port: 5432\nref: ${port}")
    out = d.resolve(cfg)
    assert out["ref"] == 5432 and isinstance(out["ref"], int)


def test_resolver_with_typed_default():
    resolvers = build_resolver_map({"rp": lambda k, default=None: {"seed": 42}.get(k, default)})
    assert d.resolve(d.loads("x: ${rp:seed,7}"), resolvers)["x"] == 42
    assert d.resolve(d.loads("x: ${rp:missing,7}"), resolvers)["x"] == 7  # int, not "7"


def test_oc_env_resolver(monkeypatch):
    monkeypatch.setenv("DEEPYAML_X", "hello")
    out = d.resolve(d.loads("a: ${oc.env:DEEPYAML_X}\nb: ${oc.env:NOPE,fallback}"),
                    build_resolver_map())
    assert out == {"a": "hello", "b": "fallback"}


def test_oc_env_missing_without_default_raises():
    with pytest.raises(InterpolationError):
        d.resolve(d.loads("a: ${oc.env:DEFINITELY_NOT_SET_DEEPYAML}"), build_resolver_map())


def test_escaped_interpolation_is_literal():
    assert d.resolve(d.loads(r"a: \${not_resolved}"))["a"] == "${not_resolved}"


def test_missing_reference_raises():
    with pytest.raises(InterpolationError):
        d.resolve(d.loads("a: ${does.not.exist}"))


def test_cycle_is_detected():
    with pytest.raises(InterpolationError):
        d.resolve(d.loads("a: ${b}\nb: ${a}"))


def test_register_custom_resolver():
    clear_custom_resolvers()
    d.register_resolver("double", lambda x: int(x) * 2)
    assert d.resolve(d.loads("a: ${double:21}"), build_resolver_map())["a"] == 42
    clear_custom_resolvers()
