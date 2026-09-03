#!/usr/bin/env python
"""Stage 1 in bulk: run Suite2p over every TIF in a folder, one recording each.

The GUI in calcium-network-pipeline/gui/ batches stages 2-3 (CASCADE + metrics) but
does NOT run Suite2p. This closes that gap so a whole plate is one command instead of
N passes through the Suite2p GUI.

For each <parent>/<name>.tif it creates <parent>/<ID>/suite2p/plane0/ using the
project's locked detection recipe (Cellpose `cpsam`, img='meanImg', diameter 12) and
the recording's OWN frame rate, read from the TIF's MetaMorph per-frame timestamps --
never the value typed at acquisition. Point the GUI's "Scan a parent folder" at
<parent> afterwards and every recording appears in the batch queue.

Resumable: a recording whose plane0/F.npy already exists is skipped unless --force.

Usage (run in the suite2p env):
    python batch_suite2p.py "D:\\data\\hSyn jGcAMP8s\\WT"
    python batch_suite2p.py "D:\\data\\WT" --tau 0.25 --diameter 12
    python batch_suite2p.py "D:\\data\\WT" --force          # redo finished ones
    python batch_suite2p.py "D:\\data\\WT" --delete-bin     # reclaim ~630 MB/recording
"""
import argparse
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np


def read_true_fps(tif_path):
    """True frame rate from the TIF's own per-frame timestamps.

    Suite2p's stored `fs` is whatever was typed at acquisition and is unreliable, so
    the timestamps are the authority. Falls back to the MetaMorph "Exposure: N msec"
    header, then to None (caller must then supply --fps).
    Returns (fps, source, n_frames).
    """
    import tifffile

    with tifffile.TiffFile(str(tif_path)) as tf:
        pages = tf.pages
        n = len(pages)
        stamps = []
        for pg in pages:
            tag = pg.tags.get("DateTime")
            if tag is None:
                break
            try:
                stamps.append(datetime.strptime(tag.value, "%Y%m%d %H:%M:%S.%f"))
            except ValueError:
                break
        if len(stamps) >= 3:
            dt = np.diff([(t - stamps[0]).total_seconds() for t in stamps])
            dt = dt[dt > 0]
            if dt.size:
                return float(1.0 / np.median(dt)), "TIF timestamps", n

        desc = pages[0].tags.get("ImageDescription")
        if desc is not None:
            m = re.search(r"Exposure:\s*([0-9.]+)\s*msec", str(desc.value))
            if m and float(m.group(1)) > 0:
                return 1000.0 / float(m.group(1)), "exposure header", n
    return None, "unknown", n


def check_last_frame(tif_path):
    """Flag a truncated final frame (acquisition stopped mid-exposure).

    Such a frame shows up as a network-wide negative deflection in every trace. It
    lands inside CASCADE's NaN edge so events are unaffected, but it is worth naming.
    """
    import tifffile

    try:
        with tifffile.TiffFile(str(tif_path)) as tf:
            n = len(tf.pages)
            if n < 2:
                return None
            last = float(tf.pages[n - 1].asarray().mean())
            prev = float(tf.pages[n - 2].asarray().mean())
            if prev > 0 and last / prev < 0.9:
                return last / prev
    except Exception:
        pass
    return None


def recording_id(tif_path):
    """Short recording ID from the filename: the well (B05, C11) when present."""
    stem = tif_path.stem
    m = re.search(r"_([A-H][0-9]{2})(?:_|$)", stem)
    return m.group(1) if m else re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)[:60]


def pick_device(requested):
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    # Apple-Silicon MPS lacks float64 -> Suite2p must stay on CPU there.
    return "cpu"


