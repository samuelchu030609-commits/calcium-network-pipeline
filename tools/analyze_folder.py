#!/usr/bin/env python
"""All three stages over a folder of microscope TIFs, in one go.

    stage 1  Suite2p   (tools/batch_suite2p.py, in the `suite2p` env)
    stage 2  CASCADE   (pipeline.run_cascade,   in the `cascade` env)  - GCaMP only
    stage 3  metrics   (pipeline.run_pipeline,  in the `analysis` env)

This is what the GUI's "Start from microscope files" mode runs, and the command
for an unattended overnight run. It is pure glue: it only calls the existing
stage scripts, each in its own environment, found by path inside the one-click
install (install/), so nothing needs `conda activate`.

For a folder <F> holding <name>.tif files it leaves:
    <F>/<ID>/suite2p/plane0/...           every stage's full output, as before
    <F>/RESULTS/<ID>_metrics.xlsx         a copy of each workbook, all in one place
    <F>/RESULTS/<ID>_baseline_qc.png      and its baseline-QC figure
    <F>/RESULTS/run_log_<time>.txt        this run's full log

Resumable: stage 1 skips recordings that already have Suite2p output, and
stages 2-3 skip recordings whose workbook already exists (use --force to redo).
One recording failing does not stop the others.

Usage (any Python of the install; the GUI uses its own):
    python tools/analyze_folder.py "<folder of TIFs>" --indicator jGCaMP8s --dry-run
    python tools/analyze_folder.py "<folder of TIFs>" --indicator jGCaMP8s
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import detection_profiles  # noqa: E402
from batch_suite2p import previous_detection, same_detection, wanted_detection  # noqa: E402

# What the user picks -> what config.json needs. Mirrors gui/app.py INDICATORS and
# pipeline/config.py ROUTE_FAMILY.
INDICATORS = {
    "jgcamp8s": {"indicator": "SRS9 jGCaMP8s", "route": "cascade_gc8s"},
    "jgcamp8f": {"indicator": "SRS10 jGCaMP8f", "route": "cascade_gc8f"},
    "fluo4": {"indicator": "Fluo-4 AM", "route": "dff"},
}


# ── Finding the install's environments ─────────────────────────────────────
def conda_base() -> Path | None:
    """Root of the conda install that holds the pipeline's environments."""
    env = os.environ.get("CNP_CONDA_BASE")
    if env:
        return Path(env)
    # Running inside one of the install's envs: <base>/envs/<name>
    prefix = Path(sys.prefix)
    if prefix.parent.name == "envs":
        return prefix.parent.parent
    return None


def env_python(base: Path, name: str) -> Path:
    if os.name == "nt":
        return base / "envs" / name / "python.exe"
    return base / "envs" / name / "bin" / "python"


def find_envs() -> dict:
    base = conda_base()
    if base is None:
        sys.exit("Could not find the pipeline's environments. Run this with a Python "
                 "from the one-click install, or set CNP_CONDA_BASE to the conda folder.")
    pys = {n: env_python(base, n) for n in ("suite2p", "cascade", "analysis")}
    missing = [f"{n} ({p})" for n, p in pys.items() if not p.is_file()]
    if missing:
        sys.exit("Missing environment(s): " + ", ".join(missing)
                 + "\nRe-run the installer (see HOW_TO_INSTALL.md).")
    return pys


# ── Keeping the computer awake ──────────────────────────────────────────────
def keep_awake() -> None:
    """Stop the computer sleeping mid-run (a whole plate can take all night)."""
    try:
        if os.name == "nt":
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif sys.platform == "darwin" and shutil.which("caffeinate"):
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    except Exception:
        pass  # a convenience only


# ── Running one step, streaming its output ─────────────────────────────────
def stream(argv, env=None, cwd=None) -> int:
    """Run argv, echoing its output line by line. Returns the exit code."""
    proc = subprocess.Popen([str(a) for a in argv], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                            encoding="utf-8", errors="replace", env=env, cwd=cwd)
    skip = 0
    for line in proc.stdout:
        # batch_suite2p ends by telling a stage-1-only user to open the GUI's batch
        # queue next; here stages 2-3 follow automatically, so that advice is wrong.
        if line.startswith("Next: launch the GUI"):
            skip = 2
        if skip:
            skip -= 1
            continue
        print(line.rstrip("\n"), flush=True)
    return proc.wait()


def read_fps(plane0: Path) -> float | None:
    """The frame rate stage 1 stored, which batch_suite2p takes from the TIF timestamps."""
    try:
        import numpy as np
        return float(np.load(plane0 / "ops.npy", allow_pickle=True).item()["fs"])
    except Exception:
        return None


