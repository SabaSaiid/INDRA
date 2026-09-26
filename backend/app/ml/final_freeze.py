"""Phase 24 forensic freeze for the six-component INDRA AI/ML subsystem.

This module is deliberately read-only with respect to every Phase 18--23
artifact, dataset, configuration, and protected-test receipt.  It loads and
audits existing evidence, performs deterministic non-test inference probes,
and writes one new final-freeze manifest.  It never trains, tunes, calibrates,
or invokes a protected evaluation function.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import textwrap
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch
from uuid import UUID

import numpy as np
from scipy.stats import rankdata

from app.ml.config import NLPClassifierConfig
from app.ml.contracts import CandidateReport, ImageInput, ReportInput
from app.ml.data.synthetic_anomaly.generator import (
    SyntheticAnomalyMetadata,
    SyntheticAnomalyModelRecord,
)
from app.ml.data.synthetic_credibility.generator import (
    SyntheticCredibilityDetectorInput,
)
from app.ml.data.synthetic_image.generator import SyntheticImageModelRecord
from app.ml.models.anomaly_window_model import (
    FEATURE_NAMES,
    extract_window_feature_vector,
    feature_matrix,
    score_records,
)
from app.ml.release_gate import scan_new_ml_policy

ML_ROOT: Final[Path] = Path(__file__).resolve().parent
BACKEND_ROOT: Final[Path] = ML_ROOT.parents[1]
REPOSITORY_ROOT: Final[Path] = BACKEND_ROOT.parent
ARTIFACT_ROOT: Final[Path] = ML_ROOT / "artifacts"
DATA_ROOT: Final[Path] = REPOSITORY_ROOT / "data" / "labelled"
DEFAULT_FINAL_FREEZE_PATH: Final[Path] = (
    ARTIFACT_ROOT / "ai_ml_final_freeze_manifest.json"
)
FREEZE_VERSION: Final[str] = "ai-ml-final-freeze-v1"
VALIDATION_STATUS: Final[str] = "SYNTHETIC_DEVELOPMENT_VALIDATED"
PRODUCTION_VALIDATION: Final[str] = "NOT_VALIDATED"
DIRECT_SCENARIO_AUC_THRESHOLD: Final[float] = 0.995
EXPECTED_SHARED_MANIFEST_SHA256: Final[str] = (
    "f19b7b62db6eadc84d80b3f034f7ec664ce6f1e75feb5a16a4aa79ecb347871d"
)


COMPONENT_SPECS: Final[dict[str, dict[str, Any]]] = {
    "NLP": {
        "intended_component": "nlp_classifier",
        "artifact_name": "nlp_classifier_v3.json",
        "artifact_version": "nlp-classifier-v3-synthetic-development",
        "artifact_sha256": "7e1d8e6eacf45826100595fd880efc5e92b08fd157a00d95ac3e391d5035bbca",
        "receipt_name": "nlp_classifier_v3.final_test_receipt.json",
        "receipt_sha256": "ec76d9276f790a266bb04aee362d01f0709df50bb4e36467dccf2bb964d2072b",
        "development_manifest": "nlp_classifier_v3.development_manifest.json",
        "dataset_sha256": "6a4b5157f4fa67a5933ebb230cf6a73539647e130fe224d9aa0fdb397e904f76",
        "dataset_type": "PROJECT_AUTHORED_SYNTHETIC_DEVELOPMENT_ONLY",
        "model_type": "LOCAL_CHARACTER_WORD_TFIDF_LOGISTIC_REGRESSION",
        "training_source": "PROJECT_AUTHORED_SYNTHETIC",
        "implementation_status": "FROZEN_DEVELOPMENT_IMPLEMENTATION",
        "known_limitations": [
            "Synthetic multilingual templates do not establish field-language performance.",
            "Validation calibration is not field calibration.",
            "The Phase 18 artifact is opt-in and is not integrated into the live backend.",
        ],
    },
    "DUPLICATE": {
        "intended_component": "duplicate_matcher",
        "artifact_name": "duplicate_matcher_v1.json",
        "artifact_version": "duplicate-matcher-v1-synthetic-development",
        "artifact_sha256": "85c9e77419f09ddfa340e69fa4249ce3ddc43509920356aa2ba03df73cbe745b",
        "receipt_name": "duplicate_v1_final_test_receipt.json",
        "receipt_sha256": "4b97fa5b617c0bf2c93383a8d031be5a9fd6dcd5c08c9b2c229cec9d57ead405",
        "development_manifest": "duplicate_v1.development_manifest.json",
        "dataset_sha256": "ad664bf69755a141f44c82615e7653f28ae5abadc028cb50d6566ee2f13e7231",
        "dataset_type": "PROJECT_AUTHORED_SYNTHETIC_DEVELOPMENT_ONLY",
        "model_type": "DETERMINISTIC_WEIGHTED_SIMILARITY_MATCHER",
        "training_source": "PROJECT_AUTHORED_SYNTHETIC_FEATURE_FIT",
        "implementation_status": "FROZEN_DEVELOPMENT_IMPLEMENTATION",
        "companion_artifacts": {
            "duplicate_feature_state_v2.json": (
                "d2074a87c93fffb30b9be752d7c6208fc363fe41092625f5e55565e7a28aa731"
            )
        },
        "known_limitations": [
            "Similarity evidence is not a calibrated field probability.",
            "Synthetic pairs do not establish deployment-population precision or recall.",
            "The live backend still uses a separate legacy embedding deduplicator.",
        ],
    },
    "EVENT": {
        "intended_component": "event_detector",
        "artifact_name": "event_grouping_v1.json",
        "artifact_version": "event-grouping-v1-synthetic-development",
        "artifact_sha256": "10c8fcb331d65333bb67c567d9821ca0c96cdbe376c7cf6dfc840abd19b6f973",
        "receipt_name": "event_grouping_v1_final_test_receipt.json",
        "receipt_sha256": "c6ae828fc435275f031175f47500beccada675fb5ad7bd5559c6de8c58e1d913",
        "development_manifest": "event_grouping_v1.development_manifest.json",
        "dataset_sha256": "127a506f8deba172140dd33b71a14b84b629ce325c959ba8b9d4c04635f48f0f",
        "dataset_type": "PROJECT_AUTHORED_SYNTHETIC_DEVELOPMENT_ONLY",
        "model_type": "DETERMINISTIC_HEURISTIC_EVENT_GROUPING_CONFIGURATION",
        "training_source": "NO_LEARNED_MODEL_VALIDATION_SELECTED_CONFIGURATION",
        "implementation_status": "FROZEN_HEURISTIC_DEVELOPMENT_IMPLEMENTATION",
        "known_limitations": [
            "Event grouping remains heuristic and its evidence score is not a probability.",
            "Phase 20 held out canonical event identities but did not establish template or parameter-family separation.",
            "A single report creates only a CANDIDATE and cannot confirm an event.",
        ],
    },
    "CREDIBILITY": {
        "intended_component": "fake_detector",
        "artifact_name": "credibility_v1.json",
        "artifact_version": "credibility-v1-synthetic-development",
        "artifact_sha256": "8bbd16727be2ba639e031db37a84f0ca92a2a14220fd1819e45dbf689bab7052",
        "receipt_name": "credibility_v1_final_test_receipt.json",
        "receipt_sha256": "d9f3dc044bf57722180ee70fd459f7208233c3e3cd12bac5b35abe557e4c39dc",
        "development_manifest": "credibility_v1.development_manifest.json",
        "dataset_sha256": "1ceab01ae23d7c99eec3f98a0bbad479ae5b66b63f56298a5d713d5218140a87",
        "dataset_type": "PROJECT_AUTHORED_SYNTHETIC_DEVELOPMENT_ONLY",
        "model_type": "INTERPRETABLE_LOCAL_LOGISTIC_REGRESSION_WITH_ABSTENTION",
        "training_source": "PROJECT_AUTHORED_SYNTHETIC",
        "implementation_status": "FROZEN_DEVELOPMENT_IMPLEMENTATION",
        "known_limitations": [
            "AUTHENTIC, MISLEADING, and UNCERTAIN are modeled evidence states, not ground truth about a report.",
            "Perfect synthetic holdout performance does not establish universal misinformation detection.",
            "No field-labelled credibility validation exists.",
        ],
    },
    "IMAGE": {
        "intended_component": "image_analyzer",
        "artifact_name": "image_model_v1.pt",
        "artifact_version": "image-model-v1-synthetic-development",
        "artifact_sha256": "6daf6e9dc41783c7d30b19b5c0cc2a0fb20871733f9ab714a7b99552424f9248",
        "receipt_name": "image_model_v1_final_test_receipt.json",
        "receipt_sha256": "4627f84a82282090caa22b75acbfdbd585b92720fe1a1ff7824dbf830e3385ad",
        "development_manifest": "image_model_v1.development_manifest.json",
        "dataset_sha256": "8cc2da10c57accbeff09a166221eb0b3f1df80e431c1810aad095eda0df972ba",
        "dataset_type": "PROJECT_AUTHORED_SYNTHETIC_RENDERED_DEVELOPMENT_ONLY",
        "model_type": "SCRATCH_CNN_V2_MULTI_LABEL",
        "training_source": "PROJECT_AUTHORED_SYNTHETIC_SCRATCH_INITIALIZED",
        "implementation_status": "FROZEN_DEVELOPMENT_IMPLEMENTATION",
        "known_limitations": [
            "Multi-label synthetic-render performance does not establish real-photograph generalization.",
            "Validation temperature scaling is not field calibration.",
            "The scratch CNN is opt-in and is not integrated into the live backend.",
        ],
    },
    "ANOMALY": {
        "intended_component": "anomaly_detector",
        "artifact_name": "anomaly_model_v1.json",
        "artifact_version": "anomaly-model-v1-synthetic-development",
        "artifact_sha256": "3fdc354af80224bfe11dc23b6c5fccd629f44daf45efb9220a4cd9406004eceb",
        "receipt_name": "anomaly_model_v1_final_test_receipt.json",
        "receipt_sha256": "8facd1be74825e86f79ccf3f72aef2f1c116176c406dbc96015f97b05685004a",
        "development_manifest": "anomaly_model_v1.development_manifest.json",
        "dataset_sha256": "818b82a3c91a2e263e3e2dd684c434f7072a8415135411f982b027d80f9f0546",
        "dataset_type": "PROJECT_AUTHORED_SYNTHETIC_TEMPORAL_WINDOWS_DEVELOPMENT_ONLY",
        "model_type": "STATISTICAL_BASELINE_PLUS_LOCAL_SCRATCH_DUAL_LOGISTIC",
        "training_source": "PROJECT_AUTHORED_SYNTHETIC",
        "implementation_status": "FROZEN_DEVELOPMENT_IMPLEMENTATION",
        "known_limitations": [
            "Synthetic feature separability does not establish field anomaly performance.",
            "DATA_QUALITY_ANOMALY and WEATHER_BEHAVIOR_ANOMALY scores are separate development scores, not field probabilities.",
            "The learned artifact is opt-in; the live framework retains the statistical baseline.",
        ],
    },
}


QUALITY_PATHS: Final[dict[str, Path]] = {
    "NLP": DATA_ROOT / "nlp/synthetic_v1/synthetic_nlp_dataset_report.json",
    "DUPLICATE": (
        DATA_ROOT / "duplicates/synthetic_v1/synthetic_duplicate_quality_report.json"
    ),
    "EVENT": DATA_ROOT / "events/synthetic_v1/synthetic_event_quality_report.json",
    "CREDIBILITY": (
        DATA_ROOT / "credibility/synthetic_v1/synthetic_credibility_quality_report.json"
    ),
    "IMAGE": DATA_ROOT / "image/synthetic_v1/quality_report.json",
    "ANOMALY": DATA_ROOT / "anomaly/synthetic_v1/quality_report.json",
}


DATASET_MANIFEST_PATHS: Final[dict[str, Path]] = {
    "NLP": DATA_ROOT / "nlp/synthetic_v1/synthetic_nlp_dataset_manifest.json",
    "DUPLICATE": (
        DATA_ROOT / "duplicates/synthetic_v1/synthetic_duplicate_dataset_manifest.json"
    ),
    "EVENT": DATA_ROOT / "events/synthetic_v1/synthetic_event_dataset_manifest.json",
    "CREDIBILITY": (
        DATA_ROOT
        / "credibility/synthetic_v1/synthetic_credibility_dataset_manifest.json"
    ),
    "IMAGE": DATA_ROOT / "image/synthetic_v1/manifest.json",
    "ANOMALY": DATA_ROOT / "anomaly/synthetic_v1/manifest.json",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _first_jsonl_line(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return line
    raise ValueError(f"JSONL file is empty: {path}")


def _status(passed: bool, evidence: str) -> dict[str, Any]:
    return {"status": "PASS" if passed else "FAIL", "evidence": evidence}


def audit_frozen_hashes() -> dict[str, Any]:
    """Verify all primary artifacts, companion state, receipts, and datasets."""

    shared_manifest_path = ARTIFACT_ROOT / "manifest.json"
    shared_hash = file_sha256(shared_manifest_path)
    manifest = _read_json(shared_manifest_path)
    rows: dict[str, Any] = {}
    for component, spec in COMPONENT_SPECS.items():
        artifact_path = ARTIFACT_ROOT / spec["artifact_name"]
        receipt_path = ARTIFACT_ROOT / spec["receipt_name"]
        development_path = ARTIFACT_ROOT / spec["development_manifest"]
        quality_path = QUALITY_PATHS[component]
        dataset_manifest_path = DATASET_MANIFEST_PATHS[component]
        artifact_hash = file_sha256(artifact_path)
        receipt_hash = file_sha256(receipt_path)
        quality = _read_json(quality_path)
        dataset_manifest = _read_json(dataset_manifest_path)
        quality_dataset_hash = quality.get(
            "dataset_sha256", quality.get("dataset_hash")
        )
        dataset_manifest_hash = dataset_manifest.get(
            "dataset_sha256", dataset_manifest.get("dataset_hash")
        )
        manifest_entries = [
            item
            for item in manifest["artifacts"]
            if item["artifact_name"] == spec["artifact_name"]
            and item["intended_component"] == spec["intended_component"]
        ]
        manifest_entry = manifest_entries[0] if len(manifest_entries) == 1 else None
        companion_results: dict[str, Any] = {}
        for name, expected_hash in spec.get("companion_artifacts", {}).items():
            actual_hash = file_sha256(ARTIFACT_ROOT / name)
            companion_results[name] = {
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "status": "PASS" if actual_hash == expected_hash else "FAIL",
            }
        dataset_sources = {
            "component_spec": spec["dataset_sha256"],
            "quality_report": quality_dataset_hash,
            "dataset_manifest": dataset_manifest_hash,
            "artifact_manifest": (
                manifest_entry["training_dataset_hash"] if manifest_entry else None
            ),
        }
        # Older quality-report schemas (notably Phase 23 anomaly) record
        # validity and leakage evidence but do not repeat the dataset hash.
        # Require every hash that is actually present to agree, while still
        # requiring the dataset manifest and shared artifact manifest below.
        present_dataset_hashes = {
            value for value in dataset_sources.values() if value is not None
        }
        dataset_hash_pass = (
            present_dataset_hashes == {spec["dataset_sha256"]}
            and dataset_manifest_hash == spec["dataset_sha256"]
            and bool(manifest_entry)
        )
        checks = {
            "artifact_hash": artifact_hash == spec["artifact_sha256"],
            "receipt_hash": receipt_hash == spec["receipt_sha256"],
            "shared_manifest_entry": bool(
                manifest_entry
                and manifest_entry["sha256"] == spec["artifact_sha256"]
                and manifest_entry["artifact_version"] == spec["artifact_version"]
                and manifest_entry["policy_status"] == "COMPLIANT"
            ),
            "dataset_hash_cross_evidence": dataset_hash_pass,
            "quality_report_valid": quality.get("valid") is True,
            "development_manifest_present": development_path.is_file(),
            "companion_artifacts": all(
                item["status"] == "PASS" for item in companion_results.values()
            ),
        }
        rows[component] = {
            "artifact_name": spec["artifact_name"],
            "artifact_sha256": artifact_hash,
            "receipt_name": spec["receipt_name"],
            "receipt_sha256": receipt_hash,
            "development_manifest": spec["development_manifest"],
            "development_manifest_sha256": file_sha256(development_path),
            "dataset_sha256": spec["dataset_sha256"],
            "dataset_hash_sources": dataset_sources,
            "dataset_manifest_sha256": file_sha256(dataset_manifest_path),
            "quality_report_sha256": file_sha256(quality_path),
            "companion_artifacts": companion_results,
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    return {
        "status": (
            "PASS"
            if shared_hash == EXPECTED_SHARED_MANIFEST_SHA256
            and all(row["status"] == "PASS" for row in rows.values())
            else "FAIL"
        ),
        "shared_artifact_manifest_sha256": shared_hash,
        "shared_artifact_manifest_unchanged": (
            shared_hash == EXPECTED_SHARED_MANIFEST_SHA256
        ),
        "components": rows,
    }


def audit_protected_receipts() -> dict[str, Any]:
    selection_fields = {
        "NLP": (
            "test_examples_available_to_configuration_selection",
            "test_used_for_calibration",
            "configuration_changed_after_freeze",
            "retrained_after_evaluation",
        ),
        "DUPLICATE": (
            "test_used_for_feature_fit",
            "test_used_for_threshold_selection",
            "configuration_changed_after_freeze",
        ),
        "EVENT": ("test_used_for_tuning",),
        "CREDIBILITY": (
            "test_used_for_model_selection",
            "test_used_for_preprocessing_fit",
            "test_used_for_calibration",
            "test_used_for_threshold_selection",
            "configuration_changed_after_freeze",
        ),
        "IMAGE": (
            "test_used_for_model_selection",
            "test_used_for_calibration",
            "test_used_for_threshold_selection",
            "configuration_changed_after_freeze",
        ),
        "ANOMALY": (
            "test_used_for_model_selection",
            "test_used_for_calibration",
            "test_used_for_threshold_selection",
            "configuration_changed_after_freeze",
        ),
    }
    artifact_hash_fields = {
        "NLP": "artifact_sha256",
        "DUPLICATE": "artifact_sha256",
        "EVENT": "artifact_file_sha256",
        "CREDIBILITY": "artifact_sha256",
        "IMAGE": "artifact_sha256",
        "ANOMALY": "model_sha256",
    }
    rows: dict[str, Any] = {}
    for component, spec in COMPONENT_SPECS.items():
        receipt = _read_json(ARTIFACT_ROOT / spec["receipt_name"])
        flags = {name: receipt.get(name) for name in selection_fields[component]}
        checks = {
            "receipt_hash": (
                file_sha256(ARTIFACT_ROOT / spec["receipt_name"])
                == spec["receipt_sha256"]
            ),
            "artifact_binding": (
                receipt.get(artifact_hash_fields[component]) == spec["artifact_sha256"]
            ),
            "invoked_exactly_once": receipt.get("evaluation_invocation_count") == 1,
            "rerun_prohibited": receipt.get("rerun_permitted") is False,
            "test_not_used_for_selection_or_retuning": all(
                value is False for value in flags.values()
            ),
            "production_not_validated": (
                receipt.get("production_validation") == PRODUCTION_VALIDATION
            ),
        }
        rows[component] = {
            "receipt_file": spec["receipt_name"],
            "receipt_sha256": spec["receipt_sha256"],
            "receipt_status": receipt.get("status"),
            "evaluation_invocation_count": receipt.get("evaluation_invocation_count"),
            "rerun_permitted": receipt.get("rerun_permitted"),
            "selection_and_retuning_flags": flags,
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    return {
        "status": (
            "PASS" if all(row["status"] == "PASS" for row in rows.values()) else "FAIL"
        ),
        "protected_test_evaluations_invoked_by_phase_24": 0,
        "components": rows,
    }


def _reference_classification(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    live_paths = {
        "backend/requirements.txt",
        "backend/app/main.py",
        "backend/app/services/dedup.py",
        "backend/app/services/pipeline.py",
    }
    if normalized in live_paths:
        return "LIVE_PRODUCTION_PATH"
    if normalized == "backend/app/ml/event_classifier.py":
        return "DEAD_CODE"
    if normalized == "backend/app/ml/final_freeze.py":
        return "DOCUMENTATION_ONLY"
    if "/tests/" in normalized or normalized.startswith("backend/tests/"):
        return "TEST_ONLY"
    if normalized.endswith("app/ml/docs/LEGACY_DEDUP_MIGRATION.md"):
        return "MIGRATION_TARGET"
    if "/docs/" in normalized or "/artifacts/" in normalized:
        return "DOCUMENTATION_ONLY"
    if normalized.endswith(
        (
            "app/ml/release_gate.py",
            "app/ml/training/duplicate_validation.py",
        )
    ):
        return "MIGRATION_TARGET"
    return "MIGRATION_TARGET"


def audit_legacy_embedding_references() -> dict[str, Any]:
    """Classify every textual legacy embedding-model reference in the backend."""

    pattern = re.compile(
        "|".join(
            (
                "mini" + "lm",
                "sentence[-_]" + "transformers?",
                "Sentence" + "Transformer",
            )
        ),
        re.IGNORECASE,
    )
    candidates: list[Path] = [BACKEND_ROOT / "requirements.txt"]
    for root in (BACKEND_ROOT / "app", BACKEND_ROOT / "tests"):
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix.casefold() not in {".py", ".md", ".txt", ".json"}:
                continue
            if path == DEFAULT_FINAL_FREEZE_PATH:
                continue
            candidates.append(path)
    references: list[dict[str, Any]] = []
    for path in sorted(set(candidates)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        classification = _reference_classification(relative)
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                references.append(
                    {
                        "file": relative,
                        "line": line_number,
                        "classification": classification,
                        "excerpt": line.strip()[:240],
                    }
                )
    counts = Counter(item["classification"] for item in references)
    live_files = sorted(
        {
            item["file"]
            for item in references
            if item["classification"] == "LIVE_PRODUCTION_PATH"
        }
    )
    dead_code_imports: list[str] = []
    legacy_module = "app.ml." + "event_classifier"
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        if path == ML_ROOT / "event_classifier.py" or "/tests/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_legacy = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name == legacy_module for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and (node.module or "") == legacy_module
            )
            for node in ast.walk(tree)
        )
        if imports_legacy:
            dead_code_imports.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    still_live = bool(live_files)
    return {
        "status": (
            "LEGACY_BACKEND_VIOLATION" if still_live else "REMOVED_FROM_LIVE_RUNTIME"
        ),
        "live_backend_depends_on_embedding_model": still_live,
        "new_six_component_subsystem_depends_on_embedding_model": False,
        "model_identifier": "sentence-" + "transformers/all-" + "MiniLM-L6-v2",
        "runtime_behavior": (
            "LIVE_LAZY_LOAD_AND_STARTUP_WARMUP; remote resolution may be attempted "
            "when the model is not cached; failure falls back to Levenshtein"
            if still_live
            else "FROZEN_LOCAL_MATCHER; no live embedding model initialization"
        ),
        "live_call_chain": (
            [
                "backend/app/main.py lifespan warmup",
                "backend/app/services/pipeline.py DedupService.find_duplicate",
                "backend/app/services/dedup.py _get_embedding_model",
            ]
            if still_live
            else []
        ),
        "live_reference_files": live_files,
        "dead_legacy_classifier_importers": dead_code_imports,
        "classification_counts": dict(sorted(counts.items())),
        "references": references,
    }


def audit_boundary_independence() -> dict[str, Any]:
    forbidden_roots = {
        "fastapi",
        "sqlalchemy",
        "kafka",
        "redis",
        "psycopg",
        "asyncpg",
        "app.api",
        "app.services",
        "app.workers",
        "app.core.database",
    }
    violations: list[str] = []
    files_scanned = 0
    for path in ML_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(ML_ROOT).parts
        if path == ML_ROOT / "event_classifier.py" or any(
            part in {"tests", "__pycache__"} for part in relative_parts
        ):
            continue
        files_scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                if any(
                    module == root or module.startswith(root + ".")
                    for root in forbidden_roots
                ):
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT).as_posix()}: {module}"
                    )
    return {
        "status": "PASS" if not violations else "FAIL",
        "files_scanned": files_scanned,
        "violations": sorted(violations),
        "excluded_legacy_file": "backend/app/ml/event_classifier.py",
        "boundaries": [
            "PostgreSQL",
            "PostGIS",
            "Kafka",
            "Redis",
            "FastAPI",
            "authentication",
            "frontend",
            "remote URLs",
            "external model-serving systems",
        ],
    }


def _prediction_digest(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _reproducibility_result(
    component: str,
    first: Any,
    second: Any,
    *,
    metadata: Mapping[str, Any],
    companion_files: Sequence[str] = (),
) -> dict[str, Any]:
    first_digest = _prediction_digest(first)
    second_digest = _prediction_digest(second)
    deterministic = first_digest == second_digest
    spec = COMPONENT_SPECS[component]
    stable_hash = (
        file_sha256(ARTIFACT_ROOT / spec["artifact_name"]) == spec["artifact_sha256"]
    )
    passed = deterministic and stable_hash and bool(metadata)
    return {
        "component": component,
        "status": "PASS" if passed else "FAIL",
        "load_status": "PASS",
        "required_metadata_status": "PASS" if metadata else "FAIL",
        "stable_sha256_status": "PASS" if stable_hash else "FAIL",
        "deterministic_inference_status": "PASS" if deterministic else "FAIL",
        "network_required": False,
        "runtime_downloads": False,
        "external_model_files": [],
        "local_hash_bound_companion_files": list(companion_files),
        "configuration_sufficient_for_inference": True,
        "inference_sha256": first_digest,
        "metadata": dict(metadata),
    }


def _nlp_reproducibility() -> dict[str, Any]:
    from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact

    artifact_path = ARTIFACT_ROOT / "nlp_classifier_v3.json"
    manifest_path = ARTIFACT_ROOT / "manifest.json"
    artifact = load_nlp_artifact(artifact_path, manifest_path=manifest_path)
    config = NLPClassifierConfig(
        model_version=artifact.model_version,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        artifact_path=artifact_path,
        char_ngram_range=tuple(artifact.char_space.ngram_range),
        word_ngram_range=tuple(artifact.word_space.ngram_range),
        random_state=artifact.classifier.random_state,
    )
    classifier = NLPClassifier(
        config=config,
        artifact_path=artifact_path,
        manifest_path=manifest_path,
    )
    probe = "Nadi ka bandh toot gaya aur paas ke gaon mein paani aa raha hai."
    first = classifier.predict(probe)
    second = classifier.predict(probe)
    return _reproducibility_result(
        "NLP",
        first,
        second,
        metadata={
            "model_version": artifact.model_version,
            "feature_version": artifact.feature_version,
            "preprocessing_version": artifact.preprocessing_version,
            "feature_count": artifact.n_features,
            "class_mapping": artifact.classes,
        },
    )


def _duplicate_reproducibility() -> dict[str, Any]:
    from app.ml.training.duplicate_validation import (
        load_duplicate_development_artifact,
    )

    artifact, matcher = load_duplicate_development_artifact()
    occurred_at = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)
    candidate = CandidateReport(
        report_id=UUID("00000000-0000-0000-0000-000000000242"),
        text="Severe waterlogging on Station Road after heavy rain",
        occurred_at=occurred_at - timedelta(minutes=7),
        latitude=25.5943,
        longitude=85.1374,
        source_type="PHASE24_AUDIT_PROBE",
    )
    report = ReportInput(
        report_id=UUID("00000000-0000-0000-0000-000000000241"),
        text="Heavy rain caused severe waterlogging on Station Road",
        occurred_at=occurred_at,
        latitude=25.5941,
        longitude=85.1376,
        source_type="PHASE24_AUDIT_PROBE",
        candidate_reports=[candidate],
    )
    first = matcher.predict(report)
    second = matcher.predict(report)
    return _reproducibility_result(
        "DUPLICATE",
        first,
        second,
        metadata={
            "artifact_version": artifact.artifact_version,
            "feature_version": artifact.feature_version,
            "preprocessing_version": artifact.preprocessing_version,
            "threshold_version": artifact.threshold_version,
            "score_interpretation": artifact.score_interpretation,
        },
        companion_files=["duplicate_feature_state_v2.json"],
    )


def _event_reproducibility() -> dict[str, Any]:
    from app.ml.components.event_detection import EventDetector
    from app.ml.training.event_validation import load_event_development_artifact

    artifact, config = load_event_development_artifact()
    detector = EventDetector(config=config)
    report = ReportInput(
        report_id=UUID("00000000-0000-0000-0000-000000000243"),
        text="Flood water is rising near the market",
        occurred_at=datetime(2026, 9, 24, 6, 15, tzinfo=timezone.utc),
        latitude=25.5941,
        longitude=85.1376,
        source_type="PHASE24_AUDIT_PROBE",
    )
    first = detector.predict(report)
    second = detector.predict(report)
    candidate = first.candidate_event
    semantics_preserved = bool(
        candidate
        and candidate.lifecycle_state == "CANDIDATE"
        and "NOT_CONFIRMED_EVENT" in first.reason_codes
        and artifact.cluster_constraints["method"] == "COMPLETE_LINK_ALL_MEMBER_PAIRS"
        and artifact.cluster_constraints["transitive_bridge_merge_permitted"] is False
    )
    result = _reproducibility_result(
        "EVENT",
        first,
        second,
        metadata={
            "artifact_version": artifact.artifact_version,
            "artifact_kind": artifact.artifact_kind,
            "algorithm_version": artifact.algorithm_version,
            "feature_version": artifact.feature_version,
            "single_report_semantics": "CANDIDATE_NOT_CONFIRMED",
            "cluster_constraint": "COMPLETE_LINK_ALL_MEMBER_PAIRS",
        },
    )
    result["semantic_invariants_status"] = "PASS" if semantics_preserved else "FAIL"
    if not semantics_preserved:
        result["status"] = "FAIL"
    return result


def _credibility_reproducibility() -> dict[str, Any]:
    from app.ml.training.credibility_validation import (
        load_credibility_development_artifact,
        predict_credibility_development,
    )

    artifact = load_credibility_development_artifact()
    value = SyntheticCredibilityDetectorInput(
        report_id=UUID("00000000-0000-0000-0000-000000000244"),
        report_text=(
            "River water entered the lower settlement; district teams are checking "
            "the reported embankment damage."
        ),
        occurred_at=datetime(2026, 9, 24, 6, 30, tzinfo=timezone.utc),
        latitude=25.5941,
        longitude=85.1376,
        source_type="PHASE24_AUDIT_PROBE",
        source_metadata={"submission_delay_seconds": 300},
    )
    first = predict_credibility_development(value, artifact)
    second = predict_credibility_development(value, artifact)
    semantics_preserved = bool(
        first.label in {"AUTHENTIC", "MISLEADING", "UNCERTAIN"}
        and first.truth_probability is False
        and first.semantic_target == "MISLEADING_RISK_EVIDENCE"
    )
    result = _reproducibility_result(
        "CREDIBILITY",
        first,
        second,
        metadata={
            "artifact_version": artifact.artifact_version,
            "artifact_kind": artifact.artifact_kind,
            "feature_version": artifact.feature_version,
            "preprocessing_version": artifact.preprocessing_version,
            "output_labels": artifact.output_labels,
            "prohibited_interpretation": artifact.prohibited_interpretation,
        },
    )
    result["semantic_invariants_status"] = "PASS" if semantics_preserved else "FAIL"
    if not semantics_preserved:
        result["status"] = "FAIL"
    return result


def _image_reproducibility() -> dict[str, Any]:
    from app.ml.training.image_synthetic_validation import (
        ProjectTrainedImageAnalyzer,
        load_image_development_manifest,
    )

    development = load_image_development_manifest()
    analyzer = ProjectTrainedImageAnalyzer()
    dataset_root = DATA_ROOT / "image/synthetic_v1"
    record = SyntheticImageModelRecord.model_validate_json(
        _first_jsonl_line(dataset_root / "model_inputs/validation.jsonl")
    )
    image_bytes = (dataset_root / record.image_path).read_bytes()
    image = ImageInput(
        image_id="phase24-validation-probe",
        image_bytes=image_bytes,
        mime_type="image/png",
        file_size=len(image_bytes),
        width=64,
        height=64,
        checksum=record.byte_sha256,
    )
    first = analyzer.predict(image)
    second = analyzer.predict(image)
    semantics_preserved = first.task_type == "MULTI_LABEL"
    result = _reproducibility_result(
        "IMAGE",
        first,
        second,
        metadata={
            "artifact_version": development.model_version,
            "architecture_version": development.architecture_version,
            "feature_version": development.feature_version,
            "preprocessing_version": development.preprocessing_version,
            "initialization": development.initialization,
            "task_type": "MULTI_LABEL",
        },
    )
    result["semantic_invariants_status"] = "PASS" if semantics_preserved else "FAIL"
    if not semantics_preserved:
        result["status"] = "FAIL"
    return result


def _anomaly_reproducibility() -> dict[str, Any]:
    from app.ml.training.anomaly_synthetic_validation import (
        load_frozen_anomaly_artifact,
    )

    artifact = load_frozen_anomaly_artifact()
    dataset_root = DATA_ROOT / "anomaly/synthetic_v1"
    record = SyntheticAnomalyModelRecord.model_validate_json(
        _first_jsonl_line(dataset_root / "model_inputs/validation.jsonl")
    )
    first_scores = score_records(artifact, [record])
    second_scores = score_records(artifact, [record])
    first = {
        label: round(float(values[0]), 14) for label, values in first_scores.items()
    }
    second = {
        label: round(float(values[0]), 14) for label, values in second_scores.items()
    }
    semantics_preserved = set(first) == {
        "DATA_QUALITY_ANOMALY",
        "WEATHER_BEHAVIOR_ANOMALY",
    }
    result = _reproducibility_result(
        "ANOMALY",
        first,
        second,
        metadata={
            "artifact_version": artifact.artifact_version,
            "model_family": artifact.model_family,
            "baseline_name": artifact.baseline_name,
            "feature_version": artifact.feature_version,
            "preprocessing_version": artifact.preprocessing_version,
            "heads": sorted(artifact.heads),
            "calibration": artifact.calibration,
        },
    )
    result["semantic_invariants_status"] = "PASS" if semantics_preserved else "FAIL"
    if not semantics_preserved:
        result["status"] = "FAIL"
    return result


def audit_artifact_reproducibility() -> dict[str, Any]:
    auditors = {
        "NLP": _nlp_reproducibility,
        "DUPLICATE": _duplicate_reproducibility,
        "EVENT": _event_reproducibility,
        "CREDIBILITY": _credibility_reproducibility,
        "IMAGE": _image_reproducibility,
        "ANOMALY": _anomaly_reproducibility,
    }
    rows: dict[str, Any] = {}

    def reject_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network access attempted during Phase 24 inference")

    for component, auditor in auditors.items():
        try:
            with patch("socket.socket", side_effect=reject_network):
                rows[component] = auditor()
            rows[component]["network_guard_active"] = True
        except Exception as error:  # noqa: BLE001 - audit records exact failure
            rows[component] = {
                "component": component,
                "status": "FAIL",
                "load_status": "FAIL",
                "error_type": type(error).__name__,
                "error": str(error),
            }
    return {
        "status": (
            "PASS" if all(row["status"] == "PASS" for row in rows.values()) else "FAIL"
        ),
        "protected_test_data_used": False,
        "active_socket_guard": True,
        "components": rows,
    }


def _receipt_evidence(component: str) -> dict[str, Any]:
    spec = COMPONENT_SPECS[component]
    return _read_json(ARTIFACT_ROOT / spec["receipt_name"])


def audit_global_data_leakage() -> dict[str, Any]:
    """Audit the nine requested leakage dimensions from frozen evidence only."""

    rows: dict[str, Any] = {}

    nlp = _read_json(QUALITY_PATHS["NLP"])
    nlp_leakage = nlp["leakage_results"]
    nlp_receipt = _receipt_evidence("NLP")
    rows["NLP"] = {
        "train_test_overlap": _status(
            nlp_leakage["exact_cross_split_text_count"] == 0
            and nlp_leakage["normalized_cross_split_text_count"] == 0
            and nlp_leakage["near_duplicate_cross_split_count"] == 0,
            "Exact, normalized, and near-duplicate cross-split counts are zero.",
        ),
        "template_scenario_leakage": _status(
            nlp_leakage["template_leakage_count"] == 0
            and nlp_leakage["scenario_leakage_count"] == 0,
            "Template and scenario leakage counts are zero.",
        ),
        "family_leakage": _status(
            all(
                nlp["holdout_contract"][key]
                for key in (
                    "split_specific_templates",
                    "split_specific_locations",
                    "split_specific_lexicons",
                    "split_specific_time_ranges",
                )
            ),
            "Generator-level template, location, lexicon, and time families are split-specific.",
        ),
        "parameter_leakage": _status(
            nlp_leakage["parameter_combination_leakage_count"] == 0,
            "Parameter-combination leakage count is zero.",
        ),
        "label_derivation_leakage": _status(
            nlp["label_source"] == "GENERATOR_SCENARIO_SPECIFICATION"
            and nlp["scenario_binding_failures"] == 0,
            "Labels come from the project generator scenario specification; scenario binding failures are zero.",
        ),
        "preprocessing_leakage": _status(
            _read_json(ARTIFACT_ROOT / "nlp_classifier_v3.development_manifest.json")[
                "frozen_configuration"
            ]["feature_fitting"]["fit_split"]
            == "train",
            "TF-IDF feature fitting is bound to train; validation and test are transform-only.",
        ),
        "calibration_leakage": _status(
            nlp_receipt["test_used_for_calibration"] is False,
            "Temperature scaling is validation-only and the receipt excludes test calibration.",
        ),
        "threshold_selection_leakage": _status(
            nlp_receipt["test_examples_available_to_configuration_selection"] is False,
            "The test examples were unavailable to configuration selection.",
        ),
        "protected_test_contamination": _status(
            nlp_receipt["evaluation_invocation_count"] == 1
            and nlp_receipt["rerun_permitted"] is False
            and nlp_receipt["configuration_changed_after_freeze"] is False,
            "One-shot receipt is complete, immutable, and records no post-freeze change.",
        ),
    }

    duplicate = _read_json(QUALITY_PATHS["DUPLICATE"])
    duplicate_leakage = duplicate["leakage_checks"]
    duplicate_development = _read_json(
        ARTIFACT_ROOT / "duplicate_v1.development_manifest.json"
    )
    duplicate_receipt = _receipt_evidence("DUPLICATE")
    rows["DUPLICATE"] = {
        "train_test_overlap": _status(
            duplicate_leakage["exact_text_cross_split"] == 0
            and duplicate_leakage["report_cross_split"] == 0
            and duplicate_leakage["incident_cross_split"] == 0,
            "Exact text, report identity, and incident cross-split counts are zero.",
        ),
        "template_scenario_leakage": _status(
            duplicate_leakage["scenario_family_cross_split"] == 0,
            "Scenario-family cross-split count is zero.",
        ),
        "family_leakage": _status(
            duplicate_leakage["incident_cross_split"] == 0
            and duplicate_leakage["report_cross_split"] == 0,
            "Incident and report families do not cross splits.",
        ),
        "parameter_leakage": _status(
            duplicate_leakage["parameter_combination_cross_split"] == 0,
            "Generator parameter-combination cross-split count is zero.",
        ),
        "label_derivation_leakage": _status(
            duplicate["invariant_checks"]["labels_come_from_scenario_identity"]
            and duplicate["invariant_checks"]["matcher_not_used_for_labels"],
            "Scenario identity supplies labels and the matcher was not used for labels.",
        ),
        "preprocessing_leakage": _status(
            duplicate_receipt["test_used_for_feature_fit"] is False,
            "Feature state was fit before test and the receipt excludes test feature fitting.",
        ),
        "calibration_leakage": _status(
            duplicate_development["calibration"]["status"]
            == "SELECTED_VALIDATION_ONLY_SYNTHETIC_DEVELOPMENT",
            "Platt score mapping was selected on validation only and does not change the duplicate decision.",
        ),
        "threshold_selection_leakage": _status(
            duplicate_development["threshold_selection"]["split"] == "validation"
            and duplicate_receipt["test_used_for_threshold_selection"] is False,
            "Thresholds are validation-selected; the receipt excludes test threshold selection.",
        ),
        "protected_test_contamination": _status(
            duplicate_receipt["evaluation_invocation_count"] == 1
            and duplicate_receipt["rerun_permitted"] is False
            and duplicate_receipt["configuration_changed_after_freeze"] is False,
            "One-shot receipt records no post-freeze configuration change.",
        ),
    }

    event = _read_json(QUALITY_PATHS["EVENT"])
    event_leakage = event["leakage_checks"]
    event_development = _read_json(
        ARTIFACT_ROOT / "event_grouping_v1.development_manifest.json"
    )
    event_receipt = _receipt_evidence("EVENT")
    rows["EVENT"] = {
        "train_test_overlap": _status(
            event_leakage["canonical_event_cross_split"] == 0
            and event_leakage["incident_cross_split"] == 0
            and event_leakage["report_cross_split"] == 0,
            "Canonical event, incident, and report identities do not cross splits.",
        ),
        "template_scenario_leakage": _status(
            False,
            "FAIL_CLOSED: Phase 20 reused the eleven scenario templates across splits and recorded no template-identity leakage check; holdout strategy is canonical event ID only.",
        ),
        "family_leakage": _status(
            event_leakage["canonical_event_cross_split"] == 0
            and event_leakage["incident_cross_split"] == 0,
            "Canonical event and incident families do not cross splits.",
        ),
        "parameter_leakage": _status(
            False,
            "FAIL_CLOSED: Phase 20 evidence contains no parameter-family or parameter-combination identity and therefore cannot prove parameter holdout.",
        ),
        "label_derivation_leakage": _status(
            event["invariant_checks"]["truth_defined_before_detector"]
            and event["invariant_checks"]["detector_not_used_for_labels"]
            and event_leakage["ground_truth_isolation"],
            "Canonical truth is defined before detection and hidden from detector inputs.",
        ),
        "preprocessing_leakage": _status(
            event_development["test_rows_accessed"] is False,
            "The deterministic normalizer/configuration freeze did not access test rows.",
        ),
        "calibration_leakage": _status(
            True,
            "NOT_APPLICABLE: event evidence scores are explicitly heuristic and uncalibrated.",
        ),
        "threshold_selection_leakage": _status(
            event_development["selection_split"] == "validation"
            and event_receipt["test_used_for_tuning"] is False,
            "Configuration selection used validation and the receipt excludes test tuning.",
        ),
        "protected_test_contamination": _status(
            event_receipt["evaluation_invocation_count"] == 1
            and event_receipt["rerun_permitted"] is False
            and event_receipt["configuration_frozen_before_test"] is True,
            "One-shot receipt binds the frozen event configuration.",
        ),
    }

    credibility = _read_json(QUALITY_PATHS["CREDIBILITY"])
    credibility_leakage = credibility["leakage_checks"]
    credibility_artifact = _read_json(ARTIFACT_ROOT / "credibility_v1.json")
    credibility_receipt = _receipt_evidence("CREDIBILITY")
    rows["CREDIBILITY"] = {
        "train_test_overlap": _status(
            credibility_leakage["exact_normalized_text_cross_split"] == 0
            and credibility_leakage["canonical_event_cross_split"] == 0,
            "Normalized text and canonical-event cross-split counts are zero.",
        ),
        "template_scenario_leakage": _status(
            credibility_leakage["template_cross_split"] == 0,
            "Template cross-split count is zero.",
        ),
        "family_leakage": _status(
            credibility_leakage["report_family_cross_split"] == 0,
            "Report-family cross-split count is zero.",
        ),
        "parameter_leakage": _status(
            credibility_leakage["parameter_combination_cross_split"] == 0,
            "Parameter-combination cross-split count is zero.",
        ),
        "label_derivation_leakage": _status(
            credibility["invariant_checks"]["scenario_identity_supplies_ground_truth"]
            and credibility["invariant_checks"]["learned_detector_not_used_for_labels"]
            and credibility["isolation_checks"]["forbidden_field_occurrences"] == 0,
            "Scenario identity supplies isolated labels; forbidden detector-input fields are absent.",
        ),
        "preprocessing_leakage": _status(
            credibility_receipt["test_used_for_preprocessing_fit"] is False,
            "The receipt excludes protected-test preprocessing fit.",
        ),
        "calibration_leakage": _status(
            credibility_artifact["calibration_split"] == "validation:calibration"
            and credibility_receipt["test_used_for_calibration"] is False,
            "Calibration uses its validation partition only.",
        ),
        "threshold_selection_leakage": _status(
            credibility_artifact["threshold_selection_split"]
            == "validation:threshold_selection"
            and credibility_receipt["test_used_for_threshold_selection"] is False,
            "Threshold selection uses its validation partition only.",
        ),
        "protected_test_contamination": _status(
            credibility_receipt["evaluation_invocation_count"] == 1
            and credibility_receipt["rerun_permitted"] is False
            and credibility_receipt["configuration_changed_after_freeze"] is False,
            "One-shot receipt records no test reuse or post-freeze change.",
        ),
    }

    image = _read_json(QUALITY_PATHS["IMAGE"])
    image_leakage = image["leakage_checks"]
    image_development = _read_json(
        ARTIFACT_ROOT / "image_model_v1.development_manifest.json"
    )
    image_receipt = _receipt_evidence("IMAGE")
    rows["IMAGE"] = {
        "train_test_overlap": _status(
            image_leakage["byte_hash_cross_split"] == 0
            and image_leakage["exact_image_identity_cross_split"] == 0,
            "Image-byte and exact-identity cross-split counts are zero.",
        ),
        "template_scenario_leakage": _status(
            image_leakage["direct_template_cross_split"] == 0
            and image_leakage["scene_family_cross_split"] == 0,
            "Direct-template and scene-family cross-split counts are zero.",
        ),
        "family_leakage": _status(
            image_leakage["background_family_cross_split"] == 0
            and image["holdout_checks"]["test_backgrounds_held_out"],
            "Background families are held out and do not cross splits.",
        ),
        "parameter_leakage": _status(
            image_leakage["parameter_family_cross_split"] == 0
            and image_leakage["parameter_combination_cross_split"] == 0,
            "Parameter families and combinations do not cross splits.",
        ),
        "label_derivation_leakage": _status(
            image["hidden_metadata_isolation"]["cnn_receives_hidden_metadata"] is False
            and image["hidden_metadata_isolation"]["mismatched_rows"] == 0,
            "Hidden scene metadata is physically separate and never reaches the CNN.",
        ),
        "preprocessing_leakage": _status(
            image_development["protected_final_test"]["accessed_for_selection"]
            is False,
            "Protected images were not accessed during training/preprocessing selection.",
        ),
        "calibration_leakage": _status(
            image_development["calibration"]["fit_source"] == "VALIDATION_ONLY"
            and image_receipt["test_used_for_calibration"] is False,
            "Per-label temperatures use validation only.",
        ),
        "threshold_selection_leakage": _status(
            image_receipt["test_used_for_threshold_selection"] is False,
            "The receipt excludes protected-test threshold selection.",
        ),
        "protected_test_contamination": _status(
            image_receipt["evaluation_invocation_count"] == 1
            and image_receipt["rerun_permitted"] is False
            and image_receipt["configuration_changed_after_freeze"] is False,
            "One-shot image receipt records no post-freeze change.",
        ),
    }

    anomaly = _read_json(QUALITY_PATHS["ANOMALY"])
    anomaly_leakage = anomaly["leakage_checks"]
    anomaly_development = _read_json(
        ARTIFACT_ROOT / "anomaly_model_v1.development_manifest.json"
    )
    anomaly_receipt = _receipt_evidence("ANOMALY")
    rows["ANOMALY"] = {
        "train_test_overlap": _status(
            anomaly_leakage["window_hash_cross_split"] == 0
            and anomaly_leakage["trajectory_hash_cross_split"] == 0,
            "Window and trajectory hashes do not cross splits.",
        ),
        "template_scenario_leakage": _status(
            anomaly_leakage["temporal_pattern_family_cross_split"] == 0,
            "Temporal-pattern families do not cross splits; scenario class names are target categories, not shared trajectory identities.",
        ),
        "family_leakage": _status(
            anomaly_leakage["station_family_cross_split"] == 0,
            "Station families do not cross splits.",
        ),
        "parameter_leakage": _status(
            anomaly_leakage["parameter_family_cross_split"] == 0
            and anomaly_leakage["parameter_combination_cross_split"] == 0,
            "Anomaly parameter families and combinations do not cross splits.",
        ),
        "label_derivation_leakage": _status(
            anomaly["hidden_metadata_isolation"]["detector_receives_hidden_metadata"]
            is False
            and anomaly["hidden_metadata_isolation"][
                "label_derived_from_detector_output"
            ]
            is False,
            "Hidden scenario metadata is separate and labels do not derive from detector output.",
        ),
        "preprocessing_leakage": _status(
            anomaly_development["test_records_loaded_for_selection"] is False,
            "Scaling and model fitting used train; test records were not loaded for selection.",
        ),
        "calibration_leakage": _status(
            anomaly_development["calibration"] == "NONE_VALIDATION_THRESHOLDS_ONLY"
            and anomaly_receipt["test_used_for_calibration"] is False,
            "No probability calibration was fitted; validation-only thresholds remain explicit.",
        ),
        "threshold_selection_leakage": _status(
            anomaly_receipt["test_used_for_threshold_selection"] is False,
            "The receipt excludes protected-test threshold selection.",
        ),
        "protected_test_contamination": _status(
            anomaly_receipt["evaluation_invocation_count"] == 1
            and anomaly_receipt["rerun_permitted"] is False
            and anomaly_receipt["configuration_changed_after_freeze"] is False,
            "One-shot anomaly receipt records no post-freeze change.",
        ),
    }

    for checks in rows.values():
        checks["overall_status"] = (
            "PASS"
            if all(item["status"] == "PASS" for item in checks.values())
            else "FAIL"
        )
    failed = {
        component: [
            name
            for name, result in checks.items()
            if name != "overall_status" and result["status"] == "FAIL"
        ]
        for component, checks in rows.items()
        if checks["overall_status"] == "FAIL"
    }
    return {
        "status": "PASS" if not failed else "FAIL",
        "components": rows,
        "failed_checks": failed,
        "protected_test_evaluations_invoked_by_phase_24": 0,
    }


def _load_anomaly_audit_split(split: str) -> dict[str, Any]:
    """Load one non-test split and derive features without retaining raw rows."""

    if split not in {"train", "validation"}:
        raise ValueError("Phase 24 separability audit permits train/validation only")
    root = DATA_ROOT / "anomaly/synthetic_v1"
    model_path = root / "model_inputs" / f"{split}.jsonl"
    metadata_path = root / "hidden_generator_metadata" / f"{split}.jsonl"
    manifest = _read_json(root / "manifest.json")
    matrices: list[np.ndarray] = []
    chunk: list[SyntheticAnomalyModelRecord] = []
    scenarios: list[str] = []
    labels: dict[str, list[bool]] = {
        "DATA_QUALITY_ANOMALY": [],
        "WEATHER_BEHAVIOR_ANOMALY": [],
        "OVERALL_ANOMALY": [],
    }
    identity_sets: dict[str, set[str]] = {
        "window_id": set(),
        "window_sha256": set(),
        "station_family": set(),
        "temporal_pattern_family": set(),
        "anomaly_parameter_family": set(),
        "parameter_combination_id": set(),
        "trajectory_sha256": set(),
    }

    with (
        model_path.open(encoding="utf-8") as model_handle,
        metadata_path.open(encoding="utf-8") as metadata_handle,
    ):
        model_lines = (line for line in model_handle if line.strip())
        metadata_lines = (line for line in metadata_handle if line.strip())
        for index, (model_line, metadata_line) in enumerate(
            zip_longest(model_lines, metadata_lines), start=1
        ):
            if model_line is None or metadata_line is None:
                raise ValueError(f"unaligned anomaly {split} rows at line {index}")
            record = SyntheticAnomalyModelRecord.model_validate_json(model_line)
            metadata = SyntheticAnomalyMetadata.model_validate_json(metadata_line)
            if (
                record.window_id != metadata.window_id
                or record.split != split
                or metadata.split != split
            ):
                raise ValueError(f"misaligned anomaly {split} row at line {index}")
            chunk.append(record)
            scenarios.append(metadata.scenario_family)
            labels["DATA_QUALITY_ANOMALY"].append(metadata.data_quality_anomaly)
            labels["WEATHER_BEHAVIOR_ANOMALY"].append(metadata.weather_behavior_anomaly)
            labels["OVERALL_ANOMALY"].append(metadata.overall_anomaly)
            identity_sets["window_id"].add(record.window_id)
            identity_sets["window_sha256"].add(record.window_sha256)
            for field in (
                "station_family",
                "temporal_pattern_family",
                "anomaly_parameter_family",
                "parameter_combination_id",
                "trajectory_sha256",
            ):
                identity_sets[field].add(str(getattr(metadata, field)))
            if len(chunk) == 512:
                matrices.append(feature_matrix(chunk))
                chunk.clear()
    if chunk:
        matrices.append(feature_matrix(chunk))
    matrix = np.vstack(matrices) if matrices else np.empty((0, len(FEATURE_NAMES)))
    expected_count = manifest["split_counts"][split]
    checks = {
        "model_input_sha256": (
            file_sha256(model_path) == manifest["split_sha256"][split]
        ),
        "hidden_metadata_sha256": (
            file_sha256(metadata_path) == manifest["hidden_metadata_sha256"][split]
        ),
        "row_count": matrix.shape[0] == expected_count,
        "feature_count": matrix.shape[1] == len(FEATURE_NAMES),
        "finite_features": bool(np.isfinite(matrix).all()),
        "one_to_one_alignment": (
            matrix.shape[0] == len(identity_sets["window_id"]) == len(scenarios)
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"anomaly {split} audit integrity failure: {checks}")
    return {
        "split": split,
        "matrix": matrix,
        "scenarios": np.asarray(scenarios, dtype=object),
        "labels": {
            name: np.asarray(values, dtype=np.bool_) for name, values in labels.items()
        },
        "identity_sets": identity_sets,
        "integrity_checks": checks,
        "model_input_sha256": file_sha256(model_path),
        "hidden_metadata_sha256": file_sha256(metadata_path),
        "row_count": matrix.shape[0],
    }


def _rank_auc_by_category(
    values: np.ndarray, categories: np.ndarray
) -> dict[str, dict[str, Any]]:
    """Return direction-invariant one-vs-rest AUC for each category."""

    ranks = rankdata(values, method="average")
    count = len(values)
    results: dict[str, dict[str, Any]] = {}
    for category in sorted({str(value) for value in categories.tolist()}):
        positive = categories == category
        positive_count = int(positive.sum())
        negative_count = count - positive_count
        if positive_count == 0 or negative_count == 0:
            continue
        rank_sum = float(ranks[positive].sum())
        auc = (rank_sum - positive_count * (positive_count + 1) / 2.0) / (
            positive_count * negative_count
        )
        results[category] = {
            "directionless_auc": max(auc, 1.0 - auc),
            "signed_auc": auc,
            "direction": "HIGHER" if auc >= 0.5 else "LOWER",
            "positive_count": positive_count,
        }
    return results


def _best_cross_split_discriminator(
    train_scores: Mapping[str, Mapping[str, Any]],
    validation_scores: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    candidates: list[tuple[float, str, bool]] = []
    for category in sorted(set(train_scores) & set(validation_scores)):
        direction_consistent = (
            train_scores[category]["direction"]
            == validation_scores[category]["direction"]
        )
        confirmed_auc = min(
            float(train_scores[category]["directionless_auc"]),
            float(validation_scores[category]["directionless_auc"]),
        )
        candidates.append((confirmed_auc, category, direction_consistent))
    if not candidates:
        raise ValueError("no cross-split discriminator categories")
    _, category, direction_consistent = max(
        candidates, key=lambda item: (item[0], item[1])
    )
    train = train_scores[category]
    validation = validation_scores[category]
    confirmed_auc = min(
        float(train["directionless_auc"]),
        float(validation["directionless_auc"]),
    )
    return {
        "category": category,
        "train_directionless_auc": round(float(train["directionless_auc"]), 8),
        "validation_directionless_auc": round(
            float(validation["directionless_auc"]), 8
        ),
        "cross_split_min_auc": round(confirmed_auc, 8),
        "train_direction": train["direction"],
        "validation_direction": validation["direction"],
        "direction_consistent": direction_consistent,
    }


def audit_anomaly_feature_separability() -> dict[str, Any]:
    """Retrospective TRAIN+VALIDATION audit; protected TEST is never opened."""

    train = _load_anomaly_audit_split("train")
    validation = _load_anomaly_audit_split("validation")
    train_target_categories = {
        name: np.where(values, name, f"NOT_{name}")
        for name, values in train["labels"].items()
    }
    validation_target_categories = {
        name: np.where(values, name, f"NOT_{name}")
        for name, values in validation["labels"].items()
    }
    feature_results: list[dict[str, Any]] = []
    for index, feature_name in enumerate(FEATURE_NAMES):
        train_values = train["matrix"][:, index]
        validation_values = validation["matrix"][:, index]
        scenario = _best_cross_split_discriminator(
            _rank_auc_by_category(train_values, train["scenarios"]),
            _rank_auc_by_category(validation_values, validation["scenarios"]),
        )
        target_candidates: list[dict[str, Any]] = []
        for target_name in sorted(train_target_categories):
            result = _best_cross_split_discriminator(
                _rank_auc_by_category(
                    train_values, train_target_categories[target_name]
                ),
                _rank_auc_by_category(
                    validation_values,
                    validation_target_categories[target_name],
                ),
            )
            result["target"] = target_name
            target_candidates.append(result)
        target = max(
            target_candidates,
            key=lambda item: (item["cross_split_min_auc"], item["target"]),
        )
        direct_scenario = bool(
            scenario["direction_consistent"]
            and scenario["cross_split_min_auc"] >= DIRECT_SCENARIO_AUC_THRESHOLD
        )
        direct_target = bool(
            target["direction_consistent"]
            and target["cross_split_min_auc"] >= DIRECT_SCENARIO_AUC_THRESHOLD
        )
        feature_results.append(
            {
                "feature": feature_name,
                "maximum_scenario_discrimination": scenario,
                "maximum_target_label_discrimination": target,
                "unusually_direct_scenario_discrimination": direct_scenario,
                "unusually_direct_target_discrimination": direct_target,
            }
        )

    direct_scenario_features = [
        row["feature"]
        for row in feature_results
        if row["unusually_direct_scenario_discrimination"]
    ]
    direct_target_features = [
        row["feature"]
        for row in feature_results
        if row["unusually_direct_target_discrimination"]
    ]
    maximum_confirmed_auc = max(
        max(
            row["maximum_scenario_discrimination"]["cross_split_min_auc"],
            row["maximum_target_label_discrimination"]["cross_split_min_auc"],
        )
        for row in feature_results
    )
    development = _read_json(
        ARTIFACT_ROOT / "anomaly_model_v1.development_manifest.json"
    )
    minimum_validation_f1 = min(
        float(metrics["f1"]) for metrics in development["validation_metrics"].values()
    )
    if direct_scenario_features or (
        len(direct_target_features) >= 3 and minimum_validation_f1 >= 0.99
    ):
        risk = "HIGH"
    elif maximum_confirmed_auc >= 0.95 or minimum_validation_f1 >= 0.98:
        risk = "MODERATE"
    else:
        risk = "LOW"

    source = textwrap.dedent(inspect.getsource(extract_window_feature_vector))
    source_tree = ast.parse(source)
    detector_fields_used = sorted(
        {
            node.attr
            for node in ast.walk(source_tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "record"
        }
    )
    hidden_or_identifier_fields = {
        "scenario_id",
        "scenario_family",
        "station_family",
        "temporal_pattern_family",
        "anomaly_parameter_family",
        "parameter_combination_id",
        "generation_parameters",
        "data_quality_anomaly",
        "weather_behavior_anomaly",
        "overall_anomaly",
        "anomaly_type",
        "anomaly_domain",
        "window_id",
        "station_id",
        "split",
        "window_sha256",
    }
    forbidden_used = sorted(set(detector_fields_used) & hidden_or_identifier_fields)
    expected_detector_fields = {"timestamps", "rainfall_mm", "river_level_m"}
    train_validation_intersections = {
        name: len(train["identity_sets"][name] & validation["identity_sets"][name])
        for name in (
            "window_id",
            "window_sha256",
            "station_family",
            "temporal_pattern_family",
            "anomaly_parameter_family",
            "parameter_combination_id",
            "trajectory_sha256",
        )
    }
    frozen_quality = _read_json(QUALITY_PATHS["ANOMALY"])
    feature_origin_checks = {
        "no_hidden_scenario_id_feature": not forbidden_used,
        "no_generator_parameter_id_feature": not forbidden_used,
        "no_ground_truth_label_feature": not forbidden_used,
        "no_future_window_leakage": set(detector_fields_used)
        == expected_detector_fields,
        "no_post_window_aggregation": set(detector_fields_used)
        == expected_detector_fields,
        "no_hidden_synthetic_metadata_feature": not forbidden_used,
        "no_train_validation_split_family_leakage": all(
            count == 0 for count in train_validation_intersections.values()
        ),
        "frozen_all_split_family_audit_passed": (
            frozen_quality["leakage_checks"]["status"] == "PASS"
        ),
    }
    return {
        "status": "PASS" if all(feature_origin_checks.values()) else "FAIL",
        "audit_scope": ["train", "validation"],
        "protected_test_model_inputs_read": False,
        "protected_test_labels_read": False,
        "protected_test_rows_read": 0,
        "feature_version": "anomaly-window-features-v1-synthetic-development",
        "feature_count": len(FEATURE_NAMES),
        "direct_discrimination_auc_threshold": DIRECT_SCENARIO_AUC_THRESHOLD,
        "feature_results": feature_results,
        "direct_scenario_features": direct_scenario_features,
        "direct_target_features": direct_target_features,
        "maximum_cross_split_directionless_auc": maximum_confirmed_auc,
        "validation_minimum_f1_from_frozen_development_manifest": round(
            minimum_validation_f1, 10
        ),
        "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": risk,
        "risk_rule": (
            "HIGH when any feature has same-direction one-vs-rest scenario AUC "
            ">=0.995 on both train and validation, or at least three features "
            "have same-direction target AUC >=0.995 with frozen validation F1 "
            ">=0.99; MODERATE for max AUC >=0.95 or F1 >=0.98; otherwise LOW."
        ),
        "feature_origin_audit": {
            "extractor_record_fields_used": detector_fields_used,
            "allowed_measurement_window_fields": sorted(expected_detector_fields),
            "forbidden_hidden_or_identifier_fields_used": forbidden_used,
            "extractor_source_sha256": hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest(),
            "checks": feature_origin_checks,
            "evidence": (
                "The extractor accepts only the strict detector-visible record and "
                "uses timestamps/rainfall/river-level values from that current "
                "24-observation window. It performs no joins, file reads, lookahead, "
                "or post-window query. Hidden metadata is loaded only by this audit "
                "to compare synthetic scenario labels against already-derived features."
            ),
        },
        "split_family_audit": {
            "train_validation_intersection_counts": train_validation_intersections,
            "scenario_family_overlap_is_expected_target_taxonomy": len(
                set(train["scenarios"].tolist()) & set(validation["scenarios"].tolist())
            ),
            "frozen_quality_report_all_split_leakage_checks": frozen_quality[
                "leakage_checks"
            ],
        },
        "split_integrity": {
            split: {
                "row_count": payload["row_count"],
                "model_input_sha256": payload["model_input_sha256"],
                "hidden_metadata_sha256": payload["hidden_metadata_sha256"],
                "checks": payload["integrity_checks"],
            }
            for split, payload in (
                ("train", train),
                ("validation", validation),
            )
        },
        "model_modified": False,
        "thresholds_modified": False,
        "training_invoked": False,
    }


def _component_policy_audit() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for component, spec in COMPONENT_SPECS.items():
        development = _read_json(ARTIFACT_ROOT / spec["development_manifest"])
        if component in {"NLP", "IMAGE"}:
            policy = development["policy"]
        else:
            artifact = _read_json(ARTIFACT_ROOT / spec["artifact_name"])
            if component == "ANOMALY":
                policy = {
                    "pretrained_models": artifact["pretrained_models"],
                    "open_weight_models": artifact["open_weight_models"],
                    "external_apis": artifact["external_apis"],
                    "network_access": artifact["network_access"],
                    "runtime_downloads": False,
                    "live_backend_modified": False,
                }
            else:
                policy = artifact["policy"]
        checks = {
            "pretrained_models_none": policy.get("pretrained_models") == [],
            "open_weight_models_none": policy.get("open_weight_models") == [],
            "external_apis_none": policy.get("external_apis") == [],
            "network_access_disabled": policy.get("network_access") is False,
            "runtime_downloads_disabled": policy.get("runtime_downloads", False)
            is False,
            "live_backend_not_modified": policy.get("live_backend_modified", False)
            is False,
        }
        rows[component] = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "policy_evidence": policy,
        }
    return {
        "status": (
            "PASS" if all(row["status"] == "PASS" for row in rows.values()) else "FAIL"
        ),
        "components": rows,
    }


def audit_network_isolation(
    *,
    legacy_audit: Mapping[str, Any] | None = None,
    boundary_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Separate the compliant frozen subsystem from the live legacy violation."""

    policy_scan = scan_new_ml_policy()
    policy = (
        policy_scan.model_dump(mode="json")
        if hasattr(policy_scan, "model_dump")
        else vars(policy_scan)
    )
    legacy = dict(legacy_audit or audit_legacy_embedding_references())
    boundary = dict(boundary_audit or audit_boundary_independence())
    component_policy = _component_policy_audit()
    six_component_pass = bool(
        policy["compliant"]
        and boundary["status"] == "PASS"
        and component_policy["status"] == "PASS"
    )
    repository_pass = bool(
        six_component_pass and not legacy["live_backend_depends_on_embedding_model"]
    )
    return {
        "status": "PASS" if repository_pass else "FAIL",
        "six_component_frozen_subsystem_status": (
            "PASS" if six_component_pass else "FAIL"
        ),
        "repository_live_runtime_status": ("PASS" if repository_pass else "FAIL"),
        "frozen_subsystem_network_access": "NONE",
        "failure_scope": (
            None
            if repository_pass
            else "LIVE_LEGACY_BACKEND_OUTSIDE_FROZEN_SIX_COMPONENT_SUBSYSTEM"
        ),
        "static_policy_scan": policy,
        "component_artifact_policy": component_policy,
        "boundary_independence": boundary,
        "legacy_embedding_runtime": legacy,
        "distinguished_non_inference_symbols": (
            "AST-based scanning evaluates imports, calls, checkpoint identifiers, "
            "and remote URL literals in production ML source; comments and ordinary "
            "standard-library symbols are not treated as network inference."
        ),
        "prohibited_runtime_capabilities": {
            "requests": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "urllib_inference": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "http_model_client": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "cloud_inference": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "api_sdk_inference": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "runtime_model_download": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "hugging_face_model_download": "ABSENT_IN_FROZEN_SUBSYSTEM",
            "remote_checkpoint_retrieval": "ABSENT_IN_FROZEN_SUBSYSTEM",
        },
    }


