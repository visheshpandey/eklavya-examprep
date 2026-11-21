"""Two logins: students (register / sign in, own data only) and teachers (accounts made by the deployer, never from the public page).

Built on the original Eklavya accounts (``app.auth``: scrypt passwords, signed tokens, sign-in rate limits). ``users.role`` is 'student' or 'teacher';
a student's login is linked to their PS02 profile through ``students.user_id``. Everything here is switched on by PS02_AUTH_REQUIRED (off in the tests
and in plain local development, so nothing else changes until it is turned on).
"""
from __future__ import annotations

import contextvars

from app import accounts, auth, db
from app.config import settings
from app.errors import ForbiddenError, UnauthorizedError
from app.ps02 import service

DEMO_STUDENT_EMAIL = "demo-student@eklavya.demo"
DEMO_STUDENT_PASSWORD = "demo-student-1"
CALLER: contextvars.ContextVar[dict | None] = contextvars.ContextVar("ps02_caller", default=None)


def required() -> bool:
    return settings.ps02_auth_required


# ------------------------------------------------------------------ who is calling
def caller_from_token(token: str | None) -> dict | None:
    """{"uid", "role"} for a valid token, None for no token; a bad token raises 401 (never a silent guest)."""
    if not token:
        return None
    uid = auth.read_token(token)
    row = db.one("SELECT id, role FROM users WHERE id=?", (uid,))
    if not row:
        raise UnauthorizedError("Please sign in again.")
    return {"uid": uid, "role": row.get("role") or "student"}


def check_student(student_id: int) -> None:
    """A student may only open their own profile; a teacher may open any. A no-op while PS02_AUTH_REQUIRED is off."""
    if not required():
        return
    who = CALLER.get()
    if not who:
        raise UnauthorizedError("Please sign in.")
    if who["role"] == "teacher":
        return
    row = db.one("SELECT user_id FROM students WHERE id=?", (student_id,))
    if not row or row["user_id"] != who["uid"]:
        raise ForbiddenError("That is not your profile.")


def check_teacher() -> None:
    if not required():
        return
    who = CALLER.get()
    if not who:
        raise UnauthorizedError("Please sign in.")
    if who["role"] != "teacher":
        raise ForbiddenError("This page is for teachers.")


# ------------------------------------------------------------------ responses
def _student_of(uid: int) -> dict | None:
    return db.one("SELECT id, name, class_section, is_demo FROM students WHERE user_id=? ORDER BY id LIMIT 1", (uid,))


def _session(uid: int) -> dict:
    row = db.one("SELECT id, name, email, role FROM users WHERE id=?", (uid,))
    role = row.get("role") or "student"
    out = {"token": auth.make_token(uid), "role": role, "name": row["name"], "email": row["email"]}
    if role == "student":
        out["student"] = _student_of(uid)
    return out


def register(name: str, email: str, password: str, class_section: str, ip: str) -> dict:
    out = accounts.signup(name, email, password, ip)            # validates, hashes, rate-limits
    uid = out["user"]["id"]
    db.execute("UPDATE users SET role='student' WHERE id=?", (uid,))
    s = service.create_student(name or email.split("@")[0], class_section)
    db.execute("UPDATE students SET user_id=? WHERE id=?", (uid, s["id"]))
    return _session(uid)


def login(email: str, password: str, ip: str, role: str | None = None) -> dict:
    out = accounts.login(email, password, ip)
    session = _session(out["user"]["id"])
    if role and session["role"] != role:        # a student cannot sign in on the teacher form, and the other way round
        raise UnauthorizedError("That account is not a %s account." % role)
    return session


# ------------------------------------------------------------------ demo accounts (always present, re-created on every start)
def _upsert_account(email: str, password: str, role: str, name: str) -> int:
    row = db.one("SELECT id FROM users WHERE email=?", (email,))
    if row:
        db.execute("UPDATE users SET password_hash=?, role=? WHERE id=?", (auth.hash_password(password), role, row["id"]))
        return row["id"]
    return db.execute("INSERT INTO users (name, email, password_hash, role, preferred_language) VALUES (?,?,?,?, 'hinglish')", (name, email, auth.hash_password(password), role))


def ensure_demo_accounts() -> None:
    """The demo teacher (credentials from TEACHER_EMAIL / TEACHER_PASSWORD) and the demo student (linked to the first demo student), so judges never have to register."""
    _upsert_account(settings.teacher_email, settings.teacher_password, "teacher", "Demo teacher")
    demo = db.one("SELECT id, user_id FROM students WHERE is_demo=1 ORDER BY id LIMIT 1")
    if not demo:
        return
    if demo["user_id"] and not db.one("SELECT 1 AS x FROM users WHERE id=? AND email IS NOT NULL", (demo["user_id"],)):
        uid = demo["user_id"]       # keep the notes already attached to the bridged user
        db.execute("UPDATE users SET email=?, password_hash=?, role='student' WHERE id=?", (DEMO_STUDENT_EMAIL, auth.hash_password(DEMO_STUDENT_PASSWORD), uid))
    else:
        uid = _upsert_account(DEMO_STUDENT_EMAIL, DEMO_STUDENT_PASSWORD, "student", demo.get("name") or "Demo student")
        db.execute("UPDATE students SET user_id=? WHERE id=?", (uid, demo["id"]))


def demo_login(role: str) -> dict:
    ensure_demo_accounts()
    email = settings.teacher_email if role == "teacher" else DEMO_STUDENT_EMAIL
    row = db.one("SELECT id FROM users WHERE email=?", (email,))
    if not row:
        raise UnauthorizedError("The demo class is still being prepared. Try again in a moment.")
    return _session(row["id"])
