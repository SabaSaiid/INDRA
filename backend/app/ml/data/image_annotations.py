"""Append-only multi-label image annotations, adjudication, QC, and splitting.

The taxonomy records only visible weather-related content.  It does not infer
whether a caption is truthful, where an image was captured, or whether a report
is authentic.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import local_only_path

from app.ml.components.image_processing import perceptual_hash_hamming_distance
from app.ml.contracts import ImageValidationResult


class ImageVisualLabel(str, Enum):
    FLOODED_SCENE = "FLOODED_SCENE"
    HEAVY_RAIN_VISUAL = "HEAVY_RAIN_VISUAL"
    STANDING_WATER = "STANDING_WATER"
    STORM_DAMAGE = "STORM_DAMAGE"
    NORMAL_SCENE = "NORMAL_SCENE"
    UNCERTAIN = "UNCERTAIN"


IMAGE_MODEL_LABELS = (
    ImageVisualLabel.FLOODED_SCENE,
    ImageVisualLabel.HEAVY_RAIN_VISUAL,
    ImageVisualLabel.STANDING_WATER,
    ImageVisualLabel.STORM_DAMAGE,
    ImageVisualLabel.NORMAL_SCENE,
)


ImageSplit = Literal["train", "validation", "test"]
ImageAnnotationStatus = Literal["UNRESOLVED", "ADJUDICATED"]
IMAGE_ANNOTATION_SCHEMA_VERSION = "image-annotations-v1"


def _validate_label_set(labels: Sequence[ImageVisualLabel], uncertain: bool) -> None:
    if not labels:
        raise ValueError("at least one image label is required")
    if len(set(labels)) != len(labels):
        raise ValueError("image labels must be unique")
    selected = set(labels)
    if ImageVisualLabel.UNCERTAIN in selected and len(selected) != 1:
        raise ValueError("UNCERTAIN cannot be combined with another label")
    if ImageVisualLabel.NORMAL_SCENE in selected and len(selected) != 1:
        raise ValueError("NORMAL_SCENE cannot be combined with another label")
    if uncertain and selected != {ImageVisualLabel.UNCERTAIN}:
        raise ValueError("uncertain annotations must use only the UNCERTAIN label")
    if not uncertain and selected == {ImageVisualLabel.UNCERTAIN}:
        raise ValueError("UNCERTAIN label requires uncertain=True")


class ImageAnnotation(BaseModel):
    """One immutable annotator judgment over an already-validated image."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(
        default_factory=lambda: f"image-annotation-{uuid4()}", min_length=1
    )
    image_id: str = Field(min_length=1)
    labels: list[ImageVisualLabel] = Field(min_length=1)
    annotator_id: str = Field(min_length=1)
    annotation_timestamp: datetime
    annotator_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    notes: str | None = None
    uncertain: bool = False
    byte_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    perceptual_similarity_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]+$"
    )
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    detected_format: Literal["JPEG", "PNG"]
    event_id: str | None = Field(default=None, min_length=1)
    incident_id: str | None = Field(default=None, min_length=1)
    report_id: str | None = Field(default=None, min_length=1)
    capture_session_id: str | None = Field(default=None, min_length=1)
    split: ImageSplit | None = None
    schema_version: Literal["image-annotations-v1"] = IMAGE_ANNOTATION_SCHEMA_VERSION

    @model_validator(mode="after")
    def validate_labels(self) -> ImageAnnotation:
        _validate_label_set(self.labels, self.uncertain)
        return self


class ImageAdjudicationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str = Field(min_length=1)
    annotations: list[ImageAnnotation] = Field(min_length=1)
    disagreement: bool
    status: ImageAnnotationStatus = "UNRESOLVED"
    adjudicated_labels: list[ImageVisualLabel] = Field(default_factory=list)
    adjudicator_id: str | None = None
    adjudication_timestamp: datetime | None = None
    adjudication_reason: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> ImageAdjudicationCase:
        if any(item.image_id != self.image_id for item in self.annotations):
            raise ValueError("all adjudication annotations must refer to image_id")
        actual_disagreement = len(
            {frozenset(item.labels) for item in self.annotations}
        ) > 1
        if self.disagreement != actual_disagreement:
            raise ValueError("adjudication disagreement flag does not match annotations")
        if self.status == "ADJUDICATED":
            if not self.adjudicated_labels or not all(
                (
                    self.adjudicator_id,
                    self.adjudication_timestamp,
                    self.adjudication_reason,
                )
            ):
                raise ValueError(
                    "adjudicated image cases require labels, adjudicator, timestamp, and reason"
                )
            _validate_label_set(
                self.adjudicated_labels,
                self.adjudicated_labels == [ImageVisualLabel.UNCERTAIN],
            )
        elif any(
            (
                self.adjudicated_labels,
                self.adjudicator_id,
                self.adjudication_timestamp,
                self.adjudication_reason,
            )
        ):
            raise ValueError("unresolved image cases cannot carry adjudication fields")
        return self

    @property
    def effective_labels(self) -> list[ImageVisualLabel]:
        if self.status == "ADJUDICATED":
            return list(self.adjudicated_labels)
        if self.disagreement:
            return [ImageVisualLabel.UNCERTAIN]
        return list(self.annotations[0].labels)


class ImageAnnotationQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    annotation_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    annotator_counts: dict[str, int] = Field(default_factory=dict)
    label_counts: dict[str, int] = Field(default_factory=dict)
    agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"]
    exact_set_agreement_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    repeatedly_annotated_image_count: int = Field(default=0, ge=0)
    disagreement_image_ids: list[str] = Field(default_factory=list)
    duplicate_annotation_ids: list[str] = Field(default_factory=list)
    repeated_annotation_keys: list[str] = Field(default_factory=list)
    duplicate_byte_hashes: dict[str, list[str]] = Field(default_factory=dict)
    inconsistent_dimension_image_ids: list[str] = Field(default_factory=list)
    inconsistent_dimension_byte_hashes: list[str] = Field(default_factory=list)
    corrupt_image_ids: list[str] = Field(default_factory=list)
    missing_image_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImageLeakageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    image_ids_across_splits: list[str] = Field(default_factory=list)
    byte_hashes_across_splits: list[str] = Field(default_factory=list)
    near_duplicate_image_pairs: list[str] = Field(default_factory=list)
    event_ids_across_splits: list[str] = Field(default_factory=list)
    incident_ids_across_splits: list[str] = Field(default_factory=list)
    report_ids_across_splits: list[str] = Field(default_factory=list)
    capture_sessions_across_splits: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    detection_method: str = (
        "Exact BYTE_HASH plus deterministic average-hash Hamming distance; "
        "the perceptual hash detects coarse luminance similarity only."
    )


class ImageGroupedSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["GROUPED_SPLIT_AVAILABLE", "GROUPED_SPLIT_UNAVAILABLE"]
    group_field: str | None = None
    group_count: int = Field(default=0, ge=0)
    train: list[ImageAnnotation] = Field(default_factory=list)
    validation: list[ImageAnnotation] = Field(default_factory=list)
    test: list[ImageAnnotation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImageAnnotationStore:
    """A JSONL append-only store that never updates original judgments."""

    def __init__(self, path: Path) -> None:
        self.path = local_only_path(path, description="annotation paths")

    def load(self) -> list[ImageAnnotation]:
        if not self.path.exists():
            return []
        records: list[ImageAnnotation] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                records.append(ImageAnnotation.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"invalid image annotation at line {line_number}: {error}"
                ) from error
        return records

    def append(self, annotation: ImageAnnotation) -> None:
        existing = self.load()
        if any(item.annotation_id == annotation.annotation_id for item in existing):
            raise ValueError(f"annotation_id already exists: {annotation.annotation_id}")
        if any(
            item.image_id == annotation.image_id
            and item.annotator_id == annotation.annotator_id
            for item in existing
        ):
            raise ValueError("the same annotator has already annotated this image")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(annotation.model_dump_json() + "\n")


def build_image_adjudication_case(
    annotations: Sequence[ImageAnnotation],
) -> ImageAdjudicationCase:
    if not annotations:
        raise ValueError("at least one image annotation is required")
    image_ids = {item.image_id for item in annotations}
    if len(image_ids) != 1:
        raise ValueError("annotations must refer to one image")
    label_sets = {frozenset(item.labels) for item in annotations}
    return ImageAdjudicationCase(
        image_id=annotations[0].image_id,
        annotations=sorted(
            annotations,
            key=lambda item: (item.annotation_timestamp, item.annotation_id),
        ),
        disagreement=len(label_sets) > 1,
    )


def adjudicate_image_case(
    case: ImageAdjudicationCase,
    *,
    labels: Sequence[ImageVisualLabel],
    adjudicator_id: str,
    reason: str,
    timestamp: datetime | None = None,
) -> ImageAdjudicationCase:
    selected = list(labels)
    _validate_label_set(selected, selected == [ImageVisualLabel.UNCERTAIN])
    if not adjudicator_id.strip() or not reason.strip():
        raise ValueError("adjudicator_id and reason are required")
    return case.model_copy(
        update={
            "status": "ADJUDICATED",
            "adjudicated_labels": selected,
            "adjudicator_id": adjudicator_id,
            "adjudication_timestamp": timestamp or datetime.now(timezone.utc),
            "adjudication_reason": reason,
        }
    )


def validate_image_annotations(
    annotations: Sequence[ImageAnnotation],
    *,
    available_image_ids: set[str] | None = None,
    validation_by_image: Mapping[str, ImageValidationResult] | None = None,
    adjudications: Sequence[ImageAdjudicationCase] | None = None,
) -> ImageAnnotationQualityReport:
    """Check identity, repetition, dimensions, image validity, and agreement."""

    errors: list[str] = []
    warnings: list[str] = []
    annotation_ids: set[str] = set()
    annotation_keys: set[tuple[str, str]] = set()
    duplicate_ids: set[str] = set()
    repeated_keys: set[str] = set()
    by_image: defaultdict[str, list[ImageAnnotation]] = defaultdict(list)
    image_ids_by_hash: defaultdict[str, set[str]] = defaultdict(set)
    dimensions_by_image: defaultdict[str, set[tuple[int, int]]] = defaultdict(set)
    dimensions_by_hash: defaultdict[str, set[tuple[int, int]]] = defaultdict(set)
    annotator_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    missing_images: set[str] = set()
    corrupt_images: set[str] = set()

    for annotation in annotations:
        if annotation.annotation_id in annotation_ids:
            duplicate_ids.add(annotation.annotation_id)
        annotation_ids.add(annotation.annotation_id)
        key = (annotation.image_id, annotation.annotator_id)
        if key in annotation_keys:
            repeated_keys.add("::".join(key))
        annotation_keys.add(key)
        by_image[annotation.image_id].append(annotation)
        image_ids_by_hash[annotation.byte_sha256.casefold()].add(annotation.image_id)
        dimensions_by_image[annotation.image_id].add((annotation.width, annotation.height))
        dimensions_by_hash[annotation.byte_sha256.casefold()].add(
            (annotation.width, annotation.height)
        )
        annotator_counts[annotation.annotator_id] += 1
        label_counts.update(label.value for label in annotation.labels)
        if available_image_ids is not None and annotation.image_id not in available_image_ids:
            missing_images.add(annotation.image_id)
        if validation_by_image is not None:
            validation = validation_by_image.get(annotation.image_id)
            if validation is None:
                missing_images.add(annotation.image_id)
            elif not validation.valid:
                corrupt_images.add(annotation.image_id)
            elif (
                validation.detected_width,
                validation.detected_height,
            ) != (annotation.width, annotation.height):
                dimensions_by_image[annotation.image_id].add(
                    (
                        validation.detected_width or -1,
                        validation.detected_height or -1,
                    )
                )

    if duplicate_ids:
        errors.append("duplicate annotation IDs exist")
    if repeated_keys:
        errors.append("the same annotator annotated an image more than once")
    if missing_images:
        errors.append("one or more annotations have no corresponding image")
    if corrupt_images:
        errors.append("one or more annotated images failed content validation")
    inconsistent_dimensions = sorted(
        image_id for image_id, dimensions in dimensions_by_image.items() if len(dimensions) > 1
    )
    if inconsistent_dimensions:
        errors.append("inconsistent dimensions exist for an image identity")
    inconsistent_hash_dimensions = sorted(
        digest for digest, dimensions in dimensions_by_hash.items() if len(dimensions) > 1
    )
    if inconsistent_hash_dimensions:
        errors.append("inconsistent dimensions exist for an exact BYTE_HASH")
    duplicate_hashes = {
        digest: sorted(image_ids)
        for digest, image_ids in sorted(image_ids_by_hash.items())
        if len(image_ids) > 1
    }
    if duplicate_hashes:
        warnings.append("distinct image IDs share an exact BYTE_HASH")

    repeated = {
        image_id: items
        for image_id, items in by_image.items()
        if len({item.annotator_id for item in items}) >= 2
    }
    disagreements = sorted(
        image_id
        for image_id, items in repeated.items()
        if len({frozenset(item.labels) for item in items}) > 1
    )
    if repeated:
        agreement_status: Literal["DATA_AVAILABLE", "DATA_UNAVAILABLE"] = "DATA_AVAILABLE"
        agreement_rate = (len(repeated) - len(disagreements)) / len(repeated)
    else:
        agreement_status = "DATA_UNAVAILABLE"
        agreement_rate = None
        warnings.append(
            "No images have judgments from multiple annotators; agreement was not calculated."
        )
    adjudication_by_image = {item.image_id: item for item in (adjudications or [])}
    for image_id in disagreements:
        case = adjudication_by_image.get(image_id)
        if case is None or case.status != "ADJUDICATED":
            warnings.append(f"unresolved annotation disagreement remains UNCERTAIN: {image_id}")

    return ImageAnnotationQualityReport(
        valid=not errors,
        annotation_count=len(annotations),
        image_count=len(by_image),
        annotator_counts=dict(sorted(annotator_counts.items())),
        label_counts=dict(sorted(label_counts.items())),
        agreement_status=agreement_status,
        exact_set_agreement_rate=agreement_rate,
        repeatedly_annotated_image_count=len(repeated),
        disagreement_image_ids=disagreements,
        duplicate_annotation_ids=sorted(duplicate_ids),
        repeated_annotation_keys=sorted(repeated_keys),
        duplicate_byte_hashes=duplicate_hashes,
        inconsistent_dimension_image_ids=inconsistent_dimensions,
        inconsistent_dimension_byte_hashes=inconsistent_hash_dimensions,
        corrupt_image_ids=sorted(corrupt_images),
        missing_image_ids=sorted(missing_images),
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
    )


def validate_image_leakage(
    annotations: Sequence[ImageAnnotation],
    *,
    perceptual_hamming_threshold: int = 5,
) -> ImageLeakageReport:
    """Detect exact identity, metadata groups, and coarse visual similarity."""

    if perceptual_hamming_threshold < 0:
        raise ValueError("perceptual_hamming_threshold cannot be negative")
    locations: dict[str, defaultdict[str, set[str]]] = {
        name: defaultdict(set)
        for name in (
            "image",
            "byte_hash",
            "event",
            "incident",
            "report",
            "capture_session",
        )
    }
    perceptual_records: dict[str, tuple[str, str]] = {}
    for annotation in annotations:
        if annotation.split is None:
            continue
        split = annotation.split
        locations["image"][annotation.image_id].add(split)
        locations["byte_hash"][annotation.byte_sha256.casefold()].add(split)
        for key, value in (
            ("event", annotation.event_id),
            ("incident", annotation.incident_id),
            ("report", annotation.report_id),
            ("capture_session", annotation.capture_session_id),
        ):
            if value:
                locations[key][value].add(split)
        if annotation.perceptual_similarity_hash:
            current = perceptual_records.get(annotation.image_id)
            candidate = (split, annotation.perceptual_similarity_hash.casefold())
            if current is None:
                perceptual_records[annotation.image_id] = candidate

    def across(name: str) -> list[str]:
        return sorted(key for key, splits in locations[name].items() if len(splits) > 1)

    near_pairs: set[str] = set()
    records = sorted(perceptual_records.items())
    for index, (left_id, (left_split, left_hash)) in enumerate(records):
        for right_id, (right_split, right_hash) in records[index + 1 :]:
            if left_split == right_split or len(left_hash) != len(right_hash):
                continue
            if (
                perceptual_hash_hamming_distance(left_hash, right_hash)
                <= perceptual_hamming_threshold
            ):
                near_pairs.add("::".join(sorted((left_id, right_id))))

    image_leaks = across("image")
    hash_leaks = across("byte_hash")
    event_leaks = across("event")
    incident_leaks = across("incident")
    report_leaks = across("report")
    capture_leaks = across("capture_session")
    errors: list[str] = []
    for values, message in (
        (image_leaks, "same image ID appears in multiple splits"),
        (hash_leaks, "same BYTE_HASH appears in multiple splits"),
        (near_pairs, "perceptually similar images appear in multiple splits"),
        (event_leaks, "same event appears in multiple splits"),
        (incident_leaks, "same incident appears in multiple splits"),
        (report_leaks, "same source report appears in multiple splits"),
        (capture_leaks, "same capture session appears in multiple splits"),
    ):
        if values:
            errors.append(message)
    return ImageLeakageReport(
        valid=not errors,
        image_ids_across_splits=image_leaks,
        byte_hashes_across_splits=hash_leaks,
        near_duplicate_image_pairs=sorted(near_pairs),
        event_ids_across_splits=event_leaks,
        incident_ids_across_splits=incident_leaks,
        report_ids_across_splits=report_leaks,
        capture_sessions_across_splits=capture_leaks,
        errors=errors,
    )


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def grouped_image_split(
    annotations: Sequence[ImageAnnotation],
    *,
    seed: int = 42,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
    perceptual_hamming_threshold: int = 5,
) -> ImageGroupedSplit:
    """Split metadata groups and deterministic near-duplicate components."""

    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(value <= 0.0 for value in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("split fractions must be positive and sum to one")
    if perceptual_hamming_threshold < 0:
        raise ValueError("perceptual_hamming_threshold cannot be negative")
    if not annotations:
        return ImageGroupedSplit(
            status="GROUPED_SPLIT_UNAVAILABLE",
            warnings=["No image annotations were supplied."],
        )
    group_field = next(
        (
            field
            for field in ("event_id", "incident_id", "report_id", "capture_session_id")
            if all(getattr(item, field) for item in annotations)
        ),
        None,
    )
    if group_field is None:
        return ImageGroupedSplit(
            status="GROUPED_SPLIT_UNAVAILABLE",
            warnings=[
                "Every annotation requires an event, incident, source-report, or capture-session key; naive random splitting is prohibited."
            ],
        )

    disjoint = _DisjointSet(len(annotations))
    first_by_group: dict[str, int] = {}
    first_by_image: dict[str, int] = {}
    first_by_hash: dict[str, int] = {}
    for index, annotation in enumerate(annotations):
        for value, lookup in (
            (str(getattr(annotation, group_field)), first_by_group),
            (annotation.image_id, first_by_image),
            (annotation.byte_sha256.casefold(), first_by_hash),
        ):
            previous = lookup.setdefault(value, index)
            disjoint.union(previous, index)
    for left_index, left in enumerate(annotations):
        if not left.perceptual_similarity_hash:
            continue
        for right_index in range(left_index + 1, len(annotations)):
            right = annotations[right_index]
            if (
                not right.perceptual_similarity_hash
                or len(left.perceptual_similarity_hash)
                != len(right.perceptual_similarity_hash)
            ):
                continue
            if (
                perceptual_hash_hamming_distance(
                    left.perceptual_similarity_hash,
                    right.perceptual_similarity_hash,
                )
                <= perceptual_hamming_threshold
            ):
                disjoint.union(left_index, right_index)

    components: defaultdict[int, list[ImageAnnotation]] = defaultdict(list)
    for index, annotation in enumerate(annotations):
        components[disjoint.find(index)].append(annotation)
    component_ids = sorted(components)
    random.Random(seed).shuffle(component_ids)
    count = len(component_ids)
    train_end = max(1, round(count * train_fraction))
    validation_count = max(1, round(count * validation_fraction)) if count >= 3 else 0
    if train_end + validation_count >= count:
        validation_count = max(0, count - train_end - 1)
    validation_end = train_end + validation_count
    buckets: dict[ImageSplit, list[ImageAnnotation]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    for index, component_id in enumerate(component_ids):
        split: ImageSplit = (
            "train"
            if index < train_end
            else "validation"
            if index < validation_end
            else "test"
        )
        buckets[split].extend(
            annotation.model_copy(update={"split": split})
            for annotation in components[component_id]
        )
    return ImageGroupedSplit(
        status="GROUPED_SPLIT_AVAILABLE",
        group_field=group_field,
        group_count=count,
        train=buckets["train"],
        validation=buckets["validation"],
        test=buckets["test"],
        warnings=(
            ["Fewer than three independent groups exist; one or more buckets are empty."]
            if count < 3
            else []
        ),
    )


__all__ = [
    "IMAGE_ANNOTATION_SCHEMA_VERSION",
    "IMAGE_MODEL_LABELS",
    "ImageAdjudicationCase",
    "ImageAnnotation",
    "ImageAnnotationQualityReport",
    "ImageAnnotationStore",
    "ImageGroupedSplit",
    "ImageLeakageReport",
    "ImageSplit",
    "ImageVisualLabel",
    "adjudicate_image_case",
    "build_image_adjudication_case",
    "grouped_image_split",
    "validate_image_annotations",
    "validate_image_leakage",
]
