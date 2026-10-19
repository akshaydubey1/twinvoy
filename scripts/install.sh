#!/usr/bin/env bash
# One-line install:  curl -fsSL <your-host>/install.sh | bash
# Creates an isolated venv in ~/.twinvoy/venv and puts `twinvoy` on PATH.
set -euo pipefail

HOME_DIR="${TWINVOY_HOME:-$HOME/.twinvoy}"
SRC="${TWINVOY_SRC:-git+https://github.com/akshaydubey1/twinvoy.git}"
PY="${PYTHON:-python3}"

command -v "$PY" >/dev/null || { echo "Python 3.10+ is required"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { echo "Python 3.10+ is required"; exit 1; }

mkdir -p "$HOME_DIR"
"$PY" -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install -q --upgrade pip
"$HOME_DIR/venv/bin/pip" install -q "twinvoy[brain,local] @ $SRC"

BIN="$HOME/.local/bin"
mkdir -p "$BIN"
ln -sf "$HOME_DIR/venv/bin/twinvoy" "$BIN/twinvoy"

echo
echo "Installed. Next steps:"
echo "  twinvoy init      # your name; meeting name becomes '<you> (AI twin)'"
echo "  twinvoy enroll    # consent + guided face capture"
echo "  twinvoy preview   # check how the twin looks"
echo "  twinvoy doctor    # see what's still missing"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Add $BIN to your PATH.";; esac
