"""Phase 17 project-generated synthetic NLP dataset regression tests."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from app.ml.data.registry import (
    DatasetApprovalError,
    DatasetClassification,
    DatasetProvenance,
    DatasetRegistry,
    DatasetStatus,
    DatasetUse,
    approve_dataset,
    hash_dataset_path,
    load_bound_validation_report,
    save_dataset_registry,
)
from app.ml.data.synthetic_nlp.generator import (
    DEFAULT_SEED,
    GENERATOR_VERSION,
    SyntheticNLPGeneratorConfig,
    register_synthetic_nlp_dataset,
    write_synthetic_nlp_dataset,
)
from app.ml.data.synthetic_nlp.languages import language_text_is_valid
from app.ml.data.synthetic_nlp.scenarios import (
    DATASET_SPLITS,
    HARD_NEGATIVE_TYPES,
    LANGUAGES,
    PRIMARY_CLASSES,
)
from app.ml.data.synthetic_nlp.validation import (
    file_sha256,
    validate_synthetic_dataset,
)


@pytest.fixture(scope="module")
def generated_corpus(tmp_path_factory):
    output = tmp_path_factory.mktemp("phase17-synthetic")
    config = SyntheticNLPGeneratorConfig(total_rows=600)
    artifacts = write_synthetic_nlp_dataset(output, config=config)
    return config, artifacts


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def _validate(
    dataset: Path, scenarios: Path, config: SyntheticNLPGeneratorConfig, total: int
):
    return validate_synthetic_dataset(
        dataset,
        scenarios,
        expected_total_rows=total,
        generator_version=GENERATOR_VERSION,
        scenario_version="synthetic-nlp-scenarios-v1",
        template_version="synthetic-nlp-templates-v1",
        split_version="synthetic-nlp-generator-splits-v1",
        seed=config.seed,
        generated_at=config.creation_timestamp.isoformat(),
    )


def test_generation_is_deterministic_and_seed_reproducible(tmp_path):
    config = SyntheticNLPGeneratorConfig(total_rows=300, seed=DEFAULT_SEED)
    first = write_synthetic_nlp_dataset(tmp_path / "first", config=config)
    second = write_synthetic_nlp_dataset(tmp_path / "second", config=config)
    changed = write_synthetic_nlp_dataset(
        tmp_path / "changed",
        config=SyntheticNLPGeneratorConfig(total_rows=300, seed=DEFAULT_SEED + 1),
    )

    assert first.dataset_hash == second.dataset_hash
    assert first.scenario_metadata_hash == second.scenario_metadata_hash
    assert first.dataset_path.read_bytes() == second.dataset_path.read_bytes()
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    assert changed.dataset_hash != first.dataset_hash


def test_labels_languages_ids_and_scenario_bindings_are_correct(generated_corpus):
    config, artifacts = generated_corpus
    records = _jsonl(artifacts.dataset_path)
    scenarios = _jsonl(artifacts.scenario_metadata_path)

    assert len(records) == config.total_rows
    assert {row["event_type"] for row in records} == set(PRIMARY_CLASSES)
    assert {row["language"] for row in records} == set(LANGUAGES)
    assert {row["split"] for row in records} == set(DATASET_SPLITS)
    assert len({row["record_id"] for row in records}) == len(records)
    assert len({row["scenario_id"] for row in records}) == len(records)
    for record, scenario in zip(records, scenarios):
        assert record["event_type"] == scenario["event_type"]
        assert record["record_id"] == scenario["record_id"]
        assert record["scenario_id"] == scenario["scenario_id"]
        assert record["label_origin"] == "GENERATOR_SCENARIO_SPECIFICATION"
        assert language_text_is_valid(record["text"], record["language"])


def test_class_language_noise_and_hard_negative_balance(generated_corpus):
    _, artifacts = generated_corpus
    report = artifacts.report

    assert report.rows_per_class == {label: 120 for label in PRIMARY_CLASSES}
    assert report.rows_per_language == {language: 200 for language in LANGUAGES}
    assert report.rows_per_split == {"train": 480, "validation": 60, "test": 60}
    assert report.class_balance == "PASS"
    assert report.language_balance == "PASS"
    assert report.template_concentration == "PASS"
    assert report.max_rows_per_template <= report.template_concentration_limit
    assert report.hard_negative_rows == 130
    assert set(report.hard_negative_distribution) == set(HARD_NEGATIVE_TYPES.values())
    assert all(
        report.noise_distribution[profile] > 0
        for profile in ("NONE", "LOW", "MEDIUM", "HIGH")
    )


def test_holdout_uses_generator_level_separation(generated_corpus):
    _, artifacts = generated_corpus
    records = _jsonl(artifacts.dataset_path)
    per_split_templates = {
        split: {row["template_id"] for row in records if row["split"] == split}
        for split in DATASET_SPLITS
    }
    per_split_scenarios = {
        split: {row["scenario_id"] for row in records if row["split"] == split}
        for split in DATASET_SPLITS
    }
    train_noise = {row["noise_profile"] for row in records if row["split"] == "train"}
    test_noise = {row["noise_profile"] for row in records if row["split"] == "test"}

    assert per_split_templates["train"].isdisjoint(per_split_templates["validation"])
    assert per_split_templates["train"].isdisjoint(per_split_templates["test"])
    assert per_split_scenarios["train"].isdisjoint(per_split_scenarios["test"])
    assert "HIGH" not in train_noise
    assert test_noise == {"HIGH"}
    assert artifacts.report.holdout_contract["random_row_split"] is False
    assert artifacts.report.leakage_results.status == "PASS"


def test_duplicate_detection_fails_closed(generated_corpus, tmp_path):
    config, artifacts = generated_corpus
    dataset = tmp_path / "dataset.jsonl"
    scenarios = tmp_path / "scenarios.jsonl"
    shutil.copy2(artifacts.dataset_path, dataset)
    shutil.copy2(artifacts.scenario_metadata_path, scenarios)
    dataset.write_bytes(
        dataset.read_bytes() + dataset.read_bytes().splitlines(keepends=True)[0]
    )
    scenarios.write_bytes(
        scenarios.read_bytes() + scenarios.read_bytes().splitlines(keepends=True)[0]
    )

    report = _validate(dataset, scenarios, config, config.total_rows + 1)

    assert report.valid is False
    assert report.duplicate_counts["duplicate_record_ids"] == 1
    assert report.duplicate_counts["duplicate_scenario_ids"] == 1
    assert report.duplicate_counts["exact_text_duplicates"] == 1
    assert report.duplicate_counts["normalized_text_duplicates"] == 1


def test_label_consistency_is_bound_to_scenario(generated_corpus, tmp_path):
    config, artifacts = generated_corpus
    records = _jsonl(artifacts.dataset_path)
    records[0]["event_type"] = "NOT_RELEVANT"
    dataset = tmp_path / "dataset.jsonl"
    _write_jsonl(dataset, records)

    report = _validate(
        dataset,
        artifacts.scenario_metadata_path,
        config,
        config.total_rows,
    )

    assert report.valid is False
    assert report.label_consistency_failures > 0
    assert report.scenario_binding_failures > 0


def test_template_and_scenario_leakage_are_detected(generated_corpus, tmp_path):
    config, artifacts = generated_corpus
    records = _jsonl(artifacts.dataset_path)
    scenarios = _jsonl(artifacts.scenario_metadata_path)
    train = next(row for row in records if row["split"] == "train")
    test_index = next(
        index for index, row in enumerate(records) if row["split"] == "test"
    )
    records[test_index]["template_id"] = train["template_id"]
    scenarios[test_index]["template_id"] = train["template_id"]
    records[test_index]["scenario_id"] = train["scenario_id"]
    scenarios[test_index]["scenario_id"] = train["scenario_id"]
    dataset = tmp_path / "dataset.jsonl"
    scenario_path = tmp_path / "scenarios.jsonl"
    _write_jsonl(dataset, records)
    _write_jsonl(scenario_path, scenarios)

    report = _validate(dataset, scenario_path, config, config.total_rows)

    assert report.valid is False
    assert report.leakage_results.template_leakage_count == 1
    assert report.leakage_results.scenario_leakage_count == 1


def test_near_duplicate_cross_split_text_is_detected(generated_corpus, tmp_path):
    config, artifacts = generated_corpus
    records = _jsonl(artifacts.dataset_path)
    scenarios = _jsonl(artifacts.scenario_metadata_path)
    train_index = next(
        index
        for index, row in enumerate(records)
        if row["split"] == "train"
        and row["event_type"] == "URBAN_FLOOD"
        and row["language"] == "English"
    )
    test_index = next(
        index
        for index, row in enumerate(records)
        if row["split"] == "test"
        and row["event_type"] == "URBAN_FLOOD"
        and row["language"] == "English"
    )
    train_text = records[train_index]["text"]
    records[test_index]["text"] = re.sub(
        r"\d+",
        lambda match: str(int(match.group(0)) + 1),
        train_text,
        count=1,
    )
    scenarios[test_index]["location"] = scenarios[train_index]["location"]
    dataset = tmp_path / "dataset.jsonl"
    scenario_path = tmp_path / "scenarios.jsonl"
    _write_jsonl(dataset, records)
    _write_jsonl(scenario_path, scenarios)

    report = _validate(dataset, scenario_path, config, config.total_rows)

    assert report.valid is False
    assert report.leakage_results.near_duplicate_cross_split_count > 0


def test_registry_integration_preserves_synthetic_governance(
    generated_corpus, tmp_path
):
    config, artifacts = generated_corpus
    registry_path = tmp_path / "registry" / "datasets.json"
    save_dataset_registry(
        DatasetRegistry(last_modified_at=config.creation_timestamp),
        registry_path,
        modified_at=config.creation_timestamp,
    )

    record = register_synthetic_nlp_dataset(
        artifacts,
        config=config,
        registry_path=registry_path,
    )

    assert record.status is DatasetStatus.VALID
    assert record.provenance is DatasetProvenance.PROJECT_AUTHORED
    assert record.data_classification is DatasetClassification.DEVELOPMENT_ONLY
    assert record.human_adjudicated is False
    assert record.label_source == "PROJECT_GENERATED_SYNTHETIC"
    assert record.metadata["synthetic"] is True
    assert record.metadata["production_validation"] == "NOT_PRODUCTION_VALIDATION"
    validation = load_bound_validation_report(record, registry_path)
    assert validation.leakage.overall_status == "PASS"
    assert validation.component_readiness["synthetic_release_evidence"] == "VALID"
    assert (
        "SYNTHETIC_LABELS_DEVELOPMENT_ONLY" in validation.approval_blockers["TRAINING"]
    )
    assert (
        "MODEL_GENERATED_LABELS_PROHIBITED"
        not in validation.approval_blockers["TRAINING"]
    )
    with pytest.raises(DatasetApprovalError, match="DEVELOPMENT_ONLY_DATASET"):
        approve_dataset(
            config.dataset_id,
            DatasetUse.TEST,
            approver_id="phase17-test",
            approval_note="Development-only data must remain blocked.",
            registry_path=registry_path,
            dataset_version=config.dataset_version,
            approved_at=config.creation_timestamp,
        )


def test_final_hashes_bind_dataset_scenarios_report_and_manifest(generated_corpus):
    _, artifacts = generated_corpus
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))

    assert (
        hash_dataset_path(artifacts.dataset_path).content_sha256
        == artifacts.dataset_hash
    )
    assert artifacts.report.dataset_hash == artifacts.dataset_hash
    assert manifest["dataset_sha256"] == artifacts.dataset_hash
    assert manifest["scenario_metadata_sha256"] == file_sha256(
        artifacts.scenario_metadata_path
    )
    assert manifest["quality_report_sha256"] == file_sha256(artifacts.report_path)
    assert manifest["network_access"] is False
    assert manifest["models_trained"] == []
    assert manifest["pretrained_models"] == []
    assert manifest["open_weight_models"] == []
