"""Local, human-only NLP annotation contracts and workflow utilities.

No function in this module derives a ground-truth label from text, rules, or a
model. Model output can only be carried as explicitly marked review context.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ml.config import local_only_path
from app.ml.contracts import PredictionStatus, TextPrediction
from app.ml.data.loaders import load_csv
from app.ml.data.schemas import DatasetSplit

ANNOTATION_SCHEMA_VERSION = "nlp-human-annotation-v1"
ANNOTATION_GUIDE_VERSION = "nlp-annotation-guide-v1"
MODEL_SUGGESTION_BANNER = "MODEL SUGGESTION — NOT GROUND TRUTH"

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PROTECTED_REPORTS_PATH = PROJECT_ROOT / "data" / "labelled" / "reports_v1.csv"
ML_ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts"
PROTECTED_V1_ARTIFACT_PATH = ML_ARTIFACT_ROOT / "nlp_classifier_v1.json"
PROTECTED_V2_ARTIFACT_PATH = ML_ARTIFACT_ROOT / "nlp_classifier_v2.json"
PROTECTED_V2_SPLIT_PATH = ML_ARTIFACT_ROOT / "nlp_classifier_v2.split.json"
PROTECTED_V2_RECEIPT_PATH = (
    ML_ARTIFACT_ROOT / "nlp_classifier_v2.final_test_receipt.json"
)

SEALED_SOURCE_DATASET_SHA256 = (
    "3178b8d980d9ea8d5bea9089d0535aeaeebfc80a4cbca9349d27d2fa1bab031d"
)
SEALED_FINAL_TEST_SHA256 = (
    "6082b1a16b0326e7932f5610ce99c873112c216b4c422f9a98dda360b0166813"
)
SEALED_FINAL_TEST_ORDER_SHA256 = (
    "9404db546620ec734efb38464aa1a7d5b7ddfab8f217facc5785d461a3c6c88a"
)
SEALED_V1_ARTIFACT_SHA256 = (
    "a12387cdfc753e92656f840ae7f22c35fac6d4d2179994b2b9c3ddc594789ba4"
)
SEALED_V2_ARTIFACT_SHA256 = (
    "ec827431e59116b534c01aba5359410c1a241e8b5c98534339c0ef0d126c560b"
)


class NLPEventLabel(str, Enum):
    URBAN_FLOOD = "URBAN_FLOOD"
    RIVER_BREACH = "RIVER_BREACH"
    CLOUDBURST = "CLOUDBURST"
    CYCLONE_INUNDATION = "CYCLONE_INUNDATION"
    NOT_RELEVANT = "NOT_RELEVANT"


class NLPAnnotationState(str, Enum):
    LABELED = "LABELED"
    UNCERTAIN = "UNCERTAIN"


class NLPLanguage(str, Enum):
    ENGLISH = "en"
    HINDI = "hi"
    HINGLISH = "hinglish"
    OTHER = "other"
    UNKNOWN = "unknown"


class NLPSamplingStrategy(str, Enum):
    RANDOM = "RANDOM"
    CLASS_BALANCED = "CLASS_BALANCED"
    LANGUAGE_BALANCED = "LANGUAGE_BALANCED"
    DISAGREEMENT_REVIEW = "DISAGREEMENT_REVIEW"
    UNCERTAINTY_REVIEW = "UNCERTAINTY_REVIEW"
    NOT_RELEVANT_REVIEW = "NOT_RELEVANT_REVIEW"
    HINDI_REVIEW = "HINDI_REVIEW"
    HINGLISH_REVIEW = "HINGLISH_REVIEW"
    CONFUSION_PAIR_REVIEW = "CONFUSION_PAIR_REVIEW"


class NLPSourceReport(BaseModel):
    """One locally supplied, still-unlabelled report for human review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_metadata_if_available: dict[str, Any] = Field(default_factory=dict)
    language_hint: NLPLanguage | None = None
    event_id_if_known: str | None = Field(default=None, min_length=1)
    incident_id_if_known: str | None = Field(default=None, min_length=1)
    source_report_family: str | None = Field(default=None, min_length=1)
    source_dataset_id: str | None = Field(default=None, min_length=1)

    @field_validator("report_id")
    @classmethod
    def report_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("report_id cannot be blank")
        return value.strip()


class NLPModelSuggestion(BaseModel):
    """Optional review context that is structurally barred from ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: NLPEventLabel
    confidence: float = Field(ge=0.0, le=1.0)
    model_version: str = Field(min_length=1)
    banner: Literal["MODEL SUGGESTION — NOT GROUND TRUTH"] = (
        MODEL_SUGGESTION_BANNER
    )


class NLPAnnotationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    text: str
    source_metadata_if_available: dict[str, Any] = Field(default_factory=dict)
    blind_annotation: bool = True
    model_assistance: Literal["NONE", "NON_GROUND_TRUTH"] = "NONE"
    model_suggestion: NLPModelSuggestion | None = None


def exact_text_sha256(text: str) -> str:
    """Hash exact UTF-8 text without normalization or transliteration."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text_for_leakage(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def normalized_text_sha256(text: str) -> str:
    return exact_text_sha256(normalize_text_for_leakage(text))


