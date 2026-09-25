"""
BUG-013 — what dedup is for, measured on 22 Sep.

The register said the 0.88 cosine threshold "misses paraphrases" and should be
lowered to catch them. That expectation was wrong for this system. A report
marked duplicate is suppressed entirely: it is never clustered and never
counted as corroboration. Two citizens describing the same flood in their own
words are two witnesses, which is exactly the evidence Report Density scores.
Catching paraphrases would throw witnesses away.

What dedup should catch is the same message sent again — a resubmission,
punctuation or case changed, an "URGENT:" prefix, a forward. The numbers below
are historical measurements with the retired MiniLM model:

    independent witnesses   0.8229  0.8359  0.9093  0.8633  0.8084
    resubmissions           0.9287  0.9891  0.9881  0.9115  0.9330

At 0.88 every historical resubmission was caught and four witness pairs of five
were kept. The current frozen local matcher has its own threshold; a narrow
literal-repost rule preserves the identical URGENT/Fwd cases without retuning it.
The fifth historical pair —
"Kankarbagh underpass completely submerged, cars stuck" against "Cars are stuck
in the flooded Kankarbagh underpass", 0.9093 — was suppressed then, and that
is the real limit: wording cannot tell "the same person again" from "a second
person describing the same thing". That needs a reporter identity, which the
anonymous citizen channel does not collect. It is recorded, not asserted.

These tests pin both sides against the current local backend path.
"""

import pytest

from tests.conftest import PATNA_LAT, PATNA_LNG, T0

INDEPENDENT_WITNESSES = [
    ("Water entering ground floor shops near Kankarbagh main road",
     "Shops on Kankarbagh main road are flooding, water is inside"),                      # 0.8229
    ("Knee deep water outside my house, drain overflowing",
     "The drain overflowed and the street outside my home is knee-deep"),                  # 0.8359
    ("Flooding on the road to Patna junction, buses diverted",
     "Buses are being diverted because the Patna junction road is under water"),           # 0.8633
    ("Heavy waterlogging near Gandhi Maidan, cannot walk",
     "Gandhi Maidan area is waterlogged, roads impassable on foot"),                       # 0.8084
]

RESUBMISSIONS = [
    ("Water entering ground floor shops near Kankarbagh main road",
     "Water entering ground floor shops near Kankarbagh main road!!"),                     # 0.9287
    ("Knee deep water outside my house, drain overflowing",
     "knee deep water outside my house drain overflowing"),                                # 0.9891
    ("Kankarbagh underpass completely submerged, cars stuck",
     "URGENT: Kankarbagh underpass completely submerged, cars stuck"),                     # 0.9881
    ("Flooding on the road to Patna junction, buses diverted",
     "Fwd: Flooding on the road to Patna junction, buses diverted. Please share"),         # 0.9115
    ("Heavy waterlogging near Gandhi Maidan, cannot walk",
     "Heavy water logging near Gandhi maidan, can not walk"),                              # 0.9330
]


def _is_duplicate(dedup, first: str, second: str) -> bool:
    """`second` arrives 2 minutes after `first`, 100 m away: only the text gate decides."""
    from datetime import timedelta

    return dedup.is_duplicate(
        second,
        PATNA_LAT,
        PATNA_LNG,
        T0 + timedelta(minutes=2),
        [(first, PATNA_LAT + 0.0009, PATNA_LNG, T0)],
    )


@pytest.mark.parametrize("first, second", INDEPENDENT_WITNESSES)
def test_a_second_witness_in_their_own_words_is_kept_as_corroboration(dedup, first, second):
    assert _is_duplicate(dedup, first, second) is False


@pytest.mark.parametrize("first, second", RESUBMISSIONS)
def test_the_same_message_sent_again_is_suppressed(dedup, first, second):
    assert _is_duplicate(dedup, first, second) is True
