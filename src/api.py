"""HTTP service: upload a file or record from the browser, get Tamil text back."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import decompose, feedback, lexicon, pronounce, scoring
from .portal import api as portal
from .asr import ModelAccessError, get_asr
from .audio import AudioError
from .config import _ENV_FILE_LOADED, ENV_FILE, PROJECT_ROOT, settings
from .translit import romanize
from .tts import MEDIA_TYPE, SPEEDS, TTSUnavailable, synthesize

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)

WEB_DIR = PROJECT_ROOT / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # CPU inference is blocking and single-threaded by design; the pool exists
    # to keep the event loop responsive, not to run transcriptions in parallel.
    # It is owned by the app, so each app instance gets a fresh one.
    pool = ThreadPoolExecutor(
        max_workers=settings.max_concurrent_transcriptions, thread_name_prefix="asr"
    )
    app.state.pool = pool
    background: list[asyncio.Task] = []
    portal.startup()   # database pool + schema, storage folders, first doctor

    if settings.asr_eager_load:
        loop = asyncio.get_running_loop()

        async def _warm_model() -> None:
            # Deliberately not awaited here: the first run downloads several GB,
            # and blocking startup would keep the port shut — and the web UI
            # unreachable — for the whole download. /health reports progress.
            log.info("warming up the model in the background")
            try:
                await loop.run_in_executor(pool, get_asr().load)
                log.info("model ready")
            except Exception:  # noqa: BLE001 - stay up and report via /health
                log.exception("warm-up failed; the API will retry on first request")

        background.append(asyncio.create_task(_warm_model()))

    if settings.tts_warm_cache:

        async def _warm_pronunciations() -> None:
            # Renders every lexicon entry once so "Pronounce" is instant and
            # keeps working offline. Skipped entries are retried on click.
            try:
                status = await pronounce.warm_cache()
                log.info(
                    "pronunciations ready: %d/%d (%d failed)",
                    status["ready"], status["total"], len(status["failed"]),
                )
            except Exception:  # noqa: BLE001
                log.exception("pronunciation warm-up failed")

        async def _warm_feedback() -> None:
            try:
                status = await feedback.warm_cache()
                log.info("feedback phrases ready: %d/%d", status["ready"], status["total"])
            except Exception:  # noqa: BLE001
                log.exception("feedback warm-up failed")

        background.append(asyncio.create_task(_warm_pronunciations()))
        background.append(asyncio.create_task(_warm_feedback()))

    try:
        yield
    finally:
        for task in background:
            if not task.done():
                task.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        portal.shutdown()   # return the database connections


async def _run_blocking(request: Request, func, *args):
    """Run a blocking call on the app's bounded pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(request.app.state.pool, func, *args)


app = FastAPI(
    title="Tamil Tutor",
    description="Tamil speech practice for children (local ASR) with the doctor's dashboard: accounts, tasks, lessons, progress.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    asr = get_asr()
    return {
        "status": "ok",
        "model_id": asr.model_id,
        "revision": asr.revision,
        "language": asr.language,
        "default_decoding": asr.decoding,
        "model_loaded": asr.is_loaded,
        "load_error": asr.load_error,
        # Never the token itself, just whether one was found and from where.
        "auth": {
            "env_file": str(ENV_FILE) if _ENV_FILE_LOADED else None,
            "hf_token_present": bool(settings.hf_token),
        },
        "pronunciation": pronounce.cache_status(),
        "feedback": feedback.cache_status(),
        # Doctor portal: whether invite e-mails go out, and the address in them.
        "email_configured": settings.email_configured,
        "public_url": settings.public_url,
    }


@app.post("/transcribe")
async def transcribe(
    request: Request,
    file: UploadFile = File(..., description="Audio file, any common format"),
) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb:.0f} MB limit.",
        )

    try:
        result = await _run_blocking(request, lambda: get_asr().transcribe(data))
    except AudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelAccessError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("transcription failed")
        raise HTTPException(
            status_code=500, detail=f"Transcription failed: {exc}"
        ) from exc

    payload = result.to_dict()
    payload["filename"] = file.filename
    payload["roman"] = romanize(result.text)
    for segment in payload["segments"]:
        segment["roman"] = romanize(segment["text"])
    return JSONResponse(payload)


