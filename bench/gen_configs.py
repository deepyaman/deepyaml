"""Generate representative Kedro conf trees for benchmarking.

Produces conf/ trees that mirror real Kedro usage: a globals file plus catalog and
parameter files that exercise the interpolation/resolver paths users actually write
(`${globals:...}`, `${oc.env:...}`, `${runtime_params:...}`), spread across multiple
files so cross-file merge + duplicate-key detection are exercised too.

Usage:
    python gen_configs.py            # writes configs/{light,small,medium,large}
"""

from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "configs"

GLOBALS = """\
base_folder: data
raw_layer: 01_raw
int_layer: 02_intermediate
sep: ","
dataset_type: pandas.CSVDataset
"""

CREDENTIALS = """\
db:
  con: ${runtime_params:db_url,sqlite:///local.db}
  username: admin
"""


def catalog_entry(i: int, *, interp: bool) -> str:
    if interp:
        return f"""\
dataset_{i:05d}:
  type: ${{globals:dataset_type}}
  filepath: ${{globals:base_folder}}/${{globals:raw_layer}}/dataset_{i:05d}.csv
  load_args:
    sep: ${{globals:sep}}
  metadata:
    bucket: ${{runtime_params:bucket,default-bucket}}
    env: ${{runtime_params:env,local}}
"""
    return f"""\
dataset_{i:05d}:
  type: pandas.CSVDataset
  filepath: data/01_raw/dataset_{i:05d}.csv
  load_args:
    sep: ","
"""


PARAMETERS = """\
model_options:
  test_size: 0.2
  random_state: ${runtime_params:seed,3}
  features:
    - engines
    - passenger_capacity
    - crew
data_dir: ${globals:base_folder}/${globals:int_layer}
"""


def gen(name: str, *, n_datasets: int, n_files: int, interp: bool) -> None:
    root = OUT / name
    if root.exists():
        shutil.rmtree(root)
    base = root / "base"
    local = root / "local"
    base.mkdir(parents=True)
    local.mkdir(parents=True)

    if interp:
        (base / "globals.yml").write_text(GLOBALS)
        (base / "parameters.yml").write_text(PARAMETERS)
    (local / "credentials.yml").write_text(CREDENTIALS if interp else "db:\n  username: admin\n")

    # Spread datasets across n_files catalog_*.yml files (unique keys => no dup errors).
    per_file = max(1, n_datasets // n_files)
    idx = 0
    for f in range(n_files):
        count = per_file if f < n_files - 1 else n_datasets - idx
        body = "".join(catalog_entry(idx + j, interp=interp) for j in range(count))
        (base / f"catalog_{f:03d}.yml").write_text(body)
        idx += count

    print(f"{name:8s}: {n_datasets:5d} datasets across {n_files} files, interp={interp}  -> {root}")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    # light: realistic size, NO interpolation (isolates parse+merge from resolve cost)
    gen("light", n_datasets=20, n_files=2, interp=False)
    # interpolation-heavy at three scales (every dataset hits the resolver path)
    gen("small", n_datasets=20, n_files=2, interp=True)
    gen("medium", n_datasets=200, n_files=10, interp=True)
    gen("large", n_datasets=2000, n_files=40, interp=True)
