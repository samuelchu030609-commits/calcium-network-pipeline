#!/usr/bin/env python
"""Tabulate every well of one plate into a single comparison workbook.

Reads each well's metrics workbook (<well>_metrics.xlsx from run_pipeline / the GUI, or
<plate>_<well>_metrics.xlsx from the lab's overnight runner) and writes
<plate>/<plate>_plate_comparison.xlsx with wells as columns, grouped by the plate map:

  Key Numbers   every Key Numbers measure except recording length, one column per well,
                plus a mean and SD column per group (formulas, descriptive only - no tests)
  Group Events  total network bursts per well, then percent_of_network for each burst
  Statistics    first group vs second group for every numeric key number: mean, SD, n,
                Welch's unpaired t-test (t, df, two-tailed p), Bonferroni-adjusted p
  Graphs        one dot plot per key number (each well a dot, mean +/- SD), also saved as
                PNGs in <plate>/<plate>_graphs/
  Notes         plate map, source files, and the code version that made the numbers

Quadrant plates (folders C02_s1 .. C02_s4 = the four quadrants of well C02, each its own
3-min movie): the quadrants are POOLED into one whole-well value (see pool_well). Activity
measures use every quadrant with cells; synchrony, burst and team measures use only
quadrants with >= --min-active active cells (default 5), because a network statistic from
2-3 cells is noise. The Quadrants tab lists what was used. The unit of the statistics is
the WELL.

The plate map is given by well COLUMN number (the digits after the row letter):
    python tools/compare_plate.py "/path/to/plate" --group WT=02,03 --group KCNT1=04,05

Run in the suite2p_analysis env. Reads only; never changes a well's own workbook.
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Arial"
SKIP_MEASURES = {"Recording length (min)"}          # identical for every well
GROUP_FILLS = ["DCE6F1", "FCE4D6", "E2EFDA", "FFF2CC"]  # blue, orange, green, yellow
THIN = Side(style="thin", color="BFBFBF")
# Graph colours: slots 1-2 of the validated categorical palette (blue, orange).
GROUP_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
MIN_N_TEST = 3            # wells with a value, per group, before a t-test is run
NOT_TESTED = {"...as a p-value": "not tested: this row is itself a p-value"}
POS_RE = re.compile(r"^([A-H][0-9]{2})_s([0-9]+)$")
ACTIVE_ROW = "Cells that fired (active)"
TEAMS_ROW = "Cell teams (assemblies)"


def pool_well(quads, sheets, n_quads_total, min_active):
    """Combine one well's quadrants into ONE well-level Key Numbers table + burst list.

    The quadrants are four separate 3-min movies of the same well, filmed one after another,
    so the well's cell population is the union of the quadrants' cells:
      * counts are summed (cells tracked, cells that fired, teams, cells in a team) and
        % active is total active / total cells;
      * per-cell rates are recomputed over ALL active cells of the well (median / mean);
      * synchrony is a within-quadrant quantity (cells in different quadrants were never
        recorded at the same time), pooled over quadrants weighted by the number of cell
        pairs (STTC) or active cells (per-cell measures) that each quadrant contributed;
      * bursts are pooled event by event; the burst count is per 3-min quadrant so that
        wells with fewer usable quadrants are comparable.
    Synchrony/burst/team rows use only quadrants with >= min_active active cells.
    Returns (key DataFrame, bursts DataFrame, n quadrants used for synchrony, {quad: used}).
    """
    kn = {q: dict(zip(sheets[q]["Key Numbers"]["Measure"], sheets[q]["Key Numbers"]["Value"]))
          for q in quads}
    num = lambda q, m: (lambda v: v[0] if v[1] in ("num", "pct") else np.nan)(parse_value(kn[q][m]))
    active = {q: (num(q, ACTIVE_ROW) if np.isfinite(num(q, ACTIVE_ROW)) else 0) for q in quads}
    cells = {q: num(q, "Cells tracked") for q in quads}
    sq = [q for q in quads if active[q] >= min_active]
    rate_frames = [sheets[q]["Firing Rates (per cell)"] for q in quads
                   if len(sheets[q]["Firing Rates (per cell)"])]
    rates = (pd.concat(rate_frames, ignore_index=True) if rate_frames
             else pd.DataFrame({"firings_per_minute": []}))
    tog = {q: sheets[q]["Firing Together (per cell)"] for q in sq}
    frames = [sheets[q]["Group Events (bursts)"].assign(quadrant=POS_RE.match(q).group(2))
              for q in sq if len(sheets[q]["Group Events (bursts)"])]
    bursts = (pd.concat(frames, ignore_index=True) if frames
              else sheets[quads[0]]["Group Events (bursts)"].iloc[0:0])

    def wmean(m, weight):
        vals = [(num(q, m), weight(q)) for q in sq]
        vals = [(v, w) for v, w in vals if np.isfinite(v) and w > 0]
        return (sum(v * w for v, w in vals) / sum(w for _, w in vals)) if vals else np.nan

    gated_k = {q: int(tog[q]["meets_event_floor"].astype(bool).sum()) for q in sq}
    gated_pairs = lambda q: gated_k[q] * (gated_k[q] - 1) / 2
    all_pairs = lambda q: active[q] * (active[q] - 1) / 2
    fr = rates["firings_per_minute"].dropna()
    gaps = bursts["gap_since_previous_burst_sec"].dropna() if len(bursts) else pd.Series(dtype=float)
    ev_total = {q: float(sheets[q]["Summary"].set_index("Metric").loc["total_events_detected", "Value"])
                for q in sq}

    def summed(m, only_numeric_quads):
        vals = [parse_value(kn[q][m]) for q in sq]
        nums = [v for v, k in vals if k == "num"]
        return float(sum(nums)) if nums else (vals[0][0] if vals and only_numeric_quads else np.nan)

    teams_ok = [q for q in sq if parse_value(kn[q][TEAMS_ROW])[1] == "num"]
    pct = lambda x: np.nan if not np.isfinite(x) else f"{x * 100:.1f}%"
    tot_cells = float(np.nansum(list(cells.values())))
    rule = {
        "Cells tracked": tot_cells,
        ACTIVE_ROW: float(sum(active.values())),
        "Percent active": pct(sum(active.values()) / tot_cells) if tot_cells else np.nan,
        "Typical firing rate (median /min)": float(fr.median()) if len(fr) else np.nan,
        "Typical cell fires about every (sec)": (60.0 / fr.median()) if len(fr) and fr.median() else np.nan,
        "Average firing rate (mean /min)": float(fr.mean()) if len(fr) else np.nan,
        "Togetherness (STTC, -1 to +1)": wmean("Togetherness (STTC, -1 to +1)", gated_pairs),
        "...measured from how many cells": f"{len(sq)} of {n_quads_total} quadrants",
        "Is that togetherness real? (z-score)": wmean("Is that togetherness real? (z-score)", gated_pairs),
        "...as a p-value": "per quadrant only",
        "...and how big vs chance (excess)": wmean("...and how big vs chance (excess)", gated_pairs),
        "Togetherness incl. barely-firing cells": wmean("Togetherness incl. barely-firing cells", all_pairs),
        "Follows-the-crowd (pop. coupling, 0-1)": wmean("Follows-the-crowd (pop. coupling, 0-1)", lambda q: active[q]),
        "Average partners per cell": (lambda v: v if np.isfinite(v) else
                                      next((kn[q]["Average partners per cell"] for q in sq), np.nan))(
                                          wmean("Average partners per cell", lambda q: active[q])),
        TEAMS_ROW: (float(sum(num(q, TEAMS_ROW) for q in teams_ok)) if teams_ok
                    else ("underpowered" if sq else np.nan)),
        "Cells that belong to a team": (float(sum(num(q, "Cells that belong to a team") for q in teams_ok))
                                        if teams_ok else np.nan),
        "Network bursts": (len(bursts) / len(sq)) if sq else np.nan,
        "Biggest burst (% of cells)": pct(max(num(q, "Biggest burst (% of cells)") for q in sq)) if sq else np.nan,
        "Typical burst length (sec)": float(bursts["burst_length_seconds"].mean()) if len(bursts) else np.nan,
        "Gap between bursts (sec)": float(gaps.mean()) if len(gaps) else np.nan,
        "How regular the bursts are (CV)": float(gaps.std(ddof=1) / gaps.mean()) if len(gaps) >= 2 else np.nan,
        "Firings outside any burst (%)": pct(
            sum(num(q, "Firings outside any burst (%)") * ev_total[q] for q in sq)
            / sum(ev_total[q] for q in sq)) if sq and sum(ev_total[q] for q in sq) else np.nan,
    }
    ref = sheets[quads[0]]["Key Numbers"]
    out = []
    for m in ref["Measure"]:
        if m.startswith("- "):
            out.append((m, np.nan))
        elif m in rule:
            out.append((m, rule[m]))
        else:                        # a row this version does not know how to pool
            out.append((m, "not pooled"))
    key = pd.DataFrame(out, columns=["Measure", "Value"])
    key["What it means"] = list(ref["What it means"])
    key.loc[key["Measure"] == "Network bursts", "Measure"] = "Network bursts (per 3-min quadrant)"
    return key, bursts, len(sq), {q: q in sq for q in quads}

def parse_groups(specs):
    groups = {}
    for spec in specs:
        name, _, cols = spec.partition("=")
        if not name or not cols:
            sys.exit(f"bad --group {spec!r}; expected NAME=02,03")
        groups[name.strip()] = [c.strip().zfill(2) for c in cols.split(",") if c.strip()]
    return groups


def parse_value(v):
    """Key Numbers values are display strings ('87%', '0.497', 'underpowered').
    Return (value, kind) with kind in {'pct', 'num', 'text', 'na'}."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a", "na"
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v), "num"
    s = str(v).strip()
    m = re.fullmatch(r"(-?[0-9.]+)\s*%", s)
    if m:
        return float(m.group(1)) / 100.0, "pct"
    try:
        return float(s), "num"
    except ValueError:
        return s, "text"


