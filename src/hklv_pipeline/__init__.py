"""Master pipeline: a folder of uploaded files -> OCR -> extraction -> rules -> verdict."""

from .pipeline import (
    PipelineResult,
    evaluate_reading,
    format_verdict,
    list_case_files,
    run_case,
    to_local_path,
)

__all__ = ["PipelineResult", "evaluate_reading", "format_verdict", "list_case_files", "run_case", "to_local_path"]