class NLPHumanAnnotation(BaseModel):
    """One immutable human judgment; a suggestion can never become its label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    annotation_id: str = Field(
        default_factory=lambda: f"nlp-annotation-{uuid4()}",
        min_length=1,
    )
    annotation_schema_version: Literal["nlp-human-annotation-v1"] = (
        ANNOTATION_SCHEMA_VERSION
    )
    report_id: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1)
    state: NLPAnnotationState
    label: NLPEventLabel | None = None
    annotator_id: str = Field(min_length=1)
    annotation_timestamp: datetime
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    source_metadata_if_available: dict[str, Any] = Field(default_factory=dict)
    language: NLPLanguage
    event_id_if_known: str | None = Field(default=None, min_length=1)
    incident_id_if_known: str | None = Field(default=None, min_length=1)
    source_report_family: str | None = Field(default=None, min_length=1)
    source_dataset_id: str | None = Field(default=None, min_length=1)
    blind_annotation: bool = True
    model_assistance: Literal["NONE", "NON_GROUND_TRUTH"] = "NONE"
    assistance_shown: bool = False
    model_assistance_shown: bool = False
    model_suggestion: NLPModelSuggestion | None = None

    @model_validator(mode="before")
    @classmethod
    def preserve_assistance_field_compatibility(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "model_assistance_shown" not in value:
            value = {
                **value,
                "model_assistance_shown": bool(value.get("assistance_shown", False)),
            }
        return value

    @field_validator("annotator_id", "reason")
    @classmethod
    def required_human_fields_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("annotator_id and reason cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_human_annotation(self) -> NLPHumanAnnotation:
        if self.annotation_timestamp.tzinfo is None:
            raise ValueError("annotation_timestamp must include a timezone")
        if self.text_hash != exact_text_sha256(self.text):
            raise ValueError("text_hash does not match the exact original text")
        if self.state is NLPAnnotationState.LABELED and self.label is None:
            raise ValueError("LABELED annotations require an approved taxonomy label")
        if self.state is NLPAnnotationState.UNCERTAIN and self.label is not None:
            raise ValueError("UNCERTAIN annotations cannot carry a class label")
        if self.model_assistance_shown != self.assistance_shown:
            raise ValueError(
                "model_assistance_shown must match the legacy assistance_shown field"
            )
        if self.blind_annotation:
            if self.assistance_shown or self.model_assistance != "NONE":
                raise ValueError("blind annotation cannot show model assistance")
            if self.model_suggestion is not None:
                raise ValueError("blind annotation cannot store a model suggestion")
        else:
            if not self.assistance_shown:
                raise ValueError("non-blind annotation must record assistance shown")
            if self.model_assistance != "NON_GROUND_TRUTH":
                raise ValueError("model assistance must be marked NON_GROUND_TRUTH")
            if self.model_suggestion is None:
                raise ValueError("assisted annotation requires suggestion provenance")
        return self


class NLPAdjudicationDecision(BaseModel):
    """Explicit human resolution; no agreement-derived decision is created."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adjudication_id: str = Field(
        default_factory=lambda: f"nlp-adjudication-{uuid4()}",
        min_length=1,
    )
    report_id: str = Field(min_length=1)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_ids: list[str] = Field(min_length=1)
    adjudicator_id: str = Field(min_length=1)
    timestamp: datetime
    final_state: NLPAnnotationState
    final_label: NLPEventLabel | None = None
    reason: str = Field(min_length=1)

    @field_validator("adjudicator_id", "reason")
    @classmethod
    def adjudication_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("adjudicator_id and reason cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_decision(self) -> NLPAdjudicationDecision:
        if self.timestamp.tzinfo is None:
            raise ValueError("adjudication timestamp must include a timezone")
        if len(self.annotation_ids) != len(set(self.annotation_ids)):
            raise ValueError("adjudication annotation_ids must be unique")
        if self.final_state is NLPAnnotationState.LABELED and self.final_label is None:
            raise ValueError("LABELED adjudication requires final_label")
        if self.final_state is NLPAnnotationState.UNCERTAIN and self.final_label is not None:
            raise ValueError("UNCERTAIN adjudication cannot carry final_label")
        return self


class NLPAdjudicationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    annotations: list[NLPHumanAnnotation] = Field(min_length=1)
    disagreement: bool
    status: Literal["UNRESOLVED", "ADJUDICATED"] = "UNRESOLVED"
    decision: NLPAdjudicationDecision | None = None

    @model_validator(mode="after")
    def validate_case(self) -> NLPAdjudicationCase:
        if {item.report_id for item in self.annotations} != {self.report_id}:
            raise ValueError("adjudication annotations must refer to one report")
        if len({item.text_hash for item in self.annotations}) != 1:
            raise ValueError("adjudication annotations disagree on exact report text")
        if self.status == "ADJUDICATED":
            if self.decision is None or self.decision.report_id != self.report_id:
                raise ValueError("adjudicated case requires a matching explicit decision")
        elif self.decision is not None:
            raise ValueError("unresolved case cannot contain a decision")
        return self

    @property
    def effective_state(self) -> NLPAnnotationState:
        return (
            self.decision.final_state
            if self.decision is not None
            else NLPAnnotationState.UNCERTAIN
        )

    @property
    def effective_label(self) -> NLPEventLabel | None:
        return self.decision.final_label if self.decision is not None else None


class NLPAnnotationQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: Literal["nlp-annotation-quality-v1"] = (
        "nlp-annotation-quality-v1"
    )
    generated_at: datetime
    valid: bool
    report_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    annotator_count: int = Field(ge=0)
    annotator_counts: dict[str, int] = Field(default_factory=dict)
    label_counts: dict[str, int] = Field(default_factory=dict)
    language_counts: dict[str, int] = Field(default_factory=dict)
    uncertain_count: int = Field(ge=0)
    agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"]
    agreement_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    repeated_report_count: int = Field(ge=0)
    minimum_repeated_reports: int = Field(ge=1)
    disagreement_count: int = Field(ge=0)
    disagreement_report_ids: list[str] = Field(default_factory=list)
    adjudication_count: int = Field(ge=0)
    unresolved_disagreement_count: int = Field(ge=0)
    duplicate_annotation_ids: list[str] = Field(default_factory=list)
    duplicate_report_annotators: list[str] = Field(default_factory=list)
    duplicate_source_report_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProtectedNLPFinalTestIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_test_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_order_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: int = Field(ge=1)
    exact_text_hashes: frozenset[str]
    normalized_text_hashes: frozenset[str]


class NLPReviewQueue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: NLPSamplingStrategy
    seed: int
    requested_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    report_ids: list[str]
    population_distribution_unchanged: Literal[True] = True
    label_generation: Literal["NONE"] = "NONE"
    basis: str = Field(min_length=1)


class NLPAnnotationStore:
    """Append-only local JSONL store; no update or delete operation exists."""

    def __init__(self, path: Path | str) -> None:
        selected = local_only_path(path, description="NLP annotation paths")
        _reject_protected_write_path(selected)
        self.path = selected

    def load(self) -> list[NLPHumanAnnotation]:
        if not self.path.exists():
            return []
        result: list[NLPHumanAnnotation] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                result.append(NLPHumanAnnotation.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"invalid NLP annotation at line {line_number}: {error}"
                ) from error
        return result

    def append(self, annotation: NLPHumanAnnotation) -> None:
        assert_no_protected_final_test_text(
            [
                NLPSourceReport(
                    report_id=annotation.report_id,
                    text=annotation.text,
                    source_metadata_if_available=(
                        annotation.source_metadata_if_available
                    ),
                    language_hint=annotation.language,
                    event_id_if_known=annotation.event_id_if_known,
                    incident_id_if_known=annotation.incident_id_if_known,
                    source_report_family=annotation.source_report_family,
                    source_dataset_id=annotation.source_dataset_id,
                )
            ]
        )
        existing = self.load()
        if any(item.annotation_id == annotation.annotation_id for item in existing):
            raise ValueError(f"annotation_id already exists: {annotation.annotation_id}")
        if any(
            item.report_id == annotation.report_id
            and item.annotator_id == annotation.annotator_id
            for item in existing
        ):
            raise ValueError("same annotator has already annotated this report")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(annotation.model_dump_json() + "\n")


class NLPAdjudicationStore:
    """Append-only explicit decision store; original annotations stay intact."""

    def __init__(self, path: Path | str) -> None:
        selected = local_only_path(path, description="NLP adjudication paths")
        _reject_protected_write_path(selected)
        self.path = selected

    def load(self) -> list[NLPAdjudicationDecision]:
        if not self.path.exists():
            return []
        result: list[NLPAdjudicationDecision] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                result.append(NLPAdjudicationDecision.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"invalid NLP adjudication at line {line_number}: {error}"
                ) from error
        return result

    def append(self, decision: NLPAdjudicationDecision) -> None:
        existing = self.load()
        if any(item.adjudication_id == decision.adjudication_id for item in existing):
            raise ValueError(
                f"adjudication_id already exists: {decision.adjudication_id}"
            )
        if any(item.report_id == decision.report_id for item in existing):
            raise ValueError("report already has an explicit adjudication decision")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(decision.model_dump_json() + "\n")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_records_sha256(records: Sequence[Any]) -> str:
    payload = [
        record.model_dump(mode="json")
        for record in sorted(records, key=lambda item: item.record_id)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_order_sha256(records: Sequence[Any]) -> str:
    encoded = json.dumps(
        [record.record_id for record in records],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_protected_nlp_assets_immutable() -> ProtectedNLPFinalTestIndex:
    """Verify sealed v1/v2 artifacts and final-test bytes before annotation work."""

    required_paths = (
        PROTECTED_REPORTS_PATH,
        PROTECTED_V1_ARTIFACT_PATH,
        PROTECTED_V2_ARTIFACT_PATH,
        PROTECTED_V2_SPLIT_PATH,
        PROTECTED_V2_RECEIPT_PATH,
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise ValueError("protected NLP evidence is missing: " + ", ".join(missing))
    if _file_sha256(PROTECTED_REPORTS_PATH) != SEALED_SOURCE_DATASET_SHA256:
        raise ValueError("protected reports_v1.csv hash changed")
    if _file_sha256(PROTECTED_V1_ARTIFACT_PATH) != SEALED_V1_ARTIFACT_SHA256:
        raise ValueError("frozen NLP v1 artifact hash changed")
    if _file_sha256(PROTECTED_V2_ARTIFACT_PATH) != SEALED_V2_ARTIFACT_SHA256:
        raise ValueError("frozen NLP v2 artifact hash changed")

    all_records = load_csv(PROTECTED_REPORTS_PATH)
    final_records = [
        record for record in all_records if record.split is DatasetSplit.TEST
    ]
    if len(final_records) != 90:
        raise ValueError("protected final-test row count changed")
    if _canonical_records_sha256(final_records) != SEALED_FINAL_TEST_SHA256:
        raise ValueError("protected final-test content hash changed")
    if _source_order_sha256(final_records) != SEALED_FINAL_TEST_ORDER_SHA256:
        raise ValueError("protected final-test order hash changed")

    split = json.loads(PROTECTED_V2_SPLIT_PATH.read_text(encoding="utf-8"))
    receipt = json.loads(PROTECTED_V2_RECEIPT_PATH.read_text(encoding="utf-8"))
    if split.get("final_test_sha256") != SEALED_FINAL_TEST_SHA256:
        raise ValueError("frozen split evidence does not match the sealed final test")
    if split.get("final_test_source_order_sha256") != SEALED_FINAL_TEST_ORDER_SHA256:
        raise ValueError("frozen split order evidence does not match")
    if (
        receipt.get("status") != "COMPLETED"
        or receipt.get("evaluation_invocation_count") != 1
        or receipt.get("final_test_split_sha256") != SEALED_FINAL_TEST_SHA256
        or receipt.get("artifact_sha256") != SEALED_V2_ARTIFACT_SHA256
    ):
        raise ValueError("frozen final-evaluation receipt is inconsistent")
    return ProtectedNLPFinalTestIndex(
        source_dataset_sha256=SEALED_SOURCE_DATASET_SHA256,
        final_test_sha256=SEALED_FINAL_TEST_SHA256,
        source_order_sha256=SEALED_FINAL_TEST_ORDER_SHA256,
        sample_count=len(final_records),
        exact_text_hashes=frozenset(exact_text_sha256(item.text) for item in final_records),
        normalized_text_hashes=frozenset(
            normalized_text_sha256(item.text) for item in final_records
        ),
    )


def _reject_protected_write_path(path: Path) -> None:
    protected = {
        candidate.resolve()
        for candidate in (
            PROTECTED_REPORTS_PATH,
            PROTECTED_V1_ARTIFACT_PATH,
            PROTECTED_V2_ARTIFACT_PATH,
            PROTECTED_V2_SPLIT_PATH,
            PROTECTED_V2_RECEIPT_PATH,
        )
    }
    if path.resolve() in protected:
        raise ValueError("annotation output cannot target a protected NLP file")


def assert_no_protected_final_test_text(
    reports: Sequence[NLPSourceReport],
    *,
    protected_index: ProtectedNLPFinalTestIndex | None = None,
) -> None:
    index = protected_index or assert_protected_nlp_assets_immutable()
    exact_matches = sorted(
        report.report_id
        for report in reports
        if exact_text_sha256(report.text) in index.exact_text_hashes
    )
    normalized_matches = sorted(
        report.report_id
        for report in reports
        if normalized_text_sha256(report.text) in index.normalized_text_hashes
    )
    if exact_matches or normalized_matches:
        raise ValueError(
            "locally supplied reports overlap the sealed final test; "
            f"exact={exact_matches}, normalized={normalized_matches}"
        )


def build_nlp_annotation_view(
    report: NLPSourceReport,
    prediction: TextPrediction | None = None,
    *,
    blind_annotation: bool = True,
) -> NLPAnnotationView:
    """Render exact report text; assistance is hidden unless explicitly enabled."""

    if blind_annotation:
        return NLPAnnotationView(
            report_id=report.report_id,
            text=report.text,
            source_metadata_if_available=report.source_metadata_if_available,
            blind_annotation=True,
        )
    if (
        prediction is None
        or prediction.status is not PredictionStatus.AVAILABLE
        or prediction.label is None
        or prediction.confidence is None
        or prediction.model_version is None
    ):
        raise ValueError("model-assisted view requires an available explicit prediction")
    suggestion = NLPModelSuggestion(
        label=NLPEventLabel(prediction.label),
        confidence=prediction.confidence,
        model_version=prediction.model_version,
    )
    return NLPAnnotationView(
        report_id=report.report_id,
        text=report.text,
        source_metadata_if_available=report.source_metadata_if_available,
        blind_annotation=False,
        model_assistance="NON_GROUND_TRUTH",
        model_suggestion=suggestion,
    )


def create_nlp_human_annotation(
    report: NLPSourceReport,
    *,
    state: NLPAnnotationState,
    label: NLPEventLabel | None,
    annotator_id: str,
    reason: str,
    confidence: float,
    language: NLPLanguage,
    timestamp: datetime | None = None,
    annotation_id: str | None = None,
    view: NLPAnnotationView | None = None,
    protected_index: ProtectedNLPFinalTestIndex | None = None,
) -> NLPHumanAnnotation:
    """Create a record only from explicit human-supplied state and label."""

    assert_no_protected_final_test_text(
        [report],
        protected_index=protected_index,
    )
    selected_view = view or build_nlp_annotation_view(report)
    if selected_view.report_id != report.report_id or selected_view.text != report.text:
        raise ValueError("annotation view does not match the source report")
    payload: dict[str, Any] = {
        "report_id": report.report_id,
        "text_hash": exact_text_sha256(report.text),
        "text": report.text,
        "state": state,
        "label": label,
        "annotator_id": annotator_id,
        "annotation_timestamp": timestamp or datetime.now(timezone.utc),
        "reason": reason,
        "confidence": confidence,
        "source_metadata_if_available": report.source_metadata_if_available,
        "language": language,
        "event_id_if_known": report.event_id_if_known,
        "incident_id_if_known": report.incident_id_if_known,
        "source_report_family": report.source_report_family,
        "source_dataset_id": report.source_dataset_id,
        "blind_annotation": selected_view.blind_annotation,
        "model_assistance": selected_view.model_assistance,
        "assistance_shown": selected_view.model_suggestion is not None,
        "model_assistance_shown": selected_view.model_suggestion is not None,
        "model_suggestion": selected_view.model_suggestion,
    }
    if annotation_id is not None:
        payload["annotation_id"] = annotation_id
    return NLPHumanAnnotation(**payload)


def build_nlp_adjudication_case(
    annotations: Sequence[NLPHumanAnnotation],
) -> NLPAdjudicationCase:
    if not annotations:
        raise ValueError("at least one human annotation is required")
    report_ids = {item.report_id for item in annotations}
    if len(report_ids) != 1:
        raise ValueError("adjudication annotations must refer to one report")
    judgments = {(item.state, item.label) for item in annotations}
    ordered = sorted(
        annotations,
        key=lambda item: (item.annotation_timestamp, item.annotation_id),
    )
    return NLPAdjudicationCase(
        report_id=ordered[0].report_id,
        annotations=ordered,
        disagreement=len(judgments) > 1,
    )


def adjudicate_nlp_case(
    case: NLPAdjudicationCase,
    *,
    final_state: NLPAnnotationState,
    final_label: NLPEventLabel | None,
    adjudicator_id: str,
    reason: str,
    timestamp: datetime | None = None,
    adjudication_id: str | None = None,
) -> NLPAdjudicationCase:
    """Record a human decision; matching annotations are not auto-adjudicated."""

    payload: dict[str, Any] = {
        "report_id": case.report_id,
        "text_hash": case.annotations[0].text_hash,
        "annotation_ids": [item.annotation_id for item in case.annotations],
        "adjudicator_id": adjudicator_id,
        "timestamp": timestamp or datetime.now(timezone.utc),
        "final_state": final_state,
        "final_label": final_label,
        "reason": reason,
    }
    if adjudication_id is not None:
        payload["adjudication_id"] = adjudication_id
    decision = NLPAdjudicationDecision(**payload)
    return case.model_copy(
        update={
            "status": "ADJUDICATED",
            "decision": decision,
        }
    )


def validate_nlp_annotation_quality(
    annotations: Sequence[NLPHumanAnnotation],
    reports: Sequence[NLPSourceReport],
    *,
    adjudications: Sequence[NLPAdjudicationDecision] = (),
    minimum_repeated_reports: int = 2,
    generated_at: datetime | None = None,
) -> NLPAnnotationQualityReport:
    if minimum_repeated_reports < 1:
        raise ValueError("minimum_repeated_reports must be positive")
    errors: list[str] = []
    warnings: list[str] = []
    report_counts = Counter(report.report_id for report in reports)
    duplicate_report_ids = sorted(
        report_id for report_id, count in report_counts.items() if count > 1
    )
    if duplicate_report_ids:
        errors.append("duplicate source report IDs exist")
    report_by_id = {report.report_id: report for report in reports}

    annotation_ids: set[str] = set()
    duplicate_annotation_ids: set[str] = set()
    report_annotators: set[tuple[str, str]] = set()
    duplicate_report_annotators: set[str] = set()
    by_report: defaultdict[str, list[NLPHumanAnnotation]] = defaultdict(list)
    annotator_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter({label.value: 0 for label in NLPEventLabel})
    language_counts: Counter[str] = Counter({language.value: 0 for language in NLPLanguage})
    uncertain_count = 0
    for annotation in annotations:
        if annotation.annotation_id in annotation_ids:
            duplicate_annotation_ids.add(annotation.annotation_id)
        annotation_ids.add(annotation.annotation_id)
        key = (annotation.report_id, annotation.annotator_id)
        if key in report_annotators:
            duplicate_report_annotators.add("::".join(key))
        report_annotators.add(key)
        by_report[annotation.report_id].append(annotation)
        annotator_counts[annotation.annotator_id] += 1
        language_counts[annotation.language.value] += 1
        if annotation.state is NLPAnnotationState.UNCERTAIN:
            uncertain_count += 1
        elif annotation.label is not None:
            label_counts[annotation.label.value] += 1

        report = report_by_id.get(annotation.report_id)
        if report is None:
            errors.append(f"missing report: {annotation.report_id}")
            continue
        if annotation.text != report.text:
            errors.append(f"annotation text differs from report: {annotation.report_id}")
        if annotation.text_hash != exact_text_sha256(report.text):
            errors.append(f"text-hash mismatch: {annotation.annotation_id}")
        if not annotation.annotator_id.strip():
            errors.append(f"missing annotator: {annotation.annotation_id}")

    if duplicate_annotation_ids:
        errors.append("duplicate annotation IDs exist")
    if duplicate_report_annotators:
        errors.append("same annotator annotated the same report more than once")
    for report_id, items in by_report.items():
        if len({item.text_hash for item in items}) > 1:
            errors.append(f"conflicting report text hashes: {report_id}")

    repeated = {
        report_id: items for report_id, items in by_report.items() if len(items) >= 2
    }
    disagreements = sorted(
        report_id
        for report_id, items in repeated.items()
        if len({(item.state, item.label) for item in items}) > 1
    )
    if len(repeated) < minimum_repeated_reports:
        agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"] = (
            "DATA_UNAVAILABLE"
        )
        agreement_rate = None
        warnings.append(
            "Repeated annotations are insufficient for agreement calculation."
        )
    else:
        agreement_status = "DATA_AVAILABLE"
        agreement_rate = (len(repeated) - len(disagreements)) / len(repeated)

    decisions_by_report: dict[str, NLPAdjudicationDecision] = {}
    for decision in adjudications:
        if decision.report_id in decisions_by_report:
            errors.append(f"duplicate adjudication for report: {decision.report_id}")
        decisions_by_report[decision.report_id] = decision
        items = by_report.get(decision.report_id, [])
        known_ids = {item.annotation_id for item in items}
        if not set(decision.annotation_ids).issubset(known_ids):
            errors.append(
                f"adjudication references unknown annotation: {decision.report_id}"
            )
        if items and decision.text_hash != items[0].text_hash:
            errors.append(f"adjudication text hash mismatch: {decision.report_id}")
    unresolved = [
        report_id for report_id in disagreements if report_id not in decisions_by_report
    ]
    warnings.extend(
        f"unresolved annotation disagreement: {report_id}"
        for report_id in unresolved
    )
    return NLPAnnotationQualityReport(
        generated_at=generated_at or datetime.now(timezone.utc),
        valid=not errors,
        report_count=len(report_by_id),
        annotation_count=len(annotations),
        annotator_count=len(annotator_counts),
        annotator_counts=dict(sorted(annotator_counts.items())),
        label_counts=dict(sorted(label_counts.items())),
        language_counts=dict(sorted(language_counts.items())),
        uncertain_count=uncertain_count,
        agreement_status=agreement_status,
        agreement_rate=agreement_rate,
        repeated_report_count=len(repeated),
        minimum_repeated_reports=minimum_repeated_reports,
        disagreement_count=len(disagreements),
        disagreement_report_ids=disagreements,
        adjudication_count=len(adjudications),
        unresolved_disagreement_count=len(unresolved),
        duplicate_annotation_ids=sorted(duplicate_annotation_ids),
        duplicate_report_annotators=sorted(duplicate_report_annotators),
        duplicate_source_report_ids=duplicate_report_ids,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
    )


def write_nlp_annotation_quality_report(
    path: Path | str,
    report: NLPAnnotationQualityReport,
) -> None:
    selected = local_only_path(path, description="annotation quality reports")
    _reject_protected_write_path(selected)
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _round_robin_groups(
    groups: Mapping[str, Sequence[str]],
    *,
    count: int,
    seed: int,
) -> list[str]:
    rng = random.Random(seed)
    buckets: dict[str, list[str]] = {}
    for name, values in sorted(groups.items()):
        bucket = sorted(set(values))
        rng.shuffle(bucket)
        buckets[name] = bucket
    selected: list[str] = []
    while len(selected) < count and any(buckets.values()):
        for name in sorted(buckets):
            if buckets[name]:
                candidate = buckets[name].pop()
                if candidate not in selected:
                    selected.append(candidate)
                    if len(selected) == count:
                        break
    return selected


def sample_nlp_review_queue(
    reports: Sequence[NLPSourceReport],
    annotations: Sequence[NLPHumanAnnotation],
    *,
    strategy: NLPSamplingStrategy,
    count: int,
    seed: int = 42,
    confusion_pair: tuple[NLPEventLabel, NLPEventLabel] | None = None,
) -> NLPReviewQueue:
    """Prioritize human review without assigning or changing any label."""

    if count < 1:
        raise ValueError("sample count must be positive")
    report_ids = sorted({report.report_id for report in reports})
    available = set(report_ids)
    by_report: defaultdict[str, list[NLPHumanAnnotation]] = defaultdict(list)
    for annotation in annotations:
        if annotation.report_id in available:
            by_report[annotation.report_id].append(annotation)
    groups: dict[str, list[str]] | None = None
    basis = "fixed-seed random sampling of locally supplied report IDs"

    if strategy is NLPSamplingStrategy.RANDOM:
        candidates = list(report_ids)
        random.Random(seed).shuffle(candidates)
        selected = candidates[:count]
    elif strategy is NLPSamplingStrategy.CLASS_BALANCED:
        groups = defaultdict(list)
        for report_id, items in by_report.items():
            for item in items:
                if item.state is NLPAnnotationState.LABELED and item.label is not None:
                    groups[item.label.value].append(report_id)
        selected = _round_robin_groups(groups, count=count, seed=seed)
        basis = "existing human labels only; labels are not generated"
    elif strategy is NLPSamplingStrategy.LANGUAGE_BALANCED:
        groups = defaultdict(list)
        for report in reports:
            annotated_languages = {
                item.language.value for item in by_report.get(report.report_id, [])
            }
            if annotated_languages:
                for language in annotated_languages:
                    groups[language].append(report.report_id)
            elif report.language_hint is not None:
                groups[report.language_hint.value].append(report.report_id)
            else:
                groups[NLPLanguage.UNKNOWN.value].append(report.report_id)
        selected = _round_robin_groups(groups, count=count, seed=seed)
        basis = "human-recorded language or supplied language hint; no translation"
    elif strategy is NLPSamplingStrategy.DISAGREEMENT_REVIEW:
        selected = sorted(
            report_id
            for report_id, items in by_report.items()
            if len(items) >= 2
            and len({(item.state, item.label) for item in items}) > 1
        )[:count]
        basis = "disagreement between independent human annotations"
    elif strategy is NLPSamplingStrategy.UNCERTAINTY_REVIEW:
        selected = sorted(
            report_id
            for report_id, items in by_report.items()
            if any(item.state is NLPAnnotationState.UNCERTAIN for item in items)
        )[:count]
        basis = "reports marked UNCERTAIN by a human annotator"
    elif strategy is NLPSamplingStrategy.NOT_RELEVANT_REVIEW:
        selected = sorted(
            report_id
            for report_id, items in by_report.items()
            if any(item.label is NLPEventLabel.NOT_RELEVANT for item in items)
        )[:count]
        basis = "reports with an existing human NOT_RELEVANT annotation"
    elif strategy in {
        NLPSamplingStrategy.HINDI_REVIEW,
        NLPSamplingStrategy.HINGLISH_REVIEW,
    }:
        target = (
            NLPLanguage.HINDI
            if strategy is NLPSamplingStrategy.HINDI_REVIEW
            else NLPLanguage.HINGLISH
        )
        selected = sorted(
            report.report_id
            for report in reports
            if report.language_hint is target
            or any(
                item.language is target for item in by_report.get(report.report_id, [])
            )
        )[:count]
        basis = f"human-recorded or supplied {target.value} language metadata"
    else:
        if confusion_pair is None:
            raise ValueError("CONFUSION_PAIR_REVIEW requires an actual/predicted pair")
        actual, predicted = confusion_pair
        selected = sorted(
            report_id
            for report_id, items in by_report.items()
            if any(
                item.state is NLPAnnotationState.LABELED
                and item.label is actual
                and item.model_suggestion is not None
                and item.model_suggestion.label is predicted
                for item in items
            )
        )[:count]
        basis = (
            "human label versus explicitly marked non-ground-truth model suggestion"
        )
    candidate_count = (
        len({value for values in groups.values() for value in values})
        if groups is not None
        else len(selected)
        if strategy is not NLPSamplingStrategy.RANDOM
        else len(report_ids)
    )
    return NLPReviewQueue(
        strategy=strategy,
        seed=seed,
        requested_count=count,
        candidate_count=candidate_count,
        report_ids=selected,
        basis=basis,
    )


def load_nlp_source_reports(
    path: Path | str,
    *,
    protect_final_test: bool = True,
) -> list[NLPSourceReport]:
    """Load local JSON/JSONL/CSV reports without changing or translating text."""

    selected = local_only_path(path, description="NLP annotation source paths")
    suffix = selected.suffix.casefold()
    if suffix == ".csv":
        with selected.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    elif suffix == ".jsonl":
        rows = [
            json.loads(line)
            for line in selected.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif suffix == ".json":
        payload = json.loads(selected.read_text(encoding="utf-8"))
        rows = payload.get("reports") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON source must be a list or contain a reports list")
    else:
        raise ValueError("NLP annotation source must be CSV, JSON, or JSONL")
    raw_corpus_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("schema_version") == "raw-nlp-report-v1"
    ]
    if raw_corpus_rows:
        if len(raw_corpus_rows) != len(rows):
            raise ValueError(
                "raw-nlp-report-v1 rows cannot be mixed with legacy source rows"
            )
        from app.ml.data.nlp_corpus import (
            RawNLPReport,
            raw_nlp_reports_to_annotation_sources,
        )

        reports = list(
            raw_nlp_reports_to_annotation_sources(
                [RawNLPReport.model_validate(row) for row in raw_corpus_rows]
            )
        )
        if protect_final_test:
            assert_no_protected_final_test_text(reports)
        return reports
    reports: list[NLPSourceReport] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise TypeError(f"source row {index} is not an object")
        metadata = row.get("source_metadata_if_available", row.get("source_metadata", {}))
        if isinstance(metadata, str):
            metadata = json.loads(metadata) if metadata.strip() else {}
        reports.append(
            NLPSourceReport(
                report_id=str(row.get("report_id") or row.get("id") or ""),
                text=str(row.get("text") or ""),
                source_metadata_if_available=metadata or {},
                language_hint=row.get("language_hint") or row.get("language") or row.get("lang"),
                event_id_if_known=row.get("event_id_if_known") or row.get("event_id"),
                incident_id_if_known=row.get("incident_id_if_known") or row.get("incident_id"),
                source_report_family=row.get("source_report_family") or row.get("report_family_id"),
                source_dataset_id=row.get("source_dataset_id"),
            )
        )
    duplicates = sorted(
        report_id
        for report_id, count in Counter(item.report_id for item in reports).items()
        if count > 1
    )
    if duplicates:
        raise ValueError(f"duplicate source report IDs: {duplicates}")
    if protect_final_test:
        assert_no_protected_final_test_text(reports)
    return reports


__all__ = [
    "ANNOTATION_GUIDE_VERSION",
    "ANNOTATION_SCHEMA_VERSION",
    "MODEL_SUGGESTION_BANNER",
    "NLPAdjudicationCase",
    "NLPAdjudicationDecision",
    "NLPAdjudicationStore",
    "NLPAnnotationQualityReport",
    "NLPAnnotationState",
    "NLPAnnotationStore",
    "NLPAnnotationView",
    "NLPEventLabel",
    "NLPHumanAnnotation",
    "NLPLanguage",
    "NLPModelSuggestion",
    "NLPReviewQueue",
    "NLPSamplingStrategy",
    "NLPSourceReport",
    "ProtectedNLPFinalTestIndex",
    "adjudicate_nlp_case",
    "assert_no_protected_final_test_text",
    "assert_protected_nlp_assets_immutable",
    "build_nlp_adjudication_case",
    "build_nlp_annotation_view",
    "create_nlp_human_annotation",
    "exact_text_sha256",
    "load_nlp_source_reports",
    "normalize_text_for_leakage",
    "normalized_text_sha256",
    "sample_nlp_review_queue",
    "validate_nlp_annotation_quality",
    "write_nlp_annotation_quality_report",
]
