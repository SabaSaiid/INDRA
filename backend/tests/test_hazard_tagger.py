"""
Phase 3 T1 and T2 — the hazard tagger: which hazards a report describes,
whether it says they are happening, and the numbers it quotes.

The first fifteen cases are T1's table, row for row, then fifteen more so every
one of the 15 hazards has a case in English and most in Hindi or Hinglish too
(the plan asks for 30). The traps the plan names are pinned individually:
Python's `\\b` on Devanagari (a word ending in a vowel sign, "लू" inside "लूट"),
BUG-088's Vietnamese "लू", and an English toilet. T2's table follows, then the
numbers and their plausible ranges.

Rules only: the tagger is `app/services/hazard_tagger.py`, not the frozen
classifier. Accuracy is measured separately, by `scripts/measure_hazard_tagger.py`.
"""

import pytest

from app.services.hazard_tagger import tag_hazards
from app.services.hazards import HAZARDS


def _tag(text):
    r = tag_hazards(text)
    return {h["type"] for h in r["hazards"]}, r["hazard_primary"]


# ── T1's table ─────────────────────────────────────────────────────────────────

T1_TABLE = [
    ("Heavy rain since morning, Boring Road waterlogged", {"RAINFALL", "URBAN_FLOOD"}, "URBAN_FLOOD"),
    ("46 degree hai, loo chal rahi hai", {"HEATWAVE"}, "HEATWAVE"),
    ("घना कोहरा, visibility 50 m on NH-44", {"FOG"}, "FOG"),
    ("Aandhi aayi, dust everywhere, trees uprooted", {"DUST_STORM", "STRONG_WIND"}, "DUST_STORM"),
    ("Bijli giri, thunder and heavy rain", {"LIGHTNING", "THUNDERSTORM", "RAINFALL"}, "LIGHTNING"),
    ("ओले गिरे, फसल बर्बाद", {"HAILSTORM"}, "HAILSTORM"),
    ("Badal phata near Kedarnath, road washed away", {"CLOUDBURST"}, "CLOUDBURST"),
    ("#DelhiFog flights diverted", {"FOG"}, "FOG"),
    ("Kadaake ki thand, 3 degree in Amritsar", {"COLD_WAVE"}, "COLD_WAVE"),
    ("Weather is nice today", set(), None),
    # The `\b` trap: कोहरा ends in a vowel sign, which `\w` does not include.
    ("घना कोहरा छाया", {"FOG"}, "FOG"),
    ("आंधी आई, पेड़ गिरे", {"DUST_STORM", "STRONG_WIND"}, "DUST_STORM"),
    # "लू" inside "लूट" (loot): `\bलू\b` matches it; tokens do not.
    ("बाज़ार में लूट", set(), None),
    # BUG-088: a transliterated Vietnamese name, with no heat word beside it.
    ("पार्टी सचिव ट्रान लू क्वांग ने कहा", set(), None),
    ("the loo was out of order", set(), None),
]


@pytest.mark.parametrize("text, hazards, primary", T1_TABLE)
def test_t1_table(text, hazards, primary):
    assert _tag(text) == (hazards, primary)


# ── Fifteen more: every hazard, and the three language forms ───────────────────

MORE = [
    ("Ganga above danger level at Patna, embankment breach near Maner", {"RIVER_BREACH"}, "RIVER_BREACH"),
    ("Nadi ufaan par, bandh toota", {"RIVER_BREACH"}, "RIVER_BREACH"),
    ("Landslide on the Mandi-Kullu highway, road blocked", {"LANDSLIDE"}, "LANDSLIDE"),
    ("भूस्खलन से सड़क बंद", {"LANDSLIDE"}, "LANDSLIDE"),
    # Sea water is a storm surge, not an urban flood, unless the text says flooded.
    ("Storm surge, sea water entered houses in Digha", {"CYCLONE_INUNDATION"}, "CYCLONE_INUNDATION"),
    ("Cyclone made landfall near Puri, gusty winds", {"CYCLONE", "STRONG_WIND"}, "CYCLONE"),
    ("चक्रवात का असर, तेज़ हवा चल रही है", {"CYCLONE", "STRONG_WIND"}, "CYCLONE"),
    ("Thunderstorm with heavy rain in Kolkata since evening", {"THUNDERSTORM", "RAINFALL"}, "THUNDERSTORM"),
    ("Hailstones the size of marbles in Shimla", {"HAILSTORM"}, "HAILSTORM"),
    ("बिजली गिरी, दो लोग घायल", {"LIGHTNING"}, "LIGHTNING"),
    ("मूसलाधार बारिश हो रही है", {"RAINFALL"}, "RAINFALL"),
    ("गली में पानी भर गया, घरों में घुसा", {"URBAN_FLOOD"}, "URBAN_FLOOD"),
    ("शीतलहर का प्रकोप, पारा 2 डिग्री", {"COLD_WAVE"}, "COLD_WAVE"),
    # "लू" with its companion is a heatwave.
    ("लू चल रही है, पारा 45 डिग्री", {"HEATWAVE"}, "HEATWAVE"),
    ("#MumbaiRains local trains running late", {"RAINFALL"}, "RAINFALL"),
    ("Strong wind, hoarding fell on a car at Ghatkopar", {"STRONG_WIND"}, "STRONG_WIND"),
    # Dust takes visibility: a dust storm's zero visibility is not fog.
    ("Dust storm in Jaipur, zero visibility on the highway", {"DUST_STORM"}, "DUST_STORM"),
    ("Sandstorm hits Bikaner", {"DUST_STORM"}, "DUST_STORM"),
    ("dense fog, 3-car pile-up on the expressway", {"FOG"}, "FOG"),
    ("a flood of emails this morning", set(), None),
    ("heat of the moment", set(), None),
]


