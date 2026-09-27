"""
INDRA Platform — The hazard tagger (layer 3, Phase 3 T1 and T2)

Which hazards a report describes, whether it says they are happening, and the
numbers it quotes:

    tag_hazards(text, depth_cm=None) -> {
        "hazards":        [{"type", "basis", "matched"}, ...]   in precedence order
        "hazard_primary": "URBAN_FLOOD" | None                  the first of them
        "hazard_family":  "water" | "convective" | "thermal" | "visibility" | None
        "tense":          None | "forecast" | "past"            None = an observation
        "negated":        ["RAINFALL", ...]                     named, but denied
        "temp_c", "visibility_m", "wind_kmh", "rain_mm":  float | None
        "implausible":    ["temp_c", ...]                       outside a plausible range
        "number_phrases": {"temp_c": "46 degree", ...}          what each number was read from
    }

Rules and dictionaries, the same kind of layer-3 extraction as `depth_cm`. It
is not the frozen classifier (`app/ml/`), which stays unwired, and it is not a
model. Every rule is below, where a nodal officer can read it and argue with it.

Matching
--------
* **Latin script** (English and Hinglish) is matched with regexes over the
  folded text: NFKC, lower case, URLs removed. `\\b` is fine for Latin.
* **Devanagari is matched on tokens, never with `\\b`.** Python's `\\w` does not
  include vowel signs, virama or anusvara (`ा ी ू े ् ं`), so `\\bकोहरा\\b` misses
  "घना कोहरा" and `\\bलू\\b` matches inside "लूट" (loot). The text is split on
  whitespace and punctuation, and a lexicon entry is a token sequence; a
  trailing `*` on a token means "starts with", for inflections (`गिर*` is गिरा,
  गिरी, गिरे, गिरने).
* **Spelling variants are folded before matching:** the nukta is dropped
  (बाढ़ = बाढ, तेज़ = तेज) and chandrabindu becomes anusvara (आँधी = आंधी).
  Devanagari digits become ASCII, so "४७ डिग्री" is 47 degrees.
* **Hashtags are hints:** `#DelhiFog`, `#MumbaiRains`, `#KeralaFloods`,
  `#CycloneMichaung` name a hazard inside a word no `\\b` rule can see.

Rules that are not just a word list
-----------------------------------
* **"लू" / "loo" needs a companion** (BUG-088): "लू चल…", "लू के थपेड़े", "लू
  लगने", "लू से बचाव", "लू की चेतावनी", "loo chal rahi", or a heat word
  (गर्मी, तापमान, डिग्री, पारा, heat, degree) in the same sentence. Alone it is
  a Vietnamese name in a translated headline ("ट्रान लू क्वांग"), or an
  English toilet. The companions are word pairs, a little stricter than the
  plan's bare "लू का" / "लू से", because "लू का" also opens "Lu's statement".
  Headlines put the verb first too ("आज से चलेगी लू", BUG-110), so चल / लग in
  the two tokens before counts as well. "लू का वार", "लू की स्थिति" (BUG-114).
* **"आंधी" / "aandhi" with rain is a squall, not a dust storm** (BUG-108). Hindi
  news writes "आंधी-बारिश", "बारिश और आंधी" for a monsoon squall; with a rain
  word within 8 tokens and no dust word (धूल, रेत, dust, sand) it is
  THUNDERSTORM and STRONG_WIND. आंधी alone, or with dust, stays DUST_STORM.
  "आंधी-पानी" (storm and rain) is the same squall, and names the rain too: पानी
  counts as rain only right beside आंधी, where it cannot be a water tank.
* **A threat is a forecast, never an observation** (BUG-114). "Flood threat",
  "risk of flooding", "बाढ़ का खतरा" (threat, risk, fear, concern, scare, खतरा):
  in a report that is otherwise a forecast, or names nothing else, the hazard
  is kept and the tense is `forecast` ("heavy rain alert, landslide risk in
  hills"). Beside something happening now it is dropped, because the report's
  one tense would call it happening too ("rain continues for 40 hours; flood
  threat in 32 districts" is rain, not a flood).
* **"Cyclone" before a model code is a product** ("Cyclone RX600", BUG-113).
* **"डूब" next to fog is a figure of speech** ("कोहरे में डूबेगा प्रदेश", a state
  "drowned" in fog, BUG-111): with कोहरा, धुंध or अंधेरा in the 4 tokens before,
  it names no flood.
* **"तूफान" / "toofan" is a thunderstorm only next to rain words** (within 5
  tokens), and never after चक्रवाती (a cyclone) or रेतीला (a sandstorm). A bare
  English "storm" follows the same rule. "Aandhi-toofan" / "आंधी-तूफान" is a
  thunderstorm with strong wind, not a dust storm.
* **Sea water is a storm surge, not an urban flood.** "Sea water entered
  houses" is CYCLONE_INUNDATION; the report is also URBAN_FLOOD only when it
  says flooded, inundated, submerged or डूबे.
* **Dust takes visibility.** A visibility figure or "zero visibility" is fog
  evidence, unless the report names a dust storm, which is what took the
  visibility.
* **A depth is a flood.** A depth cue from `extract_metadata` ("knee-deep",
  "2 ft paani") makes a report URBAN_FLOOD, unless it is a storm surge's depth.
* **Numbers can name a hazard:** a temperature of 40 °C or more is a heatwave;
  5 °C or less next to a cold word is a cold wave; visibility under 1,000 m is
  fog (IMD's definition); wind of 39 km/h or more (Beaufort 6) is strong wind.
  An implausible number names nothing.

Negation (T2)
-------------
"no", "not", "never", "without", "didn't" and the like, or नहीं / nahi / बिना,
within **3 tokens before** a hazard word drop that occurrence ("No rain in
Patna", "without rain for weeks"). Hindi puts the negation after the verb, so
नहीं / nahi within **3 tokens after** drops it too ("baarish nahi hui", "बाढ़
नहीं आई"). Not a negation: "no relief from the heat", "no break in the rain",
"rain isn't stopping" (नहीं थम रही, ruk nahi rahi). An English report that
says the hazard "did not hit / never came" is dropped as well. A Hindi negation
after the word does not deny it when a postposition follows the word ("बारिश
में भी नहीं डिगा", "बारिश से राहत नहीं"): the hazard is then a circumstance, not
the thing denied (BUG-109); nor does टला नहीं ("hasn't passed"). A hazard is kept
if any one of its mentions is not denied; the denied ones are listed in
`negated`.

Tense (T2)
----------
`forecast` for a warning or prediction ("likely", "expected", "tomorrow",
"orange alert", "next 48 hours", "aane wale", संभावना, चेतावनी, अलर्ट, होगी);
`past` for an old story ("last year", "years ago", "#throwback", "old video",
पिछले साल, पुरानी तस्वीर, or an earlier year such as "2019 floods" — but not
"worst since 2019"). A report that also says the hazard is happening now
("since morning", "right now", "ho rahi hai", "lashed", "recorded", "amid",
"continues", "receding", हुई, रही, "रात से लगातार") is an observation, whatever
else it says: "rain lashed Mumbai; more expected tomorrow" is evidence, not a
forecast. "Now through 6:45 PM" is the end of a warning, not "now". Words that
say it happened ("hits", "caused", "triggered", "wreaked havoc", "मचाई तबाही")
also outrank a forecast, but not an old story: "rainfall caused flash flooding
on August 29, 2026" can still be `past`. A Hindi auxiliary (रहा, रही, हुई …) marks
an observation only in the 4 tokens after a hazard word: in "बारिश का अलर्ट … लोगों
को किया जा रहा सतर्क" it belongs to another verb. "Kal" is both yesterday and
tomorrow in Hindi, so it sets nothing.

Hashtags
--------
A post tagged as a joke (#Humor, #Funday, #Satire, #meme …) or laughing at
itself (🤣, 😂) is not a report: its other hashtags name no hazard (BUG-112).
Words in its text still count. A post tagged as creative writing (#haiku,
#poetry, #dailyhaikuprompt …) names no hazard at all, words included: a haiku
on the prompt word "fog" is not fog (BUG-113).

A hashtag names a hazard only when it is used as a word in a sentence ("#Cloudburst
in Tehri", "#DelhiFog 100 flights diverted"), or when the text around it is
about weather: it names a hazard itself, quotes a reading, or has a weather or
impact word (IMD, alert, forecast, मौसम, killed, stranded, closed …). A tag at
the end of a post about crickets ("#ClimateChange #HeatWave") names nothing
(BUG-113).

Measured, not asserted: `scripts/measure_hazard_tagger.py` scores this module
on `tests/fixtures/hazards_v1.csv` (a frozen held-out split) and, once
`tests/fixtures/hazards_real_v1.csv` has been sampled and labelled, on 100 real
posts; it writes `hazard_tagger_metrics.json` (not generated yet).
"""

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from app.services.hazards import by_precedence, family_of

