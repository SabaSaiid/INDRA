"""Deterministic controlled-noise transforms that preserve scenario labels."""

from __future__ import annotations

import random
import re
from typing import Final

from app.ml.data.synthetic_nlp.scenarios import Language, NoiseProfile

NOISE_VERSION: Final[str] = "synthetic-nlp-controlled-noise-v1"

_ABBREVIATIONS: Final[dict[Language, tuple[tuple[str, str], ...]]] = {
    "English": (
        ("approximately", "approx"),
        ("centimetres", "cm"),
        ("information", "info"),
        ("road", "rd"),
        ("residents", "locals"),
    ),
    "Hindi": (
        ("स्थानीय", "लोकल"),
        ("जानकारी", "सूचना"),
        ("सेंटीमीटर", "सेमी"),
        ("नागरिक", "स्थानीय लोग"),
        ("सड़क", "रोड"),
    ),
    "Hinglish": (
        ("approximately", "approx"),
        ("update", "upd"),
        ("message", "msg"),
        ("road", "rd"),
        ("local", "loc"),
    ),
}


def _abbreviate_once(text: str, language: Language, rng: random.Random) -> str:
    candidates = [pair for pair in _ABBREVIATIONS[language] if pair[0] in text]
    if not candidates:
        return text
    source, replacement = rng.choice(candidates)
    return text.replace(source, replacement, 1)


def _repeat_safe_character(text: str, rng: random.Random) -> str:
    matches = list(re.finditer(r"[A-Za-z]{4,}", text))
    if not matches:
        return text
    selected = rng.choice(matches)
    word = selected.group(0)
    position = min(len(word) - 1, max(1, len(word) // 2))
    noisy_word = word[:position] + word[position] * 2 + word[position:]
    return text[: selected.start()] + noisy_word + text[selected.end() :]


def _mixed_case_word(text: str, rng: random.Random) -> str:
    matches = list(re.finditer(r"[A-Za-z]{5,}", text))
    if not matches:
        return text
    selected = rng.choice(matches)
    word = selected.group(0)
    mixed = "".join(
        character.upper() if index % 2 == 0 else character.lower()
        for index, character in enumerate(word)
    )
    return text[: selected.start()] + mixed + text[selected.end() :]


def apply_noise(
    text: str,
    *,
    profile: NoiseProfile,
    language: Language,
    rng: random.Random,
) -> str:
    """Apply bounded surface noise without deleting scenario-defining content."""

    if profile == "NONE":
        return text.strip()

    result = _abbreviate_once(text.strip(), language, rng)
    if profile == "LOW":
        return result.rstrip(".")

    result = re.sub(r"\s*[:;]\s*", " - ", result, count=1)
    result = _repeat_safe_character(result, rng)
    if profile == "MEDIUM":
        return f"{result.rstrip('.')} .."

    # HIGH is reserved for the held-out test split. The transform adds multiple
    # realistic social-message effects but retains the entire core observation.
    result = _mixed_case_word(result, rng)
    result = re.sub(r"\s+", "  ", result, count=2)
    marker = {
        "English": "pls verify #localupdate",
        "Hindi": "कृपया सत्यापित करें #स्थानीयसूचना",
        "Hinglish": "pls verify karo #localupdate",
    }[language]
    return f"{result.rstrip('.')} !!! {marker}"


__all__ = ["NOISE_VERSION", "apply_noise"]
