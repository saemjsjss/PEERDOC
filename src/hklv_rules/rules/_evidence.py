from __future__ import annotations

from ..models import Evidence, Extracted


def ev(doc_id: str, field: str, value: Extracted) -> Evidence:
    return Evidence(
        doc_id=doc_id,
        field=field,
        value=None if value.value is None else str(value.value),
        page=value.source_page,
    )
