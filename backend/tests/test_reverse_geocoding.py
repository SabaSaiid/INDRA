"""
Tests for the reverse geocoder — coordinates to a district name.

The defect these exist to prevent is not "the name is missing". It is "the
name is wrong and nothing says so". A resolver that answers `Patna` for a
point in the Bay of Bengal is worse than one that answers nothing, because a
nodal officer has no way to tell the two apart on a map. So the assertions
here are about the *refusals* at least as much as the hits, and every band
boundary is pinned individually rather than sampled.
"""

import pytest

from app.services.geocoding import (
    DISTRICT_CONFIDENT_KM,
    DISTRICT_NEARBY_KM,
    Place,
    district_by_name,
    locate_area_description,
    load_districts,
    reverse_geocode,
    sanitize_coordinates,
)

# The centroid of the one real event in the live database: Kankarbagh, Patna.
LIVE_EVENT_LAT, LIVE_EVENT_LNG = 25.59428, 85.13746


def _offset_north(lat: float, lng: float, km: float) -> tuple[float, float]:
    """A point `km` north of the given one. One degree of latitude is ~111.32 km."""
    return lat + km / 111.32, lng


class TestGazetteerFile:
    def test_the_gazetteer_is_present_and_covers_the_country(self):
        districts = load_districts()
        assert len(districts) > 700
        assert len({d["state"] for d in districts}) >= 35

    def test_every_representative_point_is_inside_india(self):
        """
        Every row must be a place the resolver would itself accept. A row
        outside India's box is unreachable — reverse_geocode rejects the query
        before it ever gets there — so it would be dead weight that looks live.
        """
        from app.services.geocoding import is_within_india

        outside = [
            d for d in load_districts()
            if not is_within_india(d["lat"], d["lng"])
        ]
        assert outside == []

    def test_every_representative_point_is_inside_its_own_bounding_box(self):
        bad = [
            d["district"] for d in load_districts()
            if not (d["min_lat"] <= d["lat"] <= d["max_lat"]
                    and d["min_lng"] <= d["lng"] <= d["max_lng"])
        ]
        assert bad == []


class TestKnownPlaces:
    def test_the_live_events_centroid_resolves_to_patna(self):
        """The exact coordinate that was being served as "Unknown"."""
        place = reverse_geocode(LIVE_EVENT_LAT, LIVE_EVENT_LNG)
        assert place is not None
        assert place.district == "Patna"
        assert place.state == "Bihar"
        assert place.precision == "district"

    @pytest.mark.parametrize("lat,lng,district,state", [
        (19.0760, 72.8777, "Mumbai", "Maharashtra"),
        (12.9716, 77.5946, "Bengaluru Urban", "Karnataka"),
        (22.5726, 88.3639, "Kolkata", "West Bengal"),
        (13.0827, 80.2707, "Chennai", "Tamil Nadu"),
    ])
    def test_major_cities_resolve_to_their_district(self, lat, lng, district, state):
        place = reverse_geocode(lat, lng)
        assert place is not None
        assert (place.district, place.state) == (district, state)

    def test_a_huge_district_resolves_from_its_far_edge(self):
        """
        Western Kutch is ~85 km from the single point that represents Kutch —
        well past DISTRICT_NEARBY_KM. Nearest-point alone would refuse it.
        Bounding-box containment is the reason this works, so if someone
        removes that pass, this test is what fails.
        """
        place = reverse_geocode(23.60, 68.80)
        assert place is not None
        assert place.district == "Kutch"
        assert place.distance_km > DISTRICT_NEARBY_KM
        assert place.precision == "district"


class TestRefusals:
    """Where the resolver must decline rather than guess."""

    @pytest.mark.parametrize("name,lat,lng", [
        ("Bay of Bengal", 15.00, 88.00),
        ("Arabian Sea", 18.00, 69.00),
        ("London", 51.5074, -0.1278),
        ("the null island", 0.0, 0.0),
    ])
    def test_a_point_we_cannot_place_returns_none(self, name, lat, lng):
        assert reverse_geocode(lat, lng) is None, f"{name} was given a name"

    def test_missing_coordinates_return_none(self):
        assert reverse_geocode(None, None) is None
        assert reverse_geocode(25.0, None) is None
        assert reverse_geocode(None, 85.0) is None

    def test_an_unreadable_gazetteer_degrades_rather_than_raises(self, monkeypatch):
        monkeypatch.setattr("app.services.geocoding.load_districts", lambda: [])
        assert reverse_geocode(LIVE_EVENT_LAT, LIVE_EVENT_LNG) is None


