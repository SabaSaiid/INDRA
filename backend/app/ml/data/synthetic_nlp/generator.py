"""Reproducible local generator for development-only synthetic NLP reports."""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from app.ml.config import local_only_path
from app.ml.data.synthetic_nlp.languages import (
    LANGUAGE_RENDERER_VERSION,
    compose_message,
    format_depth,
    format_event_time,
)
from app.ml.data.synthetic_nlp.lexicon import (
    CONCEPTS,
    DURATIONS_MINUTES,
    LEXICON_VERSION,
    LOCATIONS,
    SEVERITIES,
    SOURCE_STYLES,
    TIDE_RISE_CM,
    WATER_DEPTHS_CM,
    WIND_SPEEDS_KMPH,
    term_values,
)
from app.ml.data.synthetic_nlp.noise import NOISE_VERSION, apply_noise
from app.ml.data.synthetic_nlp.scenarios import (
    HARD_NEGATIVE_TYPES,
    SyntheticNLPRecord,
    SyntheticScenario,
)
from app.ml.data.synthetic_nlp.splits import (
    SPLIT_VERSION,
    GenerationSlot,
    generation_slots,
)
from app.ml.data.synthetic_nlp.templates import TEMPLATE_VERSION, templates_for
from app.ml.data.synthetic_nlp.validation import (
    SyntheticNLPDatasetReport,
    file_sha256,
    validate_synthetic_dataset,
    write_quality_report,
)

GENERATOR_VERSION: Final[str] = "synthetic-nlp-generator-v1"
SCENARIO_VERSION: Final[str] = "synthetic-nlp-scenarios-v1"
MANIFEST_VERSION: Final[str] = "synthetic-nlp-dataset-manifest-v1"
DEFAULT_SEED: Final[int] = 170017
DEFAULT_TOTAL_ROWS: Final[int] = 100_000
DEFAULT_DATASET_ID: Final[str] = "indra-nlp-project-synthetic-v1"
DEFAULT_DATASET_VERSION: Final[str] = "synthetic-nlp-100k-v1"
DEFAULT_CREATION_TIMESTAMP: Final[datetime] = datetime(
    2026,
    9,
    23,
    0,
    0,
    tzinfo=timezone.utc,
)

_SPLIT_TIME_ORIGINS: Final[dict[str, datetime]] = {
    "train": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "validation": datetime(2026, 5, 1, tzinfo=timezone.utc),
    "test": datetime(2026, 8, 1, tzinfo=timezone.utc),
}


@dataclass(frozen=True, slots=True)
class SyntheticNLPGeneratorConfig:
    total_rows: int = DEFAULT_TOTAL_ROWS
    seed: int = DEFAULT_SEED
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_version: str = DEFAULT_DATASET_VERSION
    creation_timestamp: datetime = DEFAULT_CREATION_TIMESTAMP
    hard_negative_every: int = 5

    def __post_init__(self) -> None:
        if self.total_rows < 50:
            raise ValueError("total_rows must allow every class in every split")
        if self.hard_negative_every < 2:
            raise ValueError("hard_negative_every must be at least 2")
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("creation_timestamp must include a timezone")
        if not self.dataset_id.strip() or not self.dataset_version.strip():
            raise ValueError("dataset identity cannot be blank")


@dataclass(frozen=True, slots=True)
class GeneratedExample:
    record: SyntheticNLPRecord
    scenario: SyntheticScenario


@dataclass(frozen=True, slots=True)
class SyntheticNLPArtifacts:
    output_directory: Path
    dataset_path: Path
    scenario_metadata_path: Path
    report_path: Path
    manifest_path: Path
    dataset_hash: str
    scenario_metadata_hash: str
    report_hash: str
    manifest_hash: str
    report: SyntheticNLPDatasetReport
    manifest: dict[str, Any]


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _short_hash(payload: Any, length: int = 24) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()[:length]


def _record_rng(seed: int, slot: GenerationSlot) -> random.Random:
    material = (
        f"{GENERATOR_VERSION}|{seed}|{slot.event_type}|{slot.split}|"
        f"{slot.split_class_ordinal}|{slot.global_index}"
    ).encode()
    derived_seed = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
    return random.Random(derived_seed)


def _event_time(slot: GenerationSlot) -> datetime:
    return _SPLIT_TIME_ORIGINS[slot.split] + timedelta(minutes=slot.split_index)


