"""Deep-training decomposition."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import decompose, lexicon  # noqa: E402
from src.translit import VIRAMA, is_tamil  # noqa: E402


# --- syllables --------------------------------------------------------------


@pytest.mark.parametrize(
    "word, expected",
    [
        ("அம்மா", ["அம்", "மா"]),
        ("வீடு", ["வீ", "டு"]),
        ("தங்கை", ["தங்", "கை"]),
        ("பாட்டி", ["பாட்", "டி"]),
        ("மரம்", ["ம", "ரம்"]),
        ("பூ", ["பூ"]),
        ("கண்", ["கண்"]),
        ("அ", ["அ"]),
        ("பள்ளிக்கு", ["பள்", "ளிக்", "கு"]),
    ],
)
def test_syllables(word, expected):
    assert decompose.syllables(word) == expected


def test_a_virama_consonant_never_stands_alone():
    """ம் has no vowel and cannot be pronounced; it must close a syllable."""
    for entry in lexicon.ALL_ENTRIES:
        for word in entry.tamil.split():
            for syllable in decompose.syllables(word):
                assert not syllable.startswith(VIRAMA)
                assert syllable != VIRAMA


def test_syllables_reassemble_the_word():
    for entry in lexicon.ALL_ENTRIES:
        for word in entry.tamil.split():
            assert "".join(decompose.syllables(word)) == word, word


# --- step sequences ----------------------------------------------------------


def texts(entry_id):
    return [(s.text, s.kind) for s in decompose.steps_for(lexicon.get(entry_id))]


def test_word_sequence_builds_up_to_the_word():
    assert texts("w_amma") == [
        ("அம்", "piece"), ("மா", "piece"),
        ("அம்மா", "slow"), ("அம்மா", "full"),
    ]


def test_no_lone_vowel_step():
    """The word is divided into its own pieces only; no standalone first vowel."""
    for entry in lexicon.ALL_ENTRIES:
        assert all(s.kind != "sound" for s in decompose.steps_for(entry)), entry.id


def test_one_piece_word_goes_straight_to_slow_then_normal():
    assert texts("w_poo") == [("பூ", "slow"), ("பூ", "full")]


def test_bare_vowel_is_just_slow_then_normal():
    assert texts("v_aa") == [("ஆ", "slow"), ("ஆ", "full")]


def test_sentence_sequence_uses_words_and_a_buildup():
    assert texts("l_school") == [
        ("நான்", "word"), ("இன்று", "word"), ("பள்ளிக்கு", "word"), ("போகிறேன்", "word"),
        ("நான் இன்று", "buildup"), ("நான் இன்று பள்ளிக்கு", "buildup"),
        ("நான் இன்று பள்ளிக்கு போகிறேன்", "slow"),
        ("நான் இன்று பள்ளிக்கு போகிறேன்", "full"),
    ]


def test_two_word_sentence_has_no_buildup():
    kinds = [k for _, k in texts("s_amma_vaa")]
    assert "buildup" not in kinds
    assert kinds == ["word", "word", "slow", "full"]


def test_every_entry_ends_with_the_whole_text_at_normal_speed():
    for entry in lexicon.ALL_ENTRIES:
        steps = decompose.steps_for(entry)
        assert steps[-1].kind == "full" and steps[-1].text == entry.tamil.strip(), entry.id
        assert steps[-1].speed == "normal"
        assert steps[-2].kind == "slow" and steps[-2].speed == "slow"


def test_only_whole_text_steps_are_strict():
    for entry in lexicon.ALL_ENTRIES:
        for s in decompose.steps_for(entry):
            assert s.strict == (s.kind in ("slow", "full")), (entry.id, s.kind)


def test_every_step_is_pronounceable_tamil_with_a_romanisation():
    for entry in lexicon.ALL_ENTRIES:
        for s in decompose.steps_for(entry):
            assert is_tamil(s.text), (entry.id, s.text)
            assert s.roman, (entry.id, s.text)
            assert not s.text.startswith(VIRAMA)


def test_indices_are_sequential():
    for entry in lexicon.ALL_ENTRIES:
        assert [s.index for s in decompose.steps_for(entry)] == list(range(len(decompose.steps_for(entry))))


def test_payload_shape():
    p = decompose.as_payload(lexicon.get("w_veedu"))
    assert p["entry"]["id"] == "w_veedu"
    assert p["count"] == len(p["steps"]) == 4
    assert set(p["steps"][0]) == {"index", "text", "roman", "kind", "label", "speed", "strict"}
