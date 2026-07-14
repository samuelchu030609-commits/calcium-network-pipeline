"""Stage 2: CASCADE spike inference on a Suite2p plane0 folder (GCaMP only).

⚠ SYNC BOUNDARY — this file tracks the finalized CASCADE code in the parent
project ("Summer Research/run_cascade.py"). It is a STUB; port that file here.
See docs/DEV.md.

The real run_cascade.py CLI (match this when porting):
    python run_cascade.py <plane0> [--fps HZ] [--family {Global,GC8s,GC8f,GC8m}]
                                   [--indicator {EXC,INH}] [--no-resample]
  - --fps       : recording rate (defaults to ops['fs'])
  - --family    : GC8s for jGCaMP8s (SRS9), GC8f for jGCaMP8f (SRS10)
  - --indicator : EXC (default) | INH
  - --no-resample : leave OFF; resampling to the model rate is the correct default

Behavior: computes dF/F from F/Fneu, picks a clean model for (family, fps),
**auto-resamples dF/F to the model's training rate** (GC8s→45 Hz, GC8f→100 Hz;
never downsample the fast GC8f), runs inference. No sibling folder is created.

Contract the orchestrator depends on (keep this signature stable):

    run_cascade(plane0_dir, family, fps) -> str

  - returns : plane0_dir (outputs are written INTO it).

Writes into plane0_dir:
  - cascade_spike_prob.npy : (n_cells × n_frames) float32, rows = F[iscell] order;
                             first/last frames are NaN (edge frames, handled downstream)
  - cascade_meta.json      : provenance incl. the TRUE spike-prob rate the notebook reads
"""
from __future__ import annotations
import argparse


def run_cascade(plane0_dir: str, family: str, fps: float, indicator: str = "EXC") -> str:
    """Run CASCADE; write outputs into plane0_dir; return plane0_dir.

    TODO: port from the finalized parent-project run_cascade.py.
    """
    raise NotImplementedError("port from finalized parent-project run_cascade.py")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plane0_dir")
    ap.add_argument("--family", required=True, help="GC8s | GC8f | Global | GC8m")
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--indicator", default="EXC", choices=["EXC", "INH"])
    args = ap.parse_args()
    print(run_cascade(args.plane0_dir, args.family, args.fps, args.indicator))


if __name__ == "__main__":
    main()
