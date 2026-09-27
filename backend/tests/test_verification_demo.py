"""
Phase 4 T8 — the verification demo, replayed from the inputs its first live
run recorded on the server (27 Sep 2026, 23:32 IST): an Extreme Uttarakhand
SDMA rain warning over Uttarkashi, and Dehradun airport's 20.0 °C maximum.

The script scores in memory and writes nothing; this checks that its pure
path still gives the verdicts the scene depends on, and that every report is
labelled synthetic.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDING = REPO_ROOT / "data" / "demo" / "verification_cases.json"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_verification_demo as demo  # noqa: E402


@pytest.fixture(scope="module")
def recorded():
    return json.loads(RECORDING.read_text())


def test_case_a_replays_corroborated_and_case_b_contradicted(recorded):
    a, b = demo.score_case(recorded["A"]), demo.score_case(recorded["B"])
    assert a["scored"]["verdict"].value == "CORROBORATED"
    assert b["scored"]["verdict"].value == "CONTRADICTED"
    assert a["scored"]["confidence"] == 0.712
    assert b["scored"]["confidence"] == 0.4369


def test_case_b_names_the_station_and_its_temperature(recorded):
    receipt = demo.score_case(recorded["B"])["scored"]["receipt"]
    reason = receipt["contradictions"][0]["reason"]
    assert "VIDN" in reason and "20.0 °C" in reason


def test_every_report_is_labelled_synthetic(recorded):
    for case in (recorded["A"], recorded["B"]):
        assert len(case["reports"]) == demo.REPORTS_PER_CASE
        assert all(r["text"].startswith(demo.LABEL) for r in case["reports"])


def test_frozen_replay_exits_zero(recorded, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_verification_demo.py", "--frozen", str(RECORDING)])
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "CORROBORATED" in out and "CONTRADICTED" in out


def test_a_missing_recording_is_an_error_not_a_pretence(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_verification_demo.py", "--frozen", str(tmp_path / "none.json")])
    assert demo.main() == 1
