"""PS02 + original Eklavya, joined: Ask a doubt (tagged to a concept) and notes (student or class), both on the original RAG pipeline."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.routes import documents
from app.errors import BadRequestError
from app.ps02 import content, doubts, notes, service

router = APIRouter()


class DoubtIn(BaseModel):
    student_id: int
    question: str = Field(min_length=2, max_length=600)
    language: str = Field(default="hinglish", pattern="^(hinglish|english|hindi)$")
    concept_id: str | None = None
    mode: str = Field(default="text", pattern="^(voice|text)$")


def _student(student_id: int) -> dict:
    s = service.get_student(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return s


@router.post("/api/ps02/doubt")
def ask_doubt(body: DoubtIn):
    _student(body.student_id)
    hint = body.concept_id if body.concept_id in content.concepts() else None
    try:
        return doubts.ask(body.student_id, body.question.strip(), body.language, hint, body.mode)
    except BadRequestError as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/ps02/doubts")
def list_doubts(student_id: int, concept_id: str | None = None):
    _student(student_id)
    return doubts.list_doubts(student_id, concept_id)


@router.get("/api/ps02/notes")
def list_notes(student_id: int):
    _student(student_id)
    return {"notes": notes.list_notes(student_id)}


@router.get("/api/ps02/class-notes")
def list_class_notes(class_section: str):
    return {"notes": notes.list_class_notes(class_section)}


@router.post("/api/ps02/notes")
async def upload_notes(student_id: int | None = Form(None), class_section: str | None = Form(None), file: UploadFile = File(None), text: str = Form(None)):
    """Upload a PDF / TXT / photo or pasted text through Eklavya's original ingest (chunking, topics, embeddings)."""
    if student_id is not None:
        _student(student_id)
    try:
        owner = notes.owner_for(student_id, class_section)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await documents.upload_document(file=file, text=text, user_id=owner)
    return notes.describe(result["document_id"], "class" if class_section else "mine")


@router.delete("/api/ps02/notes/{document_id}")
def delete_note(document_id: int, student_id: int | None = None, class_section: str | None = None):
    if not notes.delete_note(document_id, student_id, class_section):
        raise HTTPException(404, "Note not found")
    return {"deleted": document_id}
