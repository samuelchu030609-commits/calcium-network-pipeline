#!/usr/bin/env bash
# ============================================================================
# iNeuron-NetSync - one-command installer for macOS
#
# What it does (nothing outside the folders named here is touched; no password):
#   1. Puts a private copy of Python ("Miniforge") in   ~/iNeuron-NetSync/conda
#      - separate from any Python/conda you already have, so it cannot break them.
#   2. Builds the four environments the pipeline needs, at the exact versions the
#      reference numbers were produced with:
#        suite2p   stage 1  motion correction + cell detection (Suite2p + Cellpose)
#        cascade   stage 2  spike inference (CASCADE, TensorFlow)
#        analysis  stage 3  events + network metrics
#        gui       the point-and-click window
#   3. Downloads CASCADE into ~/Cascade with its two jGCaMP8 models, and the
#      Cellpose cell-detection model into ~/.cellpose.
#   4. Copies the pipeline code to ~/iNeuron-NetSync/code.
#   5. Puts an "iNeuron-NetSync" launcher on your Desktop.
#   6. Runs a self-test on built-in synthetic data and says PASSED or FAILED.
#
# Safe to run again: finished steps are skipped. Run it again after downloading a
# newer version of the pipeline to update the code (environments are kept).
#
# Usage:   bash INSTALL_MAC.sh
# ============================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"      # the downloaded pipeline
BASE="${CNP_BASE:-$HOME/iNeuron-NetSync}"
CONDA_HOME="$BASE/conda"
CODE="$BASE/code"
CASCADE_DIR="$HOME/Cascade"
CASCADE_SHA="213fd1206653bbb9dbe68a5faa8c0dab91fc46ee"      # the CASCADE version we verified
MODELS=("GC8s_EXC_45Hz_smoothing50ms" "GC8f_EXC_100Hz_smoothing10ms")
LOG="$BASE/install_log.txt"

mkdir -p "$BASE"
exec > >(tee -a "$LOG") 2>&1

c1=$'\033[1m'; c0=$'\033[0m'; cg=$'\033[32m'; cy=$'\033[33m'; cr=$'\033[31m'
step() { printf '\n%s\n' "${c1}==> $*${c0}"; }
ok()   { printf '%s\n' "  ${cg}OK${c0}    $*"; }
warn() { printf '%s\n' "  ${cy}NOTE${c0}  $*"; }
die()  { printf '\n%s\n' "  ${cr}STOPPED${c0} $*" >&2
         printf '%s\n' "  The full log is in: $LOG" >&2; exit 1; }

echo "iNeuron-NetSync installer - $(date)"
echo "Installing into: $BASE"

# ---------------------------------------------------------------- 1. checks
step "1/7  Checking this Mac"
[ "$(uname -s)" = "Darwin" ] || die "This installer is for macOS. On Windows use INSTALL_WINDOWS.bat."
case "$(uname -m)" in
  arm64)  MF_ARCH="arm64"  ;;
  x86_64) die "This Mac has an Intel processor. The pipeline needs an Apple Silicon Mac (M1 or newer):
       the PyTorch version that cell detection is pinned to is not made for Intel Macs.
       Use a Windows PC or an Apple Silicon Mac instead." ;;
  *) die "Unsupported processor: $(uname -m)" ;;
esac
ok "macOS $(sw_vers -productVersion), $(uname -m)"
case "$BASE" in *" "*) die "The install folder path contains a space ($BASE). Set CNP_BASE to a path without spaces." ;; esac
FREE_GB=$(df -g "$HOME" | awk 'NR==2{print $4}')
[ "$FREE_GB" -ge 15 ] || die "Only ${FREE_GB} GB free on this disk; the install needs about 15 GB."
ok "${FREE_GB} GB free"
# Any HTTP answer (even an error page) proves the network path works.
curl -sS --max-time 20 -o /dev/null https://conda.anaconda.org/conda-forge/ \
  || die "Cannot reach the internet (conda.anaconda.org). Check the network connection, then run this again."
