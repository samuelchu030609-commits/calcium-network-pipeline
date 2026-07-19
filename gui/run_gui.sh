#!/usr/bin/env bash
# Launch the stages 2-3 GUI (macOS / Linux).
#   ./gui/run_gui.sh
# Opens a local web page in your browser. Nothing is uploaded anywhere; it runs
# entirely on this machine and reads your files from disk.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Skip Streamlit's one-time "enter your email" prompt (it blocks startup on a
# fresh machine). Writing an empty email once makes Streamlit never ask again.
CRED="$HOME/.streamlit/credentials.toml"
if [ ! -f "$CRED" ]; then
  mkdir -p "$HOME/.streamlit"
  printf '[general]\nemail = ""\n' > "$CRED"
fi
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Prefer a dedicated `gui` conda env (envs/gui.yml) if you made one; otherwise
# use whatever python has streamlit installed.
if command -v conda >/dev/null 2>&1 && conda env list | grep -qE '/gui$'; then
  exec conda run --no-capture-output -n gui python -m streamlit run "$HERE/app.py"
fi

for PY in python3 python; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c "import streamlit" >/dev/null 2>&1; then
    exec "$PY" -m streamlit run "$HERE/app.py"
  fi
done

echo "Streamlit is not installed. Create the GUI env once with:" >&2
echo "  conda env create -f \"$HERE/../envs/gui.yml\"" >&2
echo "or install it into any env with:  pip install streamlit pandas openpyxl" >&2
exit 1
