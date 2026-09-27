"""
INDRA Platform — Text cleaning and metadata extraction (layer 3)

Pure functions, no I/O. `raw_text` in the database is never modified; these run
over it to produce what later steps read (per-report analysis, content
severity, spam rules).

    clean_text(s)          normalised text for models and rules
    detect_language(s)     "en" | "hi" | "hinglish", by script and vocabulary
    extract_metadata(s)    {depth_cm, depth_basis, keywords, places, url_count, phone_count,
                            hazards, hazard_primary, hazard_family, tense, negated,
                            temp_c, visibility_m, wind_kmh, rain_mm, implausible}
    html_to_text(s)        a Mastodon post's HTML as plain text (Phase 2 T4)
    canonical_url(u)       one article's many URLs as one (Phase 2 T7)
    core_text(s)           a post without its links and trailing hashtags (T7)

Depth extraction
----------------
A citizen rarely writes "87 cm". They write "knee-deep", "2-3 ft paani",
"कमर तक पानी", "water up to the roof". Two kinds of mention are read:

* **Measurements:** a number (digits, or a word like "one", "a", "do", "दो")
  followed by a unit (ft/feet/foot, inch, cm, m/metre/meter, मीटर, फीट). It only
  counts if a **water word is within 4 tokens** ("water", "flood", "paani",
  "पानी", "surge", …), so "30 feet from the river" is not a depth. A range
  ("2-3 ft") takes its upper bound.
* **Body and building references:** ankle 15, knee 50, waist 100, chest 130,
  neck 150, head / roof / first floor 250 cm. A body part only counts next to a
  depth cue ("deep", "high", "tak", "तक", "level", a water word …), so a knee
  injury is not a depth. A roof or first floor only counts when the water
  reaches it ("up to the roof", "above the roofs", "chhat tak", "छत तक"), so
  "people on roofs" is not a depth.

Several mentions → the maximum. The body-part values are conventional
approximations for an adult; the train split of data/labelled/reports_v1.csv is
what the rules were tuned on, and the test split measures them.
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.services.geocoding import INDIAN_GAZETTEER
from app.services.hazard_tagger import tag_hazards

# ── Cleaning ───────────────────────────────────────────────────────────────────

# Zero-width space, word joiner, BOM. ZWJ (U+200D) and ZWNJ (U+200C) are kept:
# they shape Devanagari conjuncts and removing them changes the word.
_STRIP_CHARS = {"​", "⁠", "﻿"}
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")

# ── Language detection ────────────────────────────────────────────────────────
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_LATIN_TOKEN_RE = re.compile(r"[a-z]+")

# Share of letters that must be Devanagari before a report counts as Hindi.
# Not "any Devanagari": English reports quote Hindi place names and single words
# often enough that a bare presence test would relabel them.
_DEVANAGARI_RATIO = 0.30

# Romanised Hindi that is never an ordinary English word. One is enough.
_HINGLISH_STRONG = frozenset({
    # water and flooding
    "paani", "pani", "baarish", "barish", "naali", "naala", "jaljamav",
    "jaljamaav", "bhara", "bharna", "bhar", "bharne", "bharti", "dooba",
    "doobi", "doobne",
    # body-part depth idioms
    "ghutno", "ghutne", "ghutna", "kamar", "seene", "chhat", "chhaton",
    # places and nouns
    "mohalle", "mohalla", "mohallon", "sadak", "sadkon", "galiyan", "galiyon",
    "logon", "gaadi", "gadiyan", "rickshaw", "andar", "neeche",
    # distress
    "bachao", "madad", "kripya", "phasa", "phase", "fansa", "fanse", "nikalo",
    "tainat", "shuru", "jaldi",
    # grammar glue — the strongest signal that a sentence is Hindi in Latin script
    "hai", "hain", "nahi", "nahin", "raha", "rahi", "rahe", "hua", "hui",
    "huye", "gaya", "gayi", "gaye", "mein", "yahan", "wahan", "kahan",
    "thoda", "bohot", "bahut", "kuch", "abhi", "kyunki", "lekin", "aur",
    "hamare", "hamari", "humara", "humari", "apne", "apni", "mera", "meri",
})

# Short Hindi particles that are also perfectly good English words in other
# contexts. Two or more before this counts as evidence — "water is rising
# towards me", "please log this report" and "the auto stand" are all English.
_HINGLISH_WEAK = frozenset({
    "ka", "ki", "ke", "ko", "se", "pe", "tak", "ghar", "gali", "log",
    "chal", "band", "par", "me", "ho", "kar", "auto", "upar",
})


def clean_text(s: str) -> str:
    """NFKC, invisible/control characters removed, URLs → <URL>, whitespace collapsed."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\t", " ").replace("\r", " ")
    s = "".join(
        ch for ch in s
        if ch not in _STRIP_CHARS and (ch == "\n" or unicodedata.category(ch) != "Cc")
    )
    s = URL_RE.sub(" <URL> ", s)
    s = re.sub(r"[^\S\n]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return s.strip()


# ── Tokens ─────────────────────────────────────────────────────────────────────

# Split on whitespace and punctuation (hyphens too, so "knee-deep" is two
# tokens). Not \w: Python's \w does not match Devanagari vowel signs and would
# cut words in half.
_TOKEN_RE = re.compile(r"[^\s,.;:!?()\[\]\"“”'‘’|/\-–—]+")


def _tokens(text: str) -> List[Tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def _starts(token: str, stems) -> bool:
    return any(token.startswith(stem) for stem in stems)


WATER_STEMS = (
    "water", "seawater", "floodwater", "flood", "submerg", "inundat", "surge", "torrent",
    "paani", "pani", "bhar", "पानी", "जल", "भर", "बाढ़", "baadh",
)
DEPTH_CUES = ("deep", "high", "level", "tak", "तक", "upto", "bhar", "भर")
REACH_BEFORE = ("up", "upto", "above", "over", "till", "to", "the", "reached", "reaching")

# ── Depth: body and building references ────────────────────────────────────────

BODY_PARTS: List[Tuple[str, int, Tuple[str, ...]]] = [
    ("ankle", 15, ("ankle", "takhn", "टखन")),
    ("knee", 50, ("knee", "ghutn", "ghutan", "घुटन")),
    ("waist", 100, ("waist", "kamar", "कमर")),
    ("chest", 130, ("chest", "seene", "seena", "छाती", "सीने", "सीना")),
    ("neck", 150, ("neck", "gardan", "गले", "गर्दन")),
]
REACH_DEPTH_CM = 250  # head, roof, first floor


def _body_depths(tokens: List[Tuple[str, int, int]]) -> List[Tuple[int, str]]:
    words = [t[0] for t in tokens]
    found: List[Tuple[int, str]] = []
    for i, w in enumerate(words):
        near = words[max(0, i - 3): i] + words[i + 1: i + 4]
        for name, cm, stems in BODY_PARTS:
            if _starts(w, stems) and any(_starts(n, DEPTH_CUES + WATER_STEMS) for n in near):
                found.append((cm, f"body:{name}"))

        before = words[max(0, i - 3): i]
        after = words[i + 1: i + 2]
        reached = any(b in REACH_BEFORE[:6] for b in before) or any(a in ("tak", "तक") for a in after)
        if w in ("head",) and (reached or any(a in ("height", "high", "level") for a in after)):
            found.append((REACH_DEPTH_CM, "reach:head"))
        elif _starts(w, ("roof", "chhat", "छत")) and reached:
            found.append((REACH_DEPTH_CM, "reach:roof"))
        elif w == "first" and words[i + 1: i + 2] and words[i + 1].startswith("floor") and reached:
            found.append((REACH_DEPTH_CM, "reach:first_floor"))
    return found


# ── Depth: measurements ────────────────────────────────────────────────────────

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "half": 0.5,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "aadha": 0.5,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "आधा": 0.5,
}
_UNITS_CM = {
    "ft": 30.48, "feet": 30.48, "foot": 30.48, "फीट": 30.48, "फुट": 30.48,
    "inch": 2.54, "inches": 2.54,
    "cm": 1.0,
    "m": 100.0, "mtr": 100.0, "metre": 100.0, "metres": 100.0, "meter": 100.0, "meters": 100.0,
    "मीटर": 100.0,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, _NUMBER_WORDS), key=len, reverse=True)) + r")"
