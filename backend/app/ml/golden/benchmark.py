"""Local engineering-performance measurements for the unified ML engine.

The measurements in this module are regression observations only. They are not
production throughput, capacity, latency-SLO, or real-world validation claims.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.components.duplicate_features import load_feature_state
from app.ml.components.nlp_classifier import load_nlp_artifact
from app.ml.config import (
    DEFAULT_DUPLICATE_MATCHING_CONFIG,
    DEFAULT_NLP_CLASSIFIER_CONFIG,
    file_sha256,
)
from app.ml.contracts import ReportInput, UnifiedMLResult
from app.ml.inference.engine import InferenceEngine


BENCHMARK_COMPONENTS = (
    "nlp_classifier",
    "duplicate_matcher",
    "event_detector",
    "fake_detector",
    "image_analyzer",
    "anomaly_detector",
)
BENCHMARK_SCALES = (1, 10, 100)


class BenchmarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactLoadMeasurement(BenchmarkModel):
    artifact_name: str = Field(min_length=1)
    intended_component: Literal["nlp_classifier", "duplicate_matcher"]
    load_seconds: float = Field(ge=0.0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_authorized: Literal[True] = True
    structural_validation_passed: Literal[True] = True


class ScaleMeasurement(BenchmarkModel):
    report_count: Literal[1, 10, 100]
    result_count: int = Field(ge=1)
    total_inference_seconds: float = Field(ge=0.0)
    per_component_seconds: dict[str, float]
    semantic_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_scope: Literal["LOCAL_ENGINEERING_REGRESSION_ONLY"] = (
        "LOCAL_ENGINEERING_REGRESSION_ONLY"
    )
    production_throughput_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_measurement(self) -> "ScaleMeasurement":
        if self.result_count != self.report_count:
            raise ValueError("benchmark result count must equal report count")
        if tuple(self.per_component_seconds) != BENCHMARK_COMPONENTS:
            raise ValueError("benchmark component timing order is not stable")
        if any(value < 0.0 for value in self.per_component_seconds.values()):
            raise ValueError("component timings cannot be negative")
        return self


class ResourceObservations(BenchmarkModel):
    engine_instances: Literal[1] = 1
    component_instances: Literal[6] = 6
    nlp_artifact_identity_stable: bool
    duplicate_feature_state_identity_stable: bool
    engine_retains_report_results: Literal[False] = False


class GrossRegressionGuard(BenchmarkModel):
    """Portable ceiling for catching gross regressions, not an operational SLO."""

    policy: Literal["GROSS_LOCAL_REGRESSION_ONLY"] = "GROSS_LOCAL_REGRESSION_ONLY"
    total_time_multiplier: float = Field(default=20.0, ge=1.0)
    minimum_total_ceiling_seconds: float = Field(default=2.0, gt=0.0)
    component_time_multiplier: float = Field(default=50.0, ge=1.0)
    minimum_component_ceiling_seconds: float = Field(default=1.0, gt=0.0)
    artifact_time_multiplier: float = Field(default=50.0, ge=1.0)
    minimum_artifact_ceiling_seconds: float = Field(default=2.0, gt=0.0)
    production_slo: Literal[False] = False


class LocalPerformanceBenchmark(BenchmarkModel):
    benchmark_version: Literal["golden-performance-v1"] = "golden-performance-v1"
    schema_version: Literal["1.0"] = "1.0"
    recorded_at: datetime
    fixture_status: Literal["TEST_FIXTURE_ONLY"] = "TEST_FIXTURE_ONLY"
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"
    validation_scope: Literal["ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION"] = (
        "ENGINEERING_REGRESSION_NOT_PRODUCTION_VALIDATION"
    )
    timing_method: Literal["PERF_COUNTER_WALL_CLOCK"] = "PERF_COUNTER_WALL_CLOCK"
    runtime: dict[str, str]
    artifact_loads: list[ArtifactLoadMeasurement]
    measurements: list[ScaleMeasurement]
    resource_observations: ResourceObservations
    regression_guard: GrossRegressionGuard = Field(default_factory=GrossRegressionGuard)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_benchmark(self) -> "LocalPerformanceBenchmark":
        if self.recorded_at.tzinfo is None:
            raise ValueError("benchmark timestamp must include a timezone")
        if tuple(item.report_count for item in self.measurements) != BENCHMARK_SCALES:
            raise ValueError("benchmark must record 1, 10, and 100 reports in order")
        if {item.intended_component for item in self.artifact_loads} != {
            "nlp_classifier",
            "duplicate_matcher",
        }:
            raise ValueError("benchmark must time both governed local artifacts")
        return self


class _TimedPredictor:
    """Transparent predictor proxy used only to observe component wall time."""

    def __init__(
        self,
        target: Any,
        component_name: str,
        accumulator: dict[str, float],
    ) -> None:
        self.target = target
        self.component_name = component_name
        self.accumulator = accumulator

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return self.target.predict(*args, **kwargs)
        finally:
            self.accumulator[self.component_name] += perf_counter() - started

    def __getattr__(self, name: str) -> Any:
        return getattr(self.target, name)


def _synthetic_reports(count: int) -> list[ReportInput]:
    if count not in BENCHMARK_SCALES:
        raise ValueError("benchmark report count must be 1, 10, or 100")
    start = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
    return [
        ReportInput(
            report_id=UUID(int=12_000 + index),
            text=(
                "Synthetic engineering regression report: street water is "
                f"rising after rain, fixture {index:03d}"
            ),
            occurred_at=start + timedelta(minutes=index),
            latitude=25.5941 + (index % 5) * 0.0001,
            longitude=85.1376 + (index % 5) * 0.0001,
            source_type="TEST_FIXTURE",
            source_metadata={
                "fixture_status": "TEST_FIXTURE_ONLY",
                "data_origin": "SYNTHETIC",
                "validation_scope": "NOT_PRODUCTION_DATA",
            },
        )
        for index in range(count)
    ]


def _semantic_digest(results: list[UnifiedMLResult]) -> str:
    payload = [result.model_dump(mode="json") for result in results]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _measure_artifact_loads() -> list[ArtifactLoadMeasurement]:
    nlp_path = DEFAULT_NLP_CLASSIFIER_CONFIG.artifact_path
    started = perf_counter()
    load_nlp_artifact(nlp_path)
    nlp_seconds = perf_counter() - started

    duplicate_path = DEFAULT_DUPLICATE_MATCHING_CONFIG.feature_state_path
    started = perf_counter()
    load_feature_state(duplicate_path)
    duplicate_seconds = perf_counter() - started

    return [
        ArtifactLoadMeasurement(
            artifact_name=nlp_path.name,
            intended_component="nlp_classifier",
            load_seconds=nlp_seconds,
            sha256=file_sha256(nlp_path),
        ),
        ArtifactLoadMeasurement(
            artifact_name=duplicate_path.name,
            intended_component="duplicate_matcher",
            load_seconds=duplicate_seconds,
            sha256=file_sha256(duplicate_path),
        ),
    ]


def run_local_performance_benchmark(
    *,
    recorded_at: datetime | None = None,
) -> LocalPerformanceBenchmark:
    """Measure one local engine over synthetic 1/10/100-report batches."""

    artifact_loads = _measure_artifact_loads()
    engine = InferenceEngine()
    nlp_artifact = engine.nlp_classifier._load()
    if nlp_artifact is None:
        raise RuntimeError("manifest-authorized NLP artifact is unavailable")
    duplicate_state = engine.duplicate_matcher.feature_state
    if duplicate_state is None:
        raise RuntimeError("manifest-authorized duplicate feature state is unavailable")

    original_components = {
        component_name: getattr(engine, component_name)
        for component_name in BENCHMARK_COMPONENTS
    }
    accumulator = {component_name: 0.0 for component_name in BENCHMARK_COMPONENTS}
    for component_name, component in original_components.items():
        setattr(
            engine,
            component_name,
            _TimedPredictor(component, component_name, accumulator),
        )

    measurements: list[ScaleMeasurement] = []
    for count in BENCHMARK_SCALES:
        for component_name in BENCHMARK_COMPONENTS:
            accumulator[component_name] = 0.0
        reports = _synthetic_reports(count)
        started = perf_counter()
        results = [engine.analyze(report) for report in reports]
        total_seconds = perf_counter() - started
        measurements.append(
            ScaleMeasurement(
                report_count=count,
                result_count=len(results),
                total_inference_seconds=total_seconds,
                per_component_seconds={
                    component_name: accumulator[component_name]
                    for component_name in BENCHMARK_COMPONENTS
                },
                semantic_output_sha256=_semantic_digest(results),
            )
        )

    nlp_identity_stable = (
        original_components["nlp_classifier"]._artifact is nlp_artifact
    )
    duplicate_identity_stable = (
        original_components["duplicate_matcher"].feature_state is duplicate_state
    )
    return LocalPerformanceBenchmark(
        recorded_at=recorded_at or datetime.now(timezone.utc),
        runtime={
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        artifact_loads=artifact_loads,
        measurements=measurements,
        resource_observations=ResourceObservations(
            nlp_artifact_identity_stable=nlp_identity_stable,
            duplicate_feature_state_identity_stable=duplicate_identity_stable,
        ),
        limitations=[
            "Synthetic local engineering timing only; not production throughput.",
            "Wall-clock measurements vary with hardware, operating system, and load.",
            "No database, queue, network, API, image model, or learned anomaly model is included.",
        ],
    )


__all__ = [
    "BENCHMARK_COMPONENTS",
    "BENCHMARK_SCALES",
    "ArtifactLoadMeasurement",
    "GrossRegressionGuard",
    "LocalPerformanceBenchmark",
    "ResourceObservations",
    "ScaleMeasurement",
    "run_local_performance_benchmark",
]
