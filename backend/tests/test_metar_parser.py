"""
Phase 2 T3 — the METAR parser, as pure unit tests.

The first block is T3's test table: real observations from 22 Sep plus written
winter-fog and dust-storm cases, each traced by hand before this file existed.
The fixture block reads the whole AWC cache file saved on 24 Sep (105 Indian
stations plus four neighbours that must be filtered out).

The poller's own cases — one row per station and time across ticks, a 304, a
corrupt download — need a database and live in the integration tests.
"""

import gzip
from pathlib import Path

import pytest

from app.services import metar
from app.services.metar import normalise_weather, parse_report

FIXTURE = Path(__file__).parent / "fixtures" / "metar_cache_24sep.csv.gz"


# ── T3's table ─────────────────────────────────────────────────────────────────

def test_delhi_haze():
    p = parse_report("METAR VIDP 221530Z 35004KT 4000 HZ NSC 30/24 Q1008 NOSIG")
    assert p["temperature_c"] == 30
    assert p["dewpoint_c"] == 24
    assert p["wind_kmh"] == 7.4
    assert p["visibility_m"] == 4000
    assert p["weather_codes"] == ["HZ"]
    assert p["convective_cloud"] is False
    assert "gust_kmh" not in p


def test_kolkata_haze_with_cumulonimbus():
    p = parse_report("METAR VECC 221530Z 07005KT 3500 HZ SCT018 FEW030CB SCT100 27/27 Q1006")
    assert p["visibility_m"] == 3500
    assert p["weather_codes"] == ["HZ"]
    assert p["convective_cloud"] is True


def test_winter_fog_at_fifty_metres():
    p = parse_report("METAR VIDP 150030Z 00000KT 0050 FG VV001 08/08 Q1018")
    assert p["visibility_m"] == 50
    assert p["weather_codes"] == ["FG"]
    assert p["wind_kmh"] == 0


def test_dust_storm_with_gusts():
    p = parse_report("METAR VIDP 101130Z 29015G35KT 1500 DS NSC 41/08 Q1002")
    assert p["gust_kmh"] == 64.8
    assert p["wind_kmh"] == 27.8
    assert p["visibility_m"] == 1500
    assert p["weather_codes"] == ["DS"]
    assert p["temperature_c"] == 41


def test_mumbai_thunderstorm_heavy_rain():
    p = parse_report("METAR VABB 101130Z 24012KT 3000 +TSRA FEW015CB SCT020 BKN080 26/24 Q1004")
    assert p["weather_codes"] == ["TS", "RA+"]
    assert p["convective_cloud"] is True


def test_cavok_is_ten_kilometres():
    p = parse_report("METAR VOMM 221530Z 09008KT CAVOK 29/22 Q1008 NOSIG")
    assert p["visibility_m"] == 10_000
    assert p["weather_codes"] == []


def test_nepal_is_filtered_out():
    assert metar.is_indian("VNKT") is False
    assert all(metar.is_indian(c) for c in ("VABB", "VECC", "VIDP", "VOMM"))


# ── Beyond the table ───────────────────────────────────────────────────────────

def test_9999_is_ten_kilometres():
    assert parse_report("METAR VOTV 221530Z 27006KT 9999 FEW020 28/24 Q1008")["visibility_m"] == 10_000


def test_forecast_after_tempo_is_not_present_weather():
    p = parse_report("METAR VIJU 240530Z 06003KT 5000 BR SCT020 21/21 Q1011 TEMPO 3000 TSRA")
    assert p["weather_codes"] == ["BR"]
    assert p["visibility_m"] == 5000


def test_becmg_haze_is_not_observed_haze():
    p = parse_report("METAR VIDP 221530Z 35004KT 6000 NSC 30/24 Q1008 BECMG 5000 HZ")
    assert p["weather_codes"] == []
    assert p["visibility_m"] == 6000


def test_minus_temperatures():
    p = parse_report("METAR VILH 150030Z 00000KT 8000 NSC M05/M10 Q1030")
    assert (p["temperature_c"], p["dewpoint_c"]) == (-5, -10)


def test_missing_dewpoint():
    p = parse_report("METAR VILH 150030Z 00000KT 8000 NSC 05/ Q1030")
    assert p["temperature_c"] == 5
    assert "dewpoint_c" not in p


def test_statute_miles_when_no_metric_group():
    assert parse_report("METAR KXYZ 221530Z 00000KT 1/2SM FG 10/10 A3000")["visibility_m"] == 805


def test_a_second_four_digit_group_is_a_directional_minimum():
    assert parse_report("METAR VIDP 221530Z 35004KT 4000 1500SW HZ 30/24 Q1008")["visibility_m"] == 4000


def test_runway_visual_range_is_skipped():
    p = parse_report("METAR VEPY 240530Z 00000KT 0100 R02/0325 FG VV/// 18/17 Q1020 NOSIG")
    assert p["visibility_m"] == 100
    assert p["weather_codes"] == ["FG"]


