#!/usr/bin/env bash
# Start the HKLV API inside the WSL OCR environment (loads the OCR models once, ~20 s).
#   bash /mnt/c/dcSS/scripts/wsl/serve.sh            -> http://127.0.0.1:8000/docs
# Listens on 127.0.0.1 only (reachable from Windows through WSL's localhost forwarding,
# not from the network). HKLV_PORT changes the port.
set -euo pipefail
OCR_HOME="${OCR_HOME:-$HOME/hklv-ocr}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$HERE/../../src" && pwd)"
mkdir -p "$OCR_HOME/tmp"
cd "$OCR_HOME"   # Paddle writes caches to the working directory; keep them off /mnt/c
export TMPDIR="$OCR_HOME/tmp"
# Uploads go to a private folder (owner-only) and are deleted after each request; any left
# by a killed server are swept at the next start.
export HKLV_WORK_DIR="${HKLV_WORK_DIR:-$OCR_HOME/work}"
mkdir -p "$HKLV_WORK_DIR" && chmod 700 "$HKLV_WORK_DIR"
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"
exec "$OCR_HOME/.venv/bin/python" -m uvicorn hklv_api.app:app \
    --app-dir "$SRC" --host 127.0.0.1 --port "${HKLV_PORT:-8000}" --workers 1
