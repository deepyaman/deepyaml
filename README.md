# deepyaml

Fast, antlr4-free hierarchical config loading with OmegaConf-compatible
`${...}` interpolation — and a drop-in replacement for Kedro's
`OmegaConfigLoader`.

## Why

Kedro's `OmegaConfigLoader` uses [OmegaConf](https://github.com/omry/omegaconf)
for a narrow slice of what it offers: parse YAML/JSON, deep-merge files,
resolve `${...}`, return plain dicts. For that slice it pays for OmegaConf's
full object model and the antlr4 parser runtime, which dominates load time on
interpolation-heavy configs (see
[kedro#4322](https://github.com/kedro-org/kedro/issues/4322)) and blocks
installation in WASM/Pyodide environments.

deepyaml implements exactly that slice: libyaml-backed parsing with
OmegaConf's scalar typing, a regex-driven interpolation engine over plain
dicts, and `OmegaConfigLoader`'s layering semantics — in ~700 lines of pure
Python, depending only on PyYAML.

End-to-end loads of generated Kedro-style conf trees (median of 5, outputs
verified identical; see [bench/RESULTS.md](bench/RESULTS.md)):

| scenario | datasets | interpolation | OmegaConfigLoader | deepyaml | speedup |
|----------|---------:|---------------|------------------:|---------:|--------:|
| light    |       20 | none          |           10.5 ms |   0.9 ms |     12x |
| small    |       20 | heavy         |           44.4 ms |   1.9 ms |     24x |
| medium   |      200 | heavy         |          357.4 ms |  11.4 ms |     31x |
| large    |    2,000 | heavy         |          3,506 ms |   118 ms |     30x |

## Installation

```sh
pip install deepyaml        # standalone
pip install deepyaml[kedro] # with the Kedro adapter
```

## Usage with Kedro

Point `CONFIG_LOADER_CLASS` at the adapter in your project's `settings.py`:

```python
from deepyaml.kedro import DeepYAMLConfigLoader

CONFIG_LOADER_CLASS = DeepYAMLConfigLoader
```

Everything else — `conf/base` and `conf/local` layering, `catalog*` /
`parameters*` / `credentials*` / `globals.yml` patterns, `${globals:...}`,
`${runtime_params:...}`, `${oc.env:...}` (credentials only), templating via
`_`-prefixed keys, `CONFIG_LOADER_ARGS` such as `config_patterns`,
`custom_resolvers`, and `merge_strategy` — works as it does with
`OmegaConfigLoader`. The test suite asserts scenario-by-scenario equivalence,
type-identical output included, against the real `OmegaConfigLoader`.

## Standalone usage

```python
from deepyaml import ConfigLoader

loader = ConfigLoader("conf", runtime_params={"seed": 42})
catalog = loader["catalog"]      # plain dict, fully resolved
parameters = loader["parameters"]
```

`ConfigLoader` accepts `base_env`/`run_env` (default `"base"`/`"local"`),
`config_patterns`, `custom_resolvers`, `merge_strategy`
(`{"catalog": "soft"}` for deep env merging), and `ignore_hidden`.

The building blocks are importable on their own:

```python
from deepyaml import merge, parse_file, register_format, register_resolver, resolve

register_resolver("upper", str.upper)
resolve({"a": "x", "b": "${upper:${a}}"})  # nope -- nested interpolation; see below
resolve({"a": "x", "b": "${upper:hi}"})    # {"a": "x", "b": "HI"}
```

## Supported `${...}` syntax

| form | example | notes |
|------|---------|-------|
| node reference | `${model.seed}` | dotted path, same document (per environment) |
| resolver call | `${globals:datasets.csv}`, `${oc.env:VAR,default}` | args are typed literals (`int`, `float`, `true`, `null`, quoted strings) |
| concatenation | `${folder}/raw/${name}.csv` | values stringified |
| type preservation | `x: ${big.subtree}` | a whole-string interpolation keeps the resolved type |
| escape | `\${literal}` | left as literal `${literal}` |

Not supported (by design, for now): nested interpolations (`${a.${b}}`) and
quoted resolver arguments containing commas.

## Compatibility notes

deepyaml matches `OmegaConfigLoader`'s observable behavior, including YAML 1.1
scalar typing (`no` → `False`, `12:30` → `750`, dates stay strings, `1e3` is a
float), duplicate-key errors (nested for parameters, top-level otherwise),
destructive-by-default environment merging, per-environment interpolation
scope, per-file `oc.env` resolution in credentials, and
`MissingConfigException` semantics (via the adapter). Known divergences:

- **Local filesystems only.** Remote (`s3://`, `http://`) and archive
  (`.tar`, `.zip`) conf sources are not supported.
- **Error types.** `MissingConfigException` and `ValueError` (duplicate keys)
  match Kedro's; parse and interpolation failures raise deepyaml's own
  exceptions (all `DeepYAMLError` subclasses) with equivalent messages.
- **JSON is parsed by `json`**, not through the YAML parser as OmegaConf does
  (differences only for edge cases like `1e3`, which JSON reads as a float).
- **Resolver registry.** Resolvers registered with
  `OmegaConf.register_new_resolver` are not seen by deepyaml; use
  `deepyaml.register_resolver` or `custom_resolvers`.
- Files within one directory merge in sorted order (Kedro's order is
  unspecified); observable only for overlapping `_`-prefixed keys.

## Development

```sh
uv sync --group dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The equivalence and adapter suites require the `dev` group's Kedro/OmegaConf
and skip cleanly without them.

## License

MIT
