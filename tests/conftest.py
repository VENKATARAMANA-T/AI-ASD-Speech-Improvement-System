"""Shared test setup.

Runs before ``src.config`` is imported anywhere, so the settings frozen at
import time are the test ones: never auto-download the model during a test
run, never call the speech service, never send e-mail, and use a separate
PostgreSQL database that is emptied before every portal test.

The test database is ``TEST_DATABASE_URL`` if set, otherwise ``DATABASE_URL``
with the database name replaced by ``tamiltutor_test``. It is created on the
first run (the role needs CREATEDB, which the docker-compose one has).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ASR_EAGER_LOAD", "0")
os.environ.setdefault("TTS_WARM_CACHE", "0")
os.environ["SMTP_HOST"] = ""
os.environ["DOCTOR_EMAIL"] = "doc@test.local"
os.environ["DOCTOR_PASSWORD"] = "doctor-pass"
os.environ["DOCTOR_NAME"] = "Dr. Test"
os.environ["PUBLIC_URL"] = "http://testserver"
os.environ["JWT_SECRET"] = "test-secret-not-for-production"

DEFAULT_URL = "postgresql://tamiltutor:tamiltutor@127.0.0.1:5433/tamiltutor"


def _from_env_or_file(key: str) -> str | None:
    """The shell wins over .env, as in src.config — read here without
    importing src.config, whose settings freeze on import."""
    if os.environ.get(key):
        return os.environ[key]
    from dotenv import dotenv_values

    return dotenv_values(ROOT / ".env").get(key) or None


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/" + name))


APP_DATABASE_URL = _from_env_or_file("DATABASE_URL") or DEFAULT_URL
TEST_DATABASE_URL = _from_env_or_file("TEST_DATABASE_URL") or _with_database(APP_DATABASE_URL, "tamiltutor_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


# --- database ------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Make sure the test database exists and is reachable, once per run."""
    import psycopg

    name = urlsplit(TEST_DATABASE_URL).path.lstrip("/")
    try:
        with psycopg.connect(APP_DATABASE_URL, autocommit=True, connect_timeout=5) as admin:
            if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is None:
                admin.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at {APP_DATABASE_URL!r}: {exc}\n"
            "Start it with `docker compose up -d` (or set DATABASE_URL) and run the tests again.",
            returncode=3,
        )
    yield TEST_DATABASE_URL


def reset_database() -> None:
    """Drop everything: each test starts from an empty schema, which the app
    creates again on startup (ids restart at 1)."""
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")


# --- doctor-portal fixtures --------------------------------------------------


@pytest.fixture
def portal_client(tmp_path):
    """The app with an empty accounts database and a throwaway data folder."""
    from fastapi.testclient import TestClient

    from src import api
    from src.config import settings

    reset_database()
    saved = settings.data_dir
    object.__setattr__(settings, "data_dir", tmp_path)
    try:
        with TestClient(api.app) as c:
            yield c
    finally:
        object.__setattr__(settings, "data_dir", saved)


@pytest.fixture
def doctor(portal_client):
    res = portal_client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "doctor-pass"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def add_student(client, doctor, **over):
    data = {"first_name": "Ravi", "last_name": "Kumar", "age": "7", "gender": "male",
            "email": "ravi@example.com", "phone": "9999", "address": "Chennai"}
    data.update(over)
    return client.post("/api/doctor/students", data=data, headers=doctor)


def activate_student(client, invite_link, username="ravi", password="ravi-pass"):
    token = invite_link.rsplit("/", 1)[-1]
    res = client.post(f"/api/invites/{token}/activate",
                      json={"username": username, "password": password, "confirm_password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture
def student(portal_client, doctor):
    """An activated student: (headers, student payload)."""
    created = add_student(portal_client, doctor).json()
    headers = activate_student(portal_client, created["invite"]["link"])
    return headers, created["student"]
