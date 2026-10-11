"""Synthetic-data tests for stage 1b (apply_cell_rule.py) and dark-tail trimming
(batch_suite2p.find_dark_tail / write_trimmed_copy). Touches NO real recording: every file
is generated in a temporary folder. Expected values are fixed in the asserts beforehand.

    python tests/test_stage1b.py        # suite2p env; prints ALL PASSED or raises
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import tifffile

REPO = Path(__file__).resolve().parents[1]
# lab repo: scripts at the top; iNeuron-NetSync: scripts in tools/. Same file in both.
sys.path[:0] = [str(REPO / "tools"), str(REPO)]
import apply_cell_rule as acr          # noqa: E402
import batch_suite2p as bs             # noqa: E402

UM = 0.685


def mm_desc(x=UM, y=UM, units="um", state="on"):
    """A MetaMorph-style ImageDescription with the props apply_cell_rule reads."""
    p = [f'<prop id="spatial-calibration-x" type="float" value="{x}"/>',
         f'<prop id="spatial-calibration-y" type="float" value="{y}"/>',
         f'<prop id="spatial-calibration-units" type="string" value="{units}"/>',
         f'<prop id="spatial-calibration-state" type="bool" value="{state}"/>',
         '<prop id="_MagSetting_" type="string" value="20X synthetic"/>']
    return "<MetaData>" + "".join(p) + "</MetaData>"


def make_plane0(root, diam_um, labels, desc=None, cascade=True):
    """plane0 with one ROI per requested diameter (npix rounded), db.npy -> a 1-page TIF."""
    tif = root / "rec.tif"
    if desc is not False:
        tifffile.imwrite(tif, np.zeros((8, 8), np.uint16), description=desc or mm_desc())
    p0 = root / "rec" / "suite2p" / "plane0"
    p0.mkdir(parents=True)
    stat = []
    for d in diam_um:
        n = int(round(np.pi * (d / 2 / UM) ** 2))
        stat.append(dict(ypix=np.zeros(n, int), xpix=np.arange(n)))
    np.save(p0 / "stat.npy", np.array(stat, dtype=object), allow_pickle=True)
    isc = np.column_stack([labels, np.linspace(0.1, 0.9, len(labels))]).astype(float)
    np.save(p0 / "iscell.npy", isc)
    np.save(p0 / "db.npy", dict(data_path=[str(root)], file_list=[str(tif)]), allow_pickle=True)
    if cascade:
        np.save(p0 / "cascade_spike_prob.npy", np.ones((int(np.sum(labels)), 10), np.float32))
        (p0 / "cascade_meta.json").write_text('{"n_cells": %d}' % int(np.sum(labels)))
    return p0, isc


def test_cell_rule():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        diam = [5.0, 7.9, 8.3, 12.0, 20.0]           # floor 8 um -> last three are cells
        p0, orig = make_plane0(root, diam, [1, 1, 0, 0, 1])
        real = acr.equivalent_diameter_um(np.load(p0 / "stat.npy", allow_pickle=True), UM)
        assert list(real >= 8) == [False, False, True, True, True], real

        s = acr.apply_cell_rule(p0)
        assert s["n_cells_rule"] == 3 and s["n_cells_suite2p_classifier"] == 3 and s["changed"]
        assert s["um_per_px"] == UM
        new = np.load(p0 / "iscell.npy")
        assert new.tolist() == [[0, 0], [0, 0], [1, 1], [1, 1], [1, 1]], new
        assert np.array_equal(np.load(p0 / "iscell_suite2p.npy"), orig)   # backup = Suite2p
        assert not (p0 / "cascade_spike_prob.npy").exists()               # stale rows moved
        assert (p0 / acr.STALE_DIR / "cascade_spike_prob.npy").exists()
        rec = json.loads((p0 / "cell_rule.json").read_text())
        assert rec["n_cells"] == 3 and rec["calibration"]["source"] == "TIF spatial-calibration-x"

        # idempotent: second run writes nothing, moves nothing, keeps the backup
        mt = (p0 / "cell_rule.json").stat().st_mtime_ns
        s2 = acr.apply_cell_rule(p0)
        assert not s2["changed"] and s2["action"].startswith("already applied")
        assert (p0 / "cell_rule.json").stat().st_mtime_ns == mt
        assert np.array_equal(np.load(p0 / "iscell_suite2p.npy"), orig)

        # a new CASCADE run, then a re-run of the rule: still a no-op, CASCADE untouched
        np.save(p0 / "cascade_spike_prob.npy", np.ones((3, 10), np.float32))
        acr.apply_cell_rule(p0)
        assert (p0 / "cascade_spike_prob.npy").exists()

        # revert: Suite2p labels back; CASCADE NOT swapped back because a newer one exists
        r = acr.revert_cell_rule(p0)
        assert np.array_equal(np.load(p0 / "iscell.npy"), orig) and r["restored"] == []
        assert not (p0 / "cell_rule.json").exists()

        # backup missing but rule on record -> refuse (iscell may already be the rule)
        acr.apply_cell_rule(p0)
        (p0 / "iscell_suite2p.npy").unlink()
        try:
            acr.apply_cell_rule(p0)
            raise AssertionError("should refuse without the backup")
        except RuntimeError:
            pass


def test_pixel_size_never_guessed():
    for desc, why in ((False, "no TIF"), ("<MetaData/>", "no calibration"),
                      (mm_desc(units="pixel"), "units"), (mm_desc(state="off"), "state off"),
                      (mm_desc(x=0.685, y=0.80), "non-square")):
        with tempfile.TemporaryDirectory() as t:
            p0, orig = make_plane0(Path(t), [5.0, 12.0], [1, 0], desc=desc)
            try:
                acr.apply_cell_rule(p0)
                raise AssertionError(f"{why}: should have failed")
            except (ValueError, FileNotFoundError):
                pass
            # nothing was written on failure
            assert np.array_equal(np.load(p0 / "iscell.npy"), orig), why
            assert not (p0 / "iscell_suite2p.npy").exists() and not (p0 / "cell_rule.json").exists()
            assert (p0 / "cascade_spike_prob.npy").exists(), why
    # explicit override works without any TIF
    with tempfile.TemporaryDirectory() as t:
        p0, _ = make_plane0(Path(t), [5.0, 12.0], [1, 0], desc=False)
        assert acr.apply_cell_rule(p0, um_per_px=UM)["n_cells_rule"] == 1


def test_labels_already_equal_rule():
    with tempfile.TemporaryDirectory() as t:
        p0, orig = make_plane0(Path(t), [5.0, 12.0], [0, 1])
        s = acr.apply_cell_rule(p0)
        assert not s["changed"] and (p0 / "cell_rule.json").exists()
        assert (p0 / "iscell_suite2p.npy").exists()
        assert np.array_equal(np.load(p0 / "iscell.npy"), orig)      # labels untouched
        assert (p0 / "cascade_spike_prob.npy").exists()              # same cells -> not stale


def test_new_floor_same_cells_rewrites_record():
    """A changed floor that keeps the same ROIs must still update cell_rule.json, which
    must always state the settings the current labels came from."""
    with tempfile.TemporaryDirectory() as t:
        p0, _ = make_plane0(Path(t), [5.0, 12.0], [1, 0])
        acr.apply_cell_rule(p0)
        labels = np.load(p0 / "iscell.npy")
        s = acr.apply_cell_rule(p0, min_diameter_um=9.0)          # 12 um still >= 9, 5 still <
        assert not s["changed"] and s["action"] == "rule applied", s
        assert json.loads((p0 / "cell_rule.json").read_text())["min_diameter_um"] == 9.0
        assert np.array_equal(np.load(p0 / "iscell.npy"), labels)
        s = acr.apply_cell_rule(p0, min_diameter_um=9.0)          # now on record -> no-op
        assert s["action"].startswith("already applied"), s


def movie(path, levels, rng):
    fr = np.stack([np.clip(rng.normal(1000 * v, 5, (16, 16)), 0, None) for v in levels])
    tifffile.imwrite(path, fr.astype(np.uint16))


def test_dark_tail():
    rng = np.random.default_rng(0)
    flat = [1.0] * 100
    cases = {
        "clean": (flat, 0),
        "one truncated frame (B05-like)": (flat[:-1] + [0.28], 1),
        "three, first partial (B08-like)": (flat[:-3] + [0.85, 0.18, 0.18], 3),
        "slow bleach crosses 0.9 for 20 frames (2167-like)": (list(np.linspace(1.2, 0.85, 100)), 0),
        "fade where only the last 2 dip below 0.9 (abrupt guard)":
            (flat[:-12] + list(np.linspace(1.0, 0.88, 12)), 0),
        "too many dark frames": (flat[:-8] + [0.2] * 8, 0),
    }
    # which rule must decide each case -- so a pass cannot come from the wrong branch
    why = {"clean": "no dark", "one truncated frame (B05-like)": "dropped 1",
           "three, first partial (B08-like)": "dropped 3",
           "slow bleach crosses 0.9 for 20 frames (2167-like)": "more than",
           "fade where only the last 2 dip below 0.9 (abrupt guard)": "fade gradually",
           "too many dark frames": "more than"}
    with tempfile.TemporaryDirectory() as t:
        for name, (lv, want) in cases.items():
            f = Path(t) / "m.tif"
            movie(f, lv, rng)
            k, info = bs.find_dark_tail([f])
            assert k == want and why[name] in info["reason"], (name, k, info)
        # split recording: dark tail in the last part; trimmed copy keeps exactly n - k pages
        a, b = Path(t) / "r.tif", Path(t) / "r-file002.tif"
        movie(a, flat[:60], rng)
        movie(b, flat[:38] + [0.2, 0.2], rng)
        k, info = bs.find_dark_tail([a, b])
        assert k == 2 and info["n_frames_tif"] == 100, info
        out = Path(t) / "scratch" / "_trimmed_input" / b.name
        bs.write_trimmed_copy(b, out, bs.len_pages(b) - k)
        src, cp = tifffile.imread(b), tifffile.imread(out)
        assert cp.shape == (38, 16, 16) and np.array_equal(cp, src[:38])
        assert tifffile.imread(b).shape[0] == 40                       # raw untouched


if __name__ == "__main__":
    for fn in (test_cell_rule, test_pixel_size_never_guessed, test_labels_already_equal_rule,
               test_new_floor_same_cells_rewrites_record, test_dark_tail):
        fn()
        print("ok", fn.__name__)
    print("ALL PASSED")