# ── Folding ────────────────────────────────────────────────────────────────────

_FOLD: Dict[int, Optional[str]] = {
    ord("़"): None,        # nukta: बाढ़ = बाढ
    ord("ँ"): "ं",    # chandrabindu → anusvara: आँधी = आंधी
    ord("’"): "'",
    ord("‘"): "'",
}
_FOLD.update({ord(d): str(i) for i, d in enumerate("०१२३४५६७८९")})

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def fold(text: Optional[str]) -> str:
    """NFKC, URLs removed, lower case, Devanagari spelling variants folded."""
    s = unicodedata.normalize("NFKC", text or "")
    s = _URL_RE.sub(" ", s)
    return s.lower().translate(_FOLD)


# Whitespace and punctuation split tokens; so do hyphens ("आंधी-तूफान" is two
# tokens) and the danda. Not \w, which cuts Devanagari words at vowel signs.
_TOKEN_RE = re.compile(r"[^\s,.;:!?()\[\]{}\"'|/\\\-–—#।॥*+=<>@&%…]+")


@dataclass(frozen=True)
class _Tokens:
    words: List[str]
    starts: List[int]

    @classmethod
    def of(cls, text: str) -> "_Tokens":
        found = list(_TOKEN_RE.finditer(text))
        return cls([m.group(0) for m in found], [m.start() for m in found])

    def index_at(self, offset: int) -> int:
        """The token at (or just before) a character offset."""
        return max(bisect_right(self.starts, offset) - 1, 0)


def _starts_with_any(word: str, stems: Iterable[str]) -> bool:
    return any(word.startswith(stem) for stem in stems)


# ── The lexicon ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Cue:
    """
    One way of naming a hazard. Latin cues carry a regex over the folded text;
    Devanagari cues a token sequence. `kind` marks the cues with an extra rule
    (see the module docstring): loo, toofan, storm, surge, visibility.
    """

    hazard: str
    basis: str                                  # en | hinglish | hi | smog
    kind: str = ""
    pattern: Optional["re.Pattern[str]"] = None
    seq: Tuple[str, ...] = ()
    not_after: FrozenSet[str] = frozenset()     # cancelled by these in the 2 tokens before
    not_before: Tuple[str, ...] = ()            # cancelled when the next token starts so


def _en(hazard: str, *patterns: str, kind: str = "", basis: str = "en") -> List[Cue]:
    return [Cue(hazard, basis, kind, pattern=re.compile(p)) for p in patterns]


def _hl(hazard: str, *patterns: str, kind: str = "") -> List[Cue]:
    return _en(hazard, *patterns, kind=kind, basis="hinglish")


def _hi(
    hazard: str,
    *phrases: str,
    kind: str = "",
    not_after: Sequence[str] = (),
    not_before: Sequence[str] = (),
) -> List[Cue]:
    return [
        Cue(
            hazard, "hi", kind,
            seq=tuple(fold(w) for w in phrase.split()),
            not_after=frozenset(fold(w) for w in not_after),
            not_before=tuple(fold(w) for w in not_before),
        )
        for phrase in phrases
    ]


_SEA_HI = ("समुद्री", "समुद्र", "समुंदर", "समुंदरी")
_SEA_HL = r"(?<!samundar ka\s)(?<!samudra ka\s)(?<!samudri\s)(?<!samundari\s)"

