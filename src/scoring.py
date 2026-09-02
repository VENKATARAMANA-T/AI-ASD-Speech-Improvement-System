"""Compare what the learner said against what they meant to say.

Scoring runs on the Tamil script first, and on the mechanical romanisation as a
second opinion: the model sometimes picks a different-but-homophonous spelling,
which reads as a miss on script alone. The better of the two scores wins, so a
correct pronunciation is not failed on a spelling technicality.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .translit import romanize

# Punctuation the model may add; never a pronunciation mistake.
_STRIP = set(".,!?;:'\"()[]{}-–—…‘’“”")

# A match at or above this is correct; at or above CLOSE it is nearly right.
CORRECT_THRESHOLD = 0.85
CLOSE_THRESHOLD = 0.55

# Shortest target for which "the transcript contains it" is evidence at all.
# A single vowel appears inside almost any Tamil word, so containment says
# nothing about whether that vowel was the sound produced.
MIN_CONTAINMENT_LEN = 3


@dataclass
class Assessment:
    verdict: str  # "correct" | "close" | "incorrect" | "no_speech"
    score: float  # 0.0 - 1.0
    expected_tamil: str
    expected_roman: str
    heard_tamil: str
    heard_roman: str
    detail: str

    @property
    def is_correct(self) -> bool:
        return self.verdict == "correct"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "correct": self.is_correct,
            "score": round(self.score, 3),
            "score_percent": round(self.score * 100),
            "expected": {"tamil": self.expected_tamil, "roman": self.expected_roman},
            "heard": {"tamil": self.heard_tamil, "roman": self.heard_roman},
            "detail": self.detail,
        }


def normalize(text: str) -> str:
    """NFC, drop punctuation and all whitespace, lowercase."""
    text = unicodedata.normalize("NFC", text or "")
    return "".join(ch for ch in text if ch not in _STRIP and not ch.isspace()).lower()


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance, iterative with a single row of state."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, 1):
        current = [i]
        for j, ch_b in enumerate(b, 1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ch_a != ch_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


def similarity(a: str, b: str) -> float:
    """1.0 for identical strings, 0.0 for completely different ones."""
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return max(0.0, 1.0 - edit_distance(a, b) / longest)


def assess(
    expected_tamil: str,
    heard_tamil: str,
    expected_roman: str = "",
    *,
    lenient: bool = False,
) -> Assessment:
    """Judge a single attempt at a target.

    ``lenient`` is for deep-training scaffold steps — a lone vowel or a single
    syllable. The recogniser pads those with neighbouring sounds far more often
    than a learner mispronounces them, so a target found at the start of, or
    anywhere inside, the transcript counts as said, whatever its length.
    """
    expected_norm = normalize(expected_tamil)
    heard_norm = normalize(heard_tamil)
    heard_roman = romanize(heard_tamil)
    display_roman = expected_roman or romanize(expected_tamil)

    def build(verdict: str, score: float, detail: str) -> Assessment:
        return Assessment(
            verdict=verdict,
            score=score,
            expected_tamil=expected_tamil,
            expected_roman=display_roman,
            heard_tamil=heard_tamil,
            heard_roman=heard_roman,
            detail=detail,
        )

    if not heard_norm:
        return build(
            "no_speech",
            0.0,
            "No speech was recognised. Record again, a little louder and slower.",
        )

    if heard_norm == expected_norm:
        return build("correct", 1.0, "Exact match.")

    if lenient and expected_norm and (
        heard_norm.startswith(expected_norm) or expected_norm in heard_norm
    ):
        return build("correct", 0.9, "Heard it — well done.")

    # The model often pads a short utterance, so finding the target inside the
    # transcript still counts. Two guards keep that from rescuing a wrong
    # answer: a one- or two-character target (a bare vowel) occurs inside far
    # too much ordinary Tamil to mean anything, and a target buried in a much
    # longer transcript was not what the learner actually said.
    if (
        len(expected_norm) >= MIN_CONTAINMENT_LEN
        and expected_norm in heard_norm
        and len(heard_norm) <= 2 * len(expected_norm) + 2
    ):
        return build("correct", 0.95, "Recognised, with some extra sound around it.")

    script_score = similarity(expected_norm, heard_norm)
    roman_score = similarity(
        normalize(romanize(expected_tamil)), normalize(heard_roman)
    )
    score = max(script_score, roman_score)

    if score >= CORRECT_THRESHOLD:
        return build("correct", score, "Close enough to count as correct.")
    if score >= CLOSE_THRESHOLD:
        return build(
            "close",
            score,
            f"Nearly right. Expected {expected_tamil!r}, heard {heard_tamil!r}.",
        )
    return build(
        "incorrect",
        score,
        f"That sounded like {heard_tamil!r} rather than {expected_tamil!r}.",
    )


def pick(candidates: list[tuple[str, str]], heard_tamil: str) -> tuple[int | None, list[Assessment]]:
    """Which of several targets did one utterance sound most like?

    ``candidates`` are ``(tamil, roman)`` pairs. Each is assessed against the
    transcript on its own; the winner is the highest-scoring candidate that is
    at least "close". Returns its index (``None`` if nothing came near) with
    every assessment, in the order given.
    """
    assessments = [assess(tamil, heard_tamil, roman) for tamil, roman in candidates]
    best: int | None = None
    for i, a in enumerate(assessments):
        if a.verdict in ("correct", "close") and (best is None or a.score > assessments[best].score):
            best = i
    return best, assessments
