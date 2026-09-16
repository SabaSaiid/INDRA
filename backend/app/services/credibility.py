"""
INDRA Platform — Per-report credibility score

Replaces the `credibility_score = 0.5` that api/reports.py used to write for
every report. The score is a prior on one report, stored with it at ingest; the
event-level Source Reliability factor is computed separately over the whole
cluster in fusion_engine.source_reliability_score().

    credibility = SOURCE_RELIABILITY[source] × text_quality

* **Instrument and official sources** (OFFICIAL_DISPATCH, CWC_GAUGE,
  AWS_SENSOR) get text_quality = 1.0. Their text is machine- or template-
  generated, so a terse message says nothing about how trustworthy it is.
* **Human sources** (CITIZEN_APP, TWITTER_IMD) get
  text_quality = 0.5 + 0.5 × min(1, len(text) / 60). A bare "flood" carries no
  location, depth or detail to check against anything, so it keeps only half
  the source's prior; a specific ~60-character description earns the whole of
  it. Length is a crude proxy for specificity — deliberately simple, and
  deterministic, until an NLP model exists.

Result is always within [0.0, 1.0], so `ck_credibility_range` cannot fire.
"""

import logging
from typing import Any

from app.models.enums import SourceType
from app.services.fusion_engine import SOURCE_RELIABILITY

logger = logging.getLogger("indra.services.credibility")

# Text length at which a human report earns its source's full prior.
FULL_CREDIT_TEXT_LENGTH = 60

# Floor on text quality: even a one-word report is still a first-hand signal.
MIN_TEXT_QUALITY = 0.5

HUMAN_SOURCES = {SourceType.CITIZEN_APP, SourceType.TWITTER_IMD}

# Used when a source type is not recognised — the lowest prior in the table,
# so an unknown source can never outrank a known one.
UNKNOWN_SOURCE_RELIABILITY = min(SOURCE_RELIABILITY.values())


def compute_credibility(source_type: Any, text: str) -> float:
    """Credibility of one report in [0.0, 1.0]. See the module docstring."""
    try:
        source = SourceType(source_type)
        prior = SOURCE_RELIABILITY[source]
    except (ValueError, KeyError):
        logger.warning(f"Unknown source_type {source_type!r}; using lowest reliability prior")
        source = None
        prior = UNKNOWN_SOURCE_RELIABILITY

    if source is not None and source not in HUMAN_SOURCES:
        quality = 1.0
    else:
        length = len((text or "").strip())
        quality = MIN_TEXT_QUALITY + (1.0 - MIN_TEXT_QUALITY) * min(
            1.0, length / FULL_CREDIT_TEXT_LENGTH
        )

    return round(max(0.0, min(1.0, prior * quality)), 4)
