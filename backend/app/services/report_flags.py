"""
INDRA Platform — Misleading-text flags (layer 3, Phase 3 T8 part A)

Published rules that say a report is probably not a clean first-hand
observation, each with its effect on the report's credibility. They are the
surface signals the PS's "misleading reports" row asks for, as rules a
commander can read, not a model:

| flag                 | rule                                                                  | credibility × |
|----------------------|-----------------------------------------------------------------------|---------------|
| `promotional`        | a phone number, 2+ URLs, or sales words ("buy", "discount", "offer", "call now", "whatsapp me") | 0.3 |
| `not_an_observation` | a forecast or warning (the tagger's tense)                            | — kept as context, excluded from density |
| `past_event`         | an old story: past tense, an old year, "#throwback"                   | 0.4 |
| `implausible_value`  | temperature > 55 °C (or < −15), wind > 250 km/h, rain > 1,000 mm, water deeper than 10 m | 0.3 |
| `exaggeration`       | "never seen before", "biggest ever", "end of the world", "whole city underwater", "apocalypse", "100 feet", प्रलय | 0.7 |
| `shouting`           | capitals over 60% of at least 20 letters, or "!!!"                     | 0.9 |
| `forward_marker`     | "forwarded as received", "forward to all", "share maximum", "please share", "viral", "must watch" | 0.6 |
| `coordinated`        | the same text from 3+ different reporters within 10 minutes (set by the pipeline, which can see the other reports) | 0.5 |

**Phase 5** adds two groups that are not about the text, listed here so one
table says what every flag costs:

| flag                 | set by                                                   | credibility × |
|----------------------|----------------------------------------------------------|---------------|
| `new_account`        | a social account less than 7 days old (T7, `account_signals.py`) | 0.6 |
| `few_followers`      | fewer than 5 followers (T7)                              | 0.8 |
| `bot_account`        | the platform marks the account a bot (T7)                | 0.8, and at most 0.5 of a witness in n_eff |
| `duplicate_media`    | the same file as another reporter's (T3, `media_rules.py`) | — the two count as one witness |
| `recycled_suspect`   | near-identical to media seen more than 48 h earlier (T3) | 0.3 |
| `old_capture`        | photo taken more than 48 h before the observation (T3)   | 0.4 |
| `future_capture`     | photo taken more than 1 h after the report (T3)          | 0.7 |
| `location_mismatch`  | photo's GPS more than 25 km from the report's (T3)       | 0.5 |
| `no_metadata`        | no EXIF (T3)                                             | — noted only |
| `edited`             | EXIF names an editing app (T3)                           | — noted only |

Multipliers compound, with a floor of 0.05, on top of the source-and-length
credibility of `services/credibility.py`, which stays the starting value.

**One exception to the plan's `promotional` rule:** a phone number in a report
that asks for rescue ("trapped on the roof, call 98…") is how a person in
trouble is reached, not an advert, so a phone number alone does not flag a
report whose text carries a life-safety keyword. Sales words and 2+ URLs still
do.

Everything here is text-only and deterministic; `coordinated` is the one flag
that needs other reports, and `pipeline.py` sets it.
"""

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# flag → credibility multiplier (None: no effect on credibility). Dict order is
# the order flags are listed in, everywhere.
FLAGS: Dict[str, Optional[float]] = {
    "promotional": 0.3,
    "not_an_observation": None,
    "past_event": 0.4,
    "implausible_value": 0.3,
    "exaggeration": 0.7,
    "shouting": 0.9,
    "forward_marker": 0.6,
    "coordinated": 0.5,
    # Phase 5 T7: account signals for social sources.
    "new_account": 0.6,
    "few_followers": 0.8,
    "bot_account": 0.8,
    # Phase 5 T3: photos and videos. Set by the media worker after the report
    # is stored, each at most once per report.
    "duplicate_media": None,
    "recycled_suspect": 0.3,
    "old_capture": 0.4,
    "future_capture": 0.7,
    "location_mismatch": 0.5,
    "no_metadata": None,
    "edited": None,
}
CREDIBILITY_FLOOR = 0.05

# The flags no text rule sets: the pipeline, the social poller or the media
# worker adds them, knowing something the text alone cannot show.
TEXT_FLAGS = (
    "promotional", "not_an_observation", "past_event", "implausible_value",
    "exaggeration", "shouting", "forward_marker",
)

SHOUTING_MIN_LETTERS = 20
SHOUTING_CAPITALS_SHARE = 0.6

