#!/usr/bin/env bash
# Pass 1 OCR environment: PaddleOCR-VL-1.6 on the GPU, inside WSL2 Ubuntu.
#
# Run from Windows:   wsl -d Ubuntu -- bash /mnt/c/dcSS/scripts/wsl/setup_ocr.sh
# Safe to re-run: every step skips work that is already done.
#
# Versions follow the official PaddleOCR-VL guide for NVIDIA Blackwell (RTX 50xx):
#   driver with CUDA >= 12.9, Python 3.9-3.13, paddlepaddle-gpu 3.2.1 (cu129 build),
#   paddleocr[doc-parser] >= 3.6.0 for PaddleOCR-VL-1.6.
# Ubuntu 26.04 ships Python 3.14, which is outside that range, so uv provides 3.12.
set -euo pipefail

OCR_HOME="${OCR_HOME:-$HOME/hklv-ocr}"   # Linux filesystem: much faster than /mnt/c
PY_VERSION="3.12"
PADDLE_VERSION="3.2.1"
PADDLE_INDEX="https://www.paddlepaddle.org.cn/packages/stable/cu129/"
PADDLEOCR_SPEC="paddleocr[doc-parser]>=3.6.0"
ZXING_SPEC="zxing-cpp>=3.1"

step() { printf '\n==> %s\n' "$*"; }

# The CUDA wheels are several hundred MB each; keep resuming dropped downloads.
export PIP_RESUME_RETRIES=30 PIP_RETRIES=10 PIP_TIMEOUT=60
# Ubuntu 26.04 mounts /tmp in RAM (~half of WSL memory), too small to unpack the
# 1.9 GB Paddle wheel plus CUDA libraries. Unpack on disk instead.
export TMPDIR="$OCR_HOME/tmp"
# WSL keeps the Windows GPU driver's libcuda.so here; Paddle warns if it can't see it.
export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
mkdir -p "$TMPDIR"

step "Checking the GPU is visible from WSL"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

step "Checking system libraries Paddle and OpenCV need"
# libgomp1: OpenMP, loaded by Paddle's core. libsm6/libice6: loaded by OpenCV.
missing=()
for pair in libgomp.so.1:libgomp1 libSM.so.6:libsm6 libICE.so.6:libice6; do
    ldconfig -p | grep -q "${pair%%:*}" || missing+=("${pair##*:}")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing system packages: ${missing[*]}"
    echo "Install them yourself (needs your Ubuntu password), then re-run this script:"
    echo "    sudo apt update && sudo apt install -y ${missing[*]}"
    exit 2
fi
echo "All present"

step "Installing uv (Python manager) if missing"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

step "Creating Python $PY_VERSION virtual environment in $OCR_HOME/.venv"
mkdir -p "$OCR_HOME"
uv python install "$PY_VERSION"
if [ ! -x "$OCR_HOME/.venv/bin/python" ]; then
    uv venv --seed --python "$PY_VERSION" "$OCR_HOME/.venv"
fi
# shellcheck disable=SC1091
source "$OCR_HOME/.venv/bin/activate"
python --version

step "Installing PaddlePaddle GPU $PADDLE_VERSION (CUDA 12.9 build)"
python -m pip install --upgrade pip
if python -c "import paddle, sys; sys.exit(0 if paddle.__version__ == '$PADDLE_VERSION' else 1)" 2>/dev/null; then
    echo "paddlepaddle-gpu $PADDLE_VERSION already installed"
elif ! python -m pip install "paddlepaddle-gpu==$PADDLE_VERSION" -i "$PADDLE_INDEX" --extra-index-url https://pypi.org/simple; then
    # The index page (paddlepaddle.org.cn) is sometimes down (HTTP 502) while the wheel
    # files stay available on Paddle's own storage bucket, which the index serves from.
    PYTAG="cp$(python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')"
    WHEEL="paddlepaddle_gpu-${PADDLE_VERSION}-${PYTAG}-${PYTAG}-linux_x86_64.whl"
    echo "Index unavailable; installing $WHEEL from Paddle's storage bucket"
    python -m pip install "https://paddle-whl.bj.bcebos.com/stable/cu129/paddlepaddle-gpu/$WHEEL"
fi

step "Installing $PADDLEOCR_SPEC"
python -m pip install -U "$PADDLEOCR_SPEC"

step "Installing ZXing-C++ (QR codes and barcodes)"
python -m pip install -U "$ZXING_SPEC"

step "Checking PaddlePaddle can use the GPU"
python - <<'EOF'
import paddle
print("paddle", paddle.__version__, "| compiled with CUDA:", paddle.device.is_compiled_with_cuda())
print("GPUs visible:", paddle.device.cuda.device_count())
paddle.utils.run_check()
EOF

step "Recording exact installed versions"
python -m pip freeze > "$OCR_HOME/requirements-ocr.lock.txt"
echo "Saved $OCR_HOME/requirements-ocr.lock.txt"

step "Done. Activate with:  source $OCR_HOME/.venv/bin/activate"
echo "Then check OCR end to end (downloads the ~2 GB model on first run):"
echo "    LD_LIBRARY_PATH=/usr/lib/wsl/lib python /mnt/c/dcSS/scripts/wsl/smoke_test_ocr.py"
