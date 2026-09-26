"""Reproducible local training command for the development NLP classifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.ml.components.duplicate_features import FrozenTfidfSpace, normalize_text
from app.ml.components.nlp_classifier import (
    NLPClassifierArtifact,
    NLPLinearClassifierState,
)
from app.ml.config import (
    DEFAULT_NLP_CLASSIFIER_CONFIG,
    NLPClassifierConfig,
    get_ml_config,
    local_only_path,
)
from app.ml.contracts import ArtifactManifest, ArtifactMetadata, ArtifactPolicyStatus
from app.ml.data.loaders import load_csv
from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH, DatasetComponent
from app.ml.data.schemas import DatasetRecord
from app.ml.evaluation.evaluate import evaluate_nlp_predictions
from app.ml.training.dataset_gate import require_training_dataset

EXPECTED_CLASSES = {
    "URBAN_FLOOD",
    "RIVER_BREACH",
    "CLOUDBURST",
    "CYCLONE_INUNDATION",
    "NOT_RELEVANT",
}
FLOOD_CLASSES = EXPECTED_CLASSES - {"NOT_RELEVANT"}
DATASET_VERSION = "reports-v1-development-synthetic"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_records(records: Sequence[DatasetRecord]) -> bytes:
    payload = [
        record.model_dump(mode="json")
        for record in sorted(records, key=lambda item: item.record_id)
    ]
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _audit_dataset(records: Sequence[DatasetRecord]) -> dict[str, Any]:
    errors: list[str] = []
    labels = {record.event_type for record in records}
    if None in labels or "" in labels:
        errors.append("missing event_type label")
    actual_classes = {label for label in labels if label}
    if actual_classes != EXPECTED_CLASSES:
        errors.append(
            f"dataset labels differ from audited development classes: {sorted(actual_classes)}"
        )
    empty_records = [
        record.record_id for record in records if not normalize_text(record.text)
    ]
    if empty_records:
        errors.append(f"empty text records: {empty_records}")

    normalized_text_groups: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in records:
        normalized_text_groups[normalize_text(record.text)].append(record)
    label_conflicts = [
        [item.record_id for item in group]
        for group in normalized_text_groups.values()
        if len({item.event_type for item in group}) > 1
    ]
    train_texts = {
        normalize_text(record.text)
        for record in records
        if record.split and record.split.value == "train"
    }
    test_texts = {
        normalize_text(record.text)
        for record in records
        if record.split and record.split.value == "test"
    }
    train_test_overlap = sorted(train_texts & test_texts)
    if label_conflicts:
        errors.append("normalized text has conflicting labels")
    if train_test_overlap:
        errors.append("normalized text overlaps between train and test")
    if any(record.split is None for record in records):
        errors.append("every record must have an explicit train/test split")
    return {
        "status": "VALID" if not errors else "INVALID",
        "errors": errors,
        "actual_classes": sorted(actual_classes),
        "empty_records": empty_records,
        "label_conflict_groups": label_conflicts,
        "train_test_text_overlap": train_test_overlap,
        "dataset_status": "DEVELOPMENT_ONLY / SYNTHETIC / NOT PRODUCTION VALIDATION",
    }


def _fit_vectorizers(texts: Sequence[str], config: NLPClassifierConfig):
    from sklearn.feature_extraction.text import TfidfVectorizer

    normalized = [normalize_text(text) for text in texts]
    char_vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=config.char_ngram_range,
        sublinear_tf=config.sublinear_tf,
        lowercase=False,
        norm=config.norm,
    )
    word_vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=config.word_ngram_range,
        sublinear_tf=config.sublinear_tf,
        lowercase=False,
        token_pattern=r"(?u)\b\w+\b",
        norm=config.norm,
    )
    char_vectorizer.fit(normalized)
    word_vectorizer.fit(normalized)
    return char_vectorizer, word_vectorizer


def _transform(vectorizers, texts: Sequence[str]):
    from scipy.sparse import hstack

    normalized = [normalize_text(text) for text in texts]
    char_vectorizer, word_vectorizer = vectorizers
    return hstack(
        [char_vectorizer.transform(normalized), word_vectorizer.transform(normalized)],
        format="csr",
    )


def _frozen_space(
    vectorizer, analyzer: str, ngram_range: tuple[int, int]
) -> FrozenTfidfSpace:
    vocabulary = {term: int(index) for term, index in vectorizer.vocabulary_.items()}
    return FrozenTfidfSpace(
        analyzer=analyzer,
        ngram_range=ngram_range,
        vocabulary=vocabulary,
        idf=[float(value) for value in vectorizer.idf_],
        vectorizer_config={
            "sublinear_tf": True,
            "norm": "l2",
            "lowercase": False,
            "token_pattern": r"(?u)\b\w+\b" if analyzer == "word" else None,
            "local_only": True,
        },
    )


def _fit_classifier(
    features, labels: Sequence[str], config: NLPClassifierConfig, c_value: float
):
    from sklearn.linear_model import LogisticRegression

    classifier = LogisticRegression(
        C=c_value,
        max_iter=config.max_iterations,
        random_state=config.random_state,
        solver="lbfgs",
    )
    classifier.fit(features, labels)
    return classifier


def _cross_validate_c(
    texts: Sequence[str],
    labels: Sequence[str],
    config: NLPClassifierConfig,
    classes: Sequence[str],
) -> dict[str, Any]:
    from sklearn.model_selection import StratifiedKFold

    labels_array = np.asarray(labels)
    folds = StratifiedKFold(
        n_splits=config.cross_validation_folds,
        shuffle=True,
        random_state=config.random_state,
    )
    scores: dict[str, list[float]] = {
        str(value): [] for value in config.regularization_grid
    }
    for train_indexes, validation_indexes in folds.split(texts, labels_array):
        fold_train_texts = [texts[index] for index in train_indexes]
        fold_validation_texts = [texts[index] for index in validation_indexes]
        vectorizers = _fit_vectorizers(fold_train_texts, config)
        fold_train_features = _transform(vectorizers, fold_train_texts)
        fold_validation_features = _transform(vectorizers, fold_validation_texts)
        fold_train_labels = labels_array[train_indexes]
        fold_validation_labels = labels_array[validation_indexes]
        for c_value in config.regularization_grid:
            classifier = _fit_classifier(
                fold_train_features, fold_train_labels, config, c_value
            )
            predictions = classifier.predict(fold_validation_features).tolist()
            report = evaluate_nlp_predictions(
                fold_validation_labels.tolist(),
                predictions,
                classes,
                minimum_subgroup_rows=config.minimum_subgroup_rows,
            )
            if report.macro_f1 is not None:
                scores[str(c_value)].append(report.macro_f1)
    means = {
        key: (float(np.mean(values)) if values else None)
        for key, values in scores.items()
    }
    best_c = next(
        value
        for value in config.regularization_grid
        if means[str(value)]
        == max(score for score in means.values() if score is not None)
    )
    return {
        "method": f"StratifiedKFold({config.cross_validation_folds}, shuffle=True, random_state={config.random_state}) on training rows only",
        "macro_f1_by_c": means,
        "chosen_c": best_c,
    }


def _register_artifact(
    artifact_path: Path,
    dataset_hash: str,
    config: NLPClassifierConfig,
    training_timestamp: datetime,
    manifest_path: Path,
) -> None:
    artifact_hash = _sha256_bytes(artifact_path.read_bytes())
    import scipy
    import sklearn

    metadata = ArtifactMetadata(
        artifact_name=artifact_path.name,
        artifact_version=config.model_version,
        sha256=artifact_hash,
        training_dataset_hash=dataset_hash,
        feature_version=config.feature_version,
        preprocessing_version=config.preprocessing_version,
        training_timestamp=training_timestamp,
        random_seed=config.random_state,
        framework_versions={
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "scipy": scipy.__version__,
        },
        intended_component="nlp_classifier",
        policy_status=ArtifactPolicyStatus.COMPLIANT,
    )
    if manifest_path.exists():
        manifest = ArtifactManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    else:
        manifest = ArtifactManifest(
            manifest_version="1.0",
            schema_version="1.0",
            policy_status="SCAFFOLD_ONLY",
            runtime_downloads_allowed=False,
        )
    artifacts = [
        item
        for item in manifest.artifacts
        if item.artifact_name != metadata.artifact_name
    ]
    artifacts.append(metadata)
    updated = manifest.model_copy(update={"artifacts": artifacts})
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")


def train_nlp_classifier(
    dataset_path: Path | None = None,
    *,
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    registry_path: Path | None = None,
    config: NLPClassifierConfig | None = None,
    artifact_path: Path | None = None,
    metrics_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Train, evaluate, serialize, and register the local development model."""

    config = config or DEFAULT_NLP_CLASSIFIER_CONFIG
    authorization = require_training_dataset(
        dataset_id or "<UNREGISTERED>",
        DatasetComponent.NLP,
        dataset_version=dataset_version,
        registry_path=registry_path or DEFAULT_DATASET_REGISTRY_PATH,
        supplied_path=dataset_path,
    )
    dataset_path = local_only_path(
        authorization.resolved_path,
        description="NLP dataset paths",
    )
    artifact_path = local_only_path(
        artifact_path or config.artifact_path,
        description="NLP artifact paths",
    )
    metrics_path = local_only_path(
        metrics_path or config.metrics_path,
        description="NLP metrics paths",
    )
    manifest_path = local_only_path(
        manifest_path or get_ml_config().artifact_manifest_path,
        description="artifact manifests",
    )
    dataset_bytes = dataset_path.read_bytes()
    dataset_hash = _sha256_bytes(dataset_bytes)
    records = load_csv(dataset_path)
    audit = _audit_dataset(records)
    if audit["status"] != "VALID":
        raise ValueError(
            "NLP training data audit failed: " + json.dumps(audit, sort_keys=True)
        )
    audit["dataset_status"] = (
        "REGISTRY_APPROVED_LOCAL_DATASET / NOT_PRODUCTION_VALIDATED"
    )

    classes = audit["actual_classes"]
    train_records = [
        record for record in records if record.split and record.split.value == "train"
    ]
    test_records = [
        record for record in records if record.split and record.split.value == "test"
    ]
    if not train_records or not test_records:
        raise ValueError("explicit train and test rows are required")
    train_texts = [record.text for record in train_records]
    test_texts = [record.text for record in test_records]
    train_labels = [record.event_type for record in train_records]
    test_labels = [record.event_type for record in test_records]
    if any(label is None for label in train_labels + test_labels):
        raise ValueError("all training and test rows must have labels")

    selection = _cross_validate_c(train_texts, train_labels, config, classes)
    vectorizers = _fit_vectorizers(train_texts, config)
    train_features = _transform(vectorizers, train_texts)
    test_features = _transform(vectorizers, test_texts)
    classifier = _fit_classifier(
        train_features, train_labels, config, selection["chosen_c"]
    )
    predictions = classifier.predict(test_features).tolist()
    evaluation = evaluate_nlp_predictions(
        test_labels,
        predictions,
        classes,
        record_ids=[record.record_id for record in test_records],
        texts=test_texts,
        languages=[record.language or "unknown" for record in test_records],
        minimum_subgroup_rows=config.minimum_subgroup_rows,
    )
    flood_dismissed = sum(
        truth in FLOOD_CLASSES and prediction == "NOT_RELEVANT"
        for truth, prediction in zip(test_labels, predictions)
    )
    gate = {
        "macro_f1": {
            "value": evaluation.macro_f1,
            "minimum": config.min_macro_f1,
            "pass": evaluation.macro_f1 is not None
            and evaluation.macro_f1 >= config.min_macro_f1,
        },
        "not_relevant_recall": {
            "value": evaluation.not_relevant_recall,
            "minimum": config.min_not_relevant_recall,
            "pass": evaluation.not_relevant_recall is not None
            and evaluation.not_relevant_recall >= config.min_not_relevant_recall,
        },
        "flood_to_not_relevant_errors": {
            "value": flood_dismissed,
            "maximum": config.max_flood_to_not_relevant_errors,
            "pass": flood_dismissed <= config.max_flood_to_not_relevant_errors,
        },
    }
    development_accepted = all(item["pass"] for item in gate.values())
    model_status = "DEVELOPMENT_ACCEPTED" if development_accepted else "EVALUATED"
    training_timestamp = datetime.now(timezone.utc)
    training_split_hash = _sha256_bytes(_canonical_records(train_records))
    import sklearn

    artifact = NLPClassifierArtifact(
        artifact_version="nlp-classifier-artifact-v1",
        model_version=config.model_version,
        model_status=model_status,
        feature_version=config.feature_version,
        preprocessing_version=config.preprocessing_version,
        classes=classes,
        char_space=_frozen_space(vectorizers[0], "char", config.char_ngram_range),
        word_space=_frozen_space(vectorizers[1], "word", config.word_ngram_range),
        classifier=NLPLinearClassifierState(
            regularization_c=selection["chosen_c"],
            max_iterations=config.max_iterations,
            random_state=config.random_state,
            classes=list(classifier.classes_),
            coefficients=classifier.coef_.tolist(),
            intercept=classifier.intercept_.tolist(),
        ),
        n_features=int(train_features.shape[1]),
        provenance={
            "dataset_identifier": authorization.dataset_id,
            "dataset_version": authorization.dataset_version,
            "dataset_sha256": dataset_hash,
            "training_split_sha256": training_split_hash,
            "training_timestamp": training_timestamp.isoformat(),
            "dataset_status": audit["dataset_status"],
            "python_version": platform.python_version(),
            "scikit_learn_version": sklearn.__version__,
            "numpy_version": np.__version__,
            "random_state": config.random_state,
            "classifier_configuration": {
                "regularization_c": selection["chosen_c"],
                "max_iterations": config.max_iterations,
                "solver": "lbfgs",
                "cross_validation": selection["method"],
            },
            "class_distribution": dict(sorted(Counter(train_labels).items())),
        },
    )
    metrics = {
        "model_version": config.model_version,
        "model_status": model_status,
        "dataset_version": authorization.dataset_version,
        "dataset_status": audit["dataset_status"],
        "dataset_sha256": dataset_hash,
        "training_split_sha256": training_split_hash,
        "preprocessing_version": config.preprocessing_version,
        "feature_version": config.feature_version,
        "random_state": config.random_state,
        "n_train": len(train_records),
        "n_test": len(test_records),
        "classes": classes,
        "training_class_distribution": dict(sorted(Counter(train_labels).items())),
        "selection": selection,
        "leakage_audit": audit,
        "test": evaluation.model_dump(mode="json"),
        "flood_to_not_relevant_errors": flood_dismissed,
        "acceptance_gate": gate,
        "development_acceptance": {
            "accepted": development_accepted,
            "status": model_status,
        },
        "production_validation": "NOT_VALIDATED",
        "production_validated": False,
        "legacy_reference": "LEGACY_RECORDED_METRICS / NOT REPRODUCED IN CURRENT RUN",
    }

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        artifact.model_dump_json(indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _register_artifact(
        artifact_path, dataset_hash, config, training_timestamp, manifest_path
    )
    return {
        "artifact_path": str(artifact_path),
        "metrics_path": str(metrics_path),
        "manifest_path": str(manifest_path),
        "artifact_sha256": _sha256_bytes(artifact_path.read_bytes()),
        "metrics": metrics,
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Train the local development NLP classifier"
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version")
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    result = train_nlp_classifier(
        args.dataset,
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
        registry_path=args.registry,
        artifact_path=args.artifact,
        metrics_path=args.metrics,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "metrics"}, indent=2
        )
    )
    print(json.dumps(result["metrics"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
