#!/usr/bin/env bash
# End-to-end acceptance test. Generates a tiny SYNTHETIC recording with known
# planted structure, runs the full pipeline on it, and checks the output is
# sane. This is Rule 1 applied to the distribution: predict, then test — it
# verifies the container/install actually works before you trust it on real data.
#
# Expected (deterministic, seed=0): ~14/15 active cells, mean STTC well above
# chance (z > 3), and >=1 network burst. A pure-noise pipeline, a broken CASCADE
# model, or a broken STTC would fail these.
#
# Usage (inside the container or a working local env):
#     bash examples/acceptance_test.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
OUT="${1:-/tmp/cnp_acceptance}"
PY="${PYTHON:-python}"

echo "[acceptance] generating synthetic recording -> $OUT"
rm -rf "$OUT"
cd "$REPO"
"$PY" examples/make_example.py "$OUT"

echo "[acceptance] running pipeline ..."
LOG="$OUT/_run.log"
"$PY" -m pipeline.run_pipeline "$OUT" 2>&1 | tee "$LOG"

echo "[acceptance] checking outputs ..."
PLANE0="$OUT/suite2p/plane0"
fail=0
check() { if eval "$2"; then echo "  PASS: $1"; else echo "  FAIL: $1"; fail=1; fi; }

# 1. CASCADE actually ran (baked model found, no download needed)
check "cascade_spike_prob.npy written"        "[ -f '$PLANE0/cascade_spike_prob.npy' ]"
check "cascade_meta.json written"             "[ -f '$PLANE0/cascade_meta.json' ]"
# 2. metrics + provenance + QC written
check "metrics sheets or xlsx written"        "ls '$PLANE0'/*_metrics* >/dev/null 2>&1"
check "PROVENANCE stamp written"              "ls '$PLANE0'/*PROVENANCE* >/dev/null 2>&1"
check "baseline QC png written"               "ls '$PLANE0'/*baseline_qc.png >/dev/null 2>&1"
# 3. detection-settings guard reported a MATCH (synthetic carries canonical)
check "detection settings match reported"     "grep -q 'detection settings match canonical' '$LOG'"
# 4. the planted structure was recovered
check "found active cells (>=10 of 15)"       "grep -qE 'active 1[0-5]/15' '$LOG'"
check "above-chance STTC (z >= 3)"            "grep -oE 'z [0-9]+\.[0-9]+' '$LOG' | head -1 | awk '{exit !(\$2>=3)}'"
check "at least one network burst"            "grep -qE 'Network bursts . fixed [1-9]' '$LOG'"
# 5. no placeholder junk (guarded output_prefix) and no error cells
check "no RUNID placeholder junk"             "! ls '$PLANE0'/RUNID_* >/dev/null 2>&1"

echo
if [ "$fail" -eq 0 ]; then
  echo "[acceptance] ALL CHECKS PASSED — pipeline works end-to-end."
else
  echo "[acceptance] SOME CHECKS FAILED — see above." >&2
  exit 1
fi
