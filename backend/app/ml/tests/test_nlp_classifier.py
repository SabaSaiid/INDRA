import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.ml.components.duplicate_features import normalize_text
from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact
from app.ml.config import DEFAULT_NLP_CLASSIFIER_CONFIG, load_artifact_manifest
from app.ml.contracts import PredictionStatus, ReportInput
from app.ml.data.loaders import load_csv
from app.ml.evaluation.evaluate import evaluate_nlp_predictions
from app.ml.training.train_nlp_classifier import _audit_dataset


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[3] / ".phase5-test-tmp"
    path = root / f"case-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()


def test_preprocessing_is_deterministic_and_preserves_multilingual_scripts():
    assert normalize_text("  WATER, Rising!  ") == "water rising"
    assert normalize_text("बाढ़  का  पानी") == "बाढ़ का पानी"
    assert normalize_text("Flood ka paani!!!") == "flood ka paani"
    assert normalize_text("\u00a0") == ""


def test_artifact_is_json_only_and_registered_with_matching_hash():
    artifact_path = DEFAULT_NLP_CLASSIFIER_CONFIG.artifact_path
    artifact = load_nlp_artifact(artifact_path)
    assert artifact.model_version == "nlp-classifier-v1"
    assert artifact.classes == artifact.classifier.classes
    assert artifact.n_features == (
        len(artifact.char_space.vocabulary) + len(artifact.word_space.vocabulary)
    )

    manifest = load_artifact_manifest()
    entry = next(
        item for item in manifest.artifacts
        if item.artifact_name == artifact_path.name
    )
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert entry.sha256 == digest
    assert artifact_path.suffix == ".json"


def test_predictions_support_text_report_input_and_are_deterministic():
    classifier = NLPClassifier()
    texts = [
        "Water is rising near the road",
        "नदी का पानी बढ़ रहा है",
        "Yahan flood ka paani road par aa gaya",
        "tokens never seen by the fitted vocabulary xyzzy",
    ]
    expected_classes = {
        "CLOUDBURST",
        "CYCLONE_INUNDATION",
        "NOT_RELEVANT",
        "RIVER_BREACH",
        "URBAN_FLOOD",
    }
    for text in texts:
        first = classifier.predict(text)
        second = classifier.predict(text)
        assert first.status is PredictionStatus.AVAILABLE
        assert first.model_version == "nlp-classifier-v1"
        assert first.feature_version == "nlp-features-v1"
        assert first.preprocessing_version == "nlp-text-normalization-v1"
        assert set(first.probabilities) == expected_classes
        assert first.label in first.probabilities
        assert sum(first.probabilities.values()) == pytest.approx(1.0)
        assert first.model_dump() == second.model_dump()

    report = ReportInput(
        report_id=uuid4(),
        text=texts[0],
        occurred_at="2026-01-01T00:00:00Z",
        latitude=25.5941,
        longitude=85.1376,
        source_type="TEST",
    )
    assert classifier.predict(report).model_dump() == classifier.predict(texts[0]).model_dump()


def test_empty_text_is_not_applicable_without_fabricated_probabilities():
    prediction = NLPClassifier().predict("   !!! ")
    assert prediction.status is PredictionStatus.NOT_APPLICABLE
    assert prediction.label is None
    assert prediction.probabilities == {}
    assert prediction.reason_codes == ["EMPTY_TEXT"]


def test_missing_or_invalid_artifact_is_explicitly_offline(local_tmp_path):
    missing = NLPClassifier(artifact_path=local_tmp_path / "missing.json").predict("flood")
    assert missing.status is PredictionStatus.OFFLINE
    assert missing.probabilities == {}
    assert missing.reason_codes == ["MODEL_ARTIFACT_UNAVAILABLE"]

    invalid_path = local_tmp_path / "invalid.json"
    invalid_path.write_text("not json", encoding="utf-8")
    invalid = NLPClassifier(artifact_path=invalid_path).predict("flood")
    assert invalid.status is PredictionStatus.OFFLINE
    assert invalid.reason_codes == ["MODEL_ARTIFACT_UNAVAILABLE"]


