"""Master pipeline CLI: judge one student's folder of documents.

From Windows (runs inside the WSL OCR environment):

    scripts\\run_case.cmd "C:\\dcSS\\SAMPLE DOC"
    (or, if PowerShell scripts are allowed: .\\scripts\\run_case.ps1 "C:\\dcSS\\SAMPLE DOC")

Inside WSL directly:

    bash /mnt/c/dcSS/scripts/wsl/run_case.sh "/mnt/c/dcSS/SAMPLE DOC"

Re-judge a saved reading without OCR (works on Windows too):

    .venv\\Scripts\\python.exe scripts\\run_case.py "C:\\dcSS\\SAMPLE DOC" --reading ocr_output\\sample_doc\\reading.json

Outputs (real personal data; default location is the git-ignored ocr_output/):
reading.json (raw OCR, saved as soon as OCR finishes), case.json (extracted documents),
verdict.json (every rule result).

Exit code: 0 PASS, 1 FLAG, 2 FAIL, 3 error (including bad arguments and crashes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hklv_ocr.reading import CaseReading  # noqa: E402
from hklv_pipeline import evaluate_reading, format_verdict, run_case, to_local_path  # noqa: E402
from hklv_rules.models.verdict import Outcome  # noqa: E402

EXIT = {Outcome.PASS: 0, Outcome.FLAG: 1, Outcome.FAIL: 2}
EXIT_ERROR = 3
OUTPUTS = ("reading.json", "case.json", "verdict.json")


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on bad input, which would read as FAIL; use the error code."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"{self.prog}: error: {message}\n")


class _UsageError(Exception):
    pass


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "case"


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _path(arg: str) -> Path:
    """Windows or POSIX path -> absolute local path.

    Relative paths are relative to where the user ran the command: the WSL launcher moves
    into the OCR environment's folder and passes the original folder in HKLV_CALLER_CWD.
    """
    p = to_local_path(arg)
    if not p.is_absolute():
        p = Path(os.environ.get("HKLV_CALLER_CWD") or os.getcwd()) / p
    return p.resolve()


def _describe(e: Exception) -> str:
    """Error text without document content: validation errors can echo the input."""
    if type(e).__name__ == "ValidationError" and hasattr(e, "error_count"):
        return f"{type(e).__name__}: {e.error_count()} problem(s) in the saved reading (not a reading.json?)"
    return f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    ap = _Parser(description="OCR + extraction + rules for one student's folder")
    ap.add_argument("folder", help="Folder with the student's PDFs/images (Windows paths accepted in WSL)")
    ap.add_argument("--case-id", help="Default: the folder name")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="Evaluation date YYYY-MM-DD (default: today)")
    ap.add_argument("--out", help="Output folder (default: ocr_output/<folder name>)")
    ap.add_argument("--reading", help="Skip OCR: judge this saved reading.json instead")
    ap.add_argument("--no-pages", action="store_true", help="Don't print the page-by-page classification")
    args = ap.parse_args(argv)

    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return EXIT_ERROR
    except (_UsageError, FileNotFoundError, NotADirectoryError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as e:  # a crash must never look like a verdict (exit 1 = FLAG)
        print(f"Error: the pipeline crashed: {_describe(e)}", file=sys.stderr)
        return EXIT_ERROR


def _run(args) -> int:
    folder = _path(args.folder)
    case_id = (args.case_id or folder.name).strip()
    if not case_id:
        raise _UsageError(f"cannot derive a case id from {folder}; pass --case-id")
    evaluation_date = args.date or date.today()
    out = _path(args.out) if args.out else REPO / "ocr_output" / _slug(folder.name)
    reading_file = _path(args.reading) if args.reading else None
    if reading_file is None:
        try:
            import paddle  # noqa: F401
        except ImportError:
            raise _UsageError("OCR needs the WSL OCR environment: run scripts\\run_case.cmd, or pass --reading") from None
    print(f"Case '{case_id}', evaluation date {evaluation_date.isoformat()}, folder {folder}", flush=True)

    out.mkdir(parents=True, exist_ok=True)
    # Remove the previous run's results first, so a crash can't leave an old verdict next to
    # new data. The reading being re-judged is kept, of course.
    for name in OUTPUTS:
        old = out / name
        if old.exists() and old != reading_file:
            old.unlink()

    if reading_file is not None:
        reading = CaseReading.model_validate_json(reading_file.read_text(encoding="utf-8"))
        print(f"Using saved reading ({len(reading.pages)} pages); OCR skipped", flush=True)
        result = evaluate_reading(reading, case_id=case_id, evaluation_date=evaluation_date)
    else:

        def save_reading(reading: CaseReading) -> None:
            try:
                (out / "reading.json").write_text(reading.model_dump_json(indent=1), encoding="utf-8")
                print(f"OCR done: {len(reading.pages)} pages, saved {out / 'reading.json'}", flush=True)
            except OSError as e:  # don't throw away a long OCR run over a failed save
                print(f"Warning: OCR done but reading.json could not be saved ({e}); continuing", file=sys.stderr, flush=True)

        print("Loading OCR models and reading every page (several minutes)...", flush=True)
        result = asyncio.run(run_case(folder, case_id=case_id, evaluation_date=evaluation_date, on_reading=save_reading))

    print()
    print(format_verdict(result, show_pages=not args.no_pages))
    _write_json(out / "case.json", {"pages": result.report.model_dump(mode="json")["pages"], "case": result.case.model_dump(mode="json")})
    _write_json(out / "verdict.json", result.verdict.model_dump(mode="json"))
    print(f"\nSaved case.json and verdict.json in {out}")
    return EXIT[result.verdict.outcome]


if __name__ == "__main__":
    sys.exit(main())