def cell(ws, r, c, value=None, bold=False, fill=None, fmt=None, align=None, italic=False,
         color=None, border=True):
    x = ws.cell(row=r, column=c)
    if value is not None:
        x.value = value
    x.font = Font(name=FONT, bold=bold, italic=italic, color=color)
    if fill:
        x.fill = PatternFill("solid", fgColor=fill)
    if fmt:
        x.number_format = fmt
    if align:
        x.alignment = Alignment(horizontal=align, vertical="center", wrap_text=False)
    if border:
        x.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    return x


def layout(groups, wells_found):
    """Column plan: [(kind, group, well_or_stat)], data starts at column 2."""
    plan = []
    for g, cols in groups.items():
        members = [w for w in wells_found if w[1:] in cols]
        for w in members:
            plan.append(("well", g, w))
        plan.append(("mean", g, members))
        plan.append(("sd", g, members))
    return plan


def header_rows(ws, plan, groups, first_label):
    fills = {g: GROUP_FILLS[i % len(GROUP_FILLS)] for i, g in enumerate(groups)}
    cell(ws, 1, 1, "Group", bold=True, fill="D9D9D9")
    cell(ws, 2, 1, first_label, bold=True, fill="D9D9D9")
    col = 2
    for g in groups:
        span = [i for i, p in enumerate(plan) if p[1] == g]
        a, b = col + span[0], col + span[-1]
        ws.merge_cells(start_row=1, start_column=a, end_row=1, end_column=b)
        cell(ws, 1, a, f"{g}  (n = {len(span) - 2} wells)", bold=True, fill=fills[g], align="center")
        for c in range(a + 1, b + 1):
            cell(ws, 1, c, fill=fills[g])
    for i, (kind, g, w) in enumerate(plan):
        label = w if kind == "well" else f"{g} {kind}"
        cell(ws, 2, col + i, label, bold=True, fill=fills[g], align="center")
    return fills