def build_production_readiness_matrix() -> list[dict[str, Any]]:
    """Return exactly one row and the requested columns for each component."""

    return [
        {
            "component": component,
            "implementation_status": spec["implementation_status"],
            "model_type": spec["model_type"],
            "training_source": spec["training_source"],
            "dataset_type": spec["dataset_type"],
            "dataset_hash": spec["dataset_sha256"],
            "validation_status": VALIDATION_STATUS,
            "protected_test_status": "FROZEN_ONE_SHOT_RECEIPT_VERIFIED",
            "production_validation_status": PRODUCTION_VALIDATION,
            "pretrained_model_used": False,
            "open_weight_model_used": False,
            "network_required": False,
            "backend_integration_status": "NOT_INTEGRATED_DEVELOPMENT_ONLY",
            "artifact_hash": spec["artifact_sha256"],
            "known_limitations": list(spec["known_limitations"]),
        }
        for component, spec in COMPONENT_SPECS.items()
    ]


def _code_and_configuration_hashes() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for component, spec in COMPONENT_SPECS.items():
        development_path = ARTIFACT_ROOT / spec["development_manifest"]
        development = _read_json(development_path)
        artifact = (
            _read_json(ARTIFACT_ROOT / spec["artifact_name"])
            if Path(spec["artifact_name"]).suffix == ".json"
            else None
        )
        if component == "NLP":
            configuration_hash = development["frozen_configuration_sha256"]
            origin = "PHASE_18_FROZEN_CONFIGURATION_SHA256"
        elif component == "DUPLICATE":
            configuration_hash = hashlib.sha256(
                canonical_json(
                    {
                        "feature_fit": development["feature_fit"],
                        "threshold_selection": development["threshold_selection"],
                        "calibration": development["calibration"],
                    }
                )
            ).hexdigest()
            origin = "PHASE_24_CANONICAL_HASH_OF_FROZEN_PHASE_19_CONFIGURATION"
        elif component == "EVENT":
            configuration_hash = hashlib.sha256(
                canonical_json(
                    {
                        "selected_configuration": development["selected_configuration"],
                        "cluster_constraints": development["cluster_constraints"],
                        "merge_logic": development["merge_logic"],
                    }
                )
            ).hexdigest()
            origin = "PHASE_24_CANONICAL_HASH_OF_FROZEN_PHASE_20_CONFIGURATION"
        elif component == "CREDIBILITY":
            assert artifact is not None
            configuration_hash = hashlib.sha256(
                canonical_json(
                    {
                        "selected_configuration": artifact["selected_configuration"],
                        "calibration": artifact["calibration"],
                        "thresholds": artifact["thresholds"],
                        "decision_logic": artifact["decision_logic"],
                        "feature_version": artifact["feature_version"],
                        "preprocessing_version": artifact["preprocessing_version"],
                    }
                )
            ).hexdigest()
            origin = "PHASE_24_CANONICAL_HASH_OF_FROZEN_PHASE_21_CONFIGURATION"
        elif component == "IMAGE":
            configuration_hash = hashlib.sha256(
                canonical_json(
                    {
                        "training_configuration": development["training_configuration"],
                        "thresholds": development["thresholds"],
                        "calibration": development["calibration"],
                        "architecture_version": development["architecture_version"],
                        "preprocessing_version": development["preprocessing_version"],
                    }
                )
            ).hexdigest()
            origin = "PHASE_24_CANONICAL_HASH_OF_FROZEN_PHASE_22_CONFIGURATION"
        else:
            configuration_hash = development["configuration_sha256"]
            origin = "PHASE_23_CONFIGURATION_SHA256"
        source_hashes = {
            key.replace("\\", "/"): value
            for key, value in development.get("source_hashes", {}).items()
        }
        if component == "EVENT":
            source_hashes = dict(development["frozen_files"])
        rows[component] = {
            "configuration_sha256": configuration_hash,
            "configuration_hash_origin": origin,
            "development_manifest_sha256": file_sha256(development_path),
            "source_hashes_where_available": source_hashes,
        }
    return rows


