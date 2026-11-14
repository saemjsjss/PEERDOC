"""Master pipeline: one student's folder in, one verdict out.

    Pass 1   OCR (three readers, GPU)         hklv_ocr.readers.PageReader
             classification + extraction      hklv_extract.build.build_case
             online checks (optional)         hklv_online.apply_online_checks (ACAD-01, TAX-04)
    Pass 2/3 anchors + Rulebook v2.5 rules    hklv_rules.engine.evaluate_case

`run_case` is async because OCR is (the future FastAPI service awaits it). Everything
after OCR is pure Python, so `evaluate_reading` can re-judge a saved reading without the
GPU, e.g. after a rule changes.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from hklv_extract.build import ExtractionReport, build_case
from hklv_ocr.reading import CaseReading
from hklv_ocr.readers import SUPPORTED_SUFFIXES
from hklv_rules.engine import evaluate_case
from hklv_rules.models.case import CaseFile
from hklv_rules.models.common import DEFAULT_CONFIDENCE_THRESHOLD
from hklv_rules.models.verdict import CaseVerdict, Outcome


@dataclass(frozen=True)
class PipelineResult:
    reading: CaseReading
    case: CaseFile
    report: ExtractionReport
    verdict: CaseVerdict
    seconds: dict[str, float] = field(default_factory=dict)


def to_local_path(path: str | Path) -> Path:
    """Accept Windows paths when running inside WSL.

    'C:\\dcSS\\SAMPLE DOC' -> /mnt/c/dcSS/SAMPLE DOC; a relative 'ocr_output\\x' ->
    ocr_output/x (a backslash is a path separator on Windows, never part of a name here).
    """
    text = str(path)
    if os.name != "posix":
        return Path(text)
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if m:
        return Path("/mnt") / m.group(1).lower() / m.group(2).replace("\\", "/")
    if not text.startswith("/"):
        return Path(text.replace("\\", "/"))
    return Path(text)


def list_case_files(folder: Path) -> list[Path]:
    """The uploads in `folder`: PDFs and images, not recursive, hidden files skipped.

    Sorted by name only so runs are reproducible; the name never decides what a document
    is (classification is content-based).
    """
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED_SUFFIXES),
        key=lambda p: p.name.lower(),
    )


def evaluate_reading(
    reading: CaseReading,
    *,
    case_id: str,
    evaluation_date: date,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    seconds: dict[str, float] | None = None,
    online: bool = False,
    fetch=None,
    post=None,
    get_bytes=None,
    read_register=None,
) -> PipelineResult:
    """Pass 1 extraction (+ online checks) + Pass 2/3 rules on an existing reading (no GPU).

    `online=True` checks e-Apostilles and automated challans on the official sites
    (blocking HTTP; `fetch` replaces the HTTP call in tests). Without it, ACAD-01 / TAX-04
    report "not verified online" (FLAG). RULES-v10: a found apostille's register copy is
    downloaded (`post`, `get_bytes`; the real ones unless `fetch` is replaced) and read by
    `read_register` (an OCR step; without one, ACAD-01 can't confirm the owner -> FLAG).
    """
    timings = dict(seconds or {})
    t = time.perf_counter()
    case, report = build_case(reading, case_id, evaluation_date)
    timings["extraction"] = time.perf_counter() - t
    if online:
        from hklv_online import apply_online_checks
        from hklv_online.checks import http_fetch, http_get_bytes, http_post_json

        if fetch is None:
            post, get_bytes = post or http_post_json, get_bytes or http_get_bytes
        t = time.perf_counter()
        case = apply_online_checks(
            case, fetch or http_fetch, post=post, get_bytes=get_bytes, read_register=read_register
        )
        timings["online"] = time.perf_counter() - t
    t = time.perf_counter()
    verdict = evaluate_case(case, threshold)
    timings["rules"] = time.perf_counter() - t
    return PipelineResult(reading=reading, case=case, report=report, verdict=verdict, seconds=timings)


async def run_case(
    folder: Path,
    *,
    case_id: str,
    evaluation_date: date,
    reader=None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    on_reading=None,
    progress=None,
    online: bool = False,
    fetch=None,
) -> PipelineResult:
    """OCR every upload in `folder`, extract the documents, run the rules.

    `reader` is a loaded `PageReader` (models take ~20 s to load; a service keeps one).
    `on_reading(reading)` is called as soon as OCR finishes, so a caller can save the
    expensive part before extraction runs. `progress(stat)` is called after every page
    with its time and memory (`hklv_ocr.readers.PageStat`).
    """
    files = list_case_files(folder)
    if not files:
        raise FileNotFoundError(f"No PDF or image files in {folder}")
    timings: dict[str, float] = {}
    if reader is None:
        from hklv_ocr.readers import PageReader  # needs Paddle: WSL OCR environment only

        t = time.perf_counter()
        reader = PageReader()
        timings["model_load"] = time.perf_counter() - t
    t = time.perf_counter()
    # Progress is passed per call: a shared reader (the API's) serves several jobs.
    reading = await (reader.read_files(files, progress=progress) if progress is not None else reader.read_files(files))
    timings["ocr"] = time.perf_counter() - t
    if on_reading is not None:
        on_reading(reading)
    # Online checks block on HTTP: keep them off the event loop.
    read_register = register_reader(reader, asyncio.get_running_loop()) if online else None
    return await asyncio.to_thread(
        evaluate_reading,
        reading,
        case_id=case_id,
        evaluation_date=evaluation_date,
        threshold=threshold,
        seconds=timings,
        online=online,
        fetch=fetch,
        read_register=read_register,
    )


REGISTER_OCR_SECONDS = 300  # all register pages of one apostille


def register_reader(reader, loop: asyncio.AbstractEventLoop):
    """RULES-v10: OCR the e-Apostille register's page images with the case's reader.

    Called from the online-check worker thread; the reader's coroutine runs on `loop`."""
    from hklv_extract.extractors import register_page

    def read(images: list[tuple[str, bytes]]):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # a worker thread, as it should be
        else:
            raise RuntimeError("register_reader must not run on the event loop thread")
        out = []
        deadline = time.monotonic() + REGISTER_OCR_SECONDS
        with tempfile.TemporaryDirectory(prefix="hklv-register-") as tmp:
            for i, (title, img) in enumerate(images):
                suffix = ".png" if img[1:4] == b"PNG" else ".jpg"  # PNG files start with 0x89 "PNG"
                path = Path(tmp) / f"register_{i}{suffix}"
                path.write_bytes(img)
                fut = asyncio.run_coroutine_threadsafe(reader.read_file(path), loop)
                # No cancel on timeout: it would free the GPU lock while the OCR thread runs on.
                pages = fut.result(timeout=max(deadline - time.monotonic(), 0))
                if pages:
                    out.append(register_page(pages[0], title))
        return tuple(out)

    return read


# --- report ------------------------------------------------------------------------------

_RULE = "=" * 78


def _wrap(text: str, indent: str, width: int = 78) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        if line and len(indent) + len(line) + 1 + len(w) > width:
            lines.append(indent + line)
            line = w
        else:
            line = f"{line} {w}" if line else w
    if line:
        lines.append(indent + line)
    return lines or [indent]


def format_verdict(result: PipelineResult, *, show_pages: bool = True) -> str:
    """Human-readable report: page map, documents found, then the verdict and its reasons."""
    out: list[str] = []
    if show_pages:
        out.append("Pages (classified by content; file names are shown only to locate them):")
        for p in result.report.pages:
            doc = p.doc_id or "ignored"
            out.append(f"  p{p.page_no:<3} {p.kind.value:<22} {doc:<24} {p.source_file} #{p.file_page}")
        out.append("")
    kinds: dict[str, int] = {}
    for d in result.case.documents:
        kinds[d.kind] = kinds.get(d.kind, 0) + 1
    out.append("Documents found: " + ", ".join(f"{k} x{n}" if n > 1 else k for k, n in kinds.items()))
    if result.seconds:
        out.append("Time: " + ", ".join(f"{k.replace('_', ' ')} {v:.1f}s" for k, v in result.seconds.items()))
    v = result.verdict
    out += ["", _RULE, f"  FINAL OVERALL VERDICT: {v.outcome.value}", _RULE, *_wrap(v.summary, "  "), ""]
    for title, items in (("FAILURES", v.failures), ("FLAGS (manual review)", v.flags)):
        if not items:
            continue
        out.append(f"{title}:")
        for r in items:
            first, *rest = _wrap(f"{r.rule_id}: {r.reason}", "    ")
            out.append("  - " + first.strip())
            out += [" " * 4 + x.strip() for x in rest]
        out.append("")
    passed = sum(1 for r in v.results if r.outcome is Outcome.PASS)
    out.append(f"{passed} check(s) passed, {len(v.flags)} flagged, {len(v.failures)} failed.")
    return "\n".join(out)