_SALES_RE = re.compile(
    r"\b(?:buy|discounts?|offers?|call\s+now|whatsapp\s+(?:me|us|now|karo|karein)|order\s+now|shop\s+now"
    r"|best\s+price|limited\s+stock|dm\s+(?:me|us)|free\s+delivery)\b",
    re.IGNORECASE,
)
_EXAGGERATION_RE = re.compile(
    r"never\s+seen\s+(?:before|anything\s+like|such)|biggest\s+ever|worst\s+ever|end\s+of\s+the\s+world"
    r"|(?:whole|entire)\s+(?:city|town|state)\s+(?:is\s+|has\s+)?(?:under\s?water|submerged|drowned|washed\s+away)"
    r"|apocalyp(?:se|tic)|\b100\s+(?:feet|ft)\b|hundred\s+feet|qayamat|प्रलय|क़यामत|कयामत",
    re.IGNORECASE,
)
_FORWARD_RE = re.compile(
    r"forwarded\s+as\s+received|forward\s+(?:this\s+)?to\s+all|share\s+(?:maximum|max|as\s+much\s+as\s+possible)"
    r"|(?:please|pls|plz|kindly)\s+share|\bviral\b|must\s+watch|forward\s+karo|share\s+karo"
    r"|ज़?ज्यादा\s+से\s+ज़?ज्यादा\s+शेयर|जरूर\s+शेयर|ज़रूर\s+शेयर|आगे\s+भेजें|फॉरवर्ड\s+करें",
    re.IGNORECASE,
)
_BANGS_RE = re.compile(r"!{3,}")

# The life-safety keywords of text_processing.extract_metadata that mean "come
# and get me": a phone number next to them is a way to be rescued.
_RESCUE_KEYWORDS = {"trapped", "rescue", "drown", "missing", "boat"}


def _shouting(text: str) -> Optional[str]:
    letters = [c for c in text if c.isascii() and c.isalpha()]
    if len(letters) >= SHOUTING_MIN_LETTERS:
        share = sum(1 for c in letters if c.isupper()) / len(letters)
        if share > SHOUTING_CAPITALS_SHARE:
            return f"capitals {share:.0%} of {len(letters)} letters"
    if _BANGS_RE.search(text):
        return "three or more exclamation marks"
    return None


def text_flags(text: Optional[str], meta: Mapping[str, Any]) -> Tuple[List[str], Dict[str, str]]:
    """
    The text-only flags for one report, in FLAGS order, and why each was set.
    `meta` is extract_metadata's output for the same text.
    """
    raw = text or ""
    basis: Dict[str, str] = {}

    phone = int(meta.get("phone_count") or 0)
    urls = int(meta.get("url_count") or 0)
    sales = _SALES_RE.search(raw)
    rescue = bool(set(meta.get("keywords") or []) & _RESCUE_KEYWORDS)
    if sales:
        basis["promotional"] = f"sales words: {sales.group(0)!r}"
    elif urls >= 2:
        basis["promotional"] = f"{urls} links"
    elif phone and not rescue:
        basis["promotional"] = "a phone number"

    tense = meta.get("tense")
    if tense == "forecast":
        basis["not_an_observation"] = "a forecast or warning"
    elif tense == "past":
        basis["past_event"] = "an old story (past tense, an earlier year or #throwback)"

    implausible = list(meta.get("implausible") or [])
    if implausible:
        basis["implausible_value"] = "outside a plausible range: " + ", ".join(implausible)

    exaggeration = _EXAGGERATION_RE.search(raw)
    if exaggeration:
        basis["exaggeration"] = repr(exaggeration.group(0))

    shouting = _shouting(raw)
    if shouting:
        basis["shouting"] = shouting

    forward = _FORWARD_RE.search(raw)
    if forward:
        basis["forward_marker"] = repr(forward.group(0))

    flags = [f for f in FLAGS if f in basis]
    return flags, {f: basis[f] for f in flags}


def credibility_multiplier(flags: Iterable[str]) -> float:
    """The product of the flags' multipliers; 1.0 for a clean report."""
    product = 1.0
    for flag in set(flags):
        factor = FLAGS.get(flag)
        if factor is not None:
            product *= factor
    return product


def adjust_credibility(base: float, flags: Iterable[str]) -> float:
    """
    The starting credibility × the flags' multipliers, floored at 0.05 when a
    flag lowered it. A clean report keeps its starting value exactly.
    """
    factor = credibility_multiplier(flags)
    if factor == 1.0:
        return round(base, 4)
    return round(max(CREDIBILITY_FLOOR, base * factor), 4)
