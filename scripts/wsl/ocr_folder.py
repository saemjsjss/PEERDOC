"""OCR every PDF/image in a folder with PaddleOCR-VL-1.6 and save one result per page.

Pass 1 exploration tool: it only reads; it does not classify. Output stays local:

    <out>/<file stem>/page_<n>.json   full PaddleOCR-VL result for that page
    <out>/<file stem>/page_<n>.md     the page as Markdown
    <out>/summary.jsonl               one line per page: timing, block labels, text length

Run inside the OCR venv in WSL:
    LD_LIBRARY_PATH=/usr/lib/wsl/lib python /mnt/c/dcSS/scripts/wsl/ocr_folder.py \
        "/mnt/c/dcSS/SAMPLE DOC" /mnt/c/dcSS/ocr_output/sample_doc
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def main(src: Path, out: Path) -> int:
    import paddle
    from paddleocr import PaddleOCRVL

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from hklv_ocr import paddle_wsl_fix

    paddle_wsl_fix.apply()
    out.mkdir(parents=True, exist_ok=True)
    pipeline = PaddleOCRVL(pipeline_version="v1.6", device="gpu:0")
    paddle.device.cuda.empty_cache()

    files = sorted(p for p in src.iterdir() if p.suffix.lower() in SUFFIXES)
    print(f"{len(files)} files in {src}", flush=True)
    failures = 0
    with open(out / "summary.jsonl", "w", encoding="utf-8") as summary:
        for f in files:
            doc_dir = out / f.stem
            doc_dir.mkdir(exist_ok=True)
            t_file = time.perf_counter()
            try:
                t = time.perf_counter()
                for page_no, res in enumerate(pipeline.predict(str(f)), start=1):
                    dt = time.perf_counter() - t
                    data = res.json
                    payload = data.get("res", data)
                    (doc_dir / f"page_{page_no}.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
                    )
                    md = res.markdown.get("markdown_texts", "") if hasattr(res, "markdown") else ""
                    (doc_dir / f"page_{page_no}.md").write_text(md or "", encoding="utf-8")
                    blocks = payload.get("parsing_res_list", [])
                    row = {
                        "file": f.name,
                        "page": page_no,
                        "seconds": round(dt, 1),
                        "blocks": len(blocks),
                        "labels": [b.get("block_label") for b in blocks],
                        "chars": sum(len(str(b.get("block_content", ""))) for b in blocks),
                    }
                    summary.write(json.dumps(row, ensure_ascii=False) + "\n")
                    summary.flush()
                    print(f"{f.name} p{page_no}: {dt:.1f}s, {row['blocks']} blocks, {row['chars']} chars", flush=True)
                    t = time.perf_counter()
            except Exception:  # noqa: BLE001  (log it and go on with the next file)
                failures += 1
                print(f"FAILED {f.name}:\n{traceback.format_exc()}", flush=True)
                summary.write(json.dumps({"file": f.name, "error": traceback.format_exc()[-500:]}) + "\n")
            print(f"  {f.name} total {time.perf_counter() - t_file:.1f}s", flush=True)
    print(f"DONE: {len(files)} files, {failures} failed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