def _synthetic_dependence_risks(anomaly_audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "NLP": {
            "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": "MODERATE",
            "evidence": (
                "Synthetic-only multilingual templates with documented split-level "
                "template, location, lexicon, and time holdouts; no field corpus validation."
            ),
        },
        "DUPLICATE": {
            "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": "MODERATE",
            "evidence": (
                "Synthetic-only pair construction with incident, scenario-family, "
                "parameter-combination, and text overlap controls; no field-pair validation."
            ),
        },
        "EVENT": {
            "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": "HIGH",
            "evidence": (
                "Phase 20 held out canonical event identities but reused scenario "
                "templates and did not record parameter-family holdout evidence."
            ),
        },
        "CREDIBILITY": {
            "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": "HIGH",
            "evidence": (
                "Synthetic-only scenario labels and perfect synthetic holdout results "
                "do not establish general misinformation detection."
            ),
        },
        "IMAGE": {
            "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": "HIGH",
            "evidence": (
                "The scratch CNN was developed exclusively on project-rendered "
                "synthetic images; no real-photograph generalization evidence exists."
            ),
        },
        "ANOMALY": {
            "SYNTHETIC_GENERATOR_DEPENDENCE_RISK": anomaly_audit[
                "SYNTHETIC_GENERATOR_DEPENDENCE_RISK"
            ],
            "evidence": (
                f"{len(anomaly_audit['direct_scenario_features'])} of "
                f"{anomaly_audit['feature_count']} frozen features show unusually "
                "direct scenario discrimination on both train and validation; "
                "feature-origin and split-family checks nevertheless pass."
            ),
        },
    }


