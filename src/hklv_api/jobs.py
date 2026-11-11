"""Background verification jobs: submit, poll, collect.

A full case takes several minutes (almost all OCR), too long to hold one HTTP request open.
So POST /jobs stores the upload, returns a job id at once, and a single worker runs the
jobs one at a time (the GPU is one shared resource). GET /jobs/{id} reports progress
(stage, pages read, estimated time left) and, once finished, the verdict.

Privacy: a job's uploaded files are deleted as soon as it finishes, fails or is cancelled.
The verdict (which contains personal data) is kept in memory only, and only for
KEEP_RESULT_SECONDS after the job ends or until the client deletes it; a server restart
forgets everything. Job ids are long random tokens, so they can't be guessed.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from hklv_pipeline import run_case

from .responses import FileReport, VerifyResponse, build_response
from .uploads import SavedFiles

log = logging.getLogger("hklv_api.jobs")

MAX_WAITING_JOBS = 20
KEEP_RESULT_SECONDS = 60 * 60
DEFAULT_SECONDS_PER_PAGE = 15.0  # until this server has timed some real pages
CHECKING_SECONDS = 10.0  # online checks + rules after OCR
SWEEP_EVERY_SECONDS = 2.0  # a scan of a few in-memory jobs: cheap


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Stage(StrEnum):
    WAITING = "waiting"  # in the queue behind other jobs
    READING = "reading"  # OCR, page by page
    CHECKING = "checking"  # online checks and rules
    FINISHED = "finished"


STAGE_MESSAGES = {
    Stage.WAITING: "Waiting for the reader",
    Stage.READING: "Reading the documents",
    Stage.CHECKING: "Checking against the rulebook",
    Stage.FINISHED: "Finished",
}


@dataclass
class Job:
    id: str
    folder: Path
    files: SavedFiles
    case_id: str
    evaluation_date: date
    online: bool
    pages_total: int
    status: JobStatus = JobStatus.QUEUED
    stage: Stage = Stage.WAITING
    pages_done: int = 0
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: VerifyResponse | None = None
    error: str | None = None
    cancelled: bool = False  # set by DELETE; a running job stops after the current page
    ended: asyncio.Event = field(default_factory=asyncio.Event)  # set when the run is over


class JobCancelled(Exception):
    """Raised from the progress callback to stop a job that DELETE cancelled."""


class JobView(BaseModel):
    job_id: str
    server_id: str = Field(description="Changes when the server restarts (a restart forgets every job)")
    status: JobStatus
    stage: Stage
    message: str
    case_id: str
    pages_done: int
    pages_total: int
    progress: float = Field(ge=0.0, le=1.0, description="0..1, for a progress bar")
    eta_seconds: int | None = Field(description="Estimated seconds until the verdict; null when finished")
    queue_position: int | None = Field(description="Jobs ahead of this one (0 = next); null unless queued")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    files: FileReport
    result: VerifyResponse | None = Field(description="The verdict, once status is 'done'")
    error: str | None = Field(description="What went wrong, once status is 'failed' (error type only)")


def _when(ts: float | None) -> datetime | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=UTC)


class QueueFull(Exception):
    pass


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task | None = None
        self.janitor: asyncio.Task | None = None
        self.seconds_per_page: float | None = None  # learned from finished jobs
        # One case reads at a time (POST /jobs and POST /verify both go through the queue).
        self.case_lock = asyncio.Lock()
        # Random per start: lets a client tell "the server restarted" from "the verdict expired".
        self.server_id = secrets.token_urlsafe(8)

    # -- lifecycle ------------------------------------------------------------------------

    def start(self, app) -> None:
        self.worker = asyncio.create_task(self._work(app), name="hklv-job-worker")
        self.janitor = asyncio.create_task(self._sweep_forever(), name="hklv-job-janitor")

    async def stop(self) -> None:
        for task in (self.worker, self.janitor):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for job in list(self.jobs.values()):
            shutil.rmtree(job.folder, ignore_errors=True)
        self.jobs.clear()

    # -- API --------------------------------------------------------------------------------

    def submit(self, folder: Path, files: SavedFiles, case_id: str, evaluation_date: date, online: bool, pages_total: int) -> Job:
        self.forget_expired()
        waiting = sum(1 for j in self.jobs.values() if j.status is JobStatus.QUEUED)
        if waiting >= MAX_WAITING_JOBS:
            raise QueueFull()
        job = Job(
            id=secrets.token_urlsafe(18),
            folder=folder,
            files=files,
            case_id=case_id,
            evaluation_date=evaluation_date,
            online=online,
            pages_total=max(1, pages_total),
        )
        self.jobs[job.id] = job
        self.queue.put_nowait(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        self.forget_expired()
        return self.jobs.get(job_id)

    def delete(self, job_id: str) -> None:
        """Cancel a queued or running job, or forget a finished one. A running job stops
        after the page being read (its files are deleted when it stops)."""
        job = self.jobs.pop(job_id, None)
        if job is None:
            return
        job.cancelled = True  # a queued id still in the queue is skipped by the worker
        if job.status is not JobStatus.RUNNING:
            shutil.rmtree(job.folder, ignore_errors=True)

    def forget_expired(self) -> None:
        now = time.time()
        for job_id, job in list(self.jobs.items()):
            if job.finished is not None and now - job.finished > KEEP_RESULT_SECONDS:
                del self.jobs[job_id]

    async def _sweep_forever(self) -> None:
        # Verdicts hold personal data: drop them on time even if nobody asks again.
        while True:
            await asyncio.sleep(SWEEP_EVERY_SECONDS)
            self.forget_expired()

    def view(self, job: Job) -> JobView:
        return JobView(
            job_id=job.id,
            server_id=self.server_id,
            status=job.status,
            stage=job.stage,
            message=STAGE_MESSAGES[job.stage],
            case_id=job.case_id,
            pages_done=job.pages_done,
            pages_total=job.pages_total,
            progress=self._progress(job),
            eta_seconds=self._eta(job),
            queue_position=self._position(job),
            created_at=_when(job.created),
            started_at=_when(job.started),
            finished_at=_when(job.finished),
            files=FileReport.of(job.files),
            result=job.result,
            error=job.error,
        )

    # -- progress -------------------------------------------------------------------------

    def _per_page(self) -> float:
        return self.seconds_per_page or DEFAULT_SECONDS_PER_PAGE

    def _progress(self, job: Job) -> float:
        if job.status in (JobStatus.DONE, JobStatus.FAILED):
            return 1.0
        if job.status is JobStatus.QUEUED:
            return 0.0
        # Reading is ~all of the work; keep the last few percent for the checking stage.
        reading = min(job.pages_done, job.pages_total) / job.pages_total
        return round(min(0.97, reading * 0.95 + (0.02 if job.stage is Stage.CHECKING else 0.0)), 3)

    def _position(self, job: Job) -> int | None:
        if job.status is not JobStatus.QUEUED:
            return None
        ahead = [j for j in self.jobs.values() if j.status is JobStatus.QUEUED and j.created < job.created]
        running = any(j.status is JobStatus.RUNNING for j in self.jobs.values())
        return len(ahead) + (1 if running else 0)

    def _eta(self, job: Job) -> int | None:
        if job.status in (JobStatus.DONE, JobStatus.FAILED):
            return None
        per_page = self._per_page()
        if job.status is JobStatus.RUNNING and job.started and job.pages_done:
            per_page = (time.time() - job.started) / job.pages_done  # this job's own pace
        remaining = max(0, job.pages_total - job.pages_done) * per_page + CHECKING_SECONDS
        if job.status is JobStatus.QUEUED:
            for other in self.jobs.values():
                if other is job:
                    continue
                if other.status is JobStatus.RUNNING or (other.status is JobStatus.QUEUED and other.created < job.created):
                    remaining += max(0, other.pages_total - other.pages_done) * self._per_page() + CHECKING_SECONDS
        return int(round(remaining))

    # -- worker ---------------------------------------------------------------------------

    async def _work(self, app) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                continue  # cancelled while waiting
            await self._run(job, app)

    async def _run(self, job: Job, app) -> None:
        def page_done(_stat) -> None:
            if job.cancelled:
                raise JobCancelled()
            job.pages_done += 1

        def reading_done(_reading) -> None:
            if job.cancelled:
                raise JobCancelled()
            job.stage = Stage.CHECKING

        try:
            async with self.case_lock:
                if job.cancelled:
                    return
                # Only now is the job really running: it holds the reader.
                job.status, job.stage, job.started = JobStatus.RUNNING, Stage.READING, time.time()
                result = await run_case(
                    job.folder,
                    case_id=job.case_id,
                    evaluation_date=job.evaluation_date,
                    reader=app.state.reader,
                    online=job.online,
                    fetch=app.state.fetch,
                    progress=page_done,
                    on_reading=reading_done,
                )
            job.result = build_response(result, job.files)
            job.status = JobStatus.DONE
            ocr = result.seconds.get("ocr")
            if ocr and job.pages_done:
                pace = ocr / job.pages_done
                self.seconds_per_page = pace if self.seconds_per_page is None else 0.7 * self.seconds_per_page + 0.3 * pace
        except JobCancelled:
            log.info("job cancelled while running")
            job.status, job.error = JobStatus.FAILED, "cancelled"
        except Exception as e:  # noqa: BLE001  (log the type only: messages could quote document content)
            log.error("job failed: %s", type(e).__name__)
            job.status, job.error = JobStatus.FAILED, f"verification failed ({type(e).__name__})"
        finally:
            job.stage, job.finished = Stage.FINISHED, time.time()
            shutil.rmtree(job.folder, ignore_errors=True)
            job.ended.set()
