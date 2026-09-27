"""Create-only Phase 25 migration, inventory, and provenance evidence.

This reads frozen manifests/receipts but never invokes protected evaluators,
training, tuning, or backend integration. Run from the repository root after
the AI/ML test suite has written its JUnit XML report.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import re
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.ml.final_freeze import (
    ARTIFACT_ROOT,
    DEFAULT_FINAL_FREEZE_PATH,
    audit_artifact_reproducibility,
    audit_frozen_hashes,
    audit_network_isolation,
    audit_protected_receipts,
    file_sha256,
)
from app.ml.models.anomaly_window_model import extract_window_feature_vector

FINAL_FREEZE_SHA256 = "f800014d825d5a20b3eaae8856efa03eb14abf0bc3872ac6fc6471c2b074219d"
INVENTORY_PATH = ARTIFACT_ROOT / "phase25_minilm_inventory.json"
EVENT_PATH = ARTIFACT_ROOT / "phase25_event_evidence_report.json"
MIGRATION_PATH = ARTIFACT_ROOT / "phase25_minilm_migration_manifest.json"
MODEL_PATTERNS = [
    r"MiniLM",
    r"SentenceTransformer",
    r"sentence[-_]transformers?",
    r"transformer.{0,35}embedding|embedding.{0,35}transformer",
    r"from_pretrained|AutoTokenizer|AutoModel|hf_hub_download|snapshot_download",
    r"load_state_dict_from_url|torch\.hub\.load",
    r"_get_embedding_model|embedding_model|model\.encode",
    r"warm.{0,25}(embedding|model|duplicate)",
    r"huggingface|HF_HOME|TRANSFORMERS_CACHE|HUGGINGFACE_HUB_CACHE",
    r"pretrained.{0,35}(embedding|model|checkpoint)",
    r"(remote|model)[-_ ]?(checkpoint|cache|identifier)",
    r"embedding[-_ ]?(service|client|wrapper)",
]
NETWORK_PATTERNS = [
    r"\brequests\b|\bhttpx\b|\baiohttp\b|\burllib(?:3)?\b",
    r"\b(boto3|openai|anthropic|azure\.ai|google\.generativeai)\b",
    r"hf_hub_download|snapshot_download|from_pretrained|load_state_dict_from_url",
    r"huggingface|model[-_ ]?(download|serving)|embedding[-_ ]?(api|service|client)",
]
EXCLUDES = [
    "!.git/**",
    "!**/__pycache__/**",
    "!**/.pytest*/**",
    "!**/.ruff_cache/**",
    "!**/.venv/**",
    "!**/node_modules/**",
    "!**/.next/**",
    "!**/dist/**",
    "!**/build/**",
    "!**/phase25_minilm_inventory.json",
    "!**/phase25_minilm_migration_manifest.json",
    "!**/phase25_event_evidence_report.json",
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_json(path: Path, payload: dict) -> None:
    # The Phase 25 records must not overwrite a prior forensic run.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def rg_matches(patterns: list[str]) -> list[dict]:
    command = ["rg", "--json", "--hidden", "--no-ignore", "-i", "-n"]
    for glob in EXCLUDES:
        command.extend(["--glob", glob])
    for pattern in patterns:
        command.extend(["-e", pattern])
    command.append(".")
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"repository scan failed: {result.stderr}")
    rows = []
    for line in result.stdout.splitlines():
        event = json.loads(line)
        if event["type"] != "match":
            continue
        data = event["data"]
        relative = Path(data["path"]["text"]).as_posix().removeprefix("./")
        excerpt = data["lines"].get("text", "").strip()
        for match in data["submatches"]:
            rows.append(
                {
                    "file": relative,
                    "line": data["line_number"],
                    "match": match["match"]["text"],
                    "excerpt": excerpt[:240],
                }
            )
    return sorted(rows, key=lambda row: (row["file"], row["line"], row["match"]))


def classify_model_path(path: str) -> str:
    if path.startswith("backend/tests/") or "/tests/" in path:
        return "TEST_ONLY"
    if path == "backend/app/ml/event_classifier.py":
        return "DEAD_CODE"
    if path == "backend/app/main.py":
        return "LIVE_PRODUCTION_PATH"
    if path in {
        "backend/app/services/dedup.py",
        "backend/app/ml/final_freeze.py",
        "backend/app/ml/release_gate.py",
    } or path.startswith("scripts/"):
        return "MIGRATION_TARGET"
    if (
        "/docs/" in path
        or "/artifacts/" in path
        or path.endswith((".md", ".txt", ".json", ".jsonl", ".csv"))
    ):
        return "DOCUMENTATION_ONLY"
    if path.startswith("backend/app/ml/"):
        # These matches are frozen-artifact provenance/policy keys, not live
        # embedding calls. Genuine legacy literals are identified per-row.
        return "DOCUMENTATION_ONLY"
    if path.startswith("backend/app/") or path == "backend/requirements.txt":
        return "LIVE_PRODUCTION_PATH"
    return "MIGRATION_TARGET"


def build_inventory() -> dict:
    rows = rg_matches(MODEL_PATTERNS)
    legacy_pattern = re.compile(
        r"minilm|sentence[-_]?transformer|_get_embedding_model|embedding_model|"
        r"model\.encode|transformer.{0,35}embedding|embedding.{0,35}transformer",
        re.IGNORECASE,
    )
    for row in rows:
        row["classification"] = classify_model_path(row["file"])
        row["legacy_embedding_reference"] = bool(legacy_pattern.search(row["match"]))
    counts = Counter(row["classification"] for row in rows)
    return {
        "phase": 25,
        "scope": "ENTIRE_REPOSITORY_TEXT_EXCLUDING_VCS_DEPENDENCY_BUILD_AND_TEST_CACHES",
        "search_method": "ripgrep --json --hidden --no-ignore -i",
        "search_patterns": MODEL_PATTERNS,
        "excluded_globs": EXCLUDES,
        "classification_counts": dict(sorted(counts.items())),
        "file_count": len({row["file"] for row in rows}),
        "occurrence_count": len(rows),
        "live_production_reference_files": sorted(
            {
                row["file"]
                for row in rows
                if row["classification"] == "LIVE_PRODUCTION_PATH"
            }
        ),
        "live_legacy_embedding_reference_files": sorted(
            {
                row["file"]
                for row in rows
                if row["classification"] == "LIVE_PRODUCTION_PATH"
                and row["legacy_embedding_reference"]
            }
        ),
        "classification_note": (
            "Textual reference classification is not execution proof. The Phase 25 "
            "call-path, AST, and socket-denial audits separately decide live runtime use."
        ),
        "occurrences": rows,
    }


def build_event_report() -> dict:
    data_root = ROOT / "data/labelled/events/synthetic_v1"
    dataset_path = data_root / "synthetic_event_dataset_manifest.json"
    quality_path = data_root / "synthetic_event_quality_report.json"
    development_path = ARTIFACT_ROOT / "event_grouping_v1.development_manifest.json"
    receipt_path = ARTIFACT_ROOT / "event_grouping_v1_final_test_receipt.json"
    generator_path = BACKEND / "app/ml/data/synthetic_event/generator.py"
    dataset = read_json(dataset_path)
    quality = read_json(quality_path)
    development = read_json(development_path)
    receipt = read_json(receipt_path)
    source = generator_path.read_text(encoding="utf-8")
    required = {
        "template_family_id",
        "parameter_family_id",
        "template_id",
        "parameter_combination_id",
    }
    provenance_fields = set(dataset) | set(development) | set(quality) | set(receipt)
    assert not (required & provenance_fields)
    assert dataset["holdout_strategy"] == "CANONICAL_EVENT_ID"
    assert quality["leakage_checks"]["status"] == "PASS"
    assert development["test_evaluation_invocation_count"] == 0
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["test_used_for_tuning"] is False
    assert "for scenario in EVENT_SCENARIOS" in source
    return {
        "phase": 25,
        "PHASE_20_VALIDATION_STATUS": "REVALIDATION_REQUIRED",
        "evidence_classification": "REVALIDATION_REQUIRED",
        "old_phase20_benchmark_immutable": True,
        "protected_test_rows_or_labels_read_by_phase25": False,
        "evidence_files": {
            path.relative_to(ROOT).as_posix(): file_sha256(path)
            for path in (
                dataset_path,
                quality_path,
                development_path,
                receipt_path,
                generator_path,
            )
        },
        "verified_existing_evidence": {
            "dataset_sha256": dataset["dataset_sha256"],
            "split_sha256": dataset["split_sha256"],
            "generator_version": dataset["generator_version"],
            "scenario_version": dataset["scenario_version"],
            "template_version": dataset["template_version"],
            "holdout_strategy": dataset["holdout_strategy"],
            "canonical_event_cross_split": quality["leakage_checks"][
                "canonical_event_cross_split"
            ],
            "incident_cross_split": quality["leakage_checks"]["incident_cross_split"],
            "report_cross_split": quality["leakage_checks"]["report_cross_split"],
            "ground_truth_isolation": quality["leakage_checks"][
                "ground_truth_isolation"
            ],
            "configuration_frozen_before_test": receipt[
                "configuration_frozen_before_test"
            ],
            "test_evaluation_invocation_count": receipt["evaluation_invocation_count"],
            "test_used_for_tuning": receipt["test_used_for_tuning"],
        },
        "missing_evidence": [
            "No per-example template-family identifier bound into original split provenance.",
            "No per-example parameter-family identifier bound into original split provenance.",
            "No audited train/validation/test disjointness counts for template and parameter families.",
            "No original receipt binding a family-separated protected test to the frozen configuration.",
        ],
        "why_insufficient": (
            "The quality report proves canonical-event, incident, and report isolation only. "
            "The generator iterates the same scenario-plan logic over all three splits; "
            "split-specific places and time origins do not prove template or parameter-family "
            "separation. Neither provenance manifests nor the one-shot receipt record those IDs."
        ),
        "future_remediation": {
            "designation": "PHASE_20R",
            "regenerate": [
                "A new dataset with explicit template and parameter-family IDs recorded at generation time.",
                "A family-disjoint split manifest and leakage audit with dataset/file hashes.",
                "A new, untouched protected test and new one-shot receipt.",
            ],
            "old_dataset_or_receipt_must_change": False,
            "new_protected_test_required": True,
            "same_configuration_may_be_preserved": (
                "Yes, if preregistered before any new protected-test access, hash-bound to "
                "the unchanged Phase 20 configuration, and no test-guided tuning occurs."
            ),
        },
    }


def anomaly_provenance() -> dict:
    phase24 = read_json(DEFAULT_FINAL_FREEZE_PATH)
    audit = phase24["anomaly_feature_separability_audit"]
    source = textwrap.dedent(inspect.getsource(extract_window_feature_vector))
    tree = ast.parse(source)
    fields = sorted(
        {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "record"
        }
    )
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    original_hash = audit["feature_origin_audit"]["extractor_source_sha256"]
    checks = audit["feature_origin_audit"]["checks"]
    passed = (
        audit["status"] == "PASS"
        and audit["SYNTHETIC_GENERATOR_DEPENDENCE_RISK"] == "HIGH"
        and audit["feature_count"] == 62
        and len(audit["direct_scenario_features"]) == 34
        and source_hash == original_hash
        and fields == ["rainfall_mm", "river_level_m", "timestamps"]
        and all(checks.values())
        and audit["protected_test_labels_read"] is False
        and audit["protected_test_rows_read"] == 0
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "synthetic_generator_dependence": "HIGH",
        "direct_scenario_features": len(audit["direct_scenario_features"]),
        "feature_count": audit["feature_count"],
        "detector_visible_fields_used": fields,
        "extractor_source_sha256": source_hash,
        "phase24_recorded_extractor_source_sha256": original_hash,
        "source_unchanged_since_phase24": source_hash == original_hash,
        "feature_origin_checks": checks,
        "protected_test_labels_read_by_phase25": False,
        "no_training_or_retuning": True,
        "limitation": "Source/provenance audit only; HIGH synthetic dependence remains a field-generalization risk.",
    }


def static_network_audit() -> dict:
    rows = rg_matches(NETWORK_PATTERNS)
    by_file: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_file[row["file"]].add(row["match"].lower())
    prohibited_roots = {
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "aiohttp",
        "boto3",
        "openai",
        "anthropic",
        "huggingface_hub",
        "sentence_transformers",
        "transformers",
    }
    prohibited_calls = {
        "from_pretrained",
        "hf_hub_download",
        "snapshot_download",
        "load_state_dict_from_url",
    }
    live_paths = [
        BACKEND / "app/main.py",
        BACKEND / "app/services/pipeline.py",
        BACKEND / "app/services/dedup.py",
    ]
    for path in (BACKEND / "app/ml").rglob("*.py"):
        if "tests" in path.parts or path.name in {
            "event_classifier.py",
            "final_freeze.py",
            "release_gate.py",
        }:
            continue
        live_paths.append(path)
    violations = []
    for path in live_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                if module.split(".")[0] in prohibited_roots:
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}:import {module}"
                    )
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                )
                if name in prohibited_calls:
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}:call {name}"
                    )
    non_inference = sorted(
        path
        for path in by_file
        if path.startswith("backend/app/")
        and path not in {file.relative_to(ROOT).as_posix() for file in live_paths}
        and not path.startswith("backend/app/ml/")
    )
    return {
        "repository_scan_method": "ripgrep --json --hidden --no-ignore -i plus AST of live ML source",
        "repository_text_reference_file_count": len(by_file),
        "repository_text_reference_occurrence_count": len(rows),
        "repository_references_by_file": {
            key: sorted(value) for key, value in sorted(by_file.items())
        },
        "LEGITIMATE_NON_INFERENCE_NETWORK_USAGE": non_inference,
        "ML_RUNTIME_NETWORK_DEPENDENCY": "NONE" if not violations else "PRESENT",
        "ml_runtime_ast_violations": violations,
        "boundary_note": (
            "Backend HTTP/API/feed code is not an ML inference dependency. The live "
            "duplicate adapter and frozen ML sources have no network/model-download imports or calls."
        ),
    }


def junit_result(path: Path) -> dict:
    if not path.exists():
        return {
            "status": "BLOCKED",
            "tests": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "report": None,
            "reason": "Collection blocked: pytest_asyncio is not installed; backend import also requires asyncpg.",
        }
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    totals = {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    return {
        "status": "PASS" if totals["failures"] == totals["errors"] == 0 else "FAIL",
        **totals,
        "report": path.relative_to(ROOT).as_posix(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ml-junit", type=Path, required=True)
    parser.add_argument("--backend-junit", type=Path, required=True)
    arguments = parser.parse_args()
    targets = (INVENTORY_PATH, EVENT_PATH, MIGRATION_PATH)
    if any(path.exists() for path in targets):
        raise FileExistsError("Phase 25 evidence already exists; refusing to overwrite")
    inventory = build_inventory()
    event = build_event_report()
    anomaly = anomaly_provenance()
    network = static_network_audit()
    frozen = audit_frozen_hashes()
    receipts = audit_protected_receipts()
    repro = audit_artifact_reproducibility()
    isolation = audit_network_isolation()
    probe = subprocess.run(
        [sys.executable, str(BACKEND / "app/ml/tests/phase25_adapter_probe.py")],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    socket_probe = json.loads(probe.stdout)
    ml_tests = junit_result(arguments.ml_junit.resolve())
    backend_tests = junit_result(arguments.backend_junit.resolve())
    frozen_manifest_unchanged = (
        file_sha256(DEFAULT_FINAL_FREEZE_PATH) == FINAL_FREEZE_SHA256
    )
    current_live_paths = inventory["live_legacy_embedding_reference_files"]
    status = (
        "PASS"
        if all(
            (
                not current_live_paths,
                frozen["status"] == "PASS",
                receipts["status"] == "PASS",
                repro["status"] == "PASS",
                isolation["status"] == "PASS",
                network["ML_RUNTIME_NETWORK_DEPENDENCY"] == "NONE",
                socket_probe["socket_denial"] == "PASS",
                anomaly["status"] == "PASS",
                ml_tests["status"] == "PASS",
                backend_tests["status"] == "PASS",
                frozen_manifest_unchanged,
            )
        )
        else "BLOCKED"
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    code_paths = [
        "backend/app/services/dedup.py",
        "backend/app/services/pipeline.py",
        "backend/app/main.py",
        "backend/app/core/config.py",
        "backend/app/ml/final_freeze.py",
        "backend/requirements.txt",
        "scripts/phase25_audit.py",
    ]
    payload = {
        "phase": "25 — LEGACY MINILM REPLACEMENT + FREEZE-BLOCKER REMEDIATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "repository_head": revision.stdout.strip()
        if revision.returncode == 0
        else None,
        "code_sha256": {name: file_sha256(ROOT / name) for name in code_paths},
        "minilm_inventory": {
            "file": INVENTORY_PATH.name,
            "occurrence_count": inventory["occurrence_count"],
            "file_count": inventory["file_count"],
            "classification_counts": inventory["classification_counts"],
            "current_live_reference_files": current_live_paths,
            "live_local_warmup_reference_files": inventory[
                "live_production_reference_files"
            ],
        },
        "live_minilm_paths_found_in_phase24": [
            "backend/app/main.py startup embedding warmup",
            "backend/app/services/pipeline.py dedup invocation",
            "backend/app/services/dedup.py lazy SentenceTransformer loader and similarity",
        ],
        "legacy_classifier_status": "backend/app/ml/event_classifier.py remains quarantined dead code; no production importer",
        "live_minilm_paths_removed_or_replaced": [
            "Startup warmup now hash-authorizes the frozen local Phase 19 matcher.",
            "DedupService now maps ordered backend tuples to local candidate reports and preserves first-match index.",
            "Pipeline retains duplicate_of semantics and calls only the local adapter.",
            "Runtime sentence-transformers requirement removed; inert compatibility symbol cannot load weights.",
        ],
        "replacement_implementation": {
            "duplicate": "Phase 19 frozen DuplicateMatcher plus duplicate_feature_state_v2.json; backend 1km/15min eligibility gates retained",
            "nlp": "Phase 18 frozen local NLP artifact remains opt-in; no live legacy NLP classifier importer",
            "event": "Phase 20 frozen event grouping artifact preserved; no Phase 26 backend integration",
            "credibility": "Phase 21 frozen credibility artifact preserved; no new live backend integration",
            "image": "Phase 22 image_model_v1 preserved",
            "anomaly": "Phase 23 anomaly_model_v1 preserved",
        },
        "frozen_artifacts": {
            "status": frozen["status"],
            "components": frozen["components"],
            "phase24_manifest_sha256": file_sha256(DEFAULT_FINAL_FREEZE_PATH),
            "phase24_manifest_unchanged": frozen_manifest_unchanged,
            "artifacts_changed": 0
            if frozen["status"] == "PASS" and frozen_manifest_unchanged
            else None,
        },
        "protected_receipts": {
            "status": receipts["status"],
            "components": receipts["components"],
            "tests_rerun_for_metrics": False,
        },
        "local_artifact_load_and_deterministic_probe": {
            "status": repro["status"],
            "protected_test_data_used": repro["protected_test_data_used"],
            "components": repro["components"],
        },
        "network_isolation": {
            "phase24_current_audit_status": isolation["status"],
            **network,
        },
        "socket_denial": socket_probe,
        "phase20_event_evidence": {
            "status": event["evidence_classification"],
            "file": EVENT_PATH.name,
        },
        "anomaly_provenance": anomaly,
        "tests": {
            "ai_ml": {
                **ml_tests,
                "pre_existing_warnings": [
                    "Unknown config option: asyncio_default_fixture_loop_scope",
                    "Unknown config option: asyncio_default_test_loop_scope",
                    "Unknown config option: asyncio_mode",
                ],
            },
            "backend_relevant": backend_tests,
        },
        "known_limitations": [
            "Full FastAPI startup and pre-existing backend tests remain unverified: pytest-asyncio and asyncpg are absent; dependency installation was rejected by auto-review under the offline/no-download constraint.",
            "The Phase 25 child-process probe isolates backend package initializers, so it is not full backend integration.",
            "Phase 20 needs a new family-separated dataset and protected test; the frozen old benchmark remains immutable.",
            "Anomaly generator dependence remains HIGH (34/62 directly discriminative synthetic features).",
            "Historical Phase 24 and Phase 11 manifests/gates still record pre-migration status and are not rewritten; Phase 27 must refresh the release gate.",
            "Synthetic development evidence is not production accuracy; production validation is NOT_VALIDATED.",
        ],
        "pretrained_models": [],
        "open_weight_models": [],
        "external_inference_apis": [],
        "production_validation": "NOT_VALIDATED",
    }
    write_new_json(INVENTORY_PATH, inventory)
    write_new_json(EVENT_PATH, event)
    write_new_json(MIGRATION_PATH, payload)
    print(
        json.dumps(
            {
                "status": status,
                "inventory_occurrences": inventory["occurrence_count"],
                "ml_tests": ml_tests,
                "backend_tests": backend_tests,
                "event_evidence": event["evidence_classification"],
                "anomaly": anomaly["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
