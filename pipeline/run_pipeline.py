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
import sys

from .config import load_config, ConfigError


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

    metrics_input = plane0
    if cfg.uses_cascade:
        # --- stage 2: (optional downsample ->) CASCADE ---
        # NOTE: run_cascade internals are being rewritten elsewhere; this call is
        # the stable contract. When it needs the cascade conda env, replace the
        # direct import with:  conda run -n cascade python -m pipeline.run_cascade ...
        from .run_cascade import run_cascade
        metrics_input = run_cascade(
            plane0,
            family=cfg.cascade_family,
            native_fps=cfg.native_fps,
            target_hz=cfg.cascade_target_hz,
        )
    else:
        print("[pipeline] dff route: skipping CASCADE (no model for this indicator)")

    # --- stage 3: event + network metrics -> xlsx ---
    from .run_metrics import run_metrics
    xlsx = run_metrics(metrics_input, cfg)
    print(f"[pipeline] wrote {xlsx}")
    return xlsx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data_dir", help="folder containing suite2p/ and config.json")
    args = ap.parse_args()
    run(args.data_dir)


if __name__ == "__main__":
    main()
