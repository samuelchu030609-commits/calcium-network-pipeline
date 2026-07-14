# Calcium Network Pipeline

Quantifies activity and network **synchronization** in human iPSC-derived iNeurons
imaged by widefield GCaMP fluorescence. Built for the KCNT1 epilepsy model
(WT vs KCNT1-mutant KOLF2.1 iNeurons, Lippmann Lab, Vanderbilt), but general to any
Suite2p-segmented GCaMP recording.

It takes a Suite2p output folder and produces one Excel metrics workbook per
recording (ΔF/F₀, event/spike trains, burst & network-burst metrics, co-activity,
STTC synchrony, FDR-controlled functional connectivity, cell assemblies).

**Flow:** microscope movie → **Suite2p** (motion correction + ROI segmentation) →
**CASCADE** (calibrated spike inference) → **metrics notebook** → `*_metrics.xlsx`.

> **CASCADE is used only for GCaMP (genetically-encoded) recordings** — it is trained
> on GECIs and is out-of-distribution for synthetic dyes. Synthetic-dye (Fluo-4)
> recordings are supported through a ΔF/F₀-only legacy path (`route: dff`) but are
> retired going forward.

---

## How the pipeline is split

Three stages. **You run Suite2p yourself; this tool does the rest.**

```
  YOUR MACHINE (once, per recording)          THIS TOOL
  ┌───────────────────────────────┐          ┌──────────────────────────────┐
  │ 1. Suite2p                     │          │ 2. CASCADE spike inference    │
  │    TIFs ──▶ suite2p/plane0/    │  ──────▶ │ 3. Event + network metrics    │
  │    (GUI, our documented        │  plane0  │    plane0 ──▶ *_metrics.xlsx  │
  │     detection settings)        │          │                              │
  └───────────────────────────────┘          └──────────────────────────────┘
```

Stage 1 (Suite2p) is **not** bundled — install it from its official project and run
it with our detection settings ([`docs/SUITE2P_SETTINGS.md`](docs/SUITE2P_SETTINGS.md)).
CASCADE (`cascade2p`, Rupprecht et al. 2021) is third-party too and is installed, not
vendored.

---

## Two ways to run stages 2–3

### A. Docker (for non-coders / Windows) — *image pending*
One command, nothing to install but Docker Desktop:
```
./run.sh /path/to/recording          # macOS / Linux
run.bat  C:\path\to\recording         # Windows
```
It reads a `config.json` in the recording folder (copy
[`config.example.json`](config.example.json)) and writes `*_metrics.xlsx` into
`suite2p/plane0/`. See [`docs/INSTALL.md`](docs/INSTALL.md).
*(The published image is built once the analysis code below is vendored in — see Status.)*

### B. Manual (for developers) — the working path today
Run the two stages directly in their conda envs.

**Stage 2 — CASCADE (GCaMP only):** converts fluorescence to a *calibrated* spike
probability, replacing Suite2p's raw OASIS `spks.npy`.
```bash
# dedicated cascade env (Python 3.10, TensorFlow 2.15, NumPy 1.26)
# --fps is THIS recording's true rate (e.g. 100); CASCADE resamples to the model rate itself
python run_cascade.py "/path/to/suite2p/plane0" --fps 100 --family GC8s
```
Options: `--fps HZ` (defaults to `ops['fs']`), `--family {Global,GC8s,GC8f,GC8m}`,
`--indicator {EXC,INH}` (default EXC), `--no-resample` (leave off).

**Frame-rate / model-rate matching (automatic).** There are two rates, and only one is
fixed. Your **acquisition rate changes every recording** — pass it as `--fps` (read from
the TIF; never assume a value per indicator). CASCADE is only calibrated when the
**model's** training rate matches the data, so `run_cascade.py` picks the clean model for
the family and **resamples your ΔF/F to that model's rate before inference**. You pick the
*family*, not a rate; the target rate is a property of the available CASCADE models:
- **jGCaMP8s (SRS9):** the current clean GC8s model is at **45 Hz**, so 8s recordings —
  whatever they were acquired at — get resampled to 45 Hz for inference.
- **jGCaMP8f (SRS10):** the current clean GC8f model is at **100 Hz**, so 8f recordings get
  matched to 100 Hz. **Never downsample jGCaMP8f toward 45** — it's the fast indicator and
  that would discard the kinetics the model was trained on.

These target rates (45 / 100) are today's model rates, not fixed acquisition rates — if
CASCADE ships new models they change, which is why `run_cascade` selects them at runtime
rather than hardcoding.

