"""Pronunciation assessment."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scoring import assess, edit_distance, normalize, pick, similarity  # noqa: E402


# --- helpers ---------------------------------------------------------------


def test_normalize_strips_punctuation_and_space():
    assert normalize(" அம்மா, ") == "அம்மா"
    assert normalize("A B!") == "ab"


def test_normalize_handles_none_and_empty():
    assert normalize(None) == ""
    assert normalize("") == ""


@pytest.mark.parametrize(
    "a, b, expected",
    [("", "", 0), ("a", "a", 0), ("a", "", 1), ("", "abc", 3), ("kitten", "sitting", 3)],
)
def test_edit_distance(a, b, expected):
    assert edit_distance(a, b) == expected


def test_similarity_bounds():
    assert similarity("அம்மா", "அம்மா") == 1.0
    assert similarity("", "") == 1.0
    assert similarity("abc", "xyz") == 0.0
    assert 0.0 < similarity("அம்மா", "அப்பா") < 1.0


# --- assessment ------------------------------------------------------------


def test_exact_match_is_correct():
    result = assess("அம்மா", "அம்மா", "amma")
    assert result.verdict == "correct"
    assert result.is_correct
    assert result.score == 1.0
    assert result.expected_roman == "amma"
    assert result.heard_roman == "amma"


def test_punctuation_does_not_fail_an_attempt():
    assert assess("அம்மா", "அம்மா.", "amma").verdict == "correct"


def test_silence_is_reported_separately():
    result = assess("அம்மா", "", "amma")
    assert result.verdict == "no_speech"
    assert result.score == 0.0
    assert "louder" in result.detail


def test_whitespace_only_counts_as_silence():
    assert assess("அம்மா", "   ", "amma").verdict == "no_speech"


def test_target_embedded_in_a_longer_utterance_still_counts():
    """The model often pads a short word; that is not a mispronunciation."""
    result = assess("அம்மா", "அம்மா அம்மா", "amma")
    assert result.verdict == "correct"
    assert result.score == pytest.approx(0.95)


def test_a_bare_vowel_is_not_rescued_by_containment():
    """Regression: the model hallucinates 'அம்' on silence, and 'அ' sits
    inside it. Containment must not turn that into a pass."""
    result = assess("அ", "அம்", "a")
    assert result.verdict != "correct"
    assert not result.is_correct


def test_a_vowel_inside_an_ordinary_word_is_not_correct():
    result = assess("அ", "அம்மா", "a")
    assert result.verdict == "incorrect"


def test_containment_does_not_rescue_a_target_buried_in_a_sentence():
    """Saying the word inside a whole sentence is not the drill."""
    heard = "பல மாவட்டங்கள் அம்மா சிறிய வசதியான பலமான ஜப்பானிய"
    assert assess("அம்மா", heard, "amma").verdict == "incorrect"


def test_a_different_word_is_incorrect():
    result = assess("அம்மா", "வீடு", "amma")
    assert result.verdict == "incorrect"
    assert not result.is_correct
    assert "வீடு" in result.detail


@pytest.mark.parametrize(
    "short, long_",
    [("அ", "ஆ"), ("இ", "ஈ"), ("உ", "ஊ"), ("எ", "ஏ"), ("ஒ", "ஓ")],
)
def test_vowel_length_confusions_are_failed(short, long_):
    """Short versus long is the distinction the drill exists to teach, so it
    must not pass — even though the romanisations overlap ('a' inside 'aa')."""
    from src.scoring import CLOSE_THRESHOLD

    result = assess(short, long_)
    assert result.verdict == "incorrect"
    assert result.score < CLOSE_THRESHOLD

    swapped = assess(long_, short)
    assert swapped.verdict == "incorrect"


def test_a_near_miss_is_close_rather_than_wrong():
    result = assess("பாட்டி", "பாடி", "paatti")
    assert result.verdict in {"close", "correct"}
    assert result.score > 0.55


# --- lenient mode (deep-training scaffold steps) -----------------------------


def test_lenient_accepts_the_target_at_the_start_of_the_transcript():
    """Saying அம் and being heard as அம்மா is the recogniser padding, not an error."""
    assert assess("அம்", "அம்மா", lenient=True).verdict == "correct"


def test_lenient_accepts_a_bare_vowel_inside_a_longer_transcript():
    """Strict mode must refuse this (a vowel is inside most words); lenient may not."""
    assert assess("அ", "அம்", lenient=False).verdict != "correct"
    assert assess("அ", "அம்", lenient=True).verdict == "correct"


def test_lenient_still_fails_a_different_sound():
    assert assess("ஆ", "ஈ", lenient=True).verdict == "incorrect"
    assert assess("மா", "பா", lenient=True).verdict != "correct"


def test_lenient_still_reports_silence():
    assert assess("அ", "", lenient=True).verdict == "no_speech"


def test_payload_shape():
    payload = assess("அம்மா", "அம்மா", "amma").to_dict()
    assert payload["correct"] is True
    assert payload["score_percent"] == 100
    assert payload["expected"] == {"tamil": "அம்மா", "roman": "amma"}
    assert payload["heard"]["tamil"] == "அம்மா"
    assert set(payload) == {
        "verdict", "correct", "score", "score_percent", "expected", "heard", "detail"
    }


def test_expected_roman_defaults_to_the_transliteration():
    """Omitting the label should not leave the field blank."""
    assert assess("அம்மா", "அம்மா").expected_roman == "amma"


def test_pick_returns_the_candidate_that_was_heard():
    candidates = [("அம்மா", "amma"), ("பூ", "poo"), ("நாய்", "naai")]
    best, assessments = pick(candidates, "நாய்")
    assert best == 2
    assert assessments[2].verdict == "correct"
    assert [a.expected_tamil for a in assessments] == ["அம்மா", "பூ", "நாய்"]


def test_pick_prefers_the_closest_when_none_is_exact():
    best, assessments = pick([("அம்மா", "amma"), ("அப்பா", "appa")], "அப்பா வா")
    assert best == 1
    assert assessments[1].verdict in ("correct", "close")


def test_pick_returns_none_when_nothing_is_even_close():
    best, _ = pick([("அம்மா", "amma"), ("பூ", "poo")], "வணக்கம் நண்பா")
    assert best is None
