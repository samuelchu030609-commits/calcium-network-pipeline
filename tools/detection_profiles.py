"""Cell-detection profiles: named, saved sets of the Suite2p/Cellpose settings that
decide which cells are found.

A lab makes one profile per cell line and microscope set-up, checks it with the
preview (tools/preview_detection.py), and then uses it unchanged for a whole
experiment, so every recording is detected the same way.

  * Built-in profiles ship with the code in settings/detection_profiles/ and are
    read-only. "Lippmann iNeurons, 10X" is the locked recipe the reference results
    were produced with, and the default.
  * A lab's own profiles live OUTSIDE the code, in <install>/profiles/, so updating
    the program never deletes them.

A profile is a small JSON file:
    {"name": "...", "cell_size": 12, "cell_size_unit": "px" | "um",
     "cellprob_threshold": 0.0, "flow_threshold": 0.4, "image": "meanImg",
     "min_cell_diameter_um": 8.0, "um_per_px": null, "notes": "..."}

The first five settings decide what Cellpose OUTLINES (stage 1). The last two decide
which outlines COUNT AS CELLS (stage 1b, tools/apply_cell_rule.py): every outline at
least min_cell_diameter_um across (the diameter of a circle of the same area), and
nothing else -- Suite2p's own cell classifier is not used. um_per_px is needed only
for TIFs that do not record their pixel size; a pixel size stored in the TIF always
wins. Profiles saved before the cell filter existed load with the 8 um default.

Pure standard library: used by the GUI and by analyze_folder.py in different
environments.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILTIN_DIR = REPO / "settings" / "detection_profiles"
DEFAULT_NAME = "Lippmann iNeurons, 10X"

IMAGES = {
    "meanImg": "Average image (finds quiet cells too)",
    "max_proj": "Brightest moments (max projection; favours active cells)",
    "max_proj / meanImg": "Brightest moments relative to the average (Suite2p's default)",
}
# Allowed ranges: wide enough for any sensible use, narrow enough to catch typos.
LIMITS = {"cell_size_px": (3.0, 200.0), "cell_size_um": (2.0, 300.0),
          "cellprob_threshold": (-6.0, 6.0), "flow_threshold": (0.0, 3.0),
          "min_cell_diameter_um": (0.0, 100.0), "um_per_px": (0.01, 50.0)}
# The cell filter of profiles saved before it existed, and of new ones. Validated for
# iNeurons in the parent project: it removes debris and fragments while keeping 99.6% of
# confirmed cells; 10 um starts to discard real ones.
MIN_CELL_DEFAULT = 8.0


def user_dir() -> Path | None:
    """<install>/profiles, next to the install's conda folder; None outside an install."""
    base = os.environ.get("CNP_CONDA_BASE")
    return Path(base).parent / "profiles" if base else None


def validate(p: dict) -> list[str]:
    """Plain-language problems with a profile ([] if it is fine)."""
    errs = []
    if not str(p.get("name", "")).strip():
        errs.append("The profile needs a name.")
    unit = p.get("cell_size_unit")
    if unit not in ("px", "um"):
        errs.append("Cell size unit must be pixels or micrometres.")
    try:
        size = float(p.get("cell_size"))
        lo, hi = LIMITS["cell_size_um" if unit == "um" else "cell_size_px"]
        if not lo <= size <= hi:
            errs.append(f"Cell size must be between {lo:g} and {hi:g} "
                        f"{'micrometres' if unit == 'um' else 'pixels'}.")
    except (TypeError, ValueError):
        errs.append("Cell size must be a number.")
    for key, label in (("cellprob_threshold", "Cell-probability threshold"),
                       ("flow_threshold", "Shape (flow) threshold")):
        try:
            v = float(p.get(key))
            lo, hi = LIMITS[key]
            if not lo <= v <= hi:
                errs.append(f"{label} must be between {lo:g} and {hi:g}.")
        except (TypeError, ValueError):
            errs.append(f"{label} must be a number.")
    if p.get("image") not in IMAGES:
        errs.append("Unknown detection image.")
    try:
        v = float(p.get("min_cell_diameter_um", MIN_CELL_DEFAULT))
        lo, hi = LIMITS["min_cell_diameter_um"]
        if not lo <= v <= hi:
            errs.append(f"Smallest cell must be between {lo:g} and {hi:g} micrometres.")
    except (TypeError, ValueError):
        errs.append("Smallest cell must be a number.")
    if p.get("um_per_px") not in (None, "", 0, 0.0):
        try:
            v = float(p["um_per_px"])
            lo, hi = LIMITS["um_per_px"]
            if not lo <= v <= hi:
                errs.append(f"Pixel size must be between {lo:g} and {hi:g} micrometres.")
        except (TypeError, ValueError):
            errs.append("Pixel size must be a number (or left empty).")
    return errs


