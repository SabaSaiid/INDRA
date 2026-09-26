"""Phase 25 static startup and isolated backend adapter checks."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def test_frozen_duplicate_adapter_under_socket_denial():
    """Use a child process so missing transport dependencies stay out of ML tests."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("phase25_adapter_probe.py"))],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "artifact_loaded": True,
        "missing_inference_fail_closed": True,
        "ordered_first_match": True,
        "socket_denial": "PASS",
    }


def test_live_backend_path_has_no_model_loader_or_remote_identifier():
    paths = [
        BACKEND_ROOT / "app/main.py",
        BACKEND_ROOT / "app/services/pipeline.py",
        BACKEND_ROOT / "app/services/dedup.py",
    ]
    forbidden_imports = {"sentence_transformers", "transformers", "huggingface_hub"}
    forbidden_calls = {
        "SentenceTransformer",
        "from_pretrained",
        "hf_hub_download",
        "snapshot_download",
    }
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert "all-MiniLM" not in source
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] not in forbidden_imports
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                )
                assert name not in forbidden_calls
    main_source = paths[0].read_text(encoding="utf-8")
    pipeline_source = paths[1].read_text(encoding="utf-8")
    assert "_get_local_matcher" in main_source
    assert "DedupService" in pipeline_source
    assert "find_duplicate" in pipeline_source
