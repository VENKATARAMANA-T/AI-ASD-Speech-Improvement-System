"""Audio decoding and preparation.

Everything downstream assumes mono float32 at 16 kHz, shaped ``[1, num_samples]``.
This module is the only place that knows about file formats.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, NamedTuple

import numpy as np
import torch

from .config import settings

log = logging.getLogger(__name__)

TARGET_SR = settings.sample_rate

# Below this peak amplitude there is nothing to transcribe. Loaded audio is
# peak-normalised to 0.95 unless it is essentially digital silence, so anything
# still this quiet afterwards carries no signal. Worth checking: the model
# hallucinates words ("அம்") when handed pure silence.
SILENCE_FLOOR = 1e-4


class AudioError(ValueError):
    """Raised when audio cannot be decoded or violates a limit."""


class Chunk(NamedTuple):
    """A slice of audio to be decoded independently."""

    waveform: torch.Tensor  # [1, N]
    start_sec: float
    end_sec: float


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------


def _decode_with_soundfile(data: bytes) -> tuple[np.ndarray, int]:
    import soundfile as sf

    with sf.SoundFile(io.BytesIO(data)) as f:
        return f.read(dtype="float32", always_2d=True), f.samplerate


def _decode_with_librosa(data: bytes) -> tuple[np.ndarray, int]:
    import librosa

    # librosa handles a wider set of containers via audioread/ffmpeg.
    samples, sr = librosa.load(io.BytesIO(data), sr=None, mono=False)
    if samples.ndim == 1:
        samples = samples[:, None]
    else:
        samples = samples.T
    return samples.astype(np.float32), sr


def _as_frames(resampled) -> list:
    """PyAV returns a list of frames on v9+, a single frame or None before that."""
    if resampled is None:
        return []
    return list(resampled) if isinstance(resampled, (list, tuple)) else [resampled]


def _decode_with_pyav(data: bytes) -> tuple[np.ndarray, int]:
    """Decode containers libsndfile cannot open: m4a/AAC, webm/opus, wma, amr.

    PyAV bundles the ffmpeg libraries in its wheel, so this needs no ffmpeg on
    PATH. It downmixes and resamples in one pass.
    """
    import av
    from av.audio.resampler import AudioResampler

    resampler = AudioResampler(format="flt", layout="mono", rate=TARGET_SR)
    blocks: list[np.ndarray] = []

    with av.open(io.BytesIO(data)) as container:
        if not container.streams.audio:
            raise AudioError("This file contains no audio stream.")
        stream = container.streams.audio[0]
        stream.thread_type = "AUTO"
        for frame in container.decode(stream):
            for out in _as_frames(resampler.resample(frame)):
                blocks.append(out.to_ndarray().reshape(-1))
        for out in _as_frames(resampler.resample(None)):  # flush the resampler
            blocks.append(out.to_ndarray().reshape(-1))

    if not blocks:
        raise AudioError("Decoded audio is empty.")
    return np.concatenate(blocks).astype(np.float32)[:, None], TARGET_SR


def _decode_with_ffmpeg(data: bytes) -> tuple[np.ndarray, int]:
    """Last resort for containers python libs cannot open (e.g. webm/opus)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioError(
            "Could not decode this file as audio. Supported formats include "
            "WAV, MP3, M4A, FLAC, OGG, Opus and WebM."
        )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input"
        src.write_bytes(data)
        proc = subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", str(src), "-f", "f32le", "-ac", "1", "-ar", str(TARGET_SR), "-"],
            capture_output=True,
        )
    if proc.returncode != 0:
        raise AudioError(
            f"ffmpeg failed to decode the audio: {proc.stderr.decode(errors='replace')[:400]}"
        )
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if samples.size == 0:
        raise AudioError("Decoded audio is empty.")
    return samples[:, None].copy(), TARGET_SR


