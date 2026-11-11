"""HKLV document verification API.

    POST /verify   one or more PDFs/images and/or ZIPs -> the full pipeline -> JSON verdict
    GET  /health   is the server up, are the OCR models loaded

Run inside the WSL OCR environment (the OCR models need the GPU there):

    bash /mnt/c/dcSS/scripts/wsl/serve.sh          # or scripts\\serve.cmd from Windows

The server listens on 127.0.0.1 only. Uploads are written to a per-request temporary
folder and deleted when the response is ready; nothing is kept.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from hklv_extract.build import PageReport
from hklv_pipeline import run_case
from hklv_rules.models import EApostille, IncomeTaxChallan, Outcome, RuleResult
from hklv_rules.models.case import Document

from .uploads import MAX_UPLOAD_BYTES, SavedFiles, UploadError, drop_unreadable, save_uploads

log = logging.getLogger("hklv_api")
API_VERSION = "1.0.0"
# Multipart framing adds a little on top of the files themselves.
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 5 * 1024 * 1024


# --- response models -----------------------------------------------------------------------


class OnlineResult(BaseModel):
    doc_id: str
    kind: str
    status: str | None = Field(description="VERIFIED / NOT_FOUND / UNAVAILABLE / NOT_RUN, or null if not checked")
    detail: str = ""


class FileReport(BaseModel):
    accepted: list[str]
    ignored: list[dict[str, str]]
    ignored_more: int = Field(0, description="Further ignored files not listed by name")


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


# --- app -----------------------------------------------------------------------------------


def _sweep_leftover_uploads() -> int:
    """Delete case folders a killed server left behind (one worker, so none are in use)."""
    base = Path(_work_dir() or tempfile.gettempdir())
    removed = 0
    for folder in base.glob("hklv-case-*"):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


@asynccontextmanager
async def lifespan(app: FastAPI):
    removed = _sweep_leftover_uploads()
    if removed:
        log.info("removed %d upload folder(s) left by an earlier run", removed)
    app.state.reader = getattr(app.state, "reader", None)
    app.state.fetch = getattr(app.state, "fetch", None)  # None -> real HTTP; tests inject a fake
    if app.state.reader is None and os.environ.get("HKLV_LOAD_MODELS", "1") == "1":
        from hklv_ocr.readers import PageReader

        log.info("loading OCR models")
        app.state.reader = await asyncio.to_thread(PageReader)
        log.info("OCR models loaded")
    yield


app = FastAPI(
    title="HKLV Document Verification",
    version=API_VERSION,
    description="Checks a student's documents against Rulebook v2.5 and returns PASS, FLAG or FAIL.",
    lifespan=lifespan,
)


class LimitRequestBody:
    """Cap request bodies by the bytes actually received, not only by Content-Length, so a
    chunked upload (no Content-Length) can't spool an unlimited body to disk. Once the cap
    is passed, reading stops and the client gets 413."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = MAX_REQUEST_BYTES  # read at call time (tests lower it)
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                return await _send_json(send, 400, "invalid Content-Length")
            if declared > limit:
                return await _send_json(send, 413, _too_large())
        received = 0
        exceeded = False

        async def counting_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        replaced = False

        async def guarded_send(message):
            nonlocal replaced
            if exceeded and message["type"] == "http.response.start" and not replaced:
                replaced = True
                return await _send_json(send, 413, _too_large())
            if replaced:
                return None  # swallow the app's own error response
            return await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            if not replaced:
                await _send_json(send, 413, _too_large())


class _BodyTooLarge(Exception):
    pass


def _too_large() -> str:
    return f"upload is too large (limit {MAX_UPLOAD_BYTES // 2**20} MB)"


async def _send_json(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


app.add_middleware(LimitRequestBody)


@app.get("/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "version": API_VERSION, "models_loaded": request.app.state.reader is not None}


def _work_dir() -> str | None:
    folder = os.environ.get("HKLV_WORK_DIR")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
    return folder  # None -> the system temp folder (TMPDIR)


@app.post("/verify", response_model=VerifyResponse)
async def verify(
    request: Request,
    files: list[UploadFile] = File(..., description="PDFs, images, and/or ZIP files of PDFs and images"),
    case_id: str | None = Form(None, max_length=100),
    evaluation_date: date | None = Form(None, description="Defaults to today"),
    online: bool = Form(True, description="Check e-Apostilles and challans on the official sites"),
) -> VerifyResponse:
    reader = request.app.state.reader
    if reader is None:
        raise HTTPException(status_code=503, detail="OCR models are not loaded")
    when = evaluation_date or date.today()
    with tempfile.TemporaryDirectory(prefix="hklv-case-", dir=_work_dir()) as tmp:
        folder = Path(tmp)
        try:
            saved: SavedFiles = await save_uploads(files, folder)
            # Let the reader reject files it can't open (empty, truncated, a .docx renamed
            # .pdf): they are listed as ignored instead of failing the whole case.
            check = getattr(reader, "check_readable", None)
            if check is not None:
                await asyncio.to_thread(drop_unreadable, folder, saved, check)
        except UploadError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message) from None
        except Exception as e:  # noqa: BLE001  (never log or echo file names / content)
            log.error("saving the upload failed: %s", type(e).__name__)
            raise HTTPException(status_code=500, detail=f"could not save the upload ({type(e).__name__})") from None
        if not saved.accepted:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "no readable PDF or image files found in the upload",
                    "ignored": saved.ignored,
                    "ignored_more": saved.ignored_more,
                },
            )
        try:
            result = await run_case(
                folder,
                case_id=(case_id or "").strip() or "upload",
                evaluation_date=when,
                reader=reader,
                online=online,
                fetch=request.app.state.fetch,
            )
        except Exception as e:  # noqa: BLE001
            # Log the type only: messages could quote document content.
            log.error("verification failed: %s", type(e).__name__)
            raise HTTPException(status_code=500, detail=f"verification failed ({type(e).__name__})") from None
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
        files=FileReport(accepted=saved.accepted, ignored=saved.ignored, ignored_more=saved.ignored_more),
        timings={k: round(v, 2) for k, v in result.seconds.items()},
    )
