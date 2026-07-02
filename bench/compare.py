"""Benchmark DeepYAMLConfigLoader against Kedro's OmegaConfigLoader.

For each generated conf tree (see ``gen_configs.py``), time an end-to-end
load of every default key (globals, catalog, parameters, credentials) with
both loaders, verify the outputs are identical, and print a markdown table.

Usage:
    python bench/gen_configs.py
    python bench/compare.py [--repeat 5]
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from kedro.config import MissingConfigException, OmegaConfigLoader

from deepyaml.kedro import DeepYAMLConfigLoader

HERE = Path(__file__).parent
CONFIGS = HERE / "configs"
KEYS = ["globals", "catalog", "parameters", "credentials"]
RUNTIME_PARAMS = {"seed": 42, "bucket": "bench-bucket", "env": "prod"}


def load_all(loader_cls, conf_source: Path) -> dict:
    loader = loader_cls(
        conf_source=str(conf_source),
        base_env="base",
        default_run_env="local",
        runtime_params=dict(RUNTIME_PARAMS),
    )
    configs = {}
    for key in KEYS:
        try:
            configs[key] = loader[key]
        except MissingConfigException:
            # Optional config, exactly how Kedro's framework treats it.
            configs[key] = {}
    return configs


def best_of(loader_cls, conf_source: Path, repeat: int) -> float:
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        load_all(loader_cls, conf_source)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    order = {"light": 0, "small": 1, "medium": 2, "large": 3}
    scenarios = sorted(
        (p for p in CONFIGS.iterdir() if p.is_dir()),
        key=lambda p: order.get(p.name, 99),
    )
    if not scenarios:
        raise SystemExit("no generated configs; run `python bench/gen_configs.py`")

    print("| scenario | OmegaConfigLoader | DeepYAMLConfigLoader | speedup |")
    print("|----------|------------------:|---------------------:|--------:|")
    for scenario in scenarios:
        theirs = load_all(OmegaConfigLoader, scenario)
        ours = load_all(DeepYAMLConfigLoader, scenario)
        assert ours == theirs, f"{scenario.name}: outputs differ"

        t_ocl = best_of(OmegaConfigLoader, scenario, args.repeat)
        t_dyl = best_of(DeepYAMLConfigLoader, scenario, args.repeat)
        print(
            f"| {scenario.name} | {t_ocl * 1000:9.1f} ms | {t_dyl * 1000:9.1f} ms "
            f"| {t_ocl / t_dyl:6.1f}x |"
        )


if __name__ == "__main__":
    main()
