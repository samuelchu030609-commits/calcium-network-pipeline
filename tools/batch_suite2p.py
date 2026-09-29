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

Several positions per well: when a folder holds <well>_s1, _s2 ... of the same well, each
position is its own recording and output folder (C02_s1, C02_s2 ...). A folder with one
position per well keeps plain well names (C02), as before.

Split recordings: MetaMorph caps a TIF near 2 GB, so a long stream is saved as
<name>.tif + <name>-file002.tif (+ -file003 ...). Those parts are ONE recording. They are
joined in order into a single Suite2p run, after checking from the per-frame timestamps
that each part starts one frame interval after the previous one ends. Run separately,
the parts would share a well ID and the second would overwrite the first.

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


def frame_stamps(tif_path):
    """Per-frame MetaMorph timestamps of one TIF: (stamps, n_frames, first-page desc).

    `stamps` is shorter than n_frames (possibly empty) when a page lacks a readable stamp.
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
        desc = pages[0].tags.get("ImageDescription")
        return stamps, n, (None if desc is None else str(desc.value))


def read_true_fps(parts):
    """True frame rate of one recording (a list of its TIF parts, in order).

    Suite2p's stored `fs` is whatever was typed at acquisition and is unreliable, so
    the timestamps are the authority. Falls back to the MetaMorph "Exposure: N msec"
    header, then to None (caller must then supply --fps).
    Returns (fps, source, n_frames, problem). `problem` is None, or a sentence saying
    why the parts are not one continuous recording -- the caller must then refuse it.
    """
    per_part = [frame_stamps(t) for t in parts]
    n = sum(p[1] for p in per_part)
    complete = all(len(st) == nf and nf >= 1 for st, nf, _ in per_part)
    stamps = [t for st, _, _ in per_part for t in st] if complete else per_part[0][0]
    fps, src = None, "unknown"
    if len(stamps) >= 3:
        dt = np.diff([(t - stamps[0]).total_seconds() for t in stamps])
        pos = dt[dt > 0]
        if pos.size:
            fps, src = float(1.0 / np.median(pos)), "TIF timestamps"
    if fps is None and per_part[0][2] is not None:
        m = re.search(r"Exposure:\s*([0-9.]+)\s*msec", per_part[0][2])
        if m and float(m.group(1)) > 0:
            fps, src = 1000.0 / float(m.group(1)), "exposure header"

    problem = None
    if len(parts) > 1:
        if not complete:
            problem = "split recording without full timestamps -- cannot prove the parts join"
        elif fps is None:
            problem = "split recording with no readable frame rate"
        else:
            frame = 1.0 / fps
            for (a, _, _), (b, _, _), name in zip(per_part, per_part[1:], parts[1:]):
                gap = (b[0] - a[-1]).total_seconds()
                if not 0.5 * frame <= gap <= 1.5 * frame:
                    problem = (f"{name.name} starts {gap:.3f}s after the previous part ends "
                               f"(one frame = {frame:.3f}s) -- not a continuation")
                    break
    return fps, src, n, problem


PART_RE = re.compile(r"-file(\d+)$", re.IGNORECASE)


def group_parts(tifs):
    """Group MetaMorph split files into recordings: {base stem: [tif parts in order]}.

    <name>.tif is part 1; <name>-file002.tif, -file003 ... follow in number order. Plain
    sorting gets this wrong ('-' sorts before '.', so -file002 would come first).
    """
    groups = {}
    for t in tifs:
        m = PART_RE.search(t.stem)
        base = t.stem[:m.start()] if m else t.stem
        groups.setdefault(base, []).append((int(m.group(1)) if m else 1, t))
    return {b: [t for _, t in sorted(v)] for b, v in sorted(groups.items())}


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


def recording_id(stem, with_site=False):
    """Short recording ID from the filename stem: the well (B05, C11) when present.

    with_site=True appends the stage position (C02_s3) - used only when a folder holds
    several positions of the same well, so single-position plates keep their old names.
    """
    m = re.search(r"_([A-H][0-9]{2})(?:_s([0-9]+))?(?:_|$)", stem)
    if not m:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)[:60]
    return f"{m.group(1)}_s{m.group(2)}" if with_site and m.group(2) else m.group(1)


def assign_ids(bases):
    """{base stem: output folder ID}. Positions get their own ID (C02_s1, C02_s2 ...)
    only for wells that were filmed at more than one position in this folder."""
    per_well = {}
    for b in bases:
        per_well.setdefault(recording_id(b), []).append(b)
    return {b: recording_id(b, with_site=len(per_well[recording_id(b)]) > 1) for b in bases}


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
    ap.add_argument("--fast-disk", default=None, metavar="PATH",
                    help="Put Suite2p's scratch data.bin on a FAST local disk while the "
                         "results still land beside the TIFs. Use this whenever the "
                         "recordings live on a USB/flash/network drive -- registration "
                         "and detection hammer data.bin, and slow media dominates the "
                         "runtime. Needs ~700 MB free per concurrent recording.")
    args = ap.parse_args()

    parent = Path(args.parent).expanduser().resolve()
    if not parent.is_dir():
        sys.exit(f"Not a folder: {parent}")

    # "._name.tif" files are macOS metadata sidecars written on exFAT/FAT drives, not movies.
    tifs = sorted(p for p in parent.iterdir()
                  if p.is_file() and p.suffix.lower() in (".tif", ".tiff")
                  and not p.name.startswith("._"))
    if not tifs:
        sys.exit(f"No .tif files directly inside {parent}")

    groups = group_parts(tifs)
    print(f"Parent : {parent}")
    print(f"Found  : {len(tifs)} TIF(s) = {len(groups)} recording(s)\n")

    # Two different recordings with the same ID would write into the same folder.
    rid_of = assign_ids(groups)
    ids = {}
    for base in groups:
        ids.setdefault(rid_of[base], []).append(base)
    clash = {r: b for r, b in ids.items() if len(b) > 1}
    if clash:
        for r, b in clash.items():
            print(f"  ID {r} is claimed by: " + " | ".join(b))
        sys.exit("\nDifferent recordings map to the same output folder. Move one set "
                 "into its own folder and run each folder separately.")

    plan = []
    broken = []
    for base, parts in groups.items():
        rid = rid_of[base]
        out = parent / rid
        done = (out / "suite2p" / "plane0" / "F.npy").is_file()
        fps, src, n, problem = read_true_fps(parts)
        if args.fps is not None:
            fps, src = args.fps, "--fps override"
        plan.append((parts, rid, out, done, fps, src, n))
        flag = "SKIP (done)" if done and not args.force else "run"
        rate = f"{fps:.3f} Hz ({src})" if fps else "NO RATE -> pass --fps"
        joined = f"  [{len(parts)} parts joined]" if len(parts) > 1 else ""
        dur = f"{n / fps:6.1f}s" if fps else "     ?"
        print(f"  {rid:<12} {n:>5} frames {dur}  {rate:<34} {flag}{joined}")
        if problem:
            print(f"      !! {problem}")
            broken.append(rid)

    if broken:
        sys.exit(f"\nRefusing to run: {', '.join(broken)} could not be verified as one "
                 f"continuous recording. Check those files before going further.")
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
    for i, (parts, rid, out, _done, fps, src, n) in enumerate(todo, 1):
        print("=" * 72)
        print(f"[{i}/{len(todo)}] {rid}  ({n} frames @ {fps:.3f} Hz from {src})")
        print("=" * 72, flush=True)
        t0 = time.time()
        try:
            out.mkdir(parents=True, exist_ok=True)
            # Scratch (data.bin) can live apart from the results: on slow media the
            # repeated data.bin reads during registration/detection dominate runtime.
            if args.fast_disk:
                scratch = Path(args.fast_disk).expanduser().resolve() / rid
                scratch.mkdir(parents=True, exist_ok=True)
            else:
                scratch = out
            db = suite2p.default_db()
            db.update(dict(
                data_path=[str(parts[0].parent)],
                file_list=[str(t) for t in parts],   # in order; Suite2p concatenates
                look_one_level_down=False,
                input_format="tif",
                nplanes=1, nchannels=1, functional_chan=1,
                save_path0=str(out), fast_disk=str(scratch), save_folder="suite2p",
                batch_size=500,
            ))
            settings = build_settings(suite2p, fps, args.tau, args.diameter,
                                      device, args.delete_bin)
            suite2p.run_s2p(db=db, settings=settings)

            plane0 = out / "suite2p" / "plane0"
            iscell = np.load(plane0 / "iscell.npy")
            n_cells = int(iscell[:, 0].sum())
            ratio = check_last_frame(parts[-1])
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
