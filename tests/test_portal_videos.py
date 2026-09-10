"""Video lessons: the doctor uploads and deletes, every student sees them,
and watching is tracked per student."""

from __future__ import annotations

import pytest

from tests.conftest import activate_student, add_student


@pytest.fixture
def client(portal_client):
    return portal_client

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000


def upload(client, doctor, title="Vowels lesson", data=MP4, name="lesson.mp4", **fields):
    return client.post(
        "/api/doctor/videos", headers=doctor,
        data={"title": title, "description": "Watch and repeat", **fields},
        files={"file": (name, data, "video/mp4")},
    )


def test_doctor_uploads_and_lists_a_video(client, doctor):
    res = upload(client, doctor, duration="42.5")
    assert res.status_code == 201, res.text
    v = res.json()["video"]
    assert v["title"] == "Vowels lesson"
    assert v["description"] == "Watch and repeat"
    assert v["mime"] == "video/mp4"
    assert v["size_bytes"] == len(MP4)
    assert v["duration"] == 42.5
    assert v["url"].startswith("/videos/") and v["url"].endswith(".mp4")
    assert v["counts"] == {"done": 0, "started": 0, "new": 0}

    listed = client.get("/api/doctor/videos", headers=doctor).json()
    assert [x["id"] for x in listed["videos"]] == [v["id"]]
    assert listed["max_video_mb"] > 0


def test_upload_validation(client, doctor):
    assert upload(client, doctor, title="   ").status_code == 422
    assert upload(client, doctor, name="notes.txt").status_code == 422
    assert upload(client, doctor, data=b"").status_code == 422
    assert client.post("/api/doctor/videos", data={"title": "x"}).status_code == 401


def test_upload_size_limit_removes_the_partial_file(client, doctor):
    from src.config import settings

    saved = settings.max_video_mb
    object.__setattr__(settings, "max_video_mb", 0.001)   # ~1 KB
    try:
        res = upload(client, doctor, data=b"\x00" * 5000)
    finally:
        object.__setattr__(settings, "max_video_mb", saved)
    assert res.status_code == 413
    assert not list(settings.videos_dir.glob("*.mp4"))


def test_video_file_needs_a_valid_session_and_supports_ranges(client, doctor, student):
    headers, _ = student
    url = upload(client, doctor).json()["video"]["url"]
    assert client.get(url).status_code == 401
    assert client.get(url, params={"t": "nope"}).status_code == 401

    token = headers["Authorization"].split()[1]
    full = client.get(url, params={"t": token})
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("video/mp4")
    assert full.content == MP4

    part = client.get(url, params={"t": token}, headers={"Range": "bytes=0-9"})
    assert part.status_code == 206
    assert part.content == MP4[:10]

    doc_token = doctor["Authorization"].split()[1]
    assert client.get(url, params={"t": doc_token}).status_code == 200
    assert client.get("/videos/does-not-exist.mp4", params={"t": token}).status_code == 404


def test_student_sees_every_video_as_new(client, doctor, student):
    headers, _ = student
    a = upload(client, doctor, title="A").json()["video"]
    b = upload(client, doctor, title="B").json()["video"]
    res = client.get("/api/student/videos", headers=headers).json()
    assert [v["id"] for v in res["videos"]] == [b["id"], a["id"]]   # newest first
    assert all(v["my"] == {"status": "new", "position": 0, "watched_pct": 0, "started_at": None, "completed_at": None}
               for v in res["videos"])
    assert client.get("/api/student/videos").status_code == 401


def test_watching_is_tracked_and_completes_at_ninety_percent(client, doctor, student):
    headers, s = student
    v = upload(client, doctor, duration="100").json()["video"]

    r = client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 30, "duration": 100})
    assert r.status_code == 200, r.text
    assert r.json()["my"]["status"] == "started"
    assert r.json()["my"]["watched_pct"] == 30

    # Seeking backwards never lowers the furthest point reached.
    r = client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 10, "duration": 100})
    assert r.json()["my"]["position"] == 30
    assert r.json()["my"]["watched_pct"] == 30

    r = client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 91, "duration": 100})
    my = r.json()["my"]
    assert my["status"] == "done" and my["watched_pct"] == 91 and my["completed_at"]

    listed = client.get("/api/doctor/videos", headers=doctor).json()["videos"][0]
    assert listed["counts"] == {"done": 1, "started": 0, "new": 0}
    assert listed["results"][0]["student_id"] == s["id"]
    assert listed["results"][0]["status"] == "done"

    detail = client.get(f"/api/doctor/students/{s['id']}", headers=doctor).json()
    assert detail["videos"][0]["result"]["status"] == "done"


