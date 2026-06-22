# Spike results: OmegaConf vs. pure-Python, and the WASM question

**Decision being gated:** is Rust/PyO3 justified for a Kedro config loader, or does a
pure-Python (no-antlr4) loader already capture the wins?

Environment: macOS, Python 3.10, OmegaConf 2.3.1, Kedro (latest), Pyodide 0.26.4.
Reproduce: `python gen_configs.py` then `uv run --with kedro --with pyyaml python bench_omegaconf.py`,
`node pyodide_check.mjs`.

## 1. Warm throughput (median ms, in-process)

`kedro` = real `OmegaConfigLoader` end-to-end (load+merge+resolve→plain dict).
parse/merge/resolve = OmegaConf phase breakdown. `pybase` = our pure-Python baseline doing the
**same work** without antlr4.

`pybase` uses PyYAML's **libyaml C loader** (`CSafeLoader`).

| size (datasets) | kedro | parse | merge | resolve | oc-total | **pybase** | oc/py |
|---|---:|---:|---:|---:|---:|---:|---:|
| light  (20, no interp) |    9.9 |    7.0 |   2.3 |    0.4 |    9.7 | **0.46** | 21× |
| small  (20, interp)    |   40.8 |   11.4 |   3.2 |   23.1 |   37.7 | **0.81** | 50× |
| medium (200, interp)   |  364.8 |  112.0 |  35.8 |  232.1 |  379.8 |  **7.4** | 49× |
| large  (2000, interp)  | 3578.5 | 1188.8 | 407.3 | 2311.1 | 3907.2 | **81.6** | 44× |

**Findings**
- **Interpolation resolve (antlr4 grammar visitor) is ~60% of OmegaConf's cost** whenever
  `${...}` is present; parse ~30%, merge ~10%. Merge — the thing we first assumed Rust would
  win — is the *smallest* cost.
- **A trivial pure-Python loader is ~40–50× faster than OmegaConf** doing identical work, via
  two pure-Python levers: (1) drop antlr4 (regex/hand-written resolver), (2) use libyaml
  (`CSafeLoader`). **Neither lever needs Rust.**
- **Absolute times are scale-dependent:** a 20-dataset project loads in <1 ms (pure-Python) vs
  ~41 ms (OmegaConf) — negligible. But large / interpolation-heavy catalogs (hundreds–thousands
  of datasets, common in enterprise projects) reach **hundreds of ms to seconds** in OmegaConf
  (2000 datasets: 3.6 s vs 82 ms). At that scale the gap *is* felt.