class TestPrecisionBands:
    """
    The two constants are the resolver's whole honesty policy, so both
    boundaries are pinned from each side.

    These run against a synthetic one-district gazetteer with a deliberately
    tiny bounding box. Against real geography the boxes are large and overlap,
    so the containment pass answers first and the distance bands never decide
    anything — an early draft of these tests measured containment while
    claiming to measure distance, and passed for the wrong reason. A single
    pinpoint district is the only way to exercise the bands in isolation.
    """

    ORIGIN_LAT, ORIGIN_LNG = 25.0, 85.0

    @pytest.fixture(autouse=True)
    def _one_tiny_district(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.geocoding.load_districts",
            lambda: [{
                "district": "Testpur",
                "state": "Teststate",
                "lat": self.ORIGIN_LAT,
                "lng": self.ORIGIN_LNG,
                # A box far smaller than any band, so containment never fires.
                "min_lat": self.ORIGIN_LAT - 0.001,
                "min_lng": self.ORIGIN_LNG - 0.001,
                "max_lat": self.ORIGIN_LAT + 0.001,
                "max_lng": self.ORIGIN_LNG + 0.001,
            }],
        )

    def _at(self, km: float):
        return _offset_north(self.ORIGIN_LAT, self.ORIGIN_LNG, km)

    def test_the_fixture_really_does_bypass_containment(self):
        """If this fails, every other test in this class is measuring the wrong pass."""
        place = reverse_geocode(*self._at(DISTRICT_CONFIDENT_KM + 1.0))
        assert place is not None and place.distance_km > DISTRICT_CONFIDENT_KM

    def test_just_inside_the_confident_band_is_called_a_district(self):
        place = reverse_geocode(*self._at(DISTRICT_CONFIDENT_KM - 0.5))
        assert place is not None and place.precision == "district"

    def test_just_past_the_confident_band_is_called_near(self):
        place = reverse_geocode(*self._at(DISTRICT_CONFIDENT_KM + 0.5))
        assert place is not None and place.precision == "near"

    def test_just_inside_the_nearby_band_still_resolves(self):
        place = reverse_geocode(*self._at(DISTRICT_NEARBY_KM - 0.5))
        assert place is not None and place.precision == "near"

    def test_just_past_the_nearby_band_refuses(self):
        assert reverse_geocode(*self._at(DISTRICT_NEARBY_KM + 0.5)) is None

    def test_near_is_spelled_out_in_the_label(self):
        """
        The label carries the hedge, so a caller that prints `place.label`
        cannot accidentally present an approximation as a fact.
        """
        exact = Place("Patna", "Bihar", "district", 5.0)
        approx = Place("Patna", "Bihar", "near", 40.0)
        assert exact.label == "Patna"
        assert approx.label == "near Patna"


class TestDistrictByName:
    """The path SACHET CAP alerts take, since none of them carry a geometry."""

    def test_an_unambiguous_name_resolves(self):
        place = district_by_name("Mysuru")
        assert place is not None
        assert (place.district, place.state) == ("Mysuru", "Karnataka")

    def test_matching_ignores_case_and_surrounding_space(self):
        assert district_by_name("  mYsUrU  ") == district_by_name("Mysuru")

    def test_an_ambiguous_name_is_refused_without_a_state(self):
        """Bilaspur is in both Chhattisgarh and Himachal Pradesh."""
        assert district_by_name("Bilaspur") is None

    def test_an_ambiguous_name_resolves_with_a_state_hint(self):
        place = district_by_name("Bilaspur", "Himachal Pradesh")
        assert place is not None
        assert place.state == "Himachal Pradesh"

    def test_a_wrong_state_hint_refuses_rather_than_falling_back(self):
        assert district_by_name("Bilaspur", "Kerala") is None

    def test_an_unknown_name_returns_none(self):
        assert district_by_name("Atlantis") is None
        assert district_by_name("") is None
        assert district_by_name("   ") is None


