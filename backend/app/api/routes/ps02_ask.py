"""PS02 + original Eklavya, joined: Ask a doubt (tagged to a concept) and notes (student or class), both on the original RAG pipeline."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.routes import documents
from app.errors import BadRequestError
from fastapi.concurrency import run_in_threadpool

from app.ps02 import logins, content, doubts, notebook, notes, question_gen, service

router = APIRouter()


class DoubtIn(BaseModel):
    student_id: int
    question: str = Field(min_length=2, max_length=600)
    language: str = Field(default="hinglish", pattern="^(hinglish|english|hindi)$")
    concept_id: str | None = None
    mode: str = Field(default="text", pattern="^(voice|text)$")


def _student(student_id: int) -> dict:
    logins.check_student(student_id)
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
    if student_id is None:
        logins.check_teacher()          # class notes are the teacher's
    if student_id is not None:
        _student(student_id)
    try:
        owner = notes.owner_for(student_id, class_section)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await documents.upload_document(file=file, text=text, user_id=owner)
    question_gen.clear_prefetch(None if class_section else student_id)   # questions generated before these notes existed must not be served
    return notes.describe(result["document_id"], "class" if class_section else "mine")


MAX_PHOTO_BYTES = 8 * 1024 * 1024


@router.get("/api/ps02/notebook/samples")
def notebook_samples():
    """The two built-in sample notebook photos (the page images are static files on the frontend)."""
    return {"samples": notebook.public_samples()}


@router.post("/api/ps02/notebook")
async def read_notebook(student_id: int = Form(...), attempt_id: int | None = Form(None), sample_id: str | None = Form(None), concept_id: str | None = Form(None),
                        language: str = Form("hinglish"), file: UploadFile = File(None)):
    """📸 Snap your notebook: a photo of the student's working (or a built-in sample) -> transcribed steps, the first wrong line, the misconception."""
    _student(student_id)
    if language not in ("hinglish", "english", "hindi"):
        raise HTTPException(422, "Unknown language")
    image = None
    if file is not None:
        raw = await file.read()
        if len(raw) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "That photo is larger than 8 MB. Take it again a little further away.")
        if raw:
            try:
                image, _mime = await run_in_threadpool(notebook.prepare_image, raw)
            except ValueError:
                raise HTTPException(415, "That file is not a photo. Please upload a JPG or PNG of your notebook page.")
    if image is None and not sample_id:
        raise HTTPException(422, "Send a photo of your working, or choose a sample.")
    try:
        return await run_in_threadpool(lambda: notebook.analyse(student_id, image, attempt_id=attempt_id, sample_id=sample_id,
                                                                concept_id=concept_id if concept_id in content.concepts() else None, language=language))
    except KeyError as exc:
        raise HTTPException(404, f"{str(exc).strip(chr(39))}".capitalize())


@router.delete("/api/ps02/notes/{document_id}")
def delete_note(document_id: int, student_id: int | None = None, class_section: str | None = None):
    if student_id is None:
        logins.check_teacher()
    else:
        logins.check_student(student_id)
    if not notes.delete_note(document_id, student_id, class_section):
        raise HTTPException(404, "Note not found")
    question_gen.clear_prefetch(None if class_section else student_id)
    return {"deleted": document_id}