- **This perf pain is maintainer-acknowledged, not hypothetical.** Kedro issue
  [#4322](https://github.com/kedro-org/kedro/issues/4322) ("Improve OmegaConfigLoader performance
  when global/variable interpolations are involved", extending #3893, under the *Improve
  performance of Kedro* milestone, closed via PR #4367) identifies the bottleneck as
  **`OmegaConf.to_container` resolving interpolations** — exactly the `resolve` phase this
  benchmark measures at ~60% of cost. Crucially, the benchmark above ran against **Kedro 1.4.0**,
  which already includes those fixes, and still shows the 40–50× gap: OmegaConf-side tuning
  *mitigates* but cannot remove antlr4's structural per-interpolation cost. A no-antlr4 loader
  eliminates it by construction.

### 1b. Where does the *pure-Python* time go? (mypyc/Rust relevance)

Profiling the baseline on `large` (2000 datasets), phases isolated:

| phase | time | share | compilable? |
|---|---:|---:|---|
| YAML parse — pure-Python `SafeLoader` | 607 ms | — | (use libyaml instead) |
| YAML parse — **libyaml `CSafeLoader`** | **65 ms** | **81%** | already C; Rust ≈ libyaml-class |
| deep-merge | ~0 ms | 0% | n/a |
| interpolation **resolve** (regex) | **15 ms** | **19%** | yes — but tiny |
| **total (pure-Python + libyaml)** | **80 ms** | | |

(At 200 datasets: parse 6.2 / merge 0.0 / resolve 1.4 ms.)

**Key point:** the original "~60% bottleneck" was OmegaConf's *antlr4* resolve. Switching to
pure-Python **eliminates** it — the regex resolver is only **~19% of a 40–50× smaller total**.
So there is no 60% bottleneck left for mypyc/Rust to attack; the resolve glue is 15 ms at the
2000-dataset *extreme*, 1.4 ms at 200.

**Correction (don't trust my earlier "Rust ≈ libyaml" claim):** measured against `py-yaml12`
(Rust/`saphyr`, see §3b), a Rust YAML parser is **~4.5× faster than libyaml** (13.8 ms vs 61.5 ms
at 2000 datasets), not libyaml-class. So Rust *does* have a real parse edge.

- **mypyc verdict: not worth it.** It touches only the 19% regex glue, can't speed the C parse,
  and reintroduces platform wheels — strictly dominated.
- **Rust parse speed is real — but available as a dependency.** `py-yaml12` already packages
  `saphyr` via PyO3. A **pure-Python** deepyaml could depend on it for ~14 ms 1.2 parsing + do
  the ~15 ms interpolation glue in Python → ~30 ms at 2000 datasets (~120× OmegaConf), **without
  writing any Rust**. So "want Rust-fast parsing" no longer implies "build deepyaml in Rust."
- **Rust verdict (engineering only): still weak, but less one-sided than I claimed.** Building
  deepyaml itself in Rust buys (a) fusing parse+merge+resolve in one native pass, (b) owning the
  `saphyr` integration instead of depending on a v0.1.0 binding, (c) a WASM build you control.
  Real, but each has a cheaper alternative (depend on py-yaml12; accept the beta dep; pure-Python
  WASM fallback).

## 2. Cold start (median ms over bare interpreter, subprocess)

| import | +ms over bare |
|---|---:|
| `import yaml` (PyYAML) | +10.7 |
| `import antlr4` | +8.8 |
| `import omegaconf` | +46.9 |
| `from kedro.config import OmegaConfigLoader` | +71.6 |

OmegaConf adds ~47 ms cold-start. antlr4's *import* is only ~9 ms of that — the dominant antlr4
cost is **parsing at resolve time** (section 1), not import. A PyYAML-only pure-Python loader
saves ~36 ms; a Rust loader (no PyYAML either) saves maybe ~43 ms — a ~7 ms edge over pure-Python.

## 3. WASM / Pyodide

`micropip.install("omegaconf")` **fails** in Pyodide:

```
ValueError: Can't find a pure Python 3 wheel for 'antlr4-python3-runtime==4.9.*'.
```

- `antlr4-python3-runtime` (latest) and `PyYAML` both install fine in Pyodide.
- The blocker: OmegaConf 2.3.1 **pins `antlr4-python3-runtime==4.9.*`**, and **4.9.3 ships an
  sdist only — no wheel** — which `micropip` cannot build in the browser.
- So the user's instinct ("dropping antlr4 unblocks WASM") is **correct in outcome**, but the
  mechanism is the *version pin to a wheel-less release*, not antlr4 being WASM-incompatible.
  (OmegaConf's PR #1114 vendoring would remove this external pin — but it isn't in 2.3.1.)
- A **pure-Python** loader (PyYAML + hand-written resolver) installs in Pyodide trivially.
  A **Rust/PyO3** loader would need an emscripten-built wheel published for Pyodide — extra
  toolchain work, i.e. Rust makes WASM *harder*, not easier.

## 3b. YAML spec compatibility (drop-in fidelity)

libyaml and PyYAML are both **YAML 1.1** (not 1.2). Verified that **OmegaConf is also YAML 1.1**:
it coerces scalars identically to `CSafeLoader` — `yes/no/on/off`→bool (Norway problem), `017`→15
(octal), `12:30`→750 (sexagesimal). So using libyaml gives **exact OmegaConf scalar-typing
parity for free**. A YAML *1.2* parser would *diverge* (e.g. `no`→`"no"` string), silently
breaking existing Kedro configs.

Implication for Rust: the Rust YAML ecosystem is split on spec (`serde_yaml`≈1.1 vs
`yaml-rust2`/`saphyr`→1.2), so a Rust port must deliberately pick/configure a 1.1-faithful parser
or it breaks compat. Pure-Python avoids this by sharing OmegaConf's exact parser.

**YAML 1.2 as a deliberate improvement (not just parity).** A modern replacement *can* offer
YAML 1.2 even though OmegaConf doesn't — the reason to *default* to 1.1 is migration parity
(`flag: on` means `True` in existing configs; 1.2 retypes it to `"on"`), not mimicking OmegaConf.
Library options (parser-layer, orthogonal to Rust-vs-Python):

| option | semantics | parse (2000 ds) | role |
|---|---|---:|---|
| libyaml `CSafeLoader` | 1.1, exact OmegaConf parity | 62 ms (1.0×) | migration default |
| libyaml + drop `yes/no/on/off` bool resolver | 1.1 but Norway-fixed | ~62 ms | cheap "lite-modern" toggle |
| **ruamel.yaml** (typ=safe + clib) | 1.2 (or 1.1 via `version=(1,1)`) | 129 ms (2.1×) | mature opt-in 1.2 |
| **py-yaml12** (Rust/`saphyr`, PyO3) | 1.2 only, full test-suite compliance | **14 ms (0.2×)** | fast 1.2, but v0.1.0 beta + compiled |

`ruamel.yaml` is the mature, dual-mode Python YAML 1.2 lib (1.2 default, 1.1 via `version=(1,1)`).
**`py-yaml12`** (Posit, Dec 2025, v0.1.0) is a Rust/`saphyr` PyO3 parser — ~4.5× *faster* than
libyaml and correct 1.2, but 1.2-only (no 1.1/Norway-parity mode), beta, and a compiled dep.
No Kedro precedent found for adopting either / moving config to 1.2. Recommended: libyaml 1.1
default for migration parity; offer an opt-in 1.2 backend (ruamel for maturity, or py-yaml12 for
speed once it matures).

## 3c. Config formats (scope)

OmegaConfigLoader's `_is_valid_config_path` accepts only `.yml`, `.yaml`, `.json` (verified in
source). **TOML/INI are not Kedro config formats** — Kedro uses TOML only for `pyproject.toml`.
TOML is also a poor fit for deeply-nested catalogs and non-idiomatic for `${...}`. So:
- **Ship YAML + JSON** (parity; JSON is near-free via stdlib).
- Make the parse layer pluggable (`text → value tree`); interpolation runs on the *tree*, so it's
  **format-agnostic for free** — adding TOML later (`tomllib`) is a few lines, do it on demand.
- config-rs's multi-format support is not a reason to adopt it (formats = commoditized cheap part;
  still no interpolation). Cross-format *value lookups* (e.g. read `pyproject.toml`) are better as
  a resolver (`${file:...}`) than as a catalog format.

