"""Adding, listing, inviting, activating and deleting students."""

from __future__ import annotations

import pytest

import io

from tests.conftest import activate_student, add_student


@pytest.fixture
def client(portal_client):
    return portal_client


def test_add_student_returns_profile_and_invite(client, doctor):
    res = add_student(client, doctor)
    assert res.status_code == 201, res.text
    body = res.json()
    s = body["student"]
    assert s["name"] == "Ravi Kumar"
    assert s["age"] == 7 and s["gender"] == "male"
    assert s["email"] == "ravi@example.com"
    assert s["status"] == "pending"
    assert s["photo_url"] is None
    assert s["invite"]["link"].startswith("http://testserver/#/activate/")
    # No SMTP in tests: the link is returned so the doctor can share it by hand.
    assert body["invite"]["email"]["sent"] is False
    assert "not configured" in body["invite"]["email"]["error"]
    assert body["invite"]["link"] == s["invite"]["link"]


def test_email_must_be_unique_case_insensitively(client, doctor):
    assert add_student(client, doctor).status_code == 201
    res = add_student(client, doctor, email="RAVI@example.com", first_name="Other")
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_validation(client, doctor):
    assert add_student(client, doctor, email="not-an-email").status_code == 422
    assert add_student(client, doctor, first_name="  ").status_code == 422
    assert add_student(client, doctor, age="0").status_code == 422
    assert add_student(client, doctor, age="abc").status_code == 422
    assert add_student(client, doctor, gender="dragon").status_code == 422


def test_photo_upload_and_serving(client, doctor):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    res = client.post("/api/doctor/students", headers=doctor,
                      data={"first_name": "Mala", "age": "6", "gender": "female", "email": "mala@example.com"},
                      files={"photo": ("mala.png", io.BytesIO(png), "image/png")})
    assert res.status_code == 201, res.text
    url = res.json()["student"]["photo_url"]
    assert url.startswith("/photos/1_")
    assert client.get(url).content == png

    res = client.post("/api/doctor/students", headers=doctor,
                      data={"first_name": "X", "age": "6", "gender": "other", "email": "x@example.com"},
                      files={"photo": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert res.status_code == 422


def test_change_photo(client, doctor):
    sid = add_student(client, doctor).json()["student"]["id"]
    res = client.post(f"/api/doctor/students/{sid}/photo", headers=doctor,
                      files={"photo": ("p.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 10), "image/jpeg")})
    assert res.status_code == 200
    assert res.json()["student"]["photo_url"].endswith(".jpg")


def test_list_students_with_summary(client, doctor):
    add_student(client, doctor)
    add_student(client, doctor, email="b@example.com", first_name="Anbu")
    body = client.get("/api/doctor/students", headers=doctor).json()
    names = [s["name"] for s in body["students"]]
    assert names == ["Anbu Kumar", "Ravi Kumar"]
    s = body["students"][0]["summary"]
    assert s["total"] == 52 and s["mastered"] == 0 and s["deep_pending"] == 0


def test_invite_flow(client, doctor):
    link = add_student(client, doctor).json()["invite"]["link"]
    token = link.rsplit("/", 1)[-1]

    info = client.get(f"/api/invites/{token}").json()
    assert info["valid"] is True and info["email"] == "ravi@example.com" and info["first_name"] == "Ravi"

    # mismatched passwords, short passwords and bad usernames are refused
    bad = {"username": "ravi", "password": "abcdef", "confirm_password": "abcdeg"}
    assert client.post(f"/api/invites/{token}/activate", json=bad).status_code == 422
    bad = {"username": "ravi", "password": "abc", "confirm_password": "abc"}
    assert client.post(f"/api/invites/{token}/activate", json=bad).status_code == 422
    bad = {"username": "r!", "password": "abcdef", "confirm_password": "abcdef"}
    assert client.post(f"/api/invites/{token}/activate", json=bad).status_code == 422

    res = client.post(f"/api/invites/{token}/activate",
                      json={"username": "ravi", "password": "ravi-pass", "confirm_password": "ravi-pass"})
    assert res.status_code == 200
    body = res.json()
    assert body["token"] and body["student"]["status"] == "active" and body["student"]["username"] == "ravi"
    assert body["student"]["invite"] is None

    # the link is single-use
    assert client.get(f"/api/invites/{token}").status_code == 404
    assert client.post(f"/api/invites/{token}/activate",
                       json={"username": "ravi2", "password": "ravi-pass", "confirm_password": "ravi-pass"}).status_code == 404

    # login by username and by email
    for ident in ("ravi", "ravi@example.com", "RAVI@EXAMPLE.COM"):
        res = client.post("/api/auth/student/login", json={"identifier": ident, "password": "ravi-pass"})
        assert res.status_code == 200, ident
    assert client.post("/api/auth/student/login", json={"identifier": "ravi", "password": "wrong"}).status_code == 401


def test_username_can_be_the_email_and_must_be_unique(client, doctor):
    link1 = add_student(client, doctor).json()["invite"]["link"]
    link2 = add_student(client, doctor, email="b@example.com").json()["invite"]["link"]
    activate_student(client, link1, username="ravi@example.com")
    token2 = link2.rsplit("/", 1)[-1]
    res = client.post(f"/api/invites/{token2}/activate",
                      json={"username": "ravi@example.com", "password": "abcdef", "confirm_password": "abcdef"})
    assert res.status_code == 409
    res = client.post(f"/api/invites/{token2}/activate",
                      json={"username": "RAVI", "password": "abcdef", "confirm_password": "abcdef"})
    assert res.status_code == 200


def test_pending_student_cannot_log_in(client, doctor):
    add_student(client, doctor)
    res = client.post("/api/auth/student/login", json={"identifier": "ravi@example.com", "password": "anything"})
    assert res.status_code == 401


def test_unknown_invite(client):
    assert client.get("/api/invites/nope").status_code == 404


def test_resend_invite_rotates_the_token(client, doctor):
    created = add_student(client, doctor).json()
    sid, old = created["student"]["id"], created["invite"]["link"]
    res = client.post(f"/api/doctor/students/{sid}/invite", headers=doctor)
    assert res.status_code == 200
    new = res.json()["invite"]["link"]
    assert new != old
    assert client.get(f"/api/invites/{old.rsplit('/', 1)[-1]}").status_code == 404
    assert client.get(f"/api/invites/{new.rsplit('/', 1)[-1]}").json()["valid"] is True

    activate_student(client, new)
    assert client.post(f"/api/doctor/students/{sid}/invite", headers=doctor).status_code == 409


def test_delete_student_removes_everything(client, doctor, student):
    headers, s = student
    client.post("/api/student/attempts", headers=headers,
                json={"entry_id": "w_amma", "category": "words", "verdict": "correct", "score_percent": 100})
    res = client.delete(f"/api/doctor/students/{s['id']}", headers=doctor)
    assert res.status_code == 200
    assert client.get(f"/api/doctor/students/{s['id']}", headers=doctor).status_code == 404
    assert client.get("/api/student/me", headers=headers).status_code == 401
    assert client.get("/api/doctor/students", headers=doctor).json()["students"] == []
    # the email is free again
    assert add_student(client, doctor).status_code == 201


def test_delete_unknown_student(client, doctor):
    assert client.delete("/api/doctor/students/999", headers=doctor).status_code == 404
