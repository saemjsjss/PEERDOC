#!/usr/bin/env bash
# Run the master pipeline inside the WSL OCR environment. Arguments go to run_case.py.
#   bash /mnt/c/dcSS/scripts/wsl/run_case.sh "/mnt/c/dcSS/SAMPLE DOC" [--date YYYY-MM-DD]
set -euo pipefail
OCR_HOME="${OCR_HOME:-$HOME/hklv-ocr}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Relative path arguments mean "relative to where the user ran this"; remember it before
# moving into the OCR folder.
export HKLV_CALLER_CWD="$PWD"
mkdir -p "$OCR_HOME/tmp"
cd "$OCR_HOME"   # Paddle writes caches to the working directory; keep them off /mnt/c
export TMPDIR="$OCR_HOME/tmp"                       # /tmp is a small RAM disk on Ubuntu 26.04
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"   # Windows GPU driver's libcuda
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True   # models are cached; skip the network check
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"   # Paddle's API-compatibility warnings are noise here
exec "$OCR_HOME/.venv/bin/python" -u "$HERE/../run_case.py" "$@"
