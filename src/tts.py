"""Tamil text-to-speech through Microsoft's neural voices (edge-tts).

These are the same class of neural voices as Google's pronunciation feature,
and they render isolated vowels as sounds rather than spelling them out, which
the pronunciation drill depends on. Synthesis needs an internet connection;
:mod:`src.pronounce` caches every lexicon entry to disk so the practice tab
keeps working offline once the cache is warm.
"""

from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger(__name__)

# Indian-Tamil neural voices. Others exist (ta-LK, ta-SG, ta-MY) but the
# drill teaches the Indian standard.
VOICES: dict[str, str] = {
    "ta-IN-PallaviNeural": "female",
    "ta-IN-ValluvarNeural": "male",
}

# Playback speeds, as the rate offsets edge-tts understands. "slow" is what a
# learner uses to hear each sound separately.
SPEEDS: dict[str, str] = {
    "normal": "+0%",
    "slow": "-35%",
}

MEDIA_TYPE = "audio/mpeg"


class TTSUnavailable(RuntimeError):
    """Synthesis could not run: no network, service down, or bad input."""


def default_voice() -> str:
    voice = settings.tts_voice
    if voice not in VOICES:
        log.warning("TTS_VOICE %r is not a known Tamil voice; using Pallavi", voice)
        return "ta-IN-PallaviNeural"
    return voice


async def synthesize(text: str, *, voice: str | None = None, speed: str = "normal") -> bytes:
    """Return MP3 bytes for ``text``."""
    text = (text or "").strip()
    if not text:
        raise ValueError("text must not be empty.")
    if speed not in SPEEDS:
        raise ValueError(f"speed must be one of {sorted(SPEEDS)}, got {speed!r}")
    voice = voice or default_voice()

    try:
        import edge_tts
    except ImportError as exc:
        raise TTSUnavailable("edge-tts is not installed: pip install edge-tts") from exc

    audio = bytearray()
    try:
        communicate = edge_tts.Communicate(text, voice, rate=SPEEDS[speed])
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except Exception as exc:  # noqa: BLE001 - network and service errors alike
        raise TTSUnavailable(
            f"Could not reach the speech service ({type(exc).__name__}). "
            "Pronunciation needs an internet connection the first time each "
            "sound is generated."
        ) from exc

    if not audio:
        raise TTSUnavailable("The speech service returned no audio.")
    return bytes(audio)
