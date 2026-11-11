"""Run the three Pass 1 readers on uploaded files (GPU; inside the WSL OCR environment).

Usage from async code (the future FastAPI service, or ``scripts/wsl/read_case.py``)::

    reader = PageReader()            # loads both models once (~5 s)
    pages = await reader.read_files([Path("upload1.pdf"), Path("photo.jpg")])

Paddle inference is blocking and the GPU is a single shared resource, so every model call
runs in a worker thread (``asyncio.to_thread``) behind one lock.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path

from .reading import Barcode, Box, CaseReading, LayoutBlock, PageReading, TextLine

RENDER_DPI = 300  # PP-OCRv6 needs it for MRZ and small print
# PaddleOCR-VL reads well at ~150 dpi; at 300 dpi each block costs ~4x the vision tokens.
VL_SCALE = 0.5
# Per-block generation cap (library default 4096). PaddleOCR-VL sometimes loops on repeated
# text after the real content; this bounds the time lost. Long tables still fit.
VL_MAX_NEW_TOKENS = 2048
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}


def _box(values) -> Box:
    x0, y0, x1, y1 = (int(round(float(v))) for v in list(values)[:4])
    return (x0, y0, x1, y1)


def iter_page_images(path: Path, dpi: int = RENDER_DPI) -> Iterator:
    """Yield one RGB PIL image per page."""
    from PIL import Image

    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            for i in range(len(pdf)):
                yield pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")
        finally:
            pdf.close()
    else:
        with Image.open(path) as img:
            yield img.convert("RGB")


def read_barcodes(image) -> tuple[Barcode, ...]:
    import zxingcpp

    found = []
    for r in zxingcpp.read_barcodes(image):
        if not r.valid:
            continue
        p = r.position
        xs = [p.top_left.x, p.top_right.x, p.bottom_left.x, p.bottom_right.x]
        ys = [p.top_left.y, p.top_right.y, p.bottom_left.y, p.bottom_right.y]
        fmt = str(r.format).split(".")[-1].replace(" ", "")
        found.append(Barcode(format=fmt, text=r.text, box=(min(xs), min(ys), max(xs), max(ys))))
    return tuple(found)


class PageReader:
    def __init__(self, device: str = "gpu:0") -> None:
        import paddle
        from paddleocr import PaddleOCR, PaddleOCRVL

        from . import paddle_wsl_fix

        paddle_wsl_fix.apply()
        self._lines_model = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=device,
        )
        self._vl_model = PaddleOCRVL(pipeline_version="v1.6", device=device)
        if device.startswith("gpu"):
            # Model loading leaves ~4 GB of temporary buffers reserved; on an 8 GB card that
            # pushes generation into shared system memory. Hand it back before inference.
            paddle.device.cuda.empty_cache()
        self._gpu = asyncio.Lock()

    @staticmethod
    def versions() -> dict[str, str]:
        from importlib.metadata import version

        return {
            "lines": f"PaddleOCR {version('paddleocr')} (PP-OCRv6 default det/rec)",
            "blocks": f"PaddleOCR-VL-1.6 via paddlex {version('paddlex')}",
            "barcodes": f"zxing-cpp {version('zxing-cpp')}",
            "render_dpi": str(RENDER_DPI),
        }

    # -- blocking model calls (run in a worker thread) ---------------------------------

    def _lines(self, bgr) -> tuple[TextLine, ...]:
        res = next(iter(self._lines_model.predict(bgr))).json["res"]
        boxes = res.get("rec_boxes")
        if boxes is None or len(boxes) != len(res["rec_texts"]):
            boxes = [
                (min(x for x, _ in poly), min(y for _, y in poly), max(x for x, _ in poly), max(y for _, y in poly))
                for poly in res["rec_polys"]
            ]
        return tuple(
            TextLine(text=t, score=max(0.0, min(1.0, float(s))), box=_box(b))
            for t, s, b in zip(res["rec_texts"], res["rec_scores"], boxes)
            if t.strip()
        )

    def _blocks(self, bgr) -> tuple[LayoutBlock, ...]:
        import cv2

        small = cv2.resize(bgr, None, fx=VL_SCALE, fy=VL_SCALE, interpolation=cv2.INTER_AREA)
        res = next(iter(self._vl_model.predict(small, max_new_tokens=VL_MAX_NEW_TOKENS))).json
        res = res.get("res", res)
        # The layout detector scores each box; parsing blocks carry the same coordinates.
        scores = {
            (_box(d["coordinate"]), d.get("label")): float(d["score"])
            for d in (res.get("layout_det_res") or {}).get("boxes", [])
            if "coordinate" in d and "score" in d
        }
        blocks = []
        for b in res.get("parsing_res_list", []):
            box, label = _box(b["block_bbox"]), b.get("block_label", "")
            score = scores.get((box, label))
            blocks.append(
                LayoutBlock(
                    label=label,
                    text=str(b.get("block_content") or ""),
                    box=_box(v / VL_SCALE for v in box),  # back to page pixels
                    score=None if score is None else max(0.0, min(1.0, score)),
                )
            )
        return tuple(blocks)

    def _read_image(self, image) -> tuple[tuple[TextLine, ...], tuple[LayoutBlock, ...], tuple[Barcode, ...]]:
        import numpy as np

        bgr = np.ascontiguousarray(np.array(image)[:, :, ::-1])
        return self._lines(bgr), self._blocks(bgr), read_barcodes(image)

    # -- async API ---------------------------------------------------------------------

    async def read_file(self, path: Path, first_page_no: int = 1) -> list[PageReading]:
        images = await asyncio.to_thread(lambda: list(iter_page_images(path)))
        pages = []
        for i, image in enumerate(images):
            async with self._gpu:
                lines, blocks, barcodes = await asyncio.to_thread(self._read_image, image)
            pages.append(
                PageReading(
                    page_no=first_page_no + i,
                    source_file=path.name,
                    file_page=i + 1,
                    from_image_file=path.suffix.lower() in IMAGE_SUFFIXES,
                    width=image.width,
                    height=image.height,
                    lines=lines,
                    blocks=blocks,
                    barcodes=barcodes,
                )
            )
        return pages

    async def read_files(self, paths: Sequence[Path]) -> CaseReading:
        pages: list[PageReading] = []
        for path in paths:
            pages.extend(await self.read_file(path, first_page_no=len(pages) + 1))
        return CaseReading(pages=tuple(pages), readers=self.versions())
