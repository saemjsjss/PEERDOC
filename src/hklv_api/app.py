"""HKLV document verification API.

    POST   /jobs          upload PDFs/images and/or ZIPs; returns a job id at once (202)
    GET    /jobs/{id}     progress (stage, pages read, time left) and, when done, the verdict
    DELETE /jobs/{id}     cancel a waiting job, or forget a finished one's verdict
    POST   /verify        the same in one request (waits for the verdict, ~8 min per case)
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

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles

from hklv_pipeline import run_case

from .jobs import JobManager, JobStatus, JobView, QueueFull
from .responses import Counts, FileReport, OnlineResult, VerifyResponse, build_response  # noqa: F401 (re-exported)
from .uploads import MAX_UPLOAD_BYTES, SavedFiles, UploadError, drop_unreadable, save_uploads

log = logging.getLogger("hklv_api")
API_VERSION = "1.1.0"
# Multipart framing adds a little on top of the files themselves.
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 5 * 1024 * 1024
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _work_dir() -> str | None:
    folder = os.environ.get("HKLV_WORK_DIR")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
    return folder  # None -> the system temp folder (TMPDIR)


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


app.add_middleware(LimitRequestBody)


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


# --- routes --------------------------------------------------------------------------------


@app.get("/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "version": API_VERSION, "models_loaded": request.app.state.reader is not None}


@app.post("/jobs", response_model=JobView, status_code=202, responses={499: {"description": "client went away before the job was queued"}})
async def submit_job(
    request: Request,
    files: list[UploadFile] = File(..., description="PDFs, images, and/or ZIP files of PDFs and images"),
    case_id: str | None = Form(None, max_length=100),
    evaluation_date: date | None = Form(None, description="Defaults to today"),
    online: bool = Form(True, description="Check e-Apostilles and challans on the official sites"),
) -> JobView:
    reader = _reader(request)
    folder = Path(tempfile.mkdtemp(prefix="hklv-case-", dir=_work_dir()))
    try:
        saved = await _save_and_check(files, folder, reader)
        pages = await asyncio.to_thread(_count_pages, folder, saved, reader)
        # The client may have given up (Cancel) while the upload was being unpacked and
        # checked: don't queue a case nobody can follow or delete.
        if await request.is_disconnected():
            shutil.rmtree(folder, ignore_errors=True)
            return Response(status_code=499)
        job = request.app.state.jobs.submit(
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
    return request.app.state.jobs.view(job)


@app.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str, request: Request) -> JobView:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job (finished verdicts are kept for one hour)")
    return request.app.state.jobs.view(job)


@app.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, request: Request) -> Response:
    if not request.app.state.jobs.delete(job_id):
        raise HTTPException(status_code=409, detail="the job is being read now and can't be stopped; delete it when it has finished")
    return Response(status_code=204)


@app.post("/verify", response_model=VerifyResponse)
async def verify(
    request: Request,
    files: list[UploadFile] = File(..., description="PDFs, images, and/or ZIP files of PDFs and images"),
    case_id: str | None = Form(None, max_length=100),
    evaluation_date: date | None = Form(None, description="Defaults to today"),
    online: bool = Form(True, description="Check e-Apostilles and challans on the official sites"),
) -> VerifyResponse:
    reader = _reader(request)
    with tempfile.TemporaryDirectory(prefix="hklv-case-", dir=_work_dir()) as tmp:
        folder = Path(tmp)
        saved = await _save_and_check(files, folder, reader)
        try:
            # Wait for the case being read (if any): one case on the GPU at a time.
            async with request.app.state.jobs.case_lock:
                result = await run_case(
                    folder,
                    case_id=(case_id or "").strip() or "upload",
                    evaluation_date=evaluation_date or date.today(),
                    reader=reader,
                    online=online,
                    fetch=request.app.state.fetch,
                )
        except Exception as e:  # noqa: BLE001
            # Log the type only: messages could quote document content.
            log.error("verification failed: %s", type(e).__name__)
            raise HTTPException(status_code=500, detail=f"verification failed ({type(e).__name__})") from None
    return build_response(result, saved)


# The built web UI, served from the same origin as the API (no CORS needed). Mounted last
# so the API routes above take precedence.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")

__all__ = ["JobStatus", "app"]
