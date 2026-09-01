"""Romanise Tamil script into the Latin spelling a Tamil speaker would write.

A letter-for-letter table is not enough. Tamil writes one symbol for sounds
that English spells differently depending on where they fall in a word, so the
same letter has to romanise differently by context:

* **Plosives voice between vowels.** க is ``k`` in கை (*kai*) but ``g`` in மகன்
  (*magan*); ட is ``t`` in பாட்டி (*paatti*) but ``d`` in வீடு (*veedu*).
* **Nasal clusters merge.** ங்க is ``ng`` (தங்கை → *thangai*), not ``ngk``;
  ம்ப is ``mb`` (தம்பி → *thambi*), not ``mp``.
* **Doubling behaves differently by length.** க்க doubles to ``kk`` (அக்கா →
  *akka*), but த்த would give the unreadable ``thth``, so the digraph collapses
  (தாத்தா → *thaatha*).
* **Word endings soften.** A final ஆ reduces to ``a`` (அம்மா → *amma*) and a
  final ய் reads as ``i`` (நாய் → *naai*).

Every word in :mod:`src.lexicon` romanises to exactly its conventional
spelling under these rules, which is the test that keeps them honest.
"""

from __future__ import annotations

import re
import unicodedata

# Independent vowels (உயிர் எழுத்து). Long and short forms stay distinct — the
# pronunciation drill exists to teach exactly that difference.
VOWELS: dict[str, str] = {
    "அ": "a",
    "ஆ": "aa",
    "இ": "i",
    "ஈ": "ee",
    "உ": "u",
    "ஊ": "oo",
    "எ": "e",
    "ஏ": "ae",
    "ஐ": "ai",
    "ஒ": "o",
    "ஓ": "oa",
    "ஔ": "au",
}

# Dependent vowel signs, mapped to the same sounds as their independent forms.
VOWEL_SIGNS: dict[str, str] = {
    "ா": "aa",
    "ி": "i",
    "ீ": "ee",
    "ு": "u",
    "ூ": "oo",
    "ெ": "e",
    "ே": "ae",
    "ை": "ai",
    "ொ": "o",
    "ோ": "oa",
    "ௌ": "au",
}

# Default (word-initial, doubled, post-consonant) reading of each consonant.
CONSONANTS: dict[str, str] = {
    "க": "k",
    "ங": "ng",
    "ச": "s",   # /s/ initially and between vowels; "ch" only when doubled
    "ஞ": "nj",
    "ட": "t",
    "ண": "n",
    "த": "th",
    "ந": "n",
    "ப": "p",
    "ம": "m",
    "ய": "y",
    "ர": "r",
    "ல": "l",
    "வ": "v",
    "ழ": "zh",
    "ள": "l",
    "ற": "r",
    "ன": "n",
    # Grantha letters, used for loan words.
    "ஜ": "j",
    "ஷ": "sh",
    "ஸ": "s",
    "ஹ": "h",
}

# Reading between two vowels, where Tamil plosives voice.
INTERVOCALIC: dict[str, str] = {
    "க": "g",
    "ச": "s",
    "ட": "d",
    "ப": "b",
}

# Doubled consonants that are not written by simply repeating the letter.
# ற்ற is conventionally "tr": காற்றில் -> kaatril, not "kaarril".
# ச்ச is the one place ச is /tʃ/: பச்சை -> pachai, not "passai".
GEMINATES: dict[str, str] = {"ற": "tr", "ச": "ch"}

# A nasal followed by its matching plosive is written as one cluster.
# Keyed by (nasal, plosive) -> (nasal reading, plosive reading).
NASAL_CLUSTERS: dict[tuple[str, str], tuple[str, str]] = {
    ("ங", "க"): ("n", "g"),   # தங்கை -> thangai
    ("ஞ", "ச"): ("n", "j"),   # மஞ்சள் -> manjal
    ("ண", "ட"): ("n", "d"),   # கண்டு -> kandu
    ("ந", "த"): ("n", "th"),  # சாந்தி -> saanthi
    ("ம", "ப"): ("m", "b"),   # தம்பி -> thambi
    ("ண", "ப"): ("n", "b"),   # நண்பன் -> nanban
    ("ன", "ப"): ("n", "b"),   # அன்பு -> anbu
    ("ன", "ற"): ("n", "dr"),  # என்று -> endru
}

