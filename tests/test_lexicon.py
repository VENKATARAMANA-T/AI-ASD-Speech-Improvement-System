"""The practice lexicon."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import lexicon  # noqa: E402
from src.translit import is_tamil  # noqa: E402


def test_twelve_vowels():
    assert len(lexicon.VOWELS) == 12


def test_twenty_words():
    assert len(lexicon.WORDS) == 20


def test_ten_sentences():
    assert len(lexicon.SENTENCES) == 10


def test_sentences_are_two_or_three_words():
    """Short enough to say in one breath, long enough to recognise reliably."""
    for entry in lexicon.SENTENCES:
        words = entry.tamil.split()
        assert 2 <= len(words) <= 3, f"{entry.id}: {len(words)} words"
        assert len(entry.roman.split()) == len(words), entry.id


def test_sentences_have_english_meanings():
    for entry in lexicon.SENTENCES + lexicon.LONG_SENTENCES:
        assert entry.category == "sentence"
        assert entry.meaning and entry.meaning.isascii(), entry.id


def test_ten_long_sentences():
    assert len(lexicon.LONG_SENTENCES) == 10


def test_long_sentences_are_four_or_five_words():
    for entry in lexicon.LONG_SENTENCES:
        words = entry.tamil.split()
        assert 4 <= len(words) <= 5, f"{entry.id}: {len(words)} words"
        assert len(entry.roman.split()) == len(words), entry.id


def test_ids_are_unique():
    ids = [e.id for e in lexicon.ALL_ENTRIES]
    assert len(ids) == len(set(ids))


def test_every_entry_is_populated():
    for entry in lexicon.ALL_ENTRIES:
        assert entry.tamil and is_tamil(entry.tamil), entry.id
        assert entry.roman and entry.roman.isascii(), entry.id
        assert entry.meaning, entry.id
        assert entry.category in {"vowel", "word", "sentence"}, entry.id


def test_lookup_by_id():
    entry = lexicon.get("w_amma")
    assert entry is not None
    assert entry.tamil == "அம்மா"
    assert entry.roman == "amma"
    assert entry.meaning == "mother"


def test_lookup_of_unknown_id_returns_none():
    assert lexicon.get("nope") is None


def test_payload_is_grouped_for_the_dropdown():
    payload = lexicon.as_payload()
    assert len(payload["vowels"]) == 12
    assert len(payload["words"]) == 20
    assert len(payload["sentences"]) == 10
    assert len(payload["long_sentences"]) == 10
    assert payload["count"] == 52


def test_every_romanisation_matches_the_transliterator():
    """The invariant that keeps the two honest: the prompt spelling shown to
    the learner is exactly what the transliterator produces, so an attempt is
    scored against the same form it was asked for."""
    from src.translit import romanize

    for entry in lexicon.ALL_ENTRIES:
        assert romanize(entry.tamil) == entry.roman, (
            f"{entry.id}: lexicon says {entry.roman!r}, "
            f"transliterator says {romanize(entry.tamil)!r}"
        )


def test_vowel_romanisations_are_all_distinct():
    romans = [e.roman for e in lexicon.VOWELS]
    assert len(set(romans)) == len(romans)
