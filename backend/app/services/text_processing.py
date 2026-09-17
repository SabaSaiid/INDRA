"""
INDRA Platform — Text cleaning and metadata extraction (layer 3)

Pure functions, no I/O. `raw_text` in the database is never modified; these run
over it to produce what later steps read (per-report analysis, content
severity, spam rules).

    clean_text(s)          normalised text for models and rules
    extract_metadata(s)    {depth_cm, depth_basis, keywords, places, url_count, phone_count}

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

# ── Cleaning ───────────────────────────────────────────────────────────────────

# Zero-width space, word joiner, BOM. ZWJ (U+200D) and ZWNJ (U+200C) are kept:
# they shape Devanagari conjuncts and removing them changes the word.
_STRIP_CHARS = {"​", "⁠", "﻿"}
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")


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

def extract_metadata(s: str) -> Dict[str, Any]:
    """Depth, life-safety keywords, gazetteer places, URL and phone counts."""
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
