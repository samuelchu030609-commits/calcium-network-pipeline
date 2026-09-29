"""Stage 3: event detection + network/synchrony metrics -> *_metrics.xlsx.

The analysis IS the finalized event_analysis_template.ipynb, which ships beside
this file (pipeline/event_analysis_template.ipynb). Rather than hand-transcribe
15 analysis cells here — which would silently drift from the parent and risk
transcription errors — this stage instantiates the template against ONE plane0
folder and executes its code cells headlessly, in a single namespace, as a
script. Syncing after a notebook change is a one-line re-copy of the .ipynb
(see docs/DEV.md "Sync boundary"), not a re-port of Python.

The template is driven by two assignments in its first cell:
    suite2p_folder = Path(".")        # -> the plane0 folder
    output_prefix  = "RUNID_metrics"  # -> names the workbook  <prefix>.xlsx
It uses cascade_spike_prob.npy if present (reading the TRUE rate from
cascade_meta.json), else falls back to dF/F0 peak detection.

Guards implemented (standing-rule instantiation guard):
  * cell["source"] handled as EITHER str OR list of lines (iterating a str yields
    characters and matches nothing -> the placeholder would survive and emit
    RUNID_metrics.* junk at exit 0). Joined to a single string first.
  * The substitution is HARD-ASSERTED: if the "RUNID_metrics" placeholder survives
    anywhere, we raise before executing any cell.
  * Any exception during execution names the failing cell and raises (stronger than
    scanning nbconvert outputs for output_type=="error").
  * IPython.display is stubbed and the repo's pipeline_fixes is pre-loaded, so the
    headless run reproduces every COMPUTED value without a Jupyter kernel and
    without depending on the parent project's absolute path.

Contract the orchestrator depends on (keep this signature stable):

    run_metrics(plane0_dir, config) -> str

  - plane0_dir : plane0 to read (contains cascade_spike_prob.npy + cascade_meta.json
                 for cascade routes)
  - config     : RecordingConfig (pipeline.config) — indicator, route, fps,
                 neuropil_coeff
  - returns    : path to the written <prefix>.xlsx  (or, if openpyxl is absent, the
                 <prefix>_sheets/ CSV directory that the notebook falls back to)

Output sheets:
  - per-cell : event rate, % active, STTC_to_population
  - network  : STTC_excess_over_chance (+ z, p), coactive fraction,
               FDR connectivity, guarded assembly detection
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import types
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_NOTEBOOK = os.path.join(_HERE, "event_analysis_template.ipynb")
_PLACEHOLDER = "RUNID_metrics"


def _recording_id(plane0_dir: str) -> str:
    """RUN id from the recording folder name (plane0/../.. basename)."""
    rec_dir = os.path.dirname(os.path.dirname(os.path.abspath(plane0_dir)))
    name = os.path.basename(rec_dir) or "recording"
    return f"{name}_metrics"


def run_metrics(plane0_dir: str, config) -> str:
    """Execute the metrics template against plane0_dir; return the output path.

    `config` is a RecordingConfig; its neuropil_coeff is passed through to the
    notebook (fps is read from ops['fs'] / cascade_meta.json inside the template,
    which is the authoritative rate for each signal path).
    """
    plane0_dir = os.path.abspath(plane0_dir)
    if not os.path.isfile(os.path.join(plane0_dir, "F.npy")):
        raise FileNotFoundError(f"No F.npy in {plane0_dir}; not a Suite2p plane0 folder.")
    if not os.path.isfile(_NOTEBOOK):
        raise FileNotFoundError(f"Metrics template not found: {_NOTEBOOK}")

    run_id = _recording_id(plane0_dir)
    nb = json.load(open(_NOTEBOOK))
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]

    # --- instantiate: substitute folder + prefix + neuropil, str-or-list safe ---
    sources = []
    for c in code_cells:
        s = c["source"]
        sources.append(s if isinstance(s, str) else "".join(s))   # never iterate a str

    subbed = False
    for i, txt in enumerate(sources):
        if 'output_prefix = "RUNID_metrics"' in txt or 'suite2p_folder = Path(".")' in txt:
            txt = txt.replace('output_prefix = "RUNID_metrics"', f'output_prefix = "{run_id}"')
            txt = txt.replace('suite2p_folder = Path(".")', f'suite2p_folder = Path(r"{plane0_dir}")')
            # pass the config's neuropil coefficient through (template default is None -> ops)
            if getattr(config, "neuropil_coeff", None) is not None:
                txt = txt.replace("neuropil_coeff = None",
                                  f"neuropil_coeff = {float(config.neuropil_coeff)}")
            sources[i] = txt
            subbed = True
    if not subbed:
        raise RuntimeError("Could not locate the template's settings assignments to substitute.")

    joined = "\n".join(sources)
    if _PLACEHOLDER in joined:
        raise RuntimeError(
            f"Placeholder {_PLACEHOLDER!r} survived substitution -- refusing to run "
            f"(would emit {_PLACEHOLDER}.* junk at exit 0)."
        )

    # --- environment: headless matplotlib + stubbed Jupyter display ---
    # Force the non-interactive Agg backend BEFORE any notebook cell imports
    # matplotlib. Otherwise matplotlib auto-detects a backend and probes the
    # (stubbed) IPython module for version_info/get_ipython, raising AttributeError
    # inside the QC-plot cell and silently skipping the documented baseline QC png.
    # Agg needs no display and no IPython, so the QC png is written headlessly.
    os.environ.setdefault("MPLBACKEND", "Agg")
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
    except Exception:
        pass
    # The notebook's cell 0 does `from IPython.display import display`; provide a no-op
    # so that import succeeds without a real Jupyter kernel. matplotlib's canvas init
    # (backend_bases._fix_ipython_backend2gui) still probes the stubbed IPython module
    # for get_ipython() and version_info even under Agg, so both are supplied:
    #   get_ipython() -> None       => "not in a shell", plain display hook
    #   version_info >= (8, 24)     => skip the legacy backend2gui path entirely
    _ipy = types.ModuleType("IPython"); _disp = types.ModuleType("IPython.display")
    _disp.display = lambda *a, **k: None
    _ipy.display = _disp
    _ipy.get_ipython = lambda *a, **k: None
    _ipy.version_info = (8, 24, 0, "")
    sys.modules.setdefault("IPython", _ipy)
    sys.modules.setdefault("IPython.display", _disp)
    # ensure the template's `import pipeline_fixes as pf` resolves to THIS repo's copy,
    # not the parent project's hardcoded path in cell 0's sys.path.insert.
    if "pipeline_fixes" not in sys.modules:
        sys.path.insert(0, _HERE)
        import pipeline_fixes  # noqa: F401

    # --- execute all code cells in one namespace, from the plane0 folder ---
    prev_cwd = os.getcwd()
    os.chdir(plane0_dir)
    # _TEMPLATE_PATH / _REPO_ROOT let the template stamp fingerprints of the exact code
    # (pipeline_fixes.py + this template) into the PROVENANCE file, as the parent runner does.
    ns = {"__name__": "__main__", "display": lambda *a, **k: None,
          "_TEMPLATE_PATH": _NOTEBOOK, "_REPO_ROOT": _HERE}
    try:
        for i, txt in enumerate(sources):
            try:
                exec(compile(txt, f"<metrics cell {i}>", "exec"), ns)
            except Exception as e:
                raise RuntimeError(f"metrics template failed in code cell {i}: {e}") from e
    finally:
        os.chdir(prev_cwd)

    # --- resolve the written output path ---
    xlsx = os.path.join(plane0_dir, f"{run_id}.xlsx")
    if os.path.isfile(xlsx):
        return xlsx
    sheets = os.path.join(plane0_dir, f"{run_id}_sheets")   # openpyxl-absent fallback
    if os.path.isdir(sheets):
        print(f"[run_metrics] openpyxl absent -> wrote CSV sheets: {sheets}")
        return sheets
    raise RuntimeError(
        f"metrics template ran but produced neither {xlsx} nor {sheets}. "
        f"Check SAVE_OUTPUTS in the template."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Run metrics on a Suite2p plane0 folder.")
    ap.add_argument("plane0_dir")
    args = ap.parse_args()
    # standalone use: load config from the recording folder (plane0/../..)
    from .config import load_config
    rec_dir = os.path.dirname(os.path.dirname(os.path.abspath(args.plane0_dir)))
    print(run_metrics(args.plane0_dir, load_config(rec_dir)))


if __name__ == "__main__":
    main()
