# Benchmark results

End-to-end load of all default keys (globals, catalog, parameters,
credentials) through Kedro's `OmegaConfigLoader` vs `DeepYAMLConfigLoader`,
median of 5 runs, outputs verified identical before timing.

| scenario | datasets | interpolation | OmegaConfigLoader | DeepYAMLConfigLoader | speedup |
|----------|---------:|---------------|------------------:|---------------------:|--------:|
| light    |       20 | none          |           11.0 ms |                1.0 ms |   11.1x |
| small    |       20 | heavy         |           42.6 ms |                1.7 ms |   24.5x |
| medium   |      200 | heavy         |          361.8 ms |               11.5 ms |   31.4x |
| large    |    2,000 | heavy         |         3,534.8 ms |              119.6 ms |   29.6x |

Environment: macOS 13.6 (arm64), CPython 3.10.18, kedro 1.6.0,
omegaconf 2.3.1, PyYAML 6.0.3 (libyaml). 2026-09-09.

The gap grows with interpolation density: OmegaConf parses every `${...}`
occurrence through the antlr4 runtime at resolution time, which dominates its
cost on catalog-scale configs (see Kedro issue
[#4322](https://github.com/kedro-org/kedro/issues/4322)). deepyaml replaces
that with a regex-driven engine over plain dicts, and libyaml handles the
parse.

Reproduce with:

```sh
uv run python bench/gen_configs.py
uv run python bench/compare.py
```
