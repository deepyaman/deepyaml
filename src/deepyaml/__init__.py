"""deepyaml — fast, antlr4-free hierarchical configuration loading.

A focused, pure-Python alternative to OmegaConf for the subset Kedro's
``OmegaConfigLoader`` relies on: load YAML/JSON, deep-merge environment layers,
eagerly resolve ``${...}`` interpolations/resolvers, and return plain dicts.

See ``bench/RESULTS.md`` for the measurements behind the pure-Python design.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