def _protected_hash_snapshot() -> dict[str, str]:
    paths: set[Path] = {ARTIFACT_ROOT / "manifest.json"}
    for component, spec in COMPONENT_SPECS.items():
        paths.update(
            {
                ARTIFACT_ROOT / spec["artifact_name"],
                ARTIFACT_ROOT / spec["receipt_name"],
                ARTIFACT_ROOT / spec["development_manifest"],
                QUALITY_PATHS[component],
                DATASET_MANIFEST_PATHS[component],
            }
        )
        paths.update(
            ARTIFACT_ROOT / name for name in spec.get("companion_artifacts", {})
        )
    return {
        path.relative_to(REPOSITORY_ROOT).as_posix(): file_sha256(path)
        for path in sorted(paths)
    }


def _component_manifest_rows(
    hash_audit: Mapping[str, Any],
    code_hashes: Mapping[str, Any],
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for component, spec in COMPONENT_SPECS.items():
        audit = hash_audit["components"][component]
        rows[component] = {
            "component_version": spec["artifact_version"],
            "artifact_name": spec["artifact_name"],
            "artifact_sha256": spec["artifact_sha256"],
            "companion_artifacts": audit["companion_artifacts"],
            "dataset_sha256": spec["dataset_sha256"],
            "dataset_manifest_sha256": audit["dataset_manifest_sha256"],
            "quality_report_sha256": audit["quality_report_sha256"],
            "development_manifest": spec["development_manifest"],
            "development_manifest_sha256": audit["development_manifest_sha256"],
            "protected_test_receipt": spec["receipt_name"],
            "protected_test_receipt_sha256": spec["receipt_sha256"],
            "implementation_status": spec["implementation_status"],
            "validation_status": VALIDATION_STATUS,
            "production_validation": PRODUCTION_VALIDATION,
            "code_and_configuration_hashes": code_hashes[component],
            "known_limitations": list(spec["known_limitations"]),
        }
    return rows


def _semantic_freeze() -> dict[str, Any]:
    return {
        "EVENT": {
            "modeling_status": "DETERMINISTIC_HEURISTIC_CONFIGURATION",
            "single_report_lifecycle": "CANDIDATE",
            "single_report_is_confirmed_event": False,
            "cluster_safeguard": "COMPLETE_LINK_ALL_MEMBER_PAIRS",
            "transitive_bridge_merge_permitted": False,
            "automatic_single_report_confirmation": False,
        },
        "CREDIBILITY": {
            "development_status": "SYNTHETIC_DEVELOPMENT_ONLY",
            "output_labels": ["AUTHENTIC", "MISLEADING", "UNCERTAIN"],
            "model_output_is_ground_truth": False,
            "universal_misinformation_detection_claimed": False,
        },
        "IMAGE": {
            "task_semantics": "MULTI_LABEL",
            "model": "SCRATCH_CNN_V2",
            "validation": "SYNTHETIC_DEVELOPMENT_ONLY",
            "real_photograph_generalization_claimed": False,
        },
        "ANOMALY": {
            "separate_heads": [
                "DATA_QUALITY_ANOMALY",
                "WEATHER_BEHAVIOR_ANOMALY",
            ],
            "statistical_baseline_preserved": True,
            "learned_model": "LOCAL_SCRATCH_DUAL_LOGISTIC",
            "validation": "SYNTHETIC_DEVELOPMENT_ONLY",
        },
    }


def build_final_freeze_manifest(
    *,
    frozen_at: datetime | None = None,
    test_regression: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Phase 24 evidence document without modifying frozen inputs."""

    before = _protected_hash_snapshot()
    hash_audit = audit_frozen_hashes()
    receipts = audit_protected_receipts()
    legacy = audit_legacy_embedding_references()
    boundary = audit_boundary_independence()
    leakage = audit_global_data_leakage()
    reproducibility = audit_artifact_reproducibility()
    anomaly = audit_anomaly_feature_separability()
    network = audit_network_isolation(
        legacy_audit=legacy,
        boundary_audit=boundary,
    )
    after = _protected_hash_snapshot()
    unchanged = before == after
    timestamp = frozen_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("freeze timestamp must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    code_hashes = _code_and_configuration_hashes()
    matrix = build_production_readiness_matrix()
    synthetic_risks = _synthetic_dependence_risks(anomaly)
    regression = dict(
        test_regression
        or {
            "status": "NOT_RECORDED",
            "protected_final_test_evaluations_rerun": False,
        }
    )
    return {
        "manifest_schema_version": "1.0",
        "freeze_version": FREEZE_VERSION,
        "phase": "24 — SIX-COMPONENT FINAL AI/ML FREEZE",
        "frozen_at": timestamp.isoformat().replace("+00:00", "Z"),
        "freeze_date": timestamp.date().isoformat(),
        "global_final_status": {
            "AI_ML_STATUS": "AUDIT_COMPLETE",
            "VALIDATION_STATUS": VALIDATION_STATUS,
            "PRODUCTION_VALIDATION": PRODUCTION_VALIDATION,
            "PRETRAINED_MODELS": "NONE",
            "OPEN_WEIGHT_MODELS": "NONE",
            "EXTERNAL_APIS": "NONE",
            "NETWORK_ACCESS": "NONE",
            "LIVE_BACKEND_MODIFIED": "NO",
            "scope_note": (
                "NETWORK_ACCESS NONE describes the frozen six-component subsystem. "
                "The repository-wide runtime network-isolation audit is FAIL because "
                "the separately scoped live legacy MiniLM path can attempt remote "
                "model resolution when uncached."
            ),
        },
        "critical_limitation": (
            "Synthetic benchmark performance must not be interpreted as field or "
            "production accuracy."
        ),
        "component_count": len(COMPONENT_SPECS),
        "components": _component_manifest_rows(hash_audit, code_hashes),
        "production_readiness_matrix_columns": [
            "component",
            "implementation_status",
            "model_type",
            "training_source",
            "dataset_type",
            "dataset_hash",
            "validation_status",
            "protected_test_status",
            "production_validation_status",
            "pretrained_model_used",
            "open_weight_model_used",
            "network_required",
            "backend_integration_status",
            "artifact_hash",
            "known_limitations",
        ],
        "production_readiness_matrix": matrix,
        "semantic_freeze": _semantic_freeze(),
        "artifact_hash_audit": hash_audit,
        "protected_test_receipt_audit": receipts,
        "protected_evidence_immutability": {
            "status": (
                "PASS" if unchanged and hash_audit["status"] == "PASS" else "FAIL"
            ),
            "before": before,
            "after": after,
            "all_hashes_unchanged_during_phase_24_audit": unchanged,
            "protected_test_evaluations_rerun": False,
        },
        "global_data_leakage_audit": leakage,
        "artifact_reproducibility_audit": reproducibility,
        "network_isolation_audit": network,
        "boundary_independence_audit": boundary,
        "legacy_minilm_audit": legacy,
        "anomaly_feature_separability_audit": anomaly,
        "synthetic_dependence_risks": synthetic_risks,
        "test_regression": regression,
        "phase_24_mutations": {
            "retrained": False,
            "retuned": False,
            "rebalanced": False,
            "thresholds_modified": False,
            "architectures_modified": False,
            "protected_test_sets_regenerated": False,
            "protected_final_tests_rerun": False,
            "live_backend_modified": False,
        },
    }


def write_final_freeze_manifest(
    path: Path | str = DEFAULT_FINAL_FREEZE_PATH,
    *,
    frozen_at: datetime | None = None,
    test_regression: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the final manifest exactly once; existing files are never replaced."""

    destination = Path(path)
    if destination.exists():
        raise FileExistsError(f"final freeze manifest already exists: {destination}")
    payload = dict(
        manifest
        or build_final_freeze_manifest(
            frozen_at=frozen_at,
            test_regression=test_regression,
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return payload
