"""The parsing layer, including OmegaConf-compatible YAML scalar typing."""

from __future__ import annotations

import pytest

from deepyaml import ParseError, parse, parse_file, register_format
from deepyaml.parsing import parse_yaml


class TestYamlTyping:
    """OmegaConf parses YAML 1.1 with two tweaks; match it exactly."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("no", False),  # YAML 1.1 booleans
            ("on", True),
            ("12:30", 750),  # YAML 1.1 sexagesimal
            ("0777", 511),  # YAML 1.1 octal
            ("1e3", 1000.0),  # OmegaConf extension: exponent-only floats
            ("1.5", 1.5),
            (".inf", float("inf")),
            ("2024-01-01", "2024-01-01"),  # OmegaConf drops the timestamp resolver
            ("2024-01-01T00:00:00", "2024-01-01T00:00:00"),
            ("null", None),
            ("hello", "hello"),
        ],
    )
    def test_scalar(self, text, expected):
        value = parse_yaml(f"key: {text}")["key"]
        assert value == expected
        assert type(value) is type(expected)

    def test_duplicate_keys_in_one_mapping_raise(self):
        with pytest.raises(ParseError, match="duplicate key"):
            parse_yaml("a: 1\na: 2\n")

    def test_anchors_and_merge_keys(self):
        data = parse_yaml("_base: &base\n  x: 1\nchild:\n  <<: *base\n  y: 2\n")
        assert data["child"] == {"x": 1, "y": 2}

    def test_empty_document(self):
        assert parse_yaml("") is None
        assert parse_yaml("# only a comment\n") is None


class TestErrors:
    def test_invalid_yaml_reports_position(self):
        with pytest.raises(ParseError, match=r"line \d+, column \d+"):
            parse_yaml("a: [1, 2\nb: 3\n")

    def test_invalid_json_reports_position(self):
        with pytest.raises(ParseError, match=r"line \d+, column \d+"):
            parse('{"a": 1,}', fmt="json")

    def test_parse_file_prefixes_path(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text("a: [1\n")
        with pytest.raises(ParseError, match=r"bad\.yml"):
            parse_file(bad)

    def test_unknown_format(self):
        with pytest.raises(ValueError, match="unknown format"):
            parse("a = 1", fmt="ini")

    def test_unsupported_suffix(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("a = 1\n")
        with pytest.raises(ValueError, match="unsupported config file extension"):
            parse_file(path)


class TestRegistry:
    def test_parse_file_routes_by_suffix(self, tmp_path):
        (tmp_path / "c.yaml").write_text("a: 1\n")
        (tmp_path / "c.json").write_text('{"a": 1}')
        assert parse_file(tmp_path / "c.yaml") == {"a": 1}
        assert parse_file(tmp_path / "c.json") == {"a": 1}

    def test_register_format(self, tmp_path):
        def parse_kv(text):
            return dict(line.split("=", 1) for line in text.splitlines())

        register_format("kv", parse_kv, ".kv")
        try:
            path = tmp_path / "config.kv"
            path.write_text("a=1\nb=x")
            assert parse_file(path) == {"a": "1", "b": "x"}
        finally:
            from deepyaml.parsing import PARSERS, SUFFIXES

            PARSERS.pop("kv", None)
            SUFFIXES.pop(".kv", None)