def test_recent_weather_is_not_present_weather():
    assert parse_report("METAR VABB 221530Z 24012KT 6000 SCT020 27/24 Q1004 RETSRA")["weather_codes"] == []


def test_wind_in_metres_per_second():
    assert parse_report("METAR UUEE 221530Z 18005MPS 9999 12/08 Q1010")["wind_kmh"] == 18.0


def test_variable_wind_direction_group_is_skipped():
    p = parse_report("METAR VIDP 221530Z VRB03KT 250V320 4000 HZ 30/24 Q1008")
    assert p["wind_kmh"] == 5.6
    assert p["weather_codes"] == ["HZ"]


def test_empty_report():
    assert parse_report("") == {"weather_codes": [], "convective_cloud": False}


# ── Present weather ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "token, codes",
    [
        ("HZ", ["HZ"]),
        ("-RA", ["RA-"]),
        ("+TSRA", ["TS", "RA+"]),
        ("SHRA", ["SH", "RA"]),
        ("TSGR", ["TS", "GR"]),
        ("VCTS", ["VCTS"]),
        ("VCSH", ["VCSH"]),
        ("+TS", ["TS+"]),
        ("+DS", ["DS+"]),
        ("+FC", ["FC+"]),
        # Intensity qualifies the precipitation, never the obscuration.
        ("-RABR", ["RA-", "BR"]),
        ("-TSRABR", ["TS", "RA-", "BR"]),
        ("+SHRAHZ", ["SH", "RA+", "HZ"]),
        ("FU", ["FU"]),
        ("NSW", None),
        ("NOSIG", None),
        ("Q1008", None),
        ("", None),
    ],
)
def test_normalise_weather(token, codes):
    assert normalise_weather(token) == codes


# ── The 24 Sep cache file ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rows():
    return metar.read_cache_rows(FIXTURE.read_bytes())


def test_fixture_has_the_indian_stations_and_neighbours(rows):
    assert len(rows) == 109
    assert len(metar.indian_observations(rows)) == 105


def test_neighbours_are_filtered_out(rows):
    codes = {o.station_code for o in metar.indian_observations(rows)}
    assert not codes & {"VNKT", "OPKC", "VCBI", "VGHS"}


def test_every_indian_observation_is_complete(rows):
    for o in metar.indian_observations(rows):
        assert o.recorded_at is not None and o.recorded_at.tzinfo is not None
        assert o.temperature_c is not None
        assert o.visibility_m is not None
        assert o.lat is not None and o.lng is not None


def test_no_obscuration_carries_an_intensity(rows):
    codes = {c for o in metar.indian_observations(rows) for c in o.weather_codes}
    assert not {c for c in codes if c[:2] in {"BR", "HZ", "FG", "FU"} and len(c) > 2}


def test_delhi_row_from_the_fixture(rows):
    vidp = next(o for o in metar.indian_observations(rows) if o.station_code == "VIDP")
    assert vidp.raw.startswith("METAR VIDP 240530Z")
    assert vidp.temperature_c == 31
    assert vidp.weather_codes == ["HZ"]
    assert vidp.lat == pytest.approx(28.567)


def test_plain_csv_is_accepted_as_well_as_gzip():
    plain = gzip.decompress(FIXTURE.read_bytes())
    assert len(metar.read_cache_rows(plain)) == 109


# ── Bad input ──────────────────────────────────────────────────────────────────

def test_corrupt_gzip_raises_value_error():
    with pytest.raises(ValueError, match="corrupt gzip"):
        metar.read_cache_rows(b"\x1f\x8b" + b"not really gzip")


def test_unexpected_columns_raise_value_error():
    with pytest.raises(ValueError, match="unexpected columns"):
        metar.read_cache_rows(b"a,b,c\n1,2,3\n")


def test_empty_file_raises_value_error():
    with pytest.raises(ValueError, match="empty"):
        metar.read_cache_rows(b"")


def test_a_row_with_no_time_is_dropped():
    row = {"station_id": "VIDP", "raw_text": "METAR VIDP 221530Z 35004KT 4000 HZ 30/24 Q1008",
           "observation_time": ""}
    assert metar.observation_from_row(row) is None


def test_csv_columns_fill_what_the_raw_text_omits():
    row = {
        "station_id": "VIDP",
        "raw_text": "METAR VIDP 221530Z /////KT //// Q1008",
        "observation_time": "2026-09-22T15:30:00Z",
        "temp_c": "30.4",
        "dewpoint_c": "24.1",
        "wind_speed_kt": "10",
        "visibility_statute_mi": "6+",
    }
    o = metar.observation_from_row(row)
    assert o.temperature_c == 30.4
    assert o.dewpoint_c == 24.1
    assert o.wind_kmh == 18.5
    assert o.visibility_m == 9656