@pytest.mark.parametrize("text, hazards, primary", MORE)
def test_more_cases(text, hazards, primary):
    assert _tag(text) == (hazards, primary)


def test_every_hazard_has_a_case():
    covered = set()
    for _, hazards, _ in T1_TABLE + MORE:
        covered |= hazards
    assert covered == {t for t in HAZARDS if t != "UNCLASSIFIED"}
    assert len(T1_TABLE) + len(MORE) >= 30


def test_the_family_follows_the_primary():
    assert tag_hazards("46 degree hai, loo chal rahi hai")["hazard_family"] == "thermal"
    assert tag_hazards("घना कोहरा छाया")["hazard_family"] == "visibility"
    assert tag_hazards("Weather is nice today")["hazard_family"] is None


# ── T2: negation, tense and numbers ────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, hazards, tense",
    [
        ("No rain today in Patna", set(), None),
        ("baarish nahi hui", set(), None),
        ("IMD: heavy rain likely in Patna tomorrow", {"RAINFALL"}, "forecast"),
        ("Orange alert issued for Kerala", set(), "forecast"),
        ("Throwback to the 2019 Patna floods", {"URBAN_FLOOD"}, "past"),
        # "kal" is both yesterday and tomorrow in Hindi, so it sets no tense.
        ("kal bahut baarish hui", {"RAINFALL"}, None),
    ],
)
def test_t2_negation_and_tense(text, hazards, tense):
    r = tag_hazards(text)
    assert {h["type"] for h in r["hazards"]} == hazards
    assert r["tense"] == tense


def test_a_denied_hazard_is_listed_as_negated():
    assert tag_hazards("No rain today in Patna")["negated"] == ["RAINFALL"]
    assert tag_hazards("baarish nahi hui")["negated"] == ["RAINFALL"]


@pytest.mark.parametrize(
    "text",
    [
        "no relief from the heat, 45 degree today",
        "no break in the rain since morning",
        "baarish ruk nahi rahi",
    ],
)
def test_a_continuing_hazard_is_not_a_denial(text):
    assert tag_hazards(text)["hazards"], text


def test_an_observation_outranks_a_forecast():
    """'Lashed ... more expected tomorrow' is evidence, not a forecast."""
    r = tag_hazards("Heavy rain lashed Mumbai today, more expected tomorrow")
    assert r["tense"] is None
    assert r["hazard_primary"] == "RAINFALL"


def test_worst_since_a_year_is_not_a_past_story():
    assert tag_hazards("Worst flooding since 2019, water entered homes")["tense"] is None


@pytest.mark.parametrize(
    "text, field, value, hazard",
    [
        ("48.5°C in Churu", "temp_c", 48.5, "HEATWAVE"),
        ("visibility barely 20 metres", "visibility_m", 20.0, "FOG"),
        ("winds of 90 kmph", "wind_kmh", 90.0, "STRONG_WIND"),
        ("120 mm rain in Chennai since last night", "rain_mm", 120.0, "RAINFALL"),
        ("पारा ४७ डिग्री पहुंचा, भीषण गर्मी", "temp_c", 47.0, "HEATWAVE"),
    ],
)
def test_t2_numbers(text, field, value, hazard):
    r = tag_hazards(text)
    assert r[field] == value
    assert r["hazard_primary"] == hazard
    assert r["implausible"] == []


