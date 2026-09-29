"""
pipeline_fixes.py — validated additions to the calcium-imaging analysis pipeline.

Re-implemented in the user's own session (the handoff's original file did not transfer)
and checked against the real Suite2p/CASCADE outputs. Pure numpy; no new dependencies.

Contents
--------
rolling_baseline_dff : sliding low-percentile F0 (removes photobleaching drift)  [Fix 1 / item E]
sttc_matrix / sttc_pair : Spike Time Tiling Coefficient (single source of truth)
benjamini_hochberg   : BH-FDR multiple-comparison correction
fdr_connectivity     : per-pair STTC significance + FDR graph (replaces the 99th-pct rule)  [Fix 2]
assembly_power_ok    : guard for PCA-MP+ICA assembly detection (needs T >> N)  [item D]
baseline_qc_plot     : per-cell raw F with rolling F0 drawn under it  [item G]
"""
import numpy as np
import warnings


# ------------------------------------------------------------------ photobleaching detrend
def _fit_slow_trend(Fc, fs, robust=True):
    """Per-cell slow trend  a*exp(-t/tau) + m*t + c  fit with a robust (soft_l1) loss so
    positive Ca2+ transients don't drag the baseline up. Captures fast photobleaching
    (the exp term) AND slow drift or recovery (the linear term). Falls back to the
    per-cell median if the fit fails to converge. Returns (trend, n_failed)."""
    from scipy.optimize import curve_fit
    n_cells, n_frames = Fc.shape
    t = np.arange(n_frames) / fs
    dur = n_frames / fs
    trend = np.empty_like(Fc)
    n_fail = 0

    def model(t, a, tau, m, c):
        return a * np.exp(-t / np.abs(tau)) + m * t + c

    for i in range(n_cells):
        y = Fc[i]
        c0 = np.percentile(y, 20)
        a0 = max(y[:max(3, n_frames // 20)].mean() - c0, 1.0)
        try:
            p, _ = curve_fit(model, t, y, p0=[a0, max(dur / 5, 0.3), 0.0, c0],
                             loss="soft_l1" if robust else "linear",
                             f_scale=np.std(y) + 1e-9, maxfev=4000, method="trf")
            trend[i] = model(t, *p)
        except Exception:
            trend[i] = np.median(y)
            n_fail += 1
    return trend, n_fail


def exp_detrend_Fc(Fc, fs):
    """Flatten photobleaching in a neuropil-corrected trace by subtracting the fitted
    slow trend, preserving each cell's median level so a downstream low-percentile F0
    stays positive. Use this UPSTREAM of rolling_baseline_dff when the bleaching time
    constant is comparable to the recording length (short clips), where a percentile
    window alone cannot separate 'known instrumental decay' from 'resting level'.

    Returns
    -------
    Fc_flat : (n_cells, n_frames)  detrended, median level preserved
    trend   : (n_cells, n_frames)  the removed slow trend (for QC / effective-F0)
    n_fail  : int                  cells that fell back to a flat median
    """
    Fc = np.asarray(Fc, float)
    trend, n_fail = _fit_slow_trend(Fc, fs)
    Fc_flat = Fc - trend + np.median(trend, axis=1, keepdims=True)
    return Fc_flat, trend, n_fail


# ------------------------------------------------------------------ Fix 1 / item E
def rolling_baseline_dff(F, Fneu, fs, percentile=8, window_sec=30.0, step_sec=1.0,
                         neuropil_coeff=0.7, detrend="auto"):
    """Neuropil-corrected dF/F0 with a SLIDING low-percentile baseline, plus an optional
    exponential photobleaching detrend for short recordings.

    F0(t) is the `percentile`-th percentile of the neuropil-corrected trace within a
    moving window of `window_sec`, computed on a `step_sec` grid and interpolated to
    every frame, so dF/F0 amplitudes stay comparable across the recording.

    TWO guards were added after the baseline was found to silently degrade to a single
    GLOBAL percentile on short (~10 s) recordings, leaving the whole photobleaching
    decay inside every trace (inflating shared-signal Pearson / population coupling and
    biasing CASCADE input):

      1. WINDOW GUARD + AUTO-SHRINK. If `window_sec` covers >= 50% of the recording the
         window is not "rolling" - it is global. The effective window is capped at
         `duration/4` (min 1 s) and a RuntimeWarning is emitted. Pass window_sec=None to
         always auto-size to min(30, duration/4).
      2. EXP DETREND. When `detrend` applies, the neuropil-corrected trace is flattened
         with `exp_detrend_Fc` BEFORE the percentile window. This removes fast bleaching
         (tau comparable to the recording) that a percentile window cannot, because the
         window must exceed the event width yet stay shorter than the decay - impossible
         on a short clip. detrend="auto" (default) turns it on for recordings < 120 s.

    Parameters
    ----------
    F, Fneu : (n_cells, n_frames) arrays  (Suite2p convention)
    fs : true acquisition rate in Hz (NOT ops['fs'] unless verified)
    percentile : low percentile taken as resting level (8-10 typical)
    window_sec : moving-window width (s). None -> auto min(30, duration/4). A value that
        covers >=50% of the recording is capped to duration/4 with a warning.
    step_sec : grid spacing at which F0 is evaluated then interpolated
    detrend : "auto" (exp detrend if duration < 120 s), "exp" (always), or "none".

    Returns
    -------
    dff : (n_cells, n_frames)   (Fc_flat - F0_flat)/F0_flat
    F0  : (n_cells, n_frames)   the EFFECTIVE baseline in original Fc units
                                (F0 on the detrended trace, plus the removed trend), so
                                a QC plot of F0 under the raw neuropil-corrected F is valid.
    """
    Fc_raw = np.asarray(F, float) - neuropil_coeff * np.asarray(Fneu, float)
    n_cells, n_frames = Fc_raw.shape
    dur = n_frames / fs

    if detrend == "auto":
        detrend = "exp" if dur < 120 else "none"
    if detrend == "exp":
        Fc, trend, _ = exp_detrend_Fc(Fc_raw, fs)
    else:
        Fc = Fc_raw
        trend = np.zeros_like(Fc_raw)

    if window_sec is None:
        window_sec = min(30.0, dur / 4.0)
    win = max(1, int(round(window_sec * fs)))
    if win >= 0.5 * n_frames:
        eff = min(window_sec, dur / 4.0)
        warnings.warn(
            f"rolling_baseline_dff: window {window_sec:.1f}s covers >=50% of a {dur:.1f}s "
            f"recording -> F0 would be ~global, not rolling. Auto-shrinking to {eff:.1f}s. "
            f"Pass window_sec explicitly (or None) to silence.", RuntimeWarning)
        window_sec = max(eff, 1.0 / fs)
        win = max(1, int(round(window_sec * fs)))

    step = max(1, int(round(step_sec * fs)))
    half = win // 2
    centers = np.arange(0, n_frames, step)
    F0c = np.empty((n_cells, centers.size), float)
    for k, c in enumerate(centers):
        lo, hi = max(0, c - half), min(n_frames, c + half + 1)
        F0c[:, k] = np.percentile(Fc[:, lo:hi], percentile, axis=1)
    xi = np.arange(n_frames)
    F0_flat = np.empty_like(Fc)
    for i in range(n_cells):
        F0_flat[i] = np.interp(xi, centers.astype(float), F0c[i])
    F0_flat = np.where(F0_flat <= 0, np.nan, F0_flat)
    dff = (Fc - F0_flat) / F0_flat
    # effective baseline in ORIGINAL Fc units (add the trend back, minus its median so it
    # sits at the resting level): F_raw - F0_eff == Fc_flat - F0_flat, so QC stays exact.
    F0 = F0_flat + trend - np.median(trend, axis=1, keepdims=True)
    return dff, F0


# ------------------------------------------------------------------ STTC (shared)
def sttc_matrix(frame_lists, nfr, dt):
    """Pairwise STTC matrix (Cutts & Eglen 2014). frame_lists = per-cell event FRAME
    indices; dt = tiling half-window in frames. Diagonal is NaN."""
    m = len(frame_lists)
    S = np.zeros((m, nfr), np.float32); C = np.zeros((m, nfr), np.float32); ne = np.zeros(m)
    for k, fr in enumerate(frame_lists):
        if len(fr) == 0:
            continue
        S[k, fr] = 1.0; ne[k] = len(fr)
        for p in fr:
            C[k, max(0, p - dt):min(nfr, p + dt + 1)] = 1.0
    T = C.mean(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        P = (S @ C.T) / ne[:, None]
    P = np.nan_to_num(P); Ti, Tj = T[:, None], T[None, :]
    t1 = np.where(np.isclose(P * Tj, 1), 1.0, (P - Tj) / (1 - P * Tj))
    t2 = np.where(np.isclose(P.T * Ti, 1), 1.0, (P.T - Ti) / (1 - P.T * Ti))
    M = 0.5 * (t1 + t2); np.fill_diagonal(M, np.nan)
    return M


def sttc_pair(fa, fb, nfr, dt):
    """STTC for a single pair (for validation/testing)."""
    M = sttc_matrix([np.asarray(fa), np.asarray(fb)], nfr, dt)
    return float(M[0, 1])


# ------------------------------------------------------------------ multiple comparisons
def benjamini_hochberg(pvals, q=0.05):
    """Return a boolean mask of hypotheses that survive BH-FDR at level q."""
    p = np.asarray(pvals, float); n = p.size
    if n == 0:
        return np.zeros(0, bool)
    order = np.argsort(p); ranked = p[order]
    thresh = q * np.arange(1, n + 1) / n
    below = ranked <= thresh
    mask = np.zeros(n, bool)
    if below.any():
        kmax = np.max(np.where(below)[0])
        mask = p <= ranked[kmax]
    return mask


# ------------------------------------------------------------------ Fix 2
def fdr_shuffles_needed(n_pairs, q=0.05):
    """Minimum circular-shift surrogate count for a BH-FDR rejection to be ATTAINABLE.

    An empirical p-value from S surrogates is floored at 1/(S+1). BH at level q rejects
    the smallest of m p-values only if p_(1) <= q/m. So unless 1/(S+1) <= q/m, NO pair
    can ever be called significant however strongly it co-fires: the test then reports
    zero edges by construction rather than by evidence.

    S >= m/q - 1 satisfies it, but at exactly that value 1/(S+1) and q/m are the same
    real number and the comparison then rests on float rounding. Returns ceil(m/q), one
    surrogate more, so 1/(S+1) < q/m strictly.
    """
    if not n_pairs or not np.isfinite(n_pairs) or n_pairs < 1:
        return 0
    return int(np.ceil(float(n_pairs) / float(q)))


def fdr_connectivity(event_frames, n_frames, dt_frames, n_shuffles=500, q=0.05, rng=None):
    """Per-pair STTC significance with BH-FDR (replaces the 99th-percentile edge rule).

    event_frames : list of per-ACTIVE-cell event FRAME-index arrays.
    Each pair gets a one-sided empirical p from circular-shift surrogates; BH-FDR at
    level q decides edges. `null_edges_expected` = what the old 1% rule would report.

    Besides the graph this returns the power diagnostics that make a zero edge count
    interpretable: `bh_critical_k1` (= q/m, the p-value a pair must beat to be the first
    rejection), `min_p` (= 1/(S+1), the smallest p these surrogates can produce),
    `n_shuffles_needed`, and `fdr_detectable` / `fdr_status`. When min_p exceeds
    bh_critical_k1 the edge count carries no information -- see fdr_shuffles_needed().
    """
    if rng is None:
        rng = np.random.default_rng(0)
    m = len(event_frames)
    empty = dict(n_edges=0, density=np.nan, mean_degree=np.nan, n_pairs=0,
                 adjacency=np.zeros((m, m), bool), p_values=np.array([]),
                 null_edges_expected=np.nan, min_p=np.nan, n_shuffles=n_shuffles,
                 degree=np.zeros(m, int), bh_critical_k1=np.nan, n_shuffles_needed=0,
                 fdr_detectable=False,
                 fdr_status="not computed (fewer than 2 active cells)")
    if m < 2:
        return empty
    iu = np.triu_indices(m, 1)
    obs = sttc_matrix(event_frames, n_frames, dt_frames)[iu]
    finite = np.isfinite(obs)
    ge = np.zeros(obs.shape)          # count of shuffles with null >= observed
    used = 0
    for _ in range(n_shuffles):
        sh = [np.sort((fr + rng.integers(1, n_frames)) % n_frames) if len(fr) else fr
              for fr in event_frames]
        null = sttc_matrix(sh, n_frames, dt_frames)[iu]
        ge += np.where(np.isfinite(null) & finite, null >= obs, 0.0)
        used += 1
    p = (1.0 + ge) / (used + 1.0)
    p[~finite] = 1.0
    sig = benjamini_hochberg(p, q)
    n_pairs = int(finite.sum())
    adj = np.zeros((m, m), bool)
    adj[iu[0][sig], iu[1][sig]] = True
    adj |= adj.T
    degree = adj.sum(1)
    n_edges = int(sig.sum())
    min_p = 1.0 / (used + 1.0)
    crit = (q / n_pairs) if n_pairs else np.nan
    need = fdr_shuffles_needed(n_pairs, q)
    detectable = bool(n_pairs and min_p <= crit)
    if not n_pairs:
        status = "not computed (no finite pairs)"
    elif detectable:
        status = (f"adequate: min attainable p {min_p:.2e} <= BH k=1 critical value "
                  f"{crit:.2e} ({used} surrogates, {n_pairs} pairs)")
    else:
        status = (f"UNDERPOWERED: min attainable p {min_p:.2e} > BH k=1 critical value "
                  f"{crit:.2e}; no pair can reach significance and n_edges is "
                  f"uninformative. Needs >= {need} surrogates for {n_pairs} pairs.")
    return dict(n_edges=n_edges,
                density=(n_edges / n_pairs) if n_pairs else np.nan,
                mean_degree=float(degree.mean()) if m else np.nan,
                n_pairs=n_pairs, adjacency=adj, p_values=p, degree=degree,
                null_edges_expected=0.01 * n_pairs, min_p=min_p,
                n_shuffles=used, bh_critical_k1=crit, n_shuffles_needed=need,
                fdr_detectable=detectable, fdr_status=status)


# ------------------------------------------------------------------ item D
def sttc_pair_mask(event_counts, min_events):
    """Boolean (m, m) mask: True where BOTH cells of the pair fired >= min_events events.

    WHY GATE. STTC was constructed so its EXPECTATION is not confounded by firing rate
    (Cutts & Eglen 2014) -- but rate-robustness of the expectation is not low sampling
    VARIANCE. The statistic is built from the tiling proportion P = (fraction of one
    cell's events that fall inside the other's +/-dt tiles). With one or two events that
    proportion can only take the values 0, 1/2, 1, so STTC collapses onto near-extreme
    values whatever the true coupling: a single event landing inside a tile returns
    STTC ~ +1, and one landing outside returns a small negative number set by the tiling
    fractions alone. Averaging such pairs in with well-sampled ones does not average out
    -- it adds a large, rate-dependent variance term to the network mean and drags the
    median toward the negative no-overlap value.

    Gating is therefore variance control, not bias correction, and it is not optional
    for a mean over pairs: report the gated mean as the network synchrony estimate and
    the ungated mean alongside it for comparability. Diagonal is False.
    """
    c = np.asarray(event_counts)
    ok = np.isfinite(c) & (c >= float(min_events))
    mask = np.outer(ok, ok)
    np.fill_diagonal(mask, False)
    return mask


def network_burst_intervals(coactive_fraction, peak_frames, threshold, fps,
                            coactivity_window_sec=0.0, time_sec=None):
    """Extend detected network-burst PEAKS into burst EPOCHS (onset / offset / duration).

    A network burst is the contiguous run of frames containing a significant peak over
    which the co-active fraction stays >= `threshold` -- the epoch during which
    population co-activity is elevated, not the single instant it peaks. Peaks whose
    runs coincide are reported once, at the run's own maximum.

    DURATION CAVEAT. `coactive_fraction` is built by convolving each event with a boxcar
    of width `coactivity_window_sec`, which broadens an instantaneous population event
    to at least that width. `duration_sec` is the raw supra-threshold extent;
    `duration_corrected_sec` subtracts the window width, floored at one frame. Report
    the corrected value as the network-burst duration (NBD); the raw value is kept so
    the correction stays auditable.

    Inter-burst intervals (NIBI) are measured onset-to-onset, so n_bursts bursts yield
    n_bursts - 1 intervals -- the quantity that limits whether a CV of NIBI means
    anything on a short recording.
    """
    cf = np.asarray(coactive_fraction, float)
    n = cf.size
    keys = ("onset_frame", "peak_frame", "offset_frame", "onset_sec", "peak_sec",
            "offset_sec", "duration_sec", "duration_corrected_sec", "peak_fraction")
    if n == 0 or len(np.atleast_1d(peak_frames)) == 0 or not np.isfinite(threshold):
        out = {k: np.array([]) for k in keys}
        out["inter_burst_interval_sec"] = np.array([])
        return out
    above = cf >= float(threshold)
    runs = []
    for p in np.asarray(peak_frames, int).ravel():
        if not (0 <= p < n) or not above[p]:
            continue                  # peak sits below the extent threshold: no epoch
        a = p
        while a > 0 and above[a - 1]:
            a -= 1
        b = p
        while b < n - 1 and above[b + 1]:
            b += 1
        runs.append((int(a), int(b)))
    runs = sorted(set(runs))
    if not runs:
        out = {k: np.array([]) for k in keys}
        out["inter_burst_interval_sec"] = np.array([])
        return out
    onset = np.array([a for a, _ in runs], int)
    offset = np.array([b for _, b in runs], int)
    peak = np.array([a + int(np.argmax(cf[a:b + 1])) for a, b in runs], int)
    dur = (offset - onset + 1) / float(fps)
    corr = np.maximum(1.0 / float(fps), dur - float(coactivity_window_sec))
    if time_sec is not None:
        t = np.asarray(time_sec, float)
        onset_sec, peak_sec, offset_sec = t[onset], t[peak], t[offset]
    else:
        onset_sec = onset / float(fps)
        peak_sec = peak / float(fps)
        offset_sec = offset / float(fps)
    ibi = np.diff(onset_sec) if len(onset_sec) > 1 else np.array([])
    return dict(onset_frame=onset, peak_frame=peak, offset_frame=offset,
                onset_sec=onset_sec, peak_sec=peak_sec, offset_sec=offset_sec,
                duration_sec=dur, duration_corrected_sec=corr,
                peak_fraction=cf[peak], inter_burst_interval_sec=ibi)


def burst_recruitment(event_frames, onset_frames, offset_frames, fps, frac=0.8):
    """Per network burst: which cells took part, and how fast the population locked.

    For each burst epoch [onset, offset] this returns the participating cells (>= 1 event
    inside the epoch), each participant's FIRST-event latency measured from burst onset,
    and the latency by which `frac` of the participants have fired -- t80 at the default.

    WHY RECRUITMENT TIME AND NOT JUST DURATION. Burst duration measures how long elevated
    co-activity lasted; recruitment time measures how tightly the population locked to the
    burst onset. The two dissociate -- a network can burst rarely but lock tightly, or
    often but loosely -- and they are different phenotypes. Recruitment is also the
    quantity an excitability channelopathy is most likely to move, because it is set by
    how fast activity spreads once a burst starts rather than by how often one starts.

    RESOLUTION LIMIT. Latencies are quantised to the EVENT timebase (1/fps), and for a
    resampled CASCADE train that timebase is finer than the acquisition frame interval.
    The population curve and its t_frac are real measurements; the ORDER of individual
    cells within one ACQUISITION frame is not resolved and must not be read off this
    output. Compare t_frac against the acquisition interval before interpreting it.

    Bursts with no participant return NaN latencies rather than 0, so that "no burst"
    never enters a mean as "instantaneous recruitment".
    """
    onset = np.asarray(onset_frames, int).ravel()
    offset = np.asarray(offset_frames, int).ravel()
    nb = onset.size
    out = dict(n_participants=np.zeros(nb, int),
               recruitment_sec=np.full(nb, np.nan),
               median_latency_sec=np.full(nb, np.nan),
               mean_latency_sec=np.full(nb, np.nan),
               participants=[], latencies_sec=[])
    if nb == 0:
        return out
    f = float(frac)
    for b in range(nb):
        a, z = int(onset[b]), int(offset[b])
        part, lat = [], []
        for i, fr in enumerate(event_frames):
            e = np.asarray(fr, int).ravel()
            inb = e[(e >= a) & (e <= z)]
            if inb.size:
                part.append(i)
                lat.append((inb.min() - a) / float(fps))
        out["participants"].append(np.asarray(part, int))
        lat = np.sort(np.asarray(lat, float))
        out["latencies_sec"].append(lat)
        out["n_participants"][b] = lat.size
        if lat.size:
            # index of the smallest latency by which >= frac of participants have fired
            k = int(np.ceil(f * lat.size)) - 1
            out["recruitment_sec"][b] = lat[max(0, min(k, lat.size - 1))]
            out["median_latency_sec"][b] = float(np.median(lat))
            out["mean_latency_sec"][b] = float(lat.mean())
    return out


def per_cell_burst_participation(event_frames, onset_frames, offset_frames):
    """Per cell: how many burst epochs it joined, and its in/out-of-burst event split.

    WHY THIS IS REPORTED PER CELL. A population synchrony average cannot distinguish a
    cell that is highly ACTIVE from a cell that is highly SYNCHRONISED. Both raise a mean
    event rate; only the second belongs in a synchrony claim. A well can contain its
    busiest neuron firing entirely outside every network burst, and averaging that cell
    into a population synchrony value measures the wrong thing. The two counts below
    separate them, and `participation_fraction` is the per-cell quantity that a genotype
    contrast should be run on once there are enough bursts for it to be graded rather
    than binary (it takes only n_bursts+1 distinct values).
    """
    onset = np.asarray(onset_frames, int).ravel()
    offset = np.asarray(offset_frames, int).ravel()
    n_cells = len(event_frames)
    nb = onset.size
    joined = np.zeros(n_cells, int)
    n_in = np.zeros(n_cells, int)
    n_tot = np.zeros(n_cells, int)
    for i, fr in enumerate(event_frames):
        e = np.asarray(fr, int).ravel()
        n_tot[i] = e.size
        for b in range(nb):
            k = int(((e >= onset[b]) & (e <= offset[b])).sum())
            if k:
                joined[i] += 1
                n_in[i] += k
    frac = joined / float(nb) if nb else np.full(n_cells, np.nan)
    return dict(n_bursts_joined=joined,
                participation_fraction=frac,
                n_events_in_bursts=n_in,
                n_events_outside_bursts=n_tot - n_in,
                n_bursts=int(nb))


def bootstrap_pairwise_ci(matrix, mask=None, n_boot=2000, ci=95.0, rng=None):
    """Percentile bootstrap CI for the mean of a pairwise matrix, RESAMPLING CELLS.

    WHY CELLS AND NOT PAIRS. m cells yield m(m-1)/2 pairs, but only m independent
    sampling units: every pair shares a cell with 2(m-2) others, so a bootstrap that
    resamples PAIRS treats dependent observations as independent and returns an interval
    far too narrow -- by roughly sqrt(m/2) at these m. Resampling cells and rebuilding the
    pair set from the drawn cells propagates the real sampling unit. This is the reason a
    mean pairwise synchrony computed from ~20 gated cells carries a much wider interval
    than its ~150 pairs suggest, and reporting it without one overstates the precision.

    Self-pairs created when the same cell is drawn twice are excluded: their STTC is
    identically 1 and would inflate every replicate. `mask` (if given) is the same fixed
    pair mask used for the point estimate -- e.g. the event-count gate -- so the interval
    describes the quantity actually reported, not a different pair set.

    Returns lo, hi, sd and the number of usable replicates. An interval from fewer than
    ~200 usable replicates, or from fewer than 3 cells, is returned as NaN rather than a
    misleadingly tight number.
    """
    M = np.asarray(matrix, float)
    if M.ndim != 2 or M.shape[0] != M.shape[1]:
        raise ValueError("matrix must be square (m, m)")
    m = M.shape[0]
    nan3 = (np.nan, np.nan, np.nan, 0)
    if m < 3:
        return nan3
    valid = np.isfinite(M)
    if mask is not None:
        valid &= np.asarray(mask, bool)
    np.fill_diagonal(valid, False)
    if not valid.any():
        return nan3
    g = rng if rng is not None else np.random.default_rng(0)
    reps = np.full(int(n_boot), np.nan)
    for b in range(int(n_boot)):
        idx = g.integers(0, m, m)
        sub = M[np.ix_(idx, idx)]
        ok = valid[np.ix_(idx, idx)] & (idx[:, None] != idx[None, :])
        if ok.any():
            reps[b] = sub[ok].mean()
    good = reps[np.isfinite(reps)]
    if good.size < 200:
        return (np.nan, np.nan, np.nan, int(good.size))
    a = (100.0 - float(ci)) / 2.0
    lo, hi = np.percentile(good, [a, 100.0 - a])
    return (float(lo), float(hi), float(good.std(ddof=1)), int(good.size))


def assembly_power_ok(n_active, n_bins, min_bins=50, max_ratio=0.2):
    """True only if there are enough time-bins for Marchenko-Pastur to be meaningful:
    T >= min_bins AND N/T <= max_ratio. Otherwise assembly detection should be skipped."""
    if n_active < 2 or n_bins < min_bins:
        return False
    return (n_active / n_bins) <= max_ratio


# ------------------------------------------------------------------ item G
def baseline_qc_plot(Fc, F0, fs, out_png, cell_indices=None, n_cells=6):
    """Save a per-cell QC figure: raw neuropil-corrected F with the rolling F0 under it.
    Lets you confirm F0 tracks bleaching without clipping transients."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = Fc.shape[0]
    if cell_indices is None:
        # pick the most active-looking cells (highest max-over-baseline)
        score = np.nanmax(Fc, axis=1) - np.nanmedian(Fc, axis=1)
        cell_indices = np.argsort(score)[::-1][:n_cells]
    cell_indices = list(cell_indices)[:n_cells]
    t = np.arange(Fc.shape[1]) / fs
    fig, axes = plt.subplots(len(cell_indices), 1, figsize=(9, 1.7 * len(cell_indices)),
                             sharex=True)
    if len(cell_indices) == 1:
        axes = [axes]
    for ax, ci in zip(axes, cell_indices):
        ax.plot(t, Fc[ci], lw=0.6, color="#333", label="F (neuropil-corr)")
        ax.plot(t, F0[ci], lw=1.3, color="#d1495b", label="rolling F0")
        ax.set_ylabel(f"cell {ci}", fontsize=8)
        ax.tick_params(labelsize=7)
    axes[0].legend(fontsize=7, loc="upper right")
    axes[-1].set_xlabel("time (s)")
    fig.suptitle("Rolling-baseline QC — F0 should hug the resting level, not clip peaks",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return out_png


# ------------------------------------------------------------------ CASCADE event detection
def cascade_spike_rate(spike_prob, fs):
    """Continuous inferred spike RATE per cell (spikes/s) from CASCADE spike-prob.

    CASCADE's spike_prob is the expected number of spikes per frame; summing over frames
    gives the expected spike count, and dividing by duration gives rate. This is the
    calibrated, threshold-free readout CASCADE was built for -- prefer it over any binary
    event count for per-cell activity level, population coupling and firing-rate stats.

    Returns (rate_per_cell [n_cells], total_spikes_per_cell [n_cells]).
    """
    sp = np.asarray(spike_prob, float)
    n_frames = sp.shape[1]
    total = np.nansum(sp, axis=1)                      # expected spikes per cell
    valid = np.sum(np.isfinite(sp), axis=1) / fs       # seconds actually inferred (edges are NaN)
    valid = np.where(valid > 0, valid, np.nan)
    return total / valid, total


def cascade_events(spike_prob, fs, threshold=None, k_mad=3.0, min_prob=0.05,
                   min_distance_sec=0.5, refractory_sec=None):
    """Discrete events from CASCADE spike-prob with a DATA-DRIVEN threshold.

    Replaces the arbitrary spike_prob >= 0.3 floor. CASCADE spike-prob amplitude scales
    with SNR and frame rate, so a fixed 0.3 mis-fires across recordings (on the 45 Hz SS9
    data the whole trace maxes ~0.66, so 0.3 keeps almost nothing). Instead:

      threshold = max(min_prob, median(sp) + k_mad * MAD(sp))   per recording,

    i.e. peaks that rise k_mad robust-SDs above each recording's own spike-prob noise floor.
    Pass an explicit `threshold` to override (e.g. to reproduce the old 0.3 behaviour).

    NOTE on sparse recordings: when most cells are silent, the pooled median+MAD collapses
    to near zero and `min_prob` becomes the binding threshold (the returned `floor_binding`
    flag says when this happened). In that regime this is a simple fixed floor, NOT a
    data-adaptive threshold -- prefer `cascade_discrete_spikes()` (the CASCADE authors'
    threshold-free, calibrated spike inference) for the primary event train, and treat this
    function as a fast approximate cross-check.

    Returns dict:
      event_frames  : list[np.ndarray]   peak frame indices per cell
      threshold     : float              the threshold actually used
      n_active      : int                cells with >=1 event
      active_mask   : np.ndarray[bool]
      floor_binding : bool               True if min_prob (not median+k_mad*MAD) set threshold
    """
    from scipy.signal import find_peaks
    sp = np.asarray(spike_prob, float)
    flat = sp[np.isfinite(sp)]
    floor_binding = False
    if threshold is None:
        med = np.median(flat)
        mad = 1.4826 * np.median(np.abs(flat - med)) + 1e-12
        mad_thr = med + k_mad * mad
        threshold = max(min_prob, mad_thr)
        floor_binding = bool(mad_thr < min_prob)
    dist = max(1, int(round((refractory_sec or min_distance_sec) * fs)))
    event_frames = []
    for i in range(sp.shape[0]):
        x = np.nan_to_num(sp[i], nan=0.0)
        pk, _ = find_peaks(x, height=threshold, distance=dist)
        event_frames.append(pk)
    n_ev = np.array([len(e) for e in event_frames])
    active = n_ev > 0
    return {"event_frames": event_frames, "threshold": float(threshold),
            "n_active": int(active.sum()), "active_mask": active,
            "floor_binding": floor_binding}


def cascade_discrete_spikes(spike_prob, model_name, cascade_dir=None,
                            model_folder=None, random_seed=0):
    """CALIBRATED discrete spike times from CASCADE spike-prob (authors' method).

    Wraps cascade2p.utils_discrete_spikes.infer_discrete_spikes (Rupprecht et al. 2021,
    Nat Neurosci). This is the RECOMMENDED primary event extractor -- prefer it over
    cascade_events():

      * Threshold-free. Places discrete spikes so their count in each active region equals
        the integrated probability mass (sum of spike_prob), rather than counting crossings
        of an arbitrary height. No 0.3 floor, no min_prob floor.
      * Calibrated & rate-invariant. Reads sampling_rate and smoothing from the model's own
        config.yaml, so spike trains from different indicators/rates (SS9 45 Hz jGCaMP8s vs
        SS10 100 Hz jGCaMP8f) are directly comparable -- essential for WT-vs-KCNT1 stats.
      * Correct input for STTC (Cutts & Eglen 2014), which was defined for spike trains.

    Requires the CASCADE repo importable (cascade2p) and the model's config.yaml present in
    the Pretrained_models folder. `model_name` is the model used to produce spike_prob (read
    it from cascade_meta.json['model']). `cascade_dir` defaults to ~/Cascade; model_folder
    defaults to <cascade_dir>/Pretrained_models.

    infer_discrete_spikes uses Monte-Carlo/Metropolis sampling, so total spike counts wobble
    ~3% run-to-run while the active-cell set is stable. `random_seed` (default 0) seeds numpy
    before the call so a re-run of the pipeline reproduces identical spike trains; pass
    random_seed=None to leave the global RNG untouched.

    Returns dict:
      event_frames : list[np.ndarray]   inferred spike frame indices per cell (int)
      n_spikes     : np.ndarray[int]    spikes per cell
      n_active     : int                cells with >=1 spike
      active_mask  : np.ndarray[bool]
      approximation: np.ndarray         reconstructed spike-density (n_cells x n_frames)
      model        : str
    """
    import os, sys
    if cascade_dir is None:
        cascade_dir = os.path.expanduser("~/Cascade")
    if model_folder is None:
        model_folder = os.path.join(cascade_dir, "Pretrained_models")
    if cascade_dir not in sys.path:
        sys.path.insert(0, cascade_dir)
    from cascade2p.utils_discrete_spikes import infer_discrete_spikes
    if random_seed is not None:
        np.random.seed(random_seed)
    sp = np.asarray(spike_prob, float)
    approx, spikes = infer_discrete_spikes(sp, model_name,
                                           model_folder=model_folder, verbosity=0)
    n_fr = sp.shape[1]
    event_frames = []
    for s in spikes:
        a = np.asarray(s, dtype=int)
        a = a[(a >= 0) & (a < n_fr)]        # guard against edge-offset rounding
        event_frames.append(np.sort(a))
    n_spikes = np.array([len(e) for e in event_frames])
    active = n_spikes > 0
    return {"event_frames": event_frames, "n_spikes": n_spikes,
            "n_active": int(active.sum()), "active_mask": active,
            "approximation": approx, "model": model_name}


def load_cascade_output(plane_dir):
    """Load cascade_spike_prob.npy + cascade_meta.json from a Suite2p plane0 dir.

    Returns (spike_prob [n_cells x n_frames], fs, meta_dict). fs comes from the meta
    sidecar's output_fps (authoritative: may differ from ops['fs'] if run_cascade resampled
    to the model rate). Falls back to ops['fs'] if no sidecar is present.
    """
    import os, json
    sp = np.load(os.path.join(plane_dir, "cascade_spike_prob.npy"))
    meta_path = os.path.join(plane_dir, "cascade_meta.json")
    if os.path.isfile(meta_path):
        meta = json.load(open(meta_path))
        fs = float(meta.get("output_fps") or meta.get("input_fps"))
    else:
        ops = np.load(os.path.join(plane_dir, "ops.npy"), allow_pickle=True).item()
        fs = float(ops.get("fs", np.nan)); meta = {}
    return sp, fs, meta