LEXICON: List[Cue] = [
    # ── URBAN_FLOOD ────────────────────────────────────────────────────────
    *_en(
        "URBAN_FLOOD",
        r"\b(?:flash[\s-]?)?flood(?:s|ed|ing|water|waters)?\b"
        r"(?!\s+of\b)"
        r"(?!\s+with\s+(?:\w+\s+){0,2}?(?:calls|messages|emails|e-mails|requests|complaints|queries|orders"
        r"|applications|wishes|love|greetings|posts|comments|tweets|questions|offers|visitors|tourists"
        r"|enquiries|inquiries|responses|entries)\b)"
        r"(?![\s-]*(?:lights?|lit|gates?)\b)",
        r"\bwater[\s-]?logg(?:ed|ing)\b",
        r"\binundat(?:ed|es|ing|ion)\b",
        r"\bsubmerg(?:ed|es|ing|e)\b",
        r"\bunder[\s-]?water\b",
        r"\bmarooned\b",
        r"\bdeluge\b",
        # Water coming in. Not sea water: that is a storm surge (see below).
        r"(?<!sea\s)(?<!salt\s)\bwater\s+(?:has\s+|had\s+|is\s+|was\s+|have\s+)?"
        r"(?:entered|entering|enters|inside|gush(?:ed|ing|es)\s+into|rush(?:ed|ing|es)\s+(?:into|through)"
        r"|flowing\s+into)\b",
        r"(?<!sea\s)(?<!salt\s)\bwater\s+in(?:side)?\s+(?:our|the|my|their|people's)\s+"
        r"(?:houses?|homes?|shops?|colony|building)\b",
        r"\b(?:drains?|nalas?|nallahs?|nallas?|sewers?|gutters?|manholes?)\s+(?:are\s+|is\s+|were\s+|was\s+)?"
        r"overflow(?:ing|ed|s)?\b",
        r"\boverflowing\s+(?:drains?|nalas?|nallahs?|nallas?|sewers?|manholes?)\b",
    ),
    *_hl(
        "URBAN_FLOOD",
        r"\bbaa(?:dh|rh)\b",
        r"\bjal\s?bhara+v\b",
        r"\bjal\s?jama+v\b",
        r"\bjal\s?magn\b",
        _SEA_HL + r"\bpaa?ni\s+(?:bhar|ghus)\w*",
        _SEA_HL + r"\bpaa?ni\s+aa\s+(?:gaya|gayi|gaye|raha|rahi|rahe)\b",
        r"\bsaila+b\b",
    ),
    *_hl(
        "URBAN_FLOOD",
        r"\bdoo?b\s+(?:gaya|gayi|gaye|gai|gae|chuka|chuki|chuke|raha|rahi|rahe)\b",
        r"\bdoob(?:i|e|a)\b",
        kind="doob",
    ),
    *_hi("URBAN_FLOOD", "बाढ*", "जलभराव", "जलजमाव", "जलमग्न", "सैलाब"),
    *_hi("URBAN_FLOOD", "डूब*", kind="doob"),
    *_hi("URBAN_FLOOD", "पानी भर*", "पानी घुस*", not_after=_SEA_HI),
    # Headlines put the verb first: "सड़कों पर भरा पानी", "घरों में घुसा पानी" (BUG-114).
    *_hi("URBAN_FLOOD", "भरा पानी", "भर गया पानी", "घुसा पानी", "घुस गया पानी", not_after=_SEA_HI),

    # ── RIVER_BREACH ───────────────────────────────────────────────────────
    *_en(
        "RIVER_BREACH",
        r"\briver\s+(?:is\s+|was\s+|has\s+been\s+)?(?:overflow\w*|in\s+spate|swollen|breach\w*"
        r"|burst\s+its\s+banks)",
        r"\b(?:overflowing|swollen)\s+(?:the\s+)?rivers?\b",
        r"\bin\s+spate\b",
        r"\bembankments?\s+(?:has\s+|have\s+)?(?:breach\w*|broke|broken|burst|collapsed|washed\s+away"
        r"|gave\s+way|caved\s+in)",
        r"\bbreach(?:es|ed)?\s+(?:in|of|on)\s+(?:the\s+)?(?:\w+\s+){0,2}?"
        r"(?:embankments?|bunds?|dams?|levees?|canals?)\b",
        r"\b(?:embankment|bund|dam|levee|canal)\s+breach(?:es|ed)?\b",
        r"(?<!below\s)(?<!below\sthe\s)\bdanger\s+(?:levels?|marks?)\b",
        r"\b(?:bund|bandh|dam|levee|dyke|dike)\s+(?:broke|burst|breached|collapsed|gave\s+way)\b",
        r"\bburst\s+(?:its|their)\s+banks\b",
    ),
    *_hl(
        "RIVER_BREACH",
        r"\b(?:tat)?ba+ndh\s+(?:toot|tut)\w*",
        r"\bnadi(?:yan|yaan|yon)?\s+(?:me\s+|mein\s+)?(?:ufaa?n|uphaa?n)\w*",
        r"\bkhatre\s+ke\s+nisha+n\b",
    ),
    *_hi("RIVER_BREACH", "तटबंध टूट*", "बांध टूट*", "नदी उफान*", "नदियां उफान*", "खतरे के निशान*"),

    # ── CLOUDBURST ─────────────────────────────────────────────────────────
    *_en("CLOUDBURST", r"\bcloud[\s-]?bursts?\b"),
    *_hl("CLOUDBURST", r"\bba+dal\s+(?:phat|fat)\w*"),
    *_hi("CLOUDBURST", "बादल फट*"),

    # ── LANDSLIDE ──────────────────────────────────────────────────────────
    *_en(
        "LANDSLIDE",
        r"\bland[\s-]?(?:slides?|slips?)\b",
        r"\bmud[\s-]?slides?\b",
        r"\brock[\s-]?(?:falls?|slides?)\b",
        r"\bhill(?:side|s)?\s+(?:has\s+|had\s+)?(?:collapsed|caved\s+in|came\s+down|slid|gave\s+way|sank"
        r"|sinking|cracked)\b",
        r"\bdebris\s+(?:flow|slide)s?\b",
        r"\bboulders?\s+(?:rolling|rolled|fell|falling|came\s+down|crashed)\b",
    ),
    *_hl(
        "LANDSLIDE",
        r"\bbh(?:oo|u)\s?skhalan\b",
        r"\bpaha+d\s+(?:khisak|dhas|dhans|toot|tut|gir|dhah|darak)\w*",
    ),
    *_hi(
        "LANDSLIDE",
        "भूस्खलन*", "भू स्खलन*", "पहाड दरक*", "पहाड धंस*", "पहाड खिसक*", "पहाड टूट*", "पहाड गिर*",
        "पहाडी दरक*", "पहाडी धंस*",
    ),

    # ── CYCLONE_INUNDATION ─────────────────────────────────────────────────
    *_en(
        "CYCLONE_INUNDATION",
        r"\b(?:storm|tidal|sea)\s+surges?\b",
        r"\btidal\s+(?:waves?|flooding)\b",
        r"\b(?:sea|salt)\s?water\b",
    ),
    # A bare "surge" only on a coast: "surge in prices" is not a hazard.
    *_en("CYCLONE_INUNDATION", r"(?<!storm\s)(?<!tidal\s)(?<!sea\s)\bsurges?\b", kind="surge"),
    *_hl(
        "CYCLONE_INUNDATION",
        r"\bsamu(?:ndar|dra|ndra)\s+ka\s+paa?ni\b",
        r"\bsamu(?:ndari|dri)\s+paa?ni\b",
    ),
    *_hi(
        "CYCLONE_INUNDATION",
        "समुद्र का पानी", "समुंदर का पानी", "समुद्री पानी", "ज्वार की लहर*", "ज्वारीय लहर*", "तूफानी लहर*",
    ),

    # ── RAINFALL ───────────────────────────────────────────────────────────
    *_en(
        "RAINFALL",
        r"(?<!singer\s)(?<!star\s)(?<!purple\s)\brain(?:s|ing|ed|fall|falls)?\b"
        r"(?!\s+check)(?!\s+or\s+shine)"
        r"(?!\s+(?:the\s+)?(?:singer|star|actor|concert|album|song)\b)"
        r"(?!\s+on\s+(?:my|your|his|her|our|their)\s+parade)"
        r"(?!\s+of\s+(?:goals|runs|wickets|sixes|fours|boundaries|criticism|praise|bullets|blows|abuse"
        r"|money|gifts|cash|offers|punches|fire|questions|complaints)\b)",
        r"\bdownpours?\b",
        r"\bpouring\b(?!\s+(?:in|out)\s+(?:from|for|to)\b)"
        r"(?!\s+(?:money|support|donations|wishes|messages|love)\b)",
        r"\b(?:heavy|light|moderate|rain|thunder)\s?showers?\b",
        r"\bdrizzl(?:e|ing|ed)\b",
    ),
    *_hl(
        "RAINFALL",
        r"\bba+ri?sh\w*",
        r"\bbaa?ris\b",
        r"\bbarsa+t\w*",
        r"\bmoo?sla+dha+r\w*",
        r"\bjha+m\s?jha+m\b",
        r"\bjhamajham\b",
    ),
    # Not "ओलों की बारिश", a rain of hailstones.
    *_hi("RAINFALL", "बारिश*", "वर्षा", "मूसलाधार", "बरसात*", "झमाझम", "बौछार*", not_after=("ओलों", "ओले")),

    # ── THUNDERSTORM ───────────────────────────────────────────────────────
    *_en(
        "THUNDERSTORM",
        r"\bthunder(?:storms?|showers?|claps?|ing|s|ous|y)?\b",
        r"\bnor'?\s?westers?\b",
        r"\bkal\s?bai?sa?k?h(?:i|ee)\b",
        r"\belectrical\s+storms?\b",
    ),
    *_en(
        "THUNDERSTORM",
        r"(?<!dust\s)(?<!sand\s)(?<!hail\s)(?<!cyclonic\s)(?<!by\s)(?<!snow\s)(?<!rain\s)(?<!dust-)(?<!sand-)"
        r"\bstorms?\b(?![\s-]*(?:surges?|water|drains?)\b)",
        kind="storm",
    ),
    *_hl(
        "THUNDERSTORM",
        r"\bgara?j\w*",
        r"\baandhi[\s-]+t(?:oo|u)fa+n\w*",
        r"\bt(?:oo|u)fa+ni\s+ba+ri?sh\w*",
    ),
    *_hl(
        "THUNDERSTORM",
        r"(?<!chakravati\s)(?<!samudri\s)\bt(?:oo|u)fa+n\b",
        kind="toofan",
    ),
    *_hi("THUNDERSTORM", "गरज*", "मेघ गर्जन*", "आंधी तूफान*", "तूफानी बारिश*"),
    *_hi(
        "THUNDERSTORM", "तूफान",
        kind="toofan",
        not_after=("चक्रवाती", "चक्रवात", "समुद्री", "रेतीला", "रेतीली"),
    ),

    # ── LIGHTNING ──────────────────────────────────────────────────────────
    *_en(
        "LIGHTNING",
        r"\blightning\b(?![\s-]+(?:fast|quick|speed|deals?|sale|round|network|cable|port|connector|charger)\b)",
        r"\bthunderbolts?\b",
    ),
    *_hl(
        "LIGHTNING",
        r"\bbija?li\s+(?:gir|chamak|kadak)\w*",
        r"\b(?:aa?sma+ni|aa?kaa?shi(?:ya|y)?)\s+bija?li\b",
        r"\bthanka\b",
        r"\bvajra\s?pa+t\b",
    ),
    *_hi("LIGHTNING", "बिजली गिर*", "आकाशीय बिजली", "आसमानी बिजली", "वज्रपात*", "ठनका*", "बिजली कडक*", "बिजली चमक*"),

    # ── HAILSTORM ──────────────────────────────────────────────────────────
    *_en(
        "HAILSTORM",
        r"\bhail[\s-]?(?:storms?|stones?)\b",
        r"(?<!all\s)\bhail(?:ing)?\b"
        r"(?!\s+(?:a|an|the|from|mary|to|him|her|them|you|me|us|this|his|their|our)\b)",
    ),
    *_hl("HAILSTORM", r"\bole\s+(?:gir|pad|barse|bars)\w*", r"\bola+\s?vri?shti\b"),
    *_hi("HAILSTORM", "ओले", "ओलों", "ओलावृष्टि*", "ओला वृष्टि*"),

    # ── DUST_STORM ─────────────────────────────────────────────────────────
    *_en(
        "DUST_STORM",
        r"\b(?:dust|sand)[\s-]?storms?\b",
        r"\bdust\s+(?:everywhere|all\s+over|swept|engulfed)\b",
        r"\b(?:walls?|clouds?|sheet|haze)\s+of\s+(?:dust|sand)\b",
        r"\bhaboobs?\b",
    ),
    # "aandhi", never "andhi" (blind); and not "aandhi-toofan" (a thunderstorm).
    *_hl("DUST_STORM", r"\baandhi(?:yan|yaan|yon)?\b(?![\s-]+t(?:oo|u)fa)", kind="aandhi"),
    *_hi("DUST_STORM", "आंधी", "आंधियां", "आंधियों", kind="aandhi", not_before=("तूफान",)),
    *_hi("DUST_STORM", "रेतीला तूफान*", "रेतीली आंधी*"),

    # ── STRONG_WIND ────────────────────────────────────────────────────────
    *_en(
        "STRONG_WIND",
        r"\b(?:strong|high|heavy|gusty|fierce|powerful|violent|howling|severe)\s+winds?\b",
        r"\bgust(?:s|y|ing|ed)?\b",
        r"\bgales?\b",
        r"\bgale[\s-]force\b",
        r"\bsqual(?:ls?|ly)\b",
        r"\bwindstorms?\b",
        r"\btrees?\s+(?:were\s+|was\s+|have\s+been\s+|has\s+been\s+|got\s+|had\s+been\s+)?"
        r"(?:uprooted|fell|fallen|down|toppled|crashed|collapsed|blown\s+over)\b",
        r"\b(?:uprooted|fallen|toppled)\s+(?:trees?|poles?)\b",
        r"\b(?:roofs?|rooftops?|tin\s+sheets?|asbestos\s+sheets?)\s+(?:were\s+|was\s+|got\s+)?"
        r"(?:blown|ripped|torn|flew|flying)\b",
        r"\b(?:blew|blown|ripped|tore|tearing|flying)\s+(?:the\s+|off\s+the\s+|away\s+the\s+|off\s+)?"
        r"(?:roofs?|rooftops?)\b",
        r"\bhoardings?\s+(?:has\s+|have\s+)?(?:fell|fallen|collapsed|came\s+down|crashed|blown|toppled)\b",
        r"\b(?:electric(?:ity)?\s+)?poles?\s+(?:fell|fallen|down|uprooted|collapsed)\b",
    ),
    *_hl(
        "STRONG_WIND",
        r"\baandhi[\s-]+t(?:oo|u)fa+n\w*",
        r"\b(?:tez|tej|toofa+ni|tufa+ni|jordar|zordar)\s+hawa\w*",
        r"\bhawa\w*\s+(?:\w+\s+)?(?:tez|tej)\b",
        r"\bped\w*\s+(?:gir|ukhad|ukhar|toot|tut)\w*",
        r"\b(?:tin\s+ki\s+)?chha+t\w*\s+ud\w*",
        r"\bhoarding\w*\s+gir\w*",
        r"\bkhambh?e?\s+gir\w*",
    ),
    *_hi(
        "STRONG_WIND",
        "आंधी तूफान*", "तेज हवा*", "तूफानी हवा*", "पेड गिर*", "पेड उखड*", "पेडों गिर*", "छत* उड*",
        "होर्डिंग गिर*", "खंभे गिर*", "खंभा गिर*", "खंभे टूट*", "खंभा टूट*", "गिरे पेड*",
    ),

    # ── CYCLONE ────────────────────────────────────────────────────────────
    *_en(
        "CYCLONE",
        r"\bcyclon(?:e|es|ic)\b(?!\s+(?:the\s+)?(?:roller\s?coaster|ride)\b)"
        r"(?!\s+(?:fan|separator|dust\s+collector)\b)"
        r"(?!\s+[a-z]{1,4}\d)",                   # a model code: "Cyclone RX600"
        r"\blandfall\b",
        r"\bdeep\s+depression\s+(?:over|in|off|has|intensified|moving|centred|centered|lay|lies|formed|near)\b",
        r"\bdepression\s+over\s+(?:the\s+)?(?:bay|arabian|sea)\b",
        r"\btyphoon\b",
    ),
    *_hl("CYCLONE", r"\bchakra(?:va|wa)a?t\w*"),
    *_hi("CYCLONE", "चक्रवात*"),

    # ── HEATWAVE ───────────────────────────────────────────────────────────
    *_en(
        "HEATWAVE",
        r"\bheat[\s-]?waves?\b",
        r"\b(?:extreme|intense|severe|scorching|blistering|searing|unbearable|oppressive|sweltering|killer"
        r"|brutal)\s+heat\b",
        r"\bscorch(?:ing|er)\b",
        r"\b(?:heat|sun)[\s-]?strokes?\b",
    ),
    *_en("HEATWAVE", r"\bloo\b", kind="loo", basis="hinglish"),
    # "bhishan" is how the plan's own lexicon spells it; "bheeshan" is common too.
    *_hl("HEATWAVE", r"\b(?:bh(?:i|ee?)shan|bhayankar|bhayanak|kadi|kadak|prachand|tapti)\s+garmi\b"),
    *_hi("HEATWAVE", "भीषण गर्मी", "प्रचंड गर्मी", "तपती गर्मी", "झुलसाती गर्मी"),
    *_hi("HEATWAVE", "लू", kind="loo"),

    # ── COLD_WAVE ──────────────────────────────────────────────────────────
    *_en(
        "COLD_WAVE",
        r"\bcold[\s-]?waves?\b",
        r"\b(?:biting|bitter|freezing|severe|extreme|intense|piercing|chilling|harsh|bone[\s-]chilling)\s+cold\b",
        r"\b(?:ground\s+)?frost\b",
        r"\bcold\s+day\b",
        r"\bbelow\s+(?:the\s+)?freezing\b",
        r"\b(?:pipes?|lakes?|rivers?|ponds?|taps?|water)\s+(?:\w+\s+)?(?:froze|frozen)\b",
    ),
    *_hl(
        "COLD_WAVE",
        # shitlahar, sheetlahar, sheet lehar: the vowel after the l is optional.
        r"\b(?:shee?t|seet|shit)\s?l[ae]?ha+r\w*",
        r"\bkada+ke\s+ki\s+(?:thand|thandh|sardi)\b",
        r"\b(?:bh(?:i|ee?)shan|bhayankar|kadak|kadi|jabardast)\s+(?:thand|thandh|sardi)\b",
        r"\bpaa?la\s+pad\w*",
    ),
    *_hi("COLD_WAVE", "शीतलहर*", "शीत लहर*", "कडाके की ठंड*", "कडाके की सर्दी", "भीषण ठंड*", "भीषण सर्दी", "पाला पड*"),

    # ── FOG ────────────────────────────────────────────────────────────────
    *_en("FOG", r"\bfog(?:gy|s)?\b"),
    *_en("FOG", r"\bsmog(?:gy)?\b", basis="smog"),
    *_en(
        "FOG",
        r"\b(?:low|poor|zero|nil|no|reduced|near[\s-]zero|very\s+low|bad)\s+visibility\b",
        r"\bvisibility\s+(?:is\s+|was\s+|has\s+|near\s+|almost\s+|nearly\s+|dropped\s+to\s+|down\s+to\s+"
        r"|reduced\s+to\s+)*(?:zero|nil|poor|very\s+low|low)\b",
        kind="visibility",
    ),
    *_hl("FOG", r"\bkoh(?:ra+|re|ri)\b", r"\bdhu+nd\b", r"\bdhundh\s+(?:chha|chhay|chhai)\w*"),
    *_hi("FOG", "कोहर*", "कुहासा", "धुंध"),
    *_hi("FOG", "दृश्यता शून्य", "शून्य दृश्यता", kind="visibility"),
]

