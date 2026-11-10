"""Workaround: PaddleOCR-VL generation hangs on WSL2 unless the GPU is synchronised first.

Found on Paddle 3.2.1 (cu129) + PaddleX 3.7 + RTX 5060 under WSL2. The very first
embedding call inside PaddleOCR-VL's text generation never returns: the CPU spins at
100% while the GPU sits idle. Calling paddle.device.synchronize() before generation
makes the same call finish in milliseconds, and the whole page reads in ~1.5 s.
Reproduced 2/2 times each way with a fictional one-line image.

Most likely a cross-stream ordering problem in Paddle that surfaces under the WSL2
GPU driver. Remove this once a Paddle release no longer needs it: run
scripts/wsl/smoke_test_ocr.py with HKLV_SKIP_WSL_FIX=1; if it finishes, drop the fix.
"""

from __future__ import annotations

import functools
import os

_APPLIED = False


def apply() -> bool:
    """Wrap PaddleOCR-VL's generate() so the GPU is synchronised first. Idempotent.

    Returns True if the wrapper is active.
    """
    global _APPLIED
    if _APPLIED:
        return True
    if os.environ.get("HKLV_SKIP_WSL_FIX") == "1":
        return False

    import paddle
    from paddlex.inference.models.doc_vlm.modeling.paddleocr_vl._paddleocr_vl import (
        PaddleOCRVLForConditionalGeneration as Model,
    )

    original = Model.generate

    @functools.wraps(original)
    def generate(self, inputs, **kwargs):
        paddle.device.synchronize()
        return original(self, inputs, **kwargs)

    Model.generate = generate
    _APPLIED = True
    return True
