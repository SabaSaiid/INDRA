"""Stable ML entry point with no database, Kafka, HTTP, or auth access."""

from __future__ import annotations

from app.ml.contracts import ReportInput, UnifiedMLResult
from app.ml.inference.engine import InferenceEngine


def analyze_report(
    report_input: ReportInput,
    *,
    engine: InferenceEngine | None = None,
) -> UnifiedMLResult:
    """Analyze already-loaded report data using local component interfaces."""

    return (engine or InferenceEngine()).analyze(report_input)
