"""Eklavya Exam Prep (PS02) endpoints. Students are identified by ``student_id`` (no login: this is the hackathon demo)."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ps02 import board, content, copilot, learner_model as lm, rootcause, seed, service, socratic, srs, teacher, traps

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


def ndjson(events):
    """Newline-delimited JSON, flushed as each event is produced, so the browser can show text while the model is still writing."""
    def gen():
        try:
            for event in events:
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except KeyError:
            yield json.dumps({"type": "error", "message": "Not found"}) + "\n"
        except Exception:  # noqa: BLE001 - tell the client instead of cutting the stream
            yield json.dumps({"type": "error", "message": "Something went wrong. Please try again."}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
    language: str = Field(default="hinglish", pattern="^(hinglish|english|hindi)$")


class DialogueStart(BaseModel):
    student_id: int
    attempt_id: int | None = None        # a wrong attempt, or None to start from a misconception directly ("fix the root first")
    misconception_id: str | None = None
    concept_id: str | None = None
    language: str = Field(default="hinglish", pattern="^(hinglish|english|hindi)$")


class DialogueReply(BaseModel):
    student_id: int
    dialogue_id: int
    text: str = Field(min_length=1, max_length=800)
    mode: str = Field(default="text", pattern="^(voice|text)$")
    language: str | None = Field(default=None, pattern="^(hinglish|english|hindi)$")


class AssignIn(BaseModel):
    class_section: str | None = None
    misconception_id: str
    student_ids: list[int] | None = None


class CheckAnswerIn(BaseModel):
    student_id: int
    question_id: str
    chosen_index: int = Field(ge=0, le=3)


class TimeTravelIn(BaseModel):
    on: bool


def _student(student_id: int) -> dict:
    s = service.get_student(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return s


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
def practice_next(student_id: int, review: bool = False, concept_id: str | None = None, target_mc: str | None = None):
    _student(student_id)
    return service.next_question(student_id, review=review, concept_id=concept_id, target_mc=target_mc)


@router.post("/api/practice/prefetch")
def practice_prefetch(student_id: int):
    """Start generating the first question in the background (called when the map loads), so Practice opens instantly."""
    _student(student_id)
    service._prefetch_after(student_id)
    return {"started": True}


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
        return service.apply_reasoning(body.student_id, body.attempt_id, body.reasoning_text.strip(), body.reasoning_mode, language=body.language)
    except KeyError:
        raise HTTPException(404, "Attempt not found")


@router.post("/api/dialogue/start")
def dialogue_start(body: DialogueStart):
    _student(body.student_id)
    try:
        return socratic.start(body.student_id, body.attempt_id, body.language, body.misconception_id, body.concept_id)
    except KeyError:
        raise HTTPException(404, "Attempt not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/api/dialogue/reply")
def dialogue_reply(body: DialogueReply):
    _student(body.student_id)
    try:
        return socratic.reply(body.student_id, body.dialogue_id, body.text, body.mode, body.language)
    except KeyError:
        raise HTTPException(404, "Dialogue not found")


def _trace_for(student_id: int, concept_id: str) -> dict:
    return rootcause.trace(concept_id, lm.get_mastery(student_id), service.active_misconceptions(student_id))


@router.get("/api/ps02/board")
def board_view(student_id: int):
    """🎯 Predicted CBSE Physics score (an estimate, labelled approximate) and the fixes ranked by marks."""
    _student(student_id)
    return board.student_board(student_id)


@router.get("/api/ps02/struggles")
def struggles(student_id: int, language: str = "hinglish"):
    """The concepts the student keeps failing, each with its traced root cause (a plain-template sentence; the AI sentence is /root-cause)."""
    _student(student_id)
    out = []
    for cid in rootcause.struggling(student_id):
        t = _trace_for(student_id, cid)
        out.append({**t, "explanation": rootcause.template(t, language), "explanation_source": "template"})
    return {"struggles": out}


@router.get("/api/ps02/root-cause")
def root_cause(student_id: int, concept_id: str, language: str = "hinglish"):
    _student(student_id)
    if concept_id not in content.concepts():
        raise HTTPException(404, "Unknown concept")
    t = _trace_for(student_id, concept_id)
    text, source = rootcause.explain(t, language)
    return {**t, "explanation": text, "explanation_source": source}


@router.get("/api/mastery")
def mastery(student_id: int):
    s = _student(student_id)
    return {"student": s, **service.mastery_view(student_id)}


@router.post("/api/practice/reasoning/stream")
def practice_reasoning_stream(body: ReasoningIn):
    """Same result as /api/practice/reasoning, streamed: quick (first impression) -> delta (the AI's feedback as it is written) -> final."""
    _student(body.student_id)
    return ndjson({"type": kind, **({"text": v} if kind == "delta" else {"diagnosis": v} if kind == "quick" else {"result": v})}
                  for kind, v in service.reasoning_events(body.student_id, body.attempt_id, body.reasoning_text.strip(), body.reasoning_mode, body.language))


@router.post("/api/dialogue/reply/stream")
def dialogue_reply_stream(body: DialogueReply):
    _student(body.student_id)
    return ndjson({"type": kind, **({"text": v} if kind in ("delta", "replace") else {"result": v})}
                  for kind, v in socratic.reply_events(body.student_id, body.dialogue_id, body.text, body.mode, body.language))


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


@router.get("/api/teacher/groups")
def teacher_groups(class_section: str | None = None):
    """Students grouped by a shared active misconception, with any assignment's before -> after."""
    return copilot.groups(class_section)


@router.get("/api/teacher/lesson")
def teacher_lesson(misconception_id: str, class_section: str | None = None, refresh: bool = False):
    """A 10-minute mini-lesson for the group (hook demo, analogy, 3 check questions, Hinglish script). Cached per class and misconception."""
    try:
        return copilot.lesson(class_section, misconception_id, refresh)
    except KeyError:
        raise HTTPException(404, "Unknown misconception")


@router.post("/api/teacher/assign")
def teacher_assign(body: AssignIn):
    try:
        return copilot.assign(body.class_section, body.misconception_id, body.student_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/api/ps02/assignments")
def student_assignments(student_id: int):
    _student(student_id)
    return {"assignments": copilot.student_assignments(student_id)}


@router.post("/api/demo/seed-class")
def demo_seed():
    """Rebuild the PS02 demo class 10-B. (The original Eklavya POST /api/demo/seed, which seeds a guest's demo notes, is left untouched.)"""
    return seed.reseed()


@router.post("/api/demo/tour-reset")
def demo_tour_reset():
    """Start of the Judge tour: restore the demo student (and his classmate) to the known story, in place. Other students and visitors are untouched."""
    return {"student": seed.reset_tour_students()}


@router.get("/api/ps02/checks")
def checks(student_id: int):
    """Verification checks for the Reviews screen: due, upcoming, and misconceptions already verified fixed."""
    _student(student_id)
    return traps.checks(student_id)


@router.get("/api/ps02/checks/next")
def check_next(student_id: int, misconception_id: str):
    """The trap question for a due check."""
    _student(student_id)
    try:
        return traps.next_trap(student_id, misconception_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'").capitalize())
    except ValueError as exc:
        raise HTTPException(409, str(exc).capitalize())


@router.post("/api/ps02/checks/answer")
def check_answer(body: CheckAnswerIn):
    _student(body.student_id)
    try:
        return traps.answer(body.student_id, body.question_id, body.chosen_index)
    except KeyError:
        raise HTTPException(404, "Check not found. Please open it again from Reviews.")


@router.post("/api/demo/checks-due")
def demo_checks_due(student_id: int):
    """Demo helper (Judge tour): make the student's pending verification checks due right now."""
    _student(student_id)
    traps.force_due(student_id)
    return {"ok": True}


@router.get("/api/demo/time-travel")
def get_time_travel():
    return {"on": srs.time_travel()}


@router.post("/api/demo/time-travel")
def set_time_travel(body: TimeTravelIn):
    srs.set_time_travel(body.on)
    return {"on": srs.time_travel()}
