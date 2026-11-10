# Pass 1 OCR environment (WSL2)

PaddleOCR-VL-1.6 runs on the RTX 5060 inside WSL2 Ubuntu 26.04, in its own Python 3.12
environment at `~/hklv-ocr/.venv` (Ubuntu's own Python 3.14 is too new for PaddlePaddle).

| Piece | Version |
|---|---|
| PaddlePaddle GPU | 3.2.1, CUDA 12.9 build (has native RTX 50xx / sm_120 code) |
| PaddleOCR / PaddleX | 3.7.0 / 3.7.2 |
| Models | PP-DocLayoutV3 (layout), PaddleOCR-VL-1.6-0.9B (text), cached in `~/.paddlex` |

Exact versions: [`scripts/wsl/requirements-ocr.lock.txt`](../scripts/wsl/requirements-ocr.lock.txt).

## Set up / check

From Windows PowerShell:

```powershell
wsl -d Ubuntu -- bash /mnt/c/dcSS/scripts/wsl/setup_ocr.sh
```

```powershell
wsl -d Ubuntu -- bash -c "LD_LIBRARY_PATH=/usr/lib/wsl/lib ~/hklv-ocr/.venv/bin/python /mnt/c/dcSS/scripts/wsl/smoke_test_ocr.py"
```

The smoke test reads a fictional TIN certificate and must print `SMOKE TEST PASSED`.
Measured: model load ~3 s, one page ~6.5 s.

## Problems hit during setup (handled by the script)

* **Paddle's package index returned HTTP 502.** The script falls back to the same wheel on
  Paddle's storage bucket (`paddle-whl.bj.bcebos.com`); the lock file pins its sha256.
* **`/tmp` is RAM-backed (3.7 GB) on Ubuntu 26.04**, too small to unpack the wheels, so the
  script sets `TMPDIR=~/hklv-ocr/tmp`.
* **System libraries** `libgomp1 libsm6 libice6` were missing; the script detects them and
  prints the `sudo apt install` command for you to run (it never uses sudo itself).

## Two runtime fixes every OCR caller must apply

1. **Generation hangs on WSL2 without a GPU sync.** PaddleOCR-VL's first embedding call spins
   forever (CPU 100%, GPU 0%). `hklv_ocr.paddle_wsl_fix.apply()` synchronises the GPU before
   generation; with it a page reads in seconds. Reproduced 2/2 each way.
2. **Release the loader's spare GPU memory.** Loading the text model leaves ~7 GB reserved but
   only ~3 GB used. Call `paddle.device.cuda.empty_cache()` after building the pipeline, or
   an 8 GB card spills into shared system memory.

## Open issue for Pass 1: no confidence scores

PaddleOCR-VL returns text per layout block but **no confidence value**. The rules engine
FLAGs anything below a confidence threshold, so Pass 1 needs its own confidence signal
(for example token probabilities from generation, agreement between two reads, or MRZ/QR
cross-checks) before real documents can be judged.
