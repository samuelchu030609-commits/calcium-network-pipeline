#!/usr/bin/env bash
# Container entrypoint. Receives the mounted data folder (default /data) and
# hands off to the orchestrator. Each stage runs in its own conda env: the
# orchestrator + metrics run in `analysis`, and PIPELINE_CASCADE_ENV tells
# run_pipeline to `conda run -n cascade` for the TensorFlow stage.
set -euo pipefail

DATA_DIR="${1:-/data}"
export PIPELINE_CASCADE_ENV="${PIPELINE_CASCADE_ENV:-cascade}"

# Pass --help straight through.
if [[ "$DATA_DIR" == "--help" || "$DATA_DIR" == "-h" ]]; then
  exec conda run -n analysis python /app/pipeline/run_pipeline.py --help
fi

exec conda run -n analysis python /app/pipeline/run_pipeline.py "$DATA_DIR"
