"""Doctor-portal endpoints, mounted into the main app.

Three groups:

* public — logins, invite activation, the lexicon;
* ``/api/doctor/*`` — the dashboard: students, their progress, daily tasks, video lessons;
* ``/api/student/*`` — called by the child's UI to sync progress and to fetch
  and complete today's tasks and lessons.

Role-based access: every sign-in is a JWT carrying a ``role`` claim (doctor
or student); ``require_doctor`` / ``require_student`` reject a token of the
other role, so a child cannot reach doctor endpoints and vice versa. Tokens
are stateless; a logout records the token's id in ``revoked_tokens`` and a
password change bumps the account's ``token_version``, either of which
retires a token before it expires.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import settings
from . import lexicon as lex
from . import mailer
from .db import Connection, close_pool, db_session, get_db, in_days, init_db, iso, now_iso, open_pool, parse_iso, scalar, utcnow
from .security import decode_jwt, hash_password, issue_jwt, new_token, password_problem, verify_password

Row = dict[str, Any]

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@+-]{3,64}$")
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg", ".mov": "video/quicktime"}
VIDEO_DONE_PCT = 90   # reaching this much of a lesson counts as having watched it
GENDERS = {"male", "female", "other"}
STARS = {"correct": 3, "close": 2, "incorrect": 1, "no_speech": 0}
TASK_DONE_VERDICTS = {"correct", "close"}   # two stars or better finishes a task
TaskKind = Literal["vowels", "words", "sentences", "long_sentences"]
TaskLevel = Literal["easy", "medium", "hard"]
LEVEL_NAMES = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}
Role = Literal["doctor", "child"]

router = APIRouter()


def seed_doctor() -> None:
    """Create the first doctor account when the table is empty."""
    with db_session() as conn:
        if conn.execute("SELECT 1 FROM doctors LIMIT 1").fetchone():
            return
        conn.execute(
            "INSERT INTO doctors (name, email, password_hash, created_at) VALUES (%s, %s, %s, %s)",
            (settings.doctor_name, settings.doctor_email, hash_password(settings.doctor_password), now_iso()),
        )
    log.warning("created the first doctor account: %s (change the password in Settings)", settings.doctor_email)


def startup() -> None:
    """Called from the app's lifespan: storage folders, database, first doctor."""
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    open_pool()
    init_db()
    seed_doctor()


def shutdown() -> None:
    close_pool()


# ---------------------------------------------------------------------------
# auth helpers
# ---------------------------------------------------------------------------


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _token_subject(conn: Connection, token: str | None, role: str | None = None) -> tuple[str, Row] | None:
    """(role, account row) for a live token, or None. A token is live when its
    signature and expiry check out, it has not been logged out, and the
    account's token_version still matches (a password change bumps it)."""
    claims = decode_jwt(token)
    if claims is None or (role is not None and claims["role"] != role):
        return None
    if conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = %s", (claims["jti"],)).fetchone():
        return None
    table = "doctors" if claims["role"] == "doctor" else "students"
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (int(claims["sub"]),)).fetchone()
    if row is None or row["token_version"] != claims["ver"]:
        return None
    return claims["role"], row


def require_doctor(conn: Connection = Depends(get_db), authorization: str | None = Header(default=None)) -> Row:
    found = _token_subject(conn, _bearer(authorization), "doctor")
    if found is None:
        raise HTTPException(status_code=401, detail="Please sign in as a doctor.")
    return found[1]


def require_student(conn: Connection = Depends(get_db), authorization: str | None = Header(default=None)) -> Row:
    found = _token_subject(conn, _bearer(authorization), "student")
    if found is None or found[1]["status"] != "active":
        raise HTTPException(status_code=401, detail="Please sign in.")
    return found[1]


def _sign_in(conn: Connection, role: str, row: Row) -> str:
    conn.execute("DELETE FROM revoked_tokens WHERE expires_at <= %s", (now_iso(),))
    return issue_jwt(role, row["id"], row["token_version"])


