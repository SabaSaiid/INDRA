"""Isolated Phase 25 dedup probe; does not initialize database or transport.

The backend's package initializers eagerly import asyncpg and service modules.
Those optional transport dependencies are absent in this environment. This
probe exposes only package paths, then imports the unchanged dedup module to
exercise its real local matcher and backend-facing contract. It is not a full
FastAPI startup or pipeline-integration test.
"""

from __future__ import annotations

import builtins
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

BACKEND_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_ROOT))
for package_name, subdirectory in (
    ("app.core", "core"),
    ("app.services", "services"),
):
    package = ModuleType(package_name)
    package.__path__ = [str(BACKEND_ROOT / "app" / subdirectory)]
    sys.modules[package_name] = package

from app.services import dedup

LAT = 25.5941
LNG = 85.1376
NOW = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
TEXT = "Flood at Kankarbagh, water knee deep"


def candidate(
    text: str = TEXT, *, lat: float = LAT, minutes: int = 0
) -> tuple[str, float, float, datetime]:
    return text, lat, LNG, NOW + timedelta(minutes=minutes)


def main() -> None:
    original_import = builtins.__import__
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_loader = dedup._get_local_matcher

    def reject_model_packages(name, *args, **kwargs):
        if name.split(".")[0] in {
            "sentence_transformers",
            "transformers",
            "huggingface_hub",
        }:
            raise AssertionError(f"external embedding package imported: {name}")
        return original_import(name, *args, **kwargs)

    def reject_socket(*args, **kwargs):
        raise AssertionError("model inference attempted socket access")

    def missing():
        raise FileNotFoundError("frozen matcher unavailable")

    payload = {
        "artifact_loaded": False,
        "missing_inference_fail_closed": False,
        "ordered_first_match": False,
        "socket_denial": "FAIL",
    }
    try:
        builtins.__import__ = reject_model_packages
        socket.socket.connect = reject_socket
        socket.socket.connect_ex = reject_socket
        socket.create_connection = reject_socket
        socket.getaddrinfo = reject_socket
        service = dedup.DedupService()
        assert service.find_duplicate(TEXT, LAT, LNG, NOW, []) is None
        assert service.find_duplicate(TEXT, LAT, LNG, NOW, [candidate()]) == 0
        payload["artifact_loaded"] = True
        assert (
            service.find_duplicate(
                TEXT,
                LAT,
                LNG,
                NOW,
                [
                    candidate("Traffic signal broken at Danapur crossing"),
                    candidate(),
                    candidate(),
                ],
            )
            == 1
        )
        assert (
            service.find_duplicate(
                TEXT, LAT, LNG, NOW, [candidate(lat=LAT + 0.008, minutes=14)]
            )
            == 0
        )
        assert (
            service.find_duplicate(TEXT, LAT, LNG, NOW, [candidate(lat=LAT + 0.010)])
            is None
        )
        assert (
            service.find_duplicate(TEXT, LAT, LNG, NOW, [candidate(minutes=16)]) is None
        )
        assert (
            service.find_duplicate(
                TEXT,
                LAT,
                LNG,
                NOW,
                [candidate("Traffic signal broken at Danapur crossing")],
            )
            is None
        )
        payload["ordered_first_match"] = True
        assert dedup._get_embedding_model() is None
        dedup._get_local_matcher = missing
        try:
            service.find_duplicate(TEXT, LAT, LNG, NOW, [candidate()])
        except FileNotFoundError:
            payload["missing_inference_fail_closed"] = True
        payload["socket_denial"] = "PASS"
    finally:
        dedup._get_local_matcher = original_loader
        builtins.__import__ = original_import
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.create_connection = original_create_connection
        socket.getaddrinfo = original_getaddrinfo
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