Outputs, written into the plane0 folder (no sibling folder):
- `cascade_spike_prob.npy` — `(n_cells × n_frames)` float32, rows in `F[iscell]` order;
  first/last frames are `NaN` (trace edges, handled downstream).
- `cascade_meta.json` — provenance incl. the **true** spike-probability rate the
  notebook reads (so it never assumes the wrong rate after resampling).

> First run on a new indicator downloads the model from `drive.switch.ch`. On an
> offline analysis machine, pre-download it once (e.g. `GC8f_EXC_100Hz_smoothing10ms`).

**Stage 3 — metrics notebook.** Open `event_analysis_template.ipynb`, set two things
in cell 1, run all cells:
```python
suite2p_folder = Path(".")          # the plane0 folder
output_prefix  = "RUNID_metrics"    # names the output workbook
```
If `cascade_spike_prob.npy` is present it's used automatically (rate from
`cascade_meta.json`); otherwise it falls back to ΔF/F₀ peak detection. It exports one
combined workbook `RUNID_metrics.xlsx` (friendly "Key Numbers" sheets + technical sheets).

---

## Output metrics

Per-recording `*_metrics.xlsx`:
- **Per-cell:** event/spike rate, % active, `STTC_to_population` (how coupled each cell is).
- **Network:** STTC synchrony reported as **z-score vs a circular-shift null** (not raw
  mean STTC), Pearson (secondary), population coupling, cell assemblies (power-guarded),
  per-pair functional connectivity (Benjamini–Hochberg FDR), network bursts.

Analysis helpers live in `pipeline/pipeline_fixes.py` — CASCADE readouts (discrete
spikes / MAD events / continuous rate), drift-corrected ΔF/F₀, STTC, and FDR
connectivity. See the docstring there for the full function list.

---

## Repository layout

```
calcium-network-pipeline/
├── README.md                 ← you are here
├── LICENSE                   ← MIT
├── run.sh / run.bat          ← end-user Docker wrappers
├── config.example.json       ← per-recording indicator / frame-rate / route template
├── docs/
│   ├── INSTALL.md            ← install Docker (Windows + Mac)
│   ├── SUITE2P_SETTINGS.md   ← how to run Suite2p to match our detection
│   ├── TROUBLESHOOTING.md
│   └── DEV.md                ← sync boundary + how to fill in the code
├── settings/pipeline_settings.npy  ← load-this-instead backup of Suite2p settings
├── pipeline/                 ← analysis code (stages 2–3)
│   ├── run_pipeline.py       ← orchestrator: CASCADE → metrics, routed by config
│   ├── run_cascade.py        ← CASCADE spike inference (GCaMP only)
│   ├── run_metrics.py        ← event + network metrics → xlsx
│   ├── pipeline_fixes.py     ← shared helpers (baseline, STTC, FDR, CASCADE readouts)
│   └── config.py             ← reads/validates config.json, routes by indicator
├── envs/{cascade,analysis}.yml
└── docker/{Dockerfile,entrypoint.sh}
```

## Requirements

- **Suite2p** — segmentation, run separately (stage 1).
- **CASCADE** (`cascade2p`) + its `Pretrained_models` at `~/Cascade`. Dedicated conda
  env: Python 3.10, TensorFlow 2.15, NumPy 1.26.
- **Metrics notebook:** numpy, scipy, pandas, matplotlib, scikit-learn, openpyxl, and
  `pipeline_fixes.py` on the path.

(The Docker image bundles both envs so end users need none of this.)

## Scientific-methods notes

- **CASCADE only for GCaMP** — not Fluo-4 or other synthetic dyes.
- **Prefer the discrete-spike method** over any fixed spike-probability threshold; a hard
  cutoff isn't comparable across recordings (spike-prob amplitude scales with SNR / rate).
- **Report the STTC z-score, not raw mean STTC,** when comparing conditions.
- **No per-pair connectivity claims on short, sparse recordings without FDR control** —
  the connectivity graph uses Benjamini–Hochberg and the assembly step is power-guarded.
- **Recording length matters** — very short clips leave many cells underpowered for
  pairwise statistics.

## References
- Rupprecht et al. (2021) *Nat. Neurosci.* — CASCADE calibrated spike inference.
- Cutts & Eglen (2014) *J. Neurosci.* — spike-time tiling coefficient (STTC).
- Okun et al. (2015) *Nature* — population coupling.
- Benjamini & Hochberg (1995) — false-discovery-rate control.

## Status

The analysis code is **finalized in the parent project** and being vendored into
`pipeline/` — those files are currently stubs whose signatures match the real scripts
(sync boundary in [`docs/DEV.md`](docs/DEV.md)). Once vendored (with machine-specific
paths made portable), the Docker image is built and published to GHCR.