_UNIT = "(" + "|".join(sorted(map(re.escape, _UNITS_CM), key=len, reverse=True)) + ")"
MEASURE_RE = re.compile(
    rf"(?<![\w.]){_NUM}(?:\s*(?:-|–|to)\s*{_NUM})?\s*-?\s*{_UNIT}(?![\wऀ-ॿ])",
    re.IGNORECASE,
)


def _as_number(tok: Optional[str]) -> Optional[float]:
    if tok is None:
        return None
    tok = tok.lower()
    if tok in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[tok])
    return float(tok)


def _measured_depths(text: str, tokens: List[Tuple[str, int, int]]) -> List[Tuple[int, str]]:
    found: List[Tuple[int, str]] = []
    for m in MEASURE_RE.finditer(text):
        low, high, unit = m.group(1), m.group(2), m.group(3).lower()
        value = max(v for v in (_as_number(low), _as_number(high)) if v is not None)
        idx = [i for i, (_, s, e) in enumerate(tokens) if s < m.end() and e > m.start()]
        if not idx:
            continue
        window = tokens[max(0, idx[0] - 4): idx[-1] + 5]
        if any(_starts(w, WATER_STEMS) for w, _, _ in window):
            found.append((int(round(value * _UNITS_CM[unit])), f"measure:{unit}"))
    return found


