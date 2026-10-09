#!/usr/bin/env python
"""Stage 1 in bulk: run Suite2p over every TIF in a folder, one recording each.

The GUI in iNeuron-NetSync/gui/ batches stages 2-3 (CASCADE + metrics) but
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

Detection settings (defaults = the lab's locked recipe for iNeurons at 10X):
    --diameter 12 (pixels) or --diameter-um 16.4 (converted per recording from the
    TIF's own pixel size), --cellprob-threshold 0, --flow-threshold 0.4, --img meanImg.
A recording already processed with DIFFERENT detection settings is redone; one
processed with the same settings is skipped as before. The settings applied are
written to plane0/detection_settings.json.

Redoing a recording (changed settings, or --force) first moves its old suite2p/
folder aside to suite2p_previous_<time>/ (nothing is deleted). Suite2p must start
from an empty folder: run into an old one, it finds reg_outputs.npy, decides the
movie is "already registered" and skips motion correction, so the redo is not a
fresh run (seen on B05: 336 cells / STTC 0.20 in place vs 337 / 0.28 fresh).
"""
import argparse
import json
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


def um_per_pixel(tif_path):
    """Pixel size in micrometres from a MetaMorph/MetaSeries TIF, or None if absent."""
    import tifffile

    try:
        with tifffile.TiffFile(str(tif_path)) as tf:
            info = (tf.metaseries_metadata or {}).get("PlaneInfo", {})
    except Exception:
        return None
    x = info.get("spatial-calibration-x")
    if (info.get("spatial-calibration-state") and x and float(x) > 0
            and str(info.get("spatial-calibration-units", "")).lower() in ("um", "µm", "micron")):
        return float(x)
    return None


# What decides which cells Suite2p finds. A finished recording is reused only when
# all of these match what was asked for this time.
def wanted_detection(diameter_px, cellprob, flow, img):
    return {"algorithm": "cellpose", "cellpose_model": "cpsam", "img": img,
            "cellprob_threshold": float(cellprob), "flow_threshold": float(flow),
            "diameter": float(diameter_px)}


def previous_detection(plane0):
    """The detection settings a finished recording was made with (from its ops.npy),
    or None when they cannot be read (then the recording is left alone)."""
    try:
        ops = np.load(plane0 / "ops.npy", allow_pickle=True).item()
        d = ops["detection"]
        cs = d["cellpose_settings"]
        diam = np.atleast_1d(ops["diameter"]).astype(float)
        return {"algorithm": d["algorithm"], "cellpose_model": cs["cellpose_model"],
                "img": cs["img"], "cellprob_threshold": float(cs["cellprob_threshold"]),
                "flow_threshold": float(cs["flow_threshold"]), "diameter": float(diam[-1])}
    except Exception:
        return None


def same_detection(a, b):
    for k in a:
        if isinstance(a[k], float):
            if abs(a[k] - b[k]) > 1e-6:
                return False
        elif a[k] != b[k]:
            return False
    return True


def move_aside(folder: Path, stamp: str):
    """Rename an old suite2p/ output folder so a re-run starts fresh; never deletes."""
    if folder.exists():
        dest = folder.with_name(f"suite2p_previous_{stamp}")
        folder.rename(dest)
        return dest
    return None


