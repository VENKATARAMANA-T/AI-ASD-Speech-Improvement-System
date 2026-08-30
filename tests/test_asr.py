"""ASR wrapper tests.

The real IndicConformer model is multiple gigabytes, so it is exercised only
when ``RUN_MODEL_TESTS=1`` is set. Everything else runs against a stub.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.asr import (  # noqa: E402
    ModelAccessError,
    TamilASR,
    Transcription,
    _coerce_text,
    _is_gated,
    _validate_decoding,
)
from tests.test_audio import to_wav_bytes, tone  # noqa: E402


class StubModel:
    """Stands in for the Hub model: records calls, returns a fixed string."""

    def __init__(self, text: str = "தமிழ்"):
        self.text = text
        self.calls: list[tuple[int, str, str]] = []

    def __call__(self, waveform, language, decoding):
        self.calls.append((waveform.shape[1], language, decoding))
        return self.text

    def eval(self):
        return self


@pytest.fixture
def stub_asr():
    asr = TamilASR()
    asr._model = StubModel()
    return asr


def test_validate_decoding_accepts_known_modes():
    assert _validate_decoding("CTC ") == "ctc"
    assert _validate_decoding("rnnt") == "rnnt"


def test_validate_decoding_rejects_others():
    with pytest.raises(ValueError, match="decoding must be one of"):
        _validate_decoding("beam")


def test_constructor_rejects_bad_decoding():
    with pytest.raises(ValueError):
        TamilASR(decoding="greedy")


@pytest.mark.parametrize(
    "value, expected",
    [("ok", "ok"), (["a", "b"], "a b"), (("x",), "x"), (5, "5")],
)
def test_coerce_text(value, expected):
    assert _coerce_text(value) == expected


def test_transcribe_uses_language_and_decoding(stub_asr):
    result = stub_asr.transcribe(to_wav_bytes(tone(2.0)), decoding="rnnt")

    assert result.text == "தமிழ்"
    assert result.language == "ta"
    assert result.decoding == "rnnt"
    assert [c[1:] for c in stub_asr._model.calls] == [("ta", "rnnt")]


def test_transcribe_accepts_a_tensor(stub_asr):
    result = stub_asr.transcribe(torch.zeros(1, 16_000 * 3))
    assert result.duration_sec == pytest.approx(3.0, abs=0.01)


def test_long_audio_is_decoded_in_several_calls(stub_asr):
    result = stub_asr.transcribe(to_wav_bytes(tone(95.0)))

    assert len(stub_asr._model.calls) > 1
    assert len(result.segments) == len(stub_asr._model.calls)
    # Segments are joined into one transcript.
    assert result.text == " ".join(["தமிழ்"] * len(result.segments))


def test_silence_is_not_sent_to_the_model(stub_asr):
    """Regression: handed pure silence the real model invents a word, which
    then scores as a genuine attempt in the practice drill."""
    silent = torch.zeros(1, 16_000 * 2)
    result = stub_asr.transcribe(silent)

    assert result.text == ""
    assert result.segments == []
    assert result.duration_sec == pytest.approx(2.0, abs=0.01)
    assert stub_asr._model.calls == []  # the model was never invoked


def test_audible_input_still_reaches_the_model(stub_asr):
    stub_asr.transcribe(to_wav_bytes(tone(1.0)))
    assert len(stub_asr._model.calls) == 1


def test_empty_segments_are_dropped():
    asr = TamilASR()
    asr._model = StubModel(text="   ")
    result = asr.transcribe(to_wav_bytes(tone(2.0)))
    assert result.text == ""
    assert result.segments == []


def test_transcription_serialises():
    payload = Transcription(
        text="அ", language="ta", decoding="ctc",
        duration_sec=4.0, elapsed_sec=2.0,
    ).to_dict()

    assert payload["real_time_factor"] == 0.5
    assert payload["text"] == "அ"
    assert payload["segments"] == []


def test_real_time_factor_is_safe_for_zero_duration():
    assert Transcription("", "ta", "ctc", 0.0, 1.0).real_time_factor == 0.0


@pytest.mark.parametrize(
    "message, gated",
    [
        ("You are trying to access a gated repo.", True),
        ("401 Client Error. Cannot access gated repo", True),
        ("Access to model X is restricted.", True),
        ("Connection timed out", False),
    ],
)
def test_gated_errors_are_recognised(message, gated):
    assert _is_gated(Exception(message)) is gated


def test_gated_repo_raises_an_actionable_error(monkeypatch):
    """A 401 from the Hub must explain what to do, not surface a raw traceback."""
    import transformers

    def boom(*args, **kwargs):
        raise OSError("You are trying to access a gated repo.")

    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", boom)

    asr = TamilASR()
    with pytest.raises(ModelAccessError, match="huggingface-cli login"):
        asr.load()

    assert asr.is_loaded is False
    assert "gated repository" in asr.load_error


@pytest.mark.skipif(
    os.getenv("RUN_MODEL_TESTS") != "1",
    reason="set RUN_MODEL_TESTS=1 to download and run the real model",
)
def test_real_model_end_to_end():
    sample = Path(__file__).resolve().parent.parent / "samples" / "test_ta.wav"
    if not sample.is_file():
        pytest.skip("samples/test_ta.wav is not present")

    result = TamilASR().transcribe(sample)
    assert isinstance(result.text, str)
    assert result.duration_sec > 0
