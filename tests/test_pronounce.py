"""Pronunciation cache and TTS validation. The speech service is never called."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import lexicon, pronounce, tts  # noqa: E402

FAKE_MP3 = b"ID3fake-mp3-bytes"


@pytest.fixture
def cache(tmp_path: Path, monkeypatch):
    """Point the cache at a temp dir and replace synthesis with a counter."""
    monkeypatch.setattr(pronounce, "CACHE_DIR", tmp_path / "pronounce")
    calls: list[tuple[str, str]] = []

    async def fake_synthesize(text, *, voice=None, speed="normal"):
        calls.append((text, speed))
        return FAKE_MP3 + speed.encode()

    monkeypatch.setattr(pronounce, "synthesize", fake_synthesize)
    return calls


def run(coro):
    return asyncio.run(coro)


# --- tts validation ---------------------------------------------------------


def test_synthesize_rejects_empty_text():
    with pytest.raises(ValueError, match="empty"):
        run(tts.synthesize("   "))


def test_synthesize_rejects_unknown_speed():
    with pytest.raises(ValueError, match="speed"):
        run(tts.synthesize("அம்மா", speed="fast"))


def test_speeds_are_normal_and_slow():
    assert set(tts.SPEEDS) == {"normal", "slow"}


def test_unknown_voice_falls_back_to_pallavi(monkeypatch):
    import dataclasses

    monkeypatch.setattr(
        tts, "settings", dataclasses.replace(tts.settings, tts_voice="en-US-Nope")
    )
    assert tts.default_voice() == "ta-IN-PallaviNeural"


def test_known_male_voice_is_honoured(monkeypatch):
    import dataclasses

    monkeypatch.setattr(
        tts, "settings", dataclasses.replace(tts.settings, tts_voice="ta-IN-ValluvarNeural")
    )
    assert tts.default_voice() == "ta-IN-ValluvarNeural"


def test_service_failure_becomes_tts_unavailable(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise ConnectionError("offline")
            yield  # pragma: no cover - makes this an async generator

    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", Boom)
    with pytest.raises(tts.TTSUnavailable, match="internet"):
        run(tts.synthesize("அம்மா"))


# --- cache ------------------------------------------------------------------


def test_first_request_synthesises_and_writes_the_file(cache):
    entry = lexicon.get("w_amma")
    path = run(pronounce.get_audio(entry, "normal"))

    assert path.is_file()
    assert path.read_bytes() == FAKE_MP3 + b"normal"
    assert path.name == "w_amma.normal.mp3"
    assert cache == [("அம்மா", "normal")]


def test_second_request_is_served_from_disk(cache):
    entry = lexicon.get("w_amma")
    first = run(pronounce.get_audio(entry, "normal"))
    second = run(pronounce.get_audio(entry, "normal"))

    assert first == second
    assert len(cache) == 1  # synthesised once, not twice


def test_speeds_are_cached_separately(cache):
    entry = lexicon.get("v_a")
    normal = run(pronounce.get_audio(entry, "normal"))
    slow = run(pronounce.get_audio(entry, "slow"))

    assert normal != slow
    assert slow.read_bytes().endswith(b"slow")
    assert len(cache) == 2


def test_unknown_speed_is_rejected(cache):
    with pytest.raises(ValueError):
        run(pronounce.get_audio(lexicon.get("v_a"), "fast"))


def test_empty_cached_file_is_regenerated(cache):
    """A crash mid-write must not leave a 0-byte file that gets served."""
    entry = lexicon.get("v_aa")
    path = pronounce.cache_path(entry.id, "normal")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")

    run(pronounce.get_audio(entry, "normal"))
    assert path.read_bytes() == FAKE_MP3 + b"normal"


def test_cache_status_counts_every_entry_and_speed(cache):
    status = pronounce.cache_status()
    assert status["total"] == len(lexicon.ALL_ENTRIES) * 2
    assert status["ready"] == 0

    run(pronounce.get_audio(lexicon.get("v_a"), "normal"))
    assert pronounce.cache_status()["ready"] == 1


def test_warm_cache_renders_everything(cache):
    status = run(pronounce.warm_cache())
    assert status["ready"] == status["total"] == 104
    assert status["failed"] == []
    assert len(cache) == 104


def test_warm_cache_skips_what_is_already_there(cache):
    run(pronounce.get_audio(lexicon.get("w_amma"), "normal"))
    run(pronounce.warm_cache())
    assert len(cache) == 104  # 1 up front + 103 during warm-up, none repeated


def test_warm_cache_survives_a_failing_entry(cache, monkeypatch):
    async def flaky(text, *, voice=None, speed="normal"):
        if text == "பூனை":
            raise tts.TTSUnavailable("service hiccup")
        return FAKE_MP3

    monkeypatch.setattr(pronounce, "synthesize", flaky)
    status = run(pronounce.warm_cache())

    assert status["ready"] == 102
    assert sorted(status["failed"]) == ["w_poonai/normal", "w_poonai/slow"]