def test_artifact_loader_rejects_hash_dimension_and_version_mismatches(local_tmp_path):
    source = DEFAULT_NLP_CLASSIFIER_CONFIG.artifact_path
    manifest = load_artifact_manifest()
    source_entry = next(
        item for item in manifest.artifacts if item.artifact_name == source.name
    )
    artifact_path = local_tmp_path / source.name
    manifest_path = local_tmp_path / "manifest.json"

    artifact_path.write_bytes(source.read_bytes())
    local_manifest = manifest.model_copy(update={"artifacts": [source_entry]})
    manifest_path.write_text(local_manifest.model_dump_json(indent=2), encoding="utf-8")
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash does not match manifest"):
        load_nlp_artifact(artifact_path, manifest_path=manifest_path)

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["classifier"]["coefficients"][0].pop()
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    dimension_entry = source_entry.model_copy(
        update={"sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest()}
    )
    manifest_path.write_text(
        manifest.model_copy(update={"artifacts": [dimension_entry]}).model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )
    dimension_result = NLPClassifier(
        artifact_path=artifact_path,
        manifest_path=manifest_path,
    ).predict("flood")
    assert dimension_result.status is PredictionStatus.OFFLINE
    assert "coefficient" in dimension_result.warnings[0]

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["model_version"] = "unexpected-model-version"
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    version_entry = source_entry.model_copy(
        update={"sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest()}
    )
    manifest_path.write_text(
        manifest.model_copy(update={"artifacts": [version_entry]}).model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )
    version_result = NLPClassifier(
        artifact_path=artifact_path,
        manifest_path=manifest_path,
    ).predict("flood")
    assert version_result.status is PredictionStatus.OFFLINE
    assert "model version" in version_result.warnings[0]


def test_nlp_loader_rejects_url_and_unc_paths():
    with pytest.raises(ValueError, match="remote nlp_classifier artifacts"):
        load_nlp_artifact("https://example.invalid/nlp.json")
    with pytest.raises(ValueError, match="remote nlp_classifier artifacts"):
        load_nlp_artifact(r"\\example.invalid\share\nlp.json")


def test_metrics_capture_acceptance_gate_and_multilingual_subgroups():
    metrics_path = DEFAULT_NLP_CLASSIFIER_CONFIG.metrics_path
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["model_status"] == "EVALUATED"
    assert metrics["development_acceptance"]["accepted"] is False
    assert metrics["test"]["macro_f1"] >= DEFAULT_NLP_CLASSIFIER_CONFIG.min_macro_f1
    assert metrics["test"]["not_relevant_recall"] < DEFAULT_NLP_CLASSIFIER_CONFIG.min_not_relevant_recall
    assert set(metrics["test"]["subgroup_metrics"]) == {"en", "hi", "hinglish"}
    assert metrics["production_validation"] == "NOT_VALIDATED"


def test_dataset_audit_rejects_invalid_labels_and_train_test_leakage():
    records = load_csv(DEFAULT_NLP_CLASSIFIER_CONFIG.dataset_path)
    invalid = records[0].model_copy(update={"event_type": "INVENTED_LABEL"})
    invalid_audit = _audit_dataset([invalid, *records[1:]])
    assert invalid_audit["status"] == "INVALID"
    assert any("labels differ" in error for error in invalid_audit["errors"])

    train_record = next(record for record in records if record.split.value == "train")
    test_index = next(index for index, record in enumerate(records) if record.split.value == "test")
    leaked = records[test_index].model_copy(update={"text": train_record.text})
    leaked_records = list(records)
    leaked_records[test_index] = leaked
    leakage_audit = _audit_dataset(leaked_records)
    assert leakage_audit["status"] == "INVALID"
    assert leakage_audit["train_test_text_overlap"]


def test_small_language_subgroup_is_explicitly_insufficient():
    report = evaluate_nlp_predictions(
        ["URBAN_FLOOD", "RIVER_BREACH"],
        ["URBAN_FLOOD", "RIVER_BREACH"],
        ["RIVER_BREACH", "URBAN_FLOOD"],
        languages=["hi", "en"],
        minimum_subgroup_rows=2,
    )
    assert report.evaluation_status == "DATA_AVAILABLE"
    assert report.subgroup_metrics["hi"]["status"] == "INSUFFICIENT_DATA"
    assert report.subgroup_metrics["en"]["status"] == "INSUFFICIENT_DATA"
