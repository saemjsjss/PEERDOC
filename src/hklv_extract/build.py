"""Pass 1 assembly: raw readings -> classified pages -> grouped documents -> CaseFile."""

from __future__ import annotations

import logging
import typing
from collections import Counter
from datetime import date

from pydantic import BaseModel, ConfigDict

from hklv_ocr.reading import CaseReading
from hklv_rules.models.case import CaseFile

from .classify import PageClass, PageKind, classify_pages
from .extractors import EXTRACTORS
from .group import group_pages

log = logging.getLogger(__name__)


class PageReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page_no: int
    source_file: str
    file_page: int
    kind: PageKind
    reason: str
    doc_id: str | None


class ExtractionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pages: tuple[PageReport, ...]


def build_case(reading: CaseReading, case_id: str, evaluation_date: date) -> tuple[CaseFile, ExtractionReport]:
    classes: list[PageClass] = classify_pages(reading.pages, evaluation_date)
    groups = group_pages(reading.pages, classes)
    counter: Counter[PageKind] = Counter()
    documents = []
    doc_of_page: dict[int, str] = {}
    for g in groups:
        extractor = EXTRACTORS.get(g.kind)
        if extractor is None:  # a recognised kind with no extractor yet
            continue
        counter[g.kind] += 1
        doc_id = f"{g.kind.value}-{counter[g.kind]}"
        try:
            documents.append(extractor(g, doc_id))
        except Exception as e:  # noqa: BLE001 - one unreadable document must not sink the case
            # Log the type only: messages could quote document content. With every field
            # empty, the document's rules FLAG it for a person instead of the case crashing.
            log.error("extracting %s failed: %s", doc_id, type(e).__name__)
            documents.append(typing.get_type_hints(extractor)["return"](doc_id=doc_id, pages=g.page_nos))
        for n in g.page_nos:
            doc_of_page[n] = doc_id
    report = ExtractionReport(
        pages=tuple(
            PageReport(
                page_no=p.page_no,
                source_file=p.source_file,
                file_page=p.file_page,
                kind=c.kind,
                reason=c.reason,
                doc_id=doc_of_page.get(p.page_no),
            )
            for p, c in zip(reading.pages, classes, strict=True)
        )
    )
    return CaseFile(case_id=case_id, evaluation_date=evaluation_date, documents=tuple(documents)), report
