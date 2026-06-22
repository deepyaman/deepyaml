"""Benchmark OmegaConf / Kedro OmegaConfigLoader on the generated conf trees.

Run with omegaconf + kedro available, e.g.:
    uv run --with kedro --with omegaconf python bench_omegaconf.py

Measures:
  1. end-to-end Kedro OmegaConfigLoader (load + merge + resolve + to_container -> plain dict)
  2. a phase breakdown via raw omegaconf (parse vs merge vs resolve)
across config scales, plus reports the pure-Python baseline on the same workload.
"""

from __future__ import annotations

import time
from pathlib import Path
from statistics import median

HERE = Path(__file__).parent
CONFIGS = HERE / "configs"
SIZES = ["light", "small", "medium", "large"]
RUNTIME_PARAMS = {"bucket": "bench-bucket", "seed": 42}


def timeit(fn, repeats: int = 7) -> float:
    """Return median wall time (ms) of fn over `repeats` runs."""
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e3)
    return median(samples)


def bench_kedro(size: str) -> float:
    from kedro.config import OmegaConfigLoader

    src = str(CONFIGS / size)

    def run():
        cl = OmegaConfigLoader(conf_source=src, base_env="base", default_run_env="local",
                               runtime_params=RUNTIME_PARAMS)
        # Accessing keys triggers load+merge+resolve+to_container -> plain dict.
        _ = cl["catalog"]
        try:
            _ = cl["parameters"]
        except Exception:
            pass

    return timeit(run)


def bench_omegaconf_phases(size: str) -> dict[str, float]:
    """Break OmegaConf cost into parse / merge / resolve using raw omegaconf."""
    from omegaconf import OmegaConf

    base = CONFIGS / size / "base"
    files = sorted(base.glob("catalog_*.yml"))
    globals_file = base / "globals.yml"

    # register the resolvers Kedro provides so resolve() works
    if not OmegaConf.has_resolver("runtime_params"):
        OmegaConf.register_new_resolver(
            "runtime_params", lambda key, default=None: RUNTIME_PARAMS.get(key, default))
    g = OmegaConf.load(globals_file) if globals_file.exists() else OmegaConf.create({})
    if not OmegaConf.has_resolver("globals"):
        OmegaConf.register_new_resolver(
            "globals", lambda key, default=None: OmegaConf.select(g, key, default=default))

    text = [f.read_text() for f in files]  # pre-read so we time parse, not disk

    def parse():
        return [OmegaConf.create(t) for t in text]

    parsed = parse()

    def merge():
        return OmegaConf.merge(*parsed)

    merged = merge()

    def resolve():
        return OmegaConf.to_container(merged, resolve=True)

    return {
        "parse": timeit(parse),
        "merge": timeit(merge),
        "resolve": timeit(resolve),
    }


def bench_baseline(size: str) -> float:
    from baseline_py import load_config

    src = CONFIGS / size

    def run():
        load_config(src, runtime_params=RUNTIME_PARAMS)

    return timeit(run)


def main() -> None:
    print(f"{'size':8s} {'kedro(ms)':>11s} {'parse':>8s} {'merge':>8s} {'resolve':>9s} "
          f"{'oc-total':>9s} {'pybase(ms)':>11s}")
    print("-" * 72)
    rows = []
    for size in SIZES:
        if not (CONFIGS / size).exists():
            continue
        kedro_ms = bench_kedro(size)
        phases = bench_omegaconf_phases(size)
        oc_total = sum(phases.values())
        try:
            py_ms = bench_baseline(size)
        except Exception as e:  # baseline may not cover every case yet
            py_ms = float("nan")
            print(f"  (baseline failed on {size}: {e})")
        rows.append((size, kedro_ms, phases, oc_total, py_ms))
        print(f"{size:8s} {kedro_ms:11.2f} {phases['parse']:8.2f} {phases['merge']:8.2f} "
              f"{phases['resolve']:9.2f} {oc_total:9.2f} {py_ms:11.2f}")


if __name__ == "__main__":
    main()
