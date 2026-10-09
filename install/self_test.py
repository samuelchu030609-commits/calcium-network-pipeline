#!/usr/bin/env python
"""Check that an installation of the pipeline really works. Prints PASSED / FAILED.

The installers run this as their last step; you can also run it again any time
(the guide, HOW_TO_INSTALL.md, says how). It uses only synthetic data made on the
spot, so no recordings are needed, and it writes only to a temporary folder.

  Check 1  every environment has the exact package versions the reference
           numbers were produced with
  Check 2  stages 2-3 on a synthetic recording with KNOWN planted structure
           (8 co-firing cells): CASCADE must run, the co-firing must be found
           (STTC z >= 3) and at least one network burst detected
  Check 3  all three stages, starting from a small synthetic microscope movie
           (.tif): Suite2p must detect cells and a metrics workbook must appear

Run with the `analysis` environment's Python, with CNP_CONDA_BASE pointing at the
install's miniforge3 folder (the installers and launchers set this).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from analyze_folder import conda_base, env_python  # noqa: E402

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# Same pins as the installers. Cellpose runs through torch, so torch/numpy drift
# changes which cells are detected; TensorFlow 2.15 needs numpy < 2.
EXPECTED = {
    "suite2p": {"suite2p": "1.0.0.1", "cellpose": "4.1.1", "torch": "2.11.0", "numpy": "1.26.4"},
    "cascade": {"tensorflow": "2.15.1", "numpy": "1.26.4"},
    "analysis": {"numpy": "2.2.5", "pandas": "2.3.3", "scipy": "1.15.3"},
    "gui": {"streamlit": "1.63.0"},
}

VERSION_SNIPPET = r"""
import importlib, json, sys, os, warnings
warnings.filterwarnings("ignore"); os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
out = {}
for mod in sys.argv[1:]:
    try:
        m = importlib.import_module(mod)
        v = getattr(m, "__version__", None) or getattr(m, "version", None)
        out[mod] = str(v).split("+")[0]
    except Exception as e:
        out[mod] = "MISSING (" + type(e).__name__ + ")"
print(json.dumps(out))
"""

# A small fake microscope movie: 25 round "cells" (soft-edged discs, which Cellpose
# recognises; Gaussian blobs it does not) on a dim background, each with
# its own calcium transients, 400 frames. Written as a plain TIF (no timestamps).
MOVIE_SNIPPET = r"""
import sys, numpy as np, tifffile
rng = np.random.default_rng(0)
H = W = 160; T = 400
yy, xx = np.mgrid[:H, :W]
movie = np.full((T, H, W), 100.0, dtype=np.float32)
kernel = np.exp(-np.arange(30) / 5.0)
centers = [(20 + 30 * i + rng.integers(-3, 4), 20 + 30 * j + rng.integers(-3, 4))
           for i in range(5) for j in range(5)]
for cy, cx in centers:
    r = np.hypot(yy - cy, xx - cx)
    shape = 1.0 / (1.0 + np.exp((r - 6.0) / 1.0))       # soma ~12 px across
    spikes = (rng.random(T) < 0.03).astype(np.float32)
    trace = 1.0 + 1.5 * np.convolve(spikes, kernel)[:T]
    movie += 250.0 * shape[None] * trace[:, None, None]
