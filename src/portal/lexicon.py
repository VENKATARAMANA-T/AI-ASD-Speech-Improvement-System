"""The practice lexicon as the doctor side sees it: grouped by category, each
entry carrying its category key and a difficulty label.

Same process as the speech app, so this reads :mod:`src.lexicon` directly —
nothing is fetched or cached.
"""

from __future__ import annotations

from .. import lexicon as _lex
from ..translit import romanize as _romanize

CATEGORIES = {
    "vowels": {"key": "vowels", "name": "Vowels", "short": "Vowel", "level": "", "emoji": "🔤", "tamil": "உயிர் எழுத்துக்கள்"},
    "words": {"key": "words", "name": "Words", "short": "Word", "level": "easy", "emoji": "🧩", "tamil": "சொற்கள்"},
    "sentences": {"key": "sentences", "name": "Short Sentences", "short": "Short sentence", "level": "medium", "emoji": "💬", "tamil": "சிறு வாக்கியங்கள்"},
    "long_sentences": {"key": "long_sentences", "name": "Sentences", "short": "Sentence", "level": "hard", "emoji": "📖", "tamil": "எளிய வாக்கியங்கள்"},
}
CATEGORY_ORDER = ["vowels", "words", "sentences", "long_sentences"]


def get_lexicon() -> dict:
    payload = _lex.as_payload()
    out = {k: list(payload.get(k, [])) for k in CATEGORY_ORDER}
    for k in CATEGORY_ORDER:
        for e in out[k]:
            e["cat"] = k
    out["count"] = sum(len(out[k]) for k in CATEGORY_ORDER)
    return out


def by_id(payload: dict) -> dict[str, dict]:
    return {e["id"]: e for k in CATEGORY_ORDER for e in payload.get(k, [])}


def romanize(text: str) -> str:
    try:
        return _romanize(text)
    except Exception:  # noqa: BLE001 - a label, never worth failing a request
        return ""
