"""The verdict JSON returned by POST /verify and by a finished job."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from hklv_extract.build import PageReport
from hklv_pipeline import PipelineResult
from hklv_rules.models import EApostille, IncomeTaxChallan, Outcome, RuleResult
from hklv_rules.models.case import Document

from .uploads import SavedFiles


class OnlineResult(BaseModel):
    doc_id: str
    kind: str
    status: str | None = Field(description="VERIFIED / NOT_FOUND / UNAVAILABLE / NOT_RUN, or null if not checked")
    detail: str = ""


class FileReport(BaseModel):
    accepted: list[str]
    ignored: list[dict[str, str]]
    ignored_more: int = Field(0, description="Further ignored files not listed by name")

    @classmethod
    def of(cls, saved: SavedFiles) -> FileReport:
        return cls(accepted=list(saved.accepted), ignored=list(saved.ignored), ignored_more=saved.ignored_more)


class Counts(BaseModel):
    passed: int
    flagged: int
    failed: int


class VerifyResponse(BaseModel):
    case_id: str
    evaluation_date: date
    outcome: Outcome = Field(description="Final overall verdict: PASS, FLAG (manual review) or FAIL")
    summary: str
    counts: Counts
    failures: list[RuleResult]
    flags: list[RuleResult]
    results: list[RuleResult] = Field(description="Every rule result, PASS included")
    documents: list[Document] = Field(description="The documents Pass 1 extracted, with confidences")
    pages: list[PageReport] = Field(description="How each uploaded page was classified")
    online: list[OnlineResult]
    files: FileReport
    timings: dict[str, float]


def build_response(result: PipelineResult, saved: SavedFiles) -> VerifyResponse:
    verdict = result.verdict
    return VerifyResponse(
        case_id=result.case.case_id,
        evaluation_date=result.case.evaluation_date,
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
        documents=list(result.case.documents),
        pages=list(result.report.pages),
        online=[
            OnlineResult(
                doc_id=d.doc_id,
                kind=d.kind,
                status=d.online.status.value if d.online else None,
                detail=d.online.detail if d.online else "",
            )
            for d in result.case.documents
            if isinstance(d, (EApostille, IncomeTaxChallan))
        ],
        files=FileReport.of(saved),
        timings={k: round(v, 2) for k, v in result.seconds.items()},
    )
