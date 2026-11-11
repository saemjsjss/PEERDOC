"""Background jobs: POST /jobs -> poll GET /jobs/{id} -> verdict. No GPU, no network."""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from reading_builders import make_page, qr
from test_api import PDF, passport_and_photo
from test_online import FOUND, URL, FakeWeb

import hklv_api.jobs as jobs
from hklv_api.app import app
from hklv_ocr.reading import CaseReading


class GatedReader:
    """Fake PageReader: reports each page through `progress`, and can be held mid-run."""

    def __init__(self, reading: CaseReading | None = None, pages_per_file: int = 2, hold: bool = False, error: Exception | None = None):
        self.reading = reading or passport_and_photo()
        self.pages_per_file = pages_per_file
        self.gate = threading.Event()
        self.entered = threading.Event()
        if not hold:
            self.gate.set()
        self.error = error
        self.calls = 0
        self.paths = []

    def page_count(self, path):
        return self.pages_per_file

    async def read_files(self, paths, progress=None):
        self.calls += 1
        self.paths = list(paths)
        if progress:
            progress(object())  # first page read
        self.entered.set()
        await asyncio.to_thread(self.gate.wait, 10)
        if self.error:
            raise self.error
        if progress:
            for _ in range(len(self.reading.pages) - 1):
                progress(object())
        return self.reading


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HKLV_LOAD_MODELS", "0")
    app.state.reader = None
    app.state.fetch = None
    with TestClient(app) as c:
        yield c
    app.state.reader = None
    app.state.fetch = None


def submit(client, files=None, **form):
    form.setdefault("online", "false")
    form.setdefault("evaluation_date", "2026-11-11")
    files = files or [("files", ("passport.pdf", PDF, "application/pdf")), ("files", ("photo.jpg", b"\xff\xd8jpeg", "image/jpeg"))]
    return client.post("/jobs", files=files, data=form)