def generate_example(
    slot: GenerationSlot,
    *,
    config: SyntheticNLPGeneratorConfig,
) -> GeneratedExample:
    """Generate one report whose label is copied from its structured scenario."""

    rng = _record_rng(config.seed, slot)
    event_time = _event_time(slot)
    location = rng.choice(LOCATIONS[slot.split]).for_language(slot.language)
    concept = rng.choice(CONCEPTS[slot.event_type][slot.language])
    rain = rng.choice(term_values(slot.split, slot.language, "rain"))
    river = rng.choice(term_values(slot.split, slot.language, "river"))
    storm = rng.choice(term_values(slot.split, slot.language, "storm"))
    cyclone = rng.choice(term_values(slot.split, slot.language, "cyclone"))
    topic = rng.choice(term_values(slot.split, slot.language, "topic"))
    water_depth_cm = rng.choice(WATER_DEPTHS_CM[slot.event_type])
    severity = rng.choice(SEVERITIES[slot.event_type])
    source_style = rng.choice(SOURCE_STYLES)
    duration = rng.choice(DURATIONS_MINUTES)
    wind = rng.choice(WIND_SPEEDS_KMPH)
    tide = rng.choice(TIDE_RISE_CM)
    template = rng.choice(
        templates_for(
            slot.split,
            slot.event_type,
            slot.language,
            hard_negative=slot.hard_negative,
        )
    )
    context = {
        "concept": concept,
        "cyclone": cyclone,
        "depth": format_depth(water_depth_cm, slot.language),
        "duration": duration,
        "location": location,
        "rain": rain,
        "river": river,
        "storm": storm,
        "tide": tide,
        "time": format_event_time(event_time, slot.language),
        "topic": topic,
        "wind": wind,
    }
    body = template.text.format(**context)
    framed, frame_id = compose_message(
        body,
        language=slot.language,
        source_style=source_style,
        variant=rng.randrange(6),
    )
    text = apply_noise(
        framed,
        profile=slot.noise_profile,
        language=slot.language,
        rng=rng,
    )
    rendered_template_id = f"{template.template_id}::{frame_id}"
    hard_negative_type = (
        HARD_NEGATIVE_TYPES[slot.event_type] if slot.hard_negative else None
    )
    combination_payload = {
        "event_type": slot.event_type,
        "concept": concept,
        "location": location,
        "rain_intensity": rain,
        "river_condition": river,
        "storm_condition": storm,
        "cyclone_context": cyclone,
        "language": slot.language,
        "severity": severity,
        "source_style": source_style,
        "noise_profile": slot.noise_profile,
        "hard_negative_type": hard_negative_type,
    }
    parameter_combination_id = f"combo-{_short_hash(combination_payload)}"
    scenario_payload = {
        **combination_payload,
        "event_time": event_time.isoformat(),
        "ordinal": slot.global_index,
        "seed": config.seed,
        "split": slot.split,
        "template_id": rendered_template_id,
        "water_depth_cm": water_depth_cm,
    }
    scenario_id = f"scenario-{_short_hash(scenario_payload)}"
    record_id = (
        f"synthetic-report-{_short_hash({'scenario_id': scenario_id, 'text': text})}"
    )
    scenario = SyntheticScenario(
        scenario_id=scenario_id,
        record_id=record_id,
        event_type=slot.event_type,
        concept=concept,
        scenario_family=(
            f"HARD_NEGATIVE::{hard_negative_type}"
            if hard_negative_type
            else f"PRIMARY::{slot.event_type}::{concept}"
        ),
        location=location,
        event_time=event_time.isoformat(),
        rain_intensity=rain,
        water_depth_cm=water_depth_cm,
        river_condition=river,
        storm_condition=storm,
        cyclone_context=cyclone,
        language=slot.language,
        severity=severity,
        source_style=source_style,
        noise_profile=slot.noise_profile,
        split=slot.split,
        template_id=rendered_template_id,
        parameter_combination_id=parameter_combination_id,
        hard_negative=slot.hard_negative,
        hard_negative_type=hard_negative_type,
        generator_version=GENERATOR_VERSION,
        scenario_version=SCENARIO_VERSION,
        template_version=TEMPLATE_VERSION,
        split_version=SPLIT_VERSION,
        seed=config.seed,
        ordinal=slot.global_index,
    )
    record = SyntheticNLPRecord(
        record_id=record_id,
        text=text,
        event_type=scenario.event_type,
        language=slot.language,
        split=slot.split,
        scenario_id=scenario_id,
        event_time=event_time.isoformat(),
        template_id=rendered_template_id,
        parameter_combination_id=parameter_combination_id,
        noise_profile=slot.noise_profile,
        hard_negative=slot.hard_negative,
    )
    return GeneratedExample(record=record, scenario=scenario)