def test_an_implausible_number_is_flagged_and_names_nothing():
    r = tag_hazards("temperature 75 degree")
    assert r["temp_c"] == 75.0
    assert r["implausible"] == ["temp_c"]
    assert r["hazards"] == []


@pytest.mark.parametrize(
    "text, implausible",
    [
        ("temperature 56 degree", ["temp_c"]),
        ("temperature 55 degree", []),
        ("winds of 260 km/h", ["wind_kmh"]),
        ("winds of 250 km/h", []),
    ],
)
def test_the_plausible_ranges_are_inclusive(text, implausible):
    assert tag_hazards(text)["implausible"] == implausible


def test_the_number_phrase_is_recorded_for_the_receipt():
    assert tag_hazards("46 degree hai, loo chal rahi hai")["number_phrases"]["temp_c"] == "46 degree"


def test_the_tagger_is_deterministic():
    texts = [t for t, _, _ in T1_TABLE + MORE]
    assert [tag_hazards(t) for t in texts] == [tag_hazards(t) for t in texts]


@pytest.mark.parametrize(
    "text, hazards, negated",
    [
        # The plan's own spellings, which the first regexes missed (26 Sep).
        ("Bhishan garmi se log pareshan, bahar mat niklo", {"HEATWAVE"}, []),
        ("Shitlahar chal rahi hai Patna mein", {"COLD_WAVE"}, []),
        ("sheet lehar ka prakop", {"COLD_WAVE"}, []),
        ("Not a single drop of rain in Jaipur this week", set(), ["RAINFALL"]),
    ],
)
def test_spelling_variants_and_not_a_drop(text, hazards, negated):
    r = tag_hazards(text)
    assert {h["type"] for h in r["hazards"]} == hazards
    assert r["negated"] == negated


# ── Found on the first 100 real posts (27 Sep): BUG-108 … BUG-112 ──────────────

@pytest.mark.parametrize(
    "text, hazards",
    [
        # BUG-108: आंधी with rain is a squall; alone, or with dust, a dust storm.
        ("गोरखपुर में बारिश और आंधी से कई पेड़ गिरे", {"THUNDERSTORM", "STRONG_WIND", "RAINFALL"}),
        ("आंधी-बारिश से आम की फसल को नुकसान", {"THUNDERSTORM", "STRONG_WIND", "RAINFALL"}),
        ("tez aandhi ke baad jhamajham baarish", {"THUNDERSTORM", "STRONG_WIND", "RAINFALL"}),
        ("धूल भरी आंधी के बाद हल्की बारिश", {"DUST_STORM", "RAINFALL"}),
        ("आंधी चली, आसमान में धूल ही धूल", {"DUST_STORM"}),
        ("आंधी आई, पूरा शहर धूल से भर गया", {"DUST_STORM"}),
        # BUG-111: drowned in fog is a figure of speech; drowned houses are a flood.
        ("घने कोहरे में डूबा शहर", {"FOG"}),
        ("गांव के कई घर पानी में डूब गए", {"URBAN_FLOOD"}),
        # BUG-110: the verb before लू.
        ("राजस्थान में कल से चलेगी लू", {"HEATWAVE"}),
        # BUG-109: continuing, and a circumstance rather than a denial.
        ("धुंध अभी टली नहीं है", {"FOG"}),
        ("बारिश में भी नहीं रुका मेला", {"RAINFALL"}),
        ("बारिश से कोई राहत नहीं", {"RAINFALL"}),
        # …while a plain denial still denies.
        ("इस बार बाढ़ नहीं आई", set()),
        # BUG-112: a joke is not a report.
        ("#Humor #SundayFunday #MumbaiRains", set()),
        ("#MumbaiRains local trains running late", {"RAINFALL"}),
    ],
)
def test_real_post_faults(text, hazards):
    assert {h["type"] for h in tag_hazards(text)["hazards"]} == hazards


@pytest.mark.parametrize(
    "text, tense",
    [
        # A Hindi auxiliary counts only right after a hazard word.
        ("भारी बारिश का अलर्ट, प्रशासन की ओर से लोगों को किया जा रहा सतर्क", "forecast"),
        ("तेज बारिश हो रही है, अलर्ट जारी", None),
        ("दो दिन में 60 मिमी बारिश रिकॉर्ड, आज भी अलर्ट", None),
        ("Rain and thunderstorm in Assam till Friday: IMD", "forecast"),
        ("Heavy rain alert across 12 districts of Odisha", "forecast"),
        ("The last week of the year brings dense fog, IMD expects", "forecast"),
        ("Photos from the floods last week", "past"),
    ],
)
def test_real_post_tense(text, tense):
    assert tag_hazards(text)["tense"] == tense


