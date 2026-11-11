"""Master pipeline: folder -> (OCR) -> extraction -> rules -> verdict. Fictional data, no GPU."""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import pytest
from reading_builders import make_page
from test_mrz import td3

from hklv_ocr.reading import CaseReading
from hklv_pipeline import evaluate_reading, format_verdict, list_case_files, run_case, to_local_path
from hklv_rules.models.verdict import Outcome

TODAY = date(2026, 11, 11)


def passport_and_photo() -> CaseReading:
    return CaseReading(
        pages=(
            make_page(["PASSPORT", "Surname", "UDDIN", "Given Names", "KAMAL", *td3()], page_no=1),
            make_page([], page_no=2, from_image_file=True),
        )
    )


class FakeReader:
    """Stands in for PageReader: records what it was asked to read."""

    def __init__(self, reading: CaseReading):
        self.reading, self.asked = reading, None

    async def read_files(self, paths):
        self.asked = list(paths)
        return self.reading


@pytest.fixture
def upload_folder(tmp_path: Path) -> Path:
    for name in ("b.pdf", "A.JPG", "notes.txt", ".hidden.pdf", "c.png"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.pdf").write_bytes(b"x")
    return tmp_path


def test_lists_only_top_level_pdfs_and_images_sorted(upload_folder):
    assert [p.name for p in list_case_files(upload_folder)] == ["A.JPG", "b.pdf", "c.png"]


def test_missing_folder_is_an_error(tmp_path):
    with pytest.raises(NotADirectoryError):
        list_case_files(tmp_path / "nope")


@pytest.mark.skipif(os.name != "posix", reason="Windows paths are only translated inside WSL")
def test_windows_path_becomes_wsl_mount_path():
    assert to_local_path(r"C:\dcSS\SAMPLE DOC") == Path("/mnt/c/dcSS/SAMPLE DOC")


def test_non_windows_paths_are_left_alone():
    assert to_local_path("relative/folder") == Path("relative/folder")


def test_run_case_reads_the_folder_then_extracts_and_judges(upload_folder):
    reader = FakeReader(passport_and_photo())
    saved = []
    result = asyncio.run(
        run_case(upload_folder, case_id="fictional", evaluation_date=TODAY, reader=reader, on_reading=saved.append)
    )
    assert [p.name for p in reader.asked] == ["A.JPG", "b.pdf", "c.png"]
    assert saved == [reader.reading]
    assert [d.kind for d in result.case.documents] == ["passport", "photo"]
    assert result.verdict.outcome is Outcome.FAIL  # birth certificate, FRC, bank... missing
    assert {"ocr", "extraction", "rules"} <= set(result.seconds)


def test_run_case_with_empty_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(run_case(tmp_path, case_id="x", evaluation_date=TODAY, reader=FakeReader(CaseReading())))


def test_report_shows_verdict_and_every_failure_reason():
    result = evaluate_reading(passport_and_photo(), case_id="fictional", evaluation_date=TODAY)
    text = format_verdict(result)
    assert "FINAL OVERALL VERDICT: FAIL" in text
    for r in result.verdict.failures:
        assert r.rule_id in text
        # Reasons are wrapped, so compare word sequences.
        assert " ".join(r.reason.split()) in " ".join(text.split())
    assert "p1" in text and "passport" in text
    assert "p1 " not in format_verdict(result, show_pages=False)


def _cli():
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_case_cli", Path(__file__).parents[1] / "scripts" / "run_case.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


@pytest.fixture
def saved_reading(tmp_path) -> Path:
    path = tmp_path / "reading.json"
    path.write_text(passport_and_photo().model_dump_json(), encoding="utf-8")
    return path


def test_cli_rejudges_a_saved_reading_and_exits_with_the_verdict(tmp_path, saved_reading, capsys):
    out = tmp_path / "out"
    code = _cli().main([str(tmp_path), "--reading", str(saved_reading), "--date", "2026-11-11", "--out", str(out)])
    assert code == 2  # FAIL
    assert "FINAL OVERALL VERDICT: FAIL" in capsys.readouterr().out
    assert json.loads((out / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "FAIL"
    assert json.loads((out / "case.json").read_text(encoding="utf-8"))["case"]["case_id"] == tmp_path.name


def test_cli_removes_the_previous_runs_results_before_starting(tmp_path, saved_reading):
    out = tmp_path / "out"
    out.mkdir()
    (out / "verdict.json").write_text('{"outcome": "PASS"}', encoding="utf-8")  # stale, from an old run
    bad = tmp_path / "broken.json"
    bad.write_text("not a reading", encoding="utf-8")
    assert _cli().main([str(tmp_path), "--reading", str(bad), "--out", str(out)]) == 3
    assert not (out / "verdict.json").exists()


def test_cli_keeps_the_reading_it_is_rejudging(tmp_path, saved_reading):
    # Re-judging ocr_output/x/reading.json into ocr_output/x must not delete it first.
    assert _cli().main([str(tmp_path), "--reading", str(saved_reading), "--out", str(tmp_path), "--date", "2026-11-11"]) == 2
    assert saved_reading.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["folder", "--date", "2026-13-01"],  # impossible date
        ["folder", "--no-such-option"],
        [],  # folder missing
    ],
)
def test_bad_arguments_exit_3_not_2_which_means_fail(argv, capsys):
    with pytest.raises(SystemExit) as e:
        _cli().main(argv)
    assert e.value.code == 3


def test_a_crash_exits_3_not_1_which_means_flag(tmp_path, capsys):
    bad = tmp_path / "broken.json"
    bad.write_text('{"pages": [{"page_no": "SECRET-NAME"}]}', encoding="utf-8")
    assert _cli().main([str(tmp_path), "--reading", str(bad), "--out", str(tmp_path / "out")]) == 3
    err = capsys.readouterr().err
    assert "ValidationError" in err and "SECRET-NAME" not in err  # no document content in errors


def test_cli_missing_folder_exits_3(tmp_path, monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "paddle", types.ModuleType("paddle"))  # pretend we're in the OCR env
    assert _cli().main([str(tmp_path / "missing"), "--out", str(tmp_path / "out")]) == 3


def test_ocr_without_the_ocr_environment_is_an_error_not_a_crash(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setitem(sys.modules, "paddle", None)  # import paddle -> ImportError
    assert _cli().main([str(tmp_path), "--out", str(tmp_path / "out")]) == 3
    assert "WSL" in capsys.readouterr().err


def test_relative_paths_are_relative_to_where_the_user_ran_the_command(tmp_path, saved_reading, monkeypatch):
    # The WSL launcher cd's into the OCR folder and passes the user's folder in HKLV_CALLER_CWD.
    elsewhere = tmp_path / "ocr_home"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("HKLV_CALLER_CWD", str(tmp_path))
    assert _cli().main([".", "--reading", "reading.json", "--out", "results", "--case-id", "c", "--date", "2026-11-11"]) == 2
    assert (tmp_path / "results" / "verdict.json").exists()
    assert not (elsewhere / "results").exists()


def test_case_id_comes_from_the_resolved_folder_name(tmp_path, saved_reading, monkeypatch):
    monkeypatch.setenv("HKLV_CALLER_CWD", str(tmp_path))
    out = tmp_path / "out"
    assert _cli().main([".", "--reading", str(saved_reading), "--out", str(out), "--date", "2026-11-11"]) == 2
    assert json.loads((out / "case.json").read_text(encoding="utf-8"))["case"]["case_id"] == tmp_path.name


def test_reading_is_handed_over_before_extraction_runs(upload_folder, monkeypatch):
    import hklv_pipeline.pipeline as pl

    events = []

    def exploding_build_case(*a, **k):
        events.append("extraction")
        raise RuntimeError("extraction bug")

    monkeypatch.setattr(pl, "build_case", exploding_build_case)
    with pytest.raises(RuntimeError):
        asyncio.run(
            run_case(upload_folder, case_id="x", evaluation_date=TODAY, reader=FakeReader(passport_and_photo()), on_reading=lambda r: events.append("saved"))
        )
    assert events == ["saved", "extraction"]  # the OCR result was already saved when extraction crashed


@pytest.mark.skipif(os.name != "posix", reason="Windows paths are only translated inside WSL")
def test_relative_windows_path_uses_forward_slashes_in_wsl():
    assert to_local_path(r"ocr_output\x") == Path("ocr_output/x")
