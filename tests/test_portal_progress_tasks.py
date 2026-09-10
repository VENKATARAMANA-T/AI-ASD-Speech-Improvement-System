"""Progress sync from the child portal, what the doctor sees, and daily tasks."""

from __future__ import annotations

import pytest

from datetime import datetime, timedelta, timezone

from tests.conftest import add_student


@pytest.fixture
def client(portal_client):
    return portal_client


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _attempt(client, headers, entry_id, verdict, score, category="words", source="training"):
    return client.post("/api/student/attempts", headers=headers,
                       json={"entry_id": entry_id, "category": category, "verdict": verdict,
                             "score_percent": score, "source": source})


# --- progress ---------------------------------------------------------------


def test_attempts_keep_the_best_and_count_tries(client, student):
    headers, _ = student
    item = _attempt(client, headers, "w_amma", "incorrect", 30).json()["item"]
    assert item["best"] == 1 and item["bestScore"] == 30 and item["attempts"] == 1 and item["last"] == "incorrect"
    assert item["at"].endswith("Z")
    item = _attempt(client, headers, "w_amma", "correct", 100).json()["item"]
    assert item["best"] == 3 and item["bestScore"] == 100 and item["attempts"] == 2 and item["last"] == "correct"
    item = _attempt(client, headers, "w_amma", "close", 70).json()["item"]
    assert item["best"] == 3 and item["bestScore"] == 100 and item["attempts"] == 3 and item["last"] == "close"

    assert _attempt(client, headers, "w_amma", "weird", 10).status_code == 422
    assert client.post("/api/student/attempts", json={"entry_id": "w_amma", "verdict": "correct"}).status_code == 401


def test_arcade_attempts_count_towards_progress(client, student):
    """A word said correctly in a game is progress on that word, like training."""
    headers, _ = student
    res = _attempt(client, headers, "w_poo", "correct", 100, source="arcade")
    assert res.status_code == 200
    assert res.json()["item"]["best"] == 3
    assert _attempt(client, headers, "w_poo", "correct", 100, source="minecraft").status_code == 422


def test_deep_state_round_trip(client, student):
    headers, _ = student
    res = client.put("/api/student/deep/w_veedu", headers=headers, json={"status": "deep_required", "wrong": 3})
    assert res.status_code == 200
    prog = client.get("/api/student/progress", headers=headers).json()
    assert prog["deep"]["w_veedu"]["status"] == "deep_required"
    assert prog["deep"]["w_veedu"]["wrong"] == 3
    client.put("/api/student/deep/w_veedu", headers=headers, json={"status": "deep_done", "wrong": 0})
    assert client.get("/api/student/progress", headers=headers).json()["deep"]["w_veedu"]["status"] == "deep_done"


def test_bulk_sync_merges_browser_progress_best_of(client, student):
    headers, _ = student
    _attempt(client, headers, "w_amma", "close", 70)
    res = client.post("/api/student/progress/sync", headers=headers, json={
        "items": {
            "w_amma": {"best": 3, "bestScore": 100, "attempts": 5, "last": "correct"},   # server has attempts: keep 1
            "v_a": {"best": 2, "bestScore": 60, "attempts": 2, "last": "close", "category": "vowels"},
        },
        "deep": {"w_poo": {"status": "deep_required", "wrong": 3}},
    })
    assert res.status_code == 200
    items = res.json()["items"]
    assert items["w_amma"]["best"] == 3 and items["w_amma"]["bestScore"] == 100 and items["w_amma"]["attempts"] == 1
    assert items["v_a"]["best"] == 2 and items["v_a"]["attempts"] == 2
    assert res.json()["deep"]["w_poo"]["status"] == "deep_required"


def test_doctor_sees_progress_by_category_and_deep_queue(client, doctor, student):
    headers, s = student
    _attempt(client, headers, "v_a", "correct", 100, category="vowels")
    _attempt(client, headers, "v_aa", "close", 70, category="vowels")
    _attempt(client, headers, "w_amma", "correct", 95)
    client.put("/api/student/deep/w_veedu", headers=headers, json={"status": "deep_required", "wrong": 3})
    client.put("/api/student/deep/w_poo", headers=headers, json={"status": "deep_done", "wrong": 0})

    body = client.get(f"/api/doctor/students/{s['id']}", headers=doctor).json()
    assert body["student"]["name"] == "Ravi Kumar"
    prog = body["progress"]
    cats = {c["key"]: c for c in prog["categories"]}
    assert cats["vowels"]["total"] == 12 and cats["vowels"]["mastered"] == 1 and cats["vowels"]["tried"] == 2
    assert cats["words"]["mastered"] == 1
    assert cats["sentences"]["mastered"] == 0 and cats["long_sentences"]["total"] == 10
    v_aa = next(i for i in cats["vowels"]["items"] if i["id"] == "v_aa")
    assert v_aa["best_stars"] == 2 and v_aa["best_score"] == 70 and v_aa["attempts"] == 1
    assert prog["totals"]["mastered"] == 2 and prog["totals"]["attempts"] == 3 and prog["totals"]["stars"] == 8
    assert [d["id"] for d in prog["deep"]["pending"]] == ["w_veedu"]
    assert [d["id"] for d in prog["deep"]["done"]] == ["w_poo"]
    veedu = next(i for i in cats["words"]["items"] if i["id"] == "w_veedu")
    assert veedu["deep_status"] == "deep_required"
    assert body["recent"][0]["entry_id"] == "w_amma" and body["recent"][0]["tamil"] == "அம்மா"

    summary = client.get("/api/doctor/students", headers=doctor).json()["students"][0]["summary"]
    assert summary["mastered"] == 2 and summary["deep_pending"] == 1 and summary["attempts"] == 3


