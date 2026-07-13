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

TODO: add a tiny anonymized sample recording (or a download link) so new users can
do a dry run without their own data.