# A named storm: "Toofan Biparjoy". Matched on the text with its capitals kept.
_NAMED_STORM_RE = re.compile(r"\b[Tt](?:oo|u)fa+n\s+[A-Z][a-z]{2,}\b")

# ── Hashtags ───────────────────────────────────────────────────────────────────

_HASHTAG_RE = re.compile(r"#([a-z0-9_]+)")
_HASHTAG_HINTS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("CLOUDBURST", re.compile(r"cloudburst")),
    ("LANDSLIDE", re.compile(r"landslide|landslip")),
    ("CYCLONE_INUNDATION", re.compile(r"stormsurge|tidalsurge")),
    ("URBAN_FLOOD", re.compile(r"flood|waterlogg|baadh")),
    ("RAINFALL", re.compile(r"rain|barish|baarish")),
    ("THUNDERSTORM", re.compile(r"thunder")),
    ("LIGHTNING", re.compile(r"lightning")),
    ("HAILSTORM", re.compile(r"hailstorm|^hail$")),
    ("DUST_STORM", re.compile(r"duststorm|sandstorm|aandhi")),
    ("STRONG_WIND", re.compile(r"strongwind|gustywind|squall|galewind")),
    ("CYCLONE", re.compile(r"cyclone|chakravat")),
    ("HEATWAVE", re.compile(r"heatwave|heatstroke")),
    ("COLD_WAVE", re.compile(r"coldwave|shitlahar|sheetlahar")),
    ("FOG", re.compile(r"fog|smog|kohra")),
]
# A post tagged as a joke is not a report (BUG-112), nor one laughing at itself.
_HUMOUR_TAG = re.compile(r"humou?r|funday|satire|meme|joke|sarcasm|comedy|funny|^lol$")
_HUMOUR_EMOJI = ("🤣", "😂", "😹")
# Creative writing names no hazard at all, words included (BUG-113).
_CREATIVE_TAG = re.compile(
    r"haiku|senryu|tanka|poem|poetry|^poet$|writingprompt|amwriting|flashfiction|shortstory|^vss$"
    r"|writingcommunity|micropoetry"
)
# A photo's tags say what is in the picture: "#landscape #fog" is fog seen, as
# both real-post samples were labelled.
_PHOTO_TAG = re.compile(
    r"photo|landscape|analog|35mm|filmisnotdead|kodak|ilford|fujifilm|darktable|lightroom|blackandwhite"
    r"|monochrome|goldenhour|shotoniphone"
)
# A hashtag at the end of a post names a hazard only when the text around it is
# about weather (BUG-113): one of these, a hazard named in the text, or a reading.
_WEATHER_STEMS = (
    "weather", "mausam", "forecast", "alert", "warning", "advisory", "monsoon", "temperature",
    "visibility", "humidity", "storm", "killed", "stranded", "trapped", "evacuat", "rescu", "closed",
    "divert", "cancel", "delay", "damag", "destroy", "washed", "collaps", "uproot", "disrupt", "havoc",
    fold("मौसम"), fold("मानसून"), fold("तापमान"), fold("अलर्ट"), fold("चेतावनी"), fold("मौत"),
    fold("तबाही"), fold("कहर"), fold("नुकसान"), fold("फंस"), fold("हवा"),
)
# Whole words only: "wind" is not "window", "dead" not "deadline", "shut" not "shuttle".
_WEATHER_WORDS = frozenset({"imd", "nws", "wind", "winds", "windy", "dead", "died", "death", "deaths",
                            "shut", fold("बंद")})
