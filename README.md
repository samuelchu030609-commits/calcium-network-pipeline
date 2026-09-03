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

### Indicators / constructs

Lentiviral construct names follow the lab's Lentivirus transduction record:

| Name | Construct | Modality | Pipeline route |
|---|---|---|---|
| **SRS9** | `hSyn-jGCaMP8s` | Calcium (GECI, slower) | `cascade_gc8s` |
| **SRS10** | `hSyn-jGCaMP8f` | Calcium (GECI, fast) | `cascade_gc8f` |
| **SRS11** | `hSyn-ASAP4e-kV` | **Voltage** sensor | *not supported* — different modality |
| Fluo-4 AM | synthetic dye | Calcium (dye) | `dff` (legacy, retired) |

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

For a whole plate, [`tools/batch_suite2p.py`](tools/batch_suite2p.py) runs stage 1 over
every TIF in a folder with those detection settings already applied, reading each
recording's true frame rate from its own TIF timestamps. It leaves exactly the
`<recording>/suite2p/plane0/` layout the GUI's batch queue scans for, so the two halves
meet in the middle. Run it in your Suite2p environment — `--dry-run` first, always:

```bash
python tools/batch_suite2p.py "/path/to/folder-of-tifs" --dry-run
python tools/batch_suite2p.py "/path/to/folder-of-tifs"
```

It is resumable (finished recordings are skipped) and `--delete-bin` reclaims Suite2p's
~630 MB-per-recording `data.bin` as it goes.

---

## Point-and-click GUI (easiest)

Prefer not to touch the command line? A small local app in [`gui/`](gui/) drives
stages 2–3 for you — pick the recording folder, choose the indicator from a
dropdown (no editing `config.json`), and run; it shows the friendly *Key Numbers*
and the `.xlsx`. It also has a **batch** mode (queue many recordings) and a
**compare** mode (pool workbooks into a WT-vs-KCNT1 group comparison). Launch with
`./gui/run_gui.sh` (macOS/Linux) or `gui\run_gui.bat` (Windows). See
[`gui/README.md`](gui/README.md).

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
*(The image bundles both conda envs and the CASCADE models, so the first run needs no internet — see Status.)*

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

> The Docker image bakes the GC8s + GC8f models in at build time, so a containerized
> first run needs no internet. Running **outside** the container on a fresh machine,
> the first run on a new indicator downloads the model from `drive.switch.ch`; on an
> offline analysis machine pre-download it once (e.g. `GC8f_EXC_100Hz_smoothing10ms`).

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

### Group comparison (across recordings)

To compare conditions (e.g. WT vs KCNT1), pool several `*_metrics.xlsx` into one
workbook with `pipeline/run_group.py` — per-group means ± SD and a two-group
contrast (with an exploratory Mann-Whitney p at n ≥ 3/group). It reads only the
finished workbooks' machine-readable `Summary` sheet and warns if event sources
are mixed (CASCADE spikes vs dF/F0 aren't comparable). You assign the groups.

```bash
python -m pipeline.run_group --scan /path/to/session --out group_comparison.xlsx
# or explicit: python -m pipeline.run_group A.xlsx:WT B.xlsx:WT C.xlsx:KCNT1
```
Also available as the **Compare recordings** tab in the [GUI](gui/README.md).

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

The analysis code is **vendored from the parent project** into `pipeline/` and runs
end-to-end: `run_pipeline.py` drives `run_cascade.py` → `run_metrics.py` using the
shared `pipeline_fixes.py` helpers, reproducing the parent project's authoritative
numbers on a real recording (verified on the SS9 jGCaMP8s D83 set). When the parent
CASCADE/metrics code changes, re-sync the three volatile files without touching their
fixed signatures — see the sync boundary in [`docs/DEV.md`](docs/DEV.md).

The Docker image bakes the CASCADE `Pretrained_models` (GC8s + GC8f) in at build time
for an offline first run. Cellpose `cpsam` is deliberately **not** baked: ROI detection
(stage 1) runs in the user's own Suite2p GUI, not in this container, so the image never
loads it. The canonical detection settings ship instead as
[`settings/pipeline_settings.npy`](settings) — load them in the Suite2p GUI, and
`run_pipeline.py` warns loudly if a recording's detection settings drift from them.

An end-to-end acceptance test ships under [`examples/`](examples): `bash
examples/acceptance_test.sh` generates a small synthetic recording with known planted
structure, runs the full pipeline, and asserts the structure is recovered — verifying an
install/container without real data.

The one remaining nicety before a tagged release: a Suite2p detection-panel screenshot
in `docs/SUITE2P_SETTINGS.md` (a GUI capture from your own session; `.gitignore` already
permits `docs/**/*.png`).