def stat_formula(kind, ws_row, plan, i):
    members = [j for j, p in enumerate(plan) if p[0] == "well" and p[1] == plan[i][1]]
    a = get_column_letter(2 + members[0])
    b = get_column_letter(2 + members[-1])
    rng = f"{a}{ws_row}:{b}{ws_row}"
    fn = "AVERAGE" if kind == "mean" else "STDEV"
    return f'=IFERROR({fn}({rng}),"")'


def stat_range(plan, g, row):
    idx = [j for j, p in enumerate(plan) if p[0] == "well" and p[1] == g]
    return f"'Key Numbers'!{get_column_letter(2 + idx[0])}{row}:{get_column_letter(2 + idx[-1])}{row}"


def welch(a, b):
    """Welch's unpaired t-test. Returns (t, df, p) or None."""
    from scipy import stats
    if len(a) < MIN_N_TEST or len(b) < MIN_N_TEST:
        return None
    a, b = np.asarray(a, float), np.asarray(b, float)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    if va + vb == 0:
        return None
    res = stats.ttest_ind(a, b, equal_var=False)
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    return float(res.statistic), float(df), float(res.pvalue)


def numeric(by_well, wells):
    return [by_well[w][0] for w in wells if by_well[w][1] in ("num", "pct")]


def statistics_sheet(book, plan, groups, gw, key_rows):
    """Group A vs group B for every numeric key number, as live Excel formulas.
    Returns {measure: (t, df, p) or reason-string} computed in Python for the graphs."""
    ga, gb = list(groups)[:2]
    st = book.create_sheet("Statistics")
    hdr = ["Measure", f"{ga} mean", f"{ga} SD", f"{ga} n", f"{gb} mean", f"{gb} SD", f"{gb} n",
           f"Difference ({gb} - {ga})", "t", "df (Welch)", "p (two-tailed)", "Significant?",
           "p x number of tests (Bonferroni)", "Note"]
    fills = {ga: GROUP_FILLS[0], gb: GROUP_FILLS[1]}
    for c, h in enumerate(hdr, 1):
        fill = fills[ga] if h.startswith(ga + " ") else fills[gb] if h.startswith(gb + " ") else "D9D9D9"
        cell(st, 1, c, h, bold=True, fill=fill, align="center")
    out, r = {}, 2
    tested_rows = []
    for m, krow, is_pct, by_well in key_rows:
        a, b = numeric(by_well, gw[ga]), numeric(by_well, gw[gb])
        fmt = "0.0%" if is_pct else "0.###"
        cell(st, r, 1, m)
        ra, rb = stat_range(plan, ga, krow), stat_range(plan, gb, krow)
        for c, f in ((2, f"=AVERAGE({ra})"), (3, f"=STDEV({ra})"), (4, f"=COUNT({ra})"),
                     (5, f"=AVERAGE({rb})"), (6, f"=STDEV({rb})"), (7, f"=COUNT({rb})")):
            cell(st, r, c, f'=IFERROR({f[1:]},"")', fmt="0" if c in (4, 7) else fmt, align="right")
        cell(st, r, 8, '=IFERROR(E{0}-B{0},"")'.format(r), fmt=fmt, align="right")
        res = None if m in NOT_TESTED else welch(a, b)
        if res is None:
            why = NOT_TESTED.get(m) or (
                f"not tested: needs >= {MIN_N_TEST} wells with a value in each group "
                f"({ga} {len(a)}, {gb} {len(b)})" if min(len(a), len(b)) < MIN_N_TEST
                else "not tested: no variation within either group")
            out[m] = why
            for c in range(9, 14):
                cell(st, r, c, "")
            cell(st, r, 14, why, italic=True, color="808080")
        else:
            out[m] = res
            # t and df from the group means, SDs and n (Welch-Satterthwaite).
            cell(st, r, 9, f"=(B{r}-E{r})/SQRT(C{r}^2/D{r}+F{r}^2/G{r})", fmt="0.00", align="right")
            cell(st, r, 10, f"=(C{r}^2/D{r}+F{r}^2/G{r})^2/((C{r}^2/D{r})^2/(D{r}-1)"
                            f"+(F{r}^2/G{r})^2/(G{r}-1))", fmt="0.0", align="right")
            cell(st, r, 11, f"=TTEST({ra},{rb},2,3)", fmt="0.0000", align="right")
            cell(st, r, 12, f'=IF(K{r}<0.001,"***",IF(K{r}<0.01,"**",IF(K{r}<0.05,"*","ns")))',
                 align="center", bold=True)
            tested_rows.append(r)
            cell(st, r, 14, "")
        r += 1
    n_tests = len(tested_rows)
    for tr in tested_rows:
        cell(st, tr, 13, f"=MIN(1,K{tr}*{n_tests})", fmt="0.0000", align="right")
    notes = [
        f"Test: Welch's UNPAIRED two-sample t-test, two-tailed ({ga} wells vs {gb} wells). "
        "Unpaired because each well is independent: no {0} well is matched to a particular "
        "{1} well.".format(ga, gb),
        "t and df are computed from the mean, SD and n columns; p is Excel's TTEST on the same "
        "well values (type 3 = unequal variances).",
        "Significant?: * p < 0.05, ** p < 0.01, *** p < 0.001, ns = not significant. Uses the "
        "uncorrected p.",
        f"{n_tests} measures were tested, and several measure the same thing (e.g. the STTC "
        "rows), so some p < 0.05 are expected by chance. The Bonferroni column is the "
        "strictest correction: p x number of tests.",
        "The unit is the WELL, and all wells come from one plate/differentiation. That makes "
        "these technical replicates; a genotype claim needs independent differentiations.",
    ]
    for i, t in enumerate(notes):
        cell(st, r + 1 + i, 1, t, italic=True, border=False)
    st.column_dimensions["A"].width = 40
    for c in range(2, 14):
        st.column_dimensions[get_column_letter(c)].width = 12
    st.column_dimensions["H"].width = 16
    st.column_dimensions["M"].width = 16
    st.column_dimensions["N"].width = 60
    st.freeze_panes = "B2"
    return out


