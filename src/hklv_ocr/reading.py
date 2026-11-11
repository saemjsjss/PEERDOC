"""Raw Pass 1 readings: what each reader saw on each page, before any interpretation.

Three independent readers look at every page:

* ``lines``    PP-OCRv6 text lines, each with the recogniser's own confidence score.
* ``blocks``   PaddleOCR-VL layout blocks (text, tables, seals, images). No scores.
* ``barcodes`` ZXing QR codes and barcodes. Deterministic: decoded or not.

This module has no Paddle dependency, so extraction and tests can run anywhere.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in page pixels


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TextLine(_Frozen):
    text: str
    score: float = Field(ge=0.0, le=1.0)
    box: Box


class LayoutBlock(_Frozen):
    label: str = Field(description="PaddleOCR-VL block label, e.g. text, table, seal, image, header")
    text: str = ""
    box: Box
    score: float | None = Field(default=None, ge=0.0, le=1.0, description="Layout detector's score for the block")


class Barcode(_Frozen):
    format: str = Field(description="ZXing format name, e.g. 'QRCode', 'Code128', 'PDF417'")
    text: str
    box: Box


class PageReading(_Frozen):
    page_no: int = Field(ge=1, description="1-based position of this page in the whole upload")
    source_file: str = Field(description="For traceability only; never used to classify")
    file_page: int = Field(ge=1)
    from_image_file: bool = Field(description="The upload was an image file (.jpg/.png), not a PDF")
    width: int
    height: int
    lines: tuple[TextLine, ...] = ()
    blocks: tuple[LayoutBlock, ...] = ()
    barcodes: tuple[Barcode, ...] = ()

    @property
    def line_text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def block_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text)


class CaseReading(_Frozen):
    pages: tuple[PageReading, ...] = ()
    readers: dict[str, str] = Field(default_factory=dict, description="Reader name -> version")
