"""Shared fixtures: build a temporary conf tree (base/ + local/)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def make_conf(tmp_path: Path):
    """Return a helper that writes ``{env: {filename: text}}`` and returns conf_source."""

    def _make(layout: dict[str, dict[str, str]]) -> Path:
        for env, files in layout.items():
            env_dir = tmp_path / env
            env_dir.mkdir(parents=True, exist_ok=True)
            for filename, text in files.items():
                (env_dir / filename).write_text(text)
        return tmp_path

    return _make
