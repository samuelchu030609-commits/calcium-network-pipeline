#!/usr/bin/env python
"""Quick preview of cell detection on ONE recording, before a whole folder is run.

Builds the detection image the way Suite2p does (frames binned in time, then the
average image or the high-pass-filtered maximum) and runs Suite2p's own Cellpose
step (suite2p.detection.anatomical.select_rois) with the settings to be tried.
It skips motion correction and uses only the first frames, so the cell count is
close to, not identical with, what the full run finds; the outlines show whether
the settings suit the cells.

Writes an .npz with the image, the label image of detected cells and a summary,
which the GUI draws. Run in the `suite2p` environment:

    python tools/preview_detection.py movie.tif --out preview.npz --diameter 12
    python tools/preview_detection.py movie.tif --out preview.npz --diameter-um 16 --area small
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_suite2p import um_per_pixel, read_true_fps  # noqa: E402

AREAS = {"small": 256, "quarter": 512, "whole": None}


def binned_frames(tif: Path, n: int, size: int | None, bin_size: int, keep_movie: bool):
    """Read up to n frames one at a time, crop the centre, average in bins of bin_size.

    Returns (mean of the bins, the binned movie or None, frames used, crop origin).
    Frame by frame so a full field of view never sits in memory all at once; the
    binned movie is kept only when the max projection is needed.
    """
    import tifffile

    with tifffile.TiffFile(str(tif)) as tf:
        k = min(n, len(tf.pages))
        k -= k % bin_size
        ly, lx = tf.pages[0].shape[:2]
        s = (min(size, ly, lx) if size else None)
        y0, x0 = ((ly - s) // 2, (lx - s) // 2) if s else (0, 0)
        y1, x1 = (y0 + s, x0 + s) if s else (ly, lx)
        total = np.zeros((y1 - y0, x1 - x0), np.float64)
        acc = np.zeros_like(total)
        movie = []
        for i in range(k):
            acc += tf.pages[i].asarray()[y0:y1, x0:x1]
            if (i + 1) % bin_size == 0:
                b = (acc / bin_size).astype(np.float32)
                total += b
                if keep_movie:
                    movie.append(b)
                acc[:] = 0
    nb = k // bin_size
    return (total / nb).astype(np.float32), (np.stack(movie) if keep_movie else None), k, (y0, x0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tif", help="The recording's (first) .tif file.")
    ap.add_argument("--out", required=True, help="Where to write the .npz result.")
    ap.add_argument("--diameter", type=float, default=12.0, help="Cell size in pixels.")
    ap.add_argument("--diameter-um", type=float, default=None,
                    help="Cell size in micrometres (converted with the TIF's pixel size).")
    ap.add_argument("--cellprob-threshold", type=float, default=0.0)
    ap.add_argument("--flow-threshold", type=float, default=0.4)
    ap.add_argument("--img", default="meanImg", choices=["meanImg", "max_proj", "max_proj / meanImg"])
    ap.add_argument("--fps", type=float, default=None, help="Only for TIFs without timestamps.")
    ap.add_argument("--tau", type=float, default=0.25)
    ap.add_argument("--frames", type=int, default=600, help="How many frames to use.")
    ap.add_argument("--area", choices=sorted(AREAS), default="whole",
                    help="small = centre 256x256 px, quarter = centre 512x512, whole = all.")
    args = ap.parse_args()

    tif = Path(args.tif)
    t0 = time.time()
    um_px = um_per_pixel(tif)
    if args.diameter_um is not None:
        if not um_px:
            sys.exit("This TIF does not record its pixel size: give the cell size in pixels.")
        diam = args.diameter_um / um_px
    else:
        diam = args.diameter
    fps = args.fps or read_true_fps([tif])[0]
    if not fps:
        sys.exit("No frame rate in this TIF: give it with --fps.")

    # Same binning and images as suite2p.detection.detect.detection_wrapper.
    from suite2p.detection import anatomical
    from suite2p.detection.utils import temporal_high_pass_filter
    import torch

    bin_size = int(max(1, np.round(args.tau * fps)))
    need_max = args.img != "meanImg"
    mean_img, binned, n_used, (y0, x0) = binned_frames(tif, args.frames, AREAS[args.area],
                                                       bin_size, need_max)
    max_proj = (temporal_high_pass_filter(binned, width=100).max(axis=0) if need_max
                else mean_img)       # unused by Cellpose when segmenting the average image
    cs = {"cellpose_model": "cpsam", "img": args.img, "highpass_spatial": 0,
          "flow_threshold": args.flow_threshold, "cellprob_threshold": args.cellprob_threshold,
          "params": None, "params_chan2": None}
    t1 = time.time()
    _, stats = anatomical.select_rois(mean_img, max_proj, settings=cs,
                                      diameter=[diam, diam], device=torch.device("cpu"))
    secs_detect = time.time() - t1

    labels = np.zeros(mean_img.shape, np.int32)
    sizes = []
    for i, s in enumerate(stats, 1):
        labels[s["ypix"], s["xpix"]] = i
        sizes.append(2 * np.sqrt(len(s["ypix"]) / np.pi))   # equal-area circle
    shown = {"meanImg": mean_img, "max_proj": max_proj}.get(
        args.img, np.log(np.maximum(1e-3, max_proj / np.maximum(1e-3, mean_img))))
    summary = {
        "n_cells": len(stats), "diameter_px": float(diam), "um_per_px": um_px,
        "median_cell_px": float(np.median(sizes)) if sizes else None,
        "frames_used": int(n_used), "fps": float(fps), "area": args.area,
        "crop_origin": [int(y0), int(x0)], "shape": list(mean_img.shape),
        "seconds_detection": round(secs_detect, 1), "seconds_total": round(time.time() - t0, 1),
        "settings": {"cellprob_threshold": args.cellprob_threshold,
                     "flow_threshold": args.flow_threshold, "img": args.img},
    }
    np.savez_compressed(args.out, image=shown.astype(np.float32), labels=labels,
                        summary=json.dumps(summary))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
