"""Pass 1 extraction + Pass 2/3 rules on a saved reading.json; prints the verdict.

    .venv/Scripts/python.exe scripts/extract_case.py ocr_output/sample_doc/reading.json \
        --case-id sample --date 2026-11-11 --out ocr_output/sample_doc/case.json

Output files contain real personal data: keep them under the git-ignored ocr_output/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hklv_extract.build import build_case  # noqa: E402
from hklv_ocr.reading import CaseReading  # noqa: E402
from hklv_rules.engine import evaluate_case  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reading", type=Path)
    ap.add_argument("--case-id", default="case")
    ap.add_argument("--date", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    reading = CaseReading.model_validate_json(args.reading.read_text(encoding="utf-8"))
    case, report = build_case(reading, args.case_id, args.date)
    verdict = evaluate_case(case)
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "pages": report.model_dump(mode="json")["pages"],
                    "case": case.model_dump(mode="json"),
                    "verdict": verdict.model_dump(mode="json"),
                },
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    for p in report.pages:
        print(f"p{p.page_no:>2} {p.source_file[:28]:<28} {p.file_page:>2}  {p.kind.value:<22} {p.doc_id or '-':<24} {p.reason}")
    print()
    print(verdict.summary)
    for r in verdict.results:
        if r.outcome.value != "PASS":
            print(f"  {r.outcome.value:<4} {r.rule_id:<16} {r.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