def recordings(folder: Path) -> list[Path]:
    """<folder>/<ID>/ for every recording stage 1 has finished."""
    return sorted(p.parent.parent for p in folder.glob("*/suite2p/plane0")
                  if (p / "F.npy").is_file())


def detection_check(plane0: Path, profile: dict):
    """Were this recording's cells found with the chosen profile?

    Returns (expected detection settings for the run_pipeline guard, None) when yes,
    or (None, reason) when no -- e.g. stage 1 could not redo it after the profile
    changed, so its old cells must not be analysed as if they were new ones.
    """
    rec_file = plane0 / "detection_settings.json"
    size = float(profile["cell_size"])
    if rec_file.is_file():
        rec = json.loads(rec_file.read_text())
        diam = float(rec["diameter_px"])
        if profile["cell_size_unit"] == "um":
            size_ok = rec.get("um_per_px") and abs(diam * rec["um_per_px"] - size) < 1e-3
        else:
            size_ok = abs(diam - size) < 1e-6
        if not size_ok:
            return None, (f"its cells were found with a cell size of {diam:.2f} px, not the "
                          f"profile's {size:g} {'um' if profile['cell_size_unit'] == 'um' else 'px'}")
    elif profile["cell_size_unit"] == "px":
        diam = size
    else:
        return None, ("it has no record of the cell size used, so it cannot be checked "
                      "against a profile given in micrometres")
    want = wanted_detection(diam, profile["cellprob_threshold"], profile["flow_threshold"],
                            profile["image"])
    prev = previous_detection(plane0)
    if prev is not None and not same_detection(want, prev):
        return None, ("its cells were found with different detection settings than the "
                      f"profile '{profile['name']}' (stage 1 did not redo it - see above)")
    return {k: want[k] for k in ("cellpose_model", "img", "cellprob_threshold",
                                 "flow_threshold", "diameter")}, None


