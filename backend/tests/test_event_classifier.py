"""
Day 4 T8 — the event-type classifier is reproducible, measured, and offline
unless it passed its gate.

Unit level (no database). Tests that embed text need MiniLM and are skipped
without it.
"""

import json
import logging
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from app.ml import event_classifier as ec
from app.ml.data.nlp_annotations import SEALED_SOURCE_DATASET_SHA256
from tests.conftest import requires_embeddings


@pytest.fixture(autouse=True)
def fresh_state():
    ec.reset()
    yield
    ec.reset()


@pytest.fixture
def committed_metrics():
    return json.loads(ec.METRICS_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def accepted_copy(tmp_path, monkeypatch, committed_metrics):
    """The committed artefact, with a metrics file that says accepted=true."""
    art = tmp_path / ec.ARTIFACT_PATH.name
    met = tmp_path / ec.METRICS_PATH.name
    shutil.copy(ec.ARTIFACT_PATH, art)
    met.write_text(json.dumps(dict(committed_metrics, accepted=True)), encoding="utf-8")
    monkeypatch.setattr(ec, "ARTIFACT_PATH", art)
    monkeypatch.setattr(ec, "METRICS_PATH", met)
    return art, met


# ── The committed measurement ──────────────────────────────────────────────────

def test_metrics_file_records_the_measurement(committed_metrics):
    m = committed_metrics
    assert m["n_train"] == 210 and m["n_test"] == 90
    assert m["dataset_is_synthetic"] is True
    assert m["test"]["majority_class_baseline_accuracy"] == 0.2
    matrix = m["test"]["confusion_matrix"]["matrix"]
    assert len(matrix) == 5 and all(len(row) == 5 for row in matrix)
    assert all(sum(row) == 18 for row in matrix)
    assert set(m["selection"]["cv_macro_f1"]) == {
        "logistic_regression(C=0.1)", "logistic_regression(C=1.0)",
        "logistic_regression(C=10.0)", "nearest_centroid(cosine)",
    }
    assert set(m["gate"]) == {"macro_f1", "not_relevant_recall", "flood_predicted_not_relevant"}
    assert m["accepted"] == all(g["pass"] for g in m["gate"].values())


def test_committed_metrics_match_the_dataset_file(committed_metrics):
    import hashlib

    raw = ec.DATASET_PATH.read_bytes()
    # The sealed NLP registry hashes the exact CRLF checkout; the older metrics
    # recorded the Git LF blob. Verify both without changing either artifact.
    assert hashlib.sha256(raw).hexdigest() == SEALED_SOURCE_DATASET_SHA256
    assert committed_metrics["dataset_sha256"] == hashlib.sha256(
        raw.replace(b"\r\n", b"\n")
    ).hexdigest()


def test_artefact_is_small():
    assert ec.ARTIFACT_PATH.stat().st_size < 1_000_000


@requires_embeddings
def test_training_twice_is_identical_and_reproduces_the_committed_numbers(committed_metrics):
    first = ec.train_and_evaluate()
    second = ec.train_and_evaluate()

    a, b = first["artifact"], second["artifact"]
    assert a["kind"] == b["kind"]
    if a["kind"] == "logistic_regression":
        assert np.array_equal(a["coef"], b["coef"])
        assert np.array_equal(a["intercept"], b["intercept"])
    else:
        assert np.array_equal(a["centroids"], b["centroids"])
    assert first["test_predictions"] == second["test_predictions"]
    assert len(first["test_predictions"]) == 90
    assert first["metrics"]["test"] == committed_metrics["test"]
    assert first["metrics"]["accepted"] == committed_metrics["accepted"]


# ── Inference ──────────────────────────────────────────────────────────────────

@requires_embeddings
def test_classify_is_deterministic_and_probabilities_sum_to_one(accepted_copy):
    text = ["waist-deep water on Boring Road"]
    one = ec.classify(text)
    two = ec.classify(text)

    assert one == two
    probs = one[0]["probs"]
    assert set(probs) == set(ec.CLASSES)
    assert abs(sum(probs.values()) - 1.0) < 1e-6
    assert one[0]["label"] == max(probs, key=probs.get)
    assert one[0]["model_version"] == "event_classifier_v1"
    assert ec.offline_reason() is None


def test_unaccepted_model_is_offline(committed_metrics, monkeypatch, tmp_path):
    met = tmp_path / "m.json"
    met.write_text(json.dumps(dict(committed_metrics, accepted=False)), encoding="utf-8")
    monkeypatch.setattr(ec, "METRICS_PATH", met)

    assert ec.classify(["knee-deep water"]) is None
    assert "acceptance gate" in ec.offline_reason()


def test_missing_artefact_is_offline_with_one_warning(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ec, "ARTIFACT_PATH", tmp_path / "missing.joblib")
    caplog.set_level(logging.WARNING, logger="indra.ml.event_classifier")

    assert ec.classify(["knee-deep water"]) is None
    assert ec.classify(["knee-deep water"]) is None

    warnings = [r for r in caplog.records if r.name == "indra.ml.event_classifier"]
    assert len(warnings) == 1
    assert "artefact missing" in warnings[0].getMessage()


def test_kill_switch_is_offline(accepted_copy, monkeypatch):
    monkeypatch.setattr(ec, "get_settings", lambda: SimpleNamespace(CLASSIFIER_ENABLED=False))

    assert ec.classify(["knee-deep water"]) is None
    assert "CLASSIFIER_ENABLED" in ec.offline_reason()