def wait_for(client, job_id, status, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/jobs/{job_id}").json()
        if body.get("status") == status:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job never reached {status}: {body}")


def test_submit_returns_202_and_the_job_finishes_with_the_verdict(client):
    app.state.reader = GatedReader()
    r = submit(client, case_id="case-9")
    assert r.status_code == 202, r.text
    job = r.json()
    assert len(job["job_id"]) >= 20  # unguessable token
    assert job["pages_total"] == 4  # 2 files x 2 pages (from the reader's page_count)
    assert job["files"]["accepted"] == ["passport.pdf", "photo.jpg"]
    done = wait_for(client, job["job_id"], "done")
    assert done["stage"] == "finished" and done["progress"] == 1.0 and done["eta_seconds"] is None
    result = done["result"]
    assert result["case_id"] == "case-9" and result["outcome"] == "FAIL"
    assert result["counts"]["failed"] == len(result["failures"]) > 0
    assert done["error"] is None and done["finished_at"] is not None


def test_progress_while_reading(client):
    reader = GatedReader(hold=True)
    app.state.reader = reader
    job_id = submit(client).json()["job_id"]
    assert reader.entered.wait(5)
    running = client.get(f"/jobs/{job_id}").json()
    assert running["status"] == "running" and running["stage"] == "reading"
    assert running["message"] == "Reading the documents"
    assert running["pages_done"] == 1 and 0 < running["progress"] < 1
    assert isinstance(running["eta_seconds"], int) and running["eta_seconds"] > 0
    assert running["result"] is None
    reader.gate.set()
    assert wait_for(client, job_id, "done")["pages_done"] == 2


def test_uploads_are_deleted_when_the_job_ends(client):
    reader = GatedReader()
    app.state.reader = reader
    job_id = submit(client).json()["job_id"]
    wait_for(client, job_id, "done")
    assert reader.paths and not reader.paths[0].parent.exists()


def test_second_job_waits_in_the_queue_and_can_be_cancelled(client):
    reader = GatedReader(hold=True)
    app.state.reader = reader
    first = submit(client).json()["job_id"]
    assert reader.entered.wait(5)
    second = submit(client).json()
    assert second["status"] == "queued" and second["queue_position"] == 1 and second["stage"] == "waiting"
    assert second["eta_seconds"] > 0
    assert client.delete(f"/jobs/{second['job_id']}").status_code == 204
    assert client.get(f"/jobs/{second['job_id']}").status_code == 404
    reader.gate.set()
    wait_for(client, first, "done")
    time.sleep(0.1)
    assert reader.calls == 1  # the cancelled job never ran


def test_a_running_job_cannot_be_deleted_but_a_finished_one_can(client):
    reader = GatedReader(hold=True)
    app.state.reader = reader
    job_id = submit(client).json()["job_id"]
    assert reader.entered.wait(5)
    assert client.delete(f"/jobs/{job_id}").status_code == 409
    reader.gate.set()
    wait_for(client, job_id, "done")
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_failed_job_reports_the_error_type_only(client):
    reader = GatedReader(error=RuntimeError("secret page text"))
    app.state.reader = reader
    job_id = submit(client).json()["job_id"]
    failed = wait_for(client, job_id, "failed")
    assert failed["error"] == "verification failed (RuntimeError)" and "secret" not in str(failed)
    assert failed["result"] is None
    assert not reader.paths[0].parent.exists()


def test_unknown_job_is_404(client):
    app.state.reader = GatedReader()
    assert client.get("/jobs/not-a-real-id").status_code == 404
    assert client.delete("/jobs/not-a-real-id").status_code == 204  # idempotent


def test_bad_upload_is_rejected_at_submission(client):
    app.state.reader = GatedReader()
    r = submit(client, files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 400


def test_models_not_loaded_is_503(client):
    assert submit(client).status_code == 503


def test_full_queue_is_503_and_leaves_no_files(client, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "MAX_WAITING_JOBS", 1)
    monkeypatch.setenv("HKLV_WORK_DIR", str(tmp_path))
    reader = GatedReader(hold=True)
    app.state.reader = reader
    submit(client)  # running
    assert reader.entered.wait(5)
    assert submit(client).status_code == 202  # waiting (1 of 1)
    r = submit(client)
    assert r.status_code == 503
    assert len(list(tmp_path.glob("hklv-case-*"))) == 2  # running + waiting; the rejected upload left nothing
    reader.gate.set()


def test_verdicts_expire(client, monkeypatch):
    monkeypatch.setattr(jobs, "KEEP_RESULT_SECONDS", 0)
    app.state.reader = GatedReader()
    job_id = submit(client).json()["job_id"]
    end = time.time() + 5
    while client.get(f"/jobs/{job_id}").status_code == 200 and time.time() < end:
        time.sleep(0.02)
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_online_checks_through_a_job(client):
    app.state.reader = GatedReader(CaseReading(pages=(make_page(["e-APOSTILLE", "Convention de La Haye"], barcodes=[qr(URL)]),)))
    app.state.fetch = FakeWeb({URL: (200, FOUND)})
    job_id = submit(client, online="true").json()["job_id"]
    result = wait_for(client, job_id, "done")["result"]
    assert result["online"][0]["status"] == "VERIFIED"


def test_stage_moves_to_checking_after_reading():
    manager = jobs.JobManager()
    job = jobs.Job(id="x", folder=None, files=jobs.SavedFiles(), case_id="c", evaluation_date=None, online=False, pages_total=10)
    job.status, job.stage, job.pages_done, job.started = jobs.JobStatus.RUNNING, jobs.Stage.CHECKING, 10, time.time() - 50
    assert 0.95 <= manager._progress(job) < 1.0
    assert manager._eta(job) == int(jobs.CHECKING_SECONDS)


# --- review regressions ------------------------------------------------------------------------


def test_client_gone_before_queueing_leaves_no_job_and_no_files(client, monkeypatch, tmp_path):
    from starlette.requests import Request

    async def gone(self):
        return True

    monkeypatch.setenv("HKLV_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(Request, "is_disconnected", gone)
    reader = GatedReader()
    app.state.reader = reader
    r = submit(client)
    assert r.status_code == 499
    assert app.state.jobs.jobs == {} and reader.calls == 0
    assert list(tmp_path.glob("hklv-case-*")) == []


def test_expired_verdicts_are_dropped_without_any_request(client, monkeypatch):
    monkeypatch.setattr(jobs, "KEEP_RESULT_SECONDS", 0)
    app.state.reader = GatedReader()
    job_id = submit(client).json()["job_id"]
    end = time.time() + 5
    while job_id in app.state.jobs.jobs and app.state.jobs.jobs[job_id].status is not jobs.JobStatus.DONE and time.time() < end:
        time.sleep(0.02)
    end = time.time() + 5  # the janitor runs every second here; no GET/POST meanwhile
    while job_id in app.state.jobs.jobs and time.time() < end:
        time.sleep(0.1)
    assert job_id not in app.state.jobs.jobs


def test_verify_waits_for_the_case_being_read(client):
    reader = GatedReader(hold=True)
    app.state.reader = reader
    job_id = submit(client).json()["job_id"]
    assert reader.entered.wait(5)
    results = {}

    def call_verify():
        results["r"] = client.post("/verify", files=[("files", ("a.pdf", PDF, "application/pdf"))], data={"online": "false"})

    t = threading.Thread(target=call_verify)
    t.start()
    time.sleep(0.5)
    assert reader.calls == 1  # /verify has not started reading while the job holds the GPU
    reader.gate.set()
    t.join(10)
    assert results["r"].status_code == 200 and reader.calls == 2
    wait_for(client, job_id, "done")
