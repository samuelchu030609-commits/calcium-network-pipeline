#!/usr/bin/env python
"""Stage 1b: choose which Suite2p ROIs count as cells by SIZE, not by Suite2p's classifier.

    python apply_cell_rule.py <plane0> [<plane0> ...]            # apply the rule
    python apply_cell_rule.py <plane0> --dry-run                  # report only, write nothing
    python apply_cell_rule.py <plane0> --tif <recording.tif>      # TIF not found via db.npy
    python apply_cell_rule.py <plane0> --revert                   # put Suite2p's labels back

Runs in the suite2p env (needs numpy + tifffile only), after batch_suite2p.py and before
run_cascade.py. Adopted 2026-10-10 from _review_20x_2026-10-09/REVIEW_20x_detection.md
("Solution 1").

THE RULE. A Suite2p ROI is a cell when its equivalent diameter -- the diameter of a circle
with the ROI's area, 2*sqrt(npix/pi) * um_per_px -- is at least 8 um. Every other ROI
Cellpose drew is kept as a cell. The same rule in micrometres applies at every magnification.

WHY NOT SUITE2P'S CLASSIFIER. On this data it is uninformative and it is buggy:
  * At 20x it separates 10x-confirmed cells from other ROIs no better than chance (AUC 0.49
    over 16 wells); at 10x, ROIs it rejected are found again at 20x about as often as ROIs it
    kept (76% vs 79%).
  * One of its three inputs, npix_norm, is ROI area divided by the MEDIAN ROI area of the same
    recording, so "too big" means bigger than this field's typical ROI, not big for a neuron.
  * Its skew lookup has an off-by-one: any skew below the table's lowest bin (-1.29) indexes
    bin -1, i.e. the MOST cell-like bin. A dark final frame drives every ROI's skew far below
    that, so in recordings ending on a truncated frame it keeps ~2x as many ROIs (78% vs 40%
    of ROIs in clean wells).
  * Setting use_builtin_classifier=False does not switch it off -- it only picks which
    classifier file loads -- and Suite2p 1.0 has no setting that skips classification.
The 8 um floor removed 73 of 1211 20x ROIs in the review, 2 of which matched a 10x cell, and
kept 99.6% of 10x-confirmed and of activity-confirmed cells; a 10 um floor starts discarding
real cells (97.1% / 94.8%).

WHAT IT WRITES, per plane0 folder:
  iscell_suite2p.npy  Suite2p's original labels -- written ONCE, never overwritten. If it is
                      missing but cell_rule.json exists, iscell.npy may already hold the rule,
                      so the script refuses rather than back up the wrong file.
  iscell.npy          column 0 = 1.0 if diameter >= floor else 0.0; column 1 = the same value
                      (the rule is deterministic, so the "probability" column carries no
                      extra information; nothing in the pipeline reads it).
  cell_rule.json      the rule, the pixel size and where it came from, counts, the script's
                      sha256, and what was moved aside. Its modification time is what
                      run_plate.sh compares against PROVENANCE to know stage 3 is stale.
  _stale_pre_cell_rule/  only if the cell list CHANGED and CASCADE output was present:
                      cascade_spike_prob.npy + cascade_meta.json are MOVED here (not deleted).
                      Their rows are in the OLD iscell order: left in place, the notebook would
                      either silently fall back to dF/F0 (row count differs) or, if the counts
                      happened to match, pair every spike train with the wrong cell.
After a change, stages 2 and 3 MUST be re-run for that recording (run_plate.sh does it).

Running it again on a folder that already has the rule is a no-op (same labels -> nothing
written, nothing moved). Raw TIFs and the native plane0 arrays are never modified.

PIXEL SIZE comes from the recording's own TIF -- MetaMorph's spatial-calibration-x, in um,
calibration on -- located through Suite2p's db.npy (file_list). It is never guessed: no TIF
and no --um-per-px means a hard failure. 10x Plan Apo = 1.3656 um/px, 20x Water Apo = 0.685.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

MIN_DIAMETER_UM = 8.0
STALE_DIR = "_stale_pre_cell_rule"
CASCADE_FILES = ("cascade_spike_prob.npy", "cascade_meta.json")
RULE_NAME = "equivalent_diameter_um >= min_diameter_um (Suite2p classifier ignored)"


# ---------------------------------------------------------------------------- pixel size
def _prop(desc, name):
    m = re.search(r'<prop id="%s"[^>]*value="([^"]*)"' % re.escape(name), desc)
    return m.group(1) if m else None


def pixel_size_from_tif(tif):
    """(um_per_px, details) from MetaMorph's ImageDescription on the TIF's first page.

    Requires spatial-calibration-x, units 'um', and calibration not switched off. x and y
    must agree within 1% -- the rule uses x, and a non-square pixel would make a circular
    'equivalent diameter' meaningless."""
    import tifffile

    with tifffile.TiffFile(str(tif)) as tf:
        desc = tf.pages[0].description or ""
    x, y = _prop(desc, "spatial-calibration-x"), _prop(desc, "spatial-calibration-y")
    units, state = _prop(desc, "spatial-calibration-units"), _prop(desc, "spatial-calibration-state")
    if x is None:
        raise ValueError(f"{tif}: no spatial-calibration-x in the TIF metadata")
    if units is not None and units.strip().lower() not in ("um", "µm", "micron", "microns"):
        raise ValueError(f"{tif}: spatial-calibration-units is {units!r}, expected um")
    if state is not None and state.strip().lower() in ("off", "false", "0"):
        raise ValueError(f"{tif}: spatial calibration is switched off in the metadata")
    um = float(x)
    if not (np.isfinite(um) and um > 0):
        raise ValueError(f"{tif}: spatial-calibration-x = {x!r} is not a positive number")
    if y is not None and abs(float(y) - um) > 0.01 * um:
        raise ValueError(f"{tif}: non-square pixels (x={x}, y={y})")
    return um, dict(tif=str(tif), spatial_calibration_x=um, spatial_calibration_y=None if y is None else float(y),
                    units=units, magnification=_prop(desc, "_MagSetting_"))


def find_tif(plane0):
    """The recording's TIF, in this order:
      1. plane0/frame_trim.json raw_tifs -- when batch_suite2p dropped dark frames, db.npy
         names the deleted trimmed copy, not the raw TIF;
      2. Suite2p's db.npy file_list (plane0/ first, then suite2p/), as recorded;
      3. the same file NAME in the recording folder or the plate folder above it, for
         results whose folders were moved or renamed after Suite2p ran (2354's plate folder,
         the old 'Summer Research' paths). Only the recording's own ancestry is searched."""
    names = []
    trim_p = plane0 / "frame_trim.json"
    if trim_p.is_file():
        raw = json.loads(trim_p.read_text()).get("raw_tifs") or []
        for f in raw:
            if Path(f).is_file():
                return Path(f)
        names += [Path(f).name for f in raw]
    db_path = next((p for p in (plane0 / "db.npy", plane0.parent / "db.npy") if p.is_file()), None)
    if db_path is not None:
        db = np.load(db_path, allow_pickle=True).item()
        data_path = (db.get("data_path") or [""])[0]
        for f in db.get("file_list") or []:
            p = Path(os.path.join(data_path, f))       # Suite2p joins the same way
            if p.is_file():
                return p
            names.append(p.name)
    for folder in list(plane0.parents)[1:3]:                  # <rec>/suite2p/plane0 -> <rec>, <plate>
        for n in names:
            if (folder / n).is_file():
                return folder / n
    if not names:
        raise FileNotFoundError(f"no db.npy in {plane0} or its parent -- pass --tif or --um-per-px")
    raise FileNotFoundError(f"{plane0}: the recording's file ({names[0]}) is not at its recorded "
                            f"path, in the recording folder or in the plate folder (drive not "
                            f"mounted?) -- pass --tif or --um-per-px")


