"""Cached pronunciations for every lexicon entry.

Synthesis takes about a second and needs the network, so each entry is
rendered once and kept on disk. The cache is warmed in the background when the
server starts; a click on an entry that is not cached yet synthesises it on
demand and stores the result.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from pathlib import Path

from . import lexicon
from .config import PROJECT_ROOT
from .lexicon import Entry
from .tts import SPEEDS, TTSUnavailable, default_voice, synthesize

log = logging.getLogger(__name__)

CACHE_DIR = PROJECT_ROOT / "cache" / "pronounce"


def cache_path(entry_id: str, speed: str, voice: str | None = None) -> Path:
    voice = voice or default_voice()
    return CACHE_DIR / voice / f"{entry_id}.{speed}.mp3"


async def get_audio(entry: Entry, speed: str = "normal") -> Path:
    """Path to the MP3 for ``entry`` at ``speed``, synthesising it if needed."""
    if speed not in SPEEDS:
        raise ValueError(f"speed must be one of {sorted(SPEEDS)}, got {speed!r}")

    path = cache_path(entry.id, speed)
    if path.is_file() and path.stat().st_size > 0:
        return path

    audio = await synthesize(entry.tamil, speed=speed)
    _write_atomically(path, audio)
    log.info("cached pronunciation %s (%s, %d bytes)", entry.id, speed, len(audio))
    return path


MAX_TEXT_CHARS = 200


def text_cache_path(text: str, speed: str, voice: str | None = None) -> Path:
    """Cache location for arbitrary text — deep-training pieces, mostly."""
    voice = voice or default_voice()
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / voice / "text" / f"{digest}.{speed}.mp3"


async def get_audio_for_text(text: str, speed: str = "normal") -> Path:
    """Like :func:`get_audio` but for any short Tamil string."""
    text = (text or "").strip()
    if not text:
        raise ValueError("text must not be empty.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text is longer than {MAX_TEXT_CHARS} characters.")
    if speed not in SPEEDS:
        raise ValueError(f"speed must be one of {sorted(SPEEDS)}, got {speed!r}")

    path = text_cache_path(text, speed)
    if path.is_file() and path.stat().st_size > 0:
        return path

    audio = await synthesize(text, speed=speed)
    _write_atomically(path, audio)
    log.info("cached pronunciation for %r (%s, %d bytes)", text, speed, len(audio))
    return path


async def warm_texts(items: list[tuple[str, str]], concurrency: int = 4) -> int:
    """Pre-render (text, speed) pairs; returns how many were rendered or found."""
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def one(text: str, speed: str) -> None:
        nonlocal done
        async with semaphore:
            try:
                await get_audio_for_text(text, speed)
                done += 1
            except (TTSUnavailable, ValueError) as exc:
                log.warning("could not pre-render %r/%s: %s", text, speed, exc)

    await asyncio.gather(*(one(t, s) for t, s in items))
    return done


def _write_atomically(path: Path, data: bytes) -> None:
    """Never leave a half-written file that a later request would serve."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cache_status() -> dict:
    """How much of the lexicon is ready to play without the network."""
    total = len(lexicon.ALL_ENTRIES) * len(SPEEDS)
    ready = sum(
        1
        for entry in lexicon.ALL_ENTRIES
        for speed in SPEEDS
        if cache_path(entry.id, speed).is_file()
    )
    return {"voice": default_voice(), "ready": ready, "total": total}


async def warm_cache(concurrency: int = 4) -> dict:
    """Synthesise every missing entry. Failures are counted, never raised."""
    semaphore = asyncio.Semaphore(concurrency)
    failed: list[str] = []

    async def one(entry: Entry, speed: str) -> None:
        if cache_path(entry.id, speed).is_file():
            return
        async with semaphore:
            try:
                await get_audio(entry, speed)
            except (TTSUnavailable, ValueError) as exc:
                failed.append(f"{entry.id}/{speed}")
                log.warning("pronunciation warm-up skipped %s/%s: %s", entry.id, speed, exc)

    await asyncio.gather(
        *(one(entry, speed) for entry in lexicon.ALL_ENTRIES for speed in SPEEDS)
    )
    status = cache_status()
    status["failed"] = failed
    return status
