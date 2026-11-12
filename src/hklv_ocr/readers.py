"""Run the three Pass 1 readers on uploaded files (GPU; inside the WSL OCR environment).

Usage from async code (the future FastAPI service, or ``scripts/wsl/read_case.py``)::

    reader = PageReader()            # loads both models once (~5 s)
    pages = await reader.read_files([Path("upload1.pdf"), Path("photo.jpg")])

Paddle inference is blocking and the GPU is a single shared resource, so every model call
runs in a worker thread (``asyncio.to_thread``) behind one lock.

Memory: pages are rendered and read strictly one at a time, and the GPU cache is released
(``paddle.device.cuda.empty_cache``) between the two readers and after every page. Paddle's
allocator otherwise keeps every block it ever reserved; text detection alone briefly fills
the 8 GB card, and anything run while that is still reserved spills into shared system
memory, which is many times slower. ``PageReader.stats`` records time and memory per page.
"""

from __future__ import annotations

import asyncio
import gc
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .reading import Barcode, Box, CaseReading, LayoutBlock, PageReading, TextLine
from .red_seal import find_red_seals

RENDER_DPI = 300  # PP-OCRv6 needs it for MRZ and small print
# A page image never exceeds this (an A4 page at 300 dpi is ~8.7 MP). A PDF page with a
# huge MediaBox is rendered at a lower scale, and a huge photo is shrunk, instead of
# allocating gigabytes and getting the server killed.
MAX_PAGE_PIXELS = 40_000_000
# Pillow refuses to open images above twice this ("decompression bomb"); set explicitly
# rather than relying on the library default. Uploads above it are rejected as unreadable.
MAX_IMAGE_PIXELS = 100_000_000
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


# PDFium is not thread-safe, even across documents. Every pypdfium2 call goes through this
# lock, so concurrent requests (each in its own worker thread) can't crash the process.
_PDFIUM = threading.Lock()


def page_count(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 1
    import pypdfium2 as pdfium

    with _PDFIUM:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()


def _pil_image():
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    return Image


def render_scale(width_pt: float, height_pt: float, dpi: int = RENDER_DPI) -> float:
    """PDF render scale: `dpi`, lowered so the page stays within MAX_PAGE_PIXELS."""
    scale = dpi / 72
    area = max(width_pt, 1.0) * max(height_pt, 1.0)
    return min(scale, (MAX_PAGE_PIXELS / area) ** 0.5)


def check_readable(path: Path) -> None:
    """Raise if the readers can't open this file (empty, truncated, not really a PDF/image)."""
    if path.suffix.lower() == ".pdf":
        if page_count(path) < 1:
            raise ValueError("PDF has no pages")
        return
    with _pil_image().open(path) as img:
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise ValueError("image has too many pixels")
        img.verify()


def render_page(path: Path, index: int, dpi: int = RENDER_DPI):
    """One page as an RGB PIL image (0-based index). Only this page is held in memory."""
    if path.suffix.lower() != ".pdf":
        with _pil_image().open(path) as img:
            if img.width * img.height > MAX_PAGE_PIXELS:
                factor = (MAX_PAGE_PIXELS / (img.width * img.height)) ** 0.5
                img.thumbnail((max(1, int(img.width * factor)), max(1, int(img.height * factor))))
            return img.convert("RGB")
    import pypdfium2 as pdfium

    with _PDFIUM:
        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[index]
            try:
                bitmap = page.render(scale=render_scale(*page.get_size(), dpi))
                image = bitmap.to_pil().convert("RGB")
                bitmap.close()
                return image
            finally:
                page.close()
        finally:
            pdf.close()


def _system_memory_mb() -> tuple[int | None, int | None]:
    """(available RAM, swap in use) in MB from /proc/meminfo; (None, None) elsewhere."""
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":", 1)
                info[key] = int(value.split()[0]) // 1024
        return info["MemAvailable"], info["SwapTotal"] - info["SwapFree"]
    except (OSError, KeyError, ValueError):
        return None, None


