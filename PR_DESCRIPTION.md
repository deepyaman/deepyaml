# Prototype: pure-Python `deepyaml` config loader (OmegaConfigLoader-compatible, antlr4-free)

> Temporary PR description for branch `prototype/pure-python`. Delete before merge.

## Summary

A focused, pure-Python alternative to OmegaConf for the subset Kedro's
`OmegaConfigLoader` actually uses: load YAML/JSON → deep-merge environment layers →
eagerly resolve `${...}` interpolations/resolvers → plain dict. Drops the antlr4
dependency entirely.

Ships a `DeepYAMLConfigLoader(AbstractConfigLoader)` so it's a drop-in for Kedro via
`CONFIG_LOADER_CLASS` — no changes to Kedro core.

## Why

Decision was reached **by measurement** (full investigation in `bench/RESULTS.md`):

- OmegaConf's cost on interpolation-heavy configs is ~60% the antlr4 grammar visitor
  (`to_container` resolve) — the exact bottleneck in kedro-org/kedro#4322. Removing
  antlr4 is the entire win, and it's captured in pure Python.
- OmegaConf can't be `micropip`-installed in Pyodide (it pins `antlr4-python3-runtime==4.9.*`,
  which is sdist-only). A pure-Python loader runs in WASM trivially.
- libyaml = YAML 1.1 = **exact OmegaConf scalar parity** for free.
- Rust's only real edge (parse speed) is rentable via `py-yaml12`; building the library
  itself in Rust would tax WASM, Kedro adoption, and maintainability for no net gain.

## What's included

- `src/deepyaml/` — Kedro-agnostic core:
  - `_parsers` (libyaml + JSON, pluggable registry), `_merge`, `interpolation`
    (antlr4-free `${...}`: refs, concat, type preservation, escaping, cycle guard),
    `resolvers` (`oc.env` + `register_resolver`), `loader.ConfigLoader`.
  - `kedro.DeepYAMLConfigLoader` — thin `AbstractConfigLoader` adapter (lazy kedro import).
- `tests/` — 27 tests: core, loader, and **byte-identical equivalence vs `OmegaConfigLoader`**.
- `bench/` — the spike + an apples-to-apples benchmark of the real loader.
- Build pivoted maturin/PyO3 → hatchling; pure `py3-none-any` wheel.

## Results

| config (datasets) | OmegaConfigLoader | DeepYAMLConfigLoader | speedup |
|---|---:|---:|---:|
| light (20, no interp) | 10.4 ms | 0.78 ms | 13.3× |
| small (20, interp) | 41.9 ms | 1.52 ms | 27.6× |
| medium (200, interp) | 360.8 ms | 10.9 ms | 33.0× |
| large (2000, interp) | 3574.6 ms | 105 ms | 33.9× |

Verified **byte-identical** to `OmegaConfigLoader` on the generated interpolation-heavy
configs and the spaceflights starter (`globals`/`catalog`/`parameters`/`credentials`).

## How to try

```bash
PYTHONPATH=src uv run --no-project --with pytest --with kedro python -m pytest tests/ -q
PYTHONPATH=bench/../src uv run --no-project --with kedro --with pyyaml python bench/bench_omegaconf.py
```

In a Kedro project's `settings.py`:

```python
from deepyaml.kedro import DeepYAMLConfigLoader
CONFIG_LOADER_CLASS = DeepYAMLConfigLoader
```

## Scope / known limitations

- Targets the `OmegaConfigLoader` usage path, not full OmegaConf (no lazy `DictConfig`
  object model, structured/dataclass configs, type enforcement).
- Nested interpolation `${a.${b}}` unsupported (rare in Kedro).
- Duplicate-key detection is top-level only (Kedro checks nested keys too).
- `[yaml12]` (opt-in YAML 1.2 backend) is declared but not yet wired — `register_format`
  is the hook.
- No `kedro run` integration test; config-equivalence covers the loader contract.

## Follow-ups

- Wire the optional `py-yaml12` (YAML 1.2) backend behind a flag.
- Add `py.typed`, a `LICENSE` file, and CI (3.9–3.13 matrix).
- Optional: Rust port of the hot path on `saphyr`, validated against this reference.
