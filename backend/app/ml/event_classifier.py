"""
INDRA Platform — Event-type classifier (layer 4)

Classifies a report's text into one of the four flood EventTypes or
NOT_RELEVANT.

    features   all-MiniLM-L6-v2 sentence embeddings (normalised, CPU), the same
               model instance dedup loads, so the process holds MiniLM once
    model      multinomial logistic regression or nearest cosine centroid,
               chosen by 5-fold CV macro-F1 on the train split only
    data       data/labelled/reports_v1.csv (synthetic — see its DATASHEET.md)

The artefact stores plain numpy weights, not a pickled sklearn estimator, so it
loads without depending on the sklearn version that trained it.

**Acceptance gate.** Training writes `accepted` into the metrics file, from the
test-split numbers:
    macro-F1 ≥ 0.75, NOT_RELEVANT recall ≥ 0.80, and at most 4 of the 72 flood
    rows predicted NOT_RELEVANT (dismissing a real flood is the costly error).
`classify()` returns None — the model is offline — when the artefact is
missing, the gate was not passed, or CLASSIFIER_ENABLED is false. It never
raises.

Nothing in the pipeline calls this yet (Day 4 session A measures it offline).
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger("indra.ml.event_classifier")

MODEL_VERSION = "event_classifier_v1"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CLASSES = ["URBAN_FLOOD", "RIVER_BREACH", "CLOUDBURST", "CYCLONE_INUNDATION", "NOT_RELEVANT"]
FLOOD_CLASSES = CLASSES[:4]

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / f"{MODEL_VERSION}.joblib"
METRICS_PATH = ARTIFACT_DIR / f"{MODEL_VERSION}.metrics.json"
DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "labelled" / "reports_v1.csv"

GATE_MACRO_F1 = 0.75
GATE_NOT_RELEVANT_RECALL = 0.80
GATE_MAX_FLOOD_DISMISSED = 4

LR_C_GRID = (0.1, 1.0, 10.0)
CV_FOLDS = 5
RANDOM_STATE = 42


# ── Features ───────────────────────────────────────────────────────────────────

def embed(texts: Sequence[str]) -> Optional[np.ndarray]:
    """Normalised MiniLM embeddings, float32, shape (n, 384). None if the model is unavailable."""
    from app.services.dedup import _get_embedding_model

    model = _get_embedding_model()
    if model is None:
        return None
    return model.encode(
        list(texts), normalize_embeddings=True, convert_to_numpy=True, batch_size=64
    ).astype(np.float32)


# ── The two candidate models, as pure numpy ────────────────────────────────────

def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def predict_proba(artifact: Dict[str, Any], X: np.ndarray) -> np.ndarray:
    """Class probabilities, columns in artifact['classes'] order."""
    X = X.astype(np.float64)
    if artifact["kind"] == "logistic_regression":
        return _softmax(X @ artifact["coef"].T + artifact["intercept"])
    if artifact["kind"] == "nearest_centroid":
        return _softmax((X @ artifact["centroids"].T) / artifact["temperature"])
    raise ValueError(f"unknown classifier kind {artifact['kind']!r}")


def _fit_logistic_regression(X: np.ndarray, y: np.ndarray, C: float) -> Dict[str, Any]:
    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression(
        C=C, class_weight="balanced", max_iter=2000, random_state=RANDOM_STATE
    )
    clf.fit(X.astype(np.float64), y)
    order = [list(clf.classes_).index(c) for c in CLASSES]
    return {
        "kind": "logistic_regression",
        "C": C,
        "classes": list(CLASSES),
        "coef": clf.coef_[order].copy(),
        "intercept": clf.intercept_[order].copy(),
    }


def _fit_nearest_centroid(X: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    centroids = np.stack([X[y == c].astype(np.float64).mean(axis=0) for c in CLASSES])
    centroids /= np.linalg.norm(centroids, axis=1, keepdims=True)
    # Temperature only shapes the probabilities; the argmax is the nearest centroid.
    return {
        "kind": "nearest_centroid",
        "classes": list(CLASSES),
        "centroids": centroids,
        "temperature": 0.05,
    }


def _fit(candidate: Dict[str, Any], X: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    if candidate["kind"] == "logistic_regression":
        return _fit_logistic_regression(X, y, candidate["C"])
    return _fit_nearest_centroid(X, y)


def _candidate_name(candidate: Dict[str, Any]) -> str:
    if candidate["kind"] == "logistic_regression":
        return f"logistic_regression(C={candidate['C']})"
    return "nearest_centroid(cosine)"


# ── Training and measurement ───────────────────────────────────────────────────

def load_dataset(path: Path = DATASET_PATH) -> List[Dict[str, str]]:
    import csv

    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def train_and_evaluate(dataset_path: Path = DATASET_PATH) -> Dict[str, Any]:
    """
    Select a model by CV on train, refit on all of train, evaluate once on test.
    Returns {"artifact": ..., "metrics": ..., "test_predictions": [...]}.
    """
    import sklearn
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_recall_fscore_support,
    )
    from sklearn.model_selection import StratifiedKFold

    rows = load_dataset(dataset_path)
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]

    X_train = embed([r["text"] for r in train])
    X_test = embed([r["text"] for r in test])
    if X_train is None or X_test is None:
        raise RuntimeError("MiniLM is unavailable; cannot train the event classifier")
    y_train = np.array([r["event_type"] for r in train])
    y_test = np.array([r["event_type"] for r in test])

    # 1. Model selection on train only.
    candidates = [{"kind": "logistic_regression", "C": c} for c in LR_C_GRID]
    candidates.append({"kind": "nearest_centroid"})
    folds = list(
        StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE).split(
            X_train, y_train
        )
    )
    cv_scores: Dict[str, float] = {}
    for cand in candidates:
        scores = []
        for tr, va in folds:
            art = _fit(cand, X_train[tr], y_train[tr])
            pred = np.array(CLASSES)[predict_proba(art, X_train[va]).argmax(axis=1)]
            scores.append(f1_score(y_train[va], pred, average="macro", labels=CLASSES))
        cv_scores[_candidate_name(cand)] = round(float(np.mean(scores)), 4)
    # Ties go to the earlier candidate (smaller C, then the centroid).
    best = max(candidates, key=lambda c: cv_scores[_candidate_name(c)])

    # 2. Refit on the whole train split, evaluate once on test.
    artifact = _fit(best, X_train, y_train)
    proba = predict_proba(artifact, X_test)
    y_pred = np.array(CLASSES)[proba.argmax(axis=1)]

    p, r, f, support = precision_recall_fscore_support(
        y_test, y_pred, labels=CLASSES, zero_division=0
    )
    per_class = {
        c: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
            "f1": round(float(f[i]), 4), "support": int(support[i])}
        for i, c in enumerate(CLASSES)
    }
    macro_f1 = round(float(f1_score(y_test, y_pred, average="macro", labels=CLASSES)), 4)
    accuracy = round(float(accuracy_score(y_test, y_pred)), 4)
    flood_rows = np.isin(y_test, FLOOD_CLASSES)
    flood_dismissed = int(((y_pred == "NOT_RELEVANT") & flood_rows).sum())
    majority = max(set(y_train), key=list(y_train).count)
    indic = np.array([r["lang"] in {"hi", "hinglish"} for r in test])
    by_lang = {
        lang: round(float(accuracy_score(y_test[m], y_pred[m])), 4)
        for lang, m in (
            ("en", ~indic),
            ("hi_or_hinglish", indic),
            ("hi", np.array([r["lang"] == "hi" for r in test])),
            ("hinglish", np.array([r["lang"] == "hinglish" for r in test])),
        )
        if m.any()
    }

    gate = {
        "macro_f1": {"value": macro_f1, "min": GATE_MACRO_F1, "pass": macro_f1 >= GATE_MACRO_F1},
        "not_relevant_recall": {
            "value": per_class["NOT_RELEVANT"]["recall"],
            "min": GATE_NOT_RELEVANT_RECALL,
            "pass": per_class["NOT_RELEVANT"]["recall"] >= GATE_NOT_RELEVANT_RECALL,
        },
        "flood_predicted_not_relevant": {
            "value": flood_dismissed,
            "of": int(flood_rows.sum()),
            "max": GATE_MAX_FLOOD_DISMISSED,
            "pass": flood_dismissed <= GATE_MAX_FLOOD_DISMISSED,
        },
    }
    accepted = all(g["pass"] for g in gate.values())

    dataset_sha = hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest()
    artifact.update({
        "model_version": MODEL_VERSION,
        "embedding_model": EMBEDDING_MODEL,
        "dataset_sha256": dataset_sha,
    })

    metrics = {
        "model_version": MODEL_VERSION,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_device": "cpu",
        "sklearn_version": sklearn.__version__,
        "dataset": "data/labelled/reports_v1.csv",
        "dataset_sha256": dataset_sha,
        "dataset_is_synthetic": True,
        "n_train": len(train),
        "n_test": len(test),
        "classes": CLASSES,
        "selection": {
            "method": f"StratifiedKFold({CV_FOLDS}, shuffle=True, random_state={RANDOM_STATE}) macro-F1 on train only",
            "cv_macro_f1": cv_scores,
            "chosen": _candidate_name(best),
        },
        "test": {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "majority_class_baseline_accuracy": round(float((y_test == majority).mean()), 4),
            "per_class": per_class,
            "confusion_matrix": {
                "rows_true_columns_predicted": CLASSES,
                "matrix": confusion_matrix(y_test, y_pred, labels=CLASSES).tolist(),
            },
            "accuracy_by_language": by_lang,
            "flood_rows_predicted_not_relevant": flood_dismissed,
        },
        "gate": gate,
        "accepted": accepted,
    }
    return {"artifact": artifact, "metrics": metrics, "test_predictions": y_pred.tolist()}


def save(result: Dict[str, Any], artifact_path: Path = ARTIFACT_PATH, metrics_path: Path = METRICS_PATH) -> None:
    import joblib

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(result["artifact"], artifact_path)
    metrics_path.write_text(json.dumps(result["metrics"], indent=2) + "\n", encoding="utf-8")


# ── Inference ──────────────────────────────────────────────────────────────────

_loaded: Optional[Dict[str, Any]] = None
_offline_reason: Optional[str] = None


def reset() -> None:
    """Forget the loaded artefact and any logged offline reason (tests, reloads)."""
    global _loaded, _offline_reason
    _loaded = None
    _offline_reason = None


def _go_offline(reason: str) -> None:
    global _offline_reason
    if _offline_reason != reason:
        logger.warning(f"Event classifier offline: {reason}")
        _offline_reason = reason


def offline_reason() -> Optional[str]:
    """Why classify() last returned None, or None if it is online."""
    return _offline_reason


def _load() -> Optional[Dict[str, Any]]:
    global _loaded
    if _loaded is not None:
        return _loaded
    if not ARTIFACT_PATH.exists() or not METRICS_PATH.exists():
        _go_offline(f"artefact missing ({ARTIFACT_PATH.name})")
        return None
    try:
        import joblib

        metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        artifact = joblib.load(ARTIFACT_PATH)
    except Exception as e:
        _go_offline(f"artefact unreadable ({type(e).__name__}: {e})")
        return None
    if not metrics.get("accepted"):
        _go_offline("model did not pass its acceptance gate (metrics accepted=false)")
        return None
    _loaded = artifact
    return _loaded


def classify(texts: Sequence[str]) -> Optional[List[Dict[str, Any]]]:
    """
    [{"label", "probs": {class: p}, "model_version"}] per text, or None when the
    classifier is offline. Never raises.
    """
    global _offline_reason
    try:
        if not get_settings().CLASSIFIER_ENABLED:
            _go_offline("disabled by CLASSIFIER_ENABLED=false")
            return None
        artifact = _load()
        if artifact is None:
            return None
        X = embed(texts)
        if X is None:
            _go_offline("embedding model unavailable")
            return None
        proba = predict_proba(artifact, X)
        _offline_reason = None
        classes = artifact["classes"]
        return [
            {
                "label": classes[int(row.argmax())],
                "probs": {c: float(row[i]) for i, c in enumerate(classes)},
                "model_version": artifact["model_version"],
            }
            for row in proba
        ]
    except Exception as e:
        _go_offline(f"inference failed ({type(e).__name__}: {e})")
        return None
