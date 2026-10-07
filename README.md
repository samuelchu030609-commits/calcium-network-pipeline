# Calcium Network Pipeline

Turns **calcium-imaging movies** of cultured neurons into **activity and network-synchrony
numbers**, one Excel workbook per recording.

```
  microscope .tif movies
        │
        ▼
  1. Suite2p + Cellpose   find the cells, extract each cell's fluorescence
  2. CASCADE              infer when each cell fired (calibrated spike inference)
  3. Network metrics      firing rates, STTC synchrony, network bursts, ...
        │
        ▼
  <recording>_metrics.xlsx   (a "Key Numbers" sheet explains every value in plain language)
```

Built by the Lippmann Lab (Vanderbilt) for human iPSC-derived cortical neurons imaged with
jGCaMP8s / jGCaMP8f. It works on any comparable widefield recording.

## ▶ Get started

### **[HOW_TO_INSTALL.md](HOW_TO_INSTALL.md)** — the step-by-step guide

It walks you from nothing installed to your first results, on **Windows or Mac**, with no
programming or GitHub knowledge needed. In short:

1. **Download** this pipeline as a ZIP file:
   [calcium-network-pipeline-main.zip](https://github.com/samuelchu030609-commits/calcium-network-pipeline/archive/refs/heads/main.zip)
2. **Install:** on Windows, double-click `INSTALL_WINDOWS.bat`; on a Mac, run
   `INSTALL_MAC.sh` (the guide shows how). No administrator password is needed. The
   installer checks itself at the end.
3. **Analyse:** double-click **Calcium Pipeline** on your Desktop, pick your folder of
   movies and the indicator, and press Start.

## More information

- [docs/TECHNICAL_README.md](docs/TECHNICAL_README.md): methods, outputs, design, and how
  the stages fit together
- [docs/SUITE2P_SETTINGS.md](docs/SUITE2P_SETTINGS.md): the locked cell-detection settings
- [gui/README.md](gui/README.md): the point-and-click program
- Troubleshooting: the table in [HOW_TO_INSTALL.md](HOW_TO_INSTALL.md#troubleshooting);
  for the Suite2p-output and Docker routes, [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## Citing the methods

- Pachitariu et al. (2017) bioRxiv: **Suite2p**
- Stringer et al. (2021) *Nat. Methods*: **Cellpose**; Pachitariu, Rariden & Stringer (2025)
  bioRxiv: **Cellpose-SAM** (the `cpsam` model used for detection)
- Rupprecht et al. (2021) *Nat. Neurosci.*: **CASCADE**
- Cutts & Eglen (2014) *J. Neurosci.*: **STTC** synchrony

MIT License (see [LICENSE](LICENSE)).