def doctor_public(row: Row) -> dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def student_public(row: Row) -> dict:
    """What both dashboards may see about a student. Never the password hash."""
    return {
        "id": row["id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "name": f"{row['first_name']} {row['last_name']}".strip(),
        "age": row["age"],
        "gender": row["gender"],
        "email": row["email"],
        "phone": row["phone"],
        "address": row["address"],
        "photo_url": f"/photos/{row['photo']}" if row["photo"] else None,
        "username": row["username"],
        "status": row["status"],
        "created_at": row["created_at"],
        "activated_at": row["activated_at"],
        "invite": None if row["status"] != "pending" else {
            "link": invite_link(row["invite_token"]),
            "expires_at": row["invite_expires_at"],
            "sent_at": row["invite_sent_at"],
            "email_sent": bool(row["invite_email_sent"]),
        },
    }


def invite_link(token: str | None) -> str | None:
    return f"{settings.public_url}/#/activate/{token}" if token else None


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------


@router.get("/api/lexicon")
def get_lexicon() -> dict:
    payload = dict(lex.get_lexicon())
    payload["categories"] = [lex.CATEGORIES[k] for k in lex.CATEGORY_ORDER]
    return payload


class DoctorLogin(BaseModel):
    email: str
    password: str


@router.post("/api/auth/doctor/login")
def doctor_login(body: DoctorLogin, conn: Connection = Depends(get_db)) -> dict:
    row = conn.execute("SELECT * FROM doctors WHERE email = %s", (body.email.strip(),)).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    return {"token": _sign_in(conn, "doctor", row), "doctor": doctor_public(row)}


class StudentLogin(BaseModel):
    identifier: str = Field(description="username or email")
    password: str


@router.post("/api/auth/student/login")
def student_login(body: StudentLogin, conn: Connection = Depends(get_db)) -> dict:
    ident = body.identifier.strip()
    row = conn.execute(
        "SELECT * FROM students WHERE (username = %s OR email = %s)", (ident, ident)
    ).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong username/email or password.")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="This account has not been set up yet. Use the link in your email.")
    return {"token": _sign_in(conn, "student", row), "student": student_public(row)}


class RoleLogin(BaseModel):
    role: Role
    identifier: str = Field(description="doctor e-mail, or the child's username / e-mail")
    password: str


@router.post("/api/auth/login")
def role_login(body: RoleLogin, conn: Connection = Depends(get_db)) -> dict:
    """One sign-in for both roles: the chosen role decides which accounts are
    searched, so a doctor's password never opens the child app or vice versa."""
    if body.role == "doctor":
        out = doctor_login(DoctorLogin(email=body.identifier, password=body.password), conn)
    else:
        out = student_login(StudentLogin(identifier=body.identifier, password=body.password), conn)
    return {**out, "role": body.role}


@router.get("/api/auth/me")
def whoami(conn: Connection = Depends(get_db), authorization: str | None = Header(default=None)) -> dict:
    """Which role a token belongs to, so each front end can bounce the wrong one."""
    found = _token_subject(conn, _bearer(authorization))
    if found is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    role, row = found
    if role == "doctor":
        return {"role": "doctor", "doctor": doctor_public(row), "now": now_iso()}
    return {"role": "child", "student": student_public(row), "now": now_iso()}


@router.post("/api/auth/logout")
def logout(conn: Connection = Depends(get_db), authorization: str | None = Header(default=None)) -> dict:
    """Retire this token now rather than at its expiry."""
    claims = decode_jwt(_bearer(authorization))
    if claims:
        conn.execute(
            "INSERT INTO revoked_tokens (jti, expires_at) VALUES (%s, %s) ON CONFLICT (jti) DO NOTHING",
            (claims["jti"], iso(datetime.fromtimestamp(claims["exp"], tz=timezone.utc))),
        )
    return {"ok": True}


def _invite_row(conn: Connection, token: str) -> tuple[Row | None, str | None]:
    row = conn.execute("SELECT * FROM students WHERE invite_token = %s", (token,)).fetchone()
    if row is None:
        return None, "This invitation link is not valid."
    if row["status"] != "pending":
        return row, "This account has already been set up. Please sign in."
    if row["invite_expires_at"] and row["invite_expires_at"] <= now_iso():
        return row, "This invitation has expired. Ask your doctor to send a new one."
    return row, None


@router.get("/api/invites/{token}")
def invite_info(token: str, conn: Connection = Depends(get_db)) -> dict:
    row, problem = _invite_row(conn, token)
    if row is None:
        raise HTTPException(status_code=404, detail=problem)
    return {
        "valid": problem is None,
        "reason": problem,
        "email": row["email"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "expires_at": row["invite_expires_at"],
    }


class Activate(BaseModel):
    username: str
    password: str
    confirm_password: str


@router.post("/api/invites/{token}/activate")
def activate(token: str, body: Activate, conn: Connection = Depends(get_db)) -> dict:
    row, problem = _invite_row(conn, token)
    if row is None:
        raise HTTPException(status_code=404, detail=problem)
    if problem:
        raise HTTPException(status_code=410, detail=problem)
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=422, detail="Username must be 3–64 characters: letters, numbers, . _ @ + -")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="The two passwords do not match.")
    if (why := password_problem(body.password)):
        raise HTTPException(status_code=422, detail=why)
    clash = conn.execute(
        "SELECT id FROM students WHERE id != %s AND (username = %s OR email = %s)", (row["id"], username, username)
    ).fetchone()
    if clash:
        raise HTTPException(status_code=409, detail="That username is already taken. Try another.")
    student = conn.execute(
        """UPDATE students SET username = %s, password_hash = %s, status = 'active', activated_at = %s,
           invite_token = NULL, invite_expires_at = NULL WHERE id = %s RETURNING *""",
        (username, hash_password(body.password), now_iso(), row["id"]),
    ).fetchone()
    return {"token": _sign_in(conn, "student", student), "student": student_public(student)}


# ---------------------------------------------------------------------------
# progress (shared by both dashboards)
# ---------------------------------------------------------------------------


def _progress_maps(conn: Connection, student_id: int) -> tuple[dict, dict]:
    items = {
        r["entry_id"]: {
            "best": r["best_stars"], "bestScore": r["best_score"], "attempts": r["attempts"],
            "last": r["last_verdict"], "at": r["updated_at"], "category": r["category"],
        }
        for r in conn.execute("SELECT * FROM item_progress WHERE student_id = %s", (student_id,))
    }
    deep = {
        r["entry_id"]: {"status": r["status"], "wrong": r["wrong"], "step": r["step"], "at": r["updated_at"]}
        for r in conn.execute("SELECT * FROM deep_state WHERE student_id = %s", (student_id,))
    }
    return items, deep