def _normalise(p: dict) -> dict:
    """Fill the cell-filter fields of older profiles; empty pixel size -> None."""
    p["min_cell_diameter_um"] = float(p.get("min_cell_diameter_um", MIN_CELL_DEFAULT))
    px = p.get("um_per_px")
    p["um_per_px"] = float(px) if px not in (None, "", 0, 0.0) else None
    return p


def _read(path: Path, builtin: bool) -> dict | None:
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if validate(p):
        return None
    _normalise(p)
    p["builtin"] = builtin
    p["path"] = str(path)
    return p


def load_all() -> list[dict]:
    """Built-in profiles first (the default at the very top), then the lab's own."""
    out = []
    for f in sorted(BUILTIN_DIR.glob("*.json")):
        p = _read(f, True)
        if p:
            out.append(p)
    out.sort(key=lambda p: (p["name"] != DEFAULT_NAME, p["name"].lower()))
    names = {p["name"].lower() for p in out}
    ud = user_dir()
    if ud and ud.is_dir():
        mine = [p for f in sorted(ud.glob("*.json")) if (p := _read(f, False))]
        for p in sorted(mine, key=lambda p: p["name"].lower()):
            if p["name"].lower() not in names:      # a built-in name always wins
                out.append(p)
                names.add(p["name"].lower())
    return out


def find(name_or_path: str | None) -> dict:
    """A profile by name (or by .json path); the default when None."""
    if name_or_path and name_or_path.lower().endswith(".json") and Path(name_or_path).is_file():
        p = _read(Path(name_or_path), False)
        if p is None:
            raise ValueError(f"{name_or_path} is not a valid detection profile.")
        return p
    want = (name_or_path or DEFAULT_NAME).strip().lower()
    for p in load_all():
        if p["name"].lower() == want:
            return p
    raise ValueError(f"No detection profile called '{name_or_path}'.")


def _filename(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()[:60] or "profile"
    return slug + ".json"


def save(p: dict, overwrite: bool = False) -> Path:
    """Save one of the lab's own profiles; refuses to touch built-in ones."""
    errs = validate(p)
    if errs:
        raise ValueError(" ".join(errs))
    ud = user_dir()
    if ud is None:
        raise ValueError("Profiles can only be saved in the one-click install.")
    for q in load_all():
        if q["name"].lower() == p["name"].strip().lower():
            if q["builtin"]:
                raise ValueError(f"'{q['name']}' is a built-in profile; choose another name.")
            if not overwrite:
                raise ValueError(f"A profile called '{q['name']}' already exists.")
    ud.mkdir(parents=True, exist_ok=True)
    clean = {k: p[k] for k in ("name", "cell_size", "cell_size_unit", "cellprob_threshold",
                               "flow_threshold", "image") }
    clean["name"] = clean["name"].strip()
    for k in ("cell_size", "cellprob_threshold", "flow_threshold"):
        clean[k] = float(clean[k])
    n = _normalise(dict(p))
    clean["min_cell_diameter_um"] = n["min_cell_diameter_um"]
    clean["um_per_px"] = n["um_per_px"]
    clean["notes"] = str(p.get("notes", "")).strip()
    path = ud / _filename(clean["name"])
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return path


def delete(p: dict) -> None:
    if p.get("builtin"):
        raise ValueError("Built-in profiles cannot be deleted.")
    Path(p["path"]).unlink()


def stage1_args(p: dict) -> list[str]:
    """The tools/batch_suite2p.py options that apply this profile."""
    size = ("--diameter-um" if p["cell_size_unit"] == "um" else "--diameter")
    return [size, repr(float(p["cell_size"])),
            "--cellprob-threshold", repr(float(p["cellprob_threshold"])),
            "--flow-threshold", repr(float(p["flow_threshold"])),
            "--img", p["image"], "--profile-name", p["name"]]


def stage1b_args(p: dict) -> list[str]:
    """The tools/apply_cell_rule.py options that apply this profile's cell filter.
    (Its fallback pixel size is added by the caller only when the TIF has none.)"""
    return ["--min-diameter-um", repr(float(p.get("min_cell_diameter_um", MIN_CELL_DEFAULT)))]


def describe(p: dict) -> str:
    """One line a person can read."""
    unit = "µm" if p["cell_size_unit"] == "um" else "pixels"
    floor = float(p.get("min_cell_diameter_um", MIN_CELL_DEFAULT))
    px = p.get("um_per_px")
    return (f"cells about {float(p['cell_size']):g} {unit} across · cell-probability "
            f"threshold {float(p['cellprob_threshold']):g} · shape threshold "
            f"{float(p['flow_threshold']):g} · {IMAGES[p['image']].split(' (')[0].lower()}"
            f" · counts outlines at least {floor:g} µm across as cells"
            + (f" · pixel size {float(px):g} µm if the file has none" if px else ""))