@dataclass(frozen=True)
class PageStat:
    """Time and memory for one page. GPU figures are Paddle's allocator, in MB."""

    source_file: str
    file_page: int
    seconds: float
    gpu_allocated_mb: int
    gpu_peak_reserved_mb: int  # highest reservation while reading this page
    gpu_reserved_after_mb: int  # after releasing the cache
    ram_available_mb: int | None
    swap_used_mb: int | None

    def line(self) -> str:
        ram = f", RAM free {self.ram_available_mb / 1024:.1f} GB" if self.ram_available_mb is not None else ""
        swap = f", swap {self.swap_used_mb} MB" if self.swap_used_mb else ""
        return (
            f"{self.source_file} #{self.file_page}: {self.seconds:.1f}s, GPU peak "
            f"{self.gpu_peak_reserved_mb / 1024:.2f} GB -> {self.gpu_reserved_after_mb / 1024:.2f} GB after clear{ram}{swap}"
        )


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
    def __init__(self, device: str = "gpu:0", progress: Callable[[PageStat], None] | None = None) -> None:
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
        # Seal recognition reads a stamp's curved ring text ("ADVOCATE ... NOTARY PUBLIC"),
        # which the line reader cannot; it is what confirms a stamp is a notary's.
        self._vl_model = PaddleOCRVL(pipeline_version="v1.6", device=device, use_seal_recognition=True)
        if device.startswith("gpu"):
            # Model loading leaves ~4 GB of temporary buffers reserved; on an 8 GB card that
            # pushes generation into shared system memory. Hand it back before inference.
            paddle.device.cuda.empty_cache()
        self._paddle = paddle
        self._on_gpu = device.startswith("gpu")
        # For A/B timing only: HKLV_KEEP_GPU_CACHE=1 restores the old behaviour.
        self._clear_each_page = self._on_gpu and os.environ.get("HKLV_KEEP_GPU_CACHE") != "1"
        self._gpu = asyncio.Lock()
        self.progress = progress
        # Recent pages only: a long-running server must not keep every upload's file name.
        self.stats: deque[PageStat] = deque(maxlen=200)

    check_readable = staticmethod(check_readable)
    page_count = staticmethod(page_count)

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
            for t, s, b in zip(res["rec_texts"], res["rec_scores"], boxes, strict=False)
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
        lines = self._lines(bgr)
        # Measured: text detection on a full 300-dpi page briefly reserves ~4.5 GB on top of
        # the ~3.5 GB of loaded models, i.e. the whole 8 GB card. Kept reserved, it makes the
        # slow PaddleOCR-VL generation that follows run in shared system memory (passport
        # page: 55 s instead of 16 s). Hand it back between the two readers.
        self._release_gpu_cache()
        blocks = self._blocks(bgr)
        # The layout model misses the notary's red foil seal; it is found by colour.
        blocks += tuple(LayoutBlock(label="red_seal", box=box, score=fill) for box, fill in find_red_seals(bgr))
        return lines, blocks, read_barcodes(image)

    def _release_gpu_cache(self) -> None:
        if self._clear_each_page:
            gc.collect()  # drop Python references to finished tensors first
            self._paddle.device.cuda.empty_cache()

    def _gpu_mb(self) -> tuple[int, int]:
        if not self._on_gpu:
            return 0, 0
        cuda = self._paddle.device.cuda
        return int(cuda.memory_allocated() / 2**20), int(cuda.memory_reserved() / 2**20)

    def _read_one_page(self, path: Path, index: int):
        """Render, read and release one page (runs in the worker thread)."""
        t = time.perf_counter()
        if self._on_gpu:
            self._paddle.device.cuda.reset_max_memory_reserved()
        image = render_page(path, index)
        size = (image.width, image.height)
        try:
            lines, blocks, barcodes = self._read_image(image)
        finally:
            image.close()
            del image
        peak = int(self._paddle.device.cuda.max_memory_reserved() / 2**20) if self._on_gpu else 0
        allocated, _ = self._gpu_mb()
        self._release_gpu_cache()
        _, reserved_after = self._gpu_mb()
        ram, swap = _system_memory_mb()
        stat = PageStat(path.name, index + 1, time.perf_counter() - t, allocated, peak, reserved_after, ram, swap)
        return size, lines, blocks, barcodes, stat

    # -- async API ---------------------------------------------------------------------

    async def read_file(
        self, path: Path, first_page_no: int = 1, progress: Callable[[PageStat], None] | None = None
    ) -> list[PageReading]:
        """Read one file page by page: render, OCR, release, then the next page."""
        pages = []
        for i in range(await asyncio.to_thread(page_count, path)):
            async with self._gpu:
                (width, height), lines, blocks, barcodes, stat = await asyncio.to_thread(self._read_one_page, path, i)
            self.stats.append(stat)
            callback = progress or self.progress  # per call (one job's pages) or reader-wide
            if callback is not None:
                callback(stat)
            pages.append(
                PageReading(
                    page_no=first_page_no + i,
                    source_file=path.name,
                    file_page=i + 1,
                    from_image_file=path.suffix.lower() in IMAGE_SUFFIXES,
                    width=width,
                    height=height,
                    lines=lines,
                    blocks=blocks,
                    barcodes=barcodes,
                )
            )
        return pages

    async def read_files(self, paths: Sequence[Path], progress: Callable[[PageStat], None] | None = None) -> CaseReading:
        pages: list[PageReading] = []
        for path in paths:
            pages.extend(await self.read_file(path, first_page_no=len(pages) + 1, progress=progress))
        return CaseReading(pages=tuple(pages), readers=self.versions())
