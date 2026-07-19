# Stages 2–3 GUI

A small point-and-click front-end for the two stages this pipeline owns —
**CASCADE spike inference** and **network/synchrony metrics**. It saves you from
editing `config.json` by hand and from running the pipeline on the command line.

It does **not** run Suite2p. Do stage 1 (Suite2p segmentation) yourself first,
exactly as the top-level [README](../README.md) and
[docs/SUITE2P_SETTINGS.md](../docs/SUITE2P_SETTINGS.md) describe. This GUI then
takes that Suite2p output folder and finishes the job.

```
  YOU (stage 1)                    THIS GUI (stages 2–3)
  Suite2p GUI  ──▶ suite2p/plane0/  ──▶  CASCADE ──▶ metrics ──▶ *_metrics.xlsx
```

## What it does

1. **Pick the recording folder** — the folder that contains `suite2p/`.
2. **Describe the recording** — choose the indicator from a dropdown (the
   technical *route* like `cascade_gc8s` is filled in for you) and enter the
   acquisition frame rate.
3. **Run** — it writes `config.json` into the folder, runs
   `pipeline/run_pipeline.py`, and streams the log live.
4. **Results** — shows the friendly *Key Numbers* and offers the `.xlsx` to
   download. The workbook lands in `…/suite2p/plane0/<recording>_metrics.xlsx`.

Everything runs **locally**. No files are uploaded anywhere — the GUI reads your
data straight from disk, which is why it works on large recordings and on a
shared lab machine.

## Two modes

At the top, switch between **Single recording** and **Batch queue**.

- **Single recording** — the one-at-a-time flow described above.
- **Batch queue** — process several recordings back-to-back. Build the queue two
  ways:
  - **Scan a parent folder** — point it at a folder (e.g. a day's imaging session)
    and it finds every recording (any `suite2p/plane0`) beneath it and adds them
    all. The indicator is auto-guessed from each folder name (e.g. `…SS9…` →
    jGCaMP8s, `…Fluo4…` → dye) and the frame rate is pre-read from each `ops.npy`.
  - **Add one folder** — queue a single recording at a time.

  Each row lets you fix the indicator and rate before running. **Run all** then
  processes them one after another, showing a live log per recording and a
  summary (`N/N succeeded`) with a download button for each `*_metrics.xlsx`.
  Recordings run sequentially, so a shared lab machine isn't overloaded.

## First-time setup

The GUI needs `streamlit`. The pipeline itself still runs in the conda envs the
main README sets up (`analysis` + `cascade`, or the Docker image). Two options:

**A. Dedicated GUI env (recommended — keeps the analysis env untouched):**
```bash
conda env create -f envs/gui.yml
```

**B. Or install streamlit into any env you already have:**
```bash
pip install streamlit pandas openpyxl
```

## Launch

```bash
# macOS / Linux
./gui/run_gui.sh

# Windows — double-click, or:
gui\run_gui.bat
```

A browser tab opens at `http://localhost:8501`. The launcher uses the `gui`
conda env if it exists, otherwise the first Python on your PATH that has
streamlit.

## Telling it how to run the pipeline (once)

Open **“⚙️ How to run the pipeline”** at the top and pick a mode:

| Mode | When to use | You provide |
|---|---|---|
| **conda** | You followed the manual install (two conda envs) | analysis env + cascade env |
| **docker** | You use the bundled image | the image name (default is prefilled) |
| **direct** | One Python has everything, incl. TensorFlow | the interpreter path |

Your choice is remembered in `gui/settings.local.json` (git-ignored), so you set
it once. Under the hood every mode calls the exact same
`pipeline/run_pipeline.py` the command line uses — the GUI is only a front door.
