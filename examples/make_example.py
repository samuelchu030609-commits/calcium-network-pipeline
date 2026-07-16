#!/usr/bin/env python
"""Generate a tiny SYNTHETIC recording for the end-to-end acceptance test.

This is NOT real data — it's a deterministic (fixed-seed) toy with a known
structure so the pipeline's output is predictable and checkable:

  * 15 ROIs, 450 frames @ 45 Hz (jGCaMP8s route; 45 Hz == the GC8s model's
    native rate, so CASCADE does not resample — keeps the test fast/exact).
  * A synchronous "network" subset of 8 cells that co-fire at planted times,
    plus 7 quieter cells. So the pipeline should find a clearly non-zero,
    above-chance STTC and a couple of network bursts — if it finds nothing,
    or finds structure in a pure-noise control, something is broken.
  * ops.npy carries the CANONICAL detection settings, so the detection-settings
    guard reports a match (exercising that path too).

Writes a ready-to-run recording folder: <out>/{config.json, suite2p/plane0/*}.
Run the pipeline on it with:  ./run.sh examples/_synthetic   (or acceptance_test.sh)
"""
import argparse, json, os
import numpy as np

FS = 45.0
N_FRAMES = 450
N_CELLS = 15
NET = list(range(8))          # cells 0-7 are the synchronous assembly
SEED = 0

# canonical detection settings (mirror settings/pipeline_settings.npy) so the
# guard reports a match on the synthetic recording
_DETECTION = {
    "algorithm": "cellpose", "max_overlap": 0.75, "threshold_scaling": 1.0,
    "cellpose_settings": {"cellpose_model": "cpsam", "img": "meanImg",
                          "flow_threshold": 0.4, "cellprob_threshold": 0.0},
}
_EXTRACTION = {"neuropil_coefficient": 0.7, "neuropil_extract": True}


def _transient(n, t0, amp, tau_s):
    """Single exponential-decay calcium transient onto an n-length trace."""
    tr = np.zeros(n)
    t = np.arange(n) - t0
    m = t >= 0
    tr[m] = amp * np.exp(-t[m] / (tau_s * FS))
    return tr


def build():
    rng = np.random.default_rng(SEED)
    baseline = 1000.0
    F = np.full((N_CELLS, N_FRAMES), baseline) + rng.normal(0, 15, (N_CELLS, N_FRAMES))
    # planted synchronous events for the assembly (same frames, all 8 cells)
    event_frames = [60, 150, 240, 330, 410]
    for f in event_frames:
        for c in NET:
            F[c] += _transient(N_FRAMES, f + rng.integers(0, 3), rng.uniform(300, 500), 0.3)
    # a few sparse independent events in the quieter cells
    for c in range(8, N_CELLS):
        for _ in range(rng.integers(1, 3)):
            f = rng.integers(20, N_FRAMES - 20)
            F[c] += _transient(N_FRAMES, f, rng.uniform(200, 350), 0.3)
    Fneu = np.full((N_CELLS, N_FRAMES), baseline * 0.8) + rng.normal(0, 10, (N_CELLS, N_FRAMES))
    iscell = np.column_stack([np.ones(N_CELLS), np.ones(N_CELLS)])   # all real
    stat = np.array([{"med": [rng.integers(0, 512), rng.integers(0, 512)],
                      "npix": 80} for _ in range(N_CELLS)], dtype=object)
    ops = {"fs": FS, "tau": 0.25, "nframes": N_FRAMES, "nplanes": 1, "nchannels": 1,
           "diameter": [12.0, 12.0], "detection": _DETECTION, "extraction": _EXTRACTION,
           "meanImg": np.zeros((512, 512), dtype=np.float32)}
    return F.astype(np.float32), Fneu.astype(np.float32), iscell, stat, ops


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", nargs="?", default=os.path.join(os.path.dirname(__file__), "_synthetic"),
                    help="output recording folder (default: examples/_synthetic)")
    args = ap.parse_args()
    plane0 = os.path.join(args.out, "suite2p", "plane0")
    os.makedirs(plane0, exist_ok=True)
    F, Fneu, iscell, stat, ops = build()
    np.save(os.path.join(plane0, "F.npy"), F)
    np.save(os.path.join(plane0, "Fneu.npy"), Fneu)
    # spks.npy: Suite2p's own deconvolution. The pipeline uses CASCADE/dF-F, not
    # this, but real plane0 folders always contain it and loaders expect the file.
    np.save(os.path.join(plane0, "spks.npy"), np.zeros_like(F))
    np.save(os.path.join(plane0, "iscell.npy"), iscell)
    np.save(os.path.join(plane0, "stat.npy"), stat)
    np.save(os.path.join(plane0, "ops.npy"), ops)
    json.dump({"_comment": "SYNTHETIC acceptance-test recording — not real data",
               "indicator": "jGCaMP8s (SRS9)", "native_fps": FS,
               "route": "cascade_gc8s", "neuropil_coeff": 0.7},
              open(os.path.join(args.out, "config.json"), "w"), indent=2)
    print(f"wrote synthetic recording -> {args.out}")
    print(f"  {N_CELLS} cells, {N_FRAMES} frames @ {FS} Hz; assembly = cells {NET[0]}-{NET[-1]}")


if __name__ == "__main__":
    main()
