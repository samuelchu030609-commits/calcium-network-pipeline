"""Calcium Network Pipeline — GUI.

A thin Streamlit front-end. It does NOT re-implement any analysis:

  * "From microscope files" runs tools/analyze_folder.py (all three stages over a
    folder of TIFs) as a background process and shows its progress.
  * The other modes start from existing Suite2p output: they collect what
    config.json needs (indicator, frame rate, route), write it, run
    pipeline/run_pipeline.py, stream its log, and show the friendly "Key Numbers".

With the one-click install (install/), the "Calcium Pipeline" Desktop launcher
starts this with CNP_CONDA_BASE set, and every stage runs in its own environment
of that install. Otherwise launch it with gui/run_gui.sh or gui/run_gui.bat.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import streamlit as st

# ── Paths ──────────────────────────────────────────────────────────────────
GUI_DIR = Path(__file__).resolve().parent
REPO_ROOT = GUI_DIR.parent                      # calcium-network-pipeline/
SETTINGS_PATH = GUI_DIR / "settings.local.json"  # remembers how to run (git-ignored)

# Make the `pipeline` package importable (raw_rate reader, run_group comparison).
import sys as _sys
if str(REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(REPO_ROOT))
try:
    from pipeline.raw_rate import rate_from_raw
except Exception:  # keep the GUI usable even if the optional reader can't import
    def rate_from_raw(_folder):
        return None, "raw-rate reader unavailable (could not import pipeline.raw_rate)"

# ── Indicator → route table (mirrors config.example.json / config.py) ──────
# The user picks an indicator in plain language; we derive the route slug so
# nobody has to know "cascade_gc8s". This is the single source of that mapping
# for the GUI and is kept in step with pipeline/config.py ROUTE_FAMILY.
INDICATORS = [
    {
        "label": "SRS9 — jGCaMP8s  (genetically-encoded calcium sensor, slower)",
        "short": "SRS9 · jGCaMP8s",
        "indicator": "SRS9 jGCaMP8s",
        "route": "cascade_gc8s",
        "note": "CASCADE GC8s model. Your acquisition rate is resampled to the model rate automatically.",
    },
    {
        "label": "SRS10 — jGCaMP8f  (genetically-encoded calcium sensor, fast)",
        "short": "SRS10 · jGCaMP8f",
        "indicator": "SRS10 jGCaMP8f",
        "route": "cascade_gc8f",
        "note": "CASCADE GC8f model. Do not downsample the fast indicator — acquire high and let CASCADE resample.",
    },
    {
        "label": "Fluo-4 AM  (synthetic dye — legacy ΔF/F path, no CASCADE)",
        "short": "Fluo-4 · dye",
        "indicator": "Fluo-4 AM",
        "route": "dff",
        "note": "CASCADE is GCaMP-only, so dye recordings use ΔF/F₀ event detection. Legacy path, retired going forward.",
    },
]


def make_config(indicator_idx: int, fps: float, neuropil: float) -> dict:
    """Build the config.json dict for a recording (single source of the schema)."""
    sel = INDICATORS[indicator_idx]
    return {
        "_comment": "Written by the Calcium Network Pipeline GUI.",
        "indicator": sel["indicator"],
        "native_fps": float(fps),
        "route": sel["route"],
        "neuropil_coeff": float(neuropil),
    }


def guess_indicator_idx(path) -> int:
    """Best-guess indicator from the folder path, using the lab's naming conventions.

    Falls back to SRS9 (index 0). The user can always override per recording.
    """
    s = str(path).lower()
    if "fluo" in s:
        return 2
    if any(k in s for k in ("srs10", "ss10", "jgcamp8f", "gc8f", "8f")):
        return 1
    if any(k in s for k in ("srs9", "ss9", "jgcamp8s", "gc8s", "8s")):
        return 0
    return 0


_SKIP_DIRS = {"__pycache__", ".git", "miniforge3", "anaconda3", "envs",
              "Pretrained_models", "node_modules"}


def find_recordings(parent, max_results: int = 500) -> list:
    """Every recording folder (one holding suite2p/plane0/F.npy) beneath `parent`."""
    parent = Path(parent)
    found, seen = [], set()
    for root, dirs, files in os.walk(parent):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS]
        rp = Path(root)
        if rp.name == "plane0" and rp.parent.name == "suite2p" and "F.npy" in files:
            rec = rp.parent.parent
            if rec not in seen:
                seen.add(rec)
                found.append(rec)
                if len(found) >= max_results:
                    break
    return sorted(found)


# ── Settings persistence ───────────────────────────────────────────────────
def load_settings() -> dict:
    if SETTINGS_PATH.is_file():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_settings(s: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    except Exception as exc:  # non-fatal: settings are a convenience
        st.warning(f"Could not save settings: {exc}")


# ── Environment discovery ──────────────────────────────────────────────────
def list_conda_envs() -> list[str]:
    """Named conda environments, best-effort ([] if conda is unavailable)."""
    if not shutil.which("conda"):
        return []
    try:
        out = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True, text=True, timeout=20, check=True,
        )
        envs = json.loads(out.stdout).get("envs", [])
        names = [Path(p).name for p in envs if Path(p).name and Path(p).name != "anaconda3"]
        # Drop the base prefix (its Path.name is the anaconda folder, already filtered).
        return sorted(set(names))
    except Exception:
        return []


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _prefer(names: list[str], *wants: str) -> str | None:
    for w in wants:
        for n in names:
            if w.lower() in n.lower():
                return n
    return names[0] if names else None


# ── Recording folder validation ────────────────────────────────────────────
def normalize_path(raw: str) -> Path | None:
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        return None
    return Path(os.path.expanduser(raw)).resolve()


def validate_recording(folder: Path) -> tuple[Path, bool, list[str]]:
    """Return (plane0, ok, missing_files). ok means it's a usable plane0 folder."""
    plane0 = folder / "suite2p" / "plane0"
    required = ["F.npy", "Fneu.npy", "iscell.npy", "ops.npy"]
    missing = [f for f in required if not (plane0 / f).is_file()]
    return plane0, (plane0.is_dir() and not missing), missing


