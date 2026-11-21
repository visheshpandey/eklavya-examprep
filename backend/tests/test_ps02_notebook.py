"""📸 Snap your notebook (vision stubbed): samples with a prepared fallback, the real-photo path, validation, limits, the Ask path, and the evidence tag."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.errors import LLMError
from app.main import create_app
from app.ps02 import content, learner_model as lm, llm_vision, notebook, service

client = TestClient(create_app())
PHOTO = (Path(__file__).resolve().parents[2] / "frontend" / "assets" / "notebook" / "sample-unit.jpg").read_bytes()

GOOD = {"readable": True, "transcribed_steps": ["I = 200 mA, t = 10 s", "Q = I × t", "Q = 200 × 10", "Q = 2000 C"], "first_wrong_step": 2,
        "error": "mA not converted to A: you used 200 instead of 0.2 A", "misconception_id": "MC22", "confidence": "high", "is_careless_error": False, "new_label": "",
        "feedback_hinglish": "Line 3 mein 200 mA ko A mein badalna tha.", "feedback_english": "Line 3: convert 200 mA to 0.2 A first."}


def student(name="NotebookKid"):
    return service.create_student(name, "9-Z")["id"]


def stub_vision(monkeypatch, reply):
    monkeypatch.setattr(llm_vision, "hedged_vision_json", lambda *a, **k: reply if not isinstance(reply, Exception) else (_ for _ in ()).throw(reply))


def post(sid, **data):
    files = {"file": ("page.jpg", data.pop("photo"), "image/jpeg")} if "photo" in data else None
    return client.post("/api/ps02/notebook", data={"student_id": str(sid), **{k: str(v) for k, v in data.items()}}, files=files)


def wrong_attempt(sid, concept="C1"):
    q = {**content.diagnostic()[7], "concept_id": concept}      # D08: option 0 is built from MC01
    return service.record_answer(sid, q, 0)["attempt_id"]


def test_samples_are_listed_without_their_answers():
    s = client.get("/api/ps02/notebook/samples").json()["samples"]
    assert [x["id"] for x in s] == ["unit", "formula"]
    assert all("canned" not in x and x["image"].endswith(".jpg") and len(x["question"]["options"]) == 4 for x in s)
    for x in s:                                                   # the page images exist on the frontend
        assert (Path(__file__).resolve().parents[2] / "frontend" / x["image"]).exists()


def test_a_sample_works_with_no_camera_and_no_ai(monkeypatch):
    stub_vision(monkeypatch, LLMError("down"))
    sid = student()
    before = lm.get_mastery(sid)["C1"]
    r = post(sid, sample_id="unit", language="english").json()
    assert r["readable"] is True and r["notebook"]["source"] == "sample-prepared"
    assert r["notebook"]["first_wrong_step"] == 2 and r["notebook"]["steps"][2] == "Q = 200 × 10"
    assert r["misconception"]["id"] == "MC22" and r["diagnosis"]["feedback_english"].startswith("The problem is line 3")
    assert r["sample"]["picked"] == 0 and r["sample"]["correct_index"] == 2
    assert [t["tool"] for t in r["trace"]][0] == "detect_misconception"
    assert lm.get_mastery(sid)["C1"] < before                    # a real wrong answer in the learner model
    mc = db.one("SELECT misconception_id, last_source FROM student_misconceptions WHERE student_id=?", (sid,))
    assert mc["misconception_id"] == "MC22" and mc["last_source"] == "notebook"
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": r["attempt_id"], "language": "english"}).json()
    assert d["misconception"]["id"] == "MC22" and d["transcript"][0]["role"] == "tutor"          # straight into the Socratic dialogue


def test_the_formula_sample_names_the_flipped_formula():
    sid = student("FormulaKid")
    r = post(sid, sample_id="formula").json()
    assert r["notebook"]["first_wrong_step"] == 1 and r["misconception"]["id"] == "MC21"


def test_a_real_photo_is_read_by_the_model_and_applied_like_spoken_reasoning(monkeypatch):
    seen = {}

    def fake(system, prompt, image, mime, required_keys=(), **k):
        seen.update(prompt=prompt, mime=mime, size=len(image))
        return GOOD
    monkeypatch.setattr(llm_vision, "hedged_vision_json", fake)
    sid = student("PhotoKid")
    att = wrong_attempt(sid)
    r = post(sid, attempt_id=att, photo=PHOTO, language="hinglish").json()
    assert r["readable"] and r["notebook"]["source"] == "ai" and r["notebook"]["first_wrong_step"] == 2
    assert "The correct answer" in seen["prompt"] and "MC22" in seen["prompt"] and seen["mime"] == "image/jpeg"
    assert r["diagnosis"]["misconception_id"] == "MC22" and r["diagnosis"]["confidence_label"] == "High" and r["mastery_changes"]
    assert "line 3" in r["diagnosis"]["evidence"] and "Q = 200 × 10" in r["diagnosis"]["evidence"]
    row = db.one("SELECT reasoning_mode, misconception_id FROM attempts WHERE id=?", (att,))
    assert row["reasoning_mode"] == "notebook" and row["misconception_id"] == "MC22"


def test_correct_working_with_a_wrong_pick_is_a_slip_not_a_misconception(monkeypatch):
    stub_vision(monkeypatch, {**GOOD, "transcribed_steps": ["Q = 0.2 × 10", "Q = 2 C"], "first_wrong_step": None, "error": "", "misconception_id": "NONE"})
    sid = student("SlipKid")
    att = wrong_attempt(sid)
    r = post(sid, attempt_id=att, photo=PHOTO).json()
    assert r["diagnosis"]["is_careless_error"] is True and r["misconception"] is None
    assert db.one("SELECT COUNT(*) AS n FROM student_misconceptions WHERE student_id=?", (sid,))["n"] == 0


def test_the_models_json_is_validated_and_cleaned(monkeypatch):
    stub_vision(monkeypatch, {"readable": True, "transcribed_steps": ["  a ", "", "b"], "first_wrong_step": 9, "misconception_id": "MC99", "confidence": "VERY", "error": "x"})
    sid = student("CleanKid")
    r = notebook.read(PHOTO, "image/jpeg", None, None, "english")
    assert r.transcribed_steps == ["a", "b"] and r.first_wrong_step is None            # out-of-range line -> none
    assert r.misconception_id == "MC_UNKNOWN" and r.confidence == "medium"           # unknown id and odd confidence are sanitised
    stub_vision(monkeypatch, {"readable": True, "transcribed_steps": []})
    assert notebook.read(PHOTO, "image/jpeg", None, None, "english").readable is False   # "readable" with nothing transcribed is not a reading


def test_unreadable_or_busy_photos_get_a_friendly_answer_but_samples_still_work(monkeypatch):
    sid = student("BlurKid")
    att = wrong_attempt(sid)
    stub_vision(monkeypatch, {"readable": False})
    r = post(sid, attempt_id=att, photo=PHOTO).json()
    assert r["readable"] is False and r["reason"] == "unclear" and "Couldn't read that clearly" in r["message"]
    stub_vision(monkeypatch, LLMError("busy"))
    r = post(sid, attempt_id=att, photo=PHOTO).json()
    assert r["readable"] is False and r["reason"] == "busy"
    assert db.one("SELECT reasoning_mode FROM attempts WHERE id=?", (att,))["reasoning_mode"] is None        # nothing was applied
    stub_vision(monkeypatch, {"readable": False})
    s = post(sid, sample_id="unit", photo=PHOTO).json()                                # a sample falls back to its prepared reading
    assert s["readable"] is True and s["notebook"]["source"] == "sample-prepared"


def test_requests_are_validated(monkeypatch):
    stub_vision(monkeypatch, GOOD)
    sid = student("RulesKid")
    assert client.post("/api/ps02/notebook", data={"student_id": "999999", "sample_id": "unit"}).status_code == 404
    assert post(sid).status_code == 422                                                 # neither a photo nor a sample
    assert post(sid, sample_id="nope").status_code == 404
    assert post(sid, attempt_id=999999, photo=PHOTO).status_code == 404
    bad = client.post("/api/ps02/notebook", data={"student_id": str(sid)}, files={"file": ("notes.txt", b"this is not an image", "text/plain")})
    assert bad.status_code == 415
    monkeypatch.setattr("app.api.routes.ps02_ask.MAX_PHOTO_BYTES", 100)
    assert post(sid, photo=PHOTO).status_code == 413
    assert client.post("/api/ps02/notebook", data={"student_id": str(sid), "sample_id": "unit", "language": "klingon"}).status_code == 422


def test_big_phone_photos_are_shrunk_and_normalised():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (240, 240, 230)).save(buf, "PNG")
    out, mime = notebook.prepare_image(buf.getvalue())
    img = Image.open(io.BytesIO(out))
    assert mime == "image/jpeg" and max(img.size) == notebook.MAX_SIDE and img.format == "JPEG"
    with pytest.raises(ValueError):
        notebook.prepare_image(b"not an image")


def test_a_photo_sent_from_ask_is_logged_like_a_doubt_and_shows_as_notebook_evidence(monkeypatch):
    def fake_llm(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        return {"concept_id": "C1", "misconception_id": None, "confidence": 0.1, "evidence": ""}
    monkeypatch.setattr(gemini, "llm_json", fake_llm)
    stub_vision(monkeypatch, GOOD)
    sid = service.create_student("AskPhoto", "10-B")["id"]
    try:
        lm.save_mastery(sid, {"C1": 0.6})
        r = post(sid, photo=PHOTO, language="english").json()
        assert r["readable"] and r["concept"]["id"] == "C1" and r["misconception"]["id"] == "MC22"
        assert r["mastery_changes"][0]["after"] < r["mastery_changes"][0]["before"] and r["mastery_changes"][0]["reason"] == "a mistake found in your notebook"
        ov = client.get("/api/teacher/overview", params={"class_section": "10-B"}).json()
        ex = next(e for m in ov["top_misconceptions"] if m["id"] == "MC22" for e in m["examples"] if e["student"] == "AskPhoto")
        assert ex["source"] == "notebook" and "line 3" in ex["quote"]                  # the dashboard can say "📸 from notebook"
    finally:
        from app.ps02 import reseed
        reseed.delete_by_name(["AskPhoto"])


def test_the_quoted_wrong_line_beats_a_miscounted_index(monkeypatch):
    stub_vision(monkeypatch, {**GOOD, "transcribed_steps": ["Given: I = 200 mA", "Q = I x t", "Q = 200 x 10", "Q = 2000 C"], "first_wrong_step": 0, "first_wrong_line": "Q = 200 × 10"})
    r = notebook.read(PHOTO, "image/jpeg", None, None, "english")
    assert r.first_wrong_step == 2                                   # the model said 0, but quoted line 3: the text wins ("x" and "×" match)
    stub_vision(monkeypatch, {**GOOD, "transcribed_steps": ["a = 1", "b = 2"], "first_wrong_step": 1, "first_wrong_line": "something not on the page"})
    assert notebook.read(PHOTO, "image/jpeg", None, None, "english").first_wrong_step == 1       # no good text match: keep a valid index
    stub_vision(monkeypatch, {**GOOD, "transcribed_steps": ["a = 1", "b = 2"], "first_wrong_step": None, "first_wrong_line": "b = 2"})
    assert notebook.read(PHOTO, "image/jpeg", None, None, "english").first_wrong_step == 1       # the quoted line alone is enough


def test_the_prompt_forbids_line_numbers_in_the_feedback_and_asks_for_the_quoted_line():
    assert "first_wrong_line" in notebook.SYSTEM and "Do NOT write line numbers" in notebook.SYSTEM