# Hashtags that contain a hint by accident.
_HASHTAG_NOT = re.compile(r"train|brain|drain|grain|terrain|ukrain|strain|rainbow|raincoat|thunderbolt")

# ── Context words ──────────────────────────────────────────────────────────────

# A threat is a forecast (BUG-114): "flood threat", "risk of flooding", "बाढ़ का
# खतरा". Forecast words ("possibility", "likely") are not in these: they only
# set the tense, and leave the hazard in.
_THREAT_AFTER = frozenset({"threat", "threats", "risk", "risks", "fear", "fears", "concern", "concerns",
                           "scare", "scares", "worries", "khatra", "khatre", "khatara",
                           fold("खतरा"), fold("खतरे")})
_THREAT_BEFORE = frozenset({"threat", "threats", "risk", "risks", "fear", "fears", "danger", "concern",
                            "concerns"})
_POSTPOSITIONS_OF = frozenset({"ka", "ki", "ke", fold("का"), fold("की"), fold("के")})

_EN_NEGATORS = frozenset({
    "no", "not", "never", "without", "nor", "cannot",
    "didn", "doesn", "don", "isn", "wasn", "weren", "aren", "hasn", "haven", "hadn",
})
_HI_NEGATORS = frozenset({"nahi", "nahin", "nahii", "nhi", "bina", fold("नहीं"), fold("नही"), fold("बिना")})
# A negator followed by one of these is not denying the hazard: "no relief
# from the heat", "no break in the rain", "no less than 100 mm", "never seen
# such rain", "not only rain but floods".
_NOT_A_DENIAL_NEXT = ("relief", "respite", "end", "letup", "let", "stopping", "break", "escape", "doubt",
                      "less", "seen", "saw", "experienced", "witnessed", "imagined", "only", "just",
                      fold("राहत"))
# "Not a single drop of rain": the negator is too far back for the 3-token
# window, so the phrase is matched whole.
_NOT_A_DROP = (("not", "a", "single", "drop", "of"), ("not", "a", "drop", "of"), ("not", "one", "drop", "of"))
# "rain isn't stopping": रुक नहीं रही, थमने का नाम नहीं, ruk nahi rahi.
_CONTINUING = ("ruk", "tham", "naam", "tal", fold("रुक"), fold("थम"), fold("नाम"), fold("टल"))
# A Hindi negation after the hazard does not deny it when one of these follows
# the hazard word: "बारिश में भी नहीं डिगा", "बारिश से राहत नहीं" (BUG-109).
_HI_POSTPOSITIONS = frozenset({"me", "mein", "main", "se", "ke", "ki", "ka", "ko", "par", "pe",
                               fold("में"), fold("से"), fold("के"), fold("की"), fold("का"), fold("को"),
                               fold("पर")})
_DID_NOT_HAPPEN_RE = re.compile(
    r"^(?:\S+\s){0,2}?(?:did\s+not|does\s+not|has\s+not|had\s+not|didn\s+t|doesn\s+t|hasn\s+t|hadn\s+t|never)"
    r"\s+(?:\S+\s)?(?:hit|come|arrive|reach|occur|happen|make|strike|materiali[sz]e|form)\b"
)

# The loo companions (BUG-088): the word that must follow, or a heat word in
# the same sentence.
_LOO_NEXT = (
    ("chal",), ("lag",), ("ka", "prakop"), ("ka", "asar"), ("ka", "kahar"), ("ka", "alert"),
    ("ke", "thapede"), ("ke", "thapedo"), ("se", "bach"), ("se", "maut"), ("se", "behaal"),
    ("se", "rahat"), ("se", "pareshan"), ("ki", "chetavni"), ("ki", "chetawani"), ("ki", "chapet"),
    (fold("चल"),), (fold("लग"),), (fold("का"), fold("प्रकोप")), (fold("का"), fold("असर")),
    (fold("का"), fold("कहर")), (fold("का"), fold("अलर्ट")), (fold("के"), fold("थपेड")),
    (fold("से"), fold("बच")), (fold("से"), fold("मौत")), (fold("से"), fold("बेहाल")),
    (fold("से"), fold("राहत")), (fold("से"), fold("परेशान")), (fold("की"), fold("चेतावनी")),
    (fold("की"), fold("चपेट")), (fold("जैसे"), fold("हालात")), (fold("जैसी"), fold("स्थिति")),
    # BUG-114: "लू का वार", "लू की स्थिति".
    ("ka", "waar"), ("ki", "sthiti"), ("ka", "sitam"), ("ki", "maar"), ("ka", "daur"),
    (fold("का"), fold("वार")), (fold("की"), fold("स्थिति")), (fold("का"), fold("सितम")),
    (fold("की"), fold("मार")), (fold("का"), fold("दौर")),
)
# "आज से चलेगी लू": the verb before (BUG-110).
_LOO_BEFORE = ("chal", "lag", fold("चल"), fold("लग"))
_HEAT_WORDS = ("garmi", "tapman", "degree", "digri", "heat", "temperature", "paara", "mercury", "°",
               fold("गर्मी"), fold("तापमान"), fold("डिग्री"), fold("पारा"))
_COLD_WORDS = ("cold", "freez", "froze", "frost", "chill", "shiver", "thand", "sardi", "winter",
               fold("ठंड"), fold("सर्दी"), fold("शीत"), fold("ठिठुर"))
_COAST_WORDS = ("sea", "coast", "tide", "tidal", "cyclon", "landfall", "beach", "fishing", "fisher",
                "harbour", "port", "samundar", "samudra", "machhuar", "koliwada")
_WIND_WORDS = ("wind", "gust", "squall", "gale", "hawa", "storm", "cyclon", "toofan", "tufan", "aandhi",
               fold("हवा"), fold("तूफान"), fold("आंधी"))
_RAIN_WORDS = ("rain", "precipitation", "downpour", "shower", "recorded", "baarish", "barish",
               fold("बारिश"), fold("वर्षा"), fold("बरसात"))

# BUG-108: rain next to आंधी makes it a squall; dust keeps it a dust storm.
_RAIN_STEMS = ("rain", "baarish", "barish", "barsat", "bauchhar", fold("बारिश"), fold("वर्षा"),
               fold("बरसात"), fold("बूंदाबांदी"), fold("झमाझम"), fold("बौछार"))
_DUST_STEMS = ("dust", "dhool", "dhul", "sand", "reti", "retil", fold("धूल"), fold("रेत"), fold("गर्द"))
# "आंधी-पानी": water is rain only right beside आंधी (BUG-114).
_AANDHI_WATER = ("paani", "pani", fold("पानी"))
AANDHI_RAIN_SPAN = 8
# BUG-111: "कोहरे में डूबेगा" — drowned in fog, or in darkness.
_DOOB_FIGURATIVE = ("kohr", "dhund", "andher", "fog", fold("कोहर"), fold("धुंध"), fold("अंधेर"))

_SENTENCE_RE = re.compile(r"[.!?।\n]+")

# ── Tense ──────────────────────────────────────────────────────────────────────

_FORECAST_RE = re.compile(
    r"\b(?:will|likely|unlikely|expected|expect|expects|forecasts?|forecasted|predicted|predicts?|prediction"
    r"|possible|possibility|probable|probability|tomorrow|outlook|nowcast|warns?|warned|warnings?"
    r"|chances?\s+of|(?:orange|yellow|red)\s+alerts?|alert\s+(?:issued|for|has\s+been)|advisory\s+(?:issued|for)"
    r"|within\s+(?:the\s+next\s+)?(?:\d+\s+|a\s+few\s+|few\s+)?hours"
    r"|to\s+(?:hit|lash|batter|pound|strike|intensify)"
    r"|next\s+(?:\d+|few|two|three)\s+(?:hours|days)|coming\s+(?:hours|days)|next\s+week"
    r"|(?:till|until)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next|the\s+weekend)"
    r"|(?:rain|rainfall|weather|flood|storm|cyclone|heat|heatwave|cold\s?wave|fog|thunderstorm)\s+alerts?"
    r"|alerts?\s+(?:in|across|over)"
    r"|aane\s+wa+le|aane\s+vale|sambha+va?na|hogi|hoga|honge|cheta(?:va|wa)a?ni)\b"
)
_FORECAST_HI = frozenset(fold(w) for w in ("संभावना", "पूर्वानुमान", "चेतावनी", "अलर्ट", "होगी", "होगा", "होंगे",
                                            "आशंका", "अगले"))
