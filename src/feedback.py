"""Spoken feedback for the child after each attempt ("Well done!", "Your
pronunciation is wrong, the correct pronunciation is…").

A small fixed catalogue in English and Tamil, rendered once with the neural
voices and cached on disk next to the pronunciations, so playback is instant
and works offline once warm. The correct word itself is played straight after
by the existing pronunciation endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from .config import PROJECT_ROOT
from .pronounce import _write_atomically
from .tts import TTSUnavailable, default_voice, synthesize

log = logging.getLogger(__name__)

CACHE_DIR = PROJECT_ROOT / "cache" / "feedback"

# Indian-English neural voice for the English phrases; Tamil uses the same
# voice as the pronunciations so the character sounds like one person.
ENGLISH_VOICE = "en-IN-NeerjaNeural"
LANGS = ("en", "ta")

PHRASES: dict[str, dict[str, str]] = {
    # three stars
    "correct": {
        "en": "Well done! You spoke correctly.",
        "ta": "நன்று! சரியாகச் சொன்னாய்!",
    },
    # two stars: the word follows, then a nudge
    "close": {
        "en": "Almost! The correct pronunciation is",
        "ta": "கிட்டத்தட்ட சரி! சரியான உச்சரிப்பு",
    },
    "tip_close": {
        "en": "Try once more!",
        "ta": "இன்னொரு முறை சொல்!",
    },
    # one star: the correction, then how to improve
    "wrong": {
        "en": "Your pronunciation is wrong. The correct pronunciation is",
        "ta": "உச்சரிப்பு தவறு. சரியான உச்சரிப்பு",
    },
    "tip_wrong": {
        "en": "Say it slowly. You can do it!",
        "ta": "மெதுவாகச் சொல். உன்னால் முடியும்!",
    },
    "no_speech": {
        "en": "I could not hear you. Try again.",
        "ta": "கேட்கவில்லை. மீண்டும் சொல்.",
    },
}

# Which phrase each scoring verdict maps to, and the tip that follows the word.
FOR_VERDICT = {"correct": "correct", "close": "close", "incorrect": "wrong", "no_speech": "no_speech"}
TIP_FOR = {"close": "tip_close", "wrong": "tip_wrong"}


def voice_for(lang: str) -> str:
    return ENGLISH_VOICE if lang == "en" else default_voice()


def cache_path(key: str, lang: str) -> Path:
    # The text is part of the name, so rewording a phrase re-renders it
    # instead of serving the old recording.
    digest = hashlib.sha1(PHRASES[key][lang].encode("utf-8")).hexdigest()[:8]
    return CACHE_DIR / voice_for(lang) / f"{key}.{digest}.mp3"


async def get_audio(key: str, lang: str = "en") -> Path:
    if key not in PHRASES:
        raise KeyError(key)
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}, got {lang!r}")
    path = cache_path(key, lang)
    for stale in path.parent.glob(f"{key}.*.mp3"):
        if stale != path:
            stale.unlink(missing_ok=True)
    if path.is_file() and path.stat().st_size > 0:
        return path
    audio = await synthesize(PHRASES[key][lang], voice=voice_for(lang))
    _write_atomically(path, audio)
    log.info("cached feedback %s/%s (%d bytes)", key, lang, len(audio))
    return path


def cache_status() -> dict:
    total = len(PHRASES) * len(LANGS)
    ready = sum(1 for k in PHRASES for lang in LANGS if cache_path(k, lang).is_file())
    return {"ready": ready, "total": total}


async def warm_cache(concurrency: int = 4) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    failed: list[str] = []

    async def one(key: str, lang: str) -> None:
        if cache_path(key, lang).is_file():
            return
        async with semaphore:
            try:
                await get_audio(key, lang)
            except (TTSUnavailable, ValueError) as exc:
                failed.append(f"{key}/{lang}")
                log.warning("feedback warm-up skipped %s/%s: %s", key, lang, exc)

    await asyncio.gather(*(one(k, lang) for k in PHRASES for lang in LANGS))
    status = cache_status()
    status["failed"] = failed
    return status