movie += rng.normal(0, 8, movie.shape)
tifffile.imwrite(sys.argv[1], np.clip(movie, 0, 65535).astype(np.uint16))
"""


def say(msg=""):
    print(msg, flush=True)


def check_versions(base: Path) -> bool:
    say("Check 1/3  package versions")
    good = True
    for env, want in EXPECTED.items():
        py = env_python(base, env)
        if not py.is_file():
            say(f"  FAIL  environment '{env}' is missing ({py})")
            good = False
            continue
        r = subprocess.run([str(py), "-c", VERSION_SNIPPET, *want],
                           capture_output=True, text=True)
        try:
            import json
            got = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            say(f"  FAIL  could not start Python in '{env}':\n{r.stderr[-800:]}")
            good = False
            continue
        bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
        if bad:
            for k, (g, w) in bad.items():
                say(f"  FAIL  {env}: {k} is {g}, needs {w}")
            good = False
        else:
            say(f"  ok    {env}: " + ", ".join(f"{k} {v}" for k, v in want.items()))
    return good


def check_planted(base: Path, tmp: Path) -> bool:
    say("\nCheck 2/3  stages 2-3 on a synthetic recording with known structure")
    out = tmp / "planted"
    analysis = env_python(base, "analysis")
    r = subprocess.run([str(analysis), str(REPO / "examples" / "make_example.py"), str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        say("  FAIL  could not make the synthetic recording:\n" + r.stderr[-1500:])
        return False
    env = os.environ.copy()
    env["PIPELINE_CASCADE_PYTHON"] = str(env_python(base, "cascade"))
    env.pop("PIPELINE_CASCADE_ENV", None)
    r = subprocess.run([str(analysis), "-m", "pipeline.run_pipeline", str(out)],
                       capture_output=True, text=True, cwd=REPO, env=env,
                       encoding="utf-8", errors="replace")
    log = r.stdout + r.stderr
    (tmp / "planted_log.txt").write_text(log, encoding="utf-8")
    plane0 = out / "suite2p" / "plane0"
    z = re.search(r"z ([0-9]+\.[0-9]+)", log)
    checks = [
        ("pipeline finished without errors", r.returncode == 0),
        ("CASCADE spike inference ran", (plane0 / "cascade_spike_prob.npy").is_file()),
        ("metrics workbook written", any(plane0.glob("*_metrics.xlsx"))),
        ("provenance record written", any(plane0.glob("*PROVENANCE*"))),
        ("active cells found (at least 10 of 15)", bool(re.search(r"active 1[0-5]/15", log))),
        ("co-firing detected (STTC z >= 3)", bool(z) and float(z.group(1)) >= 3),
        ("network burst detected", bool(re.search(r"Network bursts . fixed [1-9]", log))),
        ("no placeholder junk files", not any(plane0.glob("RUNID_*"))),
    ]
    for name, passed in checks:
        say(f"  {'ok  ' if passed else 'FAIL'}  {name}")
    if not all(p for _, p in checks):
        say("  --- end of the pipeline's output ---")
        say(log[-3000:])
        return False
    return True


def check_full(base: Path, tmp: Path) -> bool:
    say("\nCheck 3/3  all three stages, starting from a synthetic microscope movie")
    say("           (Suite2p + Cellpose on the CPU: usually 1-3 minutes)")
    folder = tmp / "movie"
    folder.mkdir()
    r = subprocess.run([str(env_python(base, "suite2p")), "-c", MOVIE_SNIPPET,
                        str(folder / "selftest_A01.tif")], capture_output=True, text=True)
    if r.returncode != 0:
        say("  FAIL  could not write the synthetic movie:\n" + r.stderr[-1500:])
        return False
    r = subprocess.run([str(env_python(base, "analysis")), str(REPO / "tools" / "analyze_folder.py"),
                        str(folder), "--indicator", "jgcamp8s", "--fps", "10", "--delete-bin"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = r.stdout + r.stderr
    (tmp / "full_log.txt").write_text(log, encoding="utf-8")
    cells = re.search(r"-> \S+: (\d+)/(\d+) cells", log)
    n_cells = int(cells.group(1)) if cells else 0
    checks = [
        ("Suite2p ran and detected cells" + (f" ({n_cells} found, 25 planted)" if cells else ""),
         n_cells > 0),
        ("CASCADE + metrics produced a workbook", any((folder / "RESULTS").glob("*_metrics.xlsx"))),
        ("run finished without errors", r.returncode == 0),
    ]
    for name, passed in checks:
        say(f"  {'ok  ' if passed else 'FAIL'}  {name}")
    if not all(p for _, p in checks):
        say("  --- end of the run's output ---")
        say(log[-4000:])
        return False
    return True


def main() -> int:
    base = conda_base()
    if base is None:
        say("Cannot find the install (CNP_CONDA_BASE is not set).")
        return 2
    say("=" * 64)
    say("SELF-TEST - checking that the pipeline is installed correctly")
    say("=" * 64)
    tmp = Path(tempfile.mkdtemp(prefix="cnp_selftest_"))
    results = [check_versions(base), check_planted(base, tmp), check_full(base, tmp)]
    if all(results):
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        say(f"\n(The test files were kept for inspection in {tmp})")
    say("")
    if all(results):
        say("SELF-TEST PASSED - the pipeline works on this computer.")
        return 0
    say("SELF-TEST FAILED - see the FAIL lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
