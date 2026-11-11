"""Write a fictional verdict JSON for the frontend's component tests.

Runs the real rules engine on the fictional test case from tests/builders.py (no real
person's data), with two weak readings so the verdict is FLAG, and saves the response in
the exact shape POST /verify and GET /jobs/{id} return.

    .venv\\Scripts\\python.exe scripts\\make_ui_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]

from builders import birth_certificate, case_file, complete_case_documents, nid, notarised, MOTHER  # noqa: E402

from hklv_api.responses import Counts, FileReport, OnlineResult, VerifyResponse  # noqa: E402
from hklv_extract.build import PageReport  # noqa: E402
from hklv_extract.classify import PageKind  # noqa: E402
from hklv_rules.engine import evaluate_case  # noqa: E402
from hklv_rules.models import Outcome  # noqa: E402

OUT = REPO / "frontend" / "src" / "test" / "fixtures" / "verdict-flag.json"


def main() -> None:
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-mother"]
    docs.append(nid("n-mother", MOTHER, number="6661234567", notary=notarised(stamp=True, confidence=0.82)))
    case = case_file(*docs)
    # Replace the default birth certificate with one whose registration number is shaky.
    case = case.model_copy(
        update={
            "case_id": "fictional-0417",
            "documents": tuple(
                birth_certificate(field_confidence=0.6) if d.doc_id == "birth" else d for d in case.documents
            ),
        }
    )
    verdict = evaluate_case(case)
    pages = [
        PageReport(page_no=i + 1, source_file=f"{d.doc_id}.pdf", file_page=1, kind=PageKind(d.kind) if d.kind in PageKind._value2member_map_ else PageKind.IGNORED, reason="fictional", doc_id=d.doc_id)
        for i, d in enumerate(case.documents)
    ]
    response = VerifyResponse(
        case_id=case.case_id,
        evaluation_date=case.evaluation_date,
        outcome=verdict.outcome,
        summary=verdict.summary,
        counts=Counts(
            passed=sum(1 for r in verdict.results if r.outcome is Outcome.PASS),
            flagged=len(verdict.flags),
            failed=len(verdict.failures),
        ),
        failures=list(verdict.failures),
        flags=list(verdict.flags),
        results=list(verdict.results),
        documents=list(case.documents),
        pages=pages,
        online=[OnlineResult(doc_id=d.doc_id, kind=d.kind, status=d.online.status.value, detail="fictional register entry") for d in case.documents if d.kind == "e_apostille"],
        files=FileReport(accepted=[p.source_file for p in pages], ignored=[{"name": "notes.txt", "reason": "not a PDF, image or ZIP"}]),
        timings={"ocr": 512.3, "extraction": 0.2, "online": 3.1, "rules": 0.0},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(response.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(REPO)}: {response.outcome.value}, {response.counts}")


if __name__ == "__main__":
    main()