def read_ops_hint(plane0: Path) -> dict:
    """Best-effort fs / n-frames from ops.npy (skipped silently if numpy absent)."""
    try:
        import numpy as np
        ops = np.load(plane0 / "ops.npy", allow_pickle=True).item()
        return {"fs": ops.get("fs"), "nframes": ops.get("nframes")}
    except Exception:
        return {}


_PICKER = r"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = filedialog.askdirectory(title=sys.argv[1])
root.destroy()
sys.stdout.write(path or "")
"""


def pick_folder_dialog(title: str = "Select a folder") -> str | None:
    """Native OS folder picker (works when the GUI runs on the same machine).

    Runs in its own small process: Streamlit executes this script on a worker
    thread, and macOS only allows windows on a program's main thread (an in-process
    Tk dialog hangs there).
    """
    try:
        r = subprocess.run([_sys.executable, "-c", _PICKER, title],
                           capture_output=True, text=True, timeout=600)
        return r.stdout.strip() or None
    except Exception:
        return None


# ── The one-click install ──────────────────────────────────────────────────
def installed_base() -> Path | None:
    """The install's conda folder when launched from the Desktop launcher, else None."""
    raw = os.environ.get("CNP_CONDA_BASE")
    if raw and (Path(raw) / "envs").is_dir():
        return Path(raw)
    return None


def installed_python(name: str) -> Path:
    base = installed_base()
    if os.name == "nt":
        return base / "envs" / name / "python.exe"
    return base / "envs" / name / "bin" / "python"


# ── Command construction ───────────────────────────────────────────────────
def build_command(settings: dict, data_dir: Path) -> tuple[list[str], dict, str | None, str]:
    """Return (argv, env, cwd, human_readable). Mirrors docker/run.sh / run_pipeline."""
    env = os.environ.copy()
    mode = settings.get("mode", "conda")

    if mode == "installed":
        env["PIPELINE_CASCADE_PYTHON"] = str(installed_python("cascade"))
        env.pop("PIPELINE_CASCADE_ENV", None)
        env["PYTHONUTF8"] = "1"
        argv = [str(installed_python("analysis")), "-m", "pipeline.run_pipeline", str(data_dir)]
        return argv, env, str(REPO_ROOT), " ".join(argv)

    if mode == "docker":
        image = settings.get("image", "ghcr.io/samuelchu030609-commits/calcium-network-pipeline:latest")
        argv = ["docker", "run", "--rm", "-v", f"{data_dir}:/data", image, "/data"]
        return argv, env, None, " ".join(argv)

    # conda / direct both run the orchestrator from the repo root so
    # `python -m pipeline.run_pipeline` resolves the package.
    if settings.get("cascade_env"):
        env["PIPELINE_CASCADE_ENV"] = settings["cascade_env"]

    if mode == "conda":
        analysis_env = settings.get("analysis_env") or "analysis"
        argv = ["conda", "run", "--no-capture-output", "-n", analysis_env,
                "python", "-m", "pipeline.run_pipeline", str(data_dir)]
    else:  # direct
        py = settings.get("python_path") or "python"
        argv = [py, "-m", "pipeline.run_pipeline", str(data_dir)]

    human = f"PIPELINE_CASCADE_ENV={env.get('PIPELINE_CASCADE_ENV', '')}  " + " ".join(argv)
    return argv, env, str(REPO_ROOT), human


def stream_run(argv, env, cwd, log_box) -> tuple[int, list[str]]:
    """Run the pipeline, streaming stdout/stderr live into log_box. Returns (rc, lines)."""
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env, cwd=cwd,
        )
    except FileNotFoundError as exc:
        log_box.error(f"Could not start the pipeline: {exc}\n\nCommand: {' '.join(argv)}")
        return 127, [str(exc)]

    lines: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        lines.append(line.rstrip("\n"))
        log_box.code("\n".join(lines[-500:]), language="text")
    proc.wait()
    return proc.returncode, lines


# ── Results rendering ──────────────────────────────────────────────────────
FRIENDLY_SHEETS = ["Key Numbers", "How to Read This",
                   "Firing Rates (per cell)", "Firing Together (per cell)",
                   "Group Events (bursts)", "Teams (assemblies)"]


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def show_sheet_html(xls, name) -> None:
    """Render one Excel sheet as an HTML table (no pyarrow dependency)."""
    import pandas as pd
    df = pd.read_excel(xls, name, header=None).fillna("")
    html = df.to_html(index=False, header=False, na_rep="", border=0,
                      classes="cnp-table", escape=True)
    st.markdown(
        "<style>"
        ".cnp-table{border-collapse:collapse;width:100%;font-size:0.92rem;}"
        ".cnp-table td{border:1px solid rgba(128,128,128,.25);padding:4px 10px;"
        "text-align:left;vertical-align:top;}"
        ".cnp-table tr:first-child td{font-weight:600;}"
        "</style>" + html,
        unsafe_allow_html=True,
    )


