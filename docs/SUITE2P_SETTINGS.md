# Running Suite2p to match this pipeline

You run Suite2p yourself, once per recording, to turn your TIFs into a
`suite2p/plane0/` folder. This pipeline then takes that folder.

The detection settings below are **not** Suite2p's defaults — they are the
choices this project standardized on. If you use the defaults you will get
different cells (Suite2p's default activity-based detection misses quiet/silent
neurons), and your results won't be comparable to everyone else's.

> **Fastest, least error-prone option:** in the Suite2p GUI, load
> [`../settings/pipeline_settings.npy`](../settings/pipeline_settings.npy) instead
> of setting these by hand. Then only adjust `fs` and `tau` for your recording
> (see below). The table is here so you understand *what* you're loading.

> **Different cells or magnification?** The table below is the built-in detection
> profile *Lippmann iNeurons, 10X* (12-pixel cells at 1.37 µm/pixel). The built-in
> *Lippmann iNeurons, 20X* profile is the same with a diameter of 24 px (0.685 µm/pixel,
> 20X water objective). For other cells,
> make a detection profile in the GUI (cell size, cell-probability and shape thresholds,
> detection image) and check it with the preview: see "Your cells: a detection profile"
> in [HOW_TO_INSTALL.md](../HOW_TO_INSTALL.md). The pipeline then compares each
> recording against the profile chosen for it rather than against this table.

## 1. Install Suite2p

Follow the official Suite2p installation instructions (their GitHub project).
Any recent version with Cellpose (`cpsam`) detection support works. The
Cellpose model downloads automatically on first run.

## 2. Detection settings — copy these EXACTLY (same for every recording)

| Setting                 | Value       | Why                                            |
|-------------------------|-------------|------------------------------------------------|
| Detection algorithm     | `cellpose`  | Anatomical detection, not default `sparsery`   |
| Cellpose model          | `cpsam`     | Cellpose-SAM (~1.2 GB, auto-downloads)         |
| Image for detection     | `meanImg`   | Pure anatomy → includes silent cells           |
| Diameter                | `12` px     | Target single somata, not colonies             |
| `flow_threshold`        | `0.4`       |                                                |
| `cellprob_threshold`    | `0.0`       |                                                |
| `cellpose_chan2`        | off / False | Single channel                                 |

Rationale: activity-based detection under-counts quiet KOLF neurons; lowering its
threshold adds false positives that aren't shape-separable. Anatomical detection
on the mean image finds cells by shape regardless of activity, giving an unbiased
denominator for "% of cells active."

## 2b. Which ROIs are cells: by size, not by Suite2p's classifier

After Suite2p, the pipeline's **stage 1b** (`tools/apply_cell_rule.py`) decides which
ROIs are cells: every ROI whose equivalent diameter (a circle of the same area) is at
least **8 µm** is a cell, and nothing else. The pixel size comes from the TIF
(MetaMorph `spatial-calibration-x`) and is never guessed. Suite2p's own labels are kept
in `iscell_suite2p.npy`; the rule and its counts are recorded in `cell_rule.json`.

Why not Suite2p's classifier: it cannot be switched off (`use_builtin_classifier=False`
only chooses which classifier file loads), on iPSC-derived neurons it is no better than
chance at separating confirmed cells from other ROIs, and an off-by-one in its skew
lookup roughly doubles the ROIs it keeps in recordings that end on a dark, truncated
frame. The 8 µm floor kept 99.6% of confirmed cells; 10 µm starts to discard real ones.

The main mode applies this automatically. If you run Suite2p yourself, run
`python tools/apply_cell_rule.py <recording>/suite2p/plane0` (in the `suite2p`
environment) before stages 2–3; `--um-per-px` gives the pixel size for TIFs that do
not store it, `--revert` restores Suite2p's labels.

**Dark final frames.** When acquisition stops mid-exposure, the last 1–3 frames are
partly dark, and every trace ends in a deep dip. `tools/batch_suite2p.py` drops such
frames (at most 5, and only after an abrupt drop, so slow bleaching is never cut) and
records what it dropped in `plane0/frame_trim.json`. The raw TIF is never changed.

## 3. Set these per YOUR recording — you decide, based on your data

Two settings you set yourself, because they depend on your recording, not on our
standardized choices:

**`fs` — the true frame rate.** Read it from the TIF per-frame timestamps. Do NOT
trust the value the Suite2p GUI pre-fills; it is whatever was typed at acquisition
and is often wrong.

**`tau` — the calcium decay timescale of your indicator.** This is a property of
the sensor you used, so set it to match your indicator. Detection bins the movie by
`round(tau*fs)`, so a wrong `tau` starves detection on short clips — pick the value
for your sensor rather than leaving the Suite2p default (1.0, a GCaMP6s value).

| Indicator                | Recommended `tau` | Note                                   |
|--------------------------|-------------------|----------------------------------------|
| Fluo-4 AM (dye)          | `0.25`            |                                        |
| jGCaMP8s (SRS9)          | `0.25`            | fast decay; what this project used     |
| jGCaMP8f (SRS10)         | `≤0.25`           | faster than 8s — use a smaller value   |
| GCaMP6s / slower sensors | `~1.0–1.5`        | Suite2p's default 1.0 is for this class |
| other                    | your sensor's decay time constant | look it up for your indicator |

These are starting defaults, not law — if you know your indicator's decay constant
or have measured it, use that.

## 4. Run

Set the data path to your TIF folder, Run. When it finishes you'll have a
`suite2p/plane0/` folder. Point this pipeline at the folder that contains
`suite2p/` (see the [technical README](TECHNICAL_README.md)).

## 5. Sanity check before moving on

- Open the ROIs over the mean image — you should see compact round somata, not
  giant blobs (colonies) or speckle.
- Cell count should be in the expected range for your field (hundreds, not
  single digits or thousands).

## 6. Load these settings automatically

Rather than entering the fields above by hand, load the canonical settings file
directly in the Suite2p GUI (File → Load ops/settings):

    settings/pipeline_settings.npy

This is a real Suite2p settings dict captured from the reference run (recording
2169), so it reproduces the exact detection/extraction parameters this pipeline
was validated against. **After loading, override only `fs` and `tau` for your
own recording** — those two are per-recording; everything else
(Cellpose/meanImg/diameter/flow/cellprob/max_overlap/neuropil) is the shared,
copy-exactly part. The orchestrator (`run_pipeline.py`) reads your recording's
`ops.npy` and warns loudly if these detection settings drifted from the
canonical set, so a mismatch can't silently make your numbers non-comparable.

*(A GUI screenshot of the detection panel with these fields circled would live at
`docs/img/suite2p_detection.png` — add one from your own Suite2p session; the
`.gitignore` already permits `docs/**/*.png`.)*
