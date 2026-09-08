"""API tests. The ASR singleton is replaced with a stub so no model is loaded."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import api  # noqa: E402
from src.asr import TamilASR  # noqa: E402
from tests.test_asr import StubModel  # noqa: E402
from tests.test_audio import to_wav_bytes, tone  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    asr = TamilASR()
    asr._model = StubModel()
    monkeypatch.setattr(api, "get_asr", lambda: asr)
    with TestClient(api.app) as c:
        yield c


def test_health_reports_model_state(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["language"] == "ta"
    assert body["model_loaded"] is True
    assert body["load_error"] is None


def test_transcribe_returns_text_and_metrics(client):
    files = {"file": ("clip.wav", to_wav_bytes(tone(2.0)), "audio/wav")}
    res = client.post("/transcribe", files=files)

    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "தமிழ்"
    assert body["decoding"] == "rnnt"
    assert body["filename"] == "clip.wav"
    assert body["duration_sec"] == pytest.approx(2.0, abs=0.05)
    assert "real_time_factor" in body


def test_transcribe_always_uses_the_most_accurate_decoding(client):
    """RNNT beats CTC on the FLEURS benchmark, so it is the only mode offered
    and callers cannot select a faster, less accurate one."""
    files = {"file": ("clip.wav", to_wav_bytes(tone(1.0)), "audio/wav")}
    assert client.post("/transcribe", files=files).json()["decoding"] == "rnnt"


def test_a_decoding_field_is_ignored_rather_than_honoured(client):
    files = {"file": ("clip.wav", to_wav_bytes(tone(1.0)), "audio/wav")}
    body = client.post("/transcribe", files=files, data={"decoding": "ctc"}).json()
    assert body["decoding"] == "rnnt"


def test_long_audio_returns_segments(client):
    files = {"file": ("long.wav", to_wav_bytes(tone(95.0)), "audio/wav")}
    body = client.post("/transcribe", files=files).json()
    assert len(body["segments"]) > 1
    assert body["segments"][0]["end_sec"] > body["segments"][0]["start_sec"]


def test_rejects_empty_upload(client):
    res = client.post("/transcribe", files={"file": ("x.wav", b"", "audio/wav")})
    assert res.status_code == 422


def test_rejects_undecodable_upload(client):
    files = {"file": ("x.wav", b"not audio, just bytes", "audio/wav")}
    res = client.post("/transcribe", files=files)
    assert res.status_code == 422
    assert "detail" in res.json()


def test_web_ui_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Tamil Tutor" in res.text
    # The app is hash-routed; every section must be reachable from the sidebar.
    for route in ("#/home", "#/tasks", "#/videos", "#/character", "#/train", "#/transcribe", "#/progress", "#/settings"):
        assert route in res.text, route
    # One sign-in for both roles; the doctor's dashboard is its own page.
    assert "/api/auth/login" in res.text
    assert "/api/invites/" in res.text
    assert "doctor.html" in res.text
    doc = client.get("/doctor.html")
    assert doc.status_code == 200 and "Doctor Portal" in doc.text and "/api/doctor/students" in doc.text


def test_health_reports_the_public_address_for_invite_links(client):
    body = client.get("/health").json()
    assert body["public_url"].startswith("http")
    assert not body["public_url"].endswith("/")
    assert body["email_configured"] is False


def test_romanize_endpoint(client):
    body = client.get("/romanize", params={"text": " அம்மா "}).json()
    assert body == {"text": "அம்மா", "roman": "amma"}
    assert client.get("/romanize", params={"text": "   "}).status_code == 422
    assert client.get("/romanize", params={"text": "அ" * 201}).status_code == 422


def test_transcribe_includes_the_romanisation(client):
    files = {"file": ("clip.wav", to_wav_bytes(tone(2.0)), "audio/wav")}
    body = client.post("/transcribe", files=files).json()
    assert body["text"] == "தமிழ்"
    assert body["roman"] == "thamizh"
    assert body["segments"][0]["roman"] == "thamizh"


# --- practice ---------------------------------------------------------------


def test_lexicon_lists_vowels_and_words(client):
    body = client.get("/lexicon").json()
    assert len(body["vowels"]) == 12
    assert len(body["words"]) == 20
    assert len(body["sentences"]) == 10
    assert len(body["long_sentences"]) == 10
    assert body["count"] == 52
    assert body["long_sentences"][0]["roman"] == "naan indru pallikku poagiraen"
    assert body["sentences"][0]["tamil"] == "வணக்கம் நண்பா"
    assert body["sentences"][0]["roman"] == "vanakkam nanba"
    assert body["sentences"][0]["category"] == "sentence"
    assert body["words"][0]["tamil"] == "அம்மா"
    assert body["words"][0]["roman"] == "amma"
    assert body["words"][0]["meaning"] == "mother"


def _practice(client, entry_id, files=None):
    files = files or {"file": ("try.wav", to_wav_bytes(tone(1.5)), "audio/wav")}
    return client.post("/practice", files=files, data={"entry_id": entry_id})


def test_practice_marks_a_matching_attempt_correct(client, monkeypatch):
    """The stub always returns 'தமிழ்', so practise against that entry."""
    monkeypatch.setattr(
        api.lexicon, "get",
        lambda _id: api.lexicon.Entry("t", "தமிழ்", "thamizh", "Tamil", "word"),
    )
    body = _practice(client, "t").json()

    assert body["verdict"] == "correct"
    assert body["correct"] is True
    assert body["score_percent"] == 100
    assert body["expected"]["tamil"] == "தமிழ்"
    assert body["heard"]["tamil"] == "தமிழ்"
    assert body["heard"]["roman"] == "thamizh"


def test_practice_marks_a_mismatch_incorrect(client):
    body = _practice(client, "w_amma").json()

    assert body["verdict"] == "incorrect"
    assert body["correct"] is False
    assert body["expected"]["tamil"] == "அம்மா"
    assert body["expected"]["roman"] == "amma"
    assert body["heard"]["tamil"] == "தமிழ்"


def test_practice_reports_silence(client, monkeypatch):
    monkeypatch.setattr(api.get_asr()._model, "text", "")
    body = _practice(client, "v_a").json()
    assert body["verdict"] == "no_speech"
    assert body["correct"] is False


def test_practice_includes_the_entry_and_the_transcription(client):
    body = _practice(client, "v_aa").json()
    assert body["entry"]["id"] == "v_aa"
    assert body["entry"]["tamil"] == "ஆ"
    assert body["entry"]["roman"] == "aa"
    assert body["transcription"]["duration_sec"] > 0
    assert body["transcription"]["decoding"] == "rnnt"
    assert "real_time_factor" in body["transcription"]


def test_practice_rejects_an_unknown_entry(client):
    assert _practice(client, "not_a_real_id").status_code == 404


def test_practice_rejects_an_empty_recording(client):
    files = {"file": ("try.wav", b"", "audio/wav")}
    assert _practice(client, "v_a", files=files).status_code == 422


def test_practice_rejects_undecodable_audio(client):
    files = {"file": ("try.wav", b"not audio", "audio/wav")}
    assert _practice(client, "v_a", files=files).status_code == 422


# --- pronunciation ----------------------------------------------------------


@pytest.fixture
def fake_tts(tmp_path, monkeypatch):
    """Serve pronunciations from a temp cache without touching the network."""
    monkeypatch.setattr(api.pronounce, "CACHE_DIR", tmp_path / "pronounce")

    async def fake_synthesize(text, *, voice=None, speed="normal"):
        return b"ID3" + f"{text}:{speed}".encode("utf-8")

    monkeypatch.setattr(api.pronounce, "synthesize", fake_synthesize)
    monkeypatch.setattr(api, "synthesize", fake_synthesize)
    return fake_synthesize


@pytest.fixture
def fake_feedback_tts(tmp_path, monkeypatch, fake_tts):
    monkeypatch.setattr(api.feedback, "CACHE_DIR", tmp_path / "feedback")
    calls = []

    async def fake_synthesize(text, *, voice=None, speed="normal"):
        calls.append((text, voice))
        return b"ID3" + f"{voice}|{text}".encode("utf-8")

    monkeypatch.setattr(api.feedback, "synthesize", fake_synthesize)
    return calls


def test_feedback_catalogue_covers_every_verdict(client):
    body = client.get("/feedback").json()
    assert set(body["for_verdict"]) == {"correct", "close", "incorrect", "no_speech"}
    assert set(body["for_verdict"].values()) <= set(body["phrases"])
    assert body["langs"] == ["en", "ta"]
    assert body["phrases"]["correct"]["en"] == "Well done! You spoke correctly."
    assert body["phrases"]["wrong"]["en"].startswith("Your pronunciation is wrong. The correct pronunciation is")
    # Every verdict that plays the word is followed by an improvement tip.
    assert body["tip_for"] == {"close": "tip_close", "wrong": "tip_wrong"}
    assert set(body["tip_for"].values()) <= set(body["phrases"])
    for key, texts in body["phrases"].items():
        assert texts["en"] and texts["ta"], key


def test_feedback_audio_is_spoken_in_the_right_voice_and_cached(client, fake_feedback_tts):
    res = client.get("/feedback/wrong")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
    assert res.content == b"ID3en-IN-NeerjaNeural|Your pronunciation is wrong. The correct pronunciation is"

    res = client.get("/feedback/correct", params={"lang": "ta"})
    assert res.status_code == 200
    assert res.content.startswith(b"ID3ta-IN-") and "நன்று".encode("utf-8") in res.content

    assert len(fake_feedback_tts) == 2
    client.get("/feedback/wrong")
    assert len(fake_feedback_tts) == 2   # served from the cache

    assert client.get("/health").json()["feedback"] == {"ready": 2, "total": 12}

    # Rewording a phrase must not serve the old recording.
    old = api.feedback.cache_path("wrong", "en")
    assert old.is_file()
    api.feedback.PHRASES["wrong"]["en"] = "Not quite. Say it like this:"
    try:
        res = client.get("/feedback/wrong")
        assert res.content.endswith(b"|Not quite. Say it like this:")
        assert not old.exists()   # the stale file is cleaned up
    finally:
        api.feedback.PHRASES["wrong"]["en"] = "Your pronunciation is wrong. The correct pronunciation is"
    assert client.get("/feedback/nope").status_code == 404
    assert client.get("/feedback/correct", params={"lang": "fr"}).status_code == 422


def test_pronounce_returns_mp3_for_an_entry(client, fake_tts):
    res = client.get("/pronounce/w_amma")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
    assert res.content == "ID3அம்மா:normal".encode("utf-8")
    assert "max-age" in res.headers.get("cache-control", "")


def test_pronounce_slow_speed(client, fake_tts):
    res = client.get("/pronounce/v_aa?speed=slow")
    assert res.status_code == 200
    assert res.content.endswith(b":slow")


def test_pronounce_serves_vowels_words_and_sentences(client, fake_tts):
    for entry_id in ("v_a", "v_au", "w_paatti", "w_poonai", "s_vanakkam", "s_pasi", "l_school", "l_story"):
        assert client.get(f"/pronounce/{entry_id}").status_code == 200, entry_id


def test_practice_scores_a_sentence(client, monkeypatch):
    """Multi-word targets compare ignoring spacing and punctuation."""
    monkeypatch.setattr(api.get_asr()._model, "text", "இது வீடு.")
    body = _practice(client, "s_ithu_veedu").json()
    assert body["verdict"] == "correct"
    assert body["expected"]["roman"] == "ithu veedu"
    assert body["heard"]["roman"] == "ithu veedu."


def test_pronounce_unknown_entry_is_404(client, fake_tts):
    assert client.get("/pronounce/nope").status_code == 404


def test_pronounce_unknown_speed_is_422(client, fake_tts):
    assert client.get("/pronounce/v_a?speed=fast").status_code == 422


def test_pronounce_reports_service_outage_as_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api.pronounce, "CACHE_DIR", tmp_path / "pronounce")

    async def offline(text, *, voice=None, speed="normal"):
        raise api.TTSUnavailable("no network")

    monkeypatch.setattr(api.pronounce, "synthesize", offline)
    res = client.get("/pronounce/v_a")
    assert res.status_code == 503
    assert "network" in res.json()["detail"]


def test_health_reports_pronunciation_cache(client, fake_tts):
    body = client.get("/health").json()
    assert body["pronunciation"]["total"] == 104  # 52 entries x 2 speeds
    assert body["pronunciation"]["voice"] == "ta-IN-PallaviNeural"


# --- deep training -----------------------------------------------------------


def test_decompose_returns_the_step_sequence(client, fake_tts):
    body = client.get("/decompose/w_amma").json()
    assert body["entry"]["id"] == "w_amma"
    assert [s["text"] for s in body["steps"]] == ["அம்", "மா", "அம்மா", "அம்மா"]
    assert [s["speed"] for s in body["steps"]] == ["normal", "normal", "slow", "normal"]
    assert [s["strict"] for s in body["steps"]] == [False, False, True, True]
    assert body["steps"][0]["roman"] == "am"


def test_decompose_unknown_entry_is_404(client, fake_tts):
    assert client.get("/decompose/nope").status_code == 404


def test_say_pronounces_arbitrary_text(client, fake_tts):
    res = client.get("/say", params={"text": "அம்", "speed": "slow"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
    assert res.content == "ID3அம்:slow".encode("utf-8")


def test_say_is_cached_by_content(client, fake_tts, monkeypatch):
    calls = []

    async def counting(text, *, voice=None, speed="normal"):
        calls.append(text)
        return b"ID3x"

    monkeypatch.setattr(api.pronounce, "synthesize", counting)
    client.get("/say", params={"text": "தங்"})
    client.get("/say", params={"text": "தங்"})
    assert calls == ["தங்"]


def test_say_rejects_empty_and_bad_speed(client, fake_tts):
    assert client.get("/say", params={"text": "  "}).status_code == 422
    assert client.get("/say", params={"text": "அ", "speed": "fast"}).status_code == 422


def _check(client, text, lenient=None, files=None):
    files = files or {"file": ("try.wav", to_wav_bytes(tone(1.5)), "audio/wav")}
    data = {"text": text}
    if lenient is not None:
        data["lenient"] = "true" if lenient else "false"
    return client.post("/check", files=files, data=data)


def test_check_scores_against_arbitrary_text(client, monkeypatch):
    """The stub hears 'தமிழ்'; check a piece of it leniently and the whole strictly."""
    body = _check(client, "தமிழ்").json()
    assert body["verdict"] == "correct"
    assert body["target"] == {"tamil": "தமிழ்", "roman": "thamizh", "lenient": False}

    piece = _check(client, "த", lenient=True).json()
    assert piece["verdict"] == "correct"
    assert piece["target"]["lenient"] is True

    strict_piece = _check(client, "த", lenient=False).json()
    assert strict_piece["verdict"] != "correct"


def test_check_rejects_empty_text(client):
    assert _check(client, "   ").status_code == 422


def test_check_rejects_undecodable_audio(client):
    files = {"file": ("try.wav", b"not audio", "audio/wav")}
    assert _check(client, "அ", files=files).status_code == 422


def _pick(client, target, options, files=None):
    import json
    files = files or {"file": ("try.wav", to_wav_bytes(tone(1.5)), "audio/wav")}
    return client.post("/arcade/pick", files=files, data={"target": target, "options": json.dumps(options)})


def test_arcade_pick_names_the_balloon_that_matched(client, monkeypatch):
    """The stub hears 'தமிழ்'. With that among the options, it is the pick;
    the round is won only when it was also the target."""
    monkeypatch.setattr(api.get_asr()._model, "text", "நான் தமிழ் பேசுவேன்")
    options = ["s_thamizh", "s_pasi", "s_ithu_veedu"]

    won = _pick(client, "s_thamizh", options).json()
    assert won["correct"] is True
    assert won["picked"]["id"] == "s_thamizh" and won["picked"]["index"] == 0
    assert won["target"]["id"] == "s_thamizh"
    assert [o["id"] for o in won["options"]] == options
    assert won["options"][0]["verdict"] == "correct"
    assert won["heard"]["tamil"] == "நான் தமிழ் பேசுவேன்"

    lost = _pick(client, "s_pasi", options).json()
    assert lost["correct"] is False
    assert lost["picked"]["id"] == "s_thamizh"   # the wrong balloon pops
    assert lost["verdict"] == "incorrect"        # judged against the target


def test_arcade_pick_pops_nothing_when_nothing_came_close(client):
    body = _pick(client, "w_amma", ["w_amma", "w_poo"]).json()   # stub hears 'தமிழ்'
    assert body["picked"] is None
    assert body["correct"] is False


def test_arcade_pick_validates_its_inputs(client):
    assert _pick(client, "w_amma", ["w_poo"]).status_code == 422          # target not offered
    assert _pick(client, "w_amma", []).status_code == 422                 # nothing offered
    assert _pick(client, "w_amma", ["w_amma", "nope"]).status_code == 404  # unknown entry
    files = {"file": ("try.wav", to_wav_bytes(tone(1.5)), "audio/wav")}
    assert client.post("/arcade/pick", files=files, data={"target": "w_amma", "options": "not json"}).status_code == 422


def test_lexicon_words_carry_their_syllable_count(client):
    words = {w["id"]: w for w in client.get("/lexicon").json()["words"]}
    assert words["w_amma"]["syllables"] == 2
    assert words["w_paal"]["syllables"] == 1
    assert words["w_thaatha"]["syllables"] == 2


def test_arcade_page_is_served(client):
    res = client.get("/arcade.html")
    assert res.status_code == 200
    assert "Speech Adventure" in res.text
    for title in ("Say &amp; Catch", "Balloon Speech", "Feed the Animal", "Sound Match", "Build the Word", "Treasure Hunt"):
        assert title in res.text or title.replace("&amp;", "&") in res.text


def test_speak_synthesises_arbitrary_text(client, fake_tts):
    res = client.post("/speak", data={"text": "வணக்கம்"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
    assert res.content == "ID3வணக்கம்:normal".encode("utf-8")


def test_speak_rejects_empty_text(client, fake_tts):
    assert client.post("/speak", data={"text": "  "}).status_code == 422