_FORECAST_HI_SEQ = ((fold("आने"), fold("वाले")),)

_OBSERVED_RE = re.compile(
    r"\b(?:now(?!\s+(?:through|until|till)\b)|currently|at\s+the\s+moment|since|ongoing|recorded|reported"
    r"|received|lash(?:es|ed|ing)|amid|continu(?:es|ed|ing)|reced(?:es|ed|ing)"
    r"|batter(?:s|ed|ing)|pound(?:s|ed|ing)|killed|died|dead|stranded|trapped|uprooted|submerged"
    r"|waterlogged|inundated|evacuated|rescued"
    r"|abhi|ho\s+rah[aie]|chal\s+rah[aie]|rah[aie]\s+hai|rahe\s+hain|hui|hua|huyi)\b"
)
_OBSERVED_HI = frozenset(fold(w) for w in ("रही", "रहा", "रहे", "हुई", "हुआ", "गिरे", "गिरी", "रिकॉर्ड",
                                            "रिकार्ड", "दर्ज"))
# "रात से लगातार": continuously since, happening now.
_OBSERVED_HI_SEQ = ((fold("से"), fold("लगातार")), ("se", "lagatar"))
# It happened: not a forecast, though it may be an old story ("rainfall caused
# flash flooding in the Grand Canyon on August 29"), so these do not outrank past.
_OCCURRED_RE = re.compile(r"\b(?:hits|caus(?:ed|es|ing)|triggered|wreak(?:ed|s|ing)\s+havoc)\b")
_OCCURRED_HI = frozenset(fold(w) for w in ("मचाई", "मचाया", "बरपाया"))
# A Hindi auxiliary marks an observation only this close after a hazard word.
OBSERVED_HI_SPAN = 4

_PAST_RE = re.compile(
    r"\b(?:last\s+(?:year|week|month|monsoon|season|summer|winter)(?!\s+of\b)|years?\s+ago|months?\s+ago"
    r"|weeks?\s+ago"
    r"|throwback|tbt|flashback|anniversary|remembering"
    r"|old\s+(?:video|photo|pic|picture|clip|footage|image)s?"
    r"|pich+(?:le|li)\s+(?:saal|varsh|baras|hafte|mahine)|saal\s+(?:pehle|pahle)"
    r"|pura+n[aie]\s+(?:video|photo|pic|tasveer))\b"
)
_PAST_HI_SEQ = tuple(
    tuple(fold(w) for w in phrase.split())
    for phrase in ("पिछले साल", "पिछले वर्ष", "पिछले महीने", "साल पहले", "वर्ष पहले", "पुराना वीडियो",
                   "पुरानी तस्वीर", "पुरानी फोटो", "पुराने वीडियो", "पुरानी वीडियो")
)
# An earlier year, when it dates the report rather than compares with it.
_YEAR_RE = re.compile(r"(?<![\d.:/])(19[5-9]\d|20\d\d)(?![\d.:/])(?!\s*(?:hrs?|hours|ist|utc|gmt|z)\b)")
_YEAR_COMPARED = ("since", "than", "after", "till", "until", "from", "se", fold("से"), fold("बाद"))

# ── Numbers ────────────────────────────────────────────────────────────────────

_NUM = r"(\d{1,4}(?:\.\d{1,2})?)"
_TEMP_RE = re.compile(
    r"(?:(minus)\s+|(?<![\d.]))(-?\d{1,3}(?:\.\d{1,2})?)\s*"
    r"(?:°\s*c\b|°|degrees?(?:\s*(?:celsius|c))?\b|deg\b|digri\b|" + fold("डिग्री") + r")"
)
_TEMP_WORD_RE = re.compile(
    r"\b(?:mercury|paara|temperature|temp|tapman)\s+(?:\S+\s+){0,2}?(-?\d{1,2}(?:\.\d)?)\b"
    r"(?!\s*(?:mm|km|cm|m\b|%|kmph|kph|metre|meter|ft|feet|hours|hrs|pm|am))"
)
_TEMP_CONTEXT = ("temperature", "temp", "tapman", "mercury", "paara", "celsius", "heat", "garmi", "°",
                 fold("तापमान"), fold("पारा"), fold("गर्मी"))
_VIS_UNITS = r"(m|mtrs?|metres?|meters?|meter|km|kms|kilomet(?:re|er)s?|feet|ft|" + fold("मीटर") + r")"
_VIS_RES = (
    re.compile(
        r"\bvisibility\s+(?:(?:of|is|was|at|down|dropped|reduced|fell|to|below|under|less|than|barely|just"
        r"|only|around|about|near|nearly|hardly|mere|a)\s+)*" + _NUM + r"\s*" + _VIS_UNITS + r"(?![a-z])"
    ),
    re.compile(
        r"\b(?:can'?t|cannot|can\s+not|could\s+not|couldn'?t|unable\s+to)\s+see\s+(?:beyond|more\s+than|past"
        r"|further\s+than|farther\s+than)\s+" + _NUM + r"\s*" + _VIS_UNITS + r"(?![a-z])"
    ),
    re.compile(
        _NUM + r"\s*" + _VIS_UNITS + r"\s+(?:aage|aagey|door|tak)\s+(?:bhi\s+)?(?:nahi|nahin|na)\s+dikh"
    ),
    re.compile(fold("दृश्यता") + r"\s+" + _NUM + r"\s*" + _VIS_UNITS),
)
_VIS_ZERO_RE = re.compile(
    r"\b(?:zero|nil|no)\s+visibility\b|\bvisibility\s+(?:is\s+|was\s+)?(?:almost\s+|near\s+|nearly\s+)?(?:zero|nil)\b"
    r"|" + fold("दृश्यता") + r"\s+" + fold("शून्य") + r"|" + fold("शून्य") + r"\s+" + fold("दृश्यता")
)
_WIND_RE = re.compile(
    r"(?<![\d.])" + _NUM + r"(?:\s*(?:-|–|to)\s*" + _NUM + r")?\s*"
    r"(?:km\s*/\s*h(?:r|our)?|kmph|kmh|kph|km\s+per\s+hour|kilomet(?:re|er)s?\s+(?:per|an)\s+hour"
    r"|" + fold("किमी") + r"|" + fold("किलोमीटर") + r")(?![a-z])"
    # "80 KM की रफ्तार" (BUG-114): km, then speed.
    r"|(?<![\d.])" + _NUM + r"\s*km\s+(?:" + fold("की") + r"\s+)?(?:" + fold("रफ्तार") + r"|" + fold("गति")
    + r"|" + fold("स्पीड") + r"|speed)"
)
_RAIN_MM_RE = re.compile(
    r"(?<![\d.])" + _NUM + r"\s*(?:mm|millimet(?:re|er)s?|" + fold("मिमी") + r"|" + fold("मिलीमीटर") + r")(?![a-z])"
)

TEMP_RANGE_C = (-15.0, 55.0)
WIND_MAX_KMH = 250.0
RAIN_MAX_MM = 1000.0
VISIBILITY_MAX_M = 10000.0
DEPTH_MAX_CM = 1000.0           # 10 m of water in a city is not a report, it is a typo or a joke

HEATWAVE_FROM_C = 40.0          # plan T1: "a temperature ≥ 40 °C"
COLD_WAVE_TO_C = 5.0            # plan T1: "≤ 5 °C next to a cold word"
FOG_BELOW_M = 1000.0            # IMD: fog is visibility under 1 km
STRONG_WIND_FROM_KMH = 39.0     # Beaufort 6, the MODERATE boundary of the convective severity axis


def _near(tokens: _Tokens, index: int, stems: Sequence[str], span: int) -> bool:
    lo, hi = max(0, index - span), index + span + 1
    return any(_starts_with_any(w, stems) for w in tokens.words[lo:hi])


