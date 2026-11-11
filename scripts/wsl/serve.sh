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
PORT="${HKLV_PORT:-8000}"
# Already running (e.g. started in another window)? Say so instead of loading the models
# for 20 s and then failing with "address already in use".
if curl -s -m 2 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "The HKLV server is already running: open http://127.0.0.1:$PORT in your browser."
    echo "(To restart it, press Ctrl+C in the window where it runs, then start it again.)"
    exit 0
fi
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORT "; then
    echo "Port $PORT is used by another program. Start on another port with HKLV_PORT, e.g.:"
    echo "    HKLV_PORT=8010 bash $0"
    exit 1
fi
exec "$OCR_HOME/.venv/bin/python" -m uvicorn hklv_api.app:app \
    --app-dir "$SRC" --host 127.0.0.1 --port "$PORT" --workers 1
