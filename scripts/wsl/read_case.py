"""Read every file in a folder with the three Pass 1 readers and save one reading.json.

The output contains real document text: write it only under the git-ignored ocr_output/.

    LD_LIBRARY_PATH=/usr/lib/wsl/lib ~/hklv-ocr/.venv/bin/python \
        /mnt/c/dcSS/scripts/wsl/read_case.py "/mnt/c/dcSS/SAMPLE DOC" /mnt/c/dcSS/ocr_output/sample_doc/reading.json
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hklv_ocr.readers import SUPPORTED_SUFFIXES, PageReader  # noqa: E402


async def main(src: Path, out: Path) -> int:
    files = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    t0 = time.perf_counter()
    reader = PageReader(progress=lambda stat: print("  " + stat.line(), flush=True))
    print(f"models loaded in {time.perf_counter() - t0:.1f}s; {len(files)} files", flush=True)
    pages = []
    for f in files:
        t = time.perf_counter()
        got = await reader.read_file(f, first_page_no=len(pages) + 1)
        pages.extend(got)
        print(f"{f.name}: {len(got)} page(s) in {time.perf_counter() - t:.1f}s", flush=True)
    from hklv_ocr.reading import CaseReading

    case = CaseReading(pages=tuple(pages), readers=reader.versions())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(case.model_dump_json(indent=1), encoding="utf-8")
    print(f"DONE: {len(pages)} pages in {time.perf_counter() - t0:.1f}s -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]))))
