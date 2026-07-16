# Expected input layout

Point the pipeline at a **recording folder** that looks like this:

```
my_recording_2169/
├── config.json          ← copied from config.example.json and edited
└── suite2p/
    └── plane0/
        ├── F.npy
        ├── Fneu.npy
        ├── iscell.npy
        ├── stat.npy
        ├── ops.npy
        └── ...           ← everything Suite2p wrote
```

Then:  `./run.sh my_recording_2169`  (or `run.bat my_recording_2169` on Windows).

Output `..._metrics.xlsx` is written into `suite2p/plane0/`.

## Acceptance test (no real data needed)

Before trusting the pipeline on your own recordings, verify the install/container
actually works end-to-end. `make_example.py` generates a tiny **synthetic**
recording (15 ROIs, 450 frames @ 45 Hz, seed-fixed) with a known planted
structure — 8 co-firing "assembly" cells plus quieter cells — so the output is
predictable and checkable. It is not real data; it exists only to exercise the
full chain (CASCADE model → dF/F0 → events → STTC → network bursts).

    # generate + run + assert, in one shot:
    bash examples/acceptance_test.sh

    # or by hand:
    python examples/make_example.py examples/_synthetic
    ./run.sh examples/_synthetic

The test asserts CASCADE ran against the baked model, the metrics/PROVENANCE/QC
outputs were written, the detection-settings guard reported a match, and the
planted structure was recovered (≥10/15 active, STTC z ≥ 3, ≥1 network burst).
`ALL CHECKS PASSED` means the pipeline is working. The generated `_synthetic/`
folder is gitignored (regenerate it any time from the script).