# ---------------------------------------------------------------------------- the rule
def equivalent_diameter_um(stat, um_per_px):
    npix = np.array([len(s["ypix"]) for s in stat], dtype=float)
    return 2.0 * np.sqrt(npix / np.pi) * float(um_per_px)


def _sha12(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def _atomic_save_npy(path, arr):
    tmp = path.with_name(path.stem + ".tmp.npy")
    np.save(tmp, arr)
    os.replace(tmp, path)


def _recorded_settings_match(rec_p, min_diameter_um, um_per_px):
    """True when cell_rule.json exists and records this floor and pixel size."""
    if not rec_p.is_file():
        return False
    try:
        rec = json.loads(rec_p.read_text())
        return (abs(float(rec["min_diameter_um"]) - float(min_diameter_um)) < 1e-9
                and abs(float(rec["um_per_px"]) - float(um_per_px)) < 1e-9)
    except (ValueError, KeyError, TypeError):
        return False


def apply_cell_rule(plane0, tif=None, um_per_px=None, min_diameter_um=MIN_DIAMETER_UM,
                    dry_run=False):
    """Apply the size rule to one suite2p/plane0 folder. Returns a summary dict.

    Raises on anything that would make the result untrustworthy (missing pixel size,
    stat/iscell length mismatch, a backup that may be the wrong file)."""
    plane0 = Path(plane0).expanduser().resolve()
    stat_p, isc_p = plane0 / "stat.npy", plane0 / "iscell.npy"
    bak_p, rec_p = plane0 / "iscell_suite2p.npy", plane0 / "cell_rule.json"
    for p in (stat_p, isc_p):
        if not p.is_file():
            raise FileNotFoundError(f"{p} missing -- is this a finished Suite2p plane0 folder?")

    if bak_p.is_file():
        original = np.load(bak_p)
    elif rec_p.is_file():
        raise RuntimeError(f"{plane0}: cell_rule.json exists but iscell_suite2p.npy does not -- "
                           f"iscell.npy may already hold the rule, so it cannot serve as the "
                           f"backup of Suite2p's labels. Restore iscell_suite2p.npy first.")
    else:
        original = None                                   # iscell.npy IS Suite2p's output

    stat = np.load(stat_p, allow_pickle=True)
    current = np.load(isc_p)
    if current.ndim != 2 or current.shape[0] != len(stat):
        raise ValueError(f"{plane0}: iscell.npy has shape {current.shape} but stat.npy has "
                         f"{len(stat)} ROIs")
    suite2p_labels = original if original is not None else current

    if um_per_px is not None:
        um, cal = float(um_per_px), dict(source="--um-per-px override")
        if not (np.isfinite(um) and um > 0):
            raise ValueError(f"--um-per-px {um_per_px!r} is not a positive number")
    else:
        um, cal = pixel_size_from_tif(Path(tif) if tif else find_tif(plane0))
        cal["source"] = "TIF spatial-calibration-x"

    diam = equivalent_diameter_um(stat, um)
    keep = diam >= float(min_diameter_um)
    new = np.column_stack([keep, keep]).astype(np.float64)
    changed = not np.array_equal(current[:, 0] > 0, keep)

    s = dict(plane0=str(plane0), n_rois=int(len(stat)), n_cells_rule=int(keep.sum()),
             n_below_floor=int((~keep).sum()),
             n_cells_suite2p_classifier=int((suite2p_labels[:, 0] > 0).sum()),
             um_per_px=um, min_diameter_um=float(min_diameter_um),
             median_diameter_um=round(float(np.median(diam)), 2) if len(diam) else None,
             changed=bool(changed), moved_aside=[])
    # Nothing to do only when the labels already match AND the rule is on record with these
    # same settings. (If Suite2p's own labels happened to equal the rule, the first run still
    # writes the backup and cell_rule.json, so the folder is recognisably "rule applied". A
    # new floor or pixel size that happens to keep the same ROIs still rewrites the record,
    # so cell_rule.json always states the settings the current labels came from.)
    if dry_run or (not changed and _recorded_settings_match(rec_p, min_diameter_um, um)):
        s["action"] = "dry run - nothing written" if dry_run else "already applied - nothing written"
        return s

    if original is None:                                  # first time: keep Suite2p's labels
        shutil.copy2(isc_p, bak_p)
        if not np.array_equal(np.load(bak_p), current):
            raise RuntimeError(f"{bak_p}: backup does not read back identical -- stopping")
    if changed:
        _atomic_save_npy(isc_p, new)

    present = [f for f in CASCADE_FILES if (plane0 / f).exists()] if changed else []
    if present:
        stale = plane0 / STALE_DIR
        stale.mkdir(exist_ok=True)
        for f in present:
            dst = stale / f
            if dst.exists():                              # an older stale copy: keep both
                dst = stale / f"{Path(f).stem}.{time.strftime('%Y%m%d_%H%M%S')}{Path(f).suffix}"
            os.replace(plane0 / f, dst)
            s["moved_aside"].append(str(dst.relative_to(plane0)))

    rec = dict(rule=RULE_NAME, min_diameter_um=float(min_diameter_um), um_per_px=um,
               calibration=cal, n_rois=s["n_rois"], n_cells=s["n_cells_rule"],
               n_below_floor=s["n_below_floor"],
               n_cells_suite2p_classifier=s["n_cells_suite2p_classifier"],
               iscell_sha256_12=_sha12(isc_p), suite2p_backup="iscell_suite2p.npy",
               moved_aside=s["moved_aside"], script="apply_cell_rule.py",
               script_sha256_12=_sha12(__file__), applied=time.strftime("%Y-%m-%dT%H:%M:%S"),
               reference="_review_20x_2026-10-09/REVIEW_20x_detection.md")
    tmp = rec_p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1))
    os.replace(tmp, rec_p)
    s["action"] = "rule applied" + ("; stale CASCADE output moved aside" if present else "")
    return s


