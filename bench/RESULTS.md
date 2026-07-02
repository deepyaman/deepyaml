# Benchmark results

End-to-end load of all default keys (globals, catalog, parameters,
credentials) through Kedro's `OmegaConfigLoader` vs `DeepYAMLConfigLoader`,
median of 5 runs, outputs verified identical before timing.

| scenario | datasets | interpolation | OmegaConfigLoader | DeepYAMLConfigLoader | speedup |
|----------|---------:|---------------|------------------:|---------------------:|--------:|
| light    |       20 | none          |           10.5 ms |                0.9 ms |   12.3x |
| small    |       20 | heavy         |           44.4 ms |                1.9 ms |   23.5x |
| medium   |      200 | heavy         |          357.4 ms |               11.4 ms |   31.2x |
| large    |    2,000 | heavy         |         3,506.0 ms |              118.0 ms |   29.7x |

Environment: macOS 13.6 (arm64), CPython 3.10.18, kedro 1.5.0,
omegaconf 2.3.1, PyYAML 6.0.3 (libyaml). 2026-07-02.

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