ok "internet connection works"

# ---------------------------------------------------------------- 2. miniforge
step "2/7  Private Python (Miniforge)"
if [ -x "$CONDA_HOME/bin/conda" ]; then
  ok "already installed"
else
  URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-${MF_ARCH}.sh"
  TMP="$BASE/miniforge_installer.sh"
  echo "  downloading Miniforge (about 80 MB)..."
  curl -fL --retry 3 -o "$TMP" "$URL" || die "Download of Miniforge failed."
  bash "$TMP" -b -p "$CONDA_HOME" >/dev/null || die "Miniforge did not install."
  rm -f "$TMP"
  ok "installed"
fi
CONDA="$CONDA_HOME/bin/conda"

# ---------------------------------------------------------------- 3. envs
# An environment counts as finished only once its marker file exists, so an
# interrupted build is thrown away and rebuilt instead of half-used.
env_py() { echo "$CONDA_HOME/envs/$1/bin/python"; }
build_env() {   # name, python version, conda packages..., then "--", pip packages...
  local name="$1" pyver="$2"; shift 2
  local conda_pkgs=() pip_pkgs=() seen=0
  for a in "$@"; do
    if [ "$a" = "--" ]; then seen=1; elif [ $seen -eq 0 ]; then conda_pkgs+=("$a"); else pip_pkgs+=("$a"); fi
  done
  if [ -f "$CONDA_HOME/envs/$name/.cnp_ok" ]; then ok "$name: already built"; return; fi
  echo "  building $name (a few minutes)..."
  rm -rf "$CONDA_HOME/envs/$name"
  "$CONDA" create -y -q -p "$CONDA_HOME/envs/$name" -c conda-forge --override-channels \
      "python=$pyver" pip ${conda_pkgs[@]+"${conda_pkgs[@]}"} >/dev/null \
      || die "Could not build the $name environment."
  if [ ${#pip_pkgs[@]} -gt 0 ]; then
    "$(env_py "$name")" -m pip install -q --no-input "${pip_pkgs[@]}" \
      || die "Could not install packages into the $name environment."
  fi
  touch "$CONDA_HOME/envs/$name/.cnp_ok"
  ok "$name: built"
}

step "3/7  Environments (the longest step: 10-30 minutes in total)"
# Version pins = the verified reference machine. Do not loosen them: Cellpose runs
# through torch, so a different torch/numpy can change which cells are detected,
# and TensorFlow 2.15 requires numpy < 2.
build_env suite2p 3.11 -- \
  "suite2p[gui]==1.0.0.1" "cellpose==4.1.1" "torch==2.11.0" "numpy==1.26.4" \
  "scipy==1.17.1" "tifffile==2026.3.3"
build_env cascade 3.10 "numpy=1.26.4" "h5py=3.16.0" ruamel.yaml matplotlib-base -- \
  "tensorflow==2.15.1" "scipy==1.15.3"
build_env analysis 3.10 "numpy=2.2.5" "pandas=2.3.3" "matplotlib=3.10.9" \
  "openpyxl=3.1.5" "jinja2=3.1.6" ruamel.yaml -- "scipy==1.15.3"
build_env gui 3.11 -- \
  "streamlit==1.63.0" "pandas==3.0.5" "openpyxl==3.1.5" "numpy==2.4.6" \
  "scipy==1.17.1" "tifffile==2026.3.3"

# ---------------------------------------------------------------- 4. CASCADE
step "4/7  CASCADE and its models"
if [ -d "$CASCADE_DIR/cascade2p" ]; then
  ok "CASCADE already present at $CASCADE_DIR"
elif [ -e "$CASCADE_DIR" ] && [ -n "$(ls -A "$CASCADE_DIR" 2>/dev/null)" ]; then
  die "$CASCADE_DIR exists but is not CASCADE. Rename or move that folder, then run this again."
else
  echo "  downloading CASCADE..."
  TMPZ="$BASE/cascade.zip"
  curl -fL --retry 3 -o "$TMPZ" \
    "https://github.com/HelmchenLabSoftware/Cascade/archive/${CASCADE_SHA}.zip" \
    || die "Download of CASCADE failed."
  rm -rf "$BASE/_cascade_unzip"
  unzip -q "$TMPZ" -d "$BASE/_cascade_unzip"
  rm -rf "$CASCADE_DIR"
  mv "$BASE/_cascade_unzip/Cascade-${CASCADE_SHA}" "$CASCADE_DIR"
  rm -rf "$BASE/_cascade_unzip" "$TMPZ"
  ok "CASCADE installed at $CASCADE_DIR"
fi
for m in "${MODELS[@]}"; do
  if ls "$CASCADE_DIR/Pretrained_models/$m/"*.h5 >/dev/null 2>&1; then
    ok "model $m present"
  else
    echo "  downloading model $m..."
    ( cd "$CASCADE_DIR" && "$(env_py cascade)" -c "
import os, sys, warnings; warnings.filterwarnings('ignore'); os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
sys.path.insert(0, '.')
from cascade2p import cascade
cascade.download_model('$m', verbose=0)
" ) >/dev/null 2>&1 || die "Could not download the CASCADE model $m (the server drive.switch.ch may be blocked on this network)."
    ok "model $m downloaded"
  fi
done

step "5/7  Cellpose cell-detection model (about 1.2 GB, one time)"
"$(env_py suite2p)" -c "
from cellpose import models
models.CellposeModel(gpu=False)
" >/dev/null 2>&1 && ok "Cellpose model ready" \
  || warn "Could not download the Cellpose model now; it will be downloaded on the first analysis."

# ---------------------------------------------------------------- 5. code + launcher
step "6/7  Pipeline code and Desktop launcher"
if [ "$SRC" != "$CODE" ]; then
  mkdir -p "$CODE"
  rsync -a --delete --exclude '.git' --exclude '__pycache__' \
        --exclude 'gui/settings.local.json' "$SRC/" "$CODE/"
  ok "code copied to $CODE"
fi

LAUNCHER="$BASE/iNeuron-NetSync.command"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
# Opens iNeuron-NetSync in your web browser.
# Keep this window open while you work; closing it closes the program.
export CNP_CONDA_BASE="$CONDA_HOME"
export PYTHONUTF8=1
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
mkdir -p "\$HOME/.streamlit"
[ -f "\$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "\$HOME/.streamlit/credentials.toml"
echo "Starting iNeuron-NetSync - your browser will open in a moment."
echo "Keep this window open while you use it. Close it when you are done."
exec "$(env_py gui)" -m streamlit run "$CODE/gui/app.py" --server.address localhost --server.headless false --client.toolbarMode minimal
EOF
chmod +x "$LAUNCHER"
if [ -d "$HOME/Desktop" ]; then
  cp "$LAUNCHER" "$HOME/Desktop/iNeuron-NetSync.command"
  ok "launcher placed on the Desktop: \"iNeuron-NetSync\""
else
  ok "launcher: $LAUNCHER"
fi

# ---------------------------------------------------------------- 6. self-test
step "7/7  Self-test (about 3-5 minutes)"
if [ "${CNP_SKIP_SELFTEST:-}" = "1" ]; then      # used only by the automatic GitHub test
  warn "self-test skipped (CNP_SKIP_SELFTEST=1)"; exit 0
fi
if CNP_CONDA_BASE="$CONDA_HOME" PYTHONUTF8=1 "$(env_py analysis)" "$CODE/install/self_test.py"; then
  printf '\n%s\n' "${cg}${c1}INSTALLATION COMPLETE - self-test PASSED.${c0}"
  echo "To start: double-click \"iNeuron-NetSync\" on your Desktop."
  echo "The guide (HOW_TO_INSTALL.md) explains what to do next."
else
  die "The self-test FAILED (details above). Send the file $LOG to the pipeline's maintainers."
fi
