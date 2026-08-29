"""Tests for the audio preparation layer. None of these need the ASR model."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import audio as A  # noqa: E402
from src.audio import AudioError  # noqa: E402


def tone(seconds: float, sr: int = 16_000, freq: float = 220.0, channels: int = 1):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    wave = 0.4 * np.sin(2 * np.pi * freq * t)
    if channels > 1:
        wave = np.stack([wave] * channels, axis=1)
    return wave


def to_wav_bytes(wave, sr: int = 16_000) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, wave, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def write_m4a(path: Path, wave, sr: int = 44_100, channels: int = 1) -> Path:
    """Encode AAC into an MP4 container — the format libsndfile cannot read."""
    import av

    pcm = (np.clip(wave, -1, 1) * 32767).astype(np.int16)
    layout = "stereo" if channels > 1 else "mono"
    planes = np.stack([pcm] * channels).reshape(1, -1) if channels > 1 else pcm[None, :]

    with av.open(str(path), "w", format="ipod") as container:
        stream = container.add_stream("aac", rate=sr)
        stream.layout = layout
        frame = av.AudioFrame.from_ndarray(planes, format="s16", layout=layout)
        frame.sample_rate = sr
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def test_loads_wav_to_mono_16k():
    out = A.load_audio(to_wav_bytes(tone(1.0)))
    assert out.shape[0] == 1
    assert out.dtype.is_floating_point
    assert abs(A.duration_of(out) - 1.0) < 0.02


def test_downmixes_stereo():
    out = A.load_audio(to_wav_bytes(tone(0.5, channels=2)))
    assert out.shape[0] == 1
    assert abs(A.duration_of(out) - 0.5) < 0.02


def test_resamples_to_16k():
    out = A.load_audio(to_wav_bytes(tone(1.0, sr=44_100), sr=44_100))
    assert abs(out.shape[1] - 16_000) < 400


def test_peak_normalised():
    quiet = to_wav_bytes(tone(0.5) * 0.01)
    assert A.load_audio(quiet).abs().max().item() == pytest.approx(0.95, abs=0.02)


def test_loads_from_path(tmp_path: Path):
    p = tmp_path / "clip.wav"
    p.write_bytes(to_wav_bytes(tone(0.4)))
    assert A.duration_of(A.load_audio(p)) == pytest.approx(0.4, abs=0.02)


# --- m4a / AAC ------------------------------------------------------------


def test_loads_m4a_from_path(tmp_path: Path):
    """M4A is AAC in an MP4 container; libsndfile cannot read it, PyAV can."""
    path = write_m4a(tmp_path / "clip.m4a", tone(4.0, sr=44_100), sr=44_100)
    out = A.load_audio(path)

    assert out.shape[0] == 1
    assert A.duration_of(out) == pytest.approx(4.0, abs=0.1)


def test_loads_m4a_from_bytes(tmp_path: Path):
    path = write_m4a(tmp_path / "clip.m4a", tone(2.0, sr=44_100), sr=44_100)
    out = A.load_audio(path.read_bytes())
    assert A.duration_of(out) == pytest.approx(2.0, abs=0.1)


def test_downmixes_stereo_m4a(tmp_path: Path):
    path = write_m4a(
        tmp_path / "stereo.m4a", tone(2.0, sr=44_100), sr=44_100, channels=2
    )
    out = A.load_audio(path)

    assert out.shape[0] == 1
    assert A.duration_of(out) == pytest.approx(2.0, abs=0.1)


def test_m4a_is_resampled_to_16k(tmp_path: Path):
    path = write_m4a(tmp_path / "clip.m4a", tone(3.0, sr=48_000), sr=48_000)
    out = A.load_audio(path)
    assert out.shape[1] == pytest.approx(48_000, abs=2_000)  # 3s at 16 kHz


def test_m4a_survives_the_chunker(tmp_path: Path):
    path = write_m4a(tmp_path / "long.m4a", tone(70.0, sr=44_100), sr=44_100)
    chunks = list(A.iter_chunks(A.load_audio(path)))

    assert len(chunks) > 1
    assert all(c.waveform.shape[1] > 0 for c in chunks)


def test_pyav_decoder_reports_a_container_with_no_audio_stream(monkeypatch):
    """A video-only MP4 opens fine but has nothing to transcribe."""
    import av

    class NoAudio:
        streams = type("S", (), {"audio": []})()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(av, "open", lambda *a, **k: NoAudio())
    with pytest.raises(A.AudioError, match="no audio stream"):
        A._decode_with_pyav(b"anything")


def test_undecodable_bytes_fall_through_every_decoder():
    """PyAV refusing to open must not stop the chain from reporting cleanly."""
    with pytest.raises(A.AudioError, match="Could not decode"):
        A.load_audio(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)


@pytest.mark.parametrize(
    "payload, match",
    [
        (b"", "empty"),
        (b"this is definitely not audio at all", "Could not decode"),
    ],
)
def test_rejects_bad_input(payload, match):
    with pytest.raises(AudioError, match=match):
        A.load_audio(payload)


def test_rejects_missing_file(tmp_path: Path):
    with pytest.raises(AudioError, match="No such audio file"):
        A.load_audio(tmp_path / "nope.wav")


def test_rejects_too_short():
    with pytest.raises(AudioError, match="too short"):
        A.load_audio(to_wav_bytes(tone(0.02)))


# --- chunking -------------------------------------------------------------


def test_short_audio_is_one_chunk():
    chunks = list(A.iter_chunks(A.load_audio(to_wav_bytes(tone(5.0)))))
    assert len(chunks) == 1
    assert chunks[0].start_sec == 0.0


def test_long_audio_is_split_and_covers_the_signal():
    waveform = A.load_audio(to_wav_bytes(tone(95.0)))
    chunks = list(A.iter_chunks(waveform))

    assert len(chunks) > 1
    limit = A.settings.chunk_sec + 0.5
    assert all(c.waveform.shape[1] / A.TARGET_SR <= limit for c in chunks)
    assert chunks[0].start_sec == pytest.approx(0.0, abs=0.1)
    assert chunks[-1].end_sec == pytest.approx(A.duration_of(waveform), abs=1.0)


def test_chunks_are_ordered_and_overlap_only_slightly():
    chunks = list(A.iter_chunks(A.load_audio(to_wav_bytes(tone(120.0)))))
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start_sec >= prev.start_sec
        gap = prev.end_sec - nxt.start_sec
        assert gap <= A.settings.chunk_overlap_sec + 0.1


def test_silence_is_used_as_a_split_point():
    """43s of speech-silence-speech should be cut in the silence, not mid-tone."""
    sr = 16_000
    speechlike = np.concatenate(
        [tone(20.0, freq=180), np.zeros(int(sr * 3.0), np.float32), tone(20.0, freq=300)]
    )
    chunks = list(A.iter_chunks(A.load_audio(to_wav_bytes(speechlike))))

    assert len(chunks) == 2
    assert chunks[0].end_sec == pytest.approx(20.0, abs=0.3)
    assert chunks[1].start_sec == pytest.approx(23.0, abs=0.3)