def test_ended_marks_done_even_without_a_known_duration(client, doctor, student):
    headers, _ = student
    v = upload(client, doctor).json()["video"]
    assert v["duration"] is None
    r = client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 12.5, "ended": True})
    assert r.json()["my"] == {**r.json()["my"], "status": "done", "watched_pct": 100}
    # The player reports the real length on first play; it is remembered.
    r = client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 1, "duration": 20})
    assert r.json()["video"]["duration"] == 20
    assert r.json()["my"]["status"] == "done"   # done stays done


def test_counts_cover_every_active_student(client, doctor):
    a = add_student(client, doctor, email="a@example.com").json()
    b = add_student(client, doctor, email="b@example.com").json()
    add_student(client, doctor, email="pending@example.com")   # never activates
    ha = activate_student(client, a["invite"]["link"], username="anu")
    hb = activate_student(client, b["invite"]["link"], username="bala")
    v = upload(client, doctor, duration="60").json()["video"]
    client.post(f"/api/student/videos/{v['id']}/progress", headers=ha, json={"position": 60, "ended": True})
    client.post(f"/api/student/videos/{v['id']}/progress", headers=hb, json={"position": 5, "duration": 60})

    res = client.get("/api/doctor/videos", headers=doctor).json()
    assert res["active_students"] == 2 and res["pending_students"] == 1
    video = res["videos"][0]
    assert video["students"] == 2
    assert video["counts"] == {"done": 1, "started": 1, "new": 0}
    assert sorted(r["status"] for r in video["results"]) == ["done", "started"]

    overview = client.get("/api/doctor/overview", headers=doctor).json()["counts"]
    assert overview["videos"] == 1 and overview["videos_done"] == 1 and overview["videos_possible"] == 2


def test_delete_removes_file_views_and_student_listing(client, doctor, student):
    from src.config import settings

    headers, _ = student
    v = upload(client, doctor).json()["video"]
    path = settings.videos_dir / v["url"].rsplit("/", 1)[-1]
    assert path.is_file()
    client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 1, "ended": True})

    res = client.delete(f"/api/doctor/videos/{v['id']}", headers=doctor)
    assert res.status_code == 200
    assert not path.exists()
    assert client.get("/api/doctor/videos", headers=doctor).json()["videos"] == []
    assert client.get("/api/student/videos", headers=headers).json()["videos"] == []
    assert client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 1}).status_code == 404
    assert client.delete(f"/api/doctor/videos/{v['id']}", headers=doctor).status_code == 404
    token = headers["Authorization"].split()[1]
    assert client.get(v["url"], params={"t": token}).status_code == 404


def test_deleting_a_student_drops_their_views(client, doctor, student):
    headers, s = student
    v = upload(client, doctor).json()["video"]
    client.post(f"/api/student/videos/{v['id']}/progress", headers=headers, json={"position": 1, "ended": True})
    assert client.get("/api/doctor/videos", headers=doctor).json()["videos"][0]["counts"]["done"] == 1
    client.delete(f"/api/doctor/students/{s['id']}", headers=doctor)
    video = client.get("/api/doctor/videos", headers=doctor).json()["videos"][0]
    assert video["students"] == 0 and video["counts"]["done"] == 0


@pytest.mark.parametrize("name,mime", [("a.webm", "video/webm"), ("b.mov", "video/quicktime"), ("c.M4V", "video/mp4")])
def test_accepted_formats(client, doctor, name, mime):
    res = upload(client, doctor, name=name)
    assert res.status_code == 201
    assert res.json()["video"]["mime"] == mime