def build_settings(suite2p, fps, tau, diameter, device, delete_bin,
                   cellprob=0.0, flow=0.4, img="meanImg"):
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
    s["detection"]["cellpose_settings"]["img"] = img
    s["detection"]["cellpose_settings"]["flow_threshold"] = float(flow)
    s["detection"]["cellpose_settings"]["cellprob_threshold"] = float(cellprob)
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
    ap.add_argument("--diameter-um", type=float, default=None,
                    help="Expected soma diameter in micrometres instead; converted to "
                         "pixels per recording from the TIF's own pixel size.")
    ap.add_argument("--cellprob-threshold", type=float, default=0.0,
                    help="Cellpose cell-probability threshold (default 0). Lower finds "
                         "more and fainter cells; higher finds fewer, clearer ones.")
    ap.add_argument("--flow-threshold", type=float, default=0.4,
                    help="Cellpose flow-error threshold (default 0.4). Higher keeps more "
                         "irregularly shaped objects; lower is stricter.")
    ap.add_argument("--img", default="meanImg",
                    choices=["meanImg", "max_proj", "max_proj / meanImg"],
                    help="Image Cellpose segments (default meanImg, the average image).")
    ap.add_argument("--profile-name", default=None,
                    help="Name of the detection profile, recorded with each recording.")
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
    no_scale = []
    for base, parts in groups.items():
        rid = rid_of[base]
        out = parent / rid
        plane0 = out / "suite2p" / "plane0"
        fps, src, n, problem = read_true_fps(parts)
        if args.fps is not None:
            fps, src = args.fps, "--fps override"
        um_px = um_per_pixel(parts[0])
        if args.diameter_um is not None:
            diam = args.diameter_um / um_px if um_px else None
        else:
            diam = args.diameter
        # Finished = Suite2p output exists AND was made with the detection settings
        # asked for now. Different settings -> redo, so a changed profile can never
        # silently reuse the old cells.
        redo = False
        done = (plane0 / "F.npy").is_file()
        if done and diam is not None:
            prev = previous_detection(plane0)
            want = wanted_detection(diam, args.cellprob_threshold, args.flow_threshold, args.img)
            if prev is not None and not same_detection(want, prev):
                done, redo = False, True
        plan.append((parts, rid, out, done, fps, src, n, diam, um_px, redo))
        flag = ("SKIP (done)" if done and not args.force
                else "REDO (detection settings changed)" if redo else "run")
        rate = f"{fps:.3f} Hz ({src})" if fps else "NO RATE -> pass --fps"
        joined = f"  [{len(parts)} parts joined]" if len(parts) > 1 else ""
        dur = f"{n / fps:6.1f}s" if fps else "     ?"
        cell = ""
        if args.diameter_um is not None:
            cell = (f"  cell {args.diameter_um:g} um = {diam:.1f} px" if diam
                    else "  NO PIXEL SIZE in this TIF")
        print(f"  {rid:<12} {n:>5} frames {dur}  {rate:<34} {flag}{joined}{cell}")
        if problem:
            print(f"      !! {problem}")
            broken.append(rid)
        if diam is None:
            no_scale.append(rid)

    if broken:
        sys.exit(f"\nRefusing to run: {', '.join(broken)} could not be verified as one "
                 f"continuous recording. Check those files before going further.")
    if no_scale:
        sys.exit(f"\n{', '.join(no_scale)}: the TIF does not record its pixel size, so a "
                 f"cell size in micrometres cannot be converted. Give the cell size in "
                 f"pixels instead (--diameter).")
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
          f"| diameter={args.diameter_um if args.diameter_um is not None else args.diameter}"
          f"{' um' if args.diameter_um is not None else ' px'} | cellprob={args.cellprob_threshold}"
          f" | flow={args.flow_threshold} | img={args.img}\n")

    results = []
    for i, (parts, rid, out, _done, fps, src, n, diam, um_px, redo) in enumerate(todo, 1):
        print("=" * 72)
        print(f"[{i}/{len(todo)}] {rid}  ({n} frames @ {fps:.3f} Hz from {src})")
        print("=" * 72, flush=True)
        t0 = time.time()
        try:
            if redo or args.force:
                # A re-run must start from an empty folder (see the module docstring).
                # The old CASCADE/metrics files move along with the old cells.
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                moved = move_aside(out / "suite2p", stamp)
                if moved:
                    print(f"  moved the earlier Suite2p output aside to {rid}/{moved.name}/")
                if args.fast_disk:
                    sc = Path(args.fast_disk).expanduser().resolve() / rid / "suite2p"
                    if move_aside(sc, stamp):
                        print("  moved the earlier scratch folder aside as well")
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
            settings = build_settings(suite2p, fps, args.tau, diam, device, args.delete_bin,
                                      cellprob=args.cellprob_threshold,
                                      flow=args.flow_threshold, img=args.img)
            suite2p.run_s2p(db=db, settings=settings)

            plane0 = out / "suite2p" / "plane0"
            is_default = (args.diameter_um is None and args.diameter == 12.0
                          and args.cellprob_threshold == 0.0 and args.flow_threshold == 0.4
                          and args.img == "meanImg")
            record = {"profile": args.profile_name or (
                          "Lippmann iNeurons, 10X (built-in default)" if is_default
                          else "custom settings given on the command line"),
                      "cellpose_model": "cpsam", "img": args.img,
                      "diameter_px": float(diam),
                      "diameter_um": (round(float(diam) * um_px, 3) if um_px else None),
                      "um_per_px": um_px, "cellprob_threshold": args.cellprob_threshold,
                      "flow_threshold": args.flow_threshold, "tau": args.tau,
                      "written": datetime.now().isoformat(timespec="seconds")}
            (plane0 / "detection_settings.json").write_text(json.dumps(record, indent=2))
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