# ── Found on the second 100 real posts (27 Sep): BUG-113, BUG-114 ──────────────

@pytest.mark.parametrize(
    "text, hazards",
    [
        # BUG-113: a tag list at the end of a post that is not about weather.
        ("New cafe opened on MG Road, the coffee is great #Pune #WeekendVibes #MonsoonRains", set()),
        ("Is it autumn already? The leaves are turning #nature #coldwave", set()),
        # …a tag used as a word, or beside weather words, still counts.
        ("#Landslide blocks the Rishikesh highway", {"LANDSLIDE"}),
        ("IMD says more showers today #BengaluruRains", {"RAINFALL"}),
        ("Schools closed in Lucknow #coldwave", {"COLD_WAVE"}),
        ("Mercury touched 47 in Banda #heatwave", {"HEATWAVE"}),
        # …and so does a post of nothing but tags, or a photo's tags.
        ("#Cyclone #Andhra #Kakinada", {"CYCLONE"}),
        ("Morning at the lake #landscape #fog #nikon", {"FOG"}),
        # Creative writing and laughter: not a report.
        ("mist on the paddy / a heron waits / heavy rain #haiku #poetry", set()),
        ("When the office AC is your only friend 😂 #heatwave", set()),
        # A model code is a product.
        ("The new Cyclone V3 blender is on sale", set()),
        ("Cyclone Dana nears the Odisha coast", {"CYCLONE"}),
        # BUG-114: more Hindi forms.
        ("बुंदेलखंड में लू का वार जारी", {"HEATWAVE"}),
        ("बांदा में लू की स्थिति बनी हुई है", {"HEATWAVE"}),
        ("देर रात आंधी-पानी से कई गांवों की बिजली गुल", {"THUNDERSTORM", "STRONG_WIND", "RAINFALL"}),
        ("आंधी से पानी की टंकी गिरी", {"DUST_STORM"}),
        ("निचली बस्तियों में घुसा पानी", {"URBAN_FLOOD"}),
        ("60 किमी की रफ्तार से चली हवाएं, कई खंभे टूटे", {"STRONG_WIND"}),
        # A threat: dropped beside something happening now, a forecast alone.
        ("Heavy rain lashing Assam since morning, flood threat in 12 districts", {"RAINFALL"}),
        ("Risk of flooding in low-lying Patna", {"URBAN_FLOOD"}),
        ("कोसी के किनारे बाढ़ का खतरा", {"URBAN_FLOOD"}),
        ("गंगा खतरे के निशान के पार", {"RIVER_BREACH"}),
    ],
)
def test_second_real_post_faults(text, hazards):
    assert {h["type"] for h in tag_hazards(text)["hazards"]} == hazards


def test_a_threat_alone_is_a_forecast():
    r = tag_hazards("Flood threat looms over Darbhanga")
    assert {h["type"] for h in r["hazards"]} == {"URBAN_FLOOD"}
    assert r["tense"] == "forecast"


def test_a_hindi_wind_speed_is_read():
    r = tag_hazards("कल 70 KM की रफ्तार से चलेंगी तेज हवाएं")
    assert r["wind_kmh"] == 70.0
    assert "STRONG_WIND" in {h["type"] for h in r["hazards"]}


@pytest.mark.parametrize(
    "text, tense",
    [
        ("Orange alerts issued for four districts of Kerala, heavy rain likely", "forecast"),
        ("Heavy rain to lash Konkan within the next 6 hours", "forecast"),
        ("Dust storm warning in force now through 5 PM", "forecast"),
        ("Hail hits Shimla, orange alert for tomorrow", None),
        ("Waters receding in Silchar, alert stays", None),
        ("सुबह से लगातार बारिश, शाम तक अलर्ट", None),
        ("चक्रवात ने तट पर मचाई तबाही, फिर से अलर्ट", None),
        # "Caused" says it happened, not that it is happening now.
        ("Floods caused havoc in Kedarnath in 2013", "past"),
        # Readiness after a disaster is not a forecast.
        ("Wall collapse in heavy rain; the district remains on high alert", None),
    ],
)
def test_second_real_post_tense(text, tense):
    assert tag_hazards(text)["tense"] == tense
