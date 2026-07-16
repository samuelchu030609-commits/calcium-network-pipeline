#!/usr/bin/env python
"""Build-time model baking (runs inside the `cascade` conda env).

Downloads the CASCADE pretrained models the pipeline actually selects, into
~/Cascade/Pretrained_models, so the shipped image never needs internet on the
user's first run ("deterministic, offline first run").

Which models: run_cascade routes GC8s (SRS9 / jGCaMP8s) and GC8f (SRS10 /
jGCaMP8f) with target_smoothing_ms=50, which resolves to the two names below
regardless of the recording's acquisition rate (CASCADE resamples the data to
the model's native rate internally). If you add an indicator/family, add its
model here so it too is baked in.

~53 MB total — Cellpose `cpsam` is deliberately NOT baked: detection (stage 1)
runs on the user's own machine, outside this container.
"""
import os, sys

MODELS = [
    "GC8s_EXC_45Hz_smoothing50ms",    # SRS9 / jGCaMP8s
    "GC8f_EXC_100Hz_smoothing10ms",   # SRS10 / jGCaMP8f
]

CASCADE_DIR = os.path.expanduser("~/Cascade")
os.chdir(CASCADE_DIR)                 # download_model writes to ./Pretrained_models
sys.path.insert(0, CASCADE_DIR)
from cascade2p import cascade

for m in MODELS:
    dest = os.path.join("Pretrained_models", m)
    if os.path.isdir(dest):
        print(f"[bake] already present: {m}")
        continue
    print(f"[bake] downloading {m} ...")
    cascade.download_model(m, verbose=1)
    if not os.path.isdir(dest):
        sys.exit(f"[bake] FAILED to obtain {m} — aborting build")
    print(f"[bake] ok: {m}")

print("[bake] all models present:", ", ".join(MODELS))
