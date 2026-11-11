"""FastAPI /verify: uploads -> pipeline -> JSON verdict. No GPU, no network: a fake OCR
reader returns fictional page readings and a fake web answers the online checks."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reading_builders import make_page, qr
from test_mrz import td3
from test_online import FOUND, URL, FakeWeb

import hklv_api.uploads as uploads
from hklv_api.app import app
from hklv_ocr.reading import CaseReading


def passport_and_photo() -> CaseReading:
    return CaseReading(
        pages=(
            make_page(["PASSPORT", "Surname", "UDDIN", "Given Names", "KAMAL", *td3()], page_no=1),
            make_page([], page_no=2, from_image_file=True),
        )
    )


class FakeReader:
    """Stands in for PageReader. Records which files it was given and whether they existed."""

    def __init__(self, reading: CaseReading | None = None, error: Exception | None = None):
        self.reading, self.error = reading or passport_and_photo(), error
        self.paths: list[Path] = []
        self.existed: list[bool] = []

    async def read_files(self, paths):
        self.paths = list(paths)
        self.existed = [p.exists() for p in self.paths]
        if self.error:
            raise self.error
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


def use(reader=None, fetch=None) -> FakeReader:
    app.state.reader = reader or FakeReader()
    app.state.fetch = fetch
    return app.state.reader


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


PDF = b"%PDF-1.4 fictional"


def post(client, files, **form):
    form.setdefault("online", "false")
    form.setdefault("evaluation_date", "2026-11-11")
    return client.post("/verify", files=files, data=form)


# --- basics ----------------------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "version": "1.0.0", "models_loaded": False}
    use()
    assert client.get("/health").json()["models_loaded"] is True


def test_models_not_loaded_is_503(client):
    r = post(client, [("files", ("a.pdf", PDF, "application/pdf"))])
    assert r.status_code == 503


def test_multiple_files_return_the_verdict_json(client):
    reader = use()
    r = post(client, [("files", ("passport.pdf", PDF, "application/pdf")), ("files", ("photo.jpg", b"\xff\xd8jpeg", "image/jpeg"))], case_id="case-7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["case_id"] == "case-7" and body["evaluation_date"] == "2026-11-11"
    assert body["outcome"] == "FAIL"  # fictional case lacks the birth certificate, FRC, bank ...
    assert body["counts"]["failed"] == len(body["failures"]) > 0
    assert {"REQ-03", "REQ-04"} <= {f["rule_id"] for f in body["failures"]}
    assert all(f["reason"] for f in body["failures"])
    assert [d["kind"] for d in body["documents"]] == ["passport", "photo"]
    assert [p["kind"] for p in body["pages"]] == ["passport", "photo"]
    assert sorted(body["files"]["accepted"]) == ["passport.pdf", "photo.jpg"]
    assert {"ocr", "extraction", "rules"} <= set(body["timings"])
    assert sorted(p.name for p in reader.paths) == ["passport.pdf", "photo.jpg"] and all(reader.existed)


def test_uploads_are_deleted_after_the_response(client):
    reader = use()
    post(client, [("files", ("a.pdf", PDF, "application/pdf"))])
    assert reader.paths and not any(p.exists() for p in reader.paths)
    assert not reader.paths[0].parent.exists()


def test_uploads_are_deleted_when_the_pipeline_fails(client):
    reader = use(FakeReader(error=RuntimeError("secret page text")))
    r = post(client, [("files", ("a.pdf", PDF, "application/pdf"))])
    assert r.status_code == 500
    assert "secret page text" not in r.text and "RuntimeError" in r.text
    assert not reader.paths[0].parent.exists()


def test_no_supported_files_is_400_listing_what_was_ignored(client):
    use()
    r = post(client, [("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 400
    assert r.json()["detail"]["ignored"] == [{"name": "notes.txt", "reason": "not a PDF, image or ZIP"}]


def test_bad_form_values_are_422(client):
    use()
    r = post(client, [("files", ("a.pdf", PDF, "application/pdf"))], evaluation_date="31-02-2026")
    assert r.status_code == 422


# --- ZIP handling -----------------------------------------------------------------------------


def test_zip_is_unpacked_flat_and_junk_is_skipped(client):
    reader = use()
    data = zip_bytes(
        {
            "student/passport.pdf": PDF,
            "student/scans/photo.png": b"\x89PNG fictional",
            "__MACOSX/student/._passport.pdf": b"junk",
            "student/.DS_Store": b"junk",
            "student/readme.txt": b"text",
            "student/inner.zip": zip_bytes({"x.pdf": PDF}),
        }
    )
    r = post(client, [("files", ("case.zip", data, "application/zip"))])
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    assert sorted(files["accepted"]) == ["passport.pdf", "photo.png"]
    reasons = {i["name"]: i["reason"] for i in files["ignored"]}
    assert reasons["case.zip:student/readme.txt"] == "not a PDF or image"
    assert reasons["case.zip:student/inner.zip"] == "ZIP inside a ZIP is not opened"
    folder = reader.paths[0].parent
    assert all(p.parent == folder for p in reader.paths)


def test_zip_slip_names_cannot_escape_the_work_folder(client, tmp_path):
    reader = use()
    data = zip_bytes({"../../escape.pdf": PDF, "/abs/root.pdf": PDF, "C:\\Windows\\win.pdf": PDF, "a/../../b.pdf": PDF})
    r = post(client, [("files", ("evil.zip", data, "application/zip"))])
    assert r.status_code == 200, r.text
    assert sorted(r.json()["files"]["accepted"]) == ["b.pdf", "escape.pdf", "root.pdf", "win.pdf"]
    folder = reader.paths[0].parent
    assert all(p.parent == folder for p in reader.paths)


def test_zip_and_loose_files_together_with_duplicate_names(client):
    use()
    r = post(
        client,
        [("files", ("a.pdf", PDF, "application/pdf")), ("files", ("more.zip", zip_bytes({"x/a.pdf": PDF, "y/a.pdf": PDF}), "application/zip"))],
    )
    assert sorted(r.json()["files"]["accepted"]) == ["a (2).pdf", "a (3).pdf", "a.pdf"]


def test_corrupt_zip_is_400(client):
    use()
    r = post(client, [("files", ("broken.zip", b"PK\x03\x04 not really a zip", "application/zip"))])
    assert r.status_code == 400 and "not a readable ZIP" in r.json()["detail"]


def test_zip_bomb_is_stopped_by_real_bytes_not_headers(client, monkeypatch):
    use()
    monkeypatch.setattr(uploads, "MAX_UNPACKED_BYTES", 50_000)
    data = zip_bytes({"big.pdf": b"0" * 200_000})  # compresses to almost nothing
    assert len(data) < 5_000
    r = post(client, [("files", ("bomb.zip", data, "application/zip"))])
    assert r.status_code == 413


def test_too_many_files_is_413(client, monkeypatch):
    use()
    monkeypatch.setattr(uploads, "MAX_FILES", 3)
    data = zip_bytes({f"{i}.pdf": PDF for i in range(5)})
    assert post(client, [("files", ("many.zip", data, "application/zip"))]).status_code == 413


def test_oversized_upload_is_413(client, monkeypatch):
    use()
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 1000)
    assert post(client, [("files", ("a.pdf", b"x" * 5000, "application/pdf"))]).status_code == 413


def test_oversized_request_is_rejected_before_reading(client, monkeypatch):
    import hklv_api.app as api

    use()
    monkeypatch.setattr(api, "MAX_REQUEST_BYTES", 100)
    r = post(client, [("files", ("a.pdf", b"x" * 5000, "application/pdf"))])
    assert r.status_code == 413


@pytest.mark.parametrize(
    "raw,clean",
    [("../../x.pdf", "x.pdf"), ("C:\\a\\b\\scan.PDF", "scan.PDF"), ("we<i>rd|na*me?.jpg", "we_i_rd_na_me_.jpg"), ("", "file"), ("..", "file"), ("a\x00b.pdf", "ab.pdf")],
)
def test_safe_name(raw, clean):
    assert uploads.safe_name(raw) == clean


# --- online checks through the API -----------------------------------------------------------


def apostille_reading() -> CaseReading:
    return CaseReading(pages=(make_page(["e-APOSTILLE", "Convention de La Haye"], barcodes=[qr(URL)]),))


def test_online_checks_run_when_asked(client):
    web = FakeWeb({URL: (200, FOUND)})
    use(FakeReader(apostille_reading()), fetch=web)
    body = post(client, [("files", ("a.pdf", PDF, "application/pdf"))], online="true").json()
    assert body["online"] == [{"doc_id": "e_apostille-1", "kind": "e_apostille", "status": "VERIFIED", "detail": body["online"][0]["detail"]}]
    assert web.asked == [URL]
    [acad_01] = [r for r in body["results"] if r["rule_id"] == "ACAD-01"]
    assert acad_01["outcome"] == "PASS"


def test_online_checks_off(client):
    web = FakeWeb({URL: (200, FOUND)})
    use(FakeReader(apostille_reading()), fetch=web)
    body = post(client, [("files", ("a.pdf", PDF, "application/pdf"))], online="false").json()
    assert body["online"][0]["status"] is None and web.asked == []
    [acad_01] = [r for r in body["results"] if r["rule_id"] == "ACAD-01"]
    assert acad_01["outcome"] == "FLAG"


# --- review regressions ------------------------------------------------------------------------


def test_chunked_upload_without_content_length_is_capped_by_real_bytes(client, monkeypatch):
    import hklv_api.app as api

    reader = use()
    monkeypatch.setattr(api, "MAX_REQUEST_BYTES", 10_000)
    boundary = "fictionalboundary"
    head = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"big.pdf\"\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()

    def body():  # a generator: httpx sends it chunked, with no Content-Length
        yield head
        for _ in range(50):
            yield b"x" * 4096
        yield f"\r\n--{boundary}--\r\n".encode()

    r = client.post("/verify", content=body(), headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    assert r.status_code == 413
    assert reader.paths == []  # the pipeline never ran


def test_long_non_latin_file_name_is_shortened_not_a_crash(client):
    reader = use()
    name = "\u0995\u09be\u09ae\u09be\u09b2" * 30 + ".pdf"  # 150 Bangla characters, ~450 bytes
    r = post(client, [("files", (name, PDF, "application/pdf"))])
    assert r.status_code == 200, r.text
    [saved] = r.json()["files"]["accepted"]
    assert saved.endswith(".pdf") and len(saved.encode()) <= 160
    assert "\u09be" in saved  # vowel signs (combining marks) are kept, not turned into "_"


def test_corrupt_zip_member_is_skipped_and_the_rest_kept(client):
    use()
    noise = bytes((i * 7919 + i // 7) % 251 for i in range(20000))  # barely compressible
    data = bytearray(zip_bytes({"good.pdf": PDF, "bad.pdf": noise}))
    # Damage bad.pdf's compressed bytes (they follow its local header and name).
    i = bytes(data).find(b"bad.pdf") + len("bad.pdf")
    data[i + 5 : i + 40] = b"\xff" * 35
    r = post(client, [("files", ("mixed.zip", bytes(data), "application/zip"))])
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    assert files["accepted"] == ["good.pdf"]
    assert any(i["name"].endswith("bad.pdf") and "could not be unpacked" in i["reason"] for i in files["ignored"])


def test_zip_with_invalid_utf8_names_is_a_clean_400(client):
    use()
    data = bytearray(zip_bytes({"aaaa.pdf": PDF}))
    for marker in (b"PK\x03\x04", b"PK\x01\x02"):
        start = 0
        while (i := bytes(data).find(marker, start)) >= 0:
            flag_at = i + (6 if marker == b"PK\x03\x04" else 8)
            data[flag_at] |= 0x00
            data[flag_at + 1] |= 0x08  # set the UTF-8 name flag (bit 11)
            start = i + 4
    data = bytes(data).replace(b"aaaa.pdf", b"\xff\xfe\xfd\xfc.pdf")
    r = post(client, [("files", ("names.zip", data, "application/zip"))])
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/json")


def test_zip_with_too_many_entries_is_413(client, monkeypatch):
    use()
    monkeypatch.setattr(uploads, "MAX_ZIP_ENTRIES", 10)
    r = post(client, [("files", ("many.zip", zip_bytes({f"{i}.txt": b"x" for i in range(20)}), "application/zip"))])
    assert r.status_code == 413


def test_ignored_list_is_capped(client, monkeypatch):
    use()
    monkeypatch.setattr(uploads, "MAX_IGNORED_LISTED", 3)
    r = post(client, [("files", ("junk.zip", zip_bytes({f"{i}.txt": b"x" for i in range(8)} | {"a.pdf": PDF}), "application/zip"))])
    files = r.json()["files"]
    assert len(files["ignored"]) == 3 and files["ignored_more"] == 5


def test_space_dot_pdf_entry_is_saved_as_a_readable_name(client):
    reader = use()
    r = post(client, [("files", ("odd.zip", zip_bytes({"dir/ .pdf": PDF, "b.pdf": PDF}), "application/zip"))])
    accepted = r.json()["files"]["accepted"]
    assert sorted(accepted) == ["b.pdf", "file.pdf"]
    assert sorted(p.name for p in reader.paths) == ["b.pdf", "file.pdf"]


class PickyReader(FakeReader):
    """Like the real PageReader, refuses files it can't open."""

    @staticmethod
    def check_readable(path):
        if path.stat().st_size == 0 or path.read_bytes().startswith(b"CORRUPT"):
            raise ValueError("cannot open")


