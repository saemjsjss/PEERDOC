"""HKLV document verification API.

    POST   /jobs          upload PDFs/images and/or ZIPs; returns a job id at once (202)
    GET    /jobs/{id}     progress (stage, pages read, time left) and, when done, the verdict
    DELETE /jobs/{id}     cancel a waiting or running job, or forget a finished one's verdict
    POST   /verify        the same in one request (waits for the verdict, ~8 min per case)

POST and DELETE need the header `X-HKLV: 1` (403 without it): a web page on another site
can't send a custom header without a CORS preflight, which this server never approves.
Requests must also name the host 127.0.0.1 or localhost (DNS-rebinding protection).
    GET    /health        is the server up, are the OCR models loaded
    GET    /              the web UI (frontend/dist), when it has been built

Run inside the WSL OCR environment (the OCR models need the GPU there):

    bash /mnt/c/dcSS/scripts/wsl/serve.sh          # or scripts\\serve.cmd from Windows

The server listens on 127.0.0.1 only. Uploads are written to a private work folder and
deleted as soon as their case is finished; verdicts are kept in memory for an hour at most.
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
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .jobs import Job, JobManager, JobStatus, JobView, QueueFull
from .responses import Counts, FileReport, OnlineResult, VerifyResponse, build_response  # noqa: F401 (re-exported)
from .uploads import MAX_UPLOAD_BYTES, SavedFiles, UploadError, drop_unreadable, save_uploads

log = logging.getLogger("hklv_api")
API_VERSION = "1.1.0"
# Multipart framing adds a little on top of the files themselves.
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 5 * 1024 * 1024
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
# A bigger case is refused at upload: it would hold the only GPU worker for hours.
MAX_PAGES = 300
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_HEADER = b"x-hklv"  # must be "1" on POST and DELETE


def _base_dir() -> Path:
    # HKLV_WORK_DIR (serve.sh sets it), else the system temp folder (TMPDIR).
    return Path(os.environ.get("HKLV_WORK_DIR") or tempfile.gettempdir())


def _work_dir() -> str:
    """This instance's own folder for case uploads. Two servers can't share a port, so a
    per-port folder keeps one instance's startup sweep away from another's live cases."""
    folder = _base_dir() / f"hklv-port-{os.environ.get('HKLV_PORT', '8000')}"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return str(folder)


def _sweep_leftover_uploads() -> int:
    """Delete case folders a killed server on this port left behind (one worker, so none of
    this instance's are in use yet), plus any from before per-port folders existed."""
    removed = 0
    for base in (Path(_work_dir()), _base_dir()):
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
    app.state.jobs = JobManager()
    app.state.jobs.start(app)
    try:
        yield
    finally:
        await app.state.jobs.stop()


app = FastAPI(
    title="HKLV Document Verification",
    version=API_VERSION,
    description="Checks a student's documents against Rulebook v2.5 and returns PASS, FLAG or FAIL.",
    lifespan=lifespan,
)


# --- request size --------------------------------------------------------------------------


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


class RequireCustomHeader:
    """403 for POST/DELETE without `X-HKLV: 1`. Browsers only send a custom header
    cross-origin after a CORS preflight, which this server never approves, so another web
    page the operator has open can't submit or delete jobs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in ("POST", "DELETE", "PUT", "PATCH"):
            if dict(scope.get("headers") or []).get(CSRF_HEADER) != b"1":
                return await _send_json(send, 403, "missing header X-HKLV: 1")
        return await self.app(scope, receive, send)


# Added innermost first: TrustedHost runs first, then the header check, then the size cap.
app.add_middleware(LimitRequestBody)
app.add_middleware(RequireCustomHeader)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


# --- shared steps --------------------------------------------------------------------------


def _reader(request: Request):
    reader = request.app.state.reader
    if reader is None:
        raise HTTPException(status_code=503, detail="OCR models are not loaded")
    return reader


async def _save_and_check(files: list[UploadFile], folder: Path, reader) -> SavedFiles:
    """Save the uploads, drop files the reader can't open; 400 if nothing usable is left."""
    try:
        saved = await save_uploads(files, folder)
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
    return saved


def _count_pages(folder: Path, saved: SavedFiles, reader) -> int:
    counter = getattr(reader, "page_count", None)
    if counter is None:
        return len(saved.accepted)
    total = 0
    for name in saved.accepted:
        try:
            total += counter(folder / name)
        except Exception:  # noqa: BLE001  (already checked readable; an estimate is enough)
            total += 1
    return total


async def _queue_upload(request: Request, files, case_id, evaluation_date, online) -> Job | None:
    """Save and check the upload, then queue it as a job. None if the client went away."""
    reader = _reader(request)
    folder = Path(tempfile.mkdtemp(prefix="hklv-case-", dir=_work_dir()))
    try:
        saved = await _save_and_check(files, folder, reader)
        pages = await asyncio.to_thread(_count_pages, folder, saved, reader)
        if pages > MAX_PAGES:
            raise HTTPException(status_code=413, detail=f"too many pages ({pages}; limit {MAX_PAGES})")
        # The client may have given up (Cancel) while the upload was being unpacked and
        # checked: don't queue a case nobody can follow or delete.
        if await request.is_disconnected():
            shutil.rmtree(folder, ignore_errors=True)
            return None
        return request.app.state.jobs.submit(
            folder,
            saved,
            case_id=(case_id or "").strip() or "upload",
            evaluation_date=evaluation_date or date.today(),
            online=online,
            pages_total=pages,
        )
    except QueueFull:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=503, detail="too many cases are waiting; try again later") from None
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


