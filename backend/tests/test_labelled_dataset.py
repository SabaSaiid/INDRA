"""
Day 4 T7 — the labelled report dataset is shaped as its datasheet says.

Unit level (no database). The leakage check needs the MiniLM model and is
skipped without it.
"""

import csv
import hashlib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.conftest import requires_embeddings

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "data" / "labelled" / "reports_v1.csv"
DATASHEET = REPO / "data" / "labelled" / "DATASHEET.md"
CLASSES = {"URBAN_FLOOD", "RIVER_BREACH", "CLOUDBURST", "CYCLONE_INUNDATION", "NOT_RELEVANT"}
SEVERITIES = {"ADVISORY", "MODERATE", "HIGH", "CRITICAL"}


@pytest.fixture(scope="module")
def rows():
    with DATASET.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _norm(text):
    return re.sub(r"\s+", " ", text.casefold()).strip()


def test_row_count(rows):
    assert len(rows) == 300


def test_sixty_rows_per_event_type(rows):
    assert Counter(r["event_type"] for r in rows) == {c: 60 for c in CLASSES}


def test_frozen_split_is_18_test_rows_per_class(rows):
    test = [r for r in rows if r["split"] == "test"]
    assert len(test) == 90
    assert Counter(r["event_type"] for r in test) == {c: 18 for c in CLASSES}
    assert {r["split"] for r in rows} == {"train", "test"}


def test_at_least_15_hindi_or_hinglish_rows_per_class(rows):
    counts = Counter(r["event_type"] for r in rows if r["lang"] in {"hi", "hinglish"})
    assert all(counts[c] >= 15 for c in CLASSES), counts
    assert {r["lang"] for r in rows} == {"en", "hi", "hinglish"}


def test_severity_is_empty_exactly_when_not_relevant(rows):
    for r in rows:
        assert (r["severity"] == "") == (r["event_type"] == "NOT_RELEVANT"), r["id"]


def test_each_severity_has_at_least_30_rows(rows):
    counts = Counter(r["severity"] for r in rows if r["severity"])
    assert set(counts) == SEVERITIES
    assert all(n >= 30 for n in counts.values()), counts


def test_at_least_60_rows_state_a_depth(rows):
    depths = [int(r["depth_cm"]) for r in rows if r["depth_cm"]]
    assert len(depths) >= 60
    assert all(0 < d <= 500 for d in depths)


def test_spam_only_among_not_relevant(rows):
    assert all(r["event_type"] == "NOT_RELEVANT" for r in rows if r["spam"] == "1")
    assert {r["spam"] for r in rows} == {"0", "1"}


def test_no_exact_duplicate_text_across_train_and_test(rows):
    train = {_norm(r["text"]) for r in rows if r["split"] == "train"}
    test = {_norm(r["text"]) for r in rows if r["split"] == "test"}
    assert train.isdisjoint(test)
    assert len({_norm(r["text"]) for r in rows}) == 300


@requires_embeddings
def test_no_near_duplicate_pairs_across_train_and_test(rows):
    import numpy as np

    from app.services.dedup import _get_embedding_model

    model = _get_embedding_model()
    train = [r["text"] for r in rows if r["split"] == "train"]
    test = [r["text"] for r in rows if r["split"] == "test"]
    a = model.encode(train, normalize_embeddings=True, convert_to_numpy=True)
    b = model.encode(test, normalize_embeddings=True, convert_to_numpy=True)
    sims = a @ b.T
    assert int((sims >= 0.95).sum()) == 0, float(np.max(sims))


def test_datasheet_hash_matches_the_file():
    digest = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    assert digest in DATASHEET.read_text(encoding="utf-8")


def test_split_script_refuses_to_resplit(tmp_path):
    copy = tmp_path / "reports.csv"
    copy.write_bytes(DATASET.read_bytes())
    before = hashlib.sha256(copy.read_bytes()).hexdigest()

    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "split_dataset.py"), str(copy)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "frozen" in result.stderr
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before