def student_progress(conn: Connection, student_id: int, lexicon: dict) -> dict:
    """Progress by category, plus the deep-training queue, for the doctor's view."""
    items, deep = _progress_maps(conn, student_id)
    categories = []
    totals = {"stars": 0, "mastered": 0, "total": 0, "attempts": 0}
    for key in lex.CATEGORY_ORDER:
        meta = lex.CATEGORIES[key]
        entries = lexicon.get(key, [])
        rows = []
        for e in entries:
            p = items.get(e["id"], {})
            d = deep.get(e["id"], {})
            rows.append({
                **{k: e[k] for k in ("id", "tamil", "roman", "meaning")},
                "best_stars": p.get("best", 0), "best_score": p.get("bestScore", 0),
                "attempts": p.get("attempts", 0), "last_verdict": p.get("last"), "last_at": p.get("at"),
                "deep_status": d.get("status", "normal"),
            })
        mastered = sum(1 for r in rows if r["best_stars"] >= 3)
        tried = sum(1 for r in rows if r["attempts"])
        totals["stars"] += sum(r["best_stars"] for r in rows)
        totals["mastered"] += mastered
        totals["total"] += len(rows)
        totals["attempts"] += sum(r["attempts"] for r in rows)
        categories.append({
            **meta, "total": len(rows), "mastered": mastered, "tried": tried,
            "pct": round(mastered / len(rows) * 100) if rows else 0, "items": rows,
        })
    by_id = lex.by_id(lexicon)
    deep_rows = [
        {**{k: by_id[eid][k] for k in ("id", "tamil", "roman", "meaning", "cat")}, **state}
        for eid, state in deep.items() if eid in by_id and state["status"] in ("deep_required", "deep_done")
    ]
    return {
        "categories": categories,
        "totals": totals,
        "deep": {
            "pending": [d for d in deep_rows if d["status"] == "deep_required"],
            "done": [d for d in deep_rows if d["status"] == "deep_done"],
        },
    }


def _upsert_item(conn: Connection, student_id: int, entry_id: str, category: str,
                 stars: int, score: int, verdict: str | None, add_attempts: int = 1) -> dict:
    row = conn.execute(
        """INSERT INTO item_progress (student_id, entry_id, category, best_stars, best_score, attempts, last_verdict, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (student_id, entry_id) DO UPDATE SET
               category = COALESCE(NULLIF(EXCLUDED.category, ''), item_progress.category),
               best_stars = GREATEST(item_progress.best_stars, EXCLUDED.best_stars),
               best_score = GREATEST(item_progress.best_score, EXCLUDED.best_score),
               attempts = item_progress.attempts + EXCLUDED.attempts,
               last_verdict = COALESCE(EXCLUDED.last_verdict, item_progress.last_verdict),
               updated_at = EXCLUDED.updated_at
           RETURNING *""",
        (student_id, entry_id, category, stars, score, add_attempts, verdict, now_iso()),
    ).fetchone()
    return {"best": row["best_stars"], "bestScore": row["best_score"], "attempts": row["attempts"],
            "last": row["last_verdict"], "at": row["updated_at"]}


# ---------------------------------------------------------------------------
# student API (called by the child portal)
# ---------------------------------------------------------------------------


@router.get("/api/student/me")
def student_me(student: Row = Depends(require_student)) -> dict:
    return {"student": student_public(student), "now": now_iso()}


@router.get("/api/student/progress")
def student_get_progress(student: Row = Depends(require_student), conn: Connection = Depends(get_db)) -> dict:
    items, deep = _progress_maps(conn, student["id"])
    return {"items": items, "deep": deep}


class Attempt(BaseModel):
    entry_id: str
    category: str = ""
    verdict: str
    score_percent: int = Field(default=0, ge=0, le=100)
    source: Literal["training", "deep", "task", "arcade"] = "training"