def build_settings(suite2p, fps, tau, diameter, device, delete_bin):
    s = suite2p.default_settings()
    s["torch_device"] = device
    s["fs"] = float(fps)
    s["tau"] = float(tau)
    s["diameter"] = [float(diameter), float(diameter)]
    s["run"]["do_registration"] = 1
    s["run"]["do_regmetrics"] = False
    # Locked detection recipe: anatomical Cellpose on the mean image. Activity-based
    # `sparsery` misses quiet cells, and lowering its threshold adds false positives
    # that are not shape-separable -- so % active would be biased by detection.
    s["detection"]["algorithm"] = "cellpose"
    s["detection"]["cellpose_settings"]["cellpose_model"] = "cpsam"
    s["detection"]["cellpose_settings"]["img"] = "meanImg"
    s["detection"]["cellpose_settings"]["flow_threshold"] = 0.4
    s["detection"]["cellpose_settings"]["cellprob_threshold"] = 0.0
    s["detection"]["cellpose_settings"]["cellpose_chan2"] = False
    s["classification"]["use_builtin_classifier"] = False
    s["extraction"]["neuropil_coefficient"] = 0.7
    s["io"]["delete_bin"] = bool(delete_bin)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parent", help="Folder holding the .tif recordings.")
    ap.add_argument("--tau", type=float, default=0.25,
                    help="Calcium decay timescale (default 0.25, jGCaMP8s/Fluo-4).")
    ap.add_argument("--diameter", type=float, default=12.0,
                    help="Expected soma diameter in pixels (default 12).")
    ap.add_argument("--fps", type=float, default=None,
                    help="Override the frame rate for ALL recordings. Only use this "
                         "when the TIFs carry no timestamps.")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                    help="Torch device for Cellpose (default auto).")
    ap.add_argument("--force", action="store_true",
                    help="Reprocess recordings that already have a plane0/F.npy.")
    ap.add_argument("--delete-bin", action="store_true",
                    help="Delete data.bin after each run (~630 MB each). Re-detection "
                         "would then need full re-registration.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would run, touch nothing.")
    args = ap.parse_args()

    parent = Path(args.parent).expanduser().resolve()
    if not parent.is_dir():
        sys.exit(f"Not a folder: {parent}")

    tifs = sorted(p for p in parent.iterdir()
                  if p.is_file() and p.suffix.lower() in (".tif", ".tiff"))
    if not tifs:
        sys.exit(f"No .tif files directly inside {parent}")

    print(f"Parent : {parent}")
    print(f"Found  : {len(tifs)} TIF(s)\n")

    plan = []
    for tif in tifs:
        rid = recording_id(tif)
        out = parent / rid
        done = (out / "suite2p" / "plane0" / "F.npy").is_file()
        fps, src, n = read_true_fps(tif)
        if args.fps is not None:
            fps, src = args.fps, "--fps override"
        plan.append((tif, rid, out, done, fps, src, n))
        flag = "SKIP (done)" if done and not args.force else "run"
        rate = f"{fps:.3f} Hz ({src})" if fps else "NO RATE -> pass --fps"
        print(f"  {rid:<12} {n:>5} frames  {rate:<34} {flag}")

    missing_rate = [p for p in plan if p[4] is None and not (p[3] and not args.force)]
    if missing_rate:
        sys.exit("\nSome recordings have no readable frame rate. Pass --fps.")

    todo = [p for p in plan if args.force or not p[3]]
    print(f"\n{len(todo)} to process, {len(plan) - len(todo)} already done.")
    if args.dry_run:
        print("--dry-run: stopping here.")
        return
    if not todo:
        print("Nothing to do.")
        return

    import suite2p

    device = pick_device(args.device)
    print(f"suite2p {suite2p.version} | device={device} | tau={args.tau} "
          f"| diameter={args.diameter}\n")

    results = []
    for i, (tif, rid, out, _done, fps, src, n) in enumerate(todo, 1):
        print("=" * 72)
        print(f"[{i}/{len(todo)}] {rid}  ({n} frames @ {fps:.3f} Hz from {src})")
        print("=" * 72, flush=True)
        t0 = time.time()
        try:
            out.mkdir(parents=True, exist_ok=True)
            db = suite2p.default_db()
            db.update(dict(
                data_path=[str(tif.parent)],
                file_list=[str(tif)],
                look_one_level_down=False,
                input_format="tif",
                nplanes=1, nchannels=1, functional_chan=1,
                save_path0=str(out), fast_disk=str(out), save_folder="suite2p",
                batch_size=500,
            ))
            settings = build_settings(suite2p, fps, args.tau, args.diameter,
                                      device, args.delete_bin)
            suite2p.run_s2p(db=db, settings=settings)

            plane0 = out / "suite2p" / "plane0"
            iscell = np.load(plane0 / "iscell.npy")
            n_cells = int(iscell[:, 0].sum())
            ratio = check_last_frame(tif)
            note = "" if ratio is None else f"  ⚠ truncated final frame ({ratio:.2f}x)"
            secs = time.time() - t0
            print(f"\n-> {rid}: {n_cells}/{iscell.shape[0]} cells in {secs:.0f}s{note}",
                  flush=True)
            results.append((rid, "ok", f"{n_cells} cells", secs, note.strip()))
        except Exception as e:
            traceback.print_exc()
            results.append((rid, "FAILED", str(e)[:80], time.time() - t0, ""))

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    ok = 0
    for rid, status, detail, secs, note in results:
        ok += status == "ok"
        print(f"  {rid:<12} {status:<8} {detail:<20} {secs:>6.0f}s  {note}")
    print(f"\n{ok}/{len(results)} succeeded.")
    print(f"\nNext: launch the GUI and use Batch queue -> Scan a parent folder:")
    print(f"  {parent}")
    if ok != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