@app.get("/lexicon")
async def get_lexicon() -> dict:
    """Every entry, grouped; words also say how many syllables they split into."""
    payload = lexicon.as_payload()
    for item in payload["words"]:
        item["syllables"] = len(decompose.syllables(item["tamil"]))
    return payload


@app.get("/romanize")
async def romanize_text(text: str) -> dict:
    """The English-letter form of any short Tamil text — used by the doctor
    portal when a task is typed in rather than picked from the lexicon."""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty.")
    if len(text) > pronounce.MAX_TEXT_CHARS:
        raise HTTPException(status_code=422, detail="text is too long.")
    return {"text": text, "roman": romanize(text)}


async def _transcribe_upload(request: Request, file: UploadFile):
    """Read, validate and transcribe an uploaded attempt, mapping errors to HTTP."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="The recording is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb:.0f} MB limit.",
        )
    try:
        return await _run_blocking(request, lambda: get_asr().transcribe(data))
    except AudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelAccessError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("transcription failed")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc


def _assessment_payload(assessment, result) -> dict:
    payload = assessment.to_dict()
    payload["transcription"] = result.to_dict()
    payload["transcription"]["roman"] = romanize(result.text)
    return payload


@app.post("/practice")
async def practice(
    request: Request,
    entry_id: str = Form(...),
    file: UploadFile = File(..., description="A recording of the selected sound"),
) -> JSONResponse:
    """Transcribe an attempt and judge it against the chosen lexicon entry."""
    entry = lexicon.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown entry: {entry_id!r}")

    result = await _transcribe_upload(request, file)
    assessment = scoring.assess(entry.tamil, result.text, entry.roman)
    payload = _assessment_payload(assessment, result)
    payload["entry"] = entry.to_dict()
    return JSONResponse(payload)


@app.post("/check")
async def check(
    request: Request,
    text: str = Form(..., description="The Tamil the learner was asked to say"),
    file: UploadFile = File(...),
    lenient: bool = Form(default=False),
) -> JSONResponse:
    """Judge an attempt against arbitrary Tamil text — deep-training pieces."""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty.")
    if len(text) > pronounce.MAX_TEXT_CHARS:
        raise HTTPException(status_code=422, detail="text is too long.")

    result = await _transcribe_upload(request, file)
    assessment = scoring.assess(text, result.text, lenient=lenient)
    payload = _assessment_payload(assessment, result)
    payload["target"] = {"tamil": text, "roman": romanize(text), "lenient": lenient}
    return JSONResponse(payload)


@app.post("/arcade/pick")
async def arcade_pick(
    request: Request,
    target: str = Form(..., description="The entry the child was asked to say"),
    options: str = Form(..., description="JSON list of entry ids on offer, target included"),
    file: UploadFile = File(...),
) -> JSONResponse:
    """One recording, several candidates: which did it sound like?

    The arcade's Balloon game shows a few items and asks for one; the balloon
    that matches what was heard pops, so a wrong answer is shown, not just
    marked wrong. ``picked`` is null when nothing came close.
    """
    try:
        ids = json.loads(options)
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=422, detail="options must be a JSON list of entry ids.") from None
    if not 1 <= len(ids) <= 8:
        raise HTTPException(status_code=422, detail="options must hold 1 to 8 entries.")
    if target not in ids:
        raise HTTPException(status_code=422, detail="target must be one of the options.")
    entries = []
    for entry_id in ids:
        entry = lexicon.get(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Unknown entry: {entry_id!r}")
        entries.append(entry)

    result = await _transcribe_upload(request, file)
    best, assessments = scoring.pick([(e.tamil, e.roman) for e in entries], result.text)
    target_index = ids.index(target)
    payload = _assessment_payload(assessments[target_index], result)
    payload["target"] = entries[target_index].to_dict()
    payload["picked"] = None if best is None else {"index": best, **entries[best].to_dict()}
    payload["options"] = [
        {**e.to_dict(), "verdict": a.verdict, "score_percent": round(a.score * 100)}
        for e, a in zip(entries, assessments)
    ]
    # The round is won only when the target itself was the best match.
    payload["correct"] = best == target_index and assessments[target_index].is_correct
    return JSONResponse(payload)


@app.get("/decompose/{entry_id}")
async def decompose_entry(entry_id: str) -> dict:
    """The deep-training steps for an entry. Pre-renders their audio."""
    entry = lexicon.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown entry: {entry_id!r}")

    payload = decompose.as_payload(entry)
    # Fire and forget: by the time the child taps Pronounce the piece is cached.
    if settings.tts_warm_cache:
        asyncio.create_task(
            pronounce.warm_texts([(s["text"], s["speed"]) for s in payload["steps"]])
        )
    return payload


@app.get("/say")
async def say(text: str, speed: str = "normal") -> FileResponse:
    """Hear any short Tamil text, cached by its content."""
    if speed not in SPEEDS:
        raise HTTPException(
            status_code=422, detail=f"speed must be one of {sorted(SPEEDS)}"
        )
    try:
        path = await pronounce.get_audio_for_text(text, speed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("say failed")
        raise HTTPException(status_code=500, detail=f"Pronunciation failed: {exc}") from exc

    return FileResponse(
        path,
        media_type=MEDIA_TYPE,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/feedback")
async def feedback_phrases() -> dict:
    """The spoken-feedback catalogue, so the UI can show the words it plays."""
    return {"phrases": feedback.PHRASES, "for_verdict": feedback.FOR_VERDICT, "tip_for": feedback.TIP_FOR, "langs": list(feedback.LANGS)}


@app.get("/feedback/{key}")
async def feedback_audio(key: str, lang: str = "en") -> FileResponse:
    """A spoken feedback phrase ("Well done!…") in English or Tamil."""
    if key not in feedback.PHRASES:
        raise HTTPException(status_code=404, detail=f"Unknown feedback phrase: {key!r}")
    if lang not in feedback.LANGS:
        raise HTTPException(status_code=422, detail=f"lang must be one of {list(feedback.LANGS)}")
    try:
        path = await feedback.get_audio(key, lang)
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("feedback synthesis failed")
        raise HTTPException(status_code=500, detail=f"Feedback audio failed: {exc}") from exc
    return FileResponse(path, media_type=MEDIA_TYPE, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/pronounce/{entry_id}")
async def pronounce_entry(entry_id: str, speed: str = "normal") -> FileResponse:
    """Hear a lexicon entry spoken by a native-quality neural voice."""
    entry = lexicon.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown entry: {entry_id!r}")
    if speed not in SPEEDS:
        raise HTTPException(
            status_code=422, detail=f"speed must be one of {sorted(SPEEDS)}"
        )

    try:
        path = await pronounce.get_audio(entry, speed)
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("pronunciation failed")
        raise HTTPException(status_code=500, detail=f"Pronunciation failed: {exc}") from exc

    return FileResponse(
        path,
        media_type=MEDIA_TYPE,
        filename=f"{entry.roman}.{speed}.mp3",
        # Rendered audio for an entry never changes; let the browser keep it.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/speak")
async def speak(text: str = Form(...), speed: str = Form(default="normal")) -> Response:
    """Speak arbitrary Tamil text. Not cached; needs the network each call."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty.")
    if speed not in SPEEDS:
        raise HTTPException(
            status_code=422, detail=f"speed must be one of {sorted(SPEEDS)}"
        )

    try:
        audio = await synthesize(text, speed=speed)
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("synthesis failed")
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {exc}") from exc

    return Response(content=audio, media_type=MEDIA_TYPE)


app.include_router(portal.router)

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
