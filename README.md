# Calcium Network Pipeline

Turn a Suite2p output folder into a per-cell + network-level metrics workbook
(`*_metrics.xlsx`) for calcium-imaging recordings of iNeurons.

It runs **CASCADE** spike inference and an event/synchrony analysis (dF/F events,
STTC synchrony, FDR-controlled connectivity) and writes one Excel workbook per
recording.

---

## How the pipeline is split

There are three stages. **You run Suite2p yourself; this tool does the rest.**

```
  YOUR MACHINE (once, per recording)          THIS TOOL (Docker, one command)
  ┌───────────────────────────────┐          ┌──────────────────────────────┐
  │ 1. Suite2p                     │          │ 2. CASCADE spike inference    │
  │    TIFs ──▶ suite2p/plane0/    │  ──────▶ │ 3. Event + network metrics    │
  │    (GUI, our documented        │  plane0  │    plane0 ──▶ *_metrics.xlsx  │
  │     detection settings)        │          │                              │
  └───────────────────────────────┘          └──────────────────────────────┘
```

- **Stage 1 (Suite2p)** is *not* bundled here. Install Suite2p from its official
  project and run it with our exact detection settings — see
  [`docs/SUITE2P_SETTINGS.md`](docs/SUITE2P_SETTINGS.md). This produces a
  `suite2p/plane0/` folder.
- **Stages 2–3** run inside a CPU-only Docker container, so there is nothing to
  install beyond Docker itself. You point it at your `plane0` folder and it
  writes the Excel workbook back into that folder.

Why Suite2p is separate: it's a large, well-documented tool with its own
installer, and running it is interactive (you check the ROIs). Bundling it would
duplicate their install and complicate the container for no gain.

---

## Quickstart (end users)

**1. Install Docker Desktop** (one time). See [`docs/INSTALL.md`](docs/INSTALL.md).

**2. Run Suite2p on your TIFs** with our settings
([`docs/SUITE2P_SETTINGS.md`](docs/SUITE2P_SETTINGS.md)). You'll get a
`suite2p/plane0/` folder next to your data.

**3. Create a `config.json`** in that folder describing the recording (copy
[`config.example.json`](config.example.json) and edit the indicator / frame rate).

**4. Run the pipeline** — point it at the folder that contains `suite2p/`:

- **macOS / Linux:** `./run.sh /path/to/recording`
- **Windows:** double-click `run.bat`, or `run.bat C:\path\to\recording`

Output: `..._metrics.xlsx` appears inside `suite2p/plane0/`.

*(Advanced users can skip the wrapper: `docker run --rm -v "<folder>:/data" ghcr.io/samuelchu030609-commits/calcium-network-pipeline /data`.)*

---

## Repository layout

```
calcium-network-pipeline/
├── README.md                 ← you are here
├── run.sh / run.bat          ← end-user wrappers around `docker run`
├── config.example.json       ← per-recording indicator / frame-rate template
├── docs/
│   ├── INSTALL.md            ← install Docker (Windows + Mac)
│   ├── SUITE2P_SETTINGS.md   ← how to run Suite2p to match our detection
│   └── TROUBLESHOOTING.md
├── settings/
│   └── pipeline_settings.npy ← load-this-instead backup of the Suite2p settings
├── pipeline/                 ← the actual analysis code (stages 2–3)
│   ├── run_pipeline.py       ← container entrypoint: CASCADE → metrics
│   ├── run_cascade.py        ← CASCADE spike inference
│   ├── run_metrics.py        ← event + network metrics → xlsx
│   ├── pipeline_fixes.py     ← shared helpers (baseline, FDR connectivity, …)
│   └── config.py             ← reads config.json, routes by indicator
├── envs/
│   ├── cascade.yml           ← conda env for CASCADE
│   └── analysis.yml          ← conda env for the metrics step
├── docker/
│   ├── Dockerfile            ← CPU-only image, both envs + models baked in
│   └── entrypoint.sh
└── examples/
    └── README.md             ← expected input layout + a tiny sample
```

## What the output contains

Per-recording `*_metrics.xlsx`:
- **Per-cell:** event rate, % active, `STTC_to_population` (how coupled each cell is)
- **Network:** mean STTC synchrony reported as `STTC_excess_over_chance` with
  z-score and p-value, coactive fraction, FDR-controlled connectivity, assembly
  detection (guarded for short clips)

## Status

Scaffold. The `pipeline/` scripts are stubs to be filled in — see the TODOs in
each file and [`docs/DEV.md`](docs/DEV.md).

## License

MIT — see [`LICENSE`](LICENSE).