def _numbers(text: str, tokens: _Tokens) -> Dict[str, Any]:
    """
    temp_c, visibility_m, wind_kmh, rain_mm, which of them are implausible, and
    `number_phrases`: the words each chosen number was read from, for the
    severity receipt ("46 degree").
    """
    implausible: List[str] = []
    phrases: Dict[str, str] = {}
    temp_context = any(w in text for w in _TEMP_CONTEXT)

    temps: List[Tuple[float, str]] = []
    for m in _TEMP_RE.finditer(text):
        value = float(m.group(2)) * (-1 if m.group(1) else 1)
        plausible = TEMP_RANGE_C[0] <= value <= TEMP_RANGE_C[1]
        # "360 degree view" is not a temperature; "temperature 75 degree" is,
        # and an implausible one.
        if plausible or temp_context:
            temps.append((value, m.group(0).strip()))
    if not temps:
        temps = [(float(m.group(1)), m.group(0).strip()) for m in _TEMP_WORD_RE.finditer(text)]
    temp_c = None
    if temps:
        hot = [t for t in temps if t[0] >= HEATWAVE_FROM_C]
        cold = [t for t in temps if t[0] <= COLD_WAVE_TO_C]
        temp_c, phrases["temp_c"] = (
            max(hot) if hot else (min(cold) if cold else temps[0])
        )
        if not TEMP_RANGE_C[0] <= temp_c <= TEMP_RANGE_C[1]:
            implausible.append("temp_c")

    visibilities: List[Tuple[float, str]] = []
    zero = _VIS_ZERO_RE.search(text)
    if zero:
        visibilities.append((0.0, zero.group(0).strip()))
    for regex in _VIS_RES:
        for m in regex.finditer(text):
            value, unit = float(m.group(1)), m.group(2)
            if unit.startswith("k"):
                value *= 1000
            elif unit in ("feet", "ft"):
                value *= 0.3048
            if value <= VISIBILITY_MAX_M:
                visibilities.append((round(value, 1), m.group(0).strip()))
    visibility_m = None
    if visibilities:
        visibility_m, phrases["visibility_m"] = min(visibilities)

    winds: List[Tuple[float, str]] = []
    for m in _WIND_RE.finditer(text):
        if _near(tokens, tokens.index_at(m.start()), _WIND_WORDS, 5) or _near(
            tokens, tokens.index_at(m.end() - 1), _WIND_WORDS, 5
        ):
            winds.append((max(float(g) for g in m.groups() if g is not None), m.group(0).strip()))
    wind_kmh = None
    if winds:
        wind_kmh, phrases["wind_kmh"] = max(winds)
        if wind_kmh > WIND_MAX_KMH:
            implausible.append("wind_kmh")

    rains: List[Tuple[float, str]] = []
    for m in _RAIN_MM_RE.finditer(text):
        if _near(tokens, tokens.index_at(m.start()), _RAIN_WORDS, 5):
            rains.append((float(m.group(1)), m.group(0).strip()))
    rain_mm = None
    if rains:
        rain_mm, phrases["rain_mm"] = max(rains)
        if rain_mm > RAIN_MAX_MM:
            implausible.append("rain_mm")

    return {
        "temp_c": temp_c,
        "visibility_m": visibility_m,
        "wind_kmh": wind_kmh,
        "rain_mm": rain_mm,
        "implausible": implausible,
        "number_phrases": phrases,
    }


# ── Matching ───────────────────────────────────────────────────────────────────

@dataclass
class _Hit:
    hazard: str
    basis: str
    matched: str
    first: int      # token index of the first matched token
    last: int       # token index of the last
    kind: str = ""
    tag: str = ""   # inside a hashtag: "word" used in a sentence, "block" a tag list (BUG-113)


def _seq_at(words: List[str], i: int, seq: Tuple[str, ...]) -> bool:
    if i + len(seq) > len(words):
        return False
    for word, want in zip(words[i:i + len(seq)], seq):
        if want.endswith("*"):
            if not word.startswith(want[:-1]):
                return False
        elif word != want:
            return False
    return True


def _cue_hits(text: str, tokens: _Tokens, tags: Sequence["re.Match[str]"] = ()) -> List[_Hit]:
    hits: List[_Hit] = []
    words = tokens.words
    for cue in LEXICON:
        if cue.pattern is not None:
            # `\b` sees a word start after "#", so "#fog" and "#heatwave" match here too.
            for m in cue.pattern.finditer(text):
                hits.append(_Hit(
                    cue.hazard, cue.basis, m.group(0),
                    tokens.index_at(m.start()), tokens.index_at(max(m.end() - 1, m.start())), cue.kind,
                    _tag_at(text, tags, m.start()),
                ))
            continue
        for i in range(len(words)):
            if not _seq_at(words, i, cue.seq):
                continue
            end = i + len(cue.seq) - 1
            if cue.not_after and set(words[max(0, i - 2):i]) & cue.not_after:
                continue
            if cue.not_before and end + 1 < len(words) and _starts_with_any(words[end + 1], cue.not_before):
                continue
            hits.append(_Hit(cue.hazard, cue.basis, " ".join(words[i:end + 1]), i, end, cue.kind))
    return hits


def _hashtag_hits(text: str, tokens: _Tokens, tags: Sequence["re.Match[str]"]) -> List[_Hit]:
    hits: List[_Hit] = []
    for m in tags:
        body = m.group(1)
        if _HASHTAG_NOT.search(body):
            continue
        index = tokens.index_at(m.start(1))
        for hazard, hint in _HASHTAG_HINTS:
            if hint.search(body):
                hits.append(_Hit(hazard, "hashtag", m.group(0), index, index, tag=_tag_at(text, tags, m.start(1))))
    return hits


def _tag_at(text: str, tags: Sequence["re.Match[str]"], offset: int) -> str:
    """
    "" outside a hashtag. Inside one, "word" when a word follows it in the
    sentence ("#Cloudburst in Tehri"), else "block": a tag list, or the end.
    """
    for m in tags:
        if m.start() <= offset < m.end():
            rest = text[m.end():].lstrip(" \t,;:")
            return "word" if rest and rest[0].isalnum() else "block"
    return ""


def _about_weather(hits: List[_Hit], numbers: Dict[str, Any], tokens: _Tokens, hashtag_tokens: set) -> bool:
    """Does the text itself, hashtags aside, say it is about weather? (BUG-113)"""
    if any(not h.tag for h in hits):
        return True
    # Any reading, even an impossible one: "Chennai touched 77°C" is about the heat.
    if any(numbers[k] is not None for k in ("temp_c", "visibility_m", "wind_kmh", "rain_mm")):
        return True
    return any(
        w in _WEATHER_WORDS or _starts_with_any(w, _WEATHER_STEMS)
        for i, w in enumerate(tokens.words)
        if i not in hashtag_tokens
    )


def _sentence_of(text: str, offset: int) -> str:
    start = 0
    for m in _SENTENCE_RE.finditer(text):
        if m.start() >= offset:
            return text[start:m.start()]
        start = m.end()
    return text[start:]


def _keep_special(hit: _Hit, hits: List[_Hit], text: str, tokens: _Tokens) -> bool:
    """The extra rule a `kind` carries. See the module docstring."""
    words = tokens.words
    if hit.kind == "loo":
        after = words[hit.last + 1:hit.last + 3]
        for companion in _LOO_NEXT:
            if len(after) >= len(companion) and all(
                w.startswith(c) for w, c in zip(after, companion)
            ):
                return True
        before = words[max(0, hit.first - 2):hit.first]
        if any(_starts_with_any(w, _LOO_BEFORE) for w in before):
            return True
        offset = tokens.starts[hit.first] if tokens.starts else 0
        sentence = _sentence_of(text, offset)
        return any(w in sentence for w in _HEAT_WORDS)
    if hit.kind == "doob":
        before = words[max(0, hit.first - 4):hit.first]
        return not any(_starts_with_any(w, _DOOB_FIGURATIVE) for w in before)
    if hit.kind in ("toofan", "storm"):
        return any(
            h.hazard == "RAINFALL" and abs(h.first - hit.first) <= 5 for h in hits
        )
    if hit.kind == "surge":
        return any(_starts_with_any(w, _COAST_WORDS) for w in words)
    if hit.kind == "visibility":
        return not any(h.hazard == "DUST_STORM" for h in hits)
    return True


def _denied(hit: _Hit, tokens: _Tokens) -> bool:
    """Is this mention negated? See "Negation" in the module docstring."""
    words = tokens.words

    def is_negator(j: int, negators: FrozenSet[str]) -> bool:
        if not 0 <= j < len(words) or words[j] not in negators:
            return False
        nxt = words[j + 1] if j + 1 < len(words) else ""
        prev = words[j - 1] if j >= 1 else ""
        if nxt.startswith(_NOT_A_DENIAL_NEXT):
            return False
        if _starts_with_any(nxt, _CONTINUING) or _starts_with_any(prev, _CONTINUING):
            return False
        return True

    for phrase in _NOT_A_DROP:
        start = hit.first - len(phrase)
        if start >= 0 and tuple(words[start:hit.first]) == phrase:
            return True
    before = range(max(0, hit.first - 3), hit.first)
    if any(is_negator(j, _EN_NEGATORS | _HI_NEGATORS) for j in before):
        return True
    after = range(hit.last + 1, min(len(words), hit.last + 4))
    circumstance = hit.last + 1 < len(words) and words[hit.last + 1] in _HI_POSTPOSITIONS
    if not circumstance and any(is_negator(j, _HI_NEGATORS) for j in after):
        return True
    following = " ".join(words[hit.last + 1:hit.last + 7])
    return bool(_DID_NOT_HAPPEN_RE.match(following + " "))