def generate_examples(
    config: SyntheticNLPGeneratorConfig,
) -> Iterator[GeneratedExample]:
    for slot in generation_slots(
        config.total_rows,
        hard_negative_every=config.hard_negative_every,
    ):
        yield generate_example(slot, config=config)


def _write_json_atomic(payload: dict[str, Any], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            )
        )
        handle.write(b"\n")
    temporary.replace(path)
    return file_sha256(path)


def write_synthetic_nlp_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticNLPGeneratorConfig | None = None,
    overwrite: bool = False,
) -> SyntheticNLPArtifacts:
    """Generate, validate, hash, and manifest one immutable synthetic corpus."""

    selected_config = config or SyntheticNLPGeneratorConfig()
    output = local_only_path(
        output_directory,
        description="synthetic NLP output directories",
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    dataset_path = output / "synthetic_nlp_dataset.jsonl"
    scenario_path = output / "synthetic_nlp_scenarios.jsonl"
    report_path = output / "synthetic_nlp_dataset_report.json"
    manifest_path = output / "synthetic_nlp_dataset_manifest.json"
    targets = (dataset_path, scenario_path, report_path, manifest_path)
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite generated artifacts: "
            + ", ".join(path.name for path in existing)
        )

    temporary_paths: list[Path] = []
    try:
        with (
            tempfile.NamedTemporaryFile(
                mode="wb",
                dir=output,
                prefix=dataset_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as dataset_handle,
            tempfile.NamedTemporaryFile(
                mode="wb",
                dir=output,
                prefix=scenario_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as scenario_handle,
        ):
            temporary_dataset = Path(dataset_handle.name)
            temporary_scenarios = Path(scenario_handle.name)
            temporary_paths.extend((temporary_dataset, temporary_scenarios))
            for example in generate_examples(selected_config):
                dataset_handle.write(_canonical_json(example.record.as_dict()) + b"\n")
                scenario_handle.write(
                    _canonical_json(example.scenario.as_metadata()) + b"\n"
                )
        temporary_dataset.replace(dataset_path)
        temporary_scenarios.replace(scenario_path)
        temporary_paths.clear()
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)

    report = validate_synthetic_dataset(
        dataset_path,
        scenario_path,
        expected_total_rows=selected_config.total_rows,
        generator_version=GENERATOR_VERSION,
        scenario_version=SCENARIO_VERSION,
        template_version=TEMPLATE_VERSION,
        split_version=SPLIT_VERSION,
        seed=selected_config.seed,
        generated_at=selected_config.creation_timestamp.isoformat(),
    )
    report_hash = write_quality_report(report, report_path)
    if not report.valid:
        raise ValueError(
            "generated synthetic NLP dataset failed validation: "
            + "; ".join(report.errors)
        )
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_id": selected_config.dataset_id,
        "dataset_version": selected_config.dataset_version,
        "created_at": selected_config.creation_timestamp.isoformat(),
        "generator_version": GENERATOR_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "template_version": TEMPLATE_VERSION,
        "lexicon_version": LEXICON_VERSION,
        "language_renderer_version": LANGUAGE_RENDERER_VERSION,
        "noise_version": NOISE_VERSION,
        "split_version": SPLIT_VERSION,
        "seed": selected_config.seed,
        "total_rows": selected_config.total_rows,
        "hard_negative_every": selected_config.hard_negative_every,
        "dataset_file": dataset_path.name,
        "dataset_sha256": report.dataset_hash,
        "scenario_metadata_file": scenario_path.name,
        "scenario_metadata_sha256": report.scenario_metadata_hash,
        "quality_report_file": report_path.name,
        "quality_report_sha256": report_hash,
        "provenance": "PROJECT_AUTHORED",
        "data_kind": "SYNTHETIC",
        "classification": "DEVELOPMENT_ONLY",
        "production_validation": "NOT_PRODUCTION_VALIDATION",
        "label_source": "GENERATOR_SCENARIO_SPECIFICATION",
        "random_row_split": False,
        "models_trained": [],
        "pretrained_models": [],
        "open_weight_models": [],
        "external_apis": [],
        "network_access": False,
    }
    manifest_hash = _write_json_atomic(manifest, manifest_path)
    return SyntheticNLPArtifacts(
        output_directory=output,
        dataset_path=dataset_path,
        scenario_metadata_path=scenario_path,
        report_path=report_path,
        manifest_path=manifest_path,
        dataset_hash=report.dataset_hash,
        scenario_metadata_hash=report.scenario_metadata_hash,
        report_hash=report_hash,
        manifest_hash=manifest_hash,
        report=report,
        manifest=manifest,
    )


