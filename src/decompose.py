"""Break a word into the pieces a learner practises one at a time.

Deep training takes a word the child keeps getting wrong and rebuilds it from
its parts: each piece of the word, then the whole word slowly, then at normal
speed. Tamil script makes the split reliable — it is an abugida, so every
consonant carries its vowel, and a consonant with a virama (புள்ளி) has no
vowel and must close the piece before it.

    அம்மா  ->  அம் · மா · அம்மா (slow) · அம்மா
    வீடு   ->  வீ · டு · வீடு (slow) · வீடு

Sentences decompose into words rather than pieces, with a build-up of the
first two, three… words before the whole thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lexicon import Entry
from .translit import AYTHAM, CONSONANTS, VIRAMA, VOWEL_SIGNS, VOWELS, romanize

# How far the whole-word steps may be trusted vs. the scaffolding before them.
# Whole-word steps are the real gate; short pieces are where the recogniser is
# least reliable, so those steps are checked leniently and may be skipped.
STRICT_KINDS = {"slow", "full"}

SLOW_SPEED = "slow"
NORMAL_SPEED = "normal"


@dataclass(frozen=True)
class Step:
    index: int
    text: str
    roman: str
    kind: str  # piece | word | buildup | slow | full
    label: str
    speed: str
    strict: bool

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "text": self.text,
            "roman": self.roman,
            "kind": self.kind,
            "label": self.label,
            "speed": self.speed,
            "strict": self.strict,
        }


# --------------------------------------------------------------------------
# grapheme units and syllables
# --------------------------------------------------------------------------


def units(word: str) -> list[tuple[str, str, str | None]]:
    """Split into (kind, raw text, vowel-roman) units, keeping the raw text.

    kind is "c" for a consonant unit (with its vowel sign or virama), "v" for
    an independent vowel, "x" for anything else. vowel-roman is None for a
    virama consonant, which has no vowel.
    """
    out: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in CONSONANTS:
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if nxt == VIRAMA:
                out.append(("c", ch + nxt, None))
                i += 2
            elif nxt in VOWEL_SIGNS:
                out.append(("c", ch + nxt, VOWEL_SIGNS[nxt]))
                i += 2
            else:
                out.append(("c", ch, "a"))
                i += 1
        elif ch in VOWELS:
            out.append(("v", ch, VOWELS[ch]))
            i += 1
        elif ch == AYTHAM:
            out.append(("v", ch, "a"))
            i += 1
        else:
            out.append(("x", ch, None))
            i += 1
    return out


def syllables(word: str) -> list[str]:
    """Orthographic syllables: each vowel-bearing unit starts one, and a bare
    (virama) consonant closes the one before it, so ம் can never stand alone."""
    result: list[str] = []
    for kind, raw, vowel in units(word):
        if kind == "x":
            continue
        if vowel is None:
            if result:
                result[-1] += raw
            else:
                result.append(raw)  # a word cannot start this way, but never lose text
        else:
            result.append(raw)
    return result


# --------------------------------------------------------------------------
# step sequences
# --------------------------------------------------------------------------


def _step(index: int, text: str, kind: str, label: str, speed: str) -> Step:
    return Step(index, text, romanize(text), kind, label, speed, kind in STRICT_KINDS)


def _word_steps(word: str) -> list[Step]:
    sylls = syllables(word)
    pieces: list[tuple[str, str, str, str]] = []  # (text, kind, label, speed)

    if len(sylls) > 1:
        for i, s in enumerate(sylls, 1):
            pieces.append((s, "piece", f"Piece {i} of {len(sylls)}", NORMAL_SPEED))

    pieces.append((word, "slow", "Slowly, all together", SLOW_SPEED))
    pieces.append((word, "full", "The whole word", NORMAL_SPEED))
    return _dedupe(pieces)


def _sentence_steps(sentence: str) -> list[Step]:
    words = sentence.split()
    pieces: list[tuple[str, str, str, str]] = []
    for i, w in enumerate(words, 1):
        pieces.append((w, "word", f"Word {i} of {len(words)}", NORMAL_SPEED))
    for n in range(2, len(words)):
        pieces.append((" ".join(words[:n]), "buildup", f"First {n} words", NORMAL_SPEED))
    pieces.append((sentence, "slow", "Slowly, all together", SLOW_SPEED))
    pieces.append((sentence, "full", "The whole sentence", NORMAL_SPEED))
    return _dedupe(pieces)


def _dedupe(pieces: list[tuple[str, str, str, str]]) -> list[Step]:
    """Drop a step whose text and speed repeat the one before it."""
    steps: list[Step] = []
    for text, kind, label, speed in pieces:
        if steps and steps[-1].text == text and steps[-1].speed == speed:
            continue
        steps.append(_step(len(steps), text, kind, label, speed))
    return steps


def steps_for(entry: Entry) -> list[Step]:
    """The deep-training sequence for a lexicon entry."""
    if entry.category == "sentence" or " " in entry.tamil.strip():
        return _sentence_steps(entry.tamil.strip())
    return _word_steps(entry.tamil.strip())


def as_payload(entry: Entry) -> dict:
    steps = steps_for(entry)
    return {
        "entry": entry.to_dict(),
        "steps": [s.to_dict() for s in steps],
        "count": len(steps),
    }
