# calcium-network-pipeline — repo guide

Shareable, CPU-only **Docker distribution of stages 2–3** of the calcium pipeline: CASCADE spike
inference + event/network metrics. Users run **Suite2p themselves** (stage 1, their machine, via
the Suite2p GUI), then this container turns a `suite2p/plane0/` folder into a metrics workbook.
Public repo. The full *scientific* context lives in the parent project's `CLAUDE.md` (`~/Summer
Research/`), not here — this file is for working on the distribution.

## Layout
- `pipeline/run_pipeline.py` — orchestrator / container entrypoint; routes a recording via its `config.json`.
- `pipeline/config.py` — config validation + route→family/target mapping. **Repo-native, stable.**
- `pipeline/{run_cascade,run_metrics,pipeline_fixes}.py` + `event_analysis_template.ipynb` — the
  **scientific code**, VENDORED from the parent project (see sync boundary).
- `docker/` (Dockerfile + `bake_models.py`), `envs/`, `settings/pipeline_settings.npy`, `examples/`, `docs/`.

## Sync boundary (important)
The scientific code is maintained in the parent project and MIRRORED here — do not diverge it in
this repo. The orchestrator calls fixed signatures: `run_cascade(plane0, family, fps, ...) -> plane0`
and `run_metrics(plane0, cfg) -> out_path`. Pure-internal rewrites need no glue change; only
input/output **contract** changes touch `config.py` / `run_pipeline.py`. When updating science
code, port the FINALIZED parent version, then re-run the acceptance test.

## Don't break
- `examples/acceptance_test.sh` MUST pass — planted synthetic structure → active cells, STTC z>3,
  a network burst, provenance stamp, and **no `RUNID` placeholder junk**. Run it after any change.
- Notebook instantiation handles `cell["source"]` as str OR list and HARD-FAILS if the
  `RUNID_metrics` placeholder survives. Keep that guard (a silent no-op once wrote junk files).
- Every run emits `*_metrics.PROVENANCE.txt`; `cascade_meta.json` records the true model + rate
  (family derived from the model name, not the requested flag).
- CPU-only, no GPU. `envs/cascade.yml` is pinned — **TF 2.15 requires numpy<2** (load-bearing).
- `settings/pipeline_settings.npy` is the canonical Suite2p detection config (Cellpose, `img='meanImg'`,
  diameter 12) — the ONLY guard that users' stage-1 detection matches ours. Keep it shipped.

## Routing
CASCADE is **GECI-only**: jGCaMP8s→`GC8s`, jGCaMP8f→`GC8f` (family must match the indicator; the
generic `Global` under-calls). Fluo-4 (dye) → dF/F0, no CASCADE. See `config.example.json` + `docs/`.
