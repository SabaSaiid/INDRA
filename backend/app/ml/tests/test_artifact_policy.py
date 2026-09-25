"""AST-based policy checks for new ML production code.

The legacy MiniLM module is intentionally excluded and documented as legacy.
Any new production Python file under app/ml is scanned structurally.
"""

import ast
from pathlib import Path

import pytest

from app.ml.data.annotations import AnnotationStore
from app.ml.data.candidate_pairs import load_local_reports
from app.ml.data.loaders import load_csv
from app.ml.data.versioning import source_file_sha256

ML_ROOT = Path(__file__).resolve().parents[1]
LEGACY_FILES = {ML_ROOT / "event_classifier.py"}
EXCLUDED_DIRS = {ML_ROOT / "tests", ML_ROOT / "artifacts"}


def production_sources():
    for path in ML_ROOT.rglob("*.py"):
        if path in LEGACY_FILES or any(parent in EXCLUDED_DIRS for parent in path.parents):
            continue
        yield path


def _forbidden_module_parts():
    sentence_package = "sentence" + "_" + "transformers"
    return {
        sentence_package,
        "transformers",
        "huggingface_hub",
        "openai",
        "anthropic",
        "google.generativeai",
    }


def test_new_ml_source_has_no_prohibited_imports_or_model_construction():
    prohibited_modules = _forbidden_module_parts()
    prohibited_names = {
        "Sentence" + "Transformer",
        "from_pretrained",
        "snapshot_download",
        "hf_hub_download",
    }
    checkpoint = "all" + "-" + "MiniLM" + "-" + "L6-v2"
    violations = []

    for path in production_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in prohibited_modules:
                        violations.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in prohibited_modules:
                    violations.append(f"{path}: from {node.module} import ...")
                for alias in node.names:
                    if alias.name in prohibited_names:
                        violations.append(f"{path}: imported {alias.name}")
            elif isinstance(node, ast.Call):
                function_name = ""
                if isinstance(node.func, ast.Name):
                    function_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    function_name = node.func.attr
                if function_name in prohibited_names:
                    violations.append(f"{path}: call {function_name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if checkpoint in node.value:
                    violations.append(f"{path}: prohibited checkpoint identifier")

    assert violations == [], "\n".join(violations)


def test_legacy_policy_violation_is_explicitly_quarantined():
    assert (ML_ROOT / "event_classifier.py").exists()
    assert (ML_ROOT / "artifacts" / "event_classifier_v1.joblib").exists()
    manifest = (ML_ROOT / "artifacts" / "manifest.json").read_text(encoding="utf-8")
    assert "event_classifier_v1.joblib" in manifest


def test_new_ml_source_has_no_network_or_backend_runtime_dependencies():
    prohibited_roots = {
        "aiohttp",
        "aiokafka",
        "asyncpg",
        "boto3",
        "fastapi",
        "httpx",
        "kafka",
        "redis",
        "requests",
        "socket",
        "sqlalchemy",
        "urllib",
        "urllib3",
    }
    prohibited_app_prefixes = (
        "app.api",
        "app.auth",
        "app.core",
        "app.db",
        "app.database",
        "app.models",
        "app.services",
        "app.workers",
    )
    prohibited_calls = {
        "get",
        "post",
        "request",
        "urlopen",
        "create_connection",
    }
    violations: list[str] = []
    for path in production_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_network_aliases: set[str] = set()
        for node in ast.walk(tree):
            modules: list[tuple[str, str]] = []
            if isinstance(node, ast.Import):
                modules = [
                    (alias.name, alias.asname or alias.name.split(".")[0])
                    for alias in node.names
                ]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "", node.module or "")]
            for module, alias in modules:
                root = module.split(".")[0]
                if root in prohibited_roots:
                    violations.append(f"{path}: prohibited import {module}")
                    imported_network_aliases.add(alias)
                if module.startswith(prohibited_app_prefixes):
                    violations.append(f"{path}: backend-boundary import {module}")
                if module == "app.ml.event_classifier":
                    violations.append(f"{path}: legacy classifier import")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id in imported_network_aliases
                    and node.func.attr in prohibited_calls
                ):
                    violations.append(f"{path}: network call {node.func.attr}")
    assert violations == [], "\n".join(violations)


def test_retired_embedding_package_is_absent_from_runtime_requirements():
    requirements = ML_ROOT.parents[1] / "requirements.txt"
    assert "sentence-transformers" not in requirements.read_text(encoding="utf-8")
    imports_legacy = []
    for path in production_sources():
        source = path.read_text(encoding="utf-8")
        if "sentence_transformers" in source or "sentence-transformers" in source:
            imports_legacy.append(str(path))
    assert imports_legacy == []


def test_all_local_file_boundaries_reject_url_and_unc_network_paths():
    with pytest.raises(ValueError, match="remote dataset paths"):
        load_csv("https://example.invalid/reports.csv")
    with pytest.raises(ValueError, match="remote report paths"):
        load_local_reports(r"\\example.invalid\share\reports.json")
    with pytest.raises(ValueError, match="remote dataset sources"):
        source_file_sha256(r"\\example.invalid\share\labels.jsonl")
    with pytest.raises(ValueError, match="remote annotation paths"):
        AnnotationStore(r"\\example.invalid\share\annotations.jsonl")
