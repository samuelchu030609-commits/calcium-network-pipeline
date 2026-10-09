#!/usr/bin/env bash
# End-user wrapper (macOS / Linux). Usage: ./run.sh /path/to/recording
# The folder must contain a suite2p/ subfolder and a config.json.
set -euo pipefail

IMAGE="ghcr.io/samuelchu030609-commits/ineuron-netsync:latest"

if [[ $# -lt 1 ]]; then
  echo "Usage: ./run.sh /path/to/recording"
  echo "  (the folder that contains suite2p/ and config.json)"
  exit 1
fi

FOLDER="$(cd "$1" && pwd)"   # absolute path
echo "Running pipeline on: $FOLDER"
docker run --rm -v "$FOLDER:/data" "$IMAGE" /data
echo "Done. Look for *_metrics.xlsx inside $FOLDER/suite2p/plane0/"
