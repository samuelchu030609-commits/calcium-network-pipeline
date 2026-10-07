# calcium-network-pipeline — repo guide

Shareable, CPU-only distribution of the calcium pipeline for OTHER LABS (non-programmers).
Main path: the **one-click install** (`INSTALL_WINDOWS.bat` / `INSTALL_MAC.sh` → `install/`)
builds four pinned conda envs (suite2p, cascade, analysis, gui) in a private Miniforge, and
the GUI's "From microscope files" mode runs all three stages over a folder of TIFs via
`tools/analyze_folder.py`. User guide: `HOW_TO_INSTALL.md` (plain language — keep it that
way). Docker (stages 2–3 only) is a secondary path. Public repo. The full *scientific*
context lives in the parent project's `CLAUDE.md`, not here.

## Layout
- `pipeline/run_pipeline.py` — orchestrator / container entrypoint; routes a recording via its `config.json`.
- `pipeline/config.py` — config validation + route→family/target mapping. **Repo-native, stable.**
- `pipeline/{run_cascade,run_metrics,pipeline_fixes}.py` + `event_analysis_template.ipynb` — the
  **scientific code**, VENDORED from the parent project (see sync boundary).
- `tools/analyze_folder.py` — stages 1→2→3 over a folder of TIFs, each in its own env (found
  via `CNP_CONDA_BASE` or `sys.prefix`); copies workbooks to `<folder>/RESULTS/`. Repo-native glue.
- `tools/batch_suite2p.py` (stage 1, mirrored from the parent), `tools/compare_plate.py`.
- `install/` — `install_windows.ps1` (must stay ASCII: PowerShell 5.1), `install_mac.sh`,
  `self_test.py`. Version pins live in BOTH installers AND `self_test.py` EXPECTED — change
  all three together. They equal the parent project's verified envs.
- `docker/` (Dockerfile, `bake_models.py`, `run.sh`/`run.bat`, README — the image is NOT
  published; users must build it), `envs/` (Docker/manual only — NOT used by the
  installers), `settings/pipeline_settings.npy`, `examples/`, `docs/` (`TECHNICAL_README.md`
  = the old long README).

## Sync boundary (important)
The scientific code is maintained in the parent project and MIRRORED here — do not diverge it in
this repo. The orchestrator calls fixed signatures: `run_cascade(plane0, family, fps, ...) -> plane0`
and `run_metrics(plane0, cfg) -> out_path`. Pure-internal rewrites need no glue change; only
input/output **contract** changes touch `config.py` / `run_pipeline.py`. When updating science
code, port the FINALIZED parent version, then re-run the acceptance test.

## Don't break
- `install/self_test.py` must pass on a real install (it also runs the planted-structure test
  and a synthetic TIF through all 3 stages). `.bat` files are stored CRLF (`.gitattributes`).
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