@router.post("/api/student/attempts")
def student_attempt(body: Attempt, student: Row = Depends(require_student), conn: Connection = Depends(get_db)) -> dict:
    if body.verdict not in STARS:
        raise HTTPException(status_code=422, detail=f"verdict must be one of {sorted(STARS)}")
    stars = STARS[body.verdict]
    conn.execute(
        """INSERT INTO attempts (student_id, entry_id, category, verdict, score, stars, source, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (student["id"], body.entry_id, body.category, body.verdict, body.score_percent, stars, body.source, now_iso()),
    )
    return {"item": _upsert_item(conn, student["id"], body.entry_id, body.category, stars, body.score_percent, body.verdict)}


class DeepUpdate(BaseModel):
    status: Literal["normal", "deep_required", "deep_done"]
    wrong: int = 0
    step: int = 0


@router.put("/api/student/deep/{entry_id}")
def student_deep(
    entry_id: str, body: DeepUpdate, student: Row = Depends(require_student), conn: Connection = Depends(get_db),
) -> dict:
    conn.execute(
        """INSERT INTO deep_state (student_id, entry_id, status, wrong, step, updated_at) VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (student_id, entry_id) DO UPDATE SET status = EXCLUDED.status, wrong = EXCLUDED.wrong,
           step = EXCLUDED.step, updated_at = EXCLUDED.updated_at""",
        (student["id"], entry_id, body.status, body.wrong, body.step, now_iso()),
    )
    return {"ok": True}


class ProgressSync(BaseModel):
    items: dict[str, dict] = Field(default_factory=dict)
    deep: dict[str, dict] = Field(default_factory=dict)


@router.post("/api/student/progress/sync")
def student_sync(body: ProgressSync, student: Row = Depends(require_student), conn: Connection = Depends(get_db)) -> dict:
    """Merge progress kept in a browser before the account existed: best-of."""
    for entry_id, p in body.items.items():
        cur = conn.execute(
            "SELECT attempts FROM item_progress WHERE student_id = %s AND entry_id = %s", (student["id"], entry_id)
        ).fetchone()
        add = 0 if cur else int(p.get("attempts") or 0)
        _upsert_item(conn, student["id"], entry_id, str(p.get("category") or ""),
                     int(p.get("best") or 0), int(p.get("bestScore") or 0), p.get("last"), add_attempts=add)
    for entry_id, d in body.deep.items():
        status = d.get("status") if d.get("status") in ("normal", "deep_required", "deep_done") else "normal"
        conn.execute(
            """INSERT INTO deep_state (student_id, entry_id, status, wrong, step, updated_at) VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (student_id, entry_id) DO NOTHING""",
            (student["id"], entry_id, status, int(d.get("wrong") or 0), int(d.get("step") or 0), now_iso()),
        )
    items, deep = _progress_maps(conn, student["id"])
    return {"items": items, "deep": deep}


def _task_public(row: Row, now: str) -> dict:
    return {
        "id": row["id"], "kind": row["kind"], "kind_name": lex.CATEGORIES[row["kind"]]["short"],
        "entry_id": row["entry_id"], "tamil": row["tamil"], "roman": row["roman"], "meaning": row["meaning"],
        "note": row["note"], "level": row["level"], "level_name": LEVEL_NAMES.get(row["level"], ""),
        "due_at": row["due_at"], "created_at": row["created_at"], "expired": row["due_at"] <= now,
    }


def _result_public(row: Row | None) -> dict:
    if row is None:
        return {"status": "pending", "best_verdict": None, "best_score": 0, "attempts": 0, "completed_at": None}
    return {"status": row["status"], "best_verdict": row["best_verdict"], "best_score": row["best_score"],
            "attempts": row["attempts"], "completed_at": row["completed_at"]}


@router.get("/api/student/tasks")
def student_tasks(student: Row = Depends(require_student), conn: Connection = Depends(get_db)) -> dict:
    """Tasks still open, plus the ones that closed in the last day (so a miss is visible)."""
    now = now_iso()
    since = iso(utcnow() - timedelta(days=1))
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_at > %s ORDER BY due_at ASC, id ASC", (since,)
    ).fetchall()
    tasks = []
    for r in rows:
        res = conn.execute(
            "SELECT * FROM task_results WHERE task_id = %s AND student_id = %s", (r["id"], student["id"])
        ).fetchone()
        tasks.append({**_task_public(r, now), "my": _result_public(res)})
    return {"now": now, "tasks": tasks}


@router.get("/api/student/calendar")
def student_calendar(student: Row = Depends(require_student), conn: Connection = Depends(get_db)) -> dict:
    """Every task the student has been set, with their result, for the
    done-or-not calendar on the child's home page (grouped by day client-side,
    in the child's own time zone)."""
    now = now_iso()
    rows = conn.execute(
        """SELECT t.id, t.due_at, t.created_at, r.status, r.completed_at
           FROM tasks t LEFT JOIN task_results r ON r.task_id = t.id AND r.student_id = %s
           ORDER BY t.due_at ASC""",
        (student["id"],),
    ).fetchall()
    return {
        "now": now,
        "tasks": [{
            "id": r["id"], "due_at": r["due_at"], "created_at": r["created_at"],
            "status": r["status"] or "pending", "completed_at": r["completed_at"], "expired": r["due_at"] <= now,
        } for r in rows],
    }


class TaskAttempt(BaseModel):
    verdict: str
    score_percent: int = Field(default=0, ge=0, le=100)


@router.post("/api/student/tasks/{task_id}/attempts")
def student_task_attempt(
    task_id: int, body: TaskAttempt, student: Row = Depends(require_student), conn: Connection = Depends(get_db),
) -> dict:
    task = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail="That task no longer exists.")
    if body.verdict not in STARS:
        raise HTTPException(status_code=422, detail=f"verdict must be one of {sorted(STARS)}")
    now = now_iso()
    if task["due_at"] <= now:
        raise HTTPException(status_code=409, detail="Time is up for this task.")
    stars = STARS[body.verdict]
    conn.execute(
        """INSERT INTO attempts (student_id, entry_id, category, verdict, score, stars, source, task_id, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, 'task', %s, %s)""",
        (student["id"], task["entry_id"] or f"task:{task_id}", task["kind"], body.verdict, body.score_percent, stars, task_id, now),
    )
    if task["entry_id"]:
        _upsert_item(conn, student["id"], task["entry_id"], task["kind"], stars, body.score_percent, body.verdict)
    done = body.verdict in TASK_DONE_VERDICTS
    cur = conn.execute(
        "SELECT * FROM task_results WHERE task_id = %s AND student_id = %s", (task_id, student["id"])
    ).fetchone()
    rank = {None: -1, "no_speech": 0, "incorrect": 1, "close": 2, "correct": 3}
    if cur is None:
        conn.execute(
            """INSERT INTO task_results (task_id, student_id, status, best_verdict, best_score, attempts, completed_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, 1, %s, %s)""",
            (task_id, student["id"], "done" if done else "attempted", body.verdict, body.score_percent, now if done else None, now),
        )
    else:
        best_verdict = body.verdict if rank[body.verdict] >= rank[cur["best_verdict"]] else cur["best_verdict"]
        status = "done" if (done or cur["status"] == "done") else "attempted"
        completed_at = cur["completed_at"] or (now if done else None)
        conn.execute(
            """UPDATE task_results SET status = %s, best_verdict = %s, best_score = GREATEST(best_score, %s), attempts = attempts + 1,
               completed_at = %s, updated_at = %s WHERE task_id = %s AND student_id = %s""",
            (status, best_verdict, body.score_percent, completed_at, now, task_id, student["id"]),
        )
    res = conn.execute(
        "SELECT * FROM task_results WHERE task_id = %s AND student_id = %s", (task_id, student["id"])
    ).fetchone()
    return {"task": _task_public(task, now), "my": _result_public(res)}


# --- video lessons (student side) -------------------------------------------


def _video_public(row: Row) -> dict:
    return {
        "id": row["id"], "title": row["title"], "description": row["description"],
        "url": f"/videos/{row['file_name']}", "mime": row["mime"], "size_bytes": row["size_bytes"],
        "duration": row["duration"], "created_at": row["created_at"],
    }


