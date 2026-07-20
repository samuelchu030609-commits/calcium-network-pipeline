"""Read the TRUE acquisition frame rate from a recording's raw movie file.

Suite2p's stored `ops['fs']` is unreliable; the real rate lives in the raw file's
per-frame timestamps. This reads that rate so the user doesn't have to type it.

It is a *helper* — callers surface the number for the user to confirm; nothing here
silently drives the analysis. Returns (rate_hz, source_description) on success, or
(None, reason) when it cannot determine a rate.

Supported today:
  * MetaSeries / MetaMorph and other TIFs with per-page DateTime tags -> rate from
    (n_pages - 1) / (last_timestamp - first_timestamp).
  * TIFs with an ImageJ `finterval` (seconds/frame) in their metadata.
  * ND2 only if the optional `nd2` package is installed (reports how to enable it).
"""
from __future__ import annotations

import glob
import os
from datetime import datetime
from pathlib import Path

_TIF_EXTS = ("*.tif", "*.tiff", "*.TIF", "*.TIFF")
_ND2_EXTS = ("*.nd2", "*.ND2")


def _find_raw(folder: Path):
    """Return (path, kind) for the raw movie in `folder`, or (None, None).

    Looks only at the recording folder itself (not inside suite2p/). Prefers the
    largest matching file when several exist.
    """
    tifs, nd2s = [], []
    for pat in _TIF_EXTS:
        tifs += glob.glob(os.path.join(folder, pat))
    for pat in _ND2_EXTS:
        nd2s += glob.glob(os.path.join(folder, pat))
    if tifs:
        return Path(max(tifs, key=lambda p: os.path.getsize(p))), "tif"
    if nd2s:
        return Path(max(nd2s, key=lambda p: os.path.getsize(p))), "nd2"
    return None, None


def _parse_dt(value):
    """Parse a MetaSeries-style DateTime string 'YYYYMMDD HH:MM:SS.mmm'."""
    for fmt in ("%Y%m%d %H:%M:%S.%f", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except (ValueError, TypeError):
            continue
    return None


def _rate_from_tif(path: Path):
    try:
        import tifffile
    except ImportError:
        return None, "install the 'tifffile' package to read TIF frame rates"
    try:
        with tifffile.TiffFile(path) as tif:
            n = len(tif.pages)
            if n < 2:
                return None, f"{path.name} has only {n} page(s) — no rate to infer"
            # 1) per-page DateTime timestamps (MetaSeries/MetaMorph and others)
            t0 = _parse_dt(_page_datetime(tif.pages[0]))
            t1 = _parse_dt(_page_datetime(tif.pages[n - 1]))
            if t0 and t1 and t1 > t0:
                span = (t1 - t0).total_seconds()
                if span > 0:
                    return (n - 1) / span, f"TIF timestamps ({path.name})"
            # 2) ImageJ finterval (seconds per frame)
            ij = getattr(tif, "imagej_metadata", None) or {}
            fint = ij.get("finterval")
            if fint:
                try:
                    fint = float(fint)
                    if fint > 0:
                        return 1.0 / fint, f"TIF ImageJ finterval ({path.name})"
                except (TypeError, ValueError):
                    pass
        return None, f"{path.name}: no usable per-frame timing in the TIF metadata"
    except Exception as exc:
        return None, f"could not read {path.name}: {exc}"


def _page_datetime(page):
    tag = page.tags.get("DateTime")
    return tag.value if tag is not None else None


def _rate_from_nd2(path: Path):
    try:
        import nd2  # optional
    except ImportError:
        return None, ("this is an ND2 file — install the 'nd2' package to auto-read "
                      "its rate, or enter the rate manually")
    try:
        with nd2.ND2File(path) as f:
            # experiment loops carry the sampling period (ms) for a time series
            for loop in getattr(f, "experiment", []) or []:
                params = getattr(loop, "parameters", None)
                period_ms = getattr(params, "periodMs", None) if params else None
                if period_ms:
                    return 1000.0 / float(period_ms), f"ND2 metadata ({path.name})"
        return None, f"{path.name}: no time-series period found in ND2 metadata"
    except Exception as exc:
        return None, f"could not read {path.name}: {exc}"


def rate_from_raw(recording_folder):
    """Best-effort true frame rate for the recording in `recording_folder`.

    Returns (rate_hz, source_description) or (None, reason_string).
    """
    folder = Path(recording_folder)
    if not folder.is_dir():
        return None, f"not a folder: {folder}"
    path, kind = _find_raw(folder)
    if path is None:
        return None, ("no raw movie (.tif/.tiff/.nd2) found in the recording folder — "
                      "the rate is read from the raw file's timestamps")
    if kind == "tif":
        return _rate_from_tif(path)
    return _rate_from_nd2(path)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        rate, src = rate_from_raw(arg)
        if rate:
            print(f"{arg}\n  -> {rate:.3f} Hz  [{src}]")
        else:
            print(f"{arg}\n  -> (none) {src}")