def _apprehended(hit: _Hit, tokens: _Tokens) -> bool:
    """Is this mention a threat rather than the hazard? (BUG-114)"""
    words = tokens.words
    j = hit.last + 1
    if j < len(words) and words[j] in _POSTPOSITIONS_OF:
        j += 1
    if j < len(words) and words[j] in _THREAT_AFTER:
        # "खतरे के निशान" is the danger mark of a river, not a threat.
        return not (j + 2 < len(words) and words[j + 1] in _POSTPOSITIONS_OF and words[j + 2].startswith(
            ("nisha", fold("निशान"))
        ))
    for gap in (0, 1):             # "risk of flooding", "threat of heavy flooding"
        k = hit.first - 2 - gap
        if k >= 0 and words[k] in _THREAT_BEFORE and words[k + 1] == "of":
            return True
    return False


def _tense(text: str, tokens: _Tokens, reference_year: int, hazard_ends: Sequence[int] = ()) -> Optional[str]:
    words = tokens.words
    observed = bool(_OBSERVED_RE.search(text)) or any(
        words[j] in _OBSERVED_HI
        for end in hazard_ends
        for j in range(end + 1, min(len(words), end + 1 + OBSERVED_HI_SPAN))
    ) or any(_seq_at(words, i, seq) for seq in _OBSERVED_HI_SEQ for i in range(len(words)))
    occurred = bool(_OCCURRED_RE.search(text)) or any(w in _OCCURRED_HI for w in words)

    past = bool(_PAST_RE.search(text)) or any(
        _seq_at(words, i, seq) for seq in _PAST_HI_SEQ for i in range(len(words))
    )
    if not past:
        for m in _YEAR_RE.finditer(text):
            if int(m.group(1)) >= reference_year:
                continue
            index = tokens.index_at(m.start())
            previous = words[index - 1] if index >= 1 else ""
            if previous not in _YEAR_COMPARED:
                past = True
                break

    forecast = bool(_FORECAST_RE.search(text)) or any(w in _FORECAST_HI for w in words) or any(
        _seq_at(words, i, seq) for seq in _FORECAST_HI_SEQ for i in range(len(words))
    )

    if past and not observed:
        return "past"
    if forecast and not (observed or occurred):
        return "forecast"
    return None


def _number_hits(numbers: Dict[str, Any], hits: List[_Hit]) -> List[_Hit]:
    """Hazards a plausible number names on its own."""
    found: List[_Hit] = []
    implausible = set(numbers["implausible"])
    temp = numbers["temp_c"]
    if temp is not None and "temp_c" not in implausible:
        if temp >= HEATWAVE_FROM_C:
            found.append(_Hit("HEATWAVE", "temperature", f"{temp:g} °C", 0, 0))
        elif temp <= COLD_WAVE_TO_C:
            found.append(_Hit("COLD_WAVE", "temperature", f"{temp:g} °C", 0, 0, kind="cold_number"))
    vis = numbers["visibility_m"]
    if vis is not None and vis < FOG_BELOW_M and not any(h.hazard == "DUST_STORM" for h in hits):
        found.append(_Hit("FOG", "visibility", f"{vis:g} m", 0, 0))
    wind = numbers["wind_kmh"]
    if wind is not None and "wind_kmh" not in implausible and wind >= STRONG_WIND_FROM_KMH:
        found.append(_Hit("STRONG_WIND", "wind", f"{wind:g} km/h", 0, 0))
    return found


def _aandhi_with_rain(hits: List[_Hit], tokens: _Tokens) -> List[_Hit]:
    """BUG-108: आंधी with a rain word nearby and no dust is a squall."""
    words = tokens.words
    out: List[_Hit] = []
    for h in hits:
        if h.kind != "aandhi":
            out.append(h)
            continue
        near = words[max(0, h.first - AANDHI_RAIN_SPAN):h.last + 1 + AANDHI_RAIN_SPAN]
        rain = any(_starts_with_any(w, _RAIN_STEMS) and not w.startswith("train") for w in near)
        dust = any(_starts_with_any(w, _DUST_STEMS) and w not in ("sandwich",) for w in near)
        beside = words[max(0, h.first - 1):h.first] + words[h.last + 1:h.last + 2]
        water = any(w in _AANDHI_WATER for w in beside)
        if (rain or water) and not dust:
            out.append(_Hit("THUNDERSTORM", h.basis, h.matched, h.first, h.last, tag=h.tag))
            out.append(_Hit("STRONG_WIND", h.basis, h.matched, h.first, h.last, tag=h.tag))
            if water and not rain:
                out.append(_Hit("RAINFALL", h.basis, h.matched, h.first, h.last, tag=h.tag))
        else:
            out.append(h)
    return out


def tag_hazards(
    text: Optional[str],
    *,
    depth_cm: Optional[float] = None,
    reference_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    The hazards a report describes, its tense and its numbers. Pure and never
    raises on ordinary text; the same input always gives the same output
    (`reference_year` pins the one thing that depends on the clock: which
    years count as "earlier").
    """
    raw = text or ""
    folded = fold(raw)
    tokens = _Tokens.of(folded)
    year = reference_year or datetime.now(timezone.utc).year

    tags = list(_HASHTAG_RE.finditer(folded))
    creative = any(_CREATIVE_TAG.search(m.group(1)) for m in tags)
    joke = any(_HUMOUR_TAG.search(m.group(1)) for m in tags) or any(e in folded for e in _HUMOUR_EMOJI)
    hits = _cue_hits(folded, tokens, tags) + _hashtag_hits(folded, tokens, tags)
    if joke:
        hits = [h for h in hits if not h.tag]
    for m in _NAMED_STORM_RE.finditer(unicodedata.normalize("NFKC", raw)):
        hits.append(_Hit("CYCLONE", "hinglish", m.group(0).lower(), 0, 0))
    hits = [h for h in hits if _keep_special(h, hits, folded, tokens)]
    hits = _aandhi_with_rain(hits, tokens)

    numbers = _numbers(folded, tokens)
    hashtag_tokens = {tokens.index_at(m.start(1)) for m in tags}
    # A post of nothing but tags, or a photo, is what its tags say it is.
    only_tags = all(i in hashtag_tokens for i in range(len(tokens.words)))
    photo = any(_PHOTO_TAG.search(m.group(1)) for m in tags)
    if not (only_tags or photo or _about_weather(hits, numbers, tokens, hashtag_tokens)):
        hits = [h for h in hits if h.tag != "block"]
    cold_word = any(_starts_with_any(w, _COLD_WORDS) for w in tokens.words)
    for h in _number_hits(numbers, hits):
        if h.kind == "cold_number" and not cold_word:
            continue
        hits.append(h)

    surge = any(h.hazard == "CYCLONE_INUNDATION" for h in hits)
    if depth_cm is not None and not surge:
        hits.append(_Hit("URBAN_FLOOD", "depth", f"{depth_cm:g} cm", 0, 0))
    if creative:
        hits = []

    kept: Dict[str, _Hit] = {}
    denied: Dict[str, _Hit] = {}
    feared: Dict[str, _Hit] = {}
    for h in sorted(hits, key=lambda h: (h.first, h.hazard)):
        if h.basis in ("en", "hinglish", "hi", "smog") and _apprehended(h, tokens):
            feared.setdefault(h.hazard, h)
            continue
        if h.basis in ("en", "hinglish", "hi", "smog", "hashtag") and _denied(h, tokens):
            denied.setdefault(h.hazard, h)
            continue
        kept.setdefault(h.hazard, h)

    tense = _tense(folded, tokens, year, [h.last for h in kept.values() if h.basis != "hashtag"])
    # A threat is a forecast. Beside something happening now the report's one
    # tense would call it happening too, so there it is dropped (BUG-114).
    if feared and (not kept or tense == "forecast"):
        for t, h in feared.items():
            kept.setdefault(t, h)
        tense = "forecast"

    ordered = by_precedence(kept)
    primary = ordered[0] if ordered else None
    return {
        "hazards": [
            {"type": t, "basis": kept[t].basis, "matched": kept[t].matched} for t in ordered
        ],
        "hazard_primary": primary,
        "hazard_family": family_of(primary) if primary else None,
        "tense": tense,
        "negated": by_precedence(t for t in denied if t not in kept),
        **numbers,
        "implausible": numbers["implausible"] + (
            ["depth_cm"] if depth_cm is not None and depth_cm > DEPTH_MAX_CM else []
        ),
    }
