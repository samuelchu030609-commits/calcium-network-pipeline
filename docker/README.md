# Docker route (advanced, stages 2–3 only)

> **Most people should use the one-click install instead:
> [HOW_TO_INSTALL.md](../HOW_TO_INSTALL.md).** It covers all three stages, including
> Suite2p, and needs no Docker.

This folder packages stages 2–3 (CASCADE + metrics) as a CPU-only Docker image. **The
image is not published**, so build it yourself once (below). You also need:

1. **Suite2p**, to make the `plane0` folder. Install it from the official Suite2p
   project and see [`docs/SUITE2P_SETTINGS.md`](../docs/SUITE2P_SETTINGS.md).
2. **Docker Desktop**, to run the image. Details below.

## Build the image

From the repository's top folder, with Docker running:

```
docker build -f docker/Dockerfile -t ghcr.io/samuelchu030609-commits/ineuron-netsync:latest .
```

`docker/run.sh` (macOS/Linux) and `docker/run.bat` (Windows) then run it on one recording
folder that contains `suite2p/` and a `config.json` (copy
[`config.example.json`](../config.example.json)):

```
./docker/run.sh /path/to/recording
docker\run.bat "C:\path\to\recording"
```

## Install Docker Desktop

### Windows
1. Download Docker Desktop for Windows from docker.com.
2. Run the installer. If prompted, allow it to enable **WSL 2** / virtualization
   (this is normal; a reboot may be required).
3. Launch Docker Desktop and wait until it says "Engine running."

### macOS
1. Download Docker Desktop for Mac (pick the **Apple Silicon** or **Intel** build
   to match your Mac).
2. Drag it to Applications, launch it, wait until the whale icon is steady.

## Verify

```
docker run --rm ghcr.io/samuelchu030609-commits/ineuron-netsync:latest --help
```

should print the pipeline usage.