## 4. Verdict against the gate

| Goal | Captured by pure-Python? | Does Rust add meaningfully? |
|---|---|---|
| Drop antlr4 / 40–50× faster | ✅ yes (drop antlr4 + use libyaml) | no — parse is libyaml-bound; only ~80 ms glue left |
| WASM usability | ✅ yes (trivially) | ❌ harder (needs emscripten wheels) |
| Cold start | ✅ ~36 ms saved | +~7 ms more — marginal |

mypyc was also considered: it can only speed the ~80 ms Python glue (not the libyaml-bound
parse) and reintroduces compiled wheels — not worth it. See §1b.

**On pure engineering merit, Rust is not justified** — a small pure-Python loader captures
essentially all of the performance and WASM wins, ships as a normal wheel, and stays
maintainable by Kedro's (Python) maintainers.

**The one valid reason left for Rust is the explicit goal of learning to build Rust-backed
Python packages.** That's a legitimate driver on its own — it just shouldn't be sold as a
performance or WASM necessity, and a WASM target would require Pyodide/emscripten wheel builds.

## 5. The implemented prototype (`deepyaml`) — measured

The pure-Python library now exists (`src/deepyaml`). End-to-end via its Kedro adapter
(`DeepYAMLConfigLoader`), apples-to-apples with `OmegaConfigLoader` over the same config trees —
both load `catalog` + `parameters`, including globals loading, env layering, and duplicate checks:

| size (datasets) | OmegaConfigLoader | **DeepYAMLConfigLoader** | speedup |
|---|---:|---:|---:|
| light  (20, no interp) |   10.4 ms |  **0.78 ms** | 13.3× |
| small  (20, interp)    |   41.9 ms |  **1.52 ms** | 27.6× |
| medium (200, interp)   |  360.8 ms | **10.9 ms** | 33.0× |
| large  (2000, interp)  | 3574.6 ms | **105 ms** | 33.9× |

(Lower than the bare `baseline_py` 40–50× because the real loader does more real work — globals,
adapter, two pattern groups. Still 13–34× end-to-end.) **Verified byte-identical** to
`OmegaConfigLoader` output on the generated interpolation-heavy configs and the spaceflights
starter (`globals`/`catalog`/`parameters`/`credentials`), with a 27-test suite incl. an
equivalence check. Reproduce: `PYTHONPATH=../src uv run --no-project --with kedro --with pyyaml
python bench_omegaconf.py`.
