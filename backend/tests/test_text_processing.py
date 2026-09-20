"""
Day 4 T10 — text cleaning and metadata extraction (pure, no database).

The dataset tests measure depth extraction on data/labelled/reports_v1.csv:
the rules were tuned on the train split only; the test split is the measurement.
"""

import csv
from pathlib import Path

import pytest

from app.services.text_processing import clean_text, depth_bucket, extract_metadata

DATASET = Path(__file__).resolve().parents[2] / "data" / "labelled" / "reports_v1.csv"


# ── clean_text ─────────────────────────────────────────────────────────────────

def test_zwj_is_kept():
    assert clean_text("पटना‍") == "पटना‍"


def test_zero_width_space_and_tabs_are_removed():
    assert clean_text("flood​  in\t\tPatna") == "flood in Patna"


def test_urls_are_replaced():
    assert clean_text("see https://x.co/a now") == "see <URL> now"


def test_control_characters_are_stripped_but_newlines_kept():
    assert clean_text("water\x07 rising\nnear﻿ Patna ") == "water rising\nnear Patna"


def test_nfkc_normalises_fullwidth_digits():
    assert clean_text("２ ft") == "2 ft"


def test_empty_input():
    assert clean_text("") == ""
    assert extract_metadata("")["depth_cm"] is None


# ── depth ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, depth, basis",
    [
        ("water is knee deep near Boring Road", 50, "body:knee"),
        ("2 feet water in our lane", 61, "measure:feet"),
        ("2-3 ft paani bhara hai", 91, "measure:ft"),
        ("1.5m water at Kankarbagh", 150, "measure:m"),
        ("घुटनों तक पानी", 50, "body:knee"),
        ("Around 10 cm of water on the road", 10, "measure:cm"),
        ("about a foot of muddy water inside shops", 30, "measure:foot"),
        ("Two metres of seawater through the market", 200, "measure:metres"),
        ("दो मीटर तक समुद्री पानी भर गया", 200, "measure:मीटर"),
        ("Kamar tak paani hai gali mein", 100, "body:waist"),
        ("Water up to the first floor ceiling", 250, "reach:first_floor"),
        ("नदी का पानी छत तक पहुंच गया", 250, "reach:roof"),
        ("knee deep water here, and waist deep near the station", 100, "body:waist"),
    ],
)
def test_depth_is_extracted(text, depth, basis):
    m = extract_metadata(text)
    assert (m["depth_cm"], m["depth_basis"]) == (depth, basis)


@pytest.mark.parametrize(
    "text",
    [
        "we are 30 feet from the river",
        "5 people trapped, need rescue boat",
        "twisted my knee on the way to office",
        "people on roofs waving for help",
        "families stuck on first floors asking for boats",
        "still one metre below the danger mark near Gopalganj after water level rose earlier today",
    ],
)
def test_no_depth_without_water_context(text):
    assert extract_metadata(text)["depth_cm"] is None


# ── keywords, places, counts ───────────────────────────────────────────────────

def test_life_safety_keywords():
    m = extract_metadata("5 people trapped, need rescue boat")
    assert m["keywords"] == ["trapped", "rescue", "boat"]


def test_hindi_keywords():
    assert extract_metadata("कई लोग लापता, तीन की मौत")["keywords"] == ["missing", "dead"]


def test_fast_is_not_trapped():
    assert extract_metadata("share fast")["keywords"] == []


def test_places_from_the_gazetteer():
    assert extract_metadata("Flooding in Patna")["places"] == ["Patna"]
    assert extract_metadata("delhi and New Delhi")["places"] == ["New Delhi"]
    assert extract_metadata("Patnaik road")["places"] == []


def test_url_and_phone_counts():
    m = extract_metadata("see https://x.co/a now, call +91 98765 43210 or 9876543210")
    assert m["url_count"] == 1
    assert m["phone_count"] == 2


@pytest.mark.parametrize("cm, bucket", [(29, "<30"), (30, "30-79"), (79, "30-79"), (80, "80-139"), (139, "80-139"), (140, ">=140"), (None, None)])
def test_depth_buckets(cm, bucket):
    assert depth_bucket(cm) == bucket


# ── measured on the labelled dataset ───────────────────────────────────────────

def _rows(split):
    with DATASET.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r["split"] == split]


def _bucket_accuracy(rows):
    labelled = [r for r in rows if r["depth_cm"]]
    hits = sum(
        depth_bucket(extract_metadata(r["text"])["depth_cm"]) == depth_bucket(int(r["depth_cm"]))
        for r in labelled
    )
    return hits, len(labelled)


def _false_depth_rate(rows):
    empty = [r for r in rows if not r["depth_cm"]]
    return sum(extract_metadata(r["text"])["depth_cm"] is not None for r in empty), len(empty)


def test_train_split_depth_bucket_accuracy():
    hits, n = _bucket_accuracy(_rows("train"))
    assert hits / n >= 0.85, (hits, n)


def test_test_split_depth_bucket_accuracy():
    hits, n = _bucket_accuracy(_rows("test"))
    assert hits / n >= 0.80, (hits, n)


def test_test_split_rows_without_depth_rarely_get_one():
    hits, n = _false_depth_rate(_rows("test"))
    assert hits / n <= 0.03, (hits, n)
