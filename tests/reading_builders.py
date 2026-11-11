"""Fictional page readings for Pass 1 extraction tests. No real person's data."""

from __future__ import annotations

from collections.abc import Sequence

from hklv_ocr.reading import Barcode, LayoutBlock, PageReading, TextLine

LineSpec = str | tuple[str, float]


def make_page(
    lines: Sequence[LineSpec],
    *,
    page_no: int = 1,
    vl_text: str | None = None,
    blocks: Sequence[LayoutBlock] = (),
    barcodes: Sequence[Barcode] = (),
    from_image_file: bool = False,
    seal: bool = False,
    seal_score: float | None = 0.95,
) -> PageReading:
    """One page; each line on its own row. The VL reader sees the same text unless `vl_text` is given."""
    text_lines = []
    for i, spec in enumerate(lines):
        text, score = (spec, 0.99) if isinstance(spec, str) else spec
        text_lines.append(TextLine(text=text, score=score, box=(100, 100 + i * 60, 1500, 140 + i * 60)))
    vl = "\n".join(t.text for t in text_lines) if vl_text is None else vl_text
    all_blocks = [LayoutBlock(label="text", text=vl, box=(90, 90, 1600, 200 + len(lines) * 60))]
    all_blocks.extend(blocks)
    if seal:
        all_blocks.append(LayoutBlock(label="seal", text="", box=(1700, 2500, 2100, 2900), score=seal_score))
    return PageReading(
        page_no=page_no,
        source_file="fictional.pdf",
        file_page=page_no,
        from_image_file=from_image_file,
        width=2480,
        height=3508,
        lines=tuple(text_lines),
        blocks=tuple(all_blocks),
        barcodes=tuple(barcodes),
    )


def table_block(rows: Sequence[Sequence[str]]) -> LayoutBlock:
    html = "<table>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"
    return LayoutBlock(label="table", text=html, box=(100, 1500, 2300, 2200))


def qr(text: str) -> Barcode:
    return Barcode(format="QRCode", text=text, box=(2000, 200, 2300, 500))
