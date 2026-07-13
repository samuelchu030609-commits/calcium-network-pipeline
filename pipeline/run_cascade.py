"""Stage 2: CASCADE spike inference on a Suite2p plane0 folder.

⚠ SYNC BOUNDARY — this file tracks the CASCADE code being rewritten in the parent
project ("Summer Research/run_cascade.py"). It is a STUB. Fill in from the
FINALIZED version, not a mid-revision one. See docs/DEV.md.

Contract the orchestrator depends on (keep this signature stable):

    run_cascade(plane0_dir, family, native_fps, target_hz) -> str

  - family     : "GC8s" | "GC8f"   (CASCADE model family from the route)
  - native_fps : true frame rate of the recording
  - target_hz  : downsample target for the CASCADE model (e.g. 45), or None
  - returns    : path to the plane0 folder that stage 3 should read
                 (the downsampled sibling folder if downsampling happened,
                  else plane0_dir). cascade_spike_prob.npy is written there.
"""
from __future__ import annotations
import argparse


def run_cascade(plane0_dir: str, family: str, native_fps: float, target_hz=None) -> str:
    """Run CASCADE (with optional downsample); return the plane0 dir for stage 3.

    TODO: port from the finalized parent-project run_cascade.py. Steps:
      - if target_hz and native_fps != target_hz: resample F/Fneu/spks into a
        sibling suite2p_<target>Hz/plane0 (copy iscell/stat, set ops fs/nframes)
      - select CASCADE model by (family, effective fps) and run it
      - write cascade_spike_prob.npy into that folder; return the folder path
    """
    raise NotImplementedError("port from finalized parent-project run_cascade.py")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plane0_dir")
    ap.add_argument("--family", required=True, help="GC8s | GC8f")
    ap.add_argument("--native-fps", type=float, required=True)
    ap.add_argument("--target-hz", type=float, default=None)
    args = ap.parse_args()
    print(run_cascade(args.plane0_dir, args.family, args.native_fps, args.target_hz))


if __name__ == "__main__":
    main()
