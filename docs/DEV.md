# Developer notes (filling in the scaffold)

## Sync boundary (important)

The scientific code (CASCADE + metrics) is being revised in the parent project.
To avoid porting a mid-revision version, the repo separates two layers:

| Layer | Files | Status |
|-------|-------|--------|
| **Repo-native (stable)** | `config.py`, `run_pipeline.py` | Implemented. Only *call* the stage functions, so unaffected by internal rewrites. |
| **Tracks parent project (volatile)** | `run_cascade.py`, `run_metrics.py`, `pipeline_fixes.py` | Stubs. Fill in from the **finalized** parent code, not a mid-revision copy. Signatures are already fixed by the orchestrator's contract — match them. |

Rule: when the parent CASCADE/metrics work stabilizes, drop it into the three
volatile stubs **without changing the fixed signatures** documented at the top of
each stub. `run_pipeline.py` and `config.py` should not need edits.

## Fill-in order

This repo is currently a **scaffold**. The volatile `pipeline/` scripts are stubs.
Order to fill them in:

1. **`pipeline/config.py`** — load `config.json`, validate, expose `indicator`,
   `native_fps`, `route`, `neuropil_coeff`. Small; do first.
2. **`pipeline/run_cascade.py`** — port from the working `run_cascade.py` in the
   parent project. Changes needed: remove the hardcoded `DEFAULT_FOLDER`; take the
   plane0 path as a required arg; pull `--family` (GC8s/GC8f/Global) and downsample
   target from `config.py` / route instead of manual flags.
3. **`pipeline/run_metrics.py`** — port from `event_analysis_template.ipynb`.
   Convert the notebook into a callable script (or drive the template with
   papermill). Inputs: plane0 path + config; output: `<id>_metrics.xlsx`. Must run
   non-interactively.
4. **`pipeline/pipeline_fixes.py`** — copy verbatim from the parent project (shared
   helpers: `rolling_baseline_dff`, `fdr_connectivity`, assembly guard, STTC
   excess-over-chance).
5. **`pipeline/run_pipeline.py`** — orchestrator / container entrypoint. Detects
   route from config; for CASCADE routes runs cascade then metrics, for `dff` runs
   metrics only. Activates the correct conda env per stage.

## Env split

Two conda envs inside the image (Suite2p is NOT here — users run it themselves):
- `cascade.yml` — CASCADE + its TF/torch (CPU) deps.
- `analysis.yml` — pandas / scipy / openpyxl for the metrics step.

Keep them separate (dependency conflicts). `run_pipeline.py` calls each stage with
that env's Python.

## Models

Bake into the image at build time so first run needs no internet and results are
deterministic: CASCADE `Pretrained_models` and Cellpose `cpsam`. Do NOT commit
them to git (see `.gitignore`).

## Publishing

Build → tag → push to GHCR:
```
docker build -f docker/Dockerfile -t ghcr.io/samuelchu030609-commits/calcium-network-pipeline:vX.Y .
docker push ghcr.io/samuelchu030609-commits/calcium-network-pipeline:vX.Y
```
Tag a matching GitHub release so the image version and the code version line up.