def _registry_relative(path: Path, registry_path: Path) -> str:
    return Path(os.path.relpath(path, registry_path.parent)).as_posix()


def register_synthetic_nlp_dataset(
    artifacts: SyntheticNLPArtifacts,
    *,
    config: SyntheticNLPGeneratorConfig,
    registry_path: Path | str,
    replace_existing: bool = False,
):
    """Register and structurally validate the development-only synthetic corpus."""

    from app.ml.data.dataset_validation import validate_registered_dataset
    from app.ml.data.registry import (
        DatasetClassification,
        DatasetComponent,
        DatasetFormat,
        DatasetProvenance,
        DatasetRegistryRecord,
        DatasetStatus,
        find_dataset,
        load_dataset_registry,
        register_dataset,
    )

    selected_registry = local_only_path(
        registry_path,
        description="dataset registries",
    ).resolve()
    record = DatasetRegistryRecord(
        dataset_id=config.dataset_id,
        dataset_version=config.dataset_version,
        component=DatasetComponent.NLP,
        local_path=_registry_relative(artifacts.dataset_path, selected_registry),
        format=DatasetFormat.JSONL,
        content_sha256=artifacts.dataset_hash,
        schema_version="synthetic-nlp-report-dataset-v1",
        label_schema_version="event-type-labels-v1",
        creation_timestamp=config.creation_timestamp,
        source_description=(
            "Reproducible project-generated synthetic English, Hindi, and "
            "Hinglish reports. This corpus is development-only and is not "
            "evidence of field performance."
        ),
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note=(
            "Internal synthetic development and regression use only; prohibited "
            "as production-validation or real-world performance evidence."
        ),
        grouping_field="scenario_id",
        time_field="event_time",
        split_field="split",
        label_count=config.total_rows,
        row_or_image_count=config.total_rows,
        status=DatasetStatus.DISCOVERED,
        data_classification=DatasetClassification.DEVELOPMENT_ONLY,
        human_adjudicated=False,
        label_source="PROJECT_GENERATED_SYNTHETIC",
        metadata={
            "synthetic": True,
            "synthetic_classification": "SYNTHETIC",
            "production_validation": "NOT_PRODUCTION_VALIDATION",
            "dataset_hash": artifacts.dataset_hash,
            "generator_version": GENERATOR_VERSION,
            "scenario_version": SCENARIO_VERSION,
            "template_version": TEMPLATE_VERSION,
            "split_version": SPLIT_VERSION,
            "seed": config.seed,
            "quality_report_path": _registry_relative(
                artifacts.report_path,
                selected_registry,
            ),
            "quality_report_sha256": artifacts.report_hash,
            "manifest_path": _registry_relative(
                artifacts.manifest_path,
                selected_registry,
            ),
            "manifest_sha256": artifacts.manifest_hash,
            "scenario_metadata_path": _registry_relative(
                artifacts.scenario_metadata_path,
                selected_registry,
            ),
            "scenario_metadata_sha256": artifacts.scenario_metadata_hash,
            "holdout_strategy": "GENERATOR_LEVEL_SEPARATION",
            "random_row_split": False,
            "nlp_v2_modified": False,
            "models_trained": [],
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
        },
    )
    register_dataset(
        record,
        registry_path=selected_registry,
        replace_existing=replace_existing,
        modified_at=config.creation_timestamp,
    )
    validation = validate_registered_dataset(
        config.dataset_id,
        registry_path=selected_registry,
        dataset_version=config.dataset_version,
        generated_at=config.creation_timestamp,
    )
    if not validation.valid:
        raise ValueError(
            "registered synthetic NLP dataset failed structural validation"
        )
    return find_dataset(
        load_dataset_registry(selected_registry),
        config.dataset_id,
        config.dataset_version,
    )


__all__ = [
    "DEFAULT_CREATION_TIMESTAMP",
    "DEFAULT_DATASET_ID",
    "DEFAULT_DATASET_VERSION",
    "DEFAULT_SEED",
    "DEFAULT_TOTAL_ROWS",
    "GENERATOR_VERSION",
    "MANIFEST_VERSION",
    "SCENARIO_VERSION",
    "GeneratedExample",
    "SyntheticNLPArtifacts",
    "SyntheticNLPGeneratorConfig",
    "generate_example",
    "generate_examples",
    "register_synthetic_nlp_dataset",
    "write_synthetic_nlp_dataset",
]