def _decode(data: bytes) -> tuple[np.ndarray, int]:
    """Return (samples[N, channels], sample_rate)."""
    errors: list[str] = []
    # Ordered by cost: libsndfile handles WAV/FLAC/MP3/OGG directly, PyAV covers
    # the MP4-family and other containers, and a system ffmpeg is the last resort.
    for name, decoder in (
        ("soundfile", _decode_with_soundfile),
        ("librosa", _decode_with_librosa),
        ("pyav", _decode_with_pyav),
        ("ffmpeg", _decode_with_ffmpeg),
    ):
        try:
            samples, sr = decoder(data)
            if samples.size == 0:
                raise AudioError("Decoded audio is empty.")
            return samples, sr
        except AudioError:
            raise
        except Exception as exc:  # noqa: BLE001 - fall through to next decoder
            errors.append(f"{name}: {exc}")
            log.debug("decoder %s failed: %s", name, exc)
    raise AudioError("Unsupported or corrupt audio file. Tried " + "; ".join(errors))


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def load_audio(source: bytes | str | Path) -> torch.Tensor:
    """Decode any supported input into a mono 16 kHz tensor of shape ``[1, N]``.

    Accepts raw bytes (an upload) or a filesystem path.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise AudioError(f"No such audio file: {path}")
        data = path.read_bytes()
    else:
        data = source

    if not data:
        raise AudioError("Received an empty file.")
    if len(data) > settings.max_upload_bytes:
        raise AudioError(
            f"File is larger than the {settings.max_upload_mb:.0f} MB limit."
        )

    samples, sr = _decode(data)

    # Downmix to mono.
    mono = samples.mean(axis=1) if samples.shape[1] > 1 else samples[:, 0]
    waveform = torch.from_numpy(np.ascontiguousarray(mono, dtype=np.float32)).unsqueeze(0)

    if sr != TARGET_SR:
        import torchaudio

        waveform = torchaudio.transforms.Resample(sr, TARGET_SR)(waveform)

    duration = waveform.shape[1] / TARGET_SR
    if duration > settings.max_duration_sec:
        raise AudioError(
            f"Audio is {duration / 60:.1f} min, longer than the "
            f"{settings.max_duration_sec / 60:.0f} min limit."
        )
    if waveform.shape[1] < TARGET_SR * 0.1:
        raise AudioError("Audio is too short to transcribe (under 0.1 s).")

    return _normalize(waveform)


def _normalize(waveform: torch.Tensor) -> torch.Tensor:
    """Peak-normalise, guarding against silent input."""
    peak = waveform.abs().max()
    if peak > 1e-5:
        waveform = waveform / peak * 0.95
    return waveform


def duration_of(waveform: torch.Tensor) -> float:
    return waveform.shape[1] / TARGET_SR


def is_silent(waveform: torch.Tensor) -> bool:
    """True when the clip holds no usable signal."""
    return float(waveform.abs().max()) < SILENCE_FLOOR


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------


def _speech_spans(waveform: torch.Tensor) -> list[tuple[int, int]]:
    """Sample spans containing speech, found by splitting on silence."""
    try:
        import librosa

        spans = librosa.effects.split(
            waveform.squeeze(0).numpy(), top_db=settings.silence_top_db
        )
        return [(int(a), int(b)) for a, b in spans if b > a]
    except Exception as exc:  # noqa: BLE001 - degrade to a single span
        log.debug("silence detection unavailable (%s); using whole signal", exc)
        return [(0, waveform.shape[1])]


def iter_chunks(waveform: torch.Tensor) -> Iterator[Chunk]:
    """Yield decodable chunks, cutting on silence where possible.

    Short audio is yielded whole. Longer audio is split at silences and the
    resulting spans are packed greedily up to ``chunk_sec``; any single span
    longer than that is hard-split with an overlap so words are not lost at
    the seam.
    """
    total = waveform.shape[1]
    max_len = int(settings.chunk_sec * TARGET_SR)
    overlap = int(settings.chunk_overlap_sec * TARGET_SR)

    if total <= max_len:
        yield Chunk(waveform, 0.0, total / TARGET_SR)
        return

    packed_start: int | None = None
    packed_end = 0

    def emit(start: int, end: int) -> Chunk:
        return Chunk(waveform[:, start:end], start / TARGET_SR, end / TARGET_SR)

    for span_start, span_end in _speech_spans(waveform):
        # A span too long to ever fit: flush what we have, then hard-split it.
        if span_end - span_start > max_len:
            if packed_start is not None:
                yield emit(packed_start, packed_end)
                packed_start = None
            step = max_len - overlap
            for cut in range(span_start, span_end, step):
                end = min(cut + max_len, span_end)
                yield emit(cut, end)
                if end >= span_end:
                    break
            continue

        if packed_start is None:
            packed_start, packed_end = span_start, span_end
        elif span_end - packed_start <= max_len:
            packed_end = span_end  # keep the silence between spans, it aids decoding
        else:
            yield emit(packed_start, packed_end)
            packed_start, packed_end = span_start, span_end

    if packed_start is not None:
        yield emit(packed_start, packed_end)