def render_results(xlsx_path: Path) -> None:
    import pandas as pd
    try:
        xls = pd.ExcelFile(xlsx_path)
    except Exception as exc:
        st.error(f"Produced a file but could not open it as a workbook: {exc}")
        return

    st.success(f"Done — workbook written to:\n`{xlsx_path}`")
    with open(xlsx_path, "rb") as fh:
        st.download_button("⬇ Download the metrics workbook (.xlsx)", fh,
                           file_name=xlsx_path.name, mime=XLSX_MIME)

    def show_sheet(name: str) -> None:
        show_sheet_html(xls, name)

    if "Key Numbers" in xls.sheet_names:
        st.subheader("Key Numbers")
        show_sheet("Key Numbers")
    if "How to Read This" in xls.sheet_names:
        with st.expander("How to read these numbers"):
            show_sheet("How to Read This")

    other_friendly = [s for s in FRIENDLY_SHEETS
                      if s in xls.sheet_names and s not in ("Key Numbers", "How to Read This")]
    if other_friendly:
        with st.expander("More friendly sheets"):
            tabs = st.tabs(other_friendly)
            for tab, name in zip(tabs, other_friendly):
                with tab:
                    show_sheet(name)

    tech = [s for s in xls.sheet_names if s not in FRIENDLY_SHEETS]
    if tech:
        st.caption("Technical sheets in the workbook: " + ", ".join(tech))


def run_one_recording(folder: Path, config_dict: dict, settings: dict, log_box) -> dict:
    """Write config.json, run the pipeline, stream into log_box. Shared by both modes.

    Returns {rc, xlsx (Path|None), warned (bool), lines}.
    """
    (folder / "config.json").write_text(json.dumps(config_dict, indent=2))
    argv, env, cwd, _ = build_command(settings, folder)
    rc, lines = stream_run(argv, env, cwd, log_box)
    warned = any(("DETECTION settings differ" in ln) or ("may NOT be comparable" in ln)
                 for ln in lines)
    xlsx = None
    if rc == 0:
        wrote = [ln for ln in lines if "[pipeline] wrote " in ln]
        if wrote:
            xlsx = Path(wrote[-1].split("[pipeline] wrote ", 1)[1].strip())
        else:
            xlsx = folder / "suite2p" / "plane0" / f"{folder.name}_metrics.xlsx"
    return {"rc": rc, "xlsx": xlsx, "warned": warned, "lines": lines}


# ── From-microscope-files flow (all three stages, runs in the background) ────
# INDICATORS index -> tools/analyze_folder.py --indicator value
ANALYZE_KEYS = ["jgcamp8s", "jgcamp8f", "fluo4"]
RUN_STATE = "_gui_run.json"     # in <folder>/RESULTS/: which process is analysing it
RUN_LOG = "_gui_live_log.txt"   # in <folder>/RESULTS/: that process's screen output


def run_alive(state: dict | None) -> bool:
    """Is the analysis recorded in `state` still running?

    Checks that the process is really OUR analysis, not an unrelated program that
    was given the same process number after a restart (Stop must never kill that).
    """
    if not state or not state.get("pid"):
        return False
    pid = int(state["pid"])
    if os.name == "nt":
        # os.kill(pid, 0) would KILL the process on Windows, so ask the OS directly.
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            k32.GetExitCodeProcess(h, ctypes.byref(code))
            if code.value != 259:                      # STILL_ACTIVE
                return False
            # Same process = created when we started it (FILETIME: 100 ns since 1601).
            c, e, k, u = (wintypes.FILETIME() for _ in range(4))
            k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
            created = ((c.dwHighDateTime << 32) + c.dwLowDateTime) / 1e7 - 11644473600
            return abs(created - float(state.get("t0", 0))) < 60
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:   # a finished child of this GUI lingers as a zombie until reaped
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done != 0:
            return False
    except ChildProcessError:
        pass
    r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return "analyze_folder.py" in r.stdout


def run_state(folder: Path) -> dict | None:
    p = folder / "RESULTS" / RUN_STATE
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def analyze_argv(folder: Path, ind_idx: int, *, dry_run=False, force=False,
                 delete_bin=False, fps=None) -> list[str]:
    argv = [str(installed_python("analysis")), str(REPO_ROOT / "tools" / "analyze_folder.py"),
            str(folder), "--indicator", ANALYZE_KEYS[ind_idx]]
    if dry_run:
        argv.append("--dry-run")
    if force:
        argv.append("--force")
    if delete_bin:
        argv.append("--delete-bin")
    if fps:
        argv += ["--fps", str(fps)]
    return argv


