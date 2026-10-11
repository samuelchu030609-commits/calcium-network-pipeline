# The GUI

A small point-and-click front-end that runs in your web browser, entirely on your own
computer. It has four modes:

- **From microscope files** — all three stages, starting from a folder of `.tif`
  movies: Suite2p → cell rule → CASCADE → metrics. Cells are outlined with a chosen
  **detection profile** (built-in, or the lab's own, made and previewed on one recording
  in the same page; see "Your cells: a detection profile" in
  [HOW_TO_INSTALL.md](../HOW_TO_INSTALL.md)), and the outlines at least the profile's
  smallest-cell size across (8 µm by default) are counted as cells, not Suite2p's
  classifier's choice. It runs `tools/analyze_folder.py` in the
  background, so closing the browser does not stop it, and it collects every workbook
  in `<folder>/RESULTS/`. This mode needs the one-click install
  ([HOW_TO_INSTALL.md](../HOW_TO_INSTALL.md)) and must be opened from its
  **iNeuron-NetSync** Desktop launcher.
- **One Suite2p recording** / **Batch of Suite2p recordings** — stages 2–3 only, for
  folders that already contain Suite2p output (described below).
- **Compare recordings** — pools finished workbooks into a group comparison.

For the two Suite2p modes, run stage 1 (Suite2p segmentation) yourself first, exactly
as the [technical README](../docs/TECHNICAL_README.md) and
[docs/SUITE2P_SETTINGS.md](../docs/SUITE2P_SETTINGS.md) describe:

```
  YOU (stage 1)                    THIS GUI (stages 2–3)
  Suite2p GUI  ──▶ suite2p/plane0/  ──▶  CASCADE ──▶ metrics ──▶ *_metrics.xlsx
```

## The Suite2p modes: what they do

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

## The modes in more detail

At the top, switch between the modes.

- **One Suite2p recording** — the one-at-a-time flow described above. The frame-rate
  field has a **📷 Read from raw file** button that reads the *true* rate from the
  raw movie's own timestamps (Suite2p's stored `fs` is unreliable). It works on
  MetaSeries/MetaMorph TIFs today; for ND2 it tells you to install the `nd2`
  package. It only fills the suggestion — you still see and confirm the number.
- **Batch of Suite2p recordings** — process several recordings back-to-back. Build the queue two
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
- **Compare recordings** — pool several finished `*_metrics.xlsx` into one
  **group-comparison** workbook (e.g. WT vs KCNT1). Scan a folder for workbooks
  (or add them one at a time), give each a **group label** (you assign these —
  genotype isn't read from the files), and **Build comparison**. The output has a
  per-recording table, per-group means ± SD, and — for a two-group design — a
  contrast with an exploratory Mann-Whitney p (computed only at n ≥ 3 per group).
  It warns if you mix event sources (CASCADE vs dF/F0), which aren't comparable.
  Also available on the command line: `python -m pipeline.run_group --scan PARENT`.

## First-time setup

*With the one-click install ([HOW_TO_INSTALL.md](../HOW_TO_INSTALL.md)) skip this section
and the next two: the installer builds everything and the Desktop launcher starts the GUI
already knowing where each environment is.*

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
