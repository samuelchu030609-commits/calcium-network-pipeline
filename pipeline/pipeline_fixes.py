"""Shared analysis helpers used by run_cascade and run_metrics.

⚠ SYNC BOUNDARY — this is a copy of pipeline_fixes.py from the parent project.
Do NOT hand-edit here; re-copy the FINALIZED version so the two don't drift.
See docs/DEV.md. Provides (per the parent project's current API):

CASCADE readouts
  - cascade_discrete_spikes(spike_prob, model_name, ...)  primary; wraps CASCADE's
        infer_discrete_spikes — threshold-free, calibrated across indicators/rates
        (seeded, random_seed=0, for reproducibility)
  - cascade_events(spike_prob, fs, ...)                   fast fallback: MAD peak-pick;
        returns floor_binding=True when too sparse to be data-adaptive
  - cascade_spike_rate(spike_prob, fs)                    spikes/s over valid (non-NaN) time
  - load_cascade_output(plane_dir)                        loads .npy + cascade_meta.json

dF/F0 with drift correction
  - rolling_baseline_dff(F, Fneu, fs, ...)  neuropil-corrected sliding-percentile dF/F0;
        auto-detrends photobleaching / auto-shrinks window on short clips
  - exp_detrend_Fc(Fc, fs)                  exponential photobleach removal
  - baseline_qc_plot(...)                   per-cell raw-F-vs-fitted-F0 QC figure

Synchrony / connectivity
  - sttc_matrix / sttc_pair          spike-time tiling coefficient (Cutts & Eglen 2014)
  - fdr_connectivity(...)            per-pair STTC significance with Benjamini-Hochberg FDR
  - benjamini_hochberg(pvals, q)     BH-FDR mask
  - assembly_power_ok(...)           guard: refuse assembly detection when too few time-bins
"""
