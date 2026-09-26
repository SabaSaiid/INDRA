"""Versioned, local language lexicons for synthetic report scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.ml.data.synthetic_nlp.scenarios import DatasetSplit, EventType, Language

LEXICON_VERSION: Final[str] = "synthetic-nlp-lexicon-v1"


@dataclass(frozen=True, slots=True)
class LocationName:
    english: str
    hindi: str
    hinglish: str

    def for_language(self, language: Language) -> str:
        return {
            "English": self.english,
            "Hindi": self.hindi,
            "Hinglish": self.hinglish,
        }[language]


LOCATIONS: Final[dict[DatasetSplit, tuple[LocationName, ...]]] = {
    "train": (
        LocationName("Kankarbagh, Patna", "कंकड़बाग, पटना", "Kankarbagh, Patna"),
        LocationName("Andheri East, Mumbai", "अंधेरी पूर्व, मुंबई", "Andheri East, Mumbai"),
        LocationName("Salt Lake, Kolkata", "सॉल्ट लेक, कोलकाता", "Salt Lake, Kolkata"),
        LocationName("Adyar, Chennai", "अडयार, चेन्नई", "Adyar, Chennai"),
        LocationName("Gomti Nagar, Lucknow", "गोमती नगर, लखनऊ", "Gomti Nagar, Lucknow"),
        LocationName(
            "Banjara Hills, Hyderabad",
            "बंजारा हिल्स, हैदराबाद",
            "Banjara Hills, Hyderabad",
        ),
        LocationName(
            "Indiranagar, Bengaluru", "इंदिरानगर, बेंगलुरु", "Indiranagar, Bengaluru"
        ),
        LocationName("Vashi, Navi Mumbai", "वाशी, नवी मुंबई", "Vashi, Navi Mumbai"),
        LocationName(
            "Paltan Bazar, Guwahati", "पलटन बाज़ार, गुवाहाटी", "Paltan Bazar, Guwahati"
        ),
        LocationName("Badambadi, Cuttack", "बादामबाड़ी, कटक", "Badambadi, Cuttack"),
        LocationName("Mansarovar, Jaipur", "मानसरोवर, जयपुर", "Mansarovar, Jaipur"),
        LocationName("Edappally, Kochi", "एडापल्ली, कोच्चि", "Edappally, Kochi"),
    ),
    "validation": (
        LocationName(
            "Rajendra Nagar, Delhi", "राजेंद्र नगर, दिल्ली", "Rajendra Nagar, Delhi"
        ),
        LocationName("Powai, Mumbai", "पवई, मुंबई", "Powai, Mumbai"),
        LocationName("Behala, Kolkata", "बेहाला, कोलकाता", "Behala, Kolkata"),
        LocationName("Velachery, Chennai", "वेलाचेरी, चेन्नई", "Velachery, Chennai"),
        LocationName("Aliganj, Lucknow", "अलीगंज, लखनऊ", "Aliganj, Lucknow"),
        LocationName("Secunderabad", "सिकंदराबाद", "Secunderabad"),
        LocationName(
            "Koramangala, Bengaluru", "कोरमंगला, बेंगलुरु", "Koramangala, Bengaluru"
        ),
        LocationName("Kalwa, Thane", "कलवा, ठाणे", "Kalwa, Thane"),
        LocationName("Doranda, Ranchi", "डोरंडा, रांची", "Doranda, Ranchi"),
        LocationName("Adajan, Surat", "अडाजन, सूरत", "Adajan, Surat"),
    ),
    "test": (
        LocationName("Ashok Nagar, Patna", "अशोक नगर, पटना", "Ashok Nagar, Patna"),
        LocationName("Kurla West, Mumbai", "कुर्ला पश्चिम, मुंबई", "Kurla West, Mumbai"),
        LocationName("Shibpur, Howrah", "शिबपुर, हावड़ा", "Shibpur, Howrah"),
        LocationName("Tambaram, Chennai", "तांबरम, चेन्नई", "Tambaram, Chennai"),
        LocationName("Hazratganj, Lucknow", "हज़रतगंज, लखनऊ", "Hazratganj, Lucknow"),
        LocationName("Hanamkonda, Warangal", "हनमकोंडा, वारंगल", "Hanamkonda, Warangal"),
        LocationName("Kuvempunagar, Mysuru", "कुवेम्पुनगर, मैसूरु", "Kuvempunagar, Mysuru"),
        LocationName("Old Panvel", "ओल्ड पनवेल", "Old Panvel"),
        LocationName("Matigara, Siliguri", "माटीगाड़ा, सिलीगुड़ी", "Matigara, Siliguri"),
        LocationName("Patia, Bhubaneswar", "पटिया, भुवनेश्वर", "Patia, Bhubaneswar"),
    ),
}

CONCEPTS: Final[dict[EventType, dict[Language, tuple[str, ...]]]] = {
    "URBAN_FLOOD": {
        "English": (
            "road flooding",
            "street water accumulation",
            "drainage overflow",
            "neighbourhood flooding",
        ),
        "Hindi": (
            "सड़क पर जलभराव",
            "गलियों में जमा पानी",
            "नालियों का उफान",
            "मोहल्ले में बाढ़ जैसा पानी",
        ),
        "Hinglish": (
            "road par waterlogging",
            "gali mein jama paani",
            "drain overflow",
            "mohalla flooding",
        ),
    },
    "RIVER_BREACH": {
        "English": (
            "river overtopping",
            "embankment failure",
            "a fresh river breach",
            "river water entering nearby settlements",
        ),
        "Hindi": (
            "नदी का किनारा पार करना",
            "तटबंध टूटना",
            "नदी में नया कटाव",
            "नदी का पानी बस्ती में घुसना",
        ),
        "Hinglish": (
            "nadi ka paani bank ke upar",
            "embankment tootna",
            "nadi mein fresh breach",
            "river water basti mein ghusna",
        ),
    },
    "CLOUDBURST": {
        "English": (
            "intense localized rainfall",
            "a sudden extreme downpour",
            "a short-duration rain burst",
            "a concentrated hill downpour",
        ),
        "Hindi": (
            "बेहद तेज़ स्थानीय बारिश",
            "अचानक मूसलाधार वर्षा",
            "कम समय की अत्यधिक बारिश",
            "पहाड़ी क्षेत्र में केंद्रित वर्षा",
        ),
        "Hinglish": (
            "bahut tez local baarish",
            "achanak extreme downpour",
            "short-duration rain burst",
            "pahadi area mein concentrated baarish",
        ),
    },
    "CYCLONE_INUNDATION": {
        "English": (
            "cyclone-linked coastal inundation",
            "storm-surge flooding",
            "coastal water ingress",
            "cyclone rain and sea-water impact",
        ),
        "Hindi": (
            "चक्रवात से जुड़ा तटीय जलभराव",
            "तूफानी ज्वार की बाढ़",
            "समुद्री पानी का तट में प्रवेश",
            "चक्रवाती बारिश और समुद्री पानी का असर",
        ),
        "Hinglish": (
            "cyclone-linked coastal flooding",
            "storm surge ka paani",
            "coast mein sea-water ingress",
            "cyclone rain aur samundari paani ka impact",
        ),
    },
    "NOT_RELEVANT": {
        "English": (
            "an ordinary weather update",
            "a traffic advisory",
            "a public-service announcement",
            "a community social message",
            "a non-weather civic update",
        ),
        "Hindi": (
            "सामान्य मौसम सूचना",
            "यातायात परामर्श",
            "जनसेवा घोषणा",
            "सामुदायिक संदेश",
            "गैर-मौसमी नागरिक सूचना",
        ),
        "Hinglish": (
            "normal weather update",
            "traffic advisory hai",
            "public-service announcement",
            "community ka social message",
            "non-weather civic update",
        ),
    },
}

# Values are split-specific by design. Test lexical combinations therefore do not
# appear in train even before template and scenario identifiers are considered.
SPLIT_TERMS: Final[dict[DatasetSplit, dict[Language, dict[str, tuple[str, ...]]]]] = {
    "train": {
        "English": {
            "rain": ("heavy rain", "steady monsoon rain", "intense showers"),
            "river": (
                "the river crossed its bank",
                "the embankment gave way",
                "a breach widened",
            ),
            "storm": (
                "a compact storm cell",
                "thunderclouds stalled overhead",
                "a violent rain cell",
            ),
            "cyclone": (
                "an approaching cyclone",
                "cyclonic winds",
                "a named coastal storm",
            ),
            "topic": (
                "a bus-route diversion",
                "a vaccination-camp notice",
                "a market-hours update",
            ),
        },
        "Hindi": {
            "rain": ("तेज़ बारिश", "लगातार मानसूनी वर्षा", "तीव्र बौछारें"),
            "river": ("नदी किनारे से ऊपर बह रही है", "तटबंध टूट गया", "कटाव चौड़ा हो गया"),
            "storm": (
                "छोटा लेकिन तीव्र बादल समूह",
                "गरज वाले बादल ठहरे रहे",
                "तेज़ वर्षा वाला बादल",
            ),
            "cyclone": ("पास आता चक्रवात", "चक्रवाती हवाएँ", "नामित तटीय तूफान"),
            "topic": (
                "बस मार्ग बदलने की सूचना",
                "टीकाकरण शिविर की सूचना",
                "बाज़ार के समय में बदलाव",
            ),
        },
        "Hinglish": {
            "rain": ("heavy baarish", "lagatar monsoon rain", "tez showers"),
            "river": (
                "nadi bank ke upar aa gayi",
                "embankment toot gaya",
                "breach aur khul gaya",
            ),
            "storm": (
                "compact storm cell",
                "thunderclouds ruk gaye",
                "violent rain cell",
            ),
            "cyclone": ("aata hua cyclone", "cyclonic hawa", "named coastal storm"),
            "topic": (
                "bus-route diversion",
                "vaccination camp ka notice",
                "market timing update",
            ),
        },
    },
    "validation": {
        "English": {
            "rain": (
                "relentless rainfall",
                "dense rain bands",
                "prolonged cloud cover with rain",
            ),
            "river": (
                "the floodwall was overtopped",
                "a levee section failed",
                "river flow escaped through a gap",
            ),
            "storm": (
                "a stationary convective cell",
                "a narrow torrent of rain",
                "a rapidly building storm pocket",
            ),
            "cyclone": (
                "the cyclone landfall band",
                "onshore gale conditions",
                "a severe coastal system",
            ),
            "topic": (
                "a library closure notice",
                "a power-maintenance message",
                "a school timetable reminder",
            ),
        },
        "Hindi": {
            "rain": (
                "बिना रुके वर्षा",
                "घनी बारिश की पट्टियाँ",
                "लंबे समय तक बादलों के साथ बारिश",
            ),
            "river": (
                "बाढ़ सुरक्षा दीवार के ऊपर पानी गया",
                "बांध का एक हिस्सा विफल हुआ",
                "दरार से नदी का बहाव बाहर निकला",
            ),
            "storm": (
                "एक जगह ठहरा संवहनीय बादल",
                "बारिश की संकरी तेज़ धारा",
                "तेज़ी से बना तूफानी क्षेत्र",
            ),
            "cyclone": ("चक्रवात की लैंडफॉल पट्टी", "समुद्र से आती तेज़ हवाएँ", "गंभीर तटीय तंत्र"),
            "topic": (
                "पुस्तकालय बंद रहने की सूचना",
                "बिजली रखरखाव संदेश",
                "स्कूल समय-सारिणी स्मरण",
            ),
        },
        "Hinglish": {
            "rain": (
                "rukne ka naam na leti rain",
                "dense rain bands",
                "long cloud cover ke saath baarish",
            ),
            "river": (
                "floodwall ke upar paani",
                "levee ka section fail",
                "gap se river flow bahar",
            ),
            "storm": (
                "stationary convective cell",
                "narrow torrent jaisi rain",
                "jaldi banta storm pocket",
            ),
            "cyclone": (
                "cyclone landfall band",
                "onshore gale wali hawa",
                "severe coastal system",
            ),
            "topic": (
                "library closure notice",
                "power maintenance ka message",
                "school timetable reminder",
            ),
        },
    },
    "test": {
        "English": {
            "rain": (
                "cloud sheets releasing torrents",
                "an abrupt wall of rain",
                "sustained high-intensity precipitation",
            ),
            "river": (
                "a protective bund was scoured open",
                "the channel spilled beyond its barrier",
                "a riverbank rupture released water",
            ),
            "storm": (
                "a micro-scale burst of rainfall",
                "a cloud mass unloading at once",
                "a sharply bounded deluge",
            ),
            "cyclone": (
                "the storm's surge front",
                "cyclone-driven sea rise",
                "the post-landfall coastal band",
            ),
            "topic": (
                "a parcel-delivery message",
                "a cultural-program invitation",
                "a municipal tax reminder",
            ),
        },
        "Hindi": {
            "rain": (
                "बादलों से धार की तरह बरसता पानी",
                "अचानक सामने आई बारिश की दीवार",
                "लगातार अत्यधिक तीव्र वर्षा",
            ),
            "river": (
                "सुरक्षा बांध कटकर खुल गया",
                "धारा अवरोध के बाहर फैल गई",
                "नदी किनारा फटने से पानी निकला",
            ),
            "storm": (
                "बहुत छोटे क्षेत्र में वर्षा विस्फोट",
                "बादल का एक साथ पूरा पानी बरसाना",
                "स्पष्ट सीमा वाली मूसलाधार बारिश",
            ),
            "cyclone": (
                "तूफानी ज्वार का अग्रभाग",
                "चक्रवात से बढ़ा समुद्री स्तर",
                "लैंडफॉल के बाद की तटीय पट्टी",
            ),
            "topic": (
                "पार्सल पहुंचने का संदेश",
                "सांस्कृतिक कार्यक्रम का निमंत्रण",
                "नगर कर का स्मरण",
            ),
        },
        "Hinglish": {
            "rain": (
                "cloud sheet se torrent jaisi baarish",
                "achanak wall of rain",
                "sustained high-intensity rain",
            ),
            "river": (
                "protective bund cut kar khul gaya",
                "channel barrier ke bahar spill hua",
                "riverbank rupture se paani nikla",
            ),
            "storm": (
                "micro-scale rain burst",
                "cloud mass ne ek saath paani chhoda",
                "sharp boundary wala deluge",
            ),
            "cyclone": (
                "storm surge ka front",
                "cyclone-driven sea rise",
                "post-landfall coastal band",
            ),
            "topic": (
                "parcel delivery ka message",
                "cultural program invitation",
                "municipal tax reminder",
            ),
        },
    },
}

SOURCE_STYLES: Final[tuple[str, ...]] = (
    "CITIZEN_APP",
    "SMS",
    "HELPLINE_TRANSCRIPT",
    "CONTROL_ROOM_NOTE",
    "COMMUNITY_POST",
    "FIELD_VOLUNTEER",
)

SEVERITIES: Final[dict[EventType, tuple[str, ...]]] = {
    "URBAN_FLOOD": ("ADVISORY", "MODERATE", "HIGH"),
    "RIVER_BREACH": ("MODERATE", "HIGH", "CRITICAL"),
    "CLOUDBURST": ("MODERATE", "HIGH", "CRITICAL"),
    "CYCLONE_INUNDATION": ("MODERATE", "HIGH", "CRITICAL"),
    "NOT_RELEVANT": ("NONE",),
}

WATER_DEPTHS_CM: Final[dict[EventType, tuple[int | None, ...]]] = {
    "URBAN_FLOOD": (8, 15, 25, 40, 55, 75, 95),
    "RIVER_BREACH": (35, 60, 90, 120, 160, 220),
    "CLOUDBURST": (None, 20, 45, 70),
    "CYCLONE_INUNDATION": (30, 65, 100, 145, 200),
    "NOT_RELEVANT": (None,),
}

DURATIONS_MINUTES: Final[tuple[int, ...]] = (12, 18, 24, 31, 42, 55, 68, 85)
WIND_SPEEDS_KMPH: Final[tuple[int, ...]] = (62, 74, 88, 96, 112, 128)
TIDE_RISE_CM: Final[tuple[int, ...]] = (45, 70, 95, 125, 160, 210)


def term_values(
    split: DatasetSplit,
    language: Language,
    category: str,
) -> tuple[str, ...]:
    return SPLIT_TERMS[split][language][category]


__all__ = [
    "CONCEPTS",
    "DURATIONS_MINUTES",
    "LEXICON_VERSION",
    "LOCATIONS",
    "SEVERITIES",
    "SOURCE_STYLES",
    "SPLIT_TERMS",
    "TIDE_RISE_CM",
    "WATER_DEPTHS_CM",
    "WIND_SPEEDS_KMPH",
    "LocationName",
    "term_values",
]