def make_graphs(graph_dir, pname, groups, gw, key_rows, tests):
    """One dot plot per numeric key number. Returns the PNG paths, in table order."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    graph_dir.mkdir(parents=True, exist_ok=True)
    for old in graph_dir.glob("*.png"):
        old.unlink(missing_ok=True)   # ._ sidecars vanish with their image on exFAT
    plt.rcParams.update({"font.family": "Arial", "font.size": 10})
    ink, muted, grid = "#0b0b0b", "#52514e", "#e6e5e0"
    gnames = list(groups)[:2]
    pngs = []
    k = 0
    for m, _row, is_pct, by_well in key_rows:
        # A graph needs a value in both groups; a p-value row is not a quantity to plot.
        if m in NOT_TESTED or min(len(numeric(by_well, gw[g])) for g in gnames) == 0:
            continue
        k += 1
        fig, ax = plt.subplots(figsize=(3.6, 3.6), dpi=200)
        tops = []
        for x, g in enumerate(gnames):
            vals = np.array(numeric(by_well, gw[g]), float) * (100 if is_pct else 1)
            col = GROUP_COLOURS[x]
            if len(vals):
                order = np.argsort(np.argsort(vals))
                off = (order / max(len(vals) - 1, 1) - 0.5) * 0.28 if len(vals) > 1 else [0.0]
                ax.scatter(x + np.asarray(off), vals, s=34, color=col, edgecolor="white",
                           linewidth=1.2, zorder=3)
                mu = vals.mean()
                sd = vals.std(ddof=1) if len(vals) > 1 else 0
                ax.hlines(mu, x - 0.26, x + 0.26, color=ink, linewidth=2, zorder=4)
                if len(vals) > 1:
                    ax.vlines(x, mu - sd, mu + sd, color=ink, linewidth=1.2, zorder=4)
                    ax.hlines([mu - sd, mu + sd], x - 0.08, x + 0.08, color=ink,
                              linewidth=1.2, zorder=4)
                tops.append(max(vals.max(), mu + sd))
        ax.set_xticks(range(len(gnames)))
        ax.set_xticklabels([f"{g}\n(n = {len(numeric(by_well, gw[g]))})" for g in gnames])
        ax.set_xlim(-0.6, len(gnames) - 0.4)
        ax.set_title(m, fontsize=10.5, color=ink, loc="left", wrap=True)
        ax.set_ylabel("%" if is_pct else "", color=muted)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color("#b0afa8")
        ax.tick_params(colors=muted)
        res = tests.get(m)
        lo, hi = ax.get_ylim()
        span = hi - lo
        if isinstance(res, tuple) and tops:
            t, df, pv = res
            y = max(tops) + 0.06 * span
            ax.plot([0, 0, 1, 1], [y - 0.02 * span, y, y, y - 0.02 * span], color=ink, lw=1)
            stars = "***" if pv < 0.001 else "**" if pv < 0.01 else "*" if pv < 0.05 else "ns"
            ptxt = "p < 0.001" if pv < 0.001 else f"p = {pv:.3f}"
            ax.text(0.5, y + 0.015 * span, f"{stars}  ({ptxt})", ha="center", va="bottom",
                    fontsize=9, color=ink)
            ax.set_ylim(lo, y + 0.16 * span)
        else:
            ax.set_xlabel(f"not tested: fewer than {MIN_N_TEST} wells in a group",
                          fontsize=8.5, color=muted, style="italic")
        fig.tight_layout()
        safe = re.sub(r"[^A-Za-z0-9]+", "_", m).strip("_")[:50]
        path = graph_dir / f"{k:02d}_{safe}.png"
        fig.savefig(path, facecolor="white")
        plt.close(fig)
        pngs.append(path)
    return pngs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plate", help="Plate folder holding the <well>/suite2p/plane0 folders.")
    ap.add_argument("--group", action="append", required=True,
                    help="NAME=column numbers, e.g. WT=02,03 (repeat per group).")
    ap.add_argument("--out", default=None, help="Output path (default: inside the plate folder).")
    ap.add_argument("--min-active", type=int, default=5,
                    help="Positions need at least this many active cells to count toward "
                         "synchrony/burst/team measures (default 5; quadrant plates only).")
    args = ap.parse_args()

    plate = Path(args.plate).expanduser().resolve()
    pname = plate.name
    groups = parse_groups(args.group)

    books = {}
    # Workbooks are <plate>_<rec>_metrics.xlsx (run_plate.sh) or <rec>_metrics.xlsx
    # (this repo's run_pipeline / GUI, which names them after the recording folder).
    for wb in sorted(plate.glob("*/suite2p/plane0/*_metrics.xlsx")):
        rid = wb.parent.parent.parent.name
        if wb.name in (f"{pname}_{rid}_metrics.xlsx", f"{rid}_metrics.xlsx"):
            books[rid] = wb
    if not books:
        sys.exit(f"No <well>_metrics.xlsx or {pname}_<well>_metrics.xlsx found under {plate}")
    multi = any(POS_RE.match(r) for r in books)
    well_of = (lambda rid: POS_RE.match(rid).group(1) if POS_RE.match(rid) else rid)
    in_map = (lambda w: any(w[1:] in c for c in groups.values()))
    unmapped = sorted({well_of(r) for r in books if not in_map(well_of(r))})
    recs = sorted(r for r in books if in_map(well_of(r)))

    key_rec, bursts_rec, prov_rec, sheets = {}, {}, {}, {}
    for rid in recs:
        x = pd.read_excel(books[rid], sheet_name=None)
        sheets[rid] = x
        key_rec[rid] = x["Key Numbers"]
        bursts_rec[rid] = x["Group Events (bursts)"]
        p = books[rid].with_name(books[rid].stem + ".PROVENANCE.txt")
        txt = p.read_text() if p.exists() else ""
        prov_rec[rid] = {k: (re.search(rf"^{k}: (.*)$", txt, re.M) or [None, "?"])[1]
                         for k in ("pipeline_fixes_sha256_12", "template_sha256_12",
                                   "event_source", "cascade_model", "generated")}

    wells = sorted({well_of(r) for r in recs}, key=lambda w: (w[1:], w[0]))  # column, row
    key, bursts, prov, n_sync, pos_rows = {}, {}, {}, {}, []
    if multi:
        # Every quadrant folder, including ones that produced no workbook (no cells).
        all_pos = sorted(d.name for d in plate.iterdir()
                         if d.is_dir() and POS_RE.match(d.name) and in_map(well_of(d.name)))
        for w in wells:
            mine = [r for r in recs if well_of(r) == w]
            total = len([p for p in all_pos if well_of(p) == w])
            key[w], bursts[w], n_sync[w], sync_used = pool_well(
                mine, sheets, total, args.min_active)
            used = {q: (True, sync_used[q]) for q in mine}
            prov[w] = prov_rec[mine[0]]
            for pid in (p for p in all_pos if well_of(p) == w):
                if pid not in used:
                    pos_rows.append((pid, "", "", "no", "no", "no results: no cells detected"))
                    continue
                d = dict(zip(key_rec[pid]["Measure"], key_rec[pid]["Value"]))
                a = parse_value(d[ACTIVE_ROW])[0]
                pos_rows.append((pid, d["Cells tracked"], d[ACTIVE_ROW], "yes",
                                 "yes" if used[pid][1] else "no",
                                 "" if used[pid][1] else f"fewer than {args.min_active} active cells"))
    else:
        for w in wells:
            key[w], bursts[w], prov[w] = key_rec[w], bursts_rec[w], prov_rec[w]

    ref = key[wells[0]]
    measures = list(ref["Measure"])
    for w in wells[1:]:
        if list(key[w]["Measure"]) != measures:
            sys.exit(f"{w}'s Key Numbers rows differ from {wells[0]}'s - different code versions?")
    meaning = dict(zip(ref["Measure"], ref["What it means"]))

    plan = layout(groups, wells)
    out = Path(args.out) if args.out else plate / f"{pname}_plate_comparison.xlsx"
    book = Workbook()

    # ------------------------------------------------------------ Key Numbers
    ws = book.active
    ws.title = "Key Numbers"
    fills = header_rows(ws, plan, groups, "Measure")
    note_col = 2 + len(plan)
    cell(ws, 1, note_col, fill="D9D9D9")
    cell(ws, 2, note_col, "What it means", bold=True, fill="D9D9D9")
    r = 3
    key_rows = []          # (measure, sheet row, is_percent, {well: (value, kind)})
    for mi, m in enumerate(measures):
        if m in SKIP_MEASURES:
            continue
        vals = [parse_value(key[w].loc[mi, "Value"]) for w in wells]
        if m == "Cells that belong to a team":
            # 0 members is not a measured zero when the assembly test was skipped.
            teams = list(ref["Measure"]).index("Cell teams (assemblies)")
            vals = [("n/a", "na") if parse_value(key[w].loc[teams, "Value"])[1] == "text"
                    else v for w, v in zip(wells, vals)]
        if m.startswith("- ") and all(k == "na" for _, k in vals):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=note_col)
            cell(ws, r, 1, m.strip("- ").strip(), bold=True, fill="F2F2F2")
            r += 1
            continue
        kinds = {k for _, k in vals}
        fmt = "0%" if "pct" in kinds else "0.####"
        cell(ws, r, 1, m, bold=False)
        by_well = dict(zip(wells, vals))
        for i, (kind, g, w) in enumerate(plan):
            c = 2 + i
            if kind == "well":
                v, k = by_well[w]
                cell(ws, r, c, v, fmt=fmt if k in ("num", "pct") else None,
                     align="center" if k in ("text", "na") else "right",
                     color="808080" if k == "na" else None)
            else:
                numeric = any(by_well[x][1] in ("num", "pct") for x in w)
                cell(ws, r, c, stat_formula(kind, r, plan, i) if numeric else "",
                     fmt=("0.0%" if fmt == "0%" else "0.####"), italic=True,
                     fill=fills[g], align="right")
        cell(ws, r, note_col, meaning.get(m, ""), border=True)
        if kinds & {"num", "pct"}:
            key_rows.append((m, r, "pct" in kinds, by_well))
        r += 1
    last_key_row = r - 1
    r += 1
    cell(ws, r, 1, "Mean and SD are descriptive only (Excel AVERAGE / STDEV over that group's "
                   "wells; text and n/a cells are left out). No statistical test is applied.",
         italic=True, border=False)
    cell(ws, r + 1, 1, "n/a = not defined for that well (e.g. burst length when the well had "
                       "no network bursts, or team membership when the team test was skipped).",
         italic=True, border=False)
    if multi:
        cell(ws, r + 3, 1, f"Each well = its four quadrants pooled into one well: cells and teams "
                           f"are summed, % active and firing rates are over all the well's cells, "
                           f"synchrony is pair-weighted across quadrants (quadrants were filmed one "
                           f"after another, so only cells within a quadrant can be compared). "
                           f"Synchrony, burst and team rows use only quadrants "
                           f"with >= {args.min_active} active cells (see Notes for which).",
             italic=True, border=False)
    cell(ws, r + 2, 1, "Cell teams: 'underpowered' = too many active cells for a 3-min recording "
                       "(needs active cells <= 20% of the 0.5 s time bins), so the group mean "
                       "covers only the wells where the test ran.", italic=True, border=False)

    # ------------------------------------------------------------ Group Events
    ge = book.create_sheet("Group Events")
    fills = header_rows(ge, plan, groups, "")
    # Event rows. On quadrant plates the rows are grouped by quadrant: a burst belongs to ONE
    # quadrant's own 3-min movie, and quadrants were filmed at different times, so bursts
    # are never lined up across quadrants. Each value shows when in its movie it happened.
    def events_of(w, quad):
        b = bursts[w]
        if quad is not None:
            b = b[b["quadrant"].astype(str) == quad] if "quadrant" in b else b.iloc[0:0]
        return list(zip(b.get("percent_of_network", []), b.get("time_seconds", [])))
    if multi:
        quads = sorted({str(q) for w in wells if "quadrant" in bursts[w]
                        for q in bursts[w]["quadrant"]}) or ["1"]
        layout_rows = []
        for q in quads:
            layout_rows.append(("header", q, None))
            n_q = max(len(events_of(w, q)) for w in wells)
            layout_rows += [("event", q, k) for k in range(max(n_q, 1))]
    else:
        n_max = max(len(bursts[w]) for w in wells)
        layout_rows = [("event", None, k) for k in range(max(n_max, 1))]
    first_ev, last_ev = 5, 4 + len(layout_rows)
    cell(ge, 3, 1, "Total group events in the well (quadrants used)" if multi
         else "Total group events (network bursts)", bold=True)
    cell(ge, 4, 1, "percent_of_network, per event (and when it happened):", bold=True,
         fill="F2F2F2")
    for rr, (kind_r, q, k) in enumerate(layout_rows, first_ev):
        if kind_r == "header":
            cell(ge, rr, 1, f"Quadrant {q} (_s{q})", bold=True, fill="F2F2F2")
        else:
            cell(ge, rr, 1, f"  burst {k + 1}" if multi else f"Event {k + 1}")
    avg_row = last_ev + 1
    cell(ge, avg_row, 1, "Average percent_of_network", bold=True)
    for i, (kind, g, w) in enumerate(plan):
        c = 2 + i
        L = get_column_letter(c)
        cell(ge, 4, c, fill="F2F2F2")
        if kind == "well":
            if multi and not n_sync[w]:
                cell(ge, 3, c, "n/a", bold=True, align="right", color="808080")
            else:
                cell(ge, 3, c, f"=COUNT({L}{first_ev}:{L}{last_ev})", fmt="0", bold=True,
                     align="right")
            for rr, (kind_r, q, k) in enumerate(layout_rows, first_ev):
                if kind_r == "header":
                    cell(ge, rr, c, fill="F2F2F2")
                    continue
                ev = events_of(w, q)
                if k < len(ev) and pd.notna(ev[k][0]):
                    pct_v, t = ev[k]
                    # The time rides in the number format, so the cell stays a plain number
                    # that COUNT / AVERAGE (and copy-paste into Prism) still read.
                    tag = f' "at {float(t):.1f} s"' if pd.notna(t) else ""
                    cell(ge, rr, c, float(pct_v) / 100.0, fmt=f"0.0%{tag}", align="right")
                else:
                    cell(ge, rr, c, None)
            cell(ge, avg_row, c, f'=IFERROR(AVERAGE({L}{first_ev}:{L}{last_ev}),"none")',
                 fmt="0.0%", bold=True, align="right")
        else:
            for rr, f in ((3, "0.0"), (avg_row, "0.0%")):
                cell(ge, rr, c, stat_formula(kind, rr, plan, i), fmt=f, italic=True,
                     fill=fills[g], align="right")
            for rr in range(first_ev, last_ev + 1):
                cell(ge, rr, c, fill=fills[g])
    cell(ge, avg_row + 2, 1,
         "percent_of_network = share of the active cells (of that quadrant, on quadrant plates) "
         "that fired together at the burst peak; 'at N s' = when in that movie it happened. "
         "Blank = fewer events. The group mean of 'Average percent_of_network' covers only wells "
         "that had at least one event.", italic=True, border=False)
    if multi:
        cell(ge, avg_row + 3, 1,
             f"Rows are grouped by quadrant; only quadrants with >= {args.min_active} active cells "
             "are used. Quadrants were filmed one after another, so bursts in different quadrants "
             "are separate events and are never lined up by time. Wells differ in how many quadrants were "
             "usable (Key Numbers, '...measured from how many cells'), so for comparing wells use "
             "'Network bursts (per 3-min quadrant)' on Key Numbers.", italic=True, border=False)

    # ------------------------------------------------------------ Statistics + Graphs
    gw = {g: [w for k, gg, w in plan if k == "well" and gg == g] for g in groups}
    tests = statistics_sheet(book, plan, groups, gw, key_rows)
    graph_dir = out.parent / f"{pname}_graphs"
    pngs = make_graphs(graph_dir, pname, groups, gw, key_rows, tests)
    gs = book.create_sheet("Graphs")
    cell(gs, 1, 1, f"One graph per key number. Each dot is one well; bar = mean, whiskers = SD. "
                   f"p = Welch's t-test (see Statistics). PNG copies: {graph_dir.name}/",
         italic=True, border=False)
    for i, png in enumerate(pngs):
        img = XLImage(str(png))
        img.width, img.height = 360, 360
        gs.add_image(img, f"{get_column_letter(1 + (i % 4) * 6)}{3 + (i // 4) * 19}")

    # ------------------------------------------------------------ Notes
    nt = book.create_sheet("Notes")
    rows = [("Plate", pname),
            ("Made", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Plate map (from the user)",
             "; ".join(f"{g} = wells in column {', '.join(c)}" for g, c in groups.items())),
            ("Wells included", ", ".join(wells)),
            ("Wells found but not in the plate map", ", ".join(unmapped) or "none"),
            ("Recording", "every well 3.0 min at 10 Hz (so recording length is left out)"),
            ("Caveat",
             "At 10 Hz, CASCADE-based activity numbers (% active, firing rates) depend on the "
             "spike model; synchrony and burst results are robust to it."),
            ("", ""),
            ("Well", "event source | cascade model | pipeline_fixes hash | template hash | generated")]
    rows += [(w, " | ".join(prov[w][k] for k in ("event_source", "cascade_model",
                                                   "pipeline_fixes_sha256_12",
                                                   "template_sha256_12", "generated")))
             for w in wells]
    for i, (a, b) in enumerate(rows, 1):
        cell(nt, i, 1, a, bold=True, border=False)
        cell(nt, i, 2, b, border=False)
    if multi:
        ps = book.create_sheet("Quadrants", index=len(book.sheetnames) - 1)
        r0 = 1
        hdr = ["Quadrant", "Cells tracked", "Active cells", "Used for activity",
               f"Used for synchrony/bursts (>= {args.min_active} active)", "Why not"]
        for c, h in enumerate(hdr, 1):
            cell(ps, r0, c, h, bold=True, fill="D9D9D9")
        for i, row in enumerate(pos_rows, 1):
            for c, v in enumerate(row, 1):
                cell(ps, r0 + i, c, v, color="808080" if row[3] == "no" else None)
        for c, wdt in zip("ABCDEF", (12, 14, 13, 18, 38, 34)):
            ps.column_dimensions[c].width = wdt
        ps.freeze_panes = "A2"
    versions = {(v["pipeline_fixes_sha256_12"], v["template_sha256_12"]) for v in prov_rec.values()}
    if len(versions) > 1:
        cell(nt, len(rows) + 2, 1, "WARNING", bold=True, color="FF0000", border=False)
        cell(nt, len(rows) + 2, 2, "Wells were made by different code versions - do not "
                                   "compare them until all are re-run.", color="FF0000",
             border=False)

    # ------------------------------------------------------------ widths, panes
    for sh in (ws, ge):
        sh.column_dimensions["A"].width = 44
        for c in range(2, 2 + len(plan)):
            sh.column_dimensions[get_column_letter(c)].width = 10
        sh.freeze_panes = "B3"
    for i, (kind, _g, _w) in enumerate(plan):   # room for "73.1% at 37.6 s"
        if kind == "well":
            ge.column_dimensions[get_column_letter(2 + i)].width = 17
    ws.column_dimensions[get_column_letter(note_col)].width = 90
    nt.column_dimensions["A"].width = 36
    nt.column_dimensions["B"].width = 110

    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)
    print(f"Wrote {out}")
    print(f"  groups: " + ", ".join(f"{g}: {[w for k, gg, w in plan if k == 'well' and gg == g]}"
                                   for g in groups))
    if unmapped:
        print(f"  NOT in the plate map (left out): {unmapped}")
    if len(versions) > 1:
        print("  WARNING: wells were made by different code versions")


if __name__ == "__main__":
    main()
