#!/usr/bin/env bash
# Optional: realistic lip-sync with MuseTalk on an NVIDIA GPU.
set -euo pipefail
DEST="${1:-$HOME/.twinvoy/MuseTalk}"
git clone --depth 1 https://github.com/TMElyralab/MuseTalk "$DEST"
cd "$DEST"
"$HOME/.twinvoy/venv/bin/pip" install -r requirements.txt
echo "Now download the model weights as described in $DEST/README.md (download_weights.sh),"
echo "then set in ~/.twinvoy/config.yaml:"
echo "  avatar: { backend: musetalk, musetalk_repo: $DEST }"
