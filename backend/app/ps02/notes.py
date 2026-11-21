"""Notes for PS02 students, reusing Eklavya's original document pipeline (ingest -> chunks -> topics -> embeddings -> BM25 + vector retrieval).

A PS02 student is bridged to an original Eklavya ``users`` row (``students.user_id``, created on first need), so the untouched original code
(document_intelligence, retrieval, voice_tutor) works for them. Class notes (uploaded by a teacher) belong to a pseudo-user ``class:<section>``;
retrieval for every student in that class also searches those documents (see ``retrieval.chunks_of_user``).
"""
from __future__ import annotations

from app import db
from app.domain import retrieval

CLASS_EMAIL = "class:{}"
MIN_COVERAGE = 0.4          # share of the query's words that must appear in the passages for them to count as "relevant"
SNIPPET_CHARS = 700


def user_id_for(student_id: int) -> int:
    """The original-Eklavya user behind a PS02 student (created the first time it is needed)."""
    row = db.one("SELECT name, user_id FROM students WHERE id=?", (student_id,))
    if not row:
        raise KeyError("student not found")
    if row["user_id"]:
        return row["user_id"]
    uid = db.execute("INSERT INTO users (name, preferred_language) VALUES (?, 'hinglish')", (row["name"],))
    db.execute("UPDATE students SET user_id=? WHERE id=?", (uid, student_id))
    return uid


def class_user_id(section: str) -> int:
    email = CLASS_EMAIL.format(section)
    row = db.one("SELECT id FROM users WHERE email=?", (email,))
    return row["id"] if row else db.execute("INSERT INTO users (name, email, preferred_language) VALUES (?, ?, 'hinglish')", (f"Class {section} notes", email))


def owner_for(student_id: int | None, class_section: str | None) -> int:
    """Whose notes an upload belongs to: the class (teacher upload) or the student."""
    if class_section:
        return class_user_id(class_section.strip())
    if student_id is None:
        raise ValueError("a student or a class is required")
    return user_id_for(student_id)


def _owners(student_id: int) -> list[tuple[int, str]]:
    owners = [(user_id_for(student_id), "mine")]
    row = db.one("SELECT class_section FROM students WHERE id=?", (student_id,))
    if row and row["class_section"]:
        cls = db.one("SELECT id FROM users WHERE email=?", (CLASS_EMAIL.format(row["class_section"]),))
        if cls:
            owners.append((cls["id"], "class"))
    return owners


def describe(document_id: int, scope: str = "mine") -> dict:
    doc = db.one("SELECT id, file_name, user_id, uploaded_at FROM documents WHERE id=?", (document_id,))
    topics = [t["topic_name"] for t in db.query("SELECT topic_name FROM topics WHERE document_id=? ORDER BY id", (document_id,))]
    return {"id": doc["id"], "file_name": doc["file_name"], "uploaded_at": doc["uploaded_at"], "scope": scope, "topics": topics, "chunks": retrieval.count_chunks(doc["user_id"], document_id)}


def list_notes(student_id: int) -> list[dict]:
    out = []
    for uid, scope in _owners(student_id):
        for d in db.query("SELECT id FROM documents WHERE user_id=? ORDER BY id DESC", (uid,)):
            out.append(describe(d["id"], scope))
    return out


def list_class_notes(section: str) -> list[dict]:
    row = db.one("SELECT id FROM users WHERE email=?", (CLASS_EMAIL.format(section),))
    return [describe(d["id"], "class") for d in db.query("SELECT id FROM documents WHERE user_id=? ORDER BY id DESC", (row["id"],))] if row else []


def delete_note(document_id: int, student_id: int | None = None, class_section: str | None = None) -> bool:
    from app.services.documents import delete_document
    uid = owner_for(student_id, class_section)
    if not db.one("SELECT id FROM documents WHERE id=? AND user_id=?", (document_id, uid)):
        return False
    delete_document(uid, document_id)
    return True


def has_notes(student_id: int) -> bool:
    return retrieval.has_notes(user_id_for(student_id))


def context_for(student_id: int, query: str, k: int = 2) -> dict | None:
    """Relevant passages from the student's (and class) notes for ``query``, with a citation, or None when the notes do not cover it."""
    from app.services import search
    uid = user_id_for(student_id)
    if not retrieval.has_notes(uid):
        return None
    chunks = search.search(uid, query, None, k)
    if not chunks or retrieval.coverage(query, chunks) < MIN_COVERAGE or retrieval.is_outline(chunks):
        return None
    top = chunks[0]
    text = "\n\n".join(f"[{c['heading'] or c['topic']}] {c['text']}" for c in chunks)[: SNIPPET_CHARS * k]
    return {"text": text, "citation": {"document_id": top["document_id"], "file_name": top["document"], "topic": top["topic"], "heading": top["heading"], "page": top.get("page")}}