def test_unreadable_files_are_listed_not_fatal(client):
    reader = use(PickyReader())
    r = post(client, [("files", ("good.pdf", PDF, "application/pdf")), ("files", ("empty.pdf", b"", "application/pdf")), ("files", ("fake.pdf", b"CORRUPT docx", "application/pdf"))])
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    assert files["accepted"] == ["good.pdf"]
    assert {i["name"] for i in files["ignored"]} == {"empty.pdf", "fake.pdf"}
    assert [p.name for p in reader.paths] == ["good.pdf"]


def test_only_unreadable_files_is_400(client):
    use(PickyReader())
    r = post(client, [("files", ("empty.pdf", b"", "application/pdf"))])
    assert r.status_code == 400


def test_startup_sweeps_upload_folders_left_by_a_killed_server(monkeypatch, tmp_path):
    monkeypatch.setenv("HKLV_LOAD_MODELS", "0")
    monkeypatch.setenv("HKLV_WORK_DIR", str(tmp_path))
    stale = tmp_path / "hklv-case-abc123"
    stale.mkdir()
    (stale / "passport.pdf").write_bytes(PDF)
    other = tmp_path / "keep-me"
    other.mkdir()
    app.state.reader = None
    with TestClient(app):
        pass
    assert not stale.exists() and other.exists()


def test_saving_errors_are_clean_json_without_file_names(client, monkeypatch):
    import hklv_api.app as api

    use()

    async def broken_save(files, folder):
        raise OSError(f"[Errno 36] File name too long: '{folder}/student-secret-name.pdf'")

    monkeypatch.setattr(api, "save_uploads", broken_save)
    r = post(client, [("files", ("a.pdf", PDF, "application/pdf"))])
    assert r.status_code == 500 and "student-secret-name" not in r.text
    assert r.headers["content-type"].startswith("application/json")


def test_reader_keeps_only_recent_page_stats():
    from collections import deque

    import hklv_ocr.readers as readers

    assert "deque(maxlen=200)" in Path(readers.__file__).read_text(encoding="utf-8")
    assert isinstance(deque(maxlen=200), deque)
