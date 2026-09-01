"""Tamil to Latin romanisation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.translit import is_tamil, romanize  # noqa: E402


VOWEL_CASES = [
    ("அ", "a"), ("ஆ", "aa"),
    ("இ", "i"), ("ஈ", "ee"),
    ("உ", "u"), ("ஊ", "oo"),
    ("எ", "e"), ("ஏ", "ae"),
    ("ஐ", "ai"),
    ("ஒ", "o"), ("ஓ", "oa"),
    ("ஔ", "au"),
]


@pytest.mark.parametrize("tamil, expected", VOWEL_CASES)
def test_independent_vowels(tamil, expected):
    assert romanize(tamil) == expected


def test_every_vowel_romanises_distinctly():
    """Short and long pairs must stay separable — the drill depends on it."""
    romans = [r for _, r in VOWEL_CASES]
    assert len(set(romans)) == len(romans)


def test_consonant_carries_its_inherent_vowel():
    assert romanize("க") == "ka"
    assert romanize("ம") == "ma"


def test_virama_strips_the_inherent_vowel():
    assert romanize("க்") == "k"
    assert romanize("ம்") == "m"


def test_vowel_sign_replaces_the_inherent_vowel():
    assert romanize("கா") == "kaa"
    assert romanize("கி") == "ki"
    assert romanize("கூ") == "koo"


@pytest.mark.parametrize(
    "tamil, expected",
    [
        ("அம்மா", "amma"),
        ("அப்பா", "appa"),
        ("ஆயா", "aaya"),
        ("மரம்", "maram"),
        ("பூ", "poo"),
        ("கை", "kai"),
        ("வீடு", "veedu"),
        ("பாட்டி", "paatti"),
        ("தாத்தா", "thaatha"),
        ("தங்கை", "thangai"),
        ("தம்பி", "thambi"),
        ("நாய்", "naai"),
        ("மீன்", "meen"),
    ],
)
def test_whole_words(tamil, expected):
    assert romanize(tamil) == expected


# --- context rules ---------------------------------------------------------


@pytest.mark.parametrize(
    "tamil, expected, why",
    [
        ("மகன்", "magan", "க voices between vowels"),
        ("பகல்", "pagal", "க voices between vowels"),
        ("வீடு", "veedu", "ட voices between vowels"),
        ("கை", "kai", "க stays hard word-initially"),
        ("அக்கா", "akka", "doubled க stays hard"),
    ],
)
def test_plosives_voice_between_vowels(tamil, expected, why):
    assert romanize(tamil) == expected, why


@pytest.mark.parametrize(
    "tamil, expected",
    [
        ("தங்கை", "thangai"),   # ங்க -> ng, not ngk
        ("தம்பி", "thambi"),    # ம்ப -> mb, not mp
        ("மஞ்சள்", "manjal"),   # ஞ்ச -> nj
        ("கண்டு", "kandu"),     # ண்ட -> nd
    ],
)
def test_nasal_clusters_merge(tamil, expected):
    assert romanize(tamil) == expected


def test_doubling_depends_on_the_length_of_the_reading():
    """Single letters double; digraphs would become unreadable, so collapse."""
    assert romanize("அக்கா") == "akka"      # k -> kk
    assert romanize("பாட்டி") == "paatti"   # t -> tt
    assert romanize("அப்பா") == "appa"      # p -> pp
    assert romanize("தாத்தா") == "thaatha"  # th stays single, not "ththa"


@pytest.mark.parametrize(
    "tamil, expected",
    [
        ("சமையல்", "samaiyal"),   # initial ச is /s/
        ("சிறிய", "siriya"),
        ("சொல்", "sol"),
        ("பச்சை", "pachai"),      # doubled ச்ச is the one /tʃ/ case
        ("மஞ்சள்", "manjal"),     # after ஞ் it is the nj cluster
    ],
)
def test_sa_is_s_except_when_doubled(tamil, expected):
    assert romanize(tamil) == expected


def test_doubled_rra_is_written_tr():
    """ற்ற is conventionally 'tr', not a doubled 'r'."""
    assert romanize("காற்றில்") == "kaatril"
    assert romanize("அவற்றின்") == "avatrin"


def test_word_final_long_aa_softens():
    assert romanize("அம்மா") == "amma"
    assert romanize("ஆயா") == "aaya"


def test_the_bare_vowel_aa_keeps_both_letters():
    """The softening rule must not eat the vowel that is the whole word."""
    assert romanize("ஆ") == "aa"


def test_word_final_ya_reads_as_a_vowel():
    assert romanize("நாய்") == "naai"
    assert romanize("வாய்") == "vaai"


def test_multiple_words_keep_their_spacing():
    assert romanize("அம்மா வீடு") == "amma veedu"


def test_zha_is_distinguished_from_la():
    assert romanize("ழ்") == "zh"
    assert romanize("ள்") == "l"
    assert romanize("ல்") == "l"


def test_non_tamil_passes_through():
    assert romanize("hello 123") == "hello 123"
    assert romanize("அ b") == "a b"


def test_empty_input():
    assert romanize("") == ""
    assert romanize(None) == ""


def test_stray_vowel_sign_is_dropped():
    """A combining sign with no consonant has no sensible romanisation."""
    assert romanize("ா") == ""


def test_is_tamil():
    assert is_tamil("அம்மா") is True
    assert is_tamil("amma") is False
    assert is_tamil("") is False
