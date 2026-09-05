"""PostgreSQL storage for the portal.

Connections come from a pool opened at app start (``open_pool``); outside the
app — scripts, tests calling ``db_session`` directly — a plain connection is
made per call. Rows are dicts. Timestamps are ISO-8601 UTC strings with a
trailing ``Z``: they sort correctly as text and are exactly what the two
front ends parse, so nothing is converted on the way in or out.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import settings

log = logging.getLogger(__name__)

Connection = psycopg.Connection

# citext makes e-mail and username comparisons case-insensitive at the column
# level (the SQLite schema used COLLATE NOCASE for the same thing).
SCHEMA = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS doctors (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    email         CITEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 0,   -- bumped to sign every device out
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id                SERIAL PRIMARY KEY,
    first_name        TEXT NOT NULL,
    last_name         TEXT NOT NULL DEFAULT '',
    age               INTEGER,
    gender            TEXT NOT NULL DEFAULT '',
    email             CITEXT NOT NULL UNIQUE,
    phone             TEXT NOT NULL DEFAULT '',
    address           TEXT NOT NULL DEFAULT '',
    photo             TEXT,
    username          CITEXT UNIQUE,
    password_hash     TEXT,
    token_version     INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'pending',   -- pending | active
    invite_token      TEXT UNIQUE,
    invite_expires_at TEXT,
    invite_sent_at    TEXT,
    invite_email_sent BOOLEAN NOT NULL DEFAULT FALSE,
    created_by        INTEGER REFERENCES doctors (id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL,
    activated_at      TEXT
);

-- Sign-ins are stateless JWTs; this only lists the ones cut short by a logout.
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_progress (
    student_id   INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    entry_id     TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    best_stars   INTEGER NOT NULL DEFAULT 0,
    best_score   INTEGER NOT NULL DEFAULT 0,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_verdict TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (student_id, entry_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id         SERIAL PRIMARY KEY,
    doctor_id  INTEGER REFERENCES doctors (id) ON DELETE SET NULL,
    kind       TEXT NOT NULL,          -- vowels | words | sentences | long_sentences
    entry_id   TEXT,                   -- a lexicon id, or NULL for custom text
    tamil      TEXT NOT NULL,
    roman      TEXT NOT NULL DEFAULT '',
    meaning    TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    level      TEXT NOT NULL DEFAULT '',  -- easy | medium | hard
    due_at     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id         SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    entry_id   TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT '',
    verdict    TEXT NOT NULL,
    score      INTEGER NOT NULL DEFAULT 0,
    stars      INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'training',   -- training | deep | task | arcade
    task_id    INTEGER REFERENCES tasks (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_student ON attempts (student_id, created_at);

CREATE TABLE IF NOT EXISTS deep_state (
    student_id INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    entry_id   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'normal',   -- normal | deep_required | deep_done
    wrong      INTEGER NOT NULL DEFAULT 0,
    step       INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (student_id, entry_id)
);

CREATE TABLE IF NOT EXISTS task_results (
    task_id      INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    student_id   INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | attempted | done
    best_verdict TEXT,
    best_score   INTEGER NOT NULL DEFAULT 0,
    attempts     INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (task_id, student_id)
);

CREATE TABLE IF NOT EXISTS videos (
    id          SERIAL PRIMARY KEY,
    doctor_id   INTEGER REFERENCES doctors (id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    file_name   TEXT NOT NULL UNIQUE,  -- under data/videos; random, so the URL is not guessable
    mime        TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL,
    duration    DOUBLE PRECISION,      -- seconds, measured by the doctor's browser on upload
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_views (
    video_id     INTEGER NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    student_id   INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'started',   -- started | done
    position     DOUBLE PRECISION NOT NULL DEFAULT 0,   -- furthest second reached
    watched_pct  INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (video_id, student_id)
);
"""

# Columns added after a database was first created. ADD COLUMN IF NOT EXISTS
# makes each one safe to run on every start.
MIGRATIONS = [
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS level TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE doctors ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE students ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0",
]

TABLES = ("doctors", "students", "revoked_tokens", "item_progress", "tasks", "attempts",
          "deep_state", "task_results", "videos", "video_views")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """UTC ISO-8601 with a trailing Z, second precision: what the UIs parse."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return iso(utcnow())


def in_days(days: int) -> str:
    return iso(utcnow() + timedelta(days=days))


def parse_iso(value: str) -> datetime:
    """Accept what browsers and this module produce: with Z or an offset."""
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- connections ------------------------------------------------------------

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    conn.row_factory = dict_row


def connect(url: str | None = None) -> psycopg.Connection:
    """A standalone connection, for callers that live outside the app."""
    return psycopg.connect(url or settings.database_url, row_factory=dict_row)


def open_pool() -> ConnectionPool:
    """Start the app's pool. Fails fast (with the server's own message) when
    the database cannot be reached, rather than on the first request."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url, min_size=1, max_size=max(1, settings.db_pool_size),
            configure=_configure, open=False, name="portal",
        )
        _pool.open(wait=True, timeout=15)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def init_db() -> None:
    with db_session() as conn:
        conn.execute(SCHEMA)
        for ddl in MIGRATIONS:
            conn.execute(ddl)


def scalar(conn: psycopg.Connection, sql: str, params: tuple = ()):
    """The single value of a one-column query (COUNT, EXISTS, ...)."""
    row = conn.execute(sql, params).fetchone()
    return None if row is None else next(iter(row.values()))


@contextmanager
def db_session() -> Iterator[psycopg.Connection]:
    """One transaction: commits on success, rolls back on any exception."""
    if _pool is not None:
        with _pool.connection() as conn:
            yield conn
        return
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: a connection that commits on success."""
    with db_session() as conn:
        yield conn