def test_overview(client, doctor, student):
    headers, _ = student
    add_student(client, doctor, email="pending@example.com", first_name="Pending")
    _attempt(client, headers, "w_amma", "correct", 100)
    body = client.get("/api/doctor/overview", headers=doctor).json()
    assert body["counts"]["students"] == 2 and body["counts"]["active"] == 1 and body["counts"]["pending"] == 1
    assert body["counts"]["mastered_total"] == 1
    assert body["activity"][0]["student"] == "Ravi Kumar" and body["activity"][0]["tamil"] == "அம்மா"


# --- tasks ------------------------------------------------------------------


def _create_task(client, doctor, **over):
    payload = {"kind": "words", "entry_id": "w_amma", "due_at": _iso(datetime.now(timezone.utc) + timedelta(hours=3))}
    payload.update(over)
    return client.post("/api/doctor/tasks", headers=doctor, json=payload)


def test_create_task_from_lexicon(client, doctor, student):
    res = _create_task(client, doctor, note="Say it three times")
    assert res.status_code == 201, res.text
    t = res.json()["task"]
    assert t["tamil"] == "அம்மா" and t["roman"] == "amma" and t["meaning"] == "mother"
    assert t["kind"] == "words" and t["kind_name"] == "Word" and t["expired"] is False
    assert t["students"] == 1 and t["counts"] == {"done": 0, "attempted": 0, "pending": 1}
    assert t["results"][0]["name"] == "Ravi Kumar" and t["results"][0]["status"] == "pending"


def test_create_custom_task(client, doctor):
    res = _create_task(client, doctor, entry_id=None, kind="sentences", text="நல்ல நாள்", roman="nalla naal", meaning="good day")
    assert res.status_code == 201, res.text
    t = res.json()["task"]
    assert t["entry_id"] is None and t["tamil"] == "நல்ல நாள்" and t["roman"] == "nalla naal"
    # romanised in-process when not supplied
    res = _create_task(client, doctor, entry_id=None, kind="words", text="பூ")
    assert res.status_code == 201 and res.json()["task"]["roman"] == "poo"


def test_task_level_defaults_from_the_kind_and_can_be_chosen(client, doctor, student):
    headers, _ = student
    assert _create_task(client, doctor).json()["task"]["level"] == "easy"                       # words
    assert _create_task(client, doctor, entry_id=None, kind="sentences", text="நல்ல நாள்").json()["task"]["level"] == "medium"
    t = _create_task(client, doctor, entry_id=None, kind="long_sentences", text="நான் பள்ளிக்கு போகிறேன்").json()["task"]
    assert t["level"] == "hard" and t["level_name"] == "Hard"
    # The doctor may override the label.
    t = _create_task(client, doctor, level="hard").json()["task"]
    assert t["level"] == "hard"
    assert _create_task(client, doctor, level="impossible").status_code == 422
    # Students and the list carry it too.
    assert {x["level"] for x in client.get("/api/student/tasks", headers=headers).json()["tasks"]} == {"easy", "medium", "hard"}
    assert client.get("/api/doctor/tasks", headers=doctor).json()["active"][0]["level_name"] in ("Easy", "Medium", "Hard")


def test_calendar_lists_every_task_with_the_students_result(client, doctor, student):
    headers, _ = student
    assert client.get("/api/student/calendar", headers=headers).json()["tasks"] == []
    a = _create_task(client, doctor).json()["task"]
    b = _create_task(client, doctor, entry_id=None, kind="words", text="பூ",
                     due_at=_iso(datetime.now(timezone.utc) + timedelta(days=2))).json()["task"]
    client.post(f"/api/student/tasks/{a['id']}/attempts", headers=headers, json={"verdict": "correct", "score_percent": 100})

    cal = client.get("/api/student/calendar", headers=headers).json()
    assert [t["id"] for t in cal["tasks"]] == [a["id"], b["id"]]          # by due date
    assert cal["tasks"][0]["status"] == "done" and cal["tasks"][0]["completed_at"]
    assert cal["tasks"][1]["status"] == "pending" and cal["tasks"][1]["expired"] is False
    assert cal["now"] and client.get("/api/student/calendar").status_code == 401


