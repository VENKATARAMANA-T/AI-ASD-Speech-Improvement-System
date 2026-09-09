"""Doctor login, sessions and password changes."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(portal_client):
    return portal_client


def test_health_reports_the_portal_settings(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["email_configured"] is False
    assert body["public_url"] == "http://testserver"


def test_first_doctor_is_seeded_and_can_log_in(client):
    res = client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "doctor-pass"})
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["doctor"] == {"id": 1, "name": "Dr. Test", "email": "doc@test.local"}
    assert "password_hash" not in body["doctor"]


def test_doctor_login_is_case_insensitive_on_email(client):
    res = client.post("/api/auth/doctor/login", json={"email": "DOC@test.local", "password": "doctor-pass"})
    assert res.status_code == 200


def test_wrong_password_is_rejected(client):
    res = client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "nope"})
    assert res.status_code == 401


def test_doctor_endpoints_need_a_token(client):
    assert client.get("/api/doctor/students").status_code == 401
    assert client.get("/api/doctor/students", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_me_and_logout(client, doctor):
    assert client.get("/api/doctor/me", headers=doctor).json()["doctor"]["email"] == "doc@test.local"
    assert client.post("/api/auth/logout", headers=doctor).status_code == 200
    assert client.get("/api/doctor/me", headers=doctor).status_code == 401


def test_change_password(client, doctor):
    res = client.post("/api/doctor/password", headers=doctor,
                      json={"current_password": "wrong", "new_password": "new-pass-1"})
    assert res.status_code == 403
    res = client.post("/api/doctor/password", headers=doctor,
                      json={"current_password": "doctor-pass", "new_password": "short"})
    assert res.status_code == 422
    res = client.post("/api/doctor/password", headers=doctor,
                      json={"current_password": "doctor-pass", "new_password": "new-pass-1"})
    assert res.status_code == 200
    assert client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "new-pass-1"}).status_code == 200
    assert client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "doctor-pass"}).status_code == 401


def test_a_student_token_does_not_open_doctor_endpoints(client, student):
    headers, _ = student
    assert client.get("/api/doctor/students", headers=headers).status_code == 401


# --- JWT ----------------------------------------------------------------------


def _claims(headers) -> dict:
    import jwt

    return jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})


def test_tokens_are_signed_jwts_with_role_and_expiry(client, doctor, student):
    headers, s = student
    doc, kid = _claims(doctor), _claims(headers)
    assert doc["role"] == "doctor" and doc["sub"] == "1"
    assert kid["role"] == "student" and kid["sub"] == str(s["id"])
    for c in (doc, kid):
        assert c["jti"] and c["ver"] == 0
        assert 6.9 * 86_400 < c["exp"] - c["iat"] <= 7 * 86_400   # SESSION_DAYS


def test_a_forged_or_tampered_token_is_rejected(client, doctor):
    import jwt

    claims = _claims(doctor)
    forged = jwt.encode(claims, "some-other-secret", algorithm="HS256")
    assert client.get("/api/doctor/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    unsigned = jwt.encode(claims, None, algorithm="none")
    assert client.get("/api/doctor/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401
    assert client.get("/api/doctor/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    assert client.get("/videos/anything.mp4?t=not.a.jwt").status_code == 401


def test_an_expired_token_is_rejected(client, doctor):
    import time

    import jwt

    from src.portal.security import jwt_secret

    claims = {**_claims(doctor), "iat": int(time.time()) - 20 * 86_400, "exp": int(time.time()) - 13 * 86_400}
    stale = jwt.encode(claims, jwt_secret(), algorithm="HS256")
    assert client.get("/api/doctor/me", headers={"Authorization": f"Bearer {stale}"}).status_code == 401


def test_changing_the_password_retires_older_tokens(client, doctor):
    other_device = client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "doctor-pass"}).json()["token"]
    res = client.post("/api/doctor/password", headers=doctor,
                      json={"current_password": "doctor-pass", "new_password": "new-pass-1"})
    assert res.status_code == 200
    fresh = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get("/api/doctor/me", headers=doctor).status_code == 401            # the token used to change it
    assert client.get("/api/doctor/me", headers={"Authorization": f"Bearer {other_device}"}).status_code == 401
    assert client.get("/api/doctor/me", headers=fresh).status_code == 200              # the one handed back
    assert _claims(fresh)["ver"] == 1


def test_logout_only_retires_that_token(client):
    a = client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "doctor-pass"}).json()["token"]
    b = client.post("/api/auth/doctor/login", json={"email": "doc@test.local", "password": "doctor-pass"}).json()["token"]
    assert a != b
    assert client.post("/api/auth/logout", headers={"Authorization": f"Bearer {a}"}).status_code == 200
    assert client.get("/api/doctor/me", headers={"Authorization": f"Bearer {a}"}).status_code == 401
    assert client.get("/api/doctor/me", headers={"Authorization": f"Bearer {b}"}).status_code == 200
    # logging out twice, or with no token at all, is harmless
    assert client.post("/api/auth/logout", headers={"Authorization": f"Bearer {a}"}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 200


def test_a_deleted_student_cannot_use_an_old_token(client, doctor, student):
    headers, s = student
    assert client.get("/api/student/me", headers=headers).status_code == 200
    assert client.delete(f"/api/doctor/students/{s['id']}", headers=doctor).status_code == 200
    assert client.get("/api/student/me", headers=headers).status_code == 401


def test_lexicon_is_grouped_with_category_keys(client):
    body = client.get("/api/lexicon").json()
    assert body["count"] == 52
    assert len(body["vowels"]) == 12
    assert body["words"][0]["cat"] == "words"
    assert [c["key"] for c in body["categories"]] == ["vowels", "words", "sentences", "long_sentences"]


def test_role_login_and_whoami(client, student):
    headers, s = student
    res = client.post("/api/auth/login", json={"role": "doctor", "identifier": "doc@test.local", "password": "doctor-pass"})
    assert res.status_code == 200 and res.json()["role"] == "doctor" and res.json()["doctor"]["email"] == "doc@test.local"
    doc = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get("/api/auth/me", headers=doc).json()["role"] == "doctor"

    res = client.post("/api/auth/login", json={"role": "child", "identifier": "ravi", "password": "ravi-pass"})
    assert res.status_code == 200 and res.json()["role"] == "child" and res.json()["student"]["id"] == s["id"]
    assert client.get("/api/auth/me", headers=headers).json() | {} == client.get("/api/auth/me", headers=headers).json()
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "child"

    # the role decides which accounts are searched: a doctor's password never opens the child app
    assert client.post("/api/auth/login", json={"role": "child", "identifier": "doc@test.local", "password": "doctor-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"role": "doctor", "identifier": "ravi", "password": "ravi-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"role": "parent", "identifier": "x", "password": "y"}).status_code == 422
    assert client.get("/api/auth/me").status_code == 401


def test_rbac_each_role_is_kept_out_of_the_other_api(client, doctor, student):
    headers, s = student
    # a child token on doctor endpoints
    for path in ("/api/doctor/me", "/api/doctor/students", "/api/doctor/tasks", "/api/doctor/videos", "/api/doctor/overview"):
        assert client.get(path, headers=headers).status_code == 401, path
    assert client.delete(f"/api/doctor/students/{s['id']}", headers=headers).status_code == 401
    # a doctor token on child endpoints
    for path in ("/api/student/me", "/api/student/progress", "/api/student/tasks", "/api/student/videos", "/api/student/calendar"):
        assert client.get(path, headers=doctor).status_code == 401, path
    assert client.post("/api/student/attempts", headers=doctor, json={"entry_id": "w_amma", "verdict": "correct"}).status_code == 401