def revert_cell_rule(plane0):
    """Put Suite2p's labels back. CASCADE output moved aside is restored only if no newer
    CASCADE output has been written since; otherwise stage 2 must be re-run."""
    plane0 = Path(plane0).expanduser().resolve()
    bak_p, isc_p, rec_p = plane0 / "iscell_suite2p.npy", plane0 / "iscell.npy", plane0 / "cell_rule.json"
    if not bak_p.is_file():
        raise FileNotFoundError(f"{bak_p} missing -- nothing to revert to")
    _atomic_save_npy(isc_p, np.load(bak_p))
    if rec_p.is_file():
        os.replace(rec_p, plane0 / f"cell_rule.reverted_{time.strftime('%Y%m%d_%H%M%S')}.json")
    restored, stale = [], plane0 / STALE_DIR
    if stale.is_dir() and not any((plane0 / f).exists() for f in CASCADE_FILES):
        for f in CASCADE_FILES:
            if (stale / f).exists():
                os.replace(stale / f, plane0 / f)
                restored.append(f)
    return dict(plane0=str(plane0), action="reverted to Suite2p labels", restored=restored,
                note="" if restored else "re-run stage 2 (CASCADE) and 3 for this recording")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plane0", nargs="+", help="suite2p/plane0 folder(s)")
    ap.add_argument("--tif", default=None, help="the recording's TIF, if db.npy can't find it "
                                                "(only with a single plane0)")
    ap.add_argument("--um-per-px", type=float, default=None,
                    help="pixel size override; use ONLY when no TIF exists (e.g. folder 1, "
                         "an mp4 recording) and say where the number came from")
    ap.add_argument("--min-diameter-um", type=float, default=MIN_DIAMETER_UM,
                    help=f"size floor (default {MIN_DIAMETER_UM:g}; changing it changes results)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--revert", action="store_true", help="restore Suite2p's labels")
    a = ap.parse_args()
    if a.tif and len(a.plane0) > 1:
        sys.exit("--tif applies to one recording; give one plane0 folder with it.")

    failed = 0
    for p in a.plane0:
        try:
            s = revert_cell_rule(p) if a.revert else apply_cell_rule(
                p, tif=a.tif, um_per_px=a.um_per_px, min_diameter_um=a.min_diameter_um,
                dry_run=a.dry_run)
        except Exception as e:                            # one bad folder must not stop the rest
            failed += 1
            print(f"FAILED {p}: {e}", flush=True)
            continue
        if a.revert:
            print(f"{s['action']}: {s['plane0']}  {s['restored'] or s['note']}", flush=True)
        else:
            print(f"{s['action']}: {s['plane0']}\n"
                  f"   {s['n_cells_rule']}/{s['n_rois']} ROIs >= {s['min_diameter_um']:g} um "
                  f"(Suite2p classifier kept {s['n_cells_suite2p_classifier']}); "
                  f"{s['um_per_px']:g} um/px; median diameter {s['median_diameter_um']} um"
                  + (f"\n   moved aside: {', '.join(s['moved_aside'])} -> re-run stages 2 and 3"
                     if s["moved_aside"] else ""), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
