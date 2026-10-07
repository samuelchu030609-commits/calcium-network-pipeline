"""Orchestrator / container entrypoint: route a recording through stages 2–3.

Repo-native glue. It only *calls* the stage functions, so it's stable even while
run_cascade / run_metrics internals are being rewritten (see docs/DEV.md).

Given a data folder containing suite2p/plane0/ and config.json:
  - cascade_gc8s / cascade_gc8f : (downsample ->) run_cascade -> run_metrics
  - dff (Fluo-4)                : run_metrics only (no CASCADE model)

Inside the container each stage runs in its own conda env; this process runs in
the `analysis` env and shells out to the `cascade` env for stage 2 (see the calls
marked below). For a first single-env fill-in you can import and call directly.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys

from .config import load_config, ConfigError


def _run_cascade_stage(plane0: str, family: str, fps: float) -> None:
    """Stage 2 (CASCADE), env-aware.

    Two deployment modes, both exercised:
      * Local / single-env: CASCADE (TensorFlow) lives in the SAME interpreter as
        this orchestrator, so import and call directly. This is the path verified
        against the parent project's authoritative numbers.
      * Container / two-env: TensorFlow is only in the `cascade` conda env, while
        this process runs in the `analysis` env. Set PIPELINE_CASCADE_ENV=cascade
        (the Dockerfile does) and we shell out with `conda run -n <env>` so stage 2
        runs where TF actually is. Without this, a direct import would ImportError
        inside the container.
    """
    cascade_py = os.environ.get("PIPELINE_CASCADE_PYTHON")
    cascade_env = os.environ.get("PIPELINE_CASCADE_ENV")
    if cascade_py:
        # The one-click install (install/) knows the cascade env's interpreter by
        # path, so no `conda` needs to be on PATH (it usually isn't on Windows).
        cmd = [cascade_py, "-m", "pipeline.run_cascade", plane0,
               "--family", str(family), "--fps", str(fps)]
        print(f"[pipeline] stage 2: running CASCADE with {cascade_py}")
        subprocess.run(cmd, check=True)
    elif cascade_env:
        cmd = ["conda", "run", "--no-capture-output", "-n", cascade_env,
               "python", "-m", "pipeline.run_cascade", plane0,
               "--family", str(family), "--fps", str(fps)]
        print(f"[pipeline] stage 2: shelling out to conda env {cascade_env!r}")
        subprocess.run(cmd, check=True)
    else:
        from .run_cascade import run_cascade
        run_cascade(plane0, family=family, fps=fps)


_CANON_SETTINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "settings", "pipeline_settings.npy")

# Detection (stage 1 / Suite2p) runs on the USER'S machine, outside this pipeline.
# If their Cellpose/detection settings differ from the canonical ones, their ROI
# set — and therefore every downstream number — is not comparable to the reference
# runs, and nothing else in the pipeline would reveal it. So on every run we read
# the incoming ops.npy detection block and warn loudly on any deviation. This is a
# WARNING, never fatal: a user may legitimately re-tune detection — but they must
# do so knowingly. fs/tau are per-recording and deliberately not compared.
_DETECTION_KEYS = ("cellpose_model", "img", "flow_threshold", "cellprob_threshold",
                   "diameter", "max_overlap", "threshold_scaling", "neuropil_coefficient")


def _extract_detection(ops: dict) -> dict:
    import numpy as np
    d = ops.get("detection") if isinstance(ops.get("detection"), dict) else {}
    e = ops.get("extraction") if isinstance(ops.get("extraction"), dict) else {}
    cs = d.get("cellpose_settings") if isinstance(d.get("cellpose_settings"), dict) else {}
    diam = ops.get("diameter")
    if diam is not None and np.ndim(diam):
        diam = tuple(float(x) for x in diam)
    return {"cellpose_model": cs.get("cellpose_model"), "img": cs.get("img"),
            "flow_threshold": cs.get("flow_threshold"),
            "cellprob_threshold": cs.get("cellprob_threshold"), "diameter": diam,
            "max_overlap": d.get("max_overlap"),
            "threshold_scaling": d.get("threshold_scaling"),
            "neuropil_coefficient": e.get("neuropil_coefficient")}


def _settings_equal(a, b, tol: float = 1e-6) -> bool:
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_settings_equal(x, y, tol) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def check_detection_settings(plane0: str) -> None:
    """Warn loudly if the recording's Suite2p detection settings differ from canonical."""
    import numpy as np
    if not os.path.exists(_CANON_SETTINGS):
        return  # canonical file not shipped in this checkout — skip silently
    ops_path = os.path.join(plane0, "ops.npy")
    if not os.path.exists(ops_path):
        return
    try:
        canon = _extract_detection(np.load(_CANON_SETTINGS, allow_pickle=True).item())
        cur = _extract_detection(np.load(ops_path, allow_pickle=True).item())
    except Exception as exc:  # never let the guard break a run
        print(f"[pipeline] note: could not compare detection settings ({exc})")
        return
    diffs = {k: (canon[k], cur[k]) for k in _DETECTION_KEYS
             if not _settings_equal(canon[k], cur[k])}
    if not diffs:
        print("[pipeline] detection settings match canonical (settings/pipeline_settings.npy)")
        return
    bar = "!" * 78
    print(bar)
    print("[pipeline] WARNING: Suite2p DETECTION settings differ from the canonical set.")
    print("           ROI segmentation happened on your machine, NOT in this pipeline.")
    print("           Differing detection settings change which cells are found, so your")
    print("           numbers may NOT be comparable to the reference runs. Deviations:")
    for k, (want, got) in diffs.items():
        print(f"             {k}: canonical={want!r}  yours={got!r}")
    print("           Canonical values: docs/SUITE2P_SETTINGS.md / settings/pipeline_settings.npy")
    print(bar)


def find_plane0(data_dir: str) -> str:
    p = os.path.join(data_dir, "suite2p", "plane0")
    if not os.path.isdir(p):
        sys.exit(
            f"No suite2p/plane0 found in {data_dir}.\n"
            f"Point me at the folder that CONTAINS suite2p/ (see README / examples)."
        )
    return p


def run(data_dir: str) -> str:
    """Process one recording; return the path to the written *_metrics.xlsx."""
    plane0 = find_plane0(data_dir)
    try:
        cfg = load_config(data_dir)
    except ConfigError as e:
        sys.exit(str(e))

    print(f"[pipeline] {data_dir}")
    print(f"[pipeline] indicator={cfg.indicator}  fps={cfg.native_fps}  route={cfg.route}")
    check_detection_settings(plane0)

    if cfg.uses_cascade:
        # --- stage 2: CASCADE (auto-resamples to the model rate internally) ---
        # Writes cascade_spike_prob.npy + cascade_meta.json INTO plane0 (no sibling
        # folder). Env-aware: direct import locally, `conda run -n cascade` in the
        # container (set PIPELINE_CASCADE_ENV). See _run_cascade_stage.
        _run_cascade_stage(plane0, cfg.cascade_family, cfg.native_fps)
    else:
        print("[pipeline] dff route: skipping CASCADE (GCaMP-only; dye uses dF/F0)")

    # --- stage 3: event + network metrics -> xlsx ---
    # Reads cascade_spike_prob.npy from plane0 if present (rate from cascade_meta.json),
    # else falls back to dF/F0 peak detection.
    from .run_metrics import run_metrics
    xlsx = run_metrics(plane0, cfg)
    print(f"[pipeline] wrote {xlsx}")
    return xlsx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data_dir", help="folder containing suite2p/ and config.json")
    args = ap.parse_args()
    run(args.data_dir)


if __name__ == "__main__":
    main()
