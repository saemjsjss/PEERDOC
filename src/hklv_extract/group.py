"""Group classified pages into documents (e.g. an NID card and its notarised translation).

Consecutive pages of the same kind form one document, except:

* kinds that are always one page (photo, apostille, certificate, transcript);
* identity documents whose card number shows a different person. The number comes from a
  valid MRZ, or else from a printed "NID No". A card and its own translation may differ by
  a typo (NID-03 must see that), so only numbers differing in 4+ digits split.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from hklv_ocr.reading import PageReading

from .classify import PageClass, PageKind
from .text import find_labeled, levenshtein

SINGLE_PAGE = {PageKind.PHOTO, PageKind.E_APOSTILLE, PageKind.ACADEMIC_CERTIFICATE, PageKind.ACADEMIC_TRANSCRIPT}
IDENTITY_KINDS = {PageKind.NID, PageKind.PASSPORT}
ID_LABELS = [r"NID\s*(?:No|Number)\.?", r"\bID\s*NO\.?", r"National\s*ID\s*(?:No|Number)\.?"]
SAME_PERSON_MAX_DIGITS = 3


def page_identity(page: PageReading, cls: PageClass) -> str | None:
    if cls.mrz is not None and cls.mrz.checks.get("document_number"):
        return cls.mrz.document_number
    found = find_labeled(page, ID_LABELS, value_pattern=r"\d[\d ]{8,20}\d")
    return re.sub(r"\D", "", found.value) if found else None


def _same_person(a: str, b: str) -> bool:
    return levenshtein(a, b) <= SAME_PERSON_MAX_DIGITS


@dataclass
class PageGroup:
    kind: PageKind
    pages: list[PageReading] = field(default_factory=list)
    classes: list[PageClass] = field(default_factory=list)
    identities: set[str] = field(default_factory=set)

    @property
    def page_nos(self) -> tuple[int, ...]:
        return tuple(p.page_no for p in self.pages)


def group_pages(pages: Sequence[PageReading], classes: Sequence[PageClass]) -> list[PageGroup]:
    groups: list[PageGroup] = []
    current: PageGroup | None = None
    for page, cls in zip(pages, classes):
        if cls.kind == PageKind.IGNORED:
            current = None
            continue
        identity = page_identity(page, cls) if cls.kind in IDENTITY_KINDS else None
        joins = current is not None and current.kind == cls.kind and cls.kind not in SINGLE_PAGE
        if joins and identity is not None and current.identities:
            joins = any(_same_person(identity, known) for known in current.identities)
        if not joins:
            current = PageGroup(kind=cls.kind)
            groups.append(current)
        current.pages.append(page)
        current.classes.append(cls)
        if identity is not None:
            current.identities.add(identity)
    return groups
