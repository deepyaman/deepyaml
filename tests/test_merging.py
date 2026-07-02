"""Deep-merge semantics (OmegaConf-compatible)."""

from __future__ import annotations

from deepyaml import merge


def test_later_sources_win():
    assert merge({"a": 1}, {"a": 2}, {"a": 3}) == {"a": 3}


def test_nested_dicts_merge_recursively():
    assert merge(
        {"a": {"x": 1, "y": 1}, "b": 1},
        {"a": {"y": 2, "z": 2}},
    ) == {"a": {"x": 1, "y": 2, "z": 2}, "b": 1}


def test_lists_are_replaced_not_concatenated():
    assert merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


def test_dict_replaced_by_scalar_and_vice_versa():
    assert merge({"a": {"x": 1}}, {"a": 2}) == {"a": 2}
    assert merge({"a": 2}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_none_replaces_dict():
    assert merge({"a": {"x": 1}}, {"a": None}) == {"a": None}


def test_inputs_are_not_mutated():
    first = {"a": {"x": 1}}
    second = {"a": {"y": 2}}
    merge(first, second)
    assert first == {"a": {"x": 1}}
    assert second == {"a": {"y": 2}}


def test_result_shares_no_state_with_inputs():
    source = {"a": {"x": [1]}}
    result = merge(source)
    result["a"]["x"].append(2)
    assert source == {"a": {"x": [1]}}


def test_empty_and_single_source():
    assert merge() == {}
    assert merge({"a": 1}) == {"a": 1}
