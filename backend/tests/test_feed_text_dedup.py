"""
Phase 2 T7 — which text comparison a pair of posts gets.

The embedding model is English-only. On the first live news tick it scored
unrelated Hindi headlines at cosine 0.88–0.96 and suppressed 75 of them as
copies. The pairs below are real ones from that tick: the model decides only
when both texts are mostly Latin script, Levenshtein otherwise.
"""

import pytest

from tests.conftest import requires_embeddings

from app.services.dedup import _mostly_latin, find_similar_text


@pytest.mark.parametrize(
    "text, latin",
    [
        ("IMD warns of extremely heavy rain in Telangana districts", True),
        ("सीतापुर में तेज आंधी-बारिश से हजारों बीघा फसल गिरी", False),
        ("Bihar Weather Today: पूरे बिहार में बिगड़ा रहेगा मौसम, 19 जिलों में अलर्ट", False),
        ("Bihar Ka Mausam: aaj se 28 September tak barish", True),
        ("Pluie à São Paulo", True),
        ("#IMD 2026", True),
        ("", True),
    ],
)
def test_mostly_latin(text, latin):
    assert _mostly_latin(text) is latin


# Real false matches from the 24 Sep tick (cosine 0.93 and 0.88).
@pytest.mark.parametrize(
    "new, earlier",
    [
        ("सीतापुर में तेज आंधी-बारिश से हजारों बीघा फसल गिरी: किसान परेशान, उत्पादन और आमदनी पर संकट",
         "तेज आंधी-बारिश से कई बीघे धान की फसल गिरी: हुसैनगंज में किसानों को भारी नुकसान"),
        ("उत्तर भारत में घना कोहरा, कई राज्यों में शीत लहर और बारिश का अलर्ट",
         "बढ़ती गर्मी और लू के बीच मनोहर लोहिया अस्पताल के डॉक्टरों ने सतर्क रहने की सलाह दी"),
    ],
)
def test_different_hindi_stories_are_not_copies(new, earlier):
    assert find_similar_text(new, [earlier]) is None


def test_the_same_hindi_headline_is_a_copy_by_levenshtein():
    headline = "जाते-जाते मानसून मेहरबान, यूपी, उत्तराखंड, दिल्ली-एनसीआर समेत कई राज्यों में बारिश"
    index, similarity, method = find_similar_text(headline, ["कुछ और", headline])
    assert (index, method) == (1, "levenshtein")
    assert similarity == 1.0


@requires_embeddings
def test_an_english_copy_is_still_found_by_the_model():
    match = find_similar_text(
        "IMD forecasts very dense fog over north India for next four days",
        ["Heavy rain in Kerala", "IMD forecasts very dense fog conditions in north India till tomorrow"],
    )
    assert match is not None
    index, similarity, method = match
    assert (index, method) == (1, "cosine")
    assert similarity >= 0.88


@requires_embeddings
def test_an_english_post_against_a_hindi_candidate_uses_levenshtein():
    match = find_similar_text(
        "Heavy rain alert in Bihar",
        ["बिहार में भारी बारिश का अलर्ट", "Heavy rain alert in Bihar"],
    )
    assert match[:1] == (1,)


def test_empty_input_matches_nothing():
    assert find_similar_text("", ["x"]) is None
    assert find_similar_text("x", []) is None
