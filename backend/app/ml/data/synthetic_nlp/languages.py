"""Language-aware rendering helpers for English, Hindi, and Hinglish."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Final

from app.ml.data.synthetic_nlp.scenarios import Language

LANGUAGE_RENDERER_VERSION: Final[str] = "synthetic-nlp-language-renderer-v1"

_MONTHS: Final[dict[Language, tuple[str, ...]]] = {
    "English": (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ),
    "Hindi": (
        "जनवरी",
        "फ़रवरी",
        "मार्च",
        "अप्रैल",
        "मई",
        "जून",
        "जुलाई",
        "अगस्त",
        "सितंबर",
        "अक्टूबर",
        "नवंबर",
        "दिसंबर",
    ),
    "Hinglish": (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ),
}

_STYLE_TEXT: Final[dict[Language, dict[str, tuple[str, str]]]] = {
    "English": {
        "CITIZEN_APP": ("Citizen report", "Shared through the local reporting app"),
        "SMS": ("SMS update", "Sent as a short mobile update"),
        "HELPLINE_TRANSCRIPT": (
            "Helpline caller says",
            "The caller requested verification",
        ),
        "CONTROL_ROOM_NOTE": ("Control-room note", "Logged for local review"),
        "COMMUNITY_POST": ("Community post", "Residents are exchanging updates"),
        "FIELD_VOLUNTEER": ("Field volunteer update", "Observed during a local round"),
    },
    "Hindi": {
        "CITIZEN_APP": ("नागरिक रिपोर्ट", "स्थानीय रिपोर्टिंग ऐप से भेजा गया"),
        "SMS": ("एसएमएस सूचना", "मोबाइल से संक्षिप्त सूचना भेजी गई"),
        "HELPLINE_TRANSCRIPT": ("हेल्पलाइन कॉलर ने बताया", "कॉलर ने सत्यापन का अनुरोध किया"),
        "CONTROL_ROOM_NOTE": ("नियंत्रण कक्ष टिप्पणी", "स्थानीय समीक्षा के लिए दर्ज"),
        "COMMUNITY_POST": ("सामुदायिक पोस्ट", "निवासी आपस में जानकारी साझा कर रहे हैं"),
        "FIELD_VOLUNTEER": ("मैदानी स्वयंसेवक की सूचना", "स्थानीय दौरे में देखा गया"),
    },
    "Hinglish": {
        "CITIZEN_APP": ("Citizen app report", "local reporting app se bheja gaya"),
        "SMS": ("SMS update", "mobile se short update bheja"),
        "HELPLINE_TRANSCRIPT": (
            "Helpline caller bol raha hai",
            "caller ne verification maanga",
        ),
        "CONTROL_ROOM_NOTE": ("Control-room note", "local review ke liye log hua"),
        "COMMUNITY_POST": ("Community post", "residents updates share kar rahe hain"),
        "FIELD_VOLUNTEER": ("Field volunteer update", "local round mein dekha gaya"),
    },
}

_HINGLISH_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "abhi",
        "aur",
        "baarish",
        "basti",
        "baje",
        "gali",
        "ghusna",
        "hai",
        "ka",
        "ke",
        "mein",
        "mohalla",
        "nadi",
        "nahi",
        "paani",
        "par",
        "ruk",
        "tez",
        "toot",
        "wala",
    }
)


def format_event_time(value: datetime, language: Language) -> str:
    month = _MONTHS[language][value.month - 1]
    if language == "Hindi":
        return f"{value.day:02d} {month} को {value.hour:02d}:{value.minute:02d} बजे"
    if language == "Hinglish":
        return f"{value.day:02d} {month}, {value.hour:02d}:{value.minute:02d} baje"
    return f"{value.day:02d} {month} at {value.hour:02d}:{value.minute:02d}"


def format_depth(depth_cm: int | None, language: Language) -> str:
    if depth_cm is None:
        return {
            "English": "water depth not yet measured",
            "Hindi": "पानी की गहराई अभी नहीं मापी गई",
            "Hinglish": "paani depth abhi measure nahi hui",
        }[language]
    return {
        "English": f"{depth_cm} cm of water",
        "Hindi": f"{depth_cm} सेमी पानी",
        "Hinglish": f"{depth_cm} cm paani",
    }[language]


def compose_message(
    body: str,
    *,
    language: Language,
    source_style: str,
    variant: int,
) -> tuple[str, str]:
    """Apply a source-style frame and return its structural variant ID."""

    prefix, suffix = _STYLE_TEXT[language][source_style]
    selected = variant % 6
    if selected == 0:
        text = f"{prefix}: {body}"
    elif selected == 1:
        text = f"{body} — {suffix}."
    elif selected == 2:
        text = f"{prefix}: {body}. {suffix}."
    elif selected == 3:
        text = f"{body}. [{prefix}; {suffix}]"
    elif selected == 4:
        text = f"{prefix} — {body}; {suffix}."
    else:
        text = f"{suffix}: {body} ({prefix})."
    return text, f"frame-{source_style.casefold().replace('_', '-')}-{selected + 1}"


def language_text_is_valid(text: str, language: Language) -> bool:
    """Apply transparent script/code-switch checks, not model-based detection."""

    letters = [character for character in text if character.isalpha()]
    if not letters:
        return False
    devanagari = sum("\u0900" <= character <= "\u097f" for character in letters)
    if language == "English":
        return devanagari == 0
    if language == "Hindi":
        return devanagari / len(letters) >= 0.35
    if devanagari:
        return False
    words = set(re.findall(r"[a-z]+", unicodedata.normalize("NFKC", text).casefold()))
    # Hinglish is intentionally Latin-script code switching. Every Hinglish
    # template carries at least one curated Hindi transliteration marker and
    # several additional English/source-style tokens.
    return bool(words & _HINGLISH_MARKERS) and len(words - _HINGLISH_MARKERS) >= 3


__all__ = [
    "LANGUAGE_RENDERER_VERSION",
    "compose_message",
    "format_depth",
    "format_event_time",
    "language_text_is_valid",
]
