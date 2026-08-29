"""Central configuration. Everything is overridable through environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file(path: Path = ENV_FILE) -> bool:
    """Read ``.env`` into the environment before any setting is resolved.

    Real environment variables win over the file, so an explicit
    ``set HF_TOKEN=...`` still overrides what is written here.
    """
    if not path.is_file():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # keep working without the optional dependency
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return True
    return load_dotenv(path, override=False)


# Must run before the Settings defaults below are evaluated at import time.
_ENV_FILE_LOADED = _load_env_file()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _resolve_hf_token() -> str:
    """HF_TOKEN is our name for it; HUGGINGFACE_HUB_TOKEN is the hub's own."""
    return os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN") or ""


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    # --- ASR model -------------------------------------------------------
    asr_model_id: str = os.getenv(
        "ASR_MODEL_ID", "ai4bharat/indic-conformer-600m-multilingual"
    )
    # Pin a commit sha here so upstream changes to the model's remote code
    # cannot silently change behaviour. "main" tracks the latest revision.
    # Known-good: e9b71b369c048e2c6b634d4c131061c34e441179
    asr_revision: str = os.getenv("ASR_REVISION", "main")
    asr_language: str = os.getenv("ASR_LANGUAGE", "ta")
    # Note: there is deliberately no decoding setting. The application always
    # uses the most accurate mode (see src.asr.DEFAULT_DECODING); making it
    # configurable let a stale .env silently downgrade accuracy.
    # Load the model when the API process boots rather than on first request.
    asr_eager_load: bool = _env_bool("ASR_EAGER_LOAD", True)
    # The AI4Bharat repo is gated: accept its terms on the Hub, then supply a
    # read token. `huggingface-cli login` also works and needs no variable.
    hf_token: str = _resolve_hf_token()

    # --- audio handling --------------------------------------------------
    sample_rate: int = 16_000
    max_upload_mb: float = _env_float("MAX_UPLOAD_MB", 200.0)
    max_duration_sec: float = _env_float("MAX_DURATION_SEC", 3600.0)
    # Long audio is split before decoding; attention cost grows quadratically.
    chunk_sec: float = _env_float("CHUNK_SEC", 30.0)
    chunk_overlap_sec: float = _env_float("CHUNK_OVERLAP_SEC", 2.0)
    # Energy threshold (dB below peak) used to find silence to split on.
    silence_top_db: float = _env_float("SILENCE_TOP_DB", 35.0)

    # --- serving ---------------------------------------------------------
    # CPU inference is blocking; more workers than this just cause thrashing.
    max_concurrent_transcriptions: int = _env_int("MAX_CONCURRENCY", 1)
    torch_threads: int = _env_int("TORCH_THREADS", 0)  # 0 = leave torch default

    # --- pronunciation (text-to-speech) ----------------------------------
    # A Microsoft neural Tamil voice; see src.tts.VOICES for the options.
    tts_voice: str = os.getenv("TTS_VOICE", "ta-IN-PallaviNeural")
    # Pre-render every lexicon entry when the server starts, so the first
    # click on "Pronounce" is instant and later ones work offline.
    tts_warm_cache: bool = _env_bool("TTS_WARM_CACHE", True)

    # --- doctor portal: accounts, tasks, lessons (src/portal) -------------
    # PostgreSQL holds accounts, progress, tasks and lesson metadata. The
    # default matches the container that docker-compose.yml starts.
    database_url: str = os.getenv("DATABASE_URL", "postgresql://tamiltutor:tamiltutor@127.0.0.1:5433/tamiltutor")
    db_pool_size: int = _env_int("DB_POOL_SIZE", 5)
    # Sign-ins are JWTs (HS256) signed with this secret. Leave it empty and a
    # random one is generated per process, which signs everyone out on restart.
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    # Photos and videos are files on disk under here.
    data_dir: Path = Path(os.getenv("PORTAL_DATA_DIR", str(PROJECT_ROOT / "data")))
    # How this server is reached from a browser: the address put in invite
    # e-mails. Set it to the LAN address if children use other machines.
    public_url: str = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    # The first doctor account, created on startup if no doctor exists yet.
    doctor_name: str = os.getenv("DOCTOR_NAME", "Dr. Tamil Tutor")
    doctor_email: str = os.getenv("DOCTOR_EMAIL", "doctor@tamiltutor.local")
    doctor_password: str = os.getenv("DOCTOR_PASSWORD", "doctor123")
    session_days: int = _env_int("SESSION_DAYS", 7)
    invite_days: int = _env_int("INVITE_DAYS", 7)
    # Invite e-mail. Leave SMTP_HOST empty to skip sending: the activation
    # link is then shown in the doctor's dashboard to be shared by hand.
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = _env_int("SMTP_PORT", 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", "")
    smtp_tls: bool = _env_bool("SMTP_TLS", True)
    smtp_ssl: bool = _env_bool("SMTP_SSL", False)
    max_photo_mb: float = _env_float("MAX_PHOTO_MB", 5.0)
    max_video_mb: float = _env_float("MAX_VIDEO_MB", 500.0)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


settings = Settings()