def _view_public(row: Row | None) -> dict:
    if row is None:
        return {"status": "new", "position": 0, "watched_pct": 0, "started_at": None, "completed_at": None}
    return {"status": row["status"], "position": row["position"], "watched_pct": row["watched_pct"],
            "started_at": row["started_at"], "completed_at": row["completed_at"]}


@router.get("/api/student/videos")
def student_videos(student: Row = Depends(require_student), conn: Connection = Depends(get_db)) -> dict:
    videos = []
    for v in conn.execute("SELECT * FROM videos ORDER BY id DESC").fetchall():
        view = conn.execute(
            "SELECT * FROM video_views WHERE video_id = %s AND student_id = %s", (v["id"], student["id"])
        ).fetchone()
        videos.append({**_video_public(v), "my": _view_public(view)})
    return {"now": now_iso(), "videos": videos}


class VideoProgress(BaseModel):
    position: float = Field(default=0, ge=0, description="seconds into the video")
    duration: float | None = Field(default=None, gt=0, description="length as the player sees it")
    ended: bool = False


@router.post("/api/student/videos/{video_id}/progress")
def student_video_progress(
    video_id: int, body: VideoProgress, student: Row = Depends(require_student), conn: Connection = Depends(get_db),
) -> dict:
    video = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
    if video is None:
        raise HTTPException(status_code=404, detail="That video lesson no longer exists.")
    length = body.duration or video["duration"]
    if body.duration and not video["duration"]:
        video = conn.execute(
            "UPDATE videos SET duration = %s WHERE id = %s RETURNING *", (body.duration, video_id)
        ).fetchone()
    pct = 100 if body.ended else (min(100, round(body.position / length * 100)) if length else 0)
    done = body.ended or pct >= VIDEO_DONE_PCT
    now = now_iso()
    cur = conn.execute(
        "SELECT * FROM video_views WHERE video_id = %s AND student_id = %s", (video_id, student["id"])
    ).fetchone()
    if cur is None:
        conn.execute(
            """INSERT INTO video_views (video_id, student_id, status, position, watched_pct, started_at, completed_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (video_id, student["id"], "done" if done else "started", body.position, pct, now, now if done else None, now),
        )
    else:
        status = "done" if (done or cur["status"] == "done") else "started"
        conn.execute(
            """UPDATE video_views SET status = %s, position = GREATEST(position, %s), watched_pct = GREATEST(watched_pct, %s),
               completed_at = COALESCE(completed_at, %s), updated_at = %s WHERE video_id = %s AND student_id = %s""",
            (status, body.position, pct, now if done else None, now, video_id, student["id"]),
        )
    view = conn.execute(
        "SELECT * FROM video_views WHERE video_id = %s AND student_id = %s", (video_id, student["id"])
    ).fetchone()
    return {"video": _video_public(video), "my": _view_public(view)}


# ---------------------------------------------------------------------------
# doctor API
# ---------------------------------------------------------------------------


@router.get("/api/doctor/me")
def doctor_me(doctor: Row = Depends(require_doctor)) -> dict:
    return {"doctor": doctor_public(doctor), "now": now_iso(), "email_configured": settings.email_configured}


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/doctor/password")
def doctor_change_password(
    body: ChangePassword, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)
) -> dict:
    """Changes the password and signs every other device out; the caller gets
    a fresh token so this browser stays signed in."""
    if not verify_password(body.current_password, doctor["password_hash"]):
        raise HTTPException(status_code=403, detail="The current password is wrong.")
    if (why := password_problem(body.new_password)):
        raise HTTPException(status_code=422, detail=why)
    row = conn.execute(
        "UPDATE doctors SET password_hash = %s, token_version = token_version + 1 WHERE id = %s RETURNING *",
        (hash_password(body.new_password), doctor["id"]),
    ).fetchone()
    return {"ok": True, "token": _sign_in(conn, "doctor", row)}


async def _student_summary(conn: Connection, row: Row, lexicon: dict, now: str) -> dict:
    total = lexicon["count"]
    mastered = scalar(conn, "SELECT COUNT(*) FROM item_progress WHERE student_id = %s AND best_stars >= 3", (row["id"],))
    attempts = scalar(conn, "SELECT COUNT(*) FROM attempts WHERE student_id = %s", (row["id"],))
    deep_pending = scalar(
        conn, "SELECT COUNT(*) FROM deep_state WHERE student_id = %s AND status = 'deep_required'", (row["id"],)
    )
    tasks_open = scalar(conn, "SELECT COUNT(*) FROM tasks WHERE due_at > %s", (now,))
    tasks_done = scalar(
        conn,
        """SELECT COUNT(*) FROM task_results r JOIN tasks t ON t.id = r.task_id
           WHERE r.student_id = %s AND r.status = 'done' AND t.due_at > %s""",
        (row["id"], now),
    )
    last = conn.execute(
        "SELECT created_at FROM attempts WHERE student_id = %s ORDER BY id DESC LIMIT 1", (row["id"],)
    ).fetchone()
    return {
        **student_public(row),
        "summary": {
            "mastered": mastered, "total": total, "pct": round(mastered / total * 100) if total else 0,
            "attempts": attempts, "deep_pending": deep_pending,
            "tasks_open": tasks_open, "tasks_done": tasks_done,
            "last_active": last["created_at"] if last else None,
        },
    }


@router.get("/api/doctor/overview")
async def doctor_overview(doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    now = now_iso()
    lexicon = lex.get_lexicon()
    students = conn.execute("SELECT * FROM students ORDER BY first_name, last_name").fetchall()
    open_tasks = conn.execute("SELECT * FROM tasks WHERE due_at > %s ORDER BY due_at", (now,)).fetchall()
    active_ids = [s["id"] for s in students if s["status"] == "active"]
    tasks = []
    for t in open_tasks:
        done = scalar(conn, "SELECT COUNT(*) FROM task_results WHERE task_id = %s AND status = 'done'", (t["id"],))
        tasks.append({**_task_public(t, now), "done": done, "students": len(active_ids)})
    recent = conn.execute(
        """SELECT a.*, s.first_name, s.last_name, s.photo FROM attempts a JOIN students s ON s.id = a.student_id
           ORDER BY a.id DESC LIMIT 12"""
    ).fetchall()
    by_id = lex.by_id(lexicon)
    activity = [{
        "student_id": r["student_id"], "student": f"{r['first_name']} {r['last_name']}".strip(),
        "photo_url": f"/photos/{r['photo']}" if r["photo"] else None,
        "entry_id": r["entry_id"], "tamil": by_id.get(r["entry_id"], {}).get("tamil", r["entry_id"]),
        "verdict": r["verdict"], "score": r["score"], "stars": r["stars"], "source": r["source"], "at": r["created_at"],
    } for r in recent]
    mastered_total = scalar(conn, "SELECT COUNT(*) FROM item_progress WHERE best_stars >= 3")
    deep_pending = scalar(conn, "SELECT COUNT(*) FROM deep_state WHERE status = 'deep_required'")
    videos = scalar(conn, "SELECT COUNT(*) FROM videos")
    videos_done = scalar(conn, "SELECT COUNT(*) FROM video_views WHERE status = 'done'")
    return {
        "now": now,
        "counts": {
            "students": len(students), "active": len(active_ids),
            "pending": sum(1 for s in students if s["status"] == "pending"),
            "tasks_open": len(open_tasks), "mastered_total": mastered_total,
            "possible_total": lexicon["count"] * max(len(active_ids), 1), "deep_pending": deep_pending,
            "videos": videos, "videos_done": videos_done, "videos_possible": videos * len(active_ids),
        },
        "tasks": tasks,
        "activity": activity,
        "students": [await _student_summary(conn, s, lexicon, now) for s in students],
    }


@router.get("/api/doctor/students")
async def list_students(doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    lexicon = lex.get_lexicon()
    now = now_iso()
    rows = conn.execute("SELECT * FROM students ORDER BY first_name, last_name").fetchall()
    return {"students": [await _student_summary(conn, r, lexicon, now) for r in rows], "now": now}


async def _save_photo(student_id: int, photo: UploadFile | None) -> str | None:
    if photo is None or not photo.filename:
        return None
    ext = Path(photo.filename).suffix.lower()
    if ext not in PHOTO_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Photo must be a JPG, PNG, WebP or GIF image.")
    data = await photo.read()
    if len(data) > settings.max_photo_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Photo must be under {settings.max_photo_mb:g} MB.")
    if not data:
        return None
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    name = f"{student_id}_{new_token(6)}{ext}"
    (settings.photos_dir / name).write_bytes(data)
    return name


def _remove_photo(name: str | None) -> None:
    if not name:
        return
    try:
        (settings.photos_dir / name).unlink(missing_ok=True)
    except OSError:
        pass


async def _issue_invite(conn: Connection, student: Row, doctor_name: str) -> dict:
    token = new_token(24)
    conn.execute(
        "UPDATE students SET invite_token = %s, invite_expires_at = %s, invite_sent_at = %s WHERE id = %s",
        (token, in_days(settings.invite_days), now_iso(), student["id"]),
    )
    link = invite_link(token)
    result = await mailer.send_invite(student["email"], student["first_name"], doctor_name, link)
    conn.execute("UPDATE students SET invite_email_sent = %s WHERE id = %s", (bool(result.sent), student["id"]))
    return {"link": link, "email": result.to_dict()}


@router.post("/api/doctor/students", status_code=201)
async def create_student(
    first_name: str = Form(...),
    last_name: str = Form(default=""),
    age: int = Form(...),
    gender: str = Form(...),
    email: str = Form(...),
    phone: str = Form(default=""),
    address: str = Form(default=""),
    photo: UploadFile | None = File(default=None),
    doctor: Row = Depends(require_doctor),
    conn: Connection = Depends(get_db),
) -> dict:
    first_name, last_name, email = first_name.strip(), last_name.strip(), email.strip().lower()
    gender = gender.strip().lower()
    if not first_name:
        raise HTTPException(status_code=422, detail="First name is required.")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Please enter a valid email address.")
    if not 1 <= age <= 120:
        raise HTTPException(status_code=422, detail="Age must be between 1 and 120.")
    if gender not in GENDERS:
        raise HTTPException(status_code=422, detail="Gender must be male, female or other.")
    if conn.execute("SELECT 1 FROM students WHERE email = %s", (email,)).fetchone():
        raise HTTPException(status_code=409, detail="A student with this email already exists.")

    student_id = conn.execute(
        """INSERT INTO students (first_name, last_name, age, gender, email, phone, address, created_by, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (first_name, last_name, age, gender, email, phone.strip(), address.strip(), doctor["id"], now_iso()),
    ).fetchone()["id"]
    photo_name = await _save_photo(student_id, photo)
    if photo_name:
        conn.execute("UPDATE students SET photo = %s WHERE id = %s", (photo_name, student_id))
    row = conn.execute("SELECT * FROM students WHERE id = %s", (student_id,)).fetchone()
    invite = await _issue_invite(conn, row, doctor["name"])
    row = conn.execute("SELECT * FROM students WHERE id = %s", (student_id,)).fetchone()
    return {"student": student_public(row), "invite": invite}


def _get_student(conn: Connection, student_id: int) -> Row:
    row = conn.execute("SELECT * FROM students WHERE id = %s", (student_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such student.")
    return row


@router.get("/api/doctor/students/{student_id}")
async def get_student(student_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    row = _get_student(conn, student_id)
    lexicon = lex.get_lexicon()
    now = now_iso()
    by_id = lex.by_id(lexicon)
    tasks = []
    for t in conn.execute("SELECT * FROM tasks ORDER BY due_at DESC, id DESC LIMIT 30").fetchall():
        res = conn.execute(
            "SELECT * FROM task_results WHERE task_id = %s AND student_id = %s", (t["id"], student_id)
        ).fetchone()
        tasks.append({**_task_public(t, now), "result": _result_public(res)})
    recent = [{
        "entry_id": r["entry_id"], "tamil": by_id.get(r["entry_id"], {}).get("tamil", r["entry_id"]),
        "roman": by_id.get(r["entry_id"], {}).get("roman", ""), "verdict": r["verdict"], "score": r["score"],
        "stars": r["stars"], "source": r["source"], "at": r["created_at"],
    } for r in conn.execute(
        "SELECT * FROM attempts WHERE student_id = %s ORDER BY id DESC LIMIT 20", (student_id,)
    ).fetchall()]
    videos = []
    for v in conn.execute("SELECT * FROM videos ORDER BY id DESC").fetchall():
        view = conn.execute(
            "SELECT * FROM video_views WHERE video_id = %s AND student_id = %s", (v["id"], student_id)
        ).fetchone()
        videos.append({**_video_public(v), "result": _view_public(view)})
    return {
        "student": student_public(row),
        "progress": student_progress(conn, student_id, lexicon),
        "tasks": tasks,
        "videos": videos,
        "recent": recent,
        "now": now,
    }


@router.delete("/api/doctor/students/{student_id}")
def delete_student(student_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    """Progress, attempts, task results and views go with the row (ON DELETE
    CASCADE), and the child's tokens stop working since their account is gone."""
    row = _get_student(conn, student_id)
    conn.execute("DELETE FROM students WHERE id = %s", (student_id,))
    _remove_photo(row["photo"])
    return {"ok": True, "deleted": student_id}


@router.post("/api/doctor/students/{student_id}/invite")
async def resend_invite(student_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    row = _get_student(conn, student_id)
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="This student has already set up their account.")
    invite = await _issue_invite(conn, row, doctor["name"])
    row = conn.execute("SELECT * FROM students WHERE id = %s", (student_id,)).fetchone()
    return {"student": student_public(row), "invite": invite}


@router.post("/api/doctor/students/{student_id}/photo")
async def update_photo(
    student_id: int, photo: UploadFile = File(...),
    doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db),
) -> dict:
    row = _get_student(conn, student_id)
    name = await _save_photo(student_id, photo)
    if not name:
        raise HTTPException(status_code=422, detail="The photo is empty.")
    _remove_photo(row["photo"])
    row = conn.execute("UPDATE students SET photo = %s WHERE id = %s RETURNING *", (name, student_id)).fetchone()
    return {"student": student_public(row)}


# --- tasks -----------------------------------------------------------------


class TaskCreate(BaseModel):
    kind: TaskKind
    entry_id: str | None = None
    text: str | None = Field(default=None, description="custom Tamil text when entry_id is not given")
    roman: str = ""
    meaning: str = ""
    note: str = ""
    level: TaskLevel | None = Field(default=None, description="defaults to the kind's label: words easy, short sentences medium, sentences hard")
    due_at: str = Field(description="ISO-8601 deadline; the browser sends UTC")


def _task_with_results(conn: Connection, task: Row, students: list[Row], now: str) -> dict:
    results = []
    for s in students:
        res = conn.execute(
            "SELECT * FROM task_results WHERE task_id = %s AND student_id = %s", (task["id"], s["id"])
        ).fetchone()
        results.append({
            "student_id": s["id"], "name": f"{s['first_name']} {s['last_name']}".strip(),
            "photo_url": f"/photos/{s['photo']}" if s["photo"] else None, **_result_public(res),
        })
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("done", "attempted", "pending")}
    return {**_task_public(task, now), "results": results, "counts": counts, "students": len(results)}


@router.get("/api/doctor/tasks")
def list_tasks(doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    now = now_iso()
    students = _active_students(conn)
    active = conn.execute("SELECT * FROM tasks WHERE due_at > %s ORDER BY due_at ASC, id ASC", (now,)).fetchall()
    past = conn.execute("SELECT * FROM tasks WHERE due_at <= %s ORDER BY due_at DESC, id DESC LIMIT 40", (now,)).fetchall()
    return {
        "now": now,
        "active": [_task_with_results(conn, t, students, now) for t in active],
        "past": [_task_with_results(conn, t, students, now) for t in past],
        "active_students": len(students),
        "pending_students": scalar(conn, "SELECT COUNT(*) FROM students WHERE status = 'pending'"),
    }


@router.post("/api/doctor/tasks", status_code=201)
async def create_task(body: TaskCreate, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    try:
        due = parse_iso(body.due_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="due_at must be an ISO-8601 date-time.") from exc
    if due <= utcnow():
        raise HTTPException(status_code=422, detail="The deadline must be in the future.")

    lexicon = lex.get_lexicon()
    if body.entry_id:
        entry = lex.by_id(lexicon).get(body.entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Unknown lexicon entry: {body.entry_id!r}")
        kind, entry_id = entry["cat"], entry["id"]
        tamil, roman, meaning = entry["tamil"], entry["roman"], entry["meaning"]
    else:
        tamil = (body.text or "").strip()
        if not tamil:
            raise HTTPException(status_code=422, detail="Choose an item from the list or type the Tamil text.")
        if len(tamil) > 200:
            raise HTTPException(status_code=422, detail="Custom text is too long (200 characters max).")
        kind, entry_id = body.kind, None
        roman = body.roman.strip() or lex.romanize(tamil)
        meaning = body.meaning.strip()

    level = body.level or lex.CATEGORIES[kind]["level"]
    task = conn.execute(
        """INSERT INTO tasks (doctor_id, kind, entry_id, tamil, roman, meaning, note, level, due_at, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (doctor["id"], kind, entry_id, tamil, roman, meaning, body.note.strip(), level, iso(due), now_iso()),
    ).fetchone()
    return {"task": _task_with_results(conn, task, _active_students(conn), now_iso())}


@router.get("/api/doctor/tasks/{task_id}")
def get_task(task_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    task = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail="No such task.")
    return {"task": _task_with_results(conn, task, _active_students(conn), now_iso())}


@router.delete("/api/doctor/tasks/{task_id}")
def delete_task(task_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    """Results go with the task (ON DELETE CASCADE); attempts keep their row
    with task_id set to NULL, so the child's practice history stays."""
    if conn.execute("DELETE FROM tasks WHERE id = %s RETURNING id", (task_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="No such task.")
    return {"ok": True, "deleted": task_id}


# --- video lessons ----------------------------------------------------------


def _video_with_views(conn: Connection, video: Row, students: list[Row]) -> dict:
    results = []
    for s in students:
        view = conn.execute(
            "SELECT * FROM video_views WHERE video_id = %s AND student_id = %s", (video["id"], s["id"])
        ).fetchone()
        results.append({
            "student_id": s["id"], "name": f"{s['first_name']} {s['last_name']}".strip(),
            "photo_url": f"/photos/{s['photo']}" if s["photo"] else None, **_view_public(view),
        })
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("done", "started", "new")}
    return {**_video_public(video), "results": results, "counts": counts, "students": len(results)}


def _active_students(conn: Connection) -> list[Row]:
    return conn.execute("SELECT * FROM students WHERE status = 'active' ORDER BY first_name, last_name").fetchall()


@router.get("/api/doctor/videos")
def list_videos(doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    students = _active_students(conn)
    rows = conn.execute("SELECT * FROM videos ORDER BY id DESC").fetchall()
    return {
        "now": now_iso(),
        "videos": [_video_with_views(conn, v, students) for v in rows],
        "active_students": len(students),
        "pending_students": scalar(conn, "SELECT COUNT(*) FROM students WHERE status = 'pending'"),
        "max_video_mb": settings.max_video_mb,
    }


@router.post("/api/doctor/videos", status_code=201)
async def upload_video(
    title: str = Form(...),
    description: str = Form(default=""),
    duration: float | None = Form(default=None),
    file: UploadFile = File(...),
    doctor: Row = Depends(require_doctor),
    conn: Connection = Depends(get_db),
) -> dict:
    title = title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Give the lesson a title.")
    if len(title) > 120:
        raise HTTPException(status_code=422, detail="The title is too long (120 characters max).")
    ext = Path(file.filename or "").suffix.lower()
    mime = VIDEO_TYPES.get(ext)
    if mime is None:
        raise HTTPException(status_code=422, detail="The video must be an MP4, WebM, OGV or MOV file.")

    # Stream to disk in chunks: lessons can be hundreds of megabytes.
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    name = f"{new_token(18)}{ext}"
    path = settings.videos_dir / name
    limit = int(settings.max_video_mb * 1024 * 1024)
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"The video must be under {settings.max_video_mb:g} MB.")
                out.write(chunk)
        if not size:
            raise HTTPException(status_code=422, detail="The video file is empty.")
    except Exception:
        path.unlink(missing_ok=True)
        raise

    video = conn.execute(
        """INSERT INTO videos (doctor_id, title, description, file_name, mime, size_bytes, duration, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (doctor["id"], title, description.strip()[:1000], name, mime, size,
         duration if duration and duration > 0 else None, now_iso()),
    ).fetchone()
    return {"video": _video_with_views(conn, video, _active_students(conn))}


@router.get("/api/doctor/videos/{video_id}")
def get_video(video_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    video = conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()
    if video is None:
        raise HTTPException(status_code=404, detail="No such video lesson.")
    return {"video": _video_with_views(conn, video, _active_students(conn))}


@router.delete("/api/doctor/videos/{video_id}")
def delete_video(video_id: int, doctor: Row = Depends(require_doctor), conn: Connection = Depends(get_db)) -> dict:
    video = conn.execute("DELETE FROM videos WHERE id = %s RETURNING *", (video_id,)).fetchone()
    if video is None:
        raise HTTPException(status_code=404, detail="No such video lesson.")
    try:
        (settings.videos_dir / video["file_name"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "deleted": video_id}


# ---------------------------------------------------------------------------
# static
# ---------------------------------------------------------------------------


@router.get("/videos/{name}")
def video_file(name: str, t: str | None = None, conn: Connection = Depends(get_db)) -> FileResponse:
    """The lesson file. A <video> tag cannot send a bearer header, so the
    token travels as ?t=; FileResponse honours Range for seeking."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=404)
    if _token_subject(conn, t) is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    video = conn.execute("SELECT * FROM videos WHERE file_name = %s", (name,)).fetchone()
    path = settings.videos_dir / name
    if video is None or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=video["mime"], headers={"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"})


@router.get("/photos/{name}")
def photo(name: str) -> FileResponse:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=404)
    path = settings.photos_dir / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})