class TestSanitizeCoordinatesNowNamesThings:
    """
    `sanitize_coordinates` used to answer "India Node" for any report that
    carried GPS — which is nearly all of them — so the ingest path computed a
    name it could not use. BUG: that placeholder is what made the resolved
    city a dead variable at api/reports.py.
    """

    def test_valid_gps_now_resolves_a_real_name(self):
        lat, lng, city, state = sanitize_coordinates(LIVE_EVENT_LAT, LIVE_EVENT_LNG)
        assert (lat, lng) == (LIVE_EVENT_LAT, LIVE_EVENT_LNG)
        assert (city, state) == ("Patna", "Bihar")

    def test_the_placeholder_is_gone(self):
        _, _, city, _ = sanitize_coordinates(19.0760, 72.8777)
        assert city != "India Node"

    def test_an_explicit_city_hint_still_wins(self):
        """A caller that already knows the name is not overridden by the resolver."""
        _, _, city, _ = sanitize_coordinates(
            LIVE_EVENT_LAT, LIVE_EVENT_LNG, city_hint="Kankarbagh"
        )
        assert city == "Kankarbagh"

    def test_an_inverted_pair_is_corrected_and_then_named(self):
        """The swap fix and the naming fix have to compose."""
        lat, lng, city, state = sanitize_coordinates(85.13746, 25.59428)
        assert (round(lat, 5), round(lng, 5)) == (25.59428, 85.13746)
        assert (city, state) == ("Patna", "Bihar")


class TestAreaDescriptions:
    """
    Resolving CAP alerts, which carry prose and no geometry.

    Measured against the 116 area descriptions in the live SACHET corpus:
    98 resolve (35 of them only to a state), and the 18 that do not are
    mandal-level scopes or not places at all ("some parts", "MOD TSRA").
    """

    def test_a_list_of_districts_resolves_to_all_of_them(self):
        places = locate_area_description(
            "Chamarajanagara,Kodagu,Mysuru districts of Karnataka"
        )
        assert [p.district for p in places] == ["Chamarajanagara", "Kodagu", "Mysuru"]
        assert {p.state for p in places} == {"Karnataka"}

    def test_a_transliteration_still_resolves(self):
        """
        CAP senders spell as they please: the live feed says "Puruliya" and
        "Pashchim Medinipur" where the gazetteer says "Purulia" and "Paschim
        Medinipur". Before near-name matching only the first of the three
        districts in this real description resolved.
        """
        places = locate_area_description(
            "Jhargram,Pashchim Medinipur,Puruliya districts of West Bengal"
        )
        assert [p.district for p in places] == [
            "Jhargram", "Paschim Medinipur", "Purulia",
        ]

    def test_a_near_name_is_not_matched_across_the_country(self):
        """
        Near-name matching is confined to a named state. Without that guard a
        sender's typo becomes a confident answer somewhere else entirely.
        """
        places = locate_area_description("Purulia district of Kerala")
        assert all(p.state == "Kerala" for p in places)

    def test_a_river_gauge_description_finds_the_district(self):
        """The live CWC format: river, station, district, state."""
        places = locate_area_description("Ganga, Bhagalpur, Bhagalpur, Bihar")
        assert places[0].district == "Bhagalpur"
        assert places[0].state == "Bihar"

    def test_a_state_wide_alert_resolves_to_the_state_and_says_so(self):
        places = locate_area_description("6 districts of Kerala")
        assert len(places) == 1
        assert places[0].precision == "state"
        assert places[0].state == "Kerala"
        assert places[0].district is None
        assert places[0].label == "Kerala"

    @pytest.mark.parametrize("area_desc", [
        "atp-bukkarayasamudram, atp-singanamala mandals",
        "mkp-giddalur Mandal",
        "some parts",
        "MOD TSRA",
        "",
        None,
    ])
    def test_a_scope_below_district_level_resolves_to_nothing(self, area_desc):
        """
        Mandals are below this gazetteer's resolution. Returning nothing keeps
        the alert off the map, which is the right outcome: a mandal pinned to
        a district centroid is a warning shown in the wrong place.
        """
        assert locate_area_description(area_desc) == []

    def test_duplicate_names_are_not_repeated(self):
        places = locate_area_description("Patna, Patna district, Bihar")
        assert len(places) == 1
