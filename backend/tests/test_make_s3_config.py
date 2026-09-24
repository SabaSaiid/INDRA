"""
scripts/make_s3_config.py refuses keys that are not secret (BUG-089).

The team server's .env held MinIO's `minioadmin` pair until the Phase 2
deploy; the script only refused the `.env.example` placeholders, so it would
have written the public default into the object store's identity file.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_s3_config.py"
_spec = importlib.util.spec_from_file_location("make_s3_config", SCRIPT)
make_s3_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_s3_config)

GOOD_ACCESS = "3f9a1c0b7d2e4a6f8b1c3d5e"
GOOD_SECRET = "9c1e" * 16


@pytest.mark.parametrize(
    "access, secret, reason",
    [
        ("minioadmin", "minioadmin", "well-known default"),
        ("MinioAdmin", GOOD_SECRET, "well-known default"),
        (GOOD_ACCESS, "password", "well-known default"),
        ("change-me-access-key", "change-me-secret-key", "placeholder"),
        ("short", GOOD_SECRET, "shorter than 16"),
        (GOOD_ACCESS, "0123456789abcde", "shorter than 16"),
    ],
)
def test_weak_keys_are_refused(access, secret, reason):
    assert reason in make_s3_config.weak_key_problem(access, secret)


def test_generated_keys_are_accepted():
    # What `openssl rand -hex 12` and `-hex 32` produce.
    assert make_s3_config.weak_key_problem(GOOD_ACCESS, GOOD_SECRET) == ""


def test_the_script_exits_1_on_the_minio_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("S3_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "minioadmin")
    monkeypatch.setattr(make_s3_config, "OUT", tmp_path / "s3.json")
    monkeypatch.setattr("sys.argv", ["make_s3_config.py"])
    assert make_s3_config.main() == 1
    assert not (tmp_path / "s3.json").exists()
    assert "well-known default" in capsys.readouterr().err