# ── Keywords and places ────────────────────────────────────────────────────────

LIFE_SAFETY_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("trapped", ("trap", "फंस", "फँस", "fase", "fasa", "fasi")),
    ("rescue", ("rescu", "बचा", "bachav", "bachao")),
    ("drown", ("drown", "डूबने", "डूबकर", "doobne", "dubne")),
    ("collapse", ("collaps", "ढह", "गिर")),
    ("electrocut", ("electrocut", "करंट", "karant")),
    ("missing", ("missing", "लापता", "laapata", "lapata")),
    ("dead", ("dead", "died", "death", "bodies", "killed", "मौत", "मृत", "maut", "mare")),
    ("boat", ("boat", "नाव", "naav")),
]
_EXACT_ONLY = {"fas"}  # a prefix would match "fast"


def _keywords(tokens: List[Tuple[str, int, int]]) -> List[str]:
    words = [t[0] for t in tokens]
    hits = []
    for name, stems in LIFE_SAFETY_KEYWORDS:
        if any(_starts(w, stems) or (name == "trapped" and w in _EXACT_ONLY) for w in words):
            hits.append(name)
    return hits


_PLACE_RE = re.compile(
    r"(?<![\w])(" + "|".join(sorted(map(re.escape, INDIAN_GAZETTEER), key=len, reverse=True)) + r")(?![\w])"
)


def _places(lowered: str) -> List[str]:
    seen: List[str] = []
    for m in _PLACE_RE.finditer(lowered):
        city = INDIAN_GAZETTEER[m.group(1)]["city"]
        if city not in seen:
            seen.append(city)
    return seen


# ── Public ─────────────────────────────────────────────────────────────────────

def detect_language(s: str) -> str:
    """
    "hi" (Devanagari), "hinglish" (romanised Hindi) or "en". Never raises.

    Rules, not a model — this is layer-3 processing, and a language *model* would
    be layer 4, which is out of scope:

    * **Devanagari share ≥ 30% of letters → "hi".** A threshold rather than "any
      Devanagari" because English reports routinely quote one Hindi place or
      word.
    * **A strong romanised-Hindi marker → "hinglish".** Words that are never
      ordinary English: paani, baarish, ghutno, mohalla, hai, nahi, mein, …
    * **Two or more weak markers → "hinglish".** Short Hindi particles that *are*
      English words in other contexts — ka, ke, se, pe, tak, par, me, ho, log,
      band, auto. One alone is not evidence; "water is rising towards me" is
      English.
    * Otherwise "en", the safe default: a misread language costs nothing
      downstream, since nothing routes or scores on it.

    **On the measured accuracy — read this before quoting it.** Against the
    `lang` column of `data/labelled/reports_v1.csv` this scores 100% on both the
    train (210) and test (90) splits. That number is much weaker evidence than it
    sounds: the dataset is **synthetic**, generated by this project, so its three
    languages are cleanly separated by script and by a small vocabulary. The
    honest claim is "the rule agrees with how that data was written", not "the
    rule is 100% accurate on real reports". Genuine code-mixing ("2 feet paani
    hai near Boring Road") is the case it would get wrong, and there is no
    labelled real-world data here to measure that on.

    The two-tier design exists because of a measured failure, not a guess: a
    single flat marker list also scored 100% on this dataset while misreading 5
    of 7 plain English sentences as Hinglish.
    """
    raw = s or ""
    devanagari = len(_DEVANAGARI_RE.findall(raw))
    letters = sum(1 for c in raw if c.isalpha())
    if letters and devanagari / letters >= _DEVANAGARI_RATIO:
        return "hi"

    tokens = set(_LATIN_TOKEN_RE.findall(raw.lower()))
    if tokens & _HINGLISH_STRONG:
        return "hinglish"
    if len(tokens & _HINGLISH_WEAK) >= 2:
        return "hinglish"
    return "en"


def extract_metadata(s: str, *, reference_year: Optional[int] = None) -> Dict[str, Any]:
    """
    Depth, life-safety keywords, gazetteer places, URL and phone counts, and
    (Phase 3) the hazards the text describes with its tense and numbers: see
    services/hazard_tagger.py for every rule. A depth cue makes the report a
    flood, so the tagger is given the depth found here.
    """
    raw = s or ""
    text = clean_text(raw).lower()
    tokens = _tokens(text)

    depths = _body_depths(tokens) + _measured_depths(text, tokens)
    depth_cm, depth_basis = (None, None)
    if depths:
        depth_cm, depth_basis = max(depths, key=lambda d: d[0])

    return {
        "depth_cm": depth_cm,
        "depth_basis": depth_basis,
        "keywords": _keywords(tokens),
        "places": _places(text),
        "url_count": len(URL_RE.findall(raw)),
        "phone_count": len(PHONE_RE.findall(raw)),
        **tag_hazards(raw, depth_cm=depth_cm, reference_year=reference_year),
    }


