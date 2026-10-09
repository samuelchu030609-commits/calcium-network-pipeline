# How to install and use the Calcium Network Pipeline

This guide takes you from **nothing installed** to **analysed recordings**. You do not
need to know anything about programming or GitHub. Follow the steps in order. After
each step, the box **✅ You should see** tells you whether it worked.

**What the pipeline does:** you give it a folder of calcium-imaging movies (`.tif`
files from the microscope). For each recording it finds the cells (**Suite2p** with
**Cellpose**), works out when each cell fired (**CASCADE** spike inference), and measures
activity and network synchrony (event rates, STTC synchrony, network bursts). You get
one Excel workbook per recording. A "Key Numbers" sheet in each one explains every value
in plain language.

---

## Before you start

| You need | Details |
|---|---|
| A computer | **Windows 10 or 11** (64-bit, Intel/AMD processor) **or an Apple Silicon Mac** (M1 or newer; Intel Macs are not supported). 16 GB of memory (RAM) recommended. No graphics card needed. |
| Disk space | **About 15 GB** for the program, plus room for your data. While a recording is being processed, it temporarily needs about as much extra space as the `.tif` file itself. |
| Internet | Only during installation (about 6 GB is downloaded). Analysis works offline. |
| Time | **Windows: 30 minutes to 3 hours**, mostly waiting (antivirus software slows it down). **Mac: 20–40 minutes.** You can leave it running. |
| Administrator password | **Not needed.** If Windows or macOS ever asks for one during this guide, click **Cancel**: something is wrong, see [Troubleshooting](#troubleshooting). |

**Your recordings** must be `.tif` movies, one file per recording. Movies saved by
MetaMorph/MetaSeries in several parts (`name.tif` + `name-file002.tif`) are fine; they
are joined automatically. Other formats (`.nd2`, `.czi`, `.lif`, …) must first be
exported as TIF from the microscope software or from Fiji (*File → Save As → Tiff*).

**Supported indicators:** jGCaMP8s, jGCaMP8f, and Fluo-4 (dye). For any other
indicator, contact us first: the spike-inference model has to match the indicator.

---

## Windows

### Step W1 — Download the pipeline

1. Click this link: **<https://github.com/samuelchu030609-commits/calcium-network-pipeline/archive/refs/heads/main.zip>**
   A file named `calcium-network-pipeline-main.zip` downloads (about 1 MB). No GitHub
   account is needed.
2. Open your **Downloads** folder. **Right-click** the ZIP file → **Properties**. At the
   bottom of the *General* tab, tick **Unblock** (if it is there) → **OK**.
   *(This tells Windows the file is safe and avoids security warnings later.)*
3. Right-click the ZIP file again → **Extract All…** → **Extract**.

> ✅ **You should see** a folder named `calcium-network-pipeline-main`. Inside it are
> files such as `INSTALL_WINDOWS.bat`, `HOW_TO_INSTALL.md` and `README.md`.

### Step W2 — Run the installer

1. Open the `calcium-network-pipeline-main` folder.
2. **Double-click `INSTALL_WINDOWS.bat`.**
   (If Windows hides file endings, it shows as `INSTALL_WINDOWS` with a gear icon.)
3. If a blue box says **"Windows protected your PC"**, click **More info** → **Run anyway**.
   If a box asks *"Do you want to run this file?"*, click **Run**.
4. A black window opens and shows the progress in 7 steps. **Leave it open.** Some steps
   print nothing for a long time; that is normal. Step 3 ("Environments") is the longest.

> ✅ **You should see**, at the end, in green:
> `INSTALLATION COMPLETE - self-test PASSED.`
> and a new **Calcium Pipeline** icon on your Desktop. Press any key to close the window.
>
> ❌ **If it says `STOPPED:`** the line after it says why, in plain words. See
> [Troubleshooting](#troubleshooting). The installer is safe to run again: it continues
> where it stopped.

**Where things go:** the program is installed in `C:\CalciumPipeline`, or in
`C:\Users\<you>\CalciumPipeline` if your PC does not allow the first. Two helper folders
are created in `C:\Users\<you>`: `Cascade` and `.cellpose`. Nothing else on the PC is
changed, and Python programs you may already have are not touched.

You can now delete the downloaded ZIP and the extracted folder. The installer copied
everything it needs.

➡️ Continue with [Your first analysis](#your-first-analysis).

---

## Mac

### Step M1 — Download the pipeline

1. Click this link: **<https://github.com/samuelchu030609-commits/calcium-network-pipeline/archive/refs/heads/main.zip>**
2. Open your **Downloads** folder. Safari usually unzips it by itself. If you see only a
   `.zip` file, double-click it.

> ✅ **You should see** a folder named `calcium-network-pipeline-main` containing
> `INSTALL_MAC.sh`, `HOW_TO_INSTALL.md` and `README.md`.

### Step M2 — Run the installer

The Mac installer is started from **Terminal**, the Mac's text-command window. You only
type one word.

1. Open **Terminal**: press **⌘ Command + Space**, type `Terminal`, press **Return**.
2. In the Terminal window, type `bash` followed by **one space**. Do not press Return yet.
3. **Drag** the file `INSTALL_MAC.sh` from the Finder window **into the Terminal window**.
   Its location is filled in for you, so the line now looks like
   `bash /Users/you/Downloads/calcium-network-pipeline-main/INSTALL_MAC.sh`.
4. Press **Return**.
5. **Leave the window open** while it works through 7 steps.

> ✅ **You should see**, at the end, in green:
> `INSTALLATION COMPLETE - self-test PASSED.`
> and a new **Calcium Pipeline** icon on your Desktop.
>
> ❌ **If it says `STOPPED`**, see [Troubleshooting](#troubleshooting). It is safe to run
> again: it continues where it stopped.

**Where things go:** `~/CalciumPipeline` (the program), plus `~/Cascade` and `~/.cellpose`
in your home folder. Nothing else is changed. If you already have Python or conda, they
are not touched.

---

## Your first analysis

### Step 1 — Open the program

**Double-click Calcium Pipeline** on the Desktop.

- A black (Windows) or white (Mac) text window opens: this is the program's engine room.
  **Keep it open while you work.** Closing it closes the program.
- After a few seconds your web browser opens a page titled **Calcium Network Pipeline**.
  It runs **only on your computer**. Nothing is uploaded to the internet.
- *Mac, first time only:* macOS may ask whether Terminal may access a folder (Desktop,
  Documents, an external drive). Click **Allow**.

> ✅ **You should see** the page with four choices at the top. **From microscope files**
> is selected.

### Step 2 — Analyse a folder of recordings

1. **Pick the folder.** Click **Browse…** and choose the folder that *directly* contains
   your `.tif` movies (for example one plate). The page confirms how many `.tif` files it
   found.
2. **Choose the indicator** that was imaged (jGCaMP8s, jGCaMP8f or Fluo-4).
   *Getting this right matters:* each indicator uses its own calibrated model.
3. **Click "Check the folder first".** It reads every file and lists one row per
   recording, with the **frame rate taken from the file's own timestamps**. Nothing is
   changed yet.
   - Rows ending in `run` will be analysed. Rows ending in `SKIP (done)` were already
     analysed earlier.
   - **"NO RATE"** means your files carry no timestamps (common for TIFs not saved by
     MetaMorph). Open **Options**, type the frame rate you acquired at (in Hz), and click
     Check again.
4. **Click "Start the analysis".** Progress appears on the page and updates by itself.

**How long it takes** for 3-minute movies (1800 frames, 1024 × 1024 pixels). Most of the
time goes to motion correction and cell detection:

| Computer | Per recording | 16 recordings | 64 recordings |
|---|---|---|---|
| Apple Silicon Mac (cell detection runs on its built-in graphics chip) | about 5–6 minutes | about 1½ hours | about 6 hours (one night) |
| Windows PC (cell detection runs on the processor) | about 45 minutes (30–60) | about 12 hours | about 2 days |

*The Mac numbers are measured: 64 recordings took 5 h 51 min on an M2 Pro MacBook. The
Windows numbers are estimated from measuring cell detection alone on recording B05, which
took 1–2 minutes on the Mac's graphics chip and about 40 minutes on its processor. Both
found the same cells (434 vs 435, 99% the same pixels), so only the speed differs.*
On Windows, start big folders before a weekend, or split them across several PCs (each PC
analyses its own folder).

**You can close the browser tab** and the analysis keeps running. To check on it, open
**Calcium Pipeline** again and pick the same folder. Keep the computer switched on. The
program stops it from going to sleep by itself, but **a laptop still sleeps when its lid
is closed**, so leave the lid open and the charger plugged in.

> ✅ **You should see**, when it is done:
> `The last analysis of this folder has finished.` with one `ok` row per recording, and a
> **Results** section showing each recording's **Key Numbers**.

### Step 3 — Find your results

Click **📂 Open the RESULTS folder**. It is a new folder inside your recordings folder:

| File | What it is |
|---|---|
| `<well>_metrics.xlsx` | **The results for one recording.** Start with the **Key Numbers** sheet: every number has a plain-language explanation beside it. The other sheets hold per-cell values, synchrony, network bursts, and statistical-power notes. |
| `<well>_metrics_baseline_qc.png` | A quality-control picture: a few cells' traces with the fitted baseline (red). The red line should follow the resting level of each trace. |
| `run_log_<date>.txt` | The full record of the run. Send this to us if anything looks wrong. |

Next to RESULTS, each recording also gets its own folder (e.g. `B05/suite2p/plane0/`)
with Suite2p's complete output. You can open it in the Suite2p program to inspect the
detected cells (see [For advanced users](#for-advanced-users)).

### Comparing groups (optional)

The **Compare recordings** choice at the top of the page pools finished workbooks into
one comparison workbook. You type a group label (e.g. `WT`, `KCNT1`) beside each
recording, and it reports per-group means and a two-group contrast.

---

## Updating to a newer version

Download the ZIP again (Step W1 / M1) and run the installer again (Step W2 / M2). It
takes a few minutes: it only replaces the program code and keeps everything else.
**Your recordings and results are never touched.**

## Running the self-test again

If you suspect something is broken, re-run the installer. It skips everything already
installed and repeats the self-test at the end. The self-test checks every package
version, analyses a synthetic recording with known co-firing cells, and runs all three
stages on a small synthetic movie.

## Uninstalling

Delete these folders and the Desktop icon:
- Windows: `C:\CalciumPipeline` (or `C:\Users\<you>\CalciumPipeline`),
  `C:\Users\<you>\Cascade`, `C:\Users\<you>\.cellpose`
- Mac: `~/CalciumPipeline`, `~/Cascade`, `~/.cellpose`
  (in Finder: **Go → Home**; press **⌘ Shift .** to see hidden folders such as `.cellpose`)

---

## Troubleshooting

The installer writes everything to `install_log.txt` inside the install folder. Please
send that file along with any question.

| What you see | What it means / what to do |
|---|---|
| **"Windows protected your PC"** | Click **More info** → **Run anyway**. To avoid it, do the **Unblock** step (W1.2) before extracting. |
| Windows asks for an **administrator password** | Click **Cancel**. Nothing in this guide needs one. If it happens again, tell us which step. |
| **`STOPPED: Cannot reach the internet`** | The PC is offline, or the lab network blocks the download sites. Ask IT to allow `conda.anaconda.org`, `pypi.org`, `files.pythonhosted.org`, `github.com` and `drive.switch.ch`. |
| **`STOPPED: Could not download the CASCADE model`** | The CASCADE model server (`drive.switch.ch`) is blocked. Ask IT to allow it, or ask us for the two model folders and copy them into `Cascade\Pretrained_models`. Then run the installer again. |
| **`STOPPED: Could not build the … environment`** / **`Could not install packages`** | Usually a download that broke halfway. Run the installer again. If it fails twice at the same place, send us `install_log.txt`. |
| Installing **TensorFlow** fails with *"No such file or directory"* (Windows) | The install folder path is too long for Windows. Ask IT to either allow creating `C:\CalciumPipeline`, or enable "Win32 long paths". Then run again. |
| The installer **seems frozen** | It is almost always still working: antivirus checks each of the tens of thousands of files it writes. Wait. Only if nothing at all changes for over an hour, close it and run it again; it resumes. |
| **`STOPPED: … contains a space or an accented letter`** | Your Windows user name has a space, and `C:\CalciumPipeline` could not be created. Ask IT to allow creating that folder. |
| **`The self-test FAILED`** | The lines marked `FAIL` above it say which part. Send us `install_log.txt`. |
| The browser page **does not open** | Wait 30 seconds, then type `localhost:8501` in your browser's address bar. |
| **Check the folder** says **"NO RATE"** | Your TIFs carry no timestamps. Type the acquisition frame rate under **Options**. |
| **Check** says files **"could not be verified as one continuous recording"** | Parts of a split recording (`-file002`) do not join up in time: a part is missing or belongs to another recording. Check the files in that folder. |
| **"No `.tif` files directly inside this folder"** | Pick the folder that holds the movies themselves, not a folder above it. |
| A recording shows **0 cells** / **FAILED: no ROIs were found** | Suite2p found no cells. This is typical of fields at the well edge or with no neurons in view. Check the movie in Fiji. |
| A **red WARNING about detection settings** | The Suite2p output was not made with this pipeline's cell-detection settings, so the numbers are not comparable with other runs. It cannot happen in **From microscope files** mode. |

---

## For advanced users

- **Command line / overnight runs.** The page's "From microscope files" mode runs
  `tools/analyze_folder.py` with the install's own Python. You can run it directly:
  - Windows: `C:\CalciumPipeline\conda\envs\analysis\python.exe C:\CalciumPipeline\code\tools\analyze_folder.py "D:\plate" --indicator jgcamp8s --delete-bin`
  - Mac: `~/CalciumPipeline/conda/envs/analysis/bin/python ~/CalciumPipeline/code/tools/analyze_folder.py ~/data/plate --indicator jgcamp8s --delete-bin`

  Add `--dry-run` to only list the recordings. `--fps 10` sets the frame rate for TIFs
  without timestamps.
- **Inspect detected cells in Suite2p's own program:** run the `suite2p` environment's
  Python with `-m suite2p` and open `<recording>/suite2p/plane0/stat.npy`. This needs the
  recording's `data.bin`, so untick *Delete Suite2p's large temporary file* under
  **Options** before the analysis.
- **Starting from your own Suite2p output** (already-segmented recordings): use the
  *One Suite2p recording* or *Batch of Suite2p recordings* modes. Your detection
  settings must match ours ([docs/SUITE2P_SETTINGS.md](docs/SUITE2P_SETTINGS.md)), or
  the numbers are not comparable.
- **Exact versions** installed: see `install/install_windows.ps1` / `install/install_mac.sh`.
  These are the versions the reference numbers were produced with. Changing them, torch
  above all, can change which cells are detected.
- Methods, outputs and design: [docs/TECHNICAL_README.md](docs/TECHNICAL_README.md).
