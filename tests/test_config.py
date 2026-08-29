"""Configuration loading.

These exist because a token written into .env was silently ignored: the file
was documented but never read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import _load_env_file, _resolve_hf_token  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("HF_TOKEN", "ASR_DECODING", "QUOTED_VALUE"):
        monkeypatch.delenv(key, raising=False)


def test_reads_values_from_an_env_file(tmp_path: Path, clean_env, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("HF_TOKEN=hf_fromfile\nASR_DECODING=rnnt\n", encoding="utf-8")

    assert _load_env_file(env) is True
    import os

    assert os.environ["HF_TOKEN"] == "hf_fromfile"
    assert os.environ["ASR_DECODING"] == "rnnt"


def test_real_environment_wins_over_the_file(tmp_path: Path, monkeypatch):
    """An explicit `set HF_TOKEN=...` must override what .env says."""
    monkeypatch.setenv("HF_TOKEN", "hf_from_shell")
    env = tmp_path / ".env"
    env.write_text("HF_TOKEN=hf_fromfile\n", encoding="utf-8")

    _load_env_file(env)

    import os

    assert os.environ["HF_TOKEN"] == "hf_from_shell"


def test_missing_file_is_not_an_error(tmp_path: Path):
    assert _load_env_file(tmp_path / "nope.env") is False


def test_comments_and_blank_lines_are_ignored(tmp_path: Path, clean_env):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n\nHF_TOKEN=hf_ok\n# HF_TOKEN=hf_commented_out\n",
        encoding="utf-8",
    )
    _load_env_file(env)

    import os

    assert os.environ["HF_TOKEN"] == "hf_ok"


def test_quoted_values_are_unwrapped(tmp_path: Path, clean_env):
    env = tmp_path / ".env"
    env.write_text('QUOTED_VALUE="hf_quoted"\n', encoding="utf-8")
    _load_env_file(env)

    import os

    assert os.environ["QUOTED_VALUE"] == "hf_quoted"


def test_hf_token_prefers_our_variable(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_ours")
    monkeypatch.setenv("HUGGINGFACE_HUB_TOKEN", "hf_theirs")
    assert _resolve_hf_token() == "hf_ours"


def test_hf_token_falls_back_to_the_hub_variable(monkeypatch):
    """HUGGINGFACE_HUB_TOKEN is the hub's own name for it; accept both."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACE_HUB_TOKEN", "hf_theirs")
    assert _resolve_hf_token() == "hf_theirs"


def test_hf_token_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    assert _resolve_hf_token() == ""
