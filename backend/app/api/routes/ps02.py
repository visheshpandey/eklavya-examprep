"""Eklavya Exam Prep (PS02) endpoints. Students are identified by ``student_id`` (no login: this is the hackathon demo)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ps02 import learner_model as lm, seed, service, srs, teacher

router = APIRouter()


class StudentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    class_section: str = Field(default="", max_length=20)


class DiagAnswer(BaseModel):
    question_id: str
    chosen_index: int = Field(ge=0, le=3)


class DiagSubmit(BaseModel):
    student_id: int
    answers: list[DiagAnswer]


class AnswerIn(BaseModel):
    student_id: int
    question_id: str
    chosen_index: int = Field(ge=0, le=3)
    elapsed_seconds: float | None = None


class ReasoningIn(BaseModel):
    student_id: int
    attempt_id: int
    reasoning_text: str = Field(min_length=1, max_length=1500)
    reasoning_mode: str = Field(default="text", pattern="^(voice|text)$")


class TimeTravelIn(BaseModel):
    on: bool


def _student(student_id: int) -> dict:
    s = service.get_student(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return s


@router.get("/api/health")
def health():
    return {"status": "ok", "service": "Eklavya Exam Prep"}


@router.post("/api/students")
def create_student(body: StudentIn):
    return service.create_student(body.name, body.class_section)


@router.get("/api/students")
def list_students(class_section: str | None = None):
    return {"students": [s for s in teacher.class_students(class_section or teacher.default_class())]}


@router.get("/api/diagnostic")
def diagnostic():
    return {"questions": service.diagnostic_questions()}


@router.post("/api/diagnostic/submit")
def diagnostic_submit(body: DiagSubmit):
    _student(body.student_id)
    return service.submit_diagnostic(body.student_id, [a.model_dump() for a in body.answers])


@router.get("/api/practice/next")
def practice_next(student_id: int, review: bool = False, concept_id: str | None = None):
    _student(student_id)
    return service.next_question(student_id, review=review, concept_id=concept_id)


@router.post("/api/practice/answer")
def practice_answer(body: AnswerIn):
    _student(body.student_id)
    try:
        return service.answer(body.student_id, body.question_id, body.chosen_index, body.elapsed_seconds)
    except KeyError:
        raise HTTPException(404, "Question expired. Please fetch the next one.")


@router.post("/api/practice/reasoning")
def practice_reasoning(body: ReasoningIn):
    _student(body.student_id)
    try:
        return service.apply_reasoning(body.student_id, body.attempt_id, body.reasoning_text.strip(), body.reasoning_mode)
    except KeyError:
        raise HTTPException(404, "Attempt not found")


@router.get("/api/mastery")
def mastery(student_id: int):
    s = _student(student_id)
    return {"student": s, **service.mastery_view(student_id)}


@router.get("/api/mastery/history")
def mastery_history(student_id: int, concept_id: str):
    _student(student_id)
    return {"concept_id": concept_id, "points": service.mastery_history(student_id, concept_id)}


@router.get("/api/misconceptions")
def student_misconceptions(student_id: int):
    _student(student_id)
    return {"misconceptions": service.active_misconceptions(student_id)}


@router.get("/api/reviews/due")
def reviews_due(student_id: int):
    _student(student_id)
    rows = srs.due_reviews(student_id)
    return {"time_travel": srs.time_travel(), "due": [r for r in rows if r["due"]], "upcoming": [r for r in rows if not r["due"]]}


@router.get("/api/teacher/overview")
def teacher_overview(class_section: str | None = None):
    return teacher.overview(class_section)


@router.get("/api/teacher/reteach")
def teacher_reteach(class_section: str | None = None, refresh: bool = False):
    return teacher.reteach(class_section, force=refresh)


@router.post("/api/demo/seed")
def demo_seed():
    return seed.reseed()


@router.get("/api/demo/time-travel")
def get_time_travel():
    return {"on": srs.time_travel()}


@router.post("/api/demo/time-travel")
def set_time_travel(body: TimeTravelIn):
    srs.set_time_travel(body.on)
    return {"on": srs.time_travel()}
