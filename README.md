# deepyaml

Fast, antlr4-free hierarchical configuration loading for Python — a focused
alternative to OmegaConf for the subset that Kedro's `OmegaConfigLoader` needs.

## Why

OmegaConf is a powerful general-purpose typed-config system, but Kedro uses a thin
slice of it: load YAML/JSON → deep-merge environment layers → resolve `${...}`
interpolations → plain dict. The heavyweight piece OmegaConf carries for that slice
is **antlr4**, which is ~60% of its runtime cost (kedro-org/kedro#4322), bloats the
dependency tree, and is the reason OmegaConf can't be `micropip`-installed in
Pyodide/WASM.

`deepyaml` keeps the proven OmegaConf `${...}` semantics but drops antlr4 — a
hand-written interpolation engine over a fast YAML parser (`libyaml`). The result is
~40–50× faster on large/interpolation-heavy configs, pure-Python (trivially
WASM-compatible), and small enough to read in an afternoon. See `bench/RESULTS.md`
for the measurements.

## Status

Prototype. Pure-Python by design; a Rust port of the hot path (on `saphyr`) is a
possible future optimization, validated against this reference + the benchmark suite.

## Scope

Targets Kedro's `OmegaConfigLoader` usage, not full OmegaConf:

- YAML + JSON loading (the formats `OmegaConfigLoader` supports)
- deep-merge of environment layers (e.g. `base` then `local`)
- `${a.b}` references, and `globals` / `runtime_params` / `oc.env` / custom resolvers
- eager resolution to plain dicts (no lazy `DictConfig` object model)