def test_level_column_is_added_to_an_old_database():
    """A tasks table created before the level column existed gains it on start-up."""
    from src.portal.db import connect, init_db
    from tests.conftest import reset_database

    reset_database()
    with connect() as conn:
        conn.execute("CREATE TABLE tasks (id SERIAL PRIMARY KEY, kind TEXT, tamil TEXT, due_at TEXT, created_at TEXT)")
        conn.execute("INSERT INTO tasks (kind, tamil, due_at, created_at) VALUES ('words', 'அம்மா', '2030-01-01T00:00:00Z', '2020-01-01T00:00:00Z')")
        conn.commit()
    init_db()
    with connect() as conn:
        assert conn.execute("SELECT level FROM tasks").fetchone() == {"level": ""}


def test_task_validation(client, doctor):
    assert _create_task(client, doctor, due_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=1))).status_code == 422
    assert _create_task(client, doctor, due_at="not a date").status_code == 422
    assert _create_task(client, doctor, entry_id="nope").status_code == 404
    assert _create_task(client, doctor, entry_id=None, text="  ").status_code == 422
    assert _create_task(client, doctor, kind="haiku").status_code == 422


def test_students_see_open_tasks_and_finish_them(client, doctor, student):
    headers, _ = student
    tid = _create_task(client, doctor).json()["task"]["id"]

    body = client.get("/api/student/tasks", headers=headers).json()
    assert body["now"].endswith("Z")
    assert [t["id"] for t in body["tasks"]] == [tid]
    assert body["tasks"][0]["my"]["status"] == "pending"

    res = client.post(f"/api/student/tasks/{tid}/attempts", headers=headers, json={"verdict": "incorrect", "score_percent": 20})
    assert res.status_code == 200
    assert res.json()["my"] == {"status": "attempted", "best_verdict": "incorrect", "best_score": 20, "attempts": 1, "completed_at": None}

    res = client.post(f"/api/student/tasks/{tid}/attempts", headers=headers, json={"verdict": "close", "score_percent": 70})
    my = res.json()["my"]
    assert my["status"] == "done" and my["best_verdict"] == "close" and my["attempts"] == 2 and my["completed_at"]

    # a later perfect attempt improves the record but keeps the first completion time
    res = client.post(f"/api/student/tasks/{tid}/attempts", headers=headers, json={"verdict": "correct", "score_percent": 100})
    assert res.json()["my"]["best_verdict"] == "correct" and res.json()["my"]["completed_at"] == my["completed_at"]

    # a task on a lexicon entry also feeds training progress
    assert client.get("/api/student/progress", headers=headers).json()["items"]["w_amma"]["best"] == 3

    # and the doctor sees the completion
    task = client.get(f"/api/doctor/tasks/{tid}", headers=doctor).json()["task"]
    assert task["counts"] == {"done": 1, "attempted": 0, "pending": 0}
    assert task["results"][0]["status"] == "done" and task["results"][0]["attempts"] == 3
    listing = client.get("/api/doctor/tasks", headers=doctor).json()
    assert [t["id"] for t in listing["active"]] == [tid] and listing["past"] == []


def test_expired_tasks_are_closed(client, doctor, student, monkeypatch):
    headers, _ = student
    tid = _create_task(client, doctor).json()["task"]["id"]
    # move the clock forward for the checks that compare against "now"
    from src.portal import api
    future = _iso(datetime.now(timezone.utc) + timedelta(hours=4))
    monkeypatch.setattr(api, "now_iso", lambda: future)

    res = client.post(f"/api/student/tasks/{tid}/attempts", headers=headers, json={"verdict": "correct", "score_percent": 100})
    assert res.status_code == 409

    body = client.get("/api/student/tasks", headers=headers).json()
    assert body["tasks"][0]["expired"] is True and body["tasks"][0]["my"]["status"] == "pending"

    listing = client.get("/api/doctor/tasks", headers=doctor).json()
    assert listing["active"] == [] and [t["id"] for t in listing["past"]] == [tid]


def test_delete_task(client, doctor, student):
    headers, _ = student
    tid = _create_task(client, doctor).json()["task"]["id"]
    client.post(f"/api/student/tasks/{tid}/attempts", headers=headers, json={"verdict": "correct", "score_percent": 100})
    assert client.delete(f"/api/doctor/tasks/{tid}", headers=doctor).status_code == 200
    assert client.delete(f"/api/doctor/tasks/{tid}", headers=doctor).status_code == 404
    assert client.get("/api/student/tasks", headers=headers).json()["tasks"] == []
    assert client.post(f"/api/student/tasks/{tid}/attempts", headers=headers, json={"verdict": "correct"}).status_code == 404