VIRAMA = "்"  # புள்ளி — strips the consonant's inherent vowel
AYTHAM = "ஃ"
INHERENT = "a"

_WORD_SPLIT = re.compile(r"(\s+)")


def _parse(word: str) -> list[dict]:
    """Break a word into vowel, consonant, and pass-through units."""
    units: list[dict] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in CONSONANTS:
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if nxt == VIRAMA:
                units.append({"kind": "c", "ch": ch, "vowel": None})
                i += 2
            elif nxt in VOWEL_SIGNS:
                units.append({"kind": "c", "ch": ch, "vowel": VOWEL_SIGNS[nxt]})
                i += 2
            else:
                units.append({"kind": "c", "ch": ch, "vowel": INHERENT})
                i += 1
        elif ch in VOWELS:
            units.append({"kind": "v", "text": VOWELS[ch]})
            i += 1
        elif ch == AYTHAM:
            units.append({"kind": "v", "text": "h"})
            i += 1
        elif ch in VOWEL_SIGNS or ch == VIRAMA:
            i += 1  # stray sign with no consonant to attach to
        else:
            units.append({"kind": "other", "text": ch})
            i += 1
    return units


def _ends_in_vowel(unit: dict | None) -> bool:
    if unit is None:
        return False
    if unit["kind"] == "v":
        return True
    return unit["kind"] == "c" and unit["vowel"] is not None


def _romanize_word(word: str) -> str:
    units = _parse(word)
    out: list[str] = []
    i = 0
    has_consonant = any(u["kind"] == "c" for u in units)

    while i < len(units):
        unit = units[i]

        if unit["kind"] != "c":
            out.append(unit["text"])
            i += 1
            continue

        ch, vowel = unit["ch"], unit["vowel"]
        nxt = units[i + 1] if i + 1 < len(units) else None

        # A bare consonant can pair with the one after it.
        if vowel is None and nxt is not None and nxt["kind"] == "c":
            pair = (ch, nxt["ch"])
            if pair in NASAL_CLUSTERS:
                nasal, plosive = NASAL_CLUSTERS[pair]
                out.append(nasal)
                out.append(plosive)
                if nxt["vowel"]:
                    out.append(nxt["vowel"])
                i += 2
                continue
            if ch == nxt["ch"]:
                # Doubling. Single-letter readings double; digraphs would turn
                # into unreadable runs ("ththa"), so they collapse instead.
                base = CONSONANTS[ch]
                out.append(
                    GEMINATES.get(ch, base if len(base) > 1 else base * 2)
                )
                if nxt["vowel"]:
                    out.append(nxt["vowel"])
                i += 2
                continue

        # A final ய் after a vowel reads as a vowel: நாய் -> naai.
        if ch == "ய" and vowel is None and nxt is None and _ends_in_vowel(units[i - 1] if i else None):
            out.append("i")
            i += 1
            continue

        # Plosives voice between two vowels.
        prev = units[i - 1] if i else None
        reading = CONSONANTS[ch]
        if ch in INTERVOCALIC and vowel is not None and _ends_in_vowel(prev):
            reading = INTERVOCALIC[ch]

        out.append(reading)
        if vowel is not None:
            out.append(vowel)
        i += 1

    result = "".join(out)

    # A word-final long ஆ softens: அம்மா -> amma. The bare vowel ஆ on its own
    # must keep both letters, so require an actual consonant in the word.
    if has_consonant and result.endswith("aa") and len(result) > 3:
        result = result[:-1]

    return result


def romanize(text: str) -> str:
    """Convert Tamil script to Latin letters, word by word.

    Characters outside the Tamil block pass through unchanged, so mixed-script
    transcripts stay readable.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    return "".join(
        part if part.isspace() else _romanize_word(part)
        for part in _WORD_SPLIT.split(normalized)
    )


def is_tamil(text: str) -> bool:
    """True if the string contains at least one Tamil letter."""
    return any(ch in CONSONANTS or ch in VOWELS or ch == AYTHAM for ch in text or "")
