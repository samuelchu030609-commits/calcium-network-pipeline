#!/usr/bin/env bash
# Container entrypoint. Receives the mounted data folder (default /data) and
# hands off to the orchestrator. Each stage runs in its own conda env, so we call
# run_pipeline.py with the analysis env and let it shell out to the cascade env.
set -euo pipefail

DATA_DIR="${1:-/data}"

# Pass --help straight through.
if [[ "$DATA_DIR" == "--help" || "$DATA_DIR" == "-h" ]]; then
  exec conda run -n analysis python /app/pipeline/run_pipeline.py --help
fi

exec conda run -n analysis python /app/pipeline/run_pipeline.py "$DATA_DIR"
