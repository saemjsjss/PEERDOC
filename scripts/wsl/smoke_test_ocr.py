"""Pass 1 smoke test: can PaddleOCR-VL-1.6 read a document on this GPU?

Draws a fictional TIN-style certificate (no real person's data), runs the full
PaddleOCR-VL pipeline on it, and prints what came back, how long it took and how
much GPU memory it used. Run inside the OCR venv in WSL:

    source ~/hklv-ocr/.venv/bin/activate
    python /mnt/c/dcSS/scripts/wsl/smoke_test_ocr.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Fictional test data only.
LINES = [
    ("GOVERNMENT OF THE PEOPLE'S REPUBLIC OF BANGLADESH", 34),
    ("NATIONAL BOARD OF REVENUE", 34),
    ("Taxpayer's Identification Number (TIN) Certificate", 30),
    ("", 20),
    ("TIN: 123456789012", 30),
    ("Name: MD. KAMAL UDDIN", 30),
    ("Father's Name: ABDUL KARIM", 30),
    ("Status: Individual", 30),
    ("Date: 10 November 2026", 30),
]
EXPECTED = ["NATIONAL BOARD OF REVENUE", "123456789012", "KAMAL UDDIN", "ABDUL KARIM"]


def make_document(path: Path) -> None:
    img = Image.new("RGB", (1240, 900), "white")
    draw = ImageDraw.Draw(img)
    y = 80
    for text, size in LINES:
        font = ImageFont.load_default(size=size)
        draw.text((90, y), text, fill="black", font=font)
        y += int(size * 1.9)
    draw.rectangle((40, 40, 1200, 860), outline="black", width=3)
    img.save(path)


def main() -> int:
    import faulthandler
    import os

    if os.environ.get("HKLV_TRACE_EVERY"):
        # Debug aid: print every thread's stack periodically, to see where a slow run is.
        faulthandler.dump_traceback_later(int(os.environ["HKLV_TRACE_EVERY"]), repeat=True)

    import paddle
    from paddleocr import PaddleOCRVL

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from hklv_ocr import paddle_wsl_fix

    print("WSL generation fix active:", paddle_wsl_fix.apply())

    print(f"paddle {paddle.__version__}, GPUs: {paddle.device.cuda.device_count()}")
    work = Path(tempfile.mkdtemp(prefix="hklv-smoke-"))
    doc = work / "fictional_tin.png"
    make_document(doc)
    print(f"Test document: {doc}")

    t0 = time.perf_counter()
    pipeline = PaddleOCRVL(pipeline_version="v1.6", device="gpu:0")
    # Loading the VL model leaves ~4 GB of temporary buffers reserved (7.1 GB reserved vs
    # 2.7 GB in use). On an 8 GB card that pushes generation into shared system memory,
    # which is extremely slow. Hand the unused reserve back before inference.
    reserved_before = paddle.device.cuda.memory_reserved() / 2**30
    paddle.device.cuda.empty_cache()
    print(
        f"GPU memory reserved after load: {reserved_before:.2f} GiB -> "
        f"{paddle.device.cuda.memory_reserved() / 2**30:.2f} GiB after releasing cache"
    )
    t1 = time.perf_counter()
    results = list(pipeline.predict(str(doc)))
    t2 = time.perf_counter()

    text_parts: list[str] = []
    for res in results:
        data = res.json
        payload = data.get("res", data)
        out = work / "result.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"Raw result saved: {out}")
        print("Top-level keys:", sorted(payload.keys()))
        for block in payload.get("parsing_res_list", []):
            label, content = block.get("block_label"), block.get("block_content", "")
            print(f"  [{label}] {content!r}")
            text_parts.append(str(content))

    full = "\n".join(text_parts).upper()
    found = {e: e in full for e in EXPECTED}
    print(f"\nModel load: {t1 - t0:.1f}s, first page: {t2 - t1:.1f}s")
    print(f"Peak GPU memory: {paddle.device.cuda.max_memory_allocated() / 2**30:.2f} GiB (Paddle allocator)")
    print("Expected text found:", found)
    ok = all(found.values())
    print("SMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
