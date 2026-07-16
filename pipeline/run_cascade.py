"""Stage 2: CASCADE spike inference on a Suite2p plane0 folder (GCaMP only).

CASCADE (Rupprecht et al., Nat. Neurosci. 2021) replaces Suite2p's raw OASIS
`spks.npy` with a calibrated spike-probability estimate. It wants dF/F traces,
so this stage computes them the standard way from F.npy / Fneu.npy (via
pipeline_fixes.rolling_baseline_dff, so run_cascade and run_metrics share ONE
baseline definition).

The pretrained model is chosen AUTOMATICALLY from the frame rate: nearest
available Hz for the family, then the smoothing closest to target. It is
downloaded on demand into ~/Cascade/Pretrained_models. Changing rate is just
passing a different fps.

  GC8s (jGCaMP8s, SRS9): clean model exists at 45 Hz.
  GC8f (jGCaMP8f, SRS10): clean model exists only at 100 Hz; acquire at 100 Hz.
If the data rate differs from the model rate, the dF/F is resampled to the model
rate before inference (never downsample the fast GC8f), and cascade_meta.json
records the TRUE output rate the metrics stage must read.

Run with the dedicated cascade env, either as a module (preferred inside the
container) or directly:
    conda run -n cascade python -m pipeline.run_cascade <plane0> --family GC8s --fps 45
    python -m pipeline.run_cascade <plane0> --family GC8s --fps 45   # if run from the cascade env

Contract the orchestrator depends on (keep this signature stable):

    run_cascade(plane0_dir, family, fps, indicator="EXC") -> str

  - family  : GC8s (jGCaMP8s/SRS9) or GC8f (jGCaMP8f/SRS10); also Global/GC8m if needed.
  - fps     : the recording's TRUE acquisition rate (from config.native_fps).
  - returns : plane0_dir (outputs are written INTO it).

Writes into plane0_dir:
  - cascade_spike_prob.npy : (n_cells × n_frames) float32, rows = F[iscell] order;
                             first/last frames are NaN (edge frames, handled downstream)
  - cascade_meta.json      : provenance incl. the TRUE spike-prob rate the notebook reads
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import numpy as np

CASCADE_DIR = os.path.expanduser("~/Cascade")           # where Pretrained_models lives
MODELS_YAML = os.path.join(CASCADE_DIR, "Pretrained_models", "available_models.yaml")


def _parse(name):
    hz = re.search(r"_([0-9.]+)Hz", name)
    sm = re.search(r"smoothing([0-9]+)ms", name)
    return (float(hz.group(1)) if hz else None,
            int(sm.group(1)) if sm else None)


def select_model(fps, indicator="EXC", family="Global", target_smoothing_ms=200,
                 allow_causal=False, allow_high_noise=False):
    """Nearest available model by frame rate, then smoothing closest to target."""
    import ruamel.yaml
    names = list(ruamel.yaml.YAML(typ="safe").load(open(MODELS_YAML)).keys())
    cands = []
    for m in names:
        if not m.startswith(f"{family}_{indicator}_"):
            continue
        if ("causalkernel" in m) and not allow_causal:
            continue
        if ("high_noise" in m) and not allow_high_noise:
            continue
        if "asymmetric" in m:
            continue
        hz, sm = _parse(m)
        if hz is None or sm is None:
            continue
        cands.append((m, hz, sm))
    if not cands:
        raise ValueError(f"No {family}_{indicator} models found in {MODELS_YAML}")
    nearest_hz = min({c[1] for c in cands}, key=lambda h: abs(h - fps))
    best = min([c for c in cands if c[1] == nearest_hz],
               key=lambda c: abs(c[2] - target_smoothing_ms))
    return best[0], nearest_hz


def run_cascade(plane0_dir: str, family: str, fps: float, indicator: str = "EXC",
                *, smoothing_ms=None, model=None, neuropil_coeff=0.7,
                f0_percentile=8.0, window_sec=None, allow_causal=False,
                no_resample=False) -> str:
    """Run CASCADE on plane0_dir; write outputs INTO it; return plane0_dir.

    Ported verbatim (logic-for-logic) from the finalized parent-project
    run_cascade.py. `family`/`fps` come from the recording's config
    (RecordingConfig.cascade_family / .native_fps). The keyword-only knobs mirror
    the parent CLI flags and keep their parent defaults.
    """
    if family is None:
        raise ValueError("run_cascade needs a CASCADE family (GC8s/GC8f); got None "
                         "(dff route has no CASCADE stage).")

    F = np.load(os.path.join(plane0_dir, "F.npy"))
    Fneu = np.load(os.path.join(plane0_dir, "Fneu.npy"))
    iscell = np.load(os.path.join(plane0_dir, "iscell.npy"))
    mask = iscell[:, 0].astype(bool)

    fps = float(fps)
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError(f"Invalid frame rate: {fps!r}")

    # Family-appropriate default smoothing: GCaMP8 kinetics are fast, so 200 ms (the
    # Global default) over-smooths jGCaMP8s/f. Use 50 ms for the GC8* families.
    if smoothing_ms is None:
        smoothing_ms = 50 if family.startswith("GC8") else 200

    if model:
        model, near_hz = model, _parse(model)[0]
    else:
        # Prefer a CLEAN model. Only fall back to high_noise if no clean model exists
        # for this family (e.g. GC8f has clean models only at 100 Hz), and say so.
        try:
            model, near_hz = select_model(fps, indicator=indicator, family=family,
                                           target_smoothing_ms=smoothing_ms,
                                           allow_causal=allow_causal, allow_high_noise=False)
        except ValueError:
            model, near_hz = select_model(fps, indicator=indicator, family=family,
                                           target_smoothing_ms=smoothing_ms,
                                           allow_causal=allow_causal, allow_high_noise=True)
            print(f"  WARNING: no clean {family} model; using high_noise model {model}.")

    print(f"Folder: {plane0_dir}")
    print(f"fps={fps} | cells={mask.sum()}/{len(mask)} | indicator={indicator} | family={family}")
    print(f"Auto-selected model: {model}  (model rate {near_hz} Hz)")

    # --- RATE-MATCH GUARD -----------------------------------------------------------
    # CASCADE requires the dF/F input at the model's training rate. A mismatch produces
    # calibrated-looking but WRONG spike rates, so resample the dF/F to the model rate
    # and emit output at that rate. SS9 45 Hz -> GC8s 45 Hz matches exactly (no resample).
    rate_mismatch = near_hz is not None and abs(near_hz - fps) > max(0.05 * fps, 0.5)
    if rate_mismatch and not no_resample:
        print(f"  RATE MISMATCH: data {fps} Hz vs model {near_hz} Hz "
              f"-> resampling dF/F to {near_hz} Hz before inference.")
    elif rate_mismatch and no_resample:
        print(f"  WARNING: data {fps} Hz != model {near_hz} Hz and no_resample set; "
              f"CASCADE output will be MISCALIBRATED. Prefer a rate-matched model/acquisition.")

    # dF/F with a ROLLING low-percentile baseline (matches the metrics stage; removes
    # photobleaching drift). Unified via pipeline_fixes.rolling_baseline_dff.
    # window_sec=None auto-sizes to min(30, duration/4) and exp-detrends short clips.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pipeline_fixes as pf
    dff = pf.rolling_baseline_dff(F[mask], Fneu[mask], fs=fps, percentile=f0_percentile,
                                  window_sec=window_sec, step_sec=1.0,
                                  neuropil_coeff=neuropil_coeff)[0]
    dff = np.nan_to_num(dff, nan=0.0).astype(np.float32)

    output_fps = float(fps)
    resampled = False
    if rate_mismatch and not no_resample:
        from fractions import Fraction
        from scipy.signal import resample_poly
        frac = Fraction(near_hz / fps).limit_denominator(1000)
        dff = resample_poly(dff, frac.numerator, frac.denominator, axis=1).astype(np.float32)
        output_fps = float(near_hz)
        resampled = True
        print(f"  resampled dF/F: {F[mask].shape[1]} frames @ {fps} Hz "
              f"-> {dff.shape[1]} frames @ {output_fps} Hz")

    # Resolve OUTPUT paths to ABSOLUTE before chdir(CASCADE_DIR), else the relative
    # folder resolves against CASCADE_DIR and the save fails.
    out = os.path.abspath(os.path.join(plane0_dir, "cascade_spike_prob.npy"))
    meta_out = os.path.abspath(os.path.join(plane0_dir, "cascade_meta.json"))

    sys.path.insert(0, CASCADE_DIR)   # importable regardless of cwd
    os.chdir(CASCADE_DIR)             # so predict()/download find Pretrained_models
    from cascade2p import cascade

    if not os.path.isdir(os.path.join("Pretrained_models", model)):
        print(f"Downloading model {model} ...")
        cascade.download_model(model, verbose=1)

    t0 = time.time()
    spike_prob = cascade.predict(model, dff).astype(np.float32)
    np.save(out, spike_prob)

    # Metadata sidecar: authoritative record of the spike-prob rate, so the metrics
    # stage uses OUTPUT_FPS (not ops['fs']) for time-based work on this file.
    # PROVENANCE: derive `family` from the ACTUAL model name (its first token), not the
    # requested family -- an explicit --model can differ from the family arg. Model names
    # are <FAMILY>_<INDICATOR>_<RATE>Hz_<smoothing>[_high_noise], so split('_')[0] is the
    # family the weights actually came from. family_requested is kept for auditing.
    derived_family = model.split("_")[0]
    meta = {
        "model": model, "model_rate_hz": near_hz, "family": derived_family,
        "family_requested": family, "smoothing_ms": smoothing_ms,
        "indicator": indicator, "input_fps": float(fps), "output_fps": output_fps,
        "resampled": resampled, "n_cells": int(mask.sum()), "n_frames": int(spike_prob.shape[1]),
        "neuropil_coeff": neuropil_coeff, "f0_percentile": f0_percentile,
        "baseline_window_sec": window_sec, "cascade_ref": "Rupprecht et al. 2021 Nat Neurosci",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(meta_out, "w") as fh:
        json.dump(meta, fh, indent=2)

    print(f"Inference done in {time.time()-t0:.0f}s | output {spike_prob.shape} @ {output_fps} Hz")
    print("Saved:", out)
    print("Saved:", meta_out)
    if resampled:
        print(f"  NOTE: spike_prob is at {output_fps} Hz (resampled), NOT the folder's {fps} Hz. "
              f"Downstream must read output_fps from cascade_meta.json.")
    print("spike-prob range %.4f..%.4f  mean %.4f  (NaN edge frames %.1f%%)"
          % (np.nanmin(spike_prob), np.nanmax(spike_prob), np.nanmean(spike_prob),
             100 * np.isnan(spike_prob).mean()))
    return plane0_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="CASCADE spike inference on a Suite2p plane0 folder.")
    ap.add_argument("plane0_dir", help="Suite2p plane0 folder (contains F.npy/Fneu.npy/iscell.npy)")
    ap.add_argument("--family", required=True,
                    help="GC8s (jGCaMP8s/SRS9), GC8f (jGCaMP8f/SRS10), Global, GC8m, ...")
    ap.add_argument("--fps", type=float, required=True,
                    help="Recording rate (Hz). Drives model choice / resampling.")
    ap.add_argument("--indicator", default="EXC", choices=["EXC", "INH"],
                    help="EXC = excitatory (default), INH = interneurons.")
    ap.add_argument("--smoothing-ms", type=int, default=None, dest="smoothing_ms",
                    help="Preferred smoothing (ms); nearest available at the chosen Hz is used. "
                         "Default: 50 for GC8* families, 200 for Global.")
    ap.add_argument("--model", default=None, help="Explicit model name; overrides auto-selection.")
    ap.add_argument("--neuropil", type=float, default=0.7, dest="neuropil_coeff",
                    help="Neuropil coefficient.")
    ap.add_argument("--f0-percentile", type=float, default=8.0, dest="f0_percentile",
                    help="Baseline percentile for dF/F.")
    ap.add_argument("--window-sec", type=float, default=None, dest="window_sec",
                    help="Rolling-baseline window (s). Default None = auto min(30, duration/4).")
    ap.add_argument("--causal", action="store_true", dest="allow_causal",
                    help="Allow causal-kernel models.")
    ap.add_argument("--no-resample", action="store_true", dest="no_resample",
                    help="Do NOT resample dF/F to the model rate on a mismatch (leave OFF).")
    args = ap.parse_args()
    print(run_cascade(args.plane0_dir, args.family, args.fps, args.indicator,
                      smoothing_ms=args.smoothing_ms, model=args.model,
                      neuropil_coeff=args.neuropil_coeff, f0_percentile=args.f0_percentile,
                      window_sec=args.window_sec, allow_causal=args.allow_causal,
                      no_resample=args.no_resample))


if __name__ == "__main__":
    main()
