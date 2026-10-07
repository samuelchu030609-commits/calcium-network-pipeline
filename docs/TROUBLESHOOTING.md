# Troubleshooting

**"Cannot connect to the Docker daemon"** — Docker Desktop isn't running. Open it
and wait until the engine is up, then retry.

**"No suite2p/plane0 found in /data"** — you pointed the tool at the wrong folder.
Point it at the folder that *contains* `suite2p/`, not at `plane0` itself.

**Detection found almost no cells / far too many** — you likely used Suite2p's
default detection instead of the settings in
[`SUITE2P_SETTINGS.md`](SUITE2P_SETTINGS.md), or `fs`/`tau` were wrong. Re-run
Suite2p with the documented settings (or load `settings/pipeline_settings.npy`).

**Results look off for a dye recording** — Fluo-4 must use `"route": "dff"` in
`config.json`; CASCADE has no Fluo-4 model and returns near-zero. Check the
indicator/route in your config.

**CASCADE picks a weird model / wrong frame rate** — CASCADE models are frame-rate
specific. Confirm `native_fps` in `config.json` is the true rate from the TIF
timestamps.

**Windows path with spaces fails** — wrap the path in quotes:
`docker\run.bat "C:\My Data\recording 3"`.