def start_background(folder: Path, argv: list[str]) -> None:
    """Start the analysis so that it outlives the browser tab AND this GUI's window."""
    results = folder / "RESULTS"
    results.mkdir(exist_ok=True)
    log = open(results / RUN_LOG, "w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000200 | 0x08000000   # NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            cwd=str(REPO_ROOT), env=env, **kw)
    (results / RUN_STATE).write_text(json.dumps(
        {"pid": proc.pid, "argv": argv, "t0": time.time(),
         "started": time.strftime("%Y-%m-%d %H:%M")}))


def stop_background(pid: int) -> None:
    """Stop the analysis and everything it started (Suite2p, CASCADE ...)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            import signal
            os.killpg(pid, signal.SIGTERM)
    except Exception:
        pass


def open_in_file_browser(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        st.warning(f"Could not open the folder: {exc}")


def tail(path: Path, n: int = 60) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return ""
    # TensorFlow's progress bars rewrite one line many times; keep only the last copy.
    lines = [ln.split("\r")[-1] for ln in lines]
    return "\n".join(lines[-n:])


def tif_ui(settings: dict) -> None:
    if installed_base() is None:
        st.warning("This mode needs the one-click install (see HOW_TO_INSTALL.md) and must be "
                   "started from the **Calcium Pipeline** launcher on the Desktop. "
                   "Without it, run Suite2p yourself and use the other modes.")
        return

    st.subheader("1 · Pick the folder with your microscope files")
    st.caption("The folder that directly contains the `.tif` movies (one plate or one "
               "experiment). Files saved in parts (`…-file002.tif`) are joined automatically.")
    c1, c2 = st.columns([4, 1])
    with c1:
        folder_str = st.text_input("Folder of TIFs", key="tif_folder",
                                   label_visibility="collapsed",
                                   placeholder="e.g. D:\\Imaging\\2026-09-28 plate 1")
    with c2:
        if st.button("Browse…", key="tif_browse", use_container_width=True):
            picked = pick_folder_dialog("Select the folder that contains the .tif movies")
            if picked:
                st.session_state["tif_folder"] = picked
                st.rerun()
    folder = normalize_path(folder_str)
    if not folder:
        return
    if not folder.is_dir():
        st.error(f"Not a folder: {folder}")
        return

    # An analysis already running (or finished) on this folder takes over the page.
    state = run_state(folder)
    if run_alive(state):
        progress_panel(folder, state)
        return
    if state:
        finished_banner(folder)

    n_tif = sum(1 for p in folder.iterdir() if p.is_file()
                and p.suffix.lower() in (".tif", ".tiff") and not p.name.startswith("._"))
    n_done = sum(1 for _ in folder.glob("*/suite2p/plane0/F.npy"))
    if n_tif == 0 and n_done == 0:
        st.error("No `.tif` files directly inside this folder. Pick the folder that holds "
                 "the movies themselves (not a folder above it).")
        return
    st.success(f"Found {n_tif} `.tif` file(s)"
               + (f" · {n_done} recording(s) already through stage 1" if n_done else ""))

    st.subheader("2 · Which indicator was imaged?")
    labels = [i["label"] for i in INDICATORS]
    ind_idx = st.radio("Indicator", range(len(labels)), format_func=lambda i: labels[i],
                       index=guess_indicator_idx(folder), key="tif_ind")
    st.caption(INDICATORS[ind_idx]["note"])

    with st.expander("Options"):
        delete_bin = st.checkbox(
            "Delete Suite2p's large temporary file (data.bin) after each recording",
            value=True,
            help="Each recording's data.bin is 0.6-2 GB. It is only needed to re-run cell "
                 "detection inside the Suite2p program, so deleting it is safe for this "
                 "analysis and saves a lot of disk space.")
        force = st.checkbox("Redo recordings that were already analysed", value=False)
        fps_override = st.number_input(
            "Frame rate in Hz — ONLY if the check below says “NO RATE”", min_value=0.0,
            max_value=1000.0, value=0.0, step=1.0,
            help="Normally the frame rate is read from each file's own timestamps "
                 "(MetaMorph/MetaSeries TIFs). TIFs from other software may not carry "
                 "them; then type the acquisition rate here. It applies to every file "
                 "in the folder. Leave at 0 otherwise.") or None

    st.subheader("3 · Check, then start")
    if st.button("🔍 Check the folder first (reads every file's frame rate, changes nothing)"):
        with st.spinner("Reading the files…"):
            r = subprocess.run(analyze_argv(folder, ind_idx, dry_run=True, fps=fps_override),
                               capture_output=True, text=True, cwd=str(REPO_ROOT),
                               encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONUTF8": "1"})
        st.session_state["tif_check"] = {"folder": str(folder), "rc": r.returncode,
                                         "out": (r.stdout + r.stderr)[-6000:]}
    chk = st.session_state.get("tif_check")
    checked_ok = bool(chk and chk["folder"] == str(folder) and chk["rc"] == 0)
    if chk and chk["folder"] == str(folder):
        st.code(chk["out"], language="text")
        if chk["rc"] == 0:
            st.caption("Each row is one recording, with its frame rate read from the file's own "
                       "timestamps. 'SKIP (done)' rows were already processed.")
        elif "NO RATE" in chk["out"]:
            st.error("These files carry no timestamps, so their frame rate is unknown. Open "
                     "**Options** above, type the acquisition frame rate, and check again.")
        else:
            st.error("The check found a problem (see the last lines above). Fix it before starting.")

    st.info("The analysis runs **in the background**: you can close this browser tab and "
            "come back later (open the program and pick the same folder). Keep the computer on. "
            "Rough time: 3-6 minutes per recording on a normal computer.")
    if not checked_ok:
        st.caption("Run the check above first; Start becomes available when it finds no problem.")
    if st.button("▶ Start the analysis", type="primary", disabled=not checked_ok):
        start_background(folder, analyze_argv(folder, ind_idx, force=force, delete_bin=delete_bin,
                                              fps=fps_override))
        st.rerun()

    show_results_folder(folder)


def show_results_folder(folder: Path) -> None:
    results = folder / "RESULTS"
    wbs = sorted(results.glob("*_metrics.xlsx")) if results.is_dir() else []
    if not wbs:
        return
    st.divider()
    st.subheader(f"Results — {len(wbs)} workbook(s) in RESULTS")
    if st.button("📂 Open the RESULTS folder"):
        open_in_file_browser(results)
    pick = st.selectbox("Show the Key Numbers of", [w.name for w in wbs], key="tif_show")
    if pick:
        render_results(results / pick)


def progress_panel(folder: Path, state: dict) -> None:
    st.info(f"⏳ Analysis running on this folder (started {state.get('started', '?')}). "
            "You can close this browser tab; it keeps going.")
    if st.button("■ Stop the analysis"):
        stop_background(state["pid"])
        st.warning("Stopped. Starting again later continues where it left off.")
        time.sleep(1)
        st.rerun()

    @st.fragment(run_every=5)
    def live():
        s = run_state(folder)
        if not run_alive(s):
            st.rerun()   # finished: redraw the whole page with the results
        st.code(tail(folder / "RESULTS" / RUN_LOG), language="text")
    live()


def finished_banner(folder: Path) -> None:
    """After a background run has ended, say how it went."""
    log = tail(folder / "RESULTS" / RUN_LOG, 400)
    summary = log[log.rfind("SUMMARY"):] if "SUMMARY" in log else log[-2500:]
    if "recordings analysed" in log:
        st.success("The last analysis of this folder has finished.")
    else:
        st.error("The last analysis of this folder stopped before the end. Its last lines:")
    st.code(summary, language="text")


# ── Page ───────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Calcium Network Pipeline", page_icon="🧠", layout="centered")
settings = load_settings()

st.title("🧠 Calcium Network Pipeline")
st.caption("From microscope movies to activity and network-synchrony numbers: "
           "Suite2p (cell detection) → CASCADE (spike inference) → network metrics.")

if installed_base() is not None:
    # One-click install: every stage has its own environment in a known place.
    settings["mode"] = "installed"
    st.caption(f"Using the installed pipeline in `{installed_base().parent}`.")
else:
    if settings.get("mode") == "installed":   # saved by an installed copy; not usable here
        settings.pop("mode")
    # --- Execution settings (set once, remembered) -----------------------------
    with st.expander("⚙️ How to run the pipeline (set this once)", expanded=not SETTINGS_PATH.is_file()):
        envs = list_conda_envs()
        have_docker = docker_available()

        mode_options = []
        if envs:
            mode_options.append("conda")
        if have_docker:
            mode_options.append("docker")
        mode_options.append("direct")
        default_mode = settings.get("mode") or mode_options[0]
        if default_mode not in mode_options:
            mode_options.insert(0, default_mode)

        mode = st.radio(
            "Execution mode",
            mode_options,
            index=mode_options.index(default_mode),
            help=("conda: run in your named conda envs (recommended for the manual install).  "
                  "docker: use the bundled image (needs Docker Desktop).  "
                  "direct: one Python that has everything including TensorFlow."),
            horizontal=True,
        )
        settings["mode"] = mode

        if mode == "conda":
            if envs:
                a_default = settings.get("analysis_env") or _prefer(envs, "analysis", "cascade")
                c_default = settings.get("cascade_env") or _prefer(envs, "cascade")
                settings["analysis_env"] = st.selectbox(
                    "Analysis env (runs metrics + orchestration)",
                    envs, index=envs.index(a_default) if a_default in envs else 0)
                settings["cascade_env"] = st.selectbox(
                    "CASCADE env (stage 2, needs TensorFlow)",
                    envs, index=envs.index(c_default) if c_default in envs else 0)
            else:
                st.info("No conda envs detected. Switch to 'direct' or 'docker'.")
        elif mode == "docker":
            settings["image"] = st.text_input(
                "Docker image",
                settings.get("image", "ghcr.io/samuelchu030609-commits/calcium-network-pipeline:latest"))
        else:  # direct
            settings["python_path"] = st.text_input(
                "Python interpreter (must import numpy/scipy/pandas + TensorFlow for CASCADE)",
                settings.get("python_path", "python"))
            if envs:
                c_default = settings.get("cascade_env") or _prefer(envs, "cascade")
                use_sep = st.checkbox("CASCADE (stage 2) lives in a separate conda env",
                                      value=bool(settings.get("cascade_env")))
                settings["cascade_env"] = (
                    st.selectbox("CASCADE env", envs, index=envs.index(c_default) if c_default in envs else 0)
                    if use_sep else None)

        if st.button("💾 Save these settings"):
            save_settings(settings)
            st.success("Saved.")

st.divider()


# ── Single-recording flow ──────────────────────────────────────────────────
def single_recording_ui(settings: dict) -> None:
    # --- Step 1: recording folder ---
    st.subheader("1 · Pick the recording folder")
    st.caption("The folder that **contains** `suite2p/` (not the plane0 folder itself). "
               "`config.json` will be written here.")

    col_a, col_b = st.columns([4, 1])
    with col_a:
        folder_str = st.text_input("Recording folder path",
                                   value=st.session_state.get("folder_str", ""),
                                   label_visibility="collapsed",
                                   placeholder="/path/to/2026.06.10/…_002")
    with col_b:
        if st.button("Browse…", use_container_width=True):
            picked = pick_folder_dialog()
            if picked:
                st.session_state["folder_str"] = picked
                st.rerun()

    folder = normalize_path(folder_str)
    plane0 = None
    ok = False
    if folder:
        if not folder.is_dir():
            st.error(f"Not a folder: {folder}")
        else:
            plane0, ok, missing = validate_recording(folder)
            if ok:
                hint = read_ops_hint(plane0)
                msg = f"✅ Found Suite2p output: `{plane0}`"
                if hint.get("nframes"):
                    msg += f"  · {hint['nframes']} frames"
                st.success(msg)
            else:
                st.error(f"`{plane0}` is missing: {', '.join(missing)}. "
                         "Point me at the folder that contains `suite2p/plane0/` with the Suite2p `.npy` files.")

    # --- Step 2: describe the recording ---
    st.subheader("2 · Describe the recording")
    labels = [i["label"] for i in INDICATORS]
    sel_idx = st.radio("Indicator", range(len(labels)),
                       format_func=lambda i: labels[i], index=0)
    sel = INDICATORS[sel_idx]
    st.caption(sel["note"])

    ops_fs = read_ops_hint(plane0).get("fs") if (plane0 and ok) else None
    default_fps = round(float(ops_fs), 3) if ops_fs else 45.0

    # Keep the rate in session_state so the "Read from raw file" button can set it.
    # Re-seed the default whenever the selected folder changes.
    folder_key = str(folder) if folder else ""
    if st.session_state.get("single_fps_folder") != folder_key:
        st.session_state["single_fps_folder"] = folder_key
        st.session_state["single_fps"] = default_fps
        st.session_state.pop("single_fps_src", None)

    c_fps, c_btn = st.columns([3, 2])
    with c_fps:
        fps = st.number_input(
            "Acquisition frame rate (Hz) — this recording's true rate",
            min_value=0.1, max_value=1000.0, step=1.0, key="single_fps",
            help="The recording's true rate. Suite2p's stored fs is unreliable — use "
                 "'Read from raw file' to get it from the movie's own timestamps.")
    def _read_rate_cb(rec_folder):
        # runs as an on_click callback -> before the widget re-instantiates, so
        # writing the 'single_fps' key here is allowed (unlike inside the run body).
        rate, src = rate_from_raw(rec_folder)
        if rate:
            st.session_state["single_fps"] = round(float(rate), 3)
            st.session_state["single_fps_src"] = f"✅ read {rate:.2f} Hz from {src}"
        else:
            st.session_state["single_fps_src"] = f"ℹ️ {src}"

    with c_btn:
        st.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)  # align with input
        st.button("📷 Read from raw file", disabled=not (folder and ok),
                  use_container_width=True, on_click=_read_rate_cb, args=(folder,))

    src_msg = st.session_state.get("single_fps_src")
    if src_msg:
        st.caption(src_msg)
    elif ops_fs:
        st.caption(f"ℹ️ Suite2p's stored fs is {float(ops_fs):.3g} Hz "
                   f"(a hint only — verify against the raw file).")

    with st.expander("Advanced"):
        neuropil = st.number_input("Neuropil coefficient", min_value=0.0, max_value=2.0,
                                   value=float(settings.get("neuropil_coeff", 0.7)), step=0.05)

    config_dict = make_config(sel_idx, fps, neuropil)
    with st.expander("Preview config.json that will be written"):
        st.code(json.dumps(config_dict, indent=2), language="json")

    # --- Step 3: run ---
    st.subheader("3 · Run")
    if folder:
        _, _, _, human = build_command(settings, folder)
        st.caption("Command:")
        st.code(human, language="bash")

    can_run = bool(folder and ok)
    if st.button("▶ Run pipeline", type="primary", disabled=not can_run):
        save_settings({**settings, "neuropil_coeff": float(neuropil)})
        st.info("Running… CASCADE's first run on a new indicator may download a model (one time).")
        log_box = st.empty()
        with st.spinner("Processing — this can take a few minutes on longer recordings."):
            try:
                out = run_one_recording(folder, config_dict, settings, log_box)
            except Exception as exc:
                st.error(f"Could not run: {exc}")
                st.stop()
        if out["warned"]:
            st.warning("⚠️ Suite2p **detection settings differ from canonical** — your numbers may not be "
                       "comparable to the reference runs. See the log for the differing keys.")
        if out["rc"] == 0 and out["xlsx"]:
            st.session_state["last_result"] = str(out["xlsx"])
        else:
            st.error(f"Pipeline exited with code {out['rc']}. See the log above.")
            st.session_state.pop("last_result", None)

    last = st.session_state.get("last_result")
    if last and Path(last).exists():
        st.divider()
        st.subheader("Results")
        render_results(Path(last))


# ── Batch-queue flow ───────────────────────────────────────────────────────
def batch_ui(settings: dict) -> None:
    st.subheader("Batch queue")
    st.caption("Queue several recordings and run them one after another. Each writes its "
               "own `config.json` and its own `*_metrics.xlsx`.")

    st.session_state.setdefault("queue", [])
    st.session_state.setdefault("queue_next_id", 1)

    def add_folder(folder: Path) -> bool:
        existing = {Path(it["folder"]) for it in st.session_state["queue"]}
        if folder in existing:
            return False
        plane0, ok, _ = validate_recording(folder)
        if not ok:
            return False
        qid = st.session_state["queue_next_id"]
        st.session_state["queue_next_id"] += 1
        fs = read_ops_hint(plane0).get("fs")
        st.session_state["queue"].append({
            "id": qid, "folder": str(folder),
            "indicator_idx": guess_indicator_idx(folder),
            "fps": float(fs) if fs else 45.0,
        })
        return True

    # --- add by scanning a parent folder ---
    with st.container(border=True):
        st.markdown("**Scan a parent folder** — finds every recording (a `suite2p/plane0`) beneath it.")
        c1, c2 = st.columns([4, 1])
        with c1:
            parent_str = st.text_input("Parent folder", key="batch_parent",
                                       label_visibility="collapsed",
                                       placeholder="/path/to/2026.06.10")
        with c2:
            if st.button("Browse…", key="batch_browse", use_container_width=True):
                picked = pick_folder_dialog()
                if picked:
                    st.session_state["batch_parent"] = picked
                    st.rerun()
        if st.button("🔍 Scan & add", disabled=not parent_str):
            parent = normalize_path(parent_str)
            if not parent or not parent.is_dir():
                st.error("Not a folder.")
            else:
                with st.spinner("Scanning…"):
                    recs = find_recordings(parent)
                if not recs:
                    st.warning("No `suite2p/plane0` folders found under there.")
                else:
                    added = sum(1 for r in recs if add_folder(r))
                    st.success(f"Found {len(recs)} recording(s); added {added} new.")
                    st.rerun()

    # --- add one folder ---
    with st.container(border=True):
        st.markdown("**Add one folder**")
        c1, c2 = st.columns([4, 1])
        with c1:
            one_str = st.text_input("Recording folder", key="batch_one",
                                     label_visibility="collapsed",
                                     placeholder="/path/to/…_002")
        with c2:
            if st.button("➕ Add", key="batch_add_one", use_container_width=True, disabled=not one_str):
                folder = normalize_path(one_str)
                if folder and add_folder(folder):
                    st.session_state["batch_one"] = ""
                    st.rerun()
                else:
                    st.error("Not added — not a valid Suite2p folder, or already queued.")

    queue = st.session_state["queue"]
    if not queue:
        st.info("Queue is empty. Add recordings above.")
        return

    with st.expander("Advanced (applies to every queued recording)"):
        batch_neuropil = st.number_input("Neuropil coefficient", 0.0, 2.0,
                                         value=float(settings.get("neuropil_coeff", 0.7)),
                                         step=0.05, key="batch_neuropil")

    st.markdown(f"**Queue — {len(queue)} recording(s)**  ·  edit indicator / rate per row")
    hdr = st.columns([3, 3, 1.6, 0.7])
    hdr[0].caption("Recording"); hdr[1].caption("Indicator")
    hdr[2].caption("Rate (Hz)"); hdr[3].caption(" ")

    results = st.session_state.get("batch_results", {})
    remove_id = None
    for it in queue:
        qid = it["id"]
        folder = Path(it["folder"])
        c = st.columns([3, 3, 1.6, 0.7])
        with c[0]:
            st.write(f"`{folder.name}`")
            st.caption(str(folder.parent))
            r = results.get(str(qid))
            if r:
                st.write(r["badge"])
        with c[1]:
            st.selectbox("indicator", range(len(INDICATORS)), index=it["indicator_idx"],
                         format_func=lambda i: INDICATORS[i]["short"],
                         key=f"q_ind_{qid}", label_visibility="collapsed")
        with c[2]:
            st.number_input("fps", 0.1, 1000.0, value=float(it["fps"]), step=1.0,
                            key=f"q_fps_{qid}", label_visibility="collapsed")
        with c[3]:
            if st.button("🗑", key=f"q_rm_{qid}", help="Remove from queue"):
                remove_id = qid
    if remove_id is not None:
        st.session_state["queue"] = [it for it in queue if it["id"] != remove_id]
        st.rerun()

    b = st.columns([1, 1, 3])
    if b[0].button("Clear queue"):
        st.session_state["queue"] = []
        st.session_state.pop("batch_results", None)
        st.rerun()
    run_all = b[1].button(f"▶ Run all ({len(queue)})", type="primary")

    if run_all:
        save_settings({**settings, "neuropil_coeff": float(batch_neuropil)})
        results = {}
        total = len(queue)
        prog = st.progress(0.0, text="Starting…")
        for n, it in enumerate(queue, 1):
            qid = it["id"]
            folder = Path(it["folder"])
            idx = int(st.session_state.get(f"q_ind_{qid}", it["indicator_idx"]))
            fps = float(st.session_state.get(f"q_fps_{qid}", it["fps"]))
            prog.progress((n - 1) / total, text=f"[{n}/{total}] {folder.name} — running…")
            with st.expander(f"[{n}/{total}] {folder.name}", expanded=True):
                log_box = st.empty()
                try:
                    out = run_one_recording(folder, make_config(idx, fps, batch_neuropil),
                                            settings, log_box)
                except Exception as exc:
                    results[str(qid)] = {"ok": False, "badge": f"❌ error: {exc}", "xlsx": None}
                    continue
                if out["rc"] == 0 and out["xlsx"] and out["xlsx"].exists():
                    badge = "✅ done" + ("  ·  ⚠️ detection differs" if out["warned"] else "")
                    results[str(qid)] = {"ok": True, "badge": badge, "xlsx": str(out["xlsx"])}
                else:
                    results[str(qid)] = {"ok": False, "badge": f"❌ exit code {out['rc']}", "xlsx": None}
        prog.progress(1.0, text="Batch complete.")
        st.session_state["batch_results"] = results

    # --- summary (persists across reruns, e.g. download clicks) ---
    results = st.session_state.get("batch_results", {})
    shown = {str(it["id"]): it for it in queue}
    results = {k: v for k, v in results.items() if k in shown}
    if results:
        st.divider()
        ok_n = sum(1 for r in results.values() if r["ok"])
        st.subheader(f"Batch results — {ok_n}/{len(results)} succeeded")
        for it in queue:
            r = results.get(str(it["id"]))
            if not r:
                continue
            folder = Path(it["folder"])
            cols = st.columns([4, 2])
            cols[0].write(f"`{folder.name}` — {r['badge']}")
            if r["ok"] and r["xlsx"] and Path(r["xlsx"]).exists():
                with open(r["xlsx"], "rb") as fh:
                    cols[1].download_button(
                        "⬇ .xlsx", fh, file_name=Path(r["xlsx"]).name, key=f"dl_{it['id']}",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Compare-recordings flow ────────────────────────────────────────────────
def compare_ui(settings: dict) -> None:
    st.subheader("Compare recordings")
    st.caption("Pool several finished `*_metrics.xlsx` into one comparison workbook — "
               "per-group means and a two-group contrast (e.g. WT vs KCNT1). "
               "**You** assign the group labels; genotype isn't read from the files.")

    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    try:
        from pipeline.run_group import build_comparison, _guess_group, _scan_workbooks, GroupError
    except Exception as exc:
        st.error(f"Could not load the comparison tool: {exc}")
        return

    st.session_state.setdefault("cmp_items", [])
    st.session_state.setdefault("cmp_next_id", 1)

    def add_wb(path: Path) -> bool:
        if path in {Path(it["path"]) for it in st.session_state["cmp_items"]}:
            return False
        cid = st.session_state["cmp_next_id"]
        st.session_state["cmp_next_id"] += 1
        st.session_state["cmp_items"].append(
            {"id": cid, "path": str(path), "group": _guess_group(path)})
        return True

    with st.container(border=True):
        st.markdown("**Scan a folder for finished workbooks** (`*_metrics.xlsx`).")
        c1, c2 = st.columns([4, 1])
        with c1:
            parent = st.text_input("Folder", key="cmp_parent",
                                   label_visibility="collapsed",
                                   placeholder="/path/to/session")
        with c2:
            if st.button("Browse…", key="cmp_browse", use_container_width=True):
                p = pick_folder_dialog()
                if p:
                    st.session_state["cmp_parent"] = p
                    st.rerun()
        if st.button("🔍 Scan & add", disabled=not parent):
            par = normalize_path(parent)
            if not par or not par.is_dir():
                st.error("Not a folder.")
            else:
                wbs = _scan_workbooks(par)
                if not wbs:
                    st.warning("No `*_metrics.xlsx` found under there.")
                else:
                    added = sum(1 for w in wbs if add_wb(Path(w)))
                    st.success(f"Found {len(wbs)} workbook(s); added {added} new.")
                    st.rerun()

    with st.container(border=True):
        st.markdown("**Add one workbook**")
        c1, c2 = st.columns([4, 1])
        with c1:
            one = st.text_input("Workbook", key="cmp_one",
                                label_visibility="collapsed",
                                placeholder="/path/to/2169_metrics.xlsx")
        with c2:
            if st.button("➕ Add", key="cmp_add_one", use_container_width=True, disabled=not one):
                p = normalize_path(one)
                if p and p.is_file() and add_wb(p):
                    st.session_state["cmp_one"] = ""
                    st.rerun()
                else:
                    st.error("Not added — not a file, or already listed.")

    items = st.session_state["cmp_items"]
    if not items:
        st.info("Add some `*_metrics.xlsx` workbooks above.")
        return

    st.markdown(f"**{len(items)} recording(s)**  ·  set a group label per row")
    hdr = st.columns([4, 2, 0.7])
    hdr[0].caption("Workbook"); hdr[1].caption("Group"); hdr[2].caption(" ")
    remove_id = None
    for it in items:
        cid = it["id"]
        p = Path(it["path"])
        c = st.columns([4, 2, 0.7])
        with c[0]:
            st.write(f"`{p.name}`")
            st.caption(str(p.parent))
        with c[1]:
            st.text_input("group", value=it["group"], key=f"cmp_grp_{cid}",
                          label_visibility="collapsed")
        with c[2]:
            if st.button("🗑", key=f"cmp_rm_{cid}", help="Remove"):
                remove_id = cid
    if remove_id is not None:
        st.session_state["cmp_items"] = [x for x in items if x["id"] != remove_id]
        st.rerun()

    default_out = str(Path(items[0]["path"]).parent / "group_comparison.xlsx")
    out_path = st.text_input("Save the comparison workbook to",
                             value=st.session_state.get("cmp_out", default_out), key="cmp_out")

    b = st.columns([1, 1, 3])
    if b[0].button("Clear list"):
        st.session_state["cmp_items"] = []
        st.session_state.pop("cmp_result", None)
        st.rerun()
    if b[1].button("▶ Build comparison", type="primary"):
        built = [{"path": it["path"],
                  "group": st.session_state.get(f"cmp_grp_{it['id']}", it["group"]),
                  "label": None} for it in items]
        try:
            st.session_state["cmp_result"] = build_comparison(built, out_path)
        except GroupError as exc:
            st.error(str(exc))
            st.session_state.pop("cmp_result", None)
        except Exception as exc:
            st.error(f"Failed to build the comparison: {exc}")
            st.session_state.pop("cmp_result", None)

    res = st.session_state.get("cmp_result")
    if res and Path(res).exists():
        st.divider()
        st.subheader("Comparison")
        with open(res, "rb") as fh:
            st.download_button("⬇ Download group_comparison.xlsx", fh,
                               file_name=Path(res).name, mime=XLSX_MIME)
        import pandas as pd
        try:
            xls = pd.ExcelFile(res)
        except Exception as exc:
            st.error(f"Built the file but could not reopen it: {exc}")
            return
        for sheet in ["Contrast", "By group", "Per recording"]:
            if sheet in xls.sheet_names:
                label = "Per recording (all values)" if sheet == "Per recording" else sheet
                with st.expander(label, expanded=(sheet == "Contrast")):
                    show_sheet_html(xls, sheet)
        if "How to read" in xls.sheet_names:
            with st.expander("How to read / caveats"):
                show_sheet_html(xls, "How to read")


# ── Mode switch ────────────────────────────────────────────────────────────
MODES = ["From microscope files", "One Suite2p recording", "Batch of Suite2p recordings",
         "Compare recordings"]
ui_mode = st.radio("Mode", MODES, horizontal=True, label_visibility="collapsed", key="ui_mode",
                   help="From microscope files: all three stages, starting from the .tif movies. "
                        "The two Suite2p modes start from folders that already contain "
                        "Suite2p output (suite2p/plane0). Compare: pool finished workbooks.")
st.divider()
if ui_mode == "From microscope files":
    tif_ui(settings)
elif ui_mode == "One Suite2p recording":
    single_recording_ui(settings)
elif ui_mode == "Batch of Suite2p recordings":
    batch_ui(settings)
else:
    compare_ui(settings)