# --- routes --------------------------------------------------------------------------------

Files = Annotated[list[UploadFile], File(description="PDFs, images, and/or ZIP files of PDFs and images")]
CaseId = Annotated[str | None, Form(max_length=100)]
EvaluationDate = Annotated[date | None, Form(description="Defaults to today")]
Online = Annotated[bool, Form(description="Check e-Apostilles and challans on the official sites")]


@app.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "version": API_VERSION,
        "models_loaded": request.app.state.reader is not None,
        "server_id": request.app.state.jobs.server_id,
    }


@app.post("/jobs", status_code=202, responses={499: {"description": "client went away before the job was queued"}})
async def submit_job(
    request: Request, files: Files, case_id: CaseId = None, evaluation_date: EvaluationDate = None, online: Online = True
) -> JobView:
    job = await _queue_upload(request, files, case_id, evaluation_date, online)
    if job is None:
        return Response(status_code=499)
    return request.app.state.jobs.view(job)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> JobView:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="no such job (finished verdicts are kept for one hour, and a server restart forgets them)",
        )
    return request.app.state.jobs.view(job)


@app.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, request: Request) -> Response:
    # A running job stops after the page being read; its files are deleted then.
    request.app.state.jobs.delete(job_id)
    return Response(status_code=204)


@app.post("/verify")
async def verify(
    request: Request, files: Files, case_id: CaseId = None, evaluation_date: EvaluationDate = None, online: Online = True
) -> VerifyResponse:
    # Through the same queue as POST /jobs: same waiting limit, counted in everyone's ETA.
    job = await _queue_upload(request, files, case_id, evaluation_date, online)
    if job is None:
        return Response(status_code=499)
    try:
        await job.ended.wait()
    finally:
        request.app.state.jobs.delete(job.id)  # nobody polls a /verify job; cancels it if still going
    if job.status is not JobStatus.DONE or job.result is None:
        raise HTTPException(status_code=500, detail=job.error or "verification failed")
    return job.result


# The built web UI, served from the same origin as the API (no CORS needed). Mounted last
# so the API routes above take precedence.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")

__all__ = ["JobStatus", "app"]
