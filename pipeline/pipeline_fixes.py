"""Shared analysis helpers used by run_cascade and run_metrics.

⚠ SYNC BOUNDARY — this is a copy of pipeline_fixes.py from the parent project,
which is being rewritten. Do NOT hand-edit here; re-copy the FINALIZED version so
the two don't drift. See docs/DEV.md. Provides:
  - rolling_baseline_dff(...)   rolling low-percentile F0 / dF/F (photobleach fix)
  - fdr_connectivity(...)       BH-FDR functional connectivity (replaces 99th pct)
  - assembly guard              PCA-MP+ICA only when T>=50 bins and N/T<=0.2
  - STTC excess-over-chance     effect size alongside p
"""
