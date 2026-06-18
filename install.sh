#!/usr/bin/env bash
# MOLGANG one-command installer (macOS / Linux).
#   git clone https://github.com/knitweb/molgang.git && cd molgang && ./install.sh
# Sets up a virtualenv, fetches the knitweb engine, installs both, and leaves you with a
# working `molgang` command. Re-runnable.
set -euo pipefail

green() { printf "\033[1;32m▸\033[0m %s\n" "$*"; }
red()   { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; }

# 1. Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
  red "python3 not found. Install it:  brew install python   (or https://python.org)"; exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)'; then
  red "Python 3.12+ required (have $(python3 -V)).  Try:  brew install python@3.12"; exit 1
fi
green "$(python3 -V)"

# 2. Locate this repo + fetch the knitweb engine as a sibling if missing
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [ ! -f "$ROOT/pyproject.toml" ]; then red "run this from inside the molgang repo"; exit 1; fi
PULSE="$(dirname "$ROOT")/pulse"
if [ ! -d "$PULSE/src/knitweb" ]; then
  green "fetching the knitweb engine → $PULSE"
  git clone --depth 1 https://github.com/knitweb/pulse.git "$PULSE"
else
  green "knitweb engine found → $PULSE"
fi

# 3. Virtualenv + editable installs (knitweb first so molgang's dep resolves locally)
VENV="$ROOT/.venv"
[ -d "$VENV" ] || { green "creating virtualenv → .venv"; python3 -m venv "$VENV"; }
"$VENV/bin/python" -m pip install --quiet --upgrade pip
green "installing knitweb (editable)…"
"$VENV/bin/pip" install --quiet -e "$PULSE"
green "installing molgang (editable)…"
"$VENV/bin/pip" install --quiet -e "$ROOT"

# 4. Smoke test
green "verifying…"
"$VENV/bin/molgang" doctor >/dev/null && green "all good." || { red "doctor failed"; exit 1; }

cat <<EOF

  🧪  MOLGANG is installed. To play:

      source "$VENV/bin/activate"
      molgang            # a narrated session (faucet → knit → vote → woven → anchor)
      molgang play       # interactive
      molgang serve      # browser bar at http://localhost:8765
      molgang doctor     # check your setup

EOF
