"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def make_conf(tmp_path: Path):
    """Write ``{env: {relative/path.yml: text}}`` under a temp conf source.

    Returns the conf source path. File keys may contain subdirectories.
    """

    def _make(layout: dict[str, dict[str, str]]) -> Path:
        for env, files in layout.items():
            (tmp_path / env).mkdir(parents=True, exist_ok=True)
            for relative_path, text in files.items():
                path = tmp_path / env / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        return tmp_path

    return _make
