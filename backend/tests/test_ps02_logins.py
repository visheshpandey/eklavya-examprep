"""Two logins: student accounts see only their own data; teacher accounts see the class; nobody can make themselves a teacher."""
import pytest
from fastapi.testclient import TestClient

from app import accounts, db
from app.config import settings
from app.main import create_app
from app.ps02 import logins, reseed, seed, service

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def on(monkeypatch):
    object.__setattr__(settings, "ps02_auth_required", True)
    accounts.reset_limits()
    seed.ensure_seeded()
    logins.ensure_demo_accounts()
    yield
    object.__setattr__(settings, "ps02_auth_required", False)
    reseed.delete_by_name(["Login A", "Login B"])
    db.execute("DELETE FROM users WHERE email LIKE '%@login.test'")


def H(token):
    return {"Authorization": f"Bearer {token}"}


def register(name, email, pw="longenough1"):
    r = client.post("/api/ps02/auth/register", json={"name": name, "email": email, "password": pw, "class_section": "9-L"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_student_registers_and_signs_in_and_gets_their_profile():
    s = register("Login A", "a@login.test")
    assert s["role"] == "student" and s["token"] and s["student"]["name"] == "Login A"
    again = client.post("/api/ps02/auth/login", json={"email": "a@login.test", "password": "longenough1", "role": "student"}).json()
    assert again["student"]["id"] == s["student"]["id"]
    assert client.get("/api/ps02/auth/me", headers=H(s["token"])).json()["email"] == "a@login.test"


def test_wrong_password_weak_password_and_duplicate_email_are_refused():
    register("Login A", "a@login.test")
    assert client.post("/api/ps02/auth/login", json={"email": "a@login.test", "password": "nope-nope-1"}).status_code == 401
    assert client.post("/api/ps02/auth/register", json={"name": "x", "email": "b@login.test", "password": "short"}).status_code == 400
    assert client.post("/api/ps02/auth/register", json={"name": "x", "email": "a@login.test", "password": "longenough1"}).status_code == 400


def test_without_a_token_student_data_is_closed():
    sid = register("Login A", "a@login.test")["student"]["id"]
    assert client.get("/api/mastery", params={"student_id": sid}).status_code == 401
    assert client.get("/api/teacher/overview").status_code == 401
    assert client.get("/api/mastery", params={"student_id": sid}, headers=H("garbage")).status_code == 401


def test_a_student_sees_only_their_own_profile():
    a, b = register("Login A", "a@login.test"), register("Login B", "b@login.test")
    assert client.get("/api/mastery", params={"student_id": a["student"]["id"]}, headers=H(a["token"])).status_code == 200
    r = client.get("/api/mastery", params={"student_id": b["student"]["id"]}, headers=H(a["token"]))
    assert r.status_code == 403 and "not your profile" in r.json()["error"]


def test_a_student_cannot_open_teacher_pages_or_create_profiles():
    a = register("Login A", "a@login.test")
    for path in ("/api/teacher/overview", "/api/teacher/groups", "/api/students"):
        r = client.get(path, headers=H(a["token"]))
        assert r.status_code == 403, path
    assert client.post("/api/students", json={"name": "x"}, headers=H(a["token"])).status_code == 403
    assert client.post("/api/demo/seed-class", headers=H(a["token"])).status_code == 403


def test_the_teacher_signs_in_with_the_teacher_account_and_sees_everything():
    t = client.post("/api/ps02/auth/login", json={"email": settings.teacher_email, "password": settings.teacher_password, "role": "teacher"}).json()
    assert t["role"] == "teacher" and "student" not in t
    assert client.get("/api/teacher/overview", headers=H(t["token"])).status_code == 200
    a = register("Login A", "a@login.test")
    assert client.get("/api/mastery", params={"student_id": a["student"]["id"]}, headers=H(t["token"])).status_code == 200


def test_the_roles_do_not_mix_on_the_login_forms():
    register("Login A", "a@login.test")
    assert client.post("/api/ps02/auth/login", json={"email": "a@login.test", "password": "longenough1", "role": "teacher"}).status_code == 401
    assert client.post("/api/ps02/auth/login", json={"email": settings.teacher_email, "password": settings.teacher_password, "role": "student"}).status_code == 401


def test_nobody_can_register_as_a_teacher():
    r = client.post("/api/ps02/auth/register", json={"name": "Sneaky", "email": "s@login.test", "password": "longenough1", "role": "teacher"}).json()
    assert r["role"] == "student"
    assert client.get("/api/teacher/overview", headers=H(r["token"])).status_code == 403


def test_demo_buttons_give_a_demo_student_and_a_demo_teacher():
    s = client.post("/api/ps02/auth/demo", json={"role": "student"}).json()
    assert s["role"] == "student" and s["student"]["is_demo"] == 1
    assert client.get("/api/mastery", params={"student_id": s["student"]["id"]}, headers=H(s["token"])).status_code == 200
    t = client.post("/api/ps02/auth/demo", json={"role": "teacher"}).json()
    assert t["role"] == "teacher" and client.get("/api/teacher/overview", headers=H(t["token"])).status_code == 200
    assert client.post("/api/ps02/auth/demo", json={"role": "admin"}).status_code == 422


def test_the_tour_reset_hands_out_a_token_so_the_whole_tour_works_while_logins_are_required():
    r = client.post("/api/demo/tour-reset").json()
    assert r["token"]
    assert client.get("/api/mastery", params={"student_id": r["student"]["id"]}, headers=H(r["token"])).status_code == 200
    assert client.get("/api/teacher/groups", headers=H(r["token"])).status_code == 200


def test_everything_is_open_as_before_when_logins_are_switched_off():
    object.__setattr__(settings, "ps02_auth_required", False)
    sid = service.create_student("Login A", "9-L")["id"]
    assert client.get("/api/mastery", params={"student_id": sid}).status_code == 200
    assert client.get("/api/teacher/overview").status_code == 200
