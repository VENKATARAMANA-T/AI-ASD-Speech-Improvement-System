"""Tamil speech recognition built on AI4Bharat's IndicConformer."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import torch

from . import audio as audio_utils
from .config import settings

log = logging.getLogger(__name__)

VALID_DECODINGS = ("ctc", "rnnt")

# The application always decodes this way. Measured over 25 FLEURS Tamil clips,
# RNNT beats CTC on both metrics — WER 0.164 vs 0.186, CER 0.0454 vs 0.0464 —
# for about 2.1x the compute, which still leaves it running at roughly 0.36
# real-time on CPU. Accuracy wins, so the choice is not exposed: CTC remains
# reachable only through scripts/eval_wer.py, which is how the two were
# compared in the first place.
DEFAULT_DECODING = "rnnt"


class ModelAccessError(RuntimeError):
    """The model exists but this machine is not authorised to download it."""


def _is_gated(exc: Exception) -> bool:
    text = str(exc).lower()
    return "gated repo" in text or "401 client error" in text or "restricted" in text


@dataclass
class Segment:
    start_sec: float
    end_sec: float
    text: str


@dataclass
class Transcription:
    text: str
    language: str
    decoding: str
    duration_sec: float
    elapsed_sec: float
    segments: list[Segment] = field(default_factory=list)

    @property
    def real_time_factor(self) -> float:
        """Seconds of compute per second of audio. Below 1.0 is faster than real time."""
        return self.elapsed_sec / self.duration_sec if self.duration_sec else 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "decoding": self.decoding,
            "duration_sec": round(self.duration_sec, 3),
            "elapsed_sec": round(self.elapsed_sec, 3),
            "real_time_factor": round(self.real_time_factor, 3),
            "segments": [
                {
                    "start_sec": round(s.start_sec, 3),
                    "end_sec": round(s.end_sec, 3),
                    "text": s.text,
                }
                for s in self.segments
            ],
        }


class TamilASR:
    """Wraps the IndicConformer model.

    The model is loaded once and reused. ``transcribe`` is serialised with a
    lock because the underlying model is not safe to call concurrently and CPU
    inference gains nothing from parallel calls anyway.
    """

    def __init__(
        self,
        model_id: str | None = None,
        revision: str | None = None,
        language: str | None = None,
        decoding: str | None = None,
    ) -> None:
        self.model_id = model_id or settings.asr_model_id
        self.revision = revision or settings.asr_revision
        self.language = language or settings.asr_language
        self.decoding = _validate_decoding(decoding or DEFAULT_DECODING)
        self._model = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._load_error: str | None = None

    # -- lifecycle --------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        """Download (first run) and initialise the model. Safe to call repeatedly."""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            if settings.torch_threads > 0:
                torch.set_num_threads(settings.torch_threads)

            from transformers import AutoModel

            log.info("loading %s (revision=%s)", self.model_id, self.revision)
            started = time.perf_counter()
            kwargs = {"revision": self.revision, "trust_remote_code": True}
            if settings.hf_token:
                kwargs["token"] = settings.hf_token
            try:
                model = AutoModel.from_pretrained(self.model_id, **kwargs)
            except Exception as exc:
                if _is_gated(exc):
                    message = (
                        f"{self.model_id} is a gated repository. Accept its terms at "
                        f"https://huggingface.co/{self.model_id} while signed in, then "
                        "authenticate locally with `huggingface-cli login` or by "
                        "setting the HF_TOKEN environment variable to a read token."
                    )
                    # Not logged here: callers either report it to the user
                    # (CLI, 503 response) or log it at the warm-up boundary.
                    self._load_error = message
                    raise ModelAccessError(message) from exc
                self._load_error = f"{type(exc).__name__}: {exc}"
                log.exception("model failed to load")
                raise
            if hasattr(model, "eval"):
                model.eval()
            self._model = model
            self._load_error = None
            log.info("model ready in %.1fs", time.perf_counter() - started)

    # -- inference --------------------------------------------------------

    def _decode_one(self, waveform: torch.Tensor, decoding: str) -> str:
        with self._infer_lock, torch.inference_mode():
            result = self._model(waveform, self.language, decoding)
        return _coerce_text(result)

    def transcribe(
        self,
        source: bytes | str | Path | torch.Tensor,
        decoding: str | None = None,
    ) -> Transcription:
        """Transcribe audio given as bytes, a path, or an already-prepared tensor."""
        decoding = _validate_decoding(decoding or self.decoding)

        # Validate and decode the input before touching the model: a corrupt
        # upload should not trigger a multi-gigabyte download to be told so.
        waveform = (
            source
            if isinstance(source, torch.Tensor)
            else audio_utils.load_audio(source)
        )
        duration = audio_utils.duration_of(waveform)

        # Handing pure silence to the model makes it hallucinate a word, which
        # then scores as a real attempt. Answer directly instead.
        if audio_utils.is_silent(waveform):
            return Transcription(
                text="",
                language=self.language,
                decoding=decoding,
                duration_sec=duration,
                elapsed_sec=0.0,
            )

        self.load()

        started = time.perf_counter()
        segments: list[Segment] = []
        for chunk in audio_utils.iter_chunks(waveform):
            text = self._decode_one(chunk.waveform, decoding).strip()
            if text:
                segments.append(Segment(chunk.start_sec, chunk.end_sec, text))
        elapsed = time.perf_counter() - started

        return Transcription(
            text=" ".join(s.text for s in segments).strip(),
            language=self.language,
            decoding=decoding,
            duration_sec=duration,
            elapsed_sec=elapsed,
            segments=segments,
        )


def _validate_decoding(decoding: str) -> str:
    normalised = decoding.strip().lower()
    if normalised not in VALID_DECODINGS:
        raise ValueError(
            f"decoding must be one of {VALID_DECODINGS}, got {decoding!r}"
        )
    return normalised


def _coerce_text(result) -> str:
    """The model returns a string for a single utterance, but be tolerant."""
    if isinstance(result, str):
        return result
    if isinstance(result, (list, tuple)):
        return " ".join(_coerce_text(item) for item in result)
    return str(result)


_default: TamilASR | None = None
_default_lock = threading.Lock()


def get_asr() -> TamilASR:
    """Process-wide singleton, so the weights are held in memory only once."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = TamilASR()
    return _default
