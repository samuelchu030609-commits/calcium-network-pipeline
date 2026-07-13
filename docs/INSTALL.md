# Installing (end users)

You need **two** things on your machine:

1. **Suite2p** — to make the `plane0` folder. Install from the official Suite2p
   project and see [`SUITE2P_SETTINGS.md`](SUITE2P_SETTINGS.md).
2. **Docker Desktop** — to run this pipeline. Details below.

You do **not** need Python, conda, or CASCADE — those live inside the container.

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

## Get the pipeline image

Once Docker is running, the first `run.sh` / `run.bat` will automatically pull the
image. To pull it ahead of time:

```
docker pull ghcr.io/samuelchu030609-commits/calcium-network-pipeline:latest
```

The image is CPU-only (no GPU needed) and bundles CASCADE + all models, so the
first pull is a few GB but after that it runs fully offline.

## Verify

```
docker run --rm ghcr.io/samuelchu030609-commits/calcium-network-pipeline:latest --help
```

should print the pipeline usage.