class Tee:
    """Send everything printed to the screen AND to the run log."""

    def __init__(self, path: Path):
        self.f = open(path, "a", encoding="utf-8")
        self.out = sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(s)

    def flush(self):
        self.out.flush()
        self.f.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="Folder holding the microscope .tif files.")
    ap.add_argument("--indicator", required=True, type=str.lower,
                    choices=sorted(INDICATORS),
                    help="jgcamp8s (SRS9), jgcamp8f (SRS10) or fluo4 (dye, no CASCADE).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Only list the recordings and their frame rates; run nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Redo recordings that are already finished.")
    ap.add_argument("--delete-bin", action="store_true",
                    help="Delete Suite2p's large data.bin (~0.6-2 GB per recording) after "
                         "each one. Saves disk space; Suite2p's GUI can then no longer "
                         "re-run detection on that recording without starting over.")
    ap.add_argument("--fps", type=float, default=None,
                    help="Frame rate for ALL recordings. Only for TIFs that carry no "
                         "timestamps (stage 1 will tell you if so).")
    ap.add_argument("--profile", default=None,
                    help="Cell-detection profile: its name, or a profile .json file. "
                         f"Default: '{detection_profiles.DEFAULT_NAME}'.")
    args = ap.parse_args()
    try:
        profile = detection_profiles.find(args.profile)
    except ValueError as e:
        sys.exit(str(e))

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")
    pys = find_envs()
    # Every stage inherits these. UTF-8 mode matters on Windows, where Python's default
    # file encoding is cp1252 and the metrics template (which contains Δ, ₀, ...) is
    # read with a plain open().
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    choice = INDICATORS[args.indicator]

    results_dir = folder / "RESULTS"
    if not args.dry_run:
        results_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        log_path = results_dir / f"run_log_{stamp}.txt"
        sys.stdout = Tee(log_path)
        keep_awake()

    print(f"Folder    : {folder}")
    print(f"Indicator : {choice['indicator']}  (route {choice['route']})")
    print(f"Detection : {profile['name']} - {detection_profiles.describe(profile)}")
    print(f"Started   : {datetime.now():%Y-%m-%d %H:%M}\n")

    # ── Stage 1: Suite2p (skips finished recordings itself) ──
    print("#" * 72)
    print("# STAGE 1 - Suite2p: motion correction + cell detection")
    print("#" * 72, flush=True)
    has_tifs = any(p.suffix.lower() in (".tif", ".tiff") and not p.name.startswith("._")
                   for p in folder.iterdir() if p.is_file())
    if has_tifs:
        s1 = [pys["suite2p"], REPO / "tools" / "batch_suite2p.py", folder]
        if args.dry_run:
            s1.append("--dry-run")
        if args.force:
            s1.append("--force")
        if args.delete_bin:
            s1.append("--delete-bin")
        if args.fps:
            s1 += ["--fps", str(args.fps)]
        s1 += detection_profiles.stage1_args(profile)
        rc1 = stream(s1)
    else:
        # Re-analysing a folder whose TIFs were moved away is fine; nothing at all is not.
        print("No .tif files directly in this folder - skipping stage 1.")
        rc1 = 0 if recordings(folder) else 1
    if args.dry_run:
        return rc1
    if rc1 != 0:
        print("\n!! Stage 1 reported problems (see above). Continuing with the "
              "recordings it finished.", flush=True)

    # ── Stages 2-3 per recording ──
    recs = recordings(folder)
    if not recs:
        print("\nNo finished Suite2p recordings to analyse. Stopping.")
        return 1

    env = os.environ.copy()
    env["PIPELINE_CASCADE_PYTHON"] = str(pys["cascade"])
    env.pop("PIPELINE_CASCADE_ENV", None)

    summary = []
    for i, rec in enumerate(recs, 1):
        rid = rec.name
        plane0 = rec / "suite2p" / "plane0"
        xlsx = plane0 / f"{rid}_metrics.xlsx"
        print("\n" + "#" * 72)
        print(f"# STAGES 2-3 [{i}/{len(recs)}] {rid}")
        print("#" * 72, flush=True)
        t0 = time.time()

        expected, why = detection_check(plane0, profile)
        if expected is None:
            print(f"!! {why}", flush=True)
            summary.append((rid, "SKIPPED: detected with other settings", 0))
            continue
        if xlsx.is_file() and not args.force:
            print("already analysed - skipped (use --force to redo)")
            status = "ok (already done)"
        else:
            # Copies from an earlier run must not outlive this one.
            for old in (f"{rid}_metrics.xlsx", f"{rid}_metrics_baseline_qc.png",
                        f"{rid}_detection_settings.json"):
                (results_dir / old).unlink(missing_ok=True)
            fps = read_fps(plane0)
            if not fps:
                summary.append((rid, "FAILED: no frame rate in ops.npy", 0))
                continue
            if choice["route"] == "cascade_gc8f" and fps < 15:
                print(f"!! WARNING: jGCaMP8f recorded at {fps:.1f} Hz. The GC8f CASCADE "
                      "model is trained at 100 Hz and under-calls badly below ~15 Hz; "
                      "consider analysing this folder as dF/F0 (--indicator fluo4 uses "
                      "the same dF/F0 path).", flush=True)
            # A stale result must not survive a re-run: remove CASCADE output so stage 2
            # recomputes (run_cascade overwrites, but be explicit when forcing).
            if args.force:
                for f in ("cascade_spike_prob.npy", "cascade_meta.json"):
                    (plane0 / f).unlink(missing_ok=True)
            cfg = {"_comment": "Written by tools/analyze_folder.py",
                   "indicator": choice["indicator"], "native_fps": fps,
                   "route": choice["route"], "neuropil_coeff": 0.7,
                   "detection_profile": profile["name"],
                   "detection_expected": expected}
            (rec / "config.json").write_text(json.dumps(cfg, indent=2))
            rc = stream([pys["analysis"], "-m", "pipeline.run_pipeline", rec],
                        env=env, cwd=REPO)
            status = "ok" if rc == 0 and xlsx.is_file() else f"FAILED (exit {rc})"

        if status.startswith("ok"):
            shutil.copy2(xlsx, results_dir / xlsx.name)
            for png in plane0.glob("*baseline_qc.png"):
                shutil.copy2(png, results_dir / png.name)
            if (plane0 / "detection_settings.json").is_file():
                shutil.copy2(plane0 / "detection_settings.json",
                             results_dir / f"{rid}_detection_settings.json")
        summary.append((rid, status, time.time() - t0))

    # ── Summary ──
    print("\n" + "=" * 72)
    print(f"SUMMARY  ({datetime.now():%Y-%m-%d %H:%M})")
    print("=" * 72)
    for rid, status, secs in summary:
        print(f"  {rid:<14} {status:<34} {secs:6.0f}s")
    n_ok = sum(s.startswith("ok") for _, s, _ in summary)
    print(f"\n{n_ok}/{len(summary)} recordings analysed.")
    print(f"Workbooks are collected in: {results_dir}")
    print(f"Full log: {log_path}", flush=True)
    if rc1 != 0 or n_ok != len(summary):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
