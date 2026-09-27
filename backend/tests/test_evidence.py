"""
Phase 4 T1–T3 — weather evidence per hazard, airport observations, contradictions.

Pure: every test builds an Open-Meteo hourly series or METAR observations by
hand and reads services/evidence.py, with no database and no network. The
Open-Meteo request itself (one per res-7 cell, failure is None) is tested at
the end with a mocked transport that counts calls.

Each table row in development/phase-4-verification.md T1, T2 and T3 is a test
below, named after it.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services import evidence as ev
from app.services import weather
from app.services.weather import HOURLY_VARIABLES, HourlySeries

UTC = timezone.utc
DAY = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
TIMES = tuple(DAY + timedelta(hours=h) for h in range(24))
NOW = DAY + timedelta(hours=20)


def series(elevation=200.0, **columns):
    values = {name: tuple(columns.get(name, [None] * 24)) for name in HOURLY_VARIABLES}
    return HourlySeries(TIMES, values, elevation, "open-meteo forecast")


def at(hour, minute=0):
    return DAY + timedelta(hours=hour, minutes=minute)


def window(event_type, start_hour, end_hour=None):
    end_hour = start_hour if end_hour is None else end_hour
    return ev.evidence_window(event_type, at(start_hour), at(end_hour), NOW)


def one_hot(value, hour, rest):
    column = [rest] * 24
    column[hour] = value
    return column


def obs(station="VIDP", name="Delhi IGI", km=14.0, when=None, civil=True, elevation_m=237, **fields):
    return {
        "station_code": station, "station_name": name, "distance_km": km,
        "recorded_at": when or at(5, 30), "civil": civil, "elevation_m": elevation_m,
        "temperature_c": fields.get("temperature_c"), "wind_kmh": fields.get("wind_kmh"),
        "gust_kmh": fields.get("gust_kmh"), "visibility_m": fields.get("visibility_m"),
        "weather_codes": fields.get("weather_codes", []),
        "convective_cloud": fields.get("convective_cloud", False),
    }


# ── The window ─────────────────────────────────────────────────────────────────

def test_window_is_the_observed_span_plus_minus_three_hours():
    w = window("FOG", 6)
    assert (w.start, w.end) == (at(3), at(9))
    assert "03:00–09:00" in w.label()


def test_window_never_ends_after_now():
    w = ev.evidence_window("FOG", NOW - timedelta(minutes=30), NOW - timedelta(minutes=10), NOW)
    assert w.end == NOW


def test_window_for_the_rain_family_is_the_24_hour_accumulation():
    w = window("URBAN_FLOOD", 12, 13)
    assert w.end - w.start == timedelta(hours=24)
    assert w.end == at(16)


def test_window_for_heat_covers_at_least_the_last_24_hours():
    # A heatwave reported at 22:00 must see the afternoon's maximum.
    w = ev.evidence_window("HEATWAVE", at(19), at(19), at(22))
    assert (w.start, w.end) == (at(22) - timedelta(hours=24), at(22))
    assert w.contains(at(14))


# ── T1: model evidence, the plan's table ───────────────────────────────────────

def test_t1_heatwave_46_degrees_scores_0_9():
    e = ev.model_evidence("HEATWAVE", window("HEATWAVE", 12), series(temperature_2m=one_hot(46.0, 10, 30.0)))
    assert e.score == 0.9 and e.state == "computed"
    assert "46.0 °C" in e.reason and "Open-Meteo model" in e.reason
    assert e.source == ev.OPEN_METEO_MODEL


def test_t1_heatwave_in_the_hills_uses_the_30_degree_threshold():
    e = ev.model_evidence(
        "HEATWAVE", window("HEATWAVE", 12), series(elevation=2100.0, temperature_2m=one_hot(31.0, 10, 20.0))
    )
    assert e.score >= 0.4
    assert "hill" in e.reason


def test_t1_fog_40_metres_at_05_for_a_06_event():
    e = ev.model_evidence("FOG", window("FOG", 6), series(visibility=one_hot(40.0, 5, 9000.0)))
    assert e.score == 1.0
    assert "40 m" in e.reason and "03:00–09:00" in e.reason


def test_t1_fog_outside_the_window_is_not_read():
    # 40 m at 12:00 is not evidence for fog observed at 06:00.
    e = ev.model_evidence("FOG", window("FOG", 6), series(visibility=one_hot(40.0, 12, 9000.0)))
    assert e.score == 0.0


def test_t1_strong_wind_gust_70_scores_0_8():
    e = ev.model_evidence("STRONG_WIND", window("STRONG_WIND", 6), series(wind_gusts_10m=one_hot(70.0, 5, 10.0)))
    assert e.score == 0.8
    assert "70 km/h" in e.reason


def test_t1_thunderstorm_code_95_two_hours_ago_scores_1():
    e = ev.model_evidence(
        "THUNDERSTORM", window("THUNDERSTORM", 6),
        series(weather_code=one_hot(95.0, 4, 0.0), cape=[200.0] * 24),
    )
    assert e.score == 1.0
    assert "code 95" in e.reason


def test_t1_cloudburst_120_mm_in_an_hour_scores_1():
    e = ev.model_evidence("CLOUDBURST", window("CLOUDBURST", 6), series(precipitation=one_hot(120.0, 5, 0.0)))
    assert e.score == 1.0
    assert "120 mm/h" in e.reason


def test_t1_dust_650_with_gusts_45_scores_0_8():
    air = HourlySeries(TIMES, {"dust": tuple(one_hot(650.0, 5, 10.0)), "pm10": tuple([None] * 24)},
                       None, "open-meteo air-quality")
    e = ev.model_evidence("DUST_STORM", window("DUST_STORM", 6), series(wind_gusts_10m=[45.0] * 24), air=air)
    assert e.score == 0.8
    assert "650 µg/m³" in e.reason


@pytest.mark.parametrize("event_type", ["HEATWAVE", "FOG", "STRONG_WIND", "THUNDERSTORM", "CLOUDBURST"])
def test_t1_no_model_response_is_offline_not_a_guess(event_type):
    e = ev.model_evidence(event_type, window(event_type, 6), None)
    assert e.score is None and e.state == "offline"
    assert "offline" in e.reason


def test_t1_urban_flood_reads_the_24_hour_rainfall_exactly_as_before():
    e = ev.model_evidence("URBAN_FLOOD", window("URBAN_FLOOD", 6), None, rainfall_mm=15.6, rain_score=0.35)
    assert e.score == 0.35
    assert e.reason == "15.6 mm rainfall in past 24 h (Open-Meteo modelled precipitation)"


def test_t1_partial_types_are_capped_so_the_warning_decides():
    e = ev.model_evidence("LANDSLIDE", window("LANDSLIDE", 6), None, rainfall_mm=250.0)
    assert e.score == ev.PARTIAL_EVIDENCE_CAP


# ── The scales at their published cuts ─────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    (47.0, 1.0), (46.9, 0.9), (45.0, 0.9), (44.9, 0.6), (42.0, 0.6), (41.9, 0.4), (40.0, 0.4), (39.9, 0.1),
])
def test_heat_scale_cuts(value, expected):
    assert ev.heat_score(value) == expected


@pytest.mark.parametrize("value, expected", [
    (2.0, 1.0), (2.1, 0.8), (4.0, 0.8), (7.0, 0.5), (10.0, 0.3), (10.1, 0.1),
])
def test_cold_scale_cuts(value, expected):
    assert ev.cold_score(value) == expected


@pytest.mark.parametrize("value, expected", [
    (49.0, 1.0), (50.0, 0.85), (199.0, 0.85), (200.0, 0.6), (499.0, 0.6), (500.0, 0.4), (999.0, 0.4), (1000.0, 0.0),
])
def test_visibility_scale_cuts(value, expected):
    assert ev.visibility_score(value) == expected


@pytest.mark.parametrize("value, expected", [
    (89.0, 1.0), (88.9, 0.8), (62.0, 0.8), (50.0, 0.6), (39.0, 0.4), (38.9, 0.0),
])
def test_gust_scale_cuts(value, expected):
    assert ev.gust_score(value) == expected


def test_hail_and_thunder_codes():
    assert ev.hail_score([96]) == 1.0 and ev.hail_score([99]) == 1.0 and ev.hail_score([95]) == 0.5
    assert ev.thunder_score([81], 1000.0) == 0.6
    assert ev.thunder_score([81], 999.0) == 0.3
    assert ev.thunder_score([], 500.0) == 0.3
    assert ev.thunder_score([], 499.0) == 0.0


# ── T2: station evidence, the plan's table ─────────────────────────────────────

def test_t2_fog_14_km_from_vidp_at_0530():
    w = window("FOG", 6)
    stations = ev.group_stations([obs(visibility_m=150, weather_codes=["FG"])], w)
    e = ev.station_evidence("FOG", stations, w)
    assert e.score == 0.85
    assert "VIDP" in e.reason and "14 km" in e.reason and "150 m" in e.reason
    assert e.source == ev.AIRPORT_METAR


def test_t2_thunderstorm_near_kolkata_heavy_rain_with_cb():
    w = window("THUNDERSTORM", 6)
    stations = ev.group_stations(
        [obs("VECC", "Kolkata", km=8.0, weather_codes=["TS", "RA+"], convective_cloud=True)], w
    )
    assert ev.station_evidence("THUNDERSTORM", stations, w).score == 1.0


def test_t2_thunderstorm_at_a_station_40_km_away_is_weighted_0_8():
    w = window("THUNDERSTORM", 6)
    stations = ev.group_stations([obs("VECC", "Kolkata", km=40.0, weather_codes=["TS"])], w)
    assert ev.station_evidence("THUNDERSTORM", stations, w).score == 0.8


def test_t2_heatwave_in_jaipur_the_station_decides_and_the_disagreement_is_stated():
    w = window("HEATWAVE", 12)
    model = ev.model_evidence("HEATWAVE", w, series(temperature_2m=[44.0] * 24))
    stations = ev.group_stations([obs("VIJP", "Jaipur", km=10.0, when=at(10), temperature_c=30.0)], w)
    station = ev.station_evidence("HEATWAVE", stations, w, hill_hint=False)
    combined = ev.combine_weather("HEATWAVE", model, station)
    assert combined.source == ev.AIRPORT_METAR
    assert combined.score == ev.heat_score(30.0)
    assert "disagree" in combined.reason and "the measurement is used" in combined.reason


def test_t2_no_station_within_50_km_leaves_the_model():
    w = window("FOG", 6)
    stations = ev.group_stations([obs(km=60.0, visibility_m=100)], w)
    assert stations == []
    model = ev.model_evidence("FOG", w, series(visibility=[300.0] * 24))
    combined = ev.combine_weather("FOG", model, ev.station_evidence("FOG", stations, w))
    assert combined.source == ev.OPEN_METEO_MODEL


def test_t2_an_observation_outside_the_window_is_ignored():
    w = window("FOG", 6)
    assert ev.group_stations([obs(when=at(15), visibility_m=100, weather_codes=["FG"])], w) == []


def test_t2_imd_is_named_only_for_civil_aerodromes():
    w = window("FOG", 6)
    civil = ev.station_evidence("FOG", ev.group_stations([obs(visibility_m=150)], w), w)
    other = ev.station_evidence("FOG", ev.group_stations([obs("VIXX", "Air Force Stn", civil=False,
                                                              visibility_m=150)], w), w)
    assert civil.reason.startswith("IMD airport observation")
    assert other.reason.startswith("Airport observation") and "IMD" not in other.reason


def test_t2_a_squall_code_is_at_least_0_8():
    w = window("STRONG_WIND", 6)
    stations = ev.group_stations([obs(wind_kmh=20.0, weather_codes=["SQ"])], w)
    assert ev.station_evidence("STRONG_WIND", stations, w).score == 0.8


def test_t2_rain_family_keeps_the_model_primary():
    w = window("URBAN_FLOOD", 6)
    model = ev.model_evidence("URBAN_FLOOD", w, None, rainfall_mm=15.6, rain_score=0.35)
    stations = ev.group_stations([obs(when=at(4), weather_codes=["RA+"])], w)
    combined = ev.combine_weather("URBAN_FLOOD", model, ev.station_evidence("URBAN_FLOOD", stations, w))
    assert combined.score == 0.35 and combined.source == ev.OPEN_METEO_MODEL
    assert "VIDP" in combined.reason


# ── T3: contradictions, the plan's table ───────────────────────────────────────

def _contradiction(event_type, model, observations, w, **kwargs):
    stations = ev.group_stations(observations, w)
    station = ev.station_evidence(event_type, stations, w, hill_hint=model.detail.get("hill"))
    combined = ev.combine_weather(event_type, model, station)
    return ev.find_contradiction(event_type, combined, model, stations, w, **kwargs)


def test_t3_heatwave_claim_with_vidp_at_26_7_is_contradicted_and_named():
    w = window("HEATWAVE", 12)
    model = ev.model_evidence("HEATWAVE", w, series(temperature_2m=[44.0] * 24))
    c = _contradiction("HEATWAVE", model, [obs(when=at(10), temperature_c=26.7)], w)
    assert c is not None and c["factor"] == "weather_station"
    assert "VIDP" in c["reason"] and "26.7 °C" in c["reason"]


def test_t3_heatwave_claim_with_the_feed_down_is_offline_not_contradicted():
    w = window("HEATWAVE", 12)
    model = ev.model_evidence("HEATWAVE", w, None)
    assert model.state == "offline"
    assert _contradiction("HEATWAVE", model, [], w) is None


def test_t3_flood_with_zero_rain_and_only_haze_nearby_is_contradicted_with_another_cause():
    w = window("URBAN_FLOOD", 12)
    model = ev.model_evidence("URBAN_FLOOD", w, None, rainfall_mm=0.0)
    c = _contradiction("URBAN_FLOOD", model, [obs(km=10.0, when=at(10), weather_codes=["HZ"])], w)
    assert c is not None
    assert "another cause" in c["reason"] and "possible" in c["reason"]


def test_t3_flood_with_rain_at_a_near_station_is_not_contradicted():
    w = window("URBAN_FLOOD", 12)
    model = ev.model_evidence("URBAN_FLOOD", w, None, rainfall_mm=0.0)
    assert _contradiction("URBAN_FLOOD", model, [obs(km=10.0, when=at(10), weather_codes=["RA-"])], w) is None


def test_t3_river_breach_with_zero_rain_locally_is_not_contradicted():
    w = window("RIVER_BREACH", 12)
    model = ev.model_evidence("RIVER_BREACH", w, None, rainfall_mm=0.0)
    assert _contradiction("RIVER_BREACH", model, [], w) is None


def test_t3_hailstorm_under_clear_skies_is_never_contradicted():
    w = window("HAILSTORM", 6)
    model = ev.model_evidence("HAILSTORM", w, series(weather_code=[0.0] * 24, cape=[0.0] * 24))
    assert _contradiction("HAILSTORM", model, [obs(km=5.0, weather_codes=[])], w) is None


def test_t3_fog_contradicted_by_a_near_station_reading_over_5_km():
    w = window("FOG", 6)
    model = ev.model_evidence("FOG", w, series(visibility=[2000.0] * 24))
    c = _contradiction("FOG", model, [obs(km=12.0, visibility_m=8000)], w)
    assert c is not None and "VIDP" in c["reason"]


def test_t3_fog_with_no_station_is_contradicted_only_above_8_km_modelled():
    w = window("FOG", 6)
    assert _contradiction("FOG", ev.model_evidence("FOG", w, series(visibility=[7000.0] * 24)), [], w) is None
    assert _contradiction("FOG", ev.model_evidence("FOG", w, series(visibility=[9000.0] * 24)), [], w) is not None


def test_t3_thunderstorm_whose_only_station_is_over_25_km_is_never_contradicted():
    w = window("THUNDERSTORM", 6)
    model = ev.model_evidence("THUNDERSTORM", w, series(weather_code=[0.0] * 24, cape=[10.0] * 24))
    assert _contradiction("THUNDERSTORM", model, [obs(km=30.0, weather_codes=[])], w) is None
    assert _contradiction("THUNDERSTORM", model, [obs(km=10.0, weather_codes=[])], w) is not None


def test_t3_strong_wind_needs_both_the_station_and_the_model_calm():
    w = window("STRONG_WIND", 6)
    calm = ev.model_evidence("STRONG_WIND", w, series(wind_gusts_10m=[12.0] * 24))
    assert _contradiction("STRONG_WIND", calm, [obs(wind_kmh=9.0)], w) is not None
    assert _contradiction("STRONG_WIND", calm, [], w) is None


def test_t3_cyclone_contradicted_only_when_sachet_is_known_to_be_current():
    w = window("CYCLONE", 6)
    model = ev.model_evidence("CYCLONE", w, series(wind_gusts_10m=[30.0] * 24))
    assert _contradiction("CYCLONE", model, [], w, cyclone_warning_nearby=False)["factor"] == "official_warning"
    assert _contradiction("CYCLONE", model, [], w, cyclone_warning_nearby=None) is None
    assert _contradiction("CYCLONE", model, [], w, cyclone_warning_nearby=True) is None


def test_t3_a_contradicted_factor_scores_zero_online_with_the_reason_first():
    w = window("HEATWAVE", 12)
    model = ev.model_evidence("HEATWAVE", w, series(temperature_2m=[26.0] * 24))
    c = _contradiction("HEATWAVE", model, [], w)
    e = ev.contradicted(model, c)
    assert (e.score, e.state, e.contradiction) == (0.0, "computed", True)
    assert e.reason.startswith("CONTRADICTED:")


# ── T1: the request, one per res-7 cell ────────────────────────────────────────

def _open_meteo_body():
    return {
        "elevation": 216.0,
        "hourly": {
            "time": [t.strftime("%Y-%m-%dT%H:%M") for t in TIMES],
            **{name: [1.0] * 24 for name in HOURLY_VARIABLES},
        },
    }


async def test_t1_two_events_in_one_cell_within_ten_minutes_make_one_request():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=_open_meteo_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await weather.fetch_hourly(28.5665, 77.1031, client)
        second = await weather.fetch_hourly(28.5666, 77.1032, client)
    assert first is not None and second is not None
    assert len(calls) == 1
    params = dict(calls[0].params)
    assert params["past_days"] == "1" and params["forecast_days"] == "1"
    assert set(params["hourly"].split(",")) == set(HOURLY_VARIABLES)


@pytest.mark.parametrize("response", [
    httpx.Response(500),
    httpx.Response(200, json={"hourly": {}}),
])
async def test_t1_a_failed_request_is_none(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as client:
        assert await weather.fetch_hourly(19.0896, 72.8656, client) is None


async def test_t1_a_timeout_is_none():
    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        assert await weather.fetch_hourly(13.1986, 77.7066, client) is None