def depth_bucket(depth_cm: Optional[float]) -> Optional[str]:
    """<30, 30–79, 80–139, ≥140 cm — the resolution the severity rules use."""
    if depth_cm is None:
        return None
    if depth_cm < 30:
        return "<30"
    if depth_cm < 80:
        return "30-79"
    if depth_cm < 140:
        return "80-139"
    return ">=140"


# ── Posts: HTML to text (Phase 2 T4) ──────────────────────────────────────────

from html.parser import HTMLParser  # noqa: E402  (kept beside its only user)

# Tags that end a line of text. Everything else is inline.
_BLOCK_TAGS = {"p", "br", "div", "li", "ul", "ol", "blockquote", "h1", "h2", "h3", "h4", "pre"}


class _PostText(HTMLParser):
    """
    Collects a post's visible text. A link to a page becomes its URL, written
    once; a hashtag or mention link keeps its text ("#imd", "@user"), because
    that is what the author wrote.

    Mastodon renders a link as three spans — "https://" and the tail hidden,
    the middle shown — so reading the visible text would give a truncated,
    unusable URL, and reading all of it the URL plus fragments. The href is
    the one complete copy.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._link_depth = 0      # inside an <a> whose text is replaced by its href
        self._tag_link_depth = 0  # inside a hashtag or mention <a>

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag != "a":
            return
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if {"mention", "hashtag"} & set(classes) or (attrs.get("rel") or "") == "tag":
            self._tag_link_depth += 1
            return
        href = (attrs.get("href") or "").strip()
        if href:
            self.parts.append(f" {href} ")
        self._link_depth += 1

    def handle_endtag(self, tag):
        if tag == "a":
            if self._link_depth:
                self._link_depth -= 1
            elif self._tag_link_depth:
                self._tag_link_depth -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._link_depth:
            self.parts.append(data)


def html_to_text(html: Optional[str]) -> str:
    """
    A post's HTML as plain text: tags gone, entities decoded, each link's URL
    once, paragraphs and line breaks kept as single newlines.

    Never raises: text that will not parse is returned with its tags removed
    by a regex, which is worse but still text.
    """
    if not html:
        return ""
    try:
        parser = _PostText()
        parser.feed(html)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        import html as html_lib

        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


# ── Shared links (Phase 2 T7) ──────────────────────────────────────────────────

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit  # noqa: E402

# Query parameters that say who shared a link or how, never which page it is.
_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src",
    "ref_url", "cmpid", "s", "si", "feature", "share", "amp", "outputtype",
}
_HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")
_TRAILING_PUNCTUATION = ".,;:!?)]}'\"»”’"


def canonical_url(url: Optional[str]) -> Optional[str]:
    """
    The same article's URL, however it was shared, or None if it is not a URL.

        https://www.x.com/a/?utm_source=m#top    →  https://x.com/a
        https://m.x.com/a/amp                     →  https://x.com/a
        http://X.com/a?id=7&utm_medium=social     →  https://x.com/a?id=7

    Lowercases the host, drops `www.`/`m.`/`amp.`, the fragment, tracking
    parameters (`utm_*`, `fbclid`, …), a trailing slash and an AMP path
    segment, and treats http and https alike. Parameters that choose the page
    (`?id=7`) stay, sorted. Punctuation a sentence left on the end of the link
    is removed first.
    """
    if not url:
        return None
    url = url.strip().rstrip(_TRAILING_PUNCTUATION)
    if url.lower().startswith("www."):
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None

    host = parts.hostname.lower()
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]

    segments = [seg for seg in parts.path.split("/") if seg]
    if segments and segments[-1].lower() == "amp":
        segments = segments[:-1]
    if segments and segments[0].lower() == "amp":
        segments = segments[1:]
    path = "/" + "/".join(segments) if segments else ""

    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


_HASHTAG_TAIL_RE = re.compile(r"(?:\s*#\w+)+\s*$")


def core_text(s: Optional[str]) -> str:
    """
    What a post says, without the links and the run of hashtags it ends with.

    A news outlet's post is the headline, the link and a tail of tags; the
    same outlet's RSS item is the headline alone. Compared whole they differ
    by the link and the tags; compared by their core they are the same text,
    which is what a copy is.
    """
    text = URL_RE.sub(" ", s or "")
    text = _HASHTAG_TAIL_RE.sub("", text)
    return " ".join(text.split())

