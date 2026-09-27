"""
Phase 4 T4 and T6 — receipt v2, the official-warning factor's scoring, the
three verdicts, the caps, and the news publisher rule. Pure: no database.

The database half of the official warning (in force, where) is in
test_official_warnings.py.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import ReviewStatus, Verdict
from app.services.corroboration import news_corroboration
from app.services.evidence import Evidence, evidence_window, offline
from app.services.fusion_engine import (
    FACTORS,
    RECEIPT_VERSION,
    FusionEngine,
    decide_verdict,
    review_caps,
    source_reliability_score,
)
from app.services.official_warnings import Warning, evidence_from_warnings
from app.services.pipeline import score_cluster

UTC = timezone.utc
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def warning(event="Heavy Rainfall", severity="Severe", identifier="w1", hours=6, sender="IMD Patna"):
    return Warning(identifier=identifier, sender=sender, event=event, headline=None,
                   raw_severity=severity, expires_at=NOW + timedelta(hours=hours), matched_by="polygon")


# ── The weights ────────────────────────────────────────────────────────────────

def test_weights_sum_to_one():
    assert round(sum(f["weight"] for f in FACTORS.values()), 10) == 1.0


def test_the_v2_weights_are_the_published_ones():
    assert {k: f["weight"] for k, f in FACTORS.items()} == {
        "weather_station": 0.20, "official_warning": 0.10, "report_density": 0.20,
        "spatial_coherence": 0.15, "vision_analysis": 0.15, "source_reliability": 0.15,
        "anomaly_detection": 0.05,
    }


def test_coverage_is_0_80_with_vision_and_anomaly_offline(fusion):
    r = fusion.compute_receipt(weather_score=0.5, official_score=0.0, report_density_score=0.5,
                               spatial_score=0.5, reliability_score=0.6)
    assert r["factor_coverage"] == 0.8
    assert r["receipt_version"] == RECEIPT_VERSION == 2


def test_coverage_is_0_70_when_sachet_is_stale_as_well(fusion):
    r = fusion.compute_receipt(weather_score=0.5, official_score=None, report_density_score=0.5,
                               spatial_score=0.5, reliability_score=0.6)
    assert r["factor_coverage"] == 0.7


@pytest.mark.parametrize("scores", [
    dict(weather_score=0.7, official_score=0.85, report_density_score=0.55, spatial_score=0.98,
         reliability_score=0.6),
    dict(weather_score=0.0, official_score=0.0, report_density_score=0.1537, spatial_score=1.0,
         reliability_score=0.5),
    dict(weather_score=None, official_score=0.3, report_density_score=0.8, spatial_score=0.4,
         reliability_score=None),
])
def test_total_weighted_over_coverage_is_the_confidence(fusion, scores):
    r = fusion.compute_receipt(**scores)
    assert round(r["total_weighted"] / r["factor_coverage"], 4) == r["confidence_score"]
    assert round(sum(f["weighted_points"] for f in r["factors"]), 4) == r["total_weighted"]


def test_each_row_carries_its_key(fusion):
    r = fusion.compute_receipt(weather_score=0.5)
    assert [f["key"] for f in r["factors"]] == list(FACTORS)


# ── The official warning's score (T4, pure half) ───────────────────────────────

@pytest.mark.parametrize("severity, score", [
    ("Extreme", 1.0), ("Severe", 0.85), ("Moderate", 0.6), ("Minor", 0.3), ("Unknown", 0.3), (None, 0.3),
])
def test_cap_severity_scores(severity, score):
    e = evidence_from_warnings("URBAN_FLOOD", [warning(severity=severity)], sachet_fresh=True)
    assert e.score == score


def test_a_severe_heavy_rain_warning_covering_a_flood_is_0_85_with_its_line():
    e = evidence_from_warnings("URBAN_FLOOD", [warning()], sachet_fresh=True)
    assert e.score == 0.85 and e.source == "sachet_cap"
    assert e.reason.startswith("IMD Patna: Severe Heavy Rainfall warning in force until")


def test_a_heat_warning_over_a_flood_event_is_0_with_the_reason():
    e = evidence_from_warnings("URBAN_FLOOD", [warning(event="Heat Wave")], sachet_fresh=True)
    assert e.score == 0.0 and e.state == "computed"
    assert "for heatwave, not flood" in e.reason


def test_no_warning_in_force_is_0_online():
    e = evidence_from_warnings("URBAN_FLOOD", [], sachet_fresh=True)
    assert (e.score, e.state) == (0.0, "computed")
    assert e.reason == "no official warning in force covers this event"


def test_sachet_stale_is_offline():
    e = evidence_from_warnings("URBAN_FLOOD", [warning()], sachet_fresh=False, sachet_age_minutes=45)
    assert e.score is None and e.state == "offline"
    assert "45 min ago" in e.reason


def test_the_most_severe_matching_warning_wins():
    e = evidence_from_warnings(
        "URBAN_FLOOD",
        [warning(severity="Moderate", identifier="a"), warning(severity="Extreme", identifier="b"),
         warning(event="Heat Wave", severity="Extreme", identifier="c")],
        sachet_fresh=True,
    )
    assert e.score == 1.0 and e.detail["chosen"] == "b"


def test_unclassified_has_no_hazard_to_match():
    assert evidence_from_warnings("UNCLASSIFIED", [warning()], sachet_fresh=True).state == "offline"


# ── The verdicts ───────────────────────────────────────────────────────────────

CONTRA = {"factor": "weather_station", "rule": "r", "reason": "VIDP read 26.7 °C"}


@pytest.mark.parametrize("contradictions, official, weather, expected", [
    ([CONTRA], 0.85, 0.9, Verdict.CONTRADICTED),     # a contradiction wins
    ([], 0.6, 0.0, Verdict.CORROBORATED),
    ([], 0.0, 0.6, Verdict.CORROBORATED),
    ([], 0.59, 0.59, Verdict.UNCONFIRMED),
    ([], None, None, Verdict.UNCONFIRMED),           # no signal either way
])
def test_verdicts(contradictions, official, weather, expected):
    assert decide_verdict(contradictions, official, weather)["verdict"] is expected


# ── The caps, all in determine_review_status ──────────────────────────────────

@pytest.mark.parametrize("event_type, sources, verdict, caps", [
    ("HEATWAVE", ["CITIZEN_APP"], Verdict.CONTRADICTED, ["contradicted"]),
    ("UNCLASSIFIED", ["CITIZEN_APP"], None, ["unclassified"]),
    ("URBAN_FLOOD", ["SOCIAL_MEDIA", "NEWS_MEDIA"], None, ["posts_only"]),
    ("URBAN_FLOOD", ["CITIZEN_APP", "NEWS_MEDIA"], Verdict.CORROBORATED, []),
])
def test_review_caps(event_type, sources, verdict, caps):
    assert review_caps(event_type, sources, verdict) == caps


def test_a_cap_holds_an_auto_publishable_event_for_a_human(fusion):
    assert fusion.determine_review_status(0.95) is ReviewStatus.AUTO_PUBLISHED
    assert fusion.determine_review_status(0.95, caps=["contradicted"]) is ReviewStatus.PENDING_HUMAN_REVIEW


def test_the_gates_are_unchanged(fusion):
    assert fusion.determine_review_status(0.90) is ReviewStatus.AUTO_PUBLISHED
    assert fusion.determine_review_status(0.8999) is ReviewStatus.PENDING_HUMAN_REVIEW
    assert fusion.determine_review_status(0.60) is ReviewStatus.PENDING_HUMAN_REVIEW
    assert fusion.determine_review_status(0.5999) is ReviewStatus.QUARANTINED


# ── score_cluster with an evidence bundle ──────────────────────────────────────

STATS = {"count": 10, "centroid_lat": 28.61, "centroid_lng": 77.21, "max_pairwise_km": 0.8,
         "radius_km": 0.5}


def bundle(weather, official, contradiction=None, news=None):
    return {
        "window": evidence_window("HEATWAVE", NOW - timedelta(hours=1), NOW, NOW),
        "weather": weather, "model": weather, "station": None, "stations_seen": 0,
        "official": official, "contradiction": contradiction, "news": news,
        "rainfall_mm": None, "weather_source": "not_applicable",
    }


def heat_cluster(evidence_bundle):
    density = {"n_eff": 10.0, "basis": {"reports": 10, "distinct_reporters": 10}}
    return score_cluster(
        STATS, ["OFFICIAL_DISPATCH"] * 10,
        report_texts=["Heatwave here, 47 degree today"] * 10,
        event_type="HEATWAVE", density=density, eps_km=25.0, evidence=evidence_bundle,
    )


def test_ten_confident_heatwave_reports_against_a_thermometer_wait_for_a_human():
    measured = Evidence(0.1, "computed", "maximum temperature", 26.7, source="airport_metar",
                        reason="IMD airport observation VIDP (…): maximum 26.7 °C at 14:30 IST")
    scored = heat_cluster(bundle(measured, Evidence(1.0, "computed", source="sachet_cap", reason="x"), CONTRA))
    assert scored["verdict"] is Verdict.CONTRADICTED
    assert scored["review_status"] is not ReviewStatus.AUTO_PUBLISHED
    r = scored["receipt"]
    weather_row = next(f for f in r["factors"] if f["key"] == "weather_station")
    assert (weather_row["score"], weather_row["state"], weather_row.get("contradiction")) == (0.0, "computed", True)
    assert r["contradictions"][0]["reason"] == CONTRA["reason"]
    assert "contradicted" in r["routing"]["caps"]


def test_same_inputs_twice_give_an_identical_receipt():
    b = bundle(Evidence(0.9, "computed", source="open_meteo_model", reason="m"),
               Evidence(0.85, "computed", source="sachet_cap", reason="w"))
    assert heat_cluster(b) == heat_cluster(b)


def test_a_hailstorm_under_clear_skies_is_unconfirmed():
    density = {"n_eff": 3.0, "basis": {"reports": 3, "distinct_reporters": 3}}
    scored = score_cluster(
        {**STATS, "count": 3}, ["CITIZEN_APP"] * 3, report_texts=["Hail falling here"] * 3,
        event_type="HAILSTORM", density=density, eps_km=10.0,
        evidence=bundle(Evidence(0.0, "computed", source="open_meteo_model", reason="code 0"),
                        Evidence(0.0, "computed", source="sachet_cap", reason="none")),
    )
    assert scored["verdict"] is Verdict.UNCONFIRMED


def test_a_pure_caller_without_evidence_still_scores_the_rainfall():
    scored = score_cluster(
        {**STATS, "count": 5}, ["CITIZEN_APP"] * 5, 0.35, 15.6,
        report_texts=["flooded road"] * 5, event_type="URBAN_FLOOD",
    )
    r = scored["receipt"]
    row = next(f for f in r["factors"] if f["key"] == "weather_station")
    assert row["score"] == 0.35
    assert row["evidence"] == "15.6 mm rainfall in past 24 h (Open-Meteo modelled precipitation)"
    assert r["provenance"]["official_warning"] == "offline"
    assert r["factor_coverage"] == 0.7


def test_provenance_names_every_factor():
    scored = heat_cluster(bundle(offline("x"), offline("y")))
    assert set(scored["receipt"]["provenance"]) == set(FACTORS) | {"severity"}


# ── T6: news counts only when two independent publishers agree ─────────────────

def item(domain, name, forecast=False):
    return {"publisher_domain": domain, "publisher": name, "forecast": forecast, "in_cluster": True}


def test_t6_one_headline_is_0_55_one_publisher():
    n = news_corroboration([item("thehindu.com", "The Hindu")])
    assert n["score"] == 0.55 and "1 publisher" in n["line"]


def test_t6_two_publishers_are_0_75_both_named():
    n = news_corroboration([item("thehindu.com", "The Hindu"), item("timesofindia.indiatimes.com", "TOI")])
    assert n["score"] == 0.75
    assert "The Hindu" in n["line"] and "TOI" in n["line"]


def test_t6_five_reshares_of_one_url_are_one_publisher():
    n = news_corroboration([item("www.timesofindia.indiatimes.com", "TOI")] * 5)
    assert n["count"] == 1 and n["score"] == 0.55


def test_t6_a_forecast_still_counts_as_news_context():
    n = news_corroboration([item("thehindu.com", "The Hindu"), item("toi.in", "TOI", forecast=True)])
    assert n["score"] == 0.75 and n["forecast_items"] == 1


def test_t6_no_news_is_no_score():
    assert news_corroboration([])["score"] is None


def test_t6_the_news_score_replaces_the_news_prior_in_source_reliability():
    assert source_reliability_score(["NEWS_MEDIA"]) == 0.55
    assert source_reliability_score(["NEWS_MEDIA"], news_score=0.75) == 0.75
    assert source_reliability_score(["CITIZEN_APP"], news_score=0.75) == 0.75
    assert source_reliability_score(["OFFICIAL_DISPATCH", "NEWS_MEDIA"], news_score=0.75) == 1.0
