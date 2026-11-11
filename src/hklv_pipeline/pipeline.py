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
) -> PipelineResult:
    """Pass 1 extraction (+ online checks) + Pass 2/3 rules on an existing reading (no GPU).

    `online=True` checks e-Apostilles and automated challans on the official sites
    (blocking HTTP; `fetch` replaces the HTTP call in tests). Without it, ACAD-01 / TAX-04
    report "not verified online" (FLAG).
    """
    timings = dict(seconds or {})
    t = time.perf_counter()
    case, report = build_case(reading, case_id, evaluation_date)
    timings["extraction"] = time.perf_counter() - t
    if online:
        from hklv_online import apply_online_checks
        from hklv_online.checks import http_fetch

        t = time.perf_counter()
        case = apply_online_checks(case, fetch or http_fetch)
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
        reader = PageReader(progress=progress)
        timings["model_load"] = time.perf_counter() - t
    t = time.perf_counter()
    reading = await reader.read_files(files)
    timings["ocr"] = time.perf_counter() - t
    if on_reading is not None:
        on_reading(reading)
    # Online checks block on HTTP: keep them off the event loop.
    return await asyncio.to_thread(
        evaluate_reading,
        reading,
        case_id=case_id,
        evaluation_date=evaluation_date,
        threshold=threshold,
        seconds=timings,
        online=online,
        fetch=fetch,
    )


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
