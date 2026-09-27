"""Streaming quality and leakage validation for synthetic NLP datasets."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from itertools import pairwise, zip_longest
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.ml.config import local_only_path
from app.ml.data.synthetic_nlp.languages import language_text_is_valid
from app.ml.data.synthetic_nlp.lexicon import CONCEPTS
from app.ml.data.synthetic_nlp.scenarios import (
    DATASET_SPLITS,
    HARD_NEGATIVE_TYPES,
    LANGUAGES,
    NOISE_PROFILES,
    PRIMARY_CLASSES,
)
from app.ml.data.synthetic_nlp.splits import expected_split_counts

REPORT_VERSION: Final[str] = "synthetic-nlp-dataset-report-v1"
NEAR_DUPLICATE_METHOD: Final[str] = (
    "unicode-normalized location/number-masked token-bigram SimHash; "
    "4x16-bit LSH candidate search; Hamming distance <= 3"
)


class ValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyntheticLeakageResults(ValidationModel):
    status: str
    exact_cross_split_text_count: int = Field(ge=0)
    normalized_cross_split_text_count: int = Field(ge=0)
    near_duplicate_cross_split_count: int = Field(ge=0)
    template_leakage_count: int = Field(ge=0)
    scenario_leakage_count: int = Field(ge=0)
    parameter_combination_leakage_count: int = Field(ge=0)
    method: str
    examples: dict[str, list[str]] = Field(default_factory=dict)


class SyntheticNLPDatasetReport(ValidationModel):
    report_version: str = REPORT_VERSION
    generated_at: str
    valid: bool
    total_rows: int = Field(ge=0)
    rows_per_class: dict[str, int]
    rows_per_language: dict[str, int]
    rows_per_split: dict[str, int]
    templates_per_class: dict[str, int]
    templates_per_split: dict[str, int]
    max_rows_per_template: int = Field(ge=0)
    max_rows_per_template_by_split: dict[str, int]
    template_concentration_limit: int = Field(ge=1)
    template_concentration: str
    noise_distribution: dict[str, int]
    scenario_distribution: dict[str, int]
    hard_negative_distribution: dict[str, int]
    hard_negative_rows: int = Field(ge=0)
    uncertain_rows: int = Field(ge=0)
    duplicate_counts: dict[str, int]
    language_validation_failures: dict[str, int]
    label_consistency_failures: int = Field(ge=0)
    scenario_binding_failures: int = Field(ge=0)
    class_balance: str
    language_balance: str
    split_balance: str
    leakage_results: SyntheticLeakageResults
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_metadata_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str
    scenario_version: str
    template_version: str
    split_version: str
    seed: int
    label_source: str = "GENERATOR_SCENARIO_SPECIFICATION"
    provenance: str = "PROJECT_AUTHORED"
    classification: str = "SYNTHETIC / DEVELOPMENT_ONLY"
    production_validation: str = "NOT_PRODUCTION_VALIDATION"
    holdout_contract: dict[str, Any]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def file_sha256(path: Path | str) -> str:
    selected = local_only_path(path, description="synthetic NLP dataset files")
    digest = hashlib.sha256()
    with selected.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _near_duplicate_basis(text: str, location: str) -> str:
    normalized = normalize_text(text)
    normalized_location = normalize_text(location)
    if normalized_location:
        normalized = normalized.replace(normalized_location, " location ")
    normalized = re.sub(r"\d+", " number ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _simhash64(value: str) -> int:
    tokens = value.split()
    features = (
        tokens
        if len(tokens) < 2
        else [f"{left}\u241f{right}" for left, right in pairwise(tokens)]
    )
    vector = [0] * 64
    for feature in features:
        hashed = int.from_bytes(
            hashlib.sha256(feature.encode("utf-8")).digest()[:8],
            "big",
        )
        for bit in range(64):
            vector[bit] += 1 if hashed & (1 << bit) else -1
    result = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            result |= 1 << bit
    return result


def _read_json_line(line: str, *, source: str, line_number: int) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{source} line {line_number}: invalid JSON: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise TypeError(f"{source} line {line_number}: row must be an object")
    return payload


def _add_cross_split_value(
    locations: dict[str, set[str]],
    value: str,
    split: str,
) -> None:
    locations[value].add(split)


def validate_synthetic_dataset(
    dataset_path: Path | str,
    scenario_metadata_path: Path | str,
    *,
    expected_total_rows: int,
    generator_version: str,
    scenario_version: str,
    template_version: str,
    split_version: str,
    seed: int,
    generated_at: str,
) -> SyntheticNLPDatasetReport:
    """Validate corpus rows and scenario evidence in one bounded-memory pass."""

    selected_dataset = local_only_path(
        dataset_path,
        description="synthetic NLP datasets",
    )
    selected_scenarios = local_only_path(
        scenario_metadata_path,
        description="synthetic NLP scenario metadata",
    )
    class_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    noise_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    hard_negative_counts: Counter[str] = Counter()
    language_failures: Counter[str] = Counter()
    templates_by_class: defaultdict[str, set[str]] = defaultdict(set)
    templates_by_split: defaultdict[str, set[str]] = defaultdict(set)
    template_counts: Counter[str] = Counter()
    template_counts_by_split: defaultdict[str, Counter[str]] = defaultdict(Counter)
    seen_ids: Counter[str] = Counter()
    seen_scenario_ids: Counter[str] = Counter()
    exact_texts: Counter[str] = Counter()
    normalized_texts: Counter[str] = Counter()
    normalized_labels: defaultdict[str, set[str]] = defaultdict(set)
    exact_split_locations: defaultdict[str, set[str]] = defaultdict(set)
    normalized_split_locations: defaultdict[str, set[str]] = defaultdict(set)
    template_split_locations: defaultdict[str, set[str]] = defaultdict(set)
    scenario_split_locations: defaultdict[str, set[str]] = defaultdict(set)
    combination_split_locations: defaultdict[str, set[str]] = defaultdict(set)
    skeleton_split_locations: defaultdict[str, set[str]] = defaultdict(set)
    lsh_buckets: defaultdict[tuple[int, int], list[tuple[str, int, str]]] = defaultdict(
        list
    )
    near_duplicate_pairs: set[tuple[str, str]] = set()
    near_duplicate_examples: list[str] = []
    errors: list[str] = []
    label_consistency_failures = 0
    scenario_binding_failures = 0
    total_rows = 0

    with (
        selected_dataset.open("r", encoding="utf-8", errors="strict") as dataset,
        selected_scenarios.open("r", encoding="utf-8", errors="strict") as scenarios,
    ):
        pairs = zip_longest(dataset, scenarios)
        for line_number, pair in enumerate(pairs, start=1):
            dataset_line, scenario_line = pair
            if dataset_line is None or scenario_line is None:
                errors.append("dataset and scenario metadata row counts differ")
                break
            if not dataset_line.strip() or not scenario_line.strip():
                errors.append(f"blank JSONL row at line {line_number}")
                continue
            try:
                record = _read_json_line(
                    dataset_line,
                    source="dataset",
                    line_number=line_number,
                )
                scenario = _read_json_line(
                    scenario_line,
                    source="scenario metadata",
                    line_number=line_number,
                )
            except (TypeError, ValueError) as error:
                errors.append(str(error))
                continue
            total_rows += 1
            record_id = str(record.get("record_id", ""))
            scenario_id = str(record.get("scenario_id", ""))
            text = str(record.get("text", ""))
            event_type = str(record.get("event_type", ""))
            language = str(record.get("language", ""))
            split = str(record.get("split", ""))
            template_id = str(record.get("template_id", ""))
            combination_id = str(record.get("parameter_combination_id", ""))
            noise_profile = str(record.get("noise_profile", ""))
            hard_negative = record.get("hard_negative") is True

            seen_ids[record_id] += 1
            seen_scenario_ids[scenario_id] += 1
            exact_texts[text] += 1
            normalized = normalize_text(text)
            normalized_texts[normalized] += 1
            normalized_labels[normalized].add(event_type)
            class_counts[event_type] += 1
            language_counts[language] += 1
            split_counts[split] += 1
            noise_counts[noise_profile] += 1
            scenario_family = str(scenario.get("scenario_family", ""))
            scenario_counts[scenario_family] += 1
            if hard_negative:
                hard_type = str(scenario.get("hard_negative_type", ""))
                hard_negative_counts[hard_type] += 1

            templates_by_class[event_type].add(template_id)
            templates_by_split[split].add(template_id)
            template_counts[template_id] += 1
            template_counts_by_split[split][template_id] += 1
            _add_cross_split_value(exact_split_locations, text, split)
            _add_cross_split_value(normalized_split_locations, normalized, split)
            _add_cross_split_value(template_split_locations, template_id, split)
            _add_cross_split_value(scenario_split_locations, scenario_id, split)
            _add_cross_split_value(
                combination_split_locations,
                combination_id,
                split,
            )

            if event_type not in PRIMARY_CLASSES:
                errors.append(f"line {line_number}: unsupported class {event_type!r}")
            if language not in LANGUAGES:
                errors.append(f"line {line_number}: unsupported language {language!r}")
            elif not language_text_is_valid(text, language):
                language_failures[language] += 1
            if split not in DATASET_SPLITS:
                errors.append(f"line {line_number}: unsupported split {split!r}")
            if noise_profile not in NOISE_PROFILES:
                errors.append(
                    f"line {line_number}: unsupported noise profile {noise_profile!r}"
                )
            if not record_id or not scenario_id or not text or not template_id:
                errors.append(f"line {line_number}: required generated field is empty")

            bound_fields = (
                "record_id",
                "scenario_id",
                "event_type",
                "language",
                "split",
                "template_id",
                "parameter_combination_id",
                "noise_profile",
                "hard_negative",
                "event_time",
                "label_origin",
            )
            if any(record.get(field) != scenario.get(field) for field in bound_fields):
                scenario_binding_failures += 1
            if (
                event_type != scenario.get("event_type")
                or record.get("label_origin") != "GENERATOR_SCENARIO_SPECIFICATION"
            ):
                label_consistency_failures += 1
            if (
                event_type in PRIMARY_CLASSES
                and language in LANGUAGES
                and scenario.get("concept") not in CONCEPTS[event_type][language]
            ):
                label_consistency_failures += 1
            if hard_negative:
                if scenario.get("hard_negative_type") != HARD_NEGATIVE_TYPES.get(
                    event_type
                ):
                    label_consistency_failures += 1
            elif scenario.get("hard_negative_type") is not None:
                label_consistency_failures += 1

            location = str(scenario.get("location", ""))
            basis = _near_duplicate_basis(text, location)
            _add_cross_split_value(skeleton_split_locations, basis, split)
            signature = _simhash64(basis)
            candidate_rows: dict[str, tuple[str, int, str]] = {}
            for band in range(4):
                band_value = (signature >> (band * 16)) & 0xFFFF
                for candidate in lsh_buckets[(band, band_value)]:
                    candidate_rows[candidate[2]] = candidate
            for (
                candidate_split,
                candidate_signature,
                candidate_id,
            ) in candidate_rows.values():
                if candidate_split == split:
                    continue
                if (signature ^ candidate_signature).bit_count() <= 3:
                    pair_key = tuple(sorted((record_id, candidate_id)))
                    if pair_key not in near_duplicate_pairs:
                        near_duplicate_pairs.add(pair_key)
                        if len(near_duplicate_examples) < 20:
                            near_duplicate_examples.append("::".join(pair_key))
            for band in range(4):
                band_value = (signature >> (band * 16)) & 0xFFFF
                lsh_buckets[(band, band_value)].append((split, signature, record_id))

    duplicate_ids = sum(count - 1 for count in seen_ids.values() if count > 1)
    duplicate_scenario_ids = sum(
        count - 1 for count in seen_scenario_ids.values() if count > 1
    )
    exact_duplicates = sum(count - 1 for count in exact_texts.values() if count > 1)
    normalized_duplicates = sum(
        count - 1 for count in normalized_texts.values() if count > 1
    )
    conflicting_labels = sum(
        1 for labels in normalized_labels.values() if len(labels) > 1
    )

    def leaked_values(locations: dict[str, set[str]]) -> list[str]:
        return sorted(value for value, splits in locations.items() if len(splits) > 1)

    exact_leaks = leaked_values(exact_split_locations)
    normalized_leaks = leaked_values(normalized_split_locations)
    template_leaks = leaked_values(template_split_locations)
    scenario_leaks = leaked_values(scenario_split_locations)
    combination_leaks = leaked_values(combination_split_locations)
    skeleton_leaks = leaked_values(skeleton_split_locations)
    # Exact aggressive skeleton matches are by definition near duplicates even if
    # they did not land in the stricter SimHash threshold.
    near_duplicate_count = len(near_duplicate_pairs) + len(skeleton_leaks)

    expected_splits = expected_split_counts(expected_total_rows)
    class_values = [class_counts[label] for label in PRIMARY_CLASSES]
    language_values = [language_counts[language] for language in LANGUAGES]
    class_balance = (
        "PASS"
        if max(class_values, default=0) - min(class_values, default=0) <= 1
        else "FAIL"
    )
    language_balance = (
        "PASS"
        if max(language_values, default=0) - min(language_values, default=0) <= 1
        else "FAIL"
    )
    split_balance = (
        "PASS"
        if {key: split_counts[key] for key in DATASET_SPLITS} == expected_splits
        else "FAIL"
    )
    max_rows_per_template = max(template_counts.values(), default=0)
    template_concentration_limit = max(10, (expected_total_rows + 999) // 1000)
    template_concentration = (
        "PASS" if max_rows_per_template <= template_concentration_limit else "FAIL"
    )
    leakage_failures = (
        len(exact_leaks)
        + len(normalized_leaks)
        + near_duplicate_count
        + len(template_leaks)
        + len(scenario_leaks)
        + len(combination_leaks)
    )
    leakage = SyntheticLeakageResults(
        status="PASS" if leakage_failures == 0 else "FAIL",
        exact_cross_split_text_count=len(exact_leaks),
        normalized_cross_split_text_count=len(normalized_leaks),
        near_duplicate_cross_split_count=near_duplicate_count,
        template_leakage_count=len(template_leaks),
        scenario_leakage_count=len(scenario_leaks),
        parameter_combination_leakage_count=len(combination_leaks),
        method=NEAR_DUPLICATE_METHOD,
        examples={
            "exact": exact_leaks[:20],
            "normalized": normalized_leaks[:20],
            "near_duplicate": near_duplicate_examples + skeleton_leaks[:20],
            "template": template_leaks[:20],
            "scenario": scenario_leaks[:20],
            "parameter_combination": combination_leaks[:20],
        },
    )

    if total_rows != expected_total_rows:
        errors.append(
            f"row count mismatch: expected {expected_total_rows}, found {total_rows}"
        )
    if set(class_counts) != set(PRIMARY_CLASSES):
        errors.append("primary class coverage is incomplete or contains unknown labels")
    if set(language_counts) != set(LANGUAGES):
        errors.append("language coverage is incomplete or contains unknown languages")
    if set(split_counts) != set(DATASET_SPLITS):
        errors.append("split coverage is incomplete or contains unknown splits")
    if duplicate_ids or duplicate_scenario_ids:
        errors.append("deterministic identifiers are not unique")
    if exact_duplicates or normalized_duplicates:
        errors.append("generated report text contains duplicates")
    if conflicting_labels:
        errors.append("identical normalized text has conflicting labels")
    if any(language_failures.values()):
        errors.append("language-specific script or code-switch validation failed")
    if label_consistency_failures:
        errors.append("record labels do not match structured scenario specifications")
    if scenario_binding_failures:
        errors.append("dataset rows are not bound to matching scenario metadata")
    if class_balance != "PASS" or language_balance != "PASS" or split_balance != "PASS":
        errors.append("configured class, language, or split balance failed")
    if template_concentration != "PASS":
        errors.append("realized template concentration exceeds the diversity limit")
    if leakage.status != "PASS":
        errors.append("cross-split leakage validation failed")
    if set(noise_counts) != set(NOISE_PROFILES):
        errors.append("not all controlled noise profiles are represented")
    if any(
        hard_negative_counts[HARD_NEGATIVE_TYPES[label]] == 0
        for label in PRIMARY_CLASSES
    ):
        errors.append("hard-negative coverage is incomplete")

    return SyntheticNLPDatasetReport(
        generated_at=generated_at,
        valid=not errors,
        total_rows=total_rows,
        rows_per_class={label: class_counts[label] for label in PRIMARY_CLASSES},
        rows_per_language={
            language: language_counts[language] for language in LANGUAGES
        },
        rows_per_split={split: split_counts[split] for split in DATASET_SPLITS},
        templates_per_class={
            label: len(templates_by_class[label]) for label in PRIMARY_CLASSES
        },
        templates_per_split={
            split: len(templates_by_split[split]) for split in DATASET_SPLITS
        },
        max_rows_per_template=max_rows_per_template,
        max_rows_per_template_by_split={
            split: max(template_counts_by_split[split].values(), default=0)
            for split in DATASET_SPLITS
        },
        template_concentration_limit=template_concentration_limit,
        template_concentration=template_concentration,
        noise_distribution={
            profile: noise_counts[profile] for profile in NOISE_PROFILES
        },
        scenario_distribution=dict(sorted(scenario_counts.items())),
        hard_negative_distribution=dict(sorted(hard_negative_counts.items())),
        hard_negative_rows=sum(hard_negative_counts.values()),
        uncertain_rows=class_counts["UNCERTAIN"],
        duplicate_counts={
            "duplicate_record_ids": duplicate_ids,
            "duplicate_scenario_ids": duplicate_scenario_ids,
            "exact_text_duplicates": exact_duplicates,
            "normalized_text_duplicates": normalized_duplicates,
            "conflicting_labels": conflicting_labels,
        },
        language_validation_failures={
            language: language_failures[language] for language in LANGUAGES
        },
        label_consistency_failures=label_consistency_failures,
        scenario_binding_failures=scenario_binding_failures,
        class_balance=class_balance,
        language_balance=language_balance,
        split_balance=split_balance,
        leakage_results=leakage,
        dataset_hash=file_sha256(selected_dataset),
        scenario_metadata_hash=file_sha256(selected_scenarios),
        generator_version=generator_version,
        scenario_version=scenario_version,
        template_version=template_version,
        split_version=split_version,
        seed=seed,
        holdout_contract={
            "strategy": "GENERATOR_LEVEL_SEPARATION",
            "random_row_split": False,
            "split_specific_templates": True,
            "split_specific_locations": True,
            "split_specific_lexicons": True,
            "split_specific_time_ranges": True,
            "test_noise_profile_held_out_from_train": "HIGH",
            "test_evidence_scope": "SYNTHETIC_VALIDATION_ONLY",
        },
        errors=sorted(set(errors)),
        warnings=[
            "Synthetic validation does not estimate real-world or field performance."
        ],
    )


def write_quality_report(
    report: SyntheticNLPDatasetReport,
    path: Path | str,
) -> str:
    selected = local_only_path(path, description="synthetic NLP quality reports")
    selected.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump_json(indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=selected.parent,
        prefix=selected.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    temporary.replace(selected)
    return file_sha256(selected)


__all__ = [
    "NEAR_DUPLICATE_METHOD",
    "REPORT_VERSION",
    "SyntheticLeakageResults",
    "SyntheticNLPDatasetReport",
    "file_sha256",
    "normalize_text",
    "validate_synthetic_dataset",
    "write_quality_report",
]
