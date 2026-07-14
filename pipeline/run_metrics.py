"""Stage 3: event detection + network/synchrony metrics -> *_metrics.xlsx.

⚠ SYNC BOUNDARY — this file tracks the analysis being rewritten in the parent
project ("event_analysis_template.ipynb"). It is a STUB. Fill in from the
FINALIZED version. See docs/DEV.md.

The real analysis is the notebook, driven by its first cell:
    suite2p_folder = Path(".")        # the plane0 folder
    output_prefix  = "RUNID_metrics"  # names the workbook -> RUNID_metrics.xlsx
It uses cascade_spike_prob.npy if present (reading the TRUE rate from
cascade_meta.json), else falls back to dF/F0 peak detection. Port it to a script
or drive the notebook with papermill using those two parameters.

Contract the orchestrator depends on (keep this signature stable):

    run_metrics(plane0_dir, config) -> str

  - plane0_dir : plane0 to read (contains cascade_spike_prob.npy + cascade_meta.json
                 for cascade routes)
  - config     : RecordingConfig (pipeline.config) — indicator, route, fps,
                 neuropil_coeff
  - returns    : path to the written <prefix>_metrics.xlsx

Output sheets:
  - per-cell : event rate, % active, STTC_to_population
  - network  : STTC_excess_over_chance (+ z, p), coactive fraction,
               FDR connectivity, guarded assembly detection
"""
from __future__ import annotations
import argparse


def run_metrics(plane0_dir: str, config) -> str:
    """Compute metrics; return path to the written xlsx.

    TODO: port from the finalized event_analysis_template.ipynb — as a script, or
    by driving the template with papermill. Must run non-interactively.
    Uses helpers from pipeline.pipeline_fixes (baseline dF/F, FDR connectivity,
    STTC excess-over-chance, assembly guard).
    """
    raise NotImplementedError("port from finalized event_analysis_template.ipynb")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plane0_dir")
    args = ap.parse_args()
    # standalone use: load config from the recording folder (plane0/../..)
    import os
    from .config import load_config
    rec_dir = os.path.dirname(os.path.dirname(plane0_dir := args.plane0_dir))
    print(run_metrics(plane0_dir, load_config(rec_dir)))


if __name__ == "__main__":
    main()
