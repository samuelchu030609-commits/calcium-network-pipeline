"""Calcium Network Pipeline — stages 2–3 GUI.

A thin Streamlit front-end over pipeline/run_pipeline.py. It does NOT re-implement
any analysis: it collects the same three things config.json needs (indicator,
frame rate, route), writes config.json for you, runs the existing orchestrator,
streams its log, and shows the friendly "Key Numbers" from the output workbook.

Stage 1 (Suite2p segmentation) is done by the user beforehand, exactly as the
README describes. This GUI covers stage 2 (CASCADE) + stage 3 (metrics) only.

Launch it with gui/run_gui.sh (macOS/Linux) or gui/run_gui.bat (Windows), which
is just `python -m streamlit run gui/app.py`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import streamlit as st

# ── Paths ──────────────────────────────────────────────────────────────────
GUI_DIR = Path(__file__).resolve().parent
REPO_ROOT = GUI_DIR.parent                      # calcium-network-pipeline/
SETTINGS_PATH = GUI_DIR / "settings.local.json"  # remembers how to run (git-ignored)

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


def pick_folder_dialog() -> str | None:
    """Native OS folder picker (works when the GUI runs on the same machine)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select the recording folder (contains suite2p/)")
        root.destroy()
        return path or None
    except Exception:
        return None


# ── Command construction ───────────────────────────────────────────────────
def build_command(settings: dict, data_dir: Path) -> tuple[list[str], dict, str | None, str]:
    """Return (argv, env, cwd, human_readable). Mirrors run.sh / run_pipeline."""
    env = os.environ.copy()
    mode = settings.get("mode", "conda")

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
                           file_name=xlsx_path.name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def show_sheet(name: str) -> None:
        # Render as an HTML table rather than st.dataframe/st.table so we don't
        # depend on pyarrow (some conda/anaconda bases ship a broken pyarrow).
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


# ── Page ───────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Calcium Network Pipeline", page_icon="🧠", layout="centered")
settings = load_settings()

st.title("🧠 Calcium Network Pipeline")
st.caption("Stages 2–3: CASCADE spike inference + network/synchrony metrics. "
           "Run Suite2p (stage 1) yourself first — this takes its output folder.")

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
    default_fps = float(ops_fs) if ops_fs else 45.0
    fps = st.number_input(
        "Acquisition frame rate (Hz) — this recording's true rate",
        min_value=0.1, max_value=1000.0, value=round(default_fps, 3), step=1.0,
        help="Read from the TIF timestamps. Suite2p's stored fs is often unreliable, "
             "so double-check this — it changes every recording.")
    if ops_fs:
        st.caption(f"ℹ️ Suite2p's stored fs is {float(ops_fs):.3g} Hz (a hint only — verify against the TIF).")

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


# ── Mode switch ────────────────────────────────────────────────────────────
ui_mode = st.radio("Mode", ["Single recording", "Batch queue"],
                   horizontal=True, label_visibility="collapsed", key="ui_mode")
st.divider()
if ui_mode == "Single recording":
    single_recording_ui(settings)
else:
    batch_ui(settings)
