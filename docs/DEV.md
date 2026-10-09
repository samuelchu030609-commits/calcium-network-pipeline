# Developer notes (maintaining the vendored code)

## Sync boundary (important)

The scientific code (CASCADE + metrics) lives in the parent project and is revised
there. To avoid re-syncing a mid-revision version, the repo separates two layers:

| Layer | Files | Status |
|-------|-------|--------|
| **Repo-native (stable)** | `config.py`, `run_pipeline.py` | Implemented. Only *call* the stage functions, so unaffected by internal rewrites. |
| **Tracks parent project (volatile)** | `run_cascade.py`, `run_metrics.py`, `pipeline_fixes.py` | Vendored from the finalized parent code. Re-sync when the parent stabilizes, matching the fixed signatures documented at the top of each file. |

Rule: when the parent CASCADE/metrics work changes, re-vendor the three volatile
files **without changing the fixed signatures** documented at the top of each.
`run_pipeline.py` and `config.py` should not need edits.

## How the vendored files map to the parent project

The `pipeline/` scripts are already vendored and run end-to-end. When you re-sync
after a parent-project change, here is what each file corresponds to and the
portability edits that were applied (keep them applied on every re-sync):

1. **`pipeline/config.py`** — repo-native. Loads `config.json`, validates, exposes
   `indicator`, `native_fps`, `route`, `neuropil_coeff`. No parent equivalent; do not
   overwrite from the parent.
2. **`pipeline/run_cascade.py`** — vendored from the parent `run_cascade.py`. Applied
   edits: hardcoded `DEFAULT_FOLDER` removed; the plane0 path is a required argument;
   `run_cascade(...)` is the callable core and `main()` is a thin CLI wrapper. Family
   (GC8s/GC8f/Global) and resample behaviour still come from the model actually
   selected (family = first token of the model name), NOT from a hardcoded rate.
3. **`pipeline/run_metrics.py`** — repo-native driver that executes the vendored
   `event_analysis_template.ipynb` non-interactively (inputs: plane0 path + config;
   output: `<id>_metrics.xlsx`, or CSV sheets when openpyxl is absent). It handles
   `cell["source"]` as str-or-list, HARD-FAILS if the `RUNID_metrics` placeholder
   survives substitution, forces the Agg matplotlib backend, and stubs
   `IPython.display` (+ `get_ipython`/`version_info`) so the notebook's Jupyter-only
   imports and the baseline-QC plot work headlessly. Re-sync the **notebook**, not this
   driver, when the metrics analysis changes.
4. **`pipeline/pipeline_fixes.py`** — copied verbatim from the parent project (shared
   helpers: `rolling_baseline_dff`, `exp_detrend_Fc`, `sttc_matrix`/`sttc_pair`,
   `fdr_connectivity`, `assembly_power_ok`, `cascade_discrete_spikes`/`cascade_events`/
   `cascade_spike_rate`, `baseline_qc_plot`). Re-copy byte-for-byte; do not edit here.
5. **`pipeline/run_pipeline.py`** — repo-native orchestrator / container entrypoint.
   Detects route from config; for CASCADE routes runs cascade then metrics, for `dff`
   runs metrics only. (For a single-env image it imports and calls the stages directly;
   the per-stage conda-env split is noted below.)

## Env split

Two conda envs inside the image (Suite2p is NOT here — users run it themselves):
- `cascade.yml` — CASCADE + TensorFlow-CPU 2.15 (numpy pinned <2, load-bearing).
- `analysis.yml` — numpy / scipy / pandas / matplotlib / openpyxl (+ jinja2) for the
  metrics step. Assembly detection is pure numpy — no scikit-learn needed.

Keep them separate (dependency conflicts). `run_pipeline.py` calls each stage with
that env's Python.

## Models

Bake into the image at build time so first run needs no internet and results are
deterministic: CASCADE `Pretrained_models` and Cellpose `cpsam`. Do NOT commit
them to git (see `.gitignore`).

## Publishing

Build → tag → push to GHCR:
```
docker build -f docker/Dockerfile -t ghcr.io/samuelchu030609-commits/ineuron-netsync:vX.Y .
docker push ghcr.io/samuelchu030609-commits/ineuron-netsync:vX.Y
```
Tag a matching GitHub release so the image version and the code version line up.
