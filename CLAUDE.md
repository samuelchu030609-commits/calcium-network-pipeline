# iNeuron-NetSync — repo guide

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
- `tools/batch_suite2p.py` (stage 1) and `tools/apply_cell_rule.py` (stage 1b), both
  mirrored from the parent — keep them **byte-identical** to the lab copies (`cmp` them);
  `tests/test_stage1b.py` is identical in both repos too. `tools/compare_plate.py` = the lab's
  version (quadrant pooling `<well>_s1..s4` → one whole-well value, `--min-active 5` for
  synchrony/burst/team rows) + accepting `<rec>_metrics.xlsx` names; on plates 2354 and 09-28
  it writes the same comparison workbook as the lab tool (0 differing rows, 2026-10-10).
- **Stage 1b — cells by size** (adopted in the parent 2026-10-10): every Suite2p ROI with
  equivalent diameter ≥ the profile's `min_cell_diameter_um` (default 8) is a cell; Suite2p's
  classifier is ignored (always on, at chance on iNeurons, skew-lookup off-by-one). Pixel size
  from the TIF (MetaMorph `spatial-calibration-x`), else the profile's `um_per_px` fallback
  (analyze_folder retries with it only on a missing-calibration error), else a hard failure —
  never guessed. Writes `iscell_suite2p.npy` (backup), `cell_rule.json`; moves now-stale
  CASCADE output to `_stale_pre_cell_rule/`. analyze_folder runs it per recording after
  stage 1 and redoes stages 2–3 when `cell_rule.json` is newer than the workbook. The
  Suite2p-output GUI modes do NOT apply it (they take the user's `iscell.npy` as given).
- **Dark final frames**: batch_suite2p drops ≤5 trailing frames after an abrupt drop
  (`find_dark_tail`), via a trimmed scratch copy; record in `plane0/frame_trim.json`.
- **Detection profiles** (`tools/detection_profiles.py`): built-in JSON in
  `settings/detection_profiles/` (default "Lippmann iNeurons, 10X" = 12 **px**, kept in px on
  purpose: 16.4 µm → 12.009 px, which would count as a different setting and force re-runs;
  "Lippmann iNeurons, 20X" = 24 px at 0.685 µm/px — never pool 10X with 20X);
  user profiles in `<install>/profiles/` (outside the code, so updates keep them). A profile →
  batch_suite2p `--diameter|--diameter-um --cellprob-threshold --flow-threshold --img`.
  batch_suite2p treats a finished recording as done only if its ops.npy detection matches
  (else REDO + removes stale cascade/metrics files), writes `plane0/detection_settings.json`;
  analyze_folder refuses stages 2–3 on mismatched detection and passes `detection_expected`
  to the run_pipeline guard; run_group warns on mixed detection. Defaults reproduce the old
  settings dict exactly (verified) and all lab plates dry-run as done.
- `tools/preview_detection.py` (suite2p env): Suite2p's own `anatomical.select_rois` on a
  meanImg/max_proj built like `detection_wrapper` (no registration, first N frames). On B05 its
  images match Suite2p's (r = 1.0 mean, 0.994 max_proj).
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
- No GPU needed. `envs/cascade.yml` is pinned — **TF 2.15 requires numpy<2** (load-bearing).
- **Cellpose (inside Suite2p detection) uses a GPU whenever `cellpose.core.use_gpu()` says one
  works**, ignoring Suite2p's `torch_device`: MPS on Apple Silicon; never on the Windows install
  (CPU torch). B05 1024²: MPS 434 vs CPU 435 cells, 99.1% pixel overlap; CPU ~40 min vs MPS
  1–2 min. GitHub's macOS runner has a broken virtual MPS (0 cells), so the workflow patches
  `cellpose.core._use_gpu_torch` there only. Measured Mac throughput: 64 × 3-min recordings
  in 5 h 51 min (M2 Pro). Keep HOW_TO_INSTALL.md's timing table in line with these.
- `settings/pipeline_settings.npy` is the canonical Suite2p detection config (Cellpose, `img='meanImg'`,
  diameter 12) — the ONLY guard that users' stage-1 detection matches ours. Keep it shipped.

## Routing
CASCADE is **GECI-only**: jGCaMP8s→`GC8s`, jGCaMP8f→`GC8f` (family must match the indicator; the
generic `Global` under-calls). Fluo-4 (dye) → dF/F0, no CASCADE. See `config.example.json` + `docs/`.
