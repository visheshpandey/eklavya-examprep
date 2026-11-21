"""The PS02 learning loop: diagnostic -> targeted question -> answer -> (reasoning) -> BKT + misconception + SM-2 updates.

``record_answer`` is the single place an answer changes the learner model; the HTTP routes and the demo seeder both call it.
A wrong answer is first applied *provisionally* (using the distractor's misconception as a prior); when the student then explains
their reasoning, ``apply_reasoning`` rolls that back and re-applies it with what the classifier actually found.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from app import db
from app.ps02 import agent, calibration, content, learner_model as lm, misconception, notes as notes_mod, question_gen, srs

FAST_SECONDS = 20
CHECK_EVERY = 4     # ask for reasoning on about 1 in 4 correct answers, to catch lucky guesses


# ------------------------------------------------------------------ students
DEFAULT_CLASS = "10-B"


def create_student(name: str, class_section: str = "", is_demo: bool = False) -> dict:
    """New students join class 10-B (unless told otherwise) so they show up on the teacher heatmap straight away."""
    section = class_section.strip() or DEFAULT_CLASS
    sid = db.execute("INSERT INTO students (name, class_section, is_demo) VALUES (?,?,?)", (name.strip() or "Student", section, 1 if is_demo else 0))
    return {"id": sid, "name": name.strip() or "Student", "class_section": section}


def get_student(student_id: int) -> dict | None:
    return db.one("SELECT id, name, class_section, is_demo FROM students WHERE id=?", (student_id,))


# ------------------------------------------------------------------ diagnostic
def diagnostic_questions() -> list[dict]:
    """The 14 questions with the answer key and misconception mapping removed."""
    return [{"id": q["id"], "concept_id": q["concept_id"], "concept_name": content.concepts()[q["concept_id"]]["name"], "chapter": content.concepts()[q["concept_id"]]["chapter"],
             "difficulty": q["difficulty"], "stem": q["stem"], "options": q["options"]} for q in content.diagnostic()]


def submit_diagnostic(student_id: int, answers: list[dict], when: datetime | None = None) -> dict:
    bank = {q["id"]: q for q in content.diagnostic()}
    results: dict[str, tuple[bool, int]] = {}
    graded = []
    for a in answers:
        q = bank.get(a.get("question_id"))
        if not q or a.get("chosen_index") not in (0, 1, 2, 3):
            continue
        ok = a["chosen_index"] == q["correct_index"]
        results[q["concept_id"]] = (ok, q["difficulty"])
        graded.append((q, a["chosen_index"], ok))
    when = when or datetime.now(timezone.utc)
    db.execute("DELETE FROM attempts WHERE student_id=? AND phase='diagnostic'", (student_id,))
    lm.save_mastery(student_id, lm.seed_from_diagnostic(results), touched={c: ok for c, (ok, _) in results.items()}, when=when.isoformat(timespec="seconds"))
    found: list[str] = []
    for q, chosen, ok in graded:
        mc = None if ok else q["distractor_misconceptions"].get(str(chosen))
        if mc and mc != "MC_UNKNOWN":
            _note_misconception(student_id, mc, f'Picked "{q["options"][chosen]}"', when)
            found.append(mc)
        db.execute("INSERT INTO attempts (student_id, question_json, concept_id, difficulty, chosen_index, correct, misconception_id, phase, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (student_id, json.dumps(q), q["concept_id"], q["difficulty"], chosen, 1 if ok else 0, mc, "diagnostic", when.isoformat(timespec="seconds")))
        srs.record(student_id, q["concept_id"], srs.quality(ok, has_misconception=bool(mc)), now=when)
    return {"score": sum(1 for _, _, ok in graded if ok), "total": len(graded), "mastery": lm.get_mastery(student_id),
            "possible_misconceptions": [misconception_card(m) for m in dict.fromkeys(found)]}


# ------------------------------------------------------------------ misconception bookkeeping
def misconception_card(mc_id: str) -> dict:
    m = content.misconceptions().get(mc_id) or {}
    return {"id": mc_id, "label": m.get("label", ""), "description": m.get("description", ""), "correction": m.get("correction", ""), "analogy": m.get("analogy", "")}


def _note_misconception(student_id: int, mc_id: str, quote: str, when: datetime | None = None, source: str | None = None) -> None:
    when_s = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    row = db.one("SELECT count FROM student_misconceptions WHERE student_id=? AND misconception_id=?", (student_id, mc_id))
    with db.get_conn() as c:
        if row:
            c.execute("UPDATE student_misconceptions SET count=?, last_seen=?, resolved=0, last_quote=?, last_source=? WHERE student_id=? AND misconception_id=?",
                      (row["count"] + 1, when_s, quote[:300], source, student_id, mc_id))
        else:
            c.execute("INSERT INTO student_misconceptions (student_id, misconception_id, count, last_seen, resolved, last_quote, last_source) VALUES (?,?,?,?,0,?,?)",
                      (student_id, mc_id, 1, when_s, quote[:300], source))


def active_misconceptions(student_id: int) -> list[dict]:
    rows = db.query("SELECT * FROM student_misconceptions WHERE student_id=? AND resolved=0 AND count>0 ORDER BY count DESC, last_seen DESC", (student_id,))
    return [{**misconception_card(r["misconception_id"]), "count": r["count"], "last_seen": r["last_seen"], "quote": r["last_quote"]} for r in rows]


def _resolve_if_overcome(student_id: int, question: dict) -> None:
    """A correct answer to a question whose distractors were built from a misconception counts toward overcoming it."""
    for mc in set(question.get("distractor_misconceptions", {}).values()):
        if mc != "MC_UNKNOWN":
            db.execute("UPDATE student_misconceptions SET resolved=1 WHERE student_id=? AND misconception_id=? AND resolved=0", (student_id, mc))


# ------------------------------------------------------------------ the core update
def _iso(when: datetime | None) -> str:
    return (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def record_answer(student_id: int, question: dict, chosen_index: int, *, phase: str = "practice", reasoning: str | None = None, mode: str | None = None,
                  misconception_id: str | None = None, confidence: float | None = None, careless: bool = False, lucky: bool = False,
                  fast: bool = False, when: datetime | None = None) -> dict:
    """Apply one answer to BKT + SM-2, store the attempt, and return what changed."""
    cid, difficulty = question["concept_id"], int(question.get("difficulty", 2))
    correct = chosen_index == question["correct_index"]
    prior = None if correct else question.get("distractor_misconceptions", {}).get(str(chosen_index))
    mc = misconception_id if misconception_id not in (None, "NONE") else None
    effective = None if careless else (mc or (prior if prior != "MC_UNKNOWN" else None))   # a careless slip carries no misconception

    mastery = lm.get_mastery(student_id)
    deltas = lm.apply_answer(mastery, cid, correct, difficulty, misconception_id=None if correct else effective, careless=careless, lucky=lucky)
    before = {}
    for d in deltas:
        before.setdefault(d["concept_id"], d["before"])
    lm.save_mastery(student_id, {d["concept_id"]: mastery[d["concept_id"]] for d in deltas}, touched={cid: correct}, when=_iso(when))

    srs_before = db.one("SELECT easiness, interval_days, repetitions, due_at FROM reviews WHERE student_id=? AND concept_id=?", (student_id, cid))
    review = srs.record(student_id, cid, srs.quality(correct, careless=careless, has_misconception=bool(effective), fast=fast), now=when)

    attempt_id = db.execute(
        "INSERT INTO attempts (student_id, question_json, concept_id, difficulty, chosen_index, correct, reasoning_text, reasoning_mode, misconception_id, misconception_confidence,"
        " is_careless, phase, delta_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (student_id, json.dumps(question), cid, difficulty, chosen_index, 1 if correct else 0, reasoning, mode, effective, confidence, 1 if careless else 0, phase,
         json.dumps({"before": before, "srs_before": srs_before, "deltas": deltas}), _iso(when)))
    if correct:
        _resolve_if_overcome(student_id, question)
    elif mc and mc != "MC_UNKNOWN" and reasoning:
        _note_misconception(student_id, mc, reasoning, when, mode)
    return {"attempt_id": attempt_id, "correct": correct, "deltas": deltas, "review": review, "misconception_prior": prior}


# ------------------------------------------------------------------ next question
def _recent_stems(student_id: int, n: int = 200) -> list[str]:
    """Every stem this student has seen (newest first): new questions must not repeat any of them."""
    rows = db.query("SELECT question_json FROM attempts WHERE student_id=? ORDER BY id DESC LIMIT ?", (student_id, n))
    return [json.loads(r["question_json"]).get("stem", "") for r in rows]


def _notes_ctx(student_id: int, concept_id: str) -> dict | None:
    """Relevant passages from the student's notes for this concept (None when they have no notes or the notes do not cover it)."""
    try:
        c = content.concepts()[concept_id]
        return notes_mod.context_for(student_id, f"{c['name']} {c.get('short', '')} {c['description']} {' '.join(c['key_formulas'])}")
    except Exception:  # noqa: BLE001 - notes only ever add to a question; never block it
        return None


def _last_concept(student_id: int) -> str | None:
    row = db.one("SELECT concept_id FROM attempts WHERE student_id=? AND phase='practice' ORDER BY id DESC LIMIT 1", (student_id,))
    return row["concept_id"] if row else None


def plan_next(student_id: int, review: bool = False, concept_id: str | None = None) -> dict:
    """Decide WHAT to ask next. The tutor agent (app/ps02/agent.py) does it as logged tool calls: mastery -> pick concept -> trace root cause -> difficulty."""
    return agent.decide_next(student_id, review, concept_id)


def public_question(question_id: str, q: dict, plan: dict) -> dict:
    return {"question_id": question_id, "concept_id": q["concept_id"], "concept_name": content.concepts()[q["concept_id"]]["name"], "chapter": content.concepts()[q["concept_id"]]["chapter"],
            "difficulty": q["difficulty"], "stem": q["stem"], "options": q["options"], "why": plan["why"], "source": q.get("source", "ai"), "note": q.get("note"),
            "target": {"id": q["target_mc"], "label": content.misconceptions()[q["target_mc"]]["label"]} if q.get("target_mc") else None,
            "trace": plan.get("trace", []), "root_cause": plan.get("root_cause") and {"concept_id": plan["root_cause"]["root"]["concept_id"], "name": plan["root_cause"]["root"]["name"],
                                                                                  "misconception": plan["root_cause"]["root"]["misconception"], "from": plan["root_cause"]["concept_id"], "applied": bool(plan.get("root_applied"))}}


def _store_question(student_id: int, q: dict) -> str:
    qid = uuid.uuid4().hex[:12]
    with db.get_conn() as c:
        c.execute("INSERT INTO ps02_cache (cache_key, payload, created_at) VALUES (?,?,?)", (f"q:{qid}", json.dumps({"student_id": student_id, "question": q}), time.time()))
    return qid


def _load_question(question_id: str) -> dict | None:
    row = db.one("SELECT payload FROM ps02_cache WHERE cache_key=?", (f"q:{question_id}",))
    return json.loads(row["payload"]) if row else None


def next_question(student_id: int, review: bool = False, concept_id: str | None = None, target_mc: str | None = None) -> dict:
    target_mc = target_mc if target_mc in content.misconceptions() and target_mc != "MC_UNKNOWN" else None
    plan = plan_next(student_id, review, concept_id)
    cid, diff = plan["concept_id"], plan["difficulty"]
    started = time.perf_counter()
    q = None if target_mc else question_gen.take_prefetched(student_id, cid, diff, wait_seconds=10)   # a targeted question is never the generic prefetched one
    prefetched = q is not None
    if q is None:
        active = [m["id"] for m in active_misconceptions(student_id) if cid in content.misconceptions()[m["id"]]["concept_ids"]]
        q = question_gen.generate(cid, diff, active, _recent_stems(student_id), _notes_ctx(student_id, cid), target_mc)   # only on a prefetch miss
    q = {**q, "difficulty": diff}   # the badge, the stored question, BKT and the "why" line all use the planner's one difficulty value
    plan = {**plan, "trace": plan["trace"] + agent.steps_for_generation(q, prefetched, round((time.perf_counter() - started) * 1000), target_mc)}
    return public_question(_store_question(student_id, q), q, plan)


def _prefetch_after(student_id: int) -> None:
    """While the student reads feedback / explains their thinking, start generating the question they will most likely get next."""
    try:
        plan = plan_next(student_id)
        active = [m["id"] for m in active_misconceptions(student_id) if plan["concept_id"] in content.misconceptions()[m["id"]]["concept_ids"]]
        question_gen.prefetch(student_id, plan["concept_id"], plan["difficulty"], active, _recent_stems(student_id), _notes_ctx(student_id, plan["concept_id"]))
    except Exception:  # noqa: BLE001 - an optimisation only
        pass


# ------------------------------------------------------------------ answer + reasoning (HTTP flow)
def answer(student_id: int, question_id: str, chosen_index: int, elapsed_seconds: float | None = None) -> dict:
    stored = _load_question(question_id)
    if not stored or stored["student_id"] != student_id:
        raise KeyError("question not found")
    q = stored["question"]
    result = record_answer(student_id, q, chosen_index, fast=bool(elapsed_seconds is not None and elapsed_seconds <= FAST_SECONDS))
    correct = result["correct"]
    check = correct and result["attempt_id"] % CHECK_EVERY == 0
    _prefetch_after(student_id)
    return {"attempt_id": result["attempt_id"], "correct": correct, "correct_index": q["correct_index"], "explanation": q.get("explanation", ""),
            "needs_reasoning": (not correct) or check, "reasoning_kind": "wrong" if not correct else ("check" if check else None),
            "reasoning_prompt": ("Why did you pick this? Explain your thinking in your own words, in any language." if not correct
                                 else "Nice! Quick check: how did you get this?" if check else None),
            "mastery_changes": result["deltas"], "review": result["review"], "trace": agent.steps_for_answer(result, correct, result.get("misconception_prior"))}


def _restore_srs(student_id: int, concept_id: str, row: dict | None) -> None:
    db.execute("DELETE FROM reviews WHERE student_id=? AND concept_id=?", (student_id, concept_id))
    if row:
        db.execute("INSERT INTO reviews (student_id, concept_id, easiness, interval_days, repetitions, due_at) VALUES (?,?,?,?,?,?)",
                   (student_id, concept_id, row["easiness"], row["interval_days"], row["repetitions"], row["due_at"]))


def apply_reasoning(student_id: int, attempt_id: int, reasoning: str, mode: str = "text", when: datetime | None = None, diag: dict | None = None, language: str = "hinglish") -> dict:
    """Classify the student's explanation, then replace the provisional update from ``answer`` with the informed one."""
    att = db.one("SELECT * FROM attempts WHERE id=? AND student_id=?", (attempt_id, student_id))
    if not att:
        raise KeyError("attempt not found")
    q = json.loads(att["question_json"])
    meta = json.loads(att["delta_json"] or "{}")
    cid, correct = att["concept_id"], bool(att["correct"])
    prior = None if correct else q.get("distractor_misconceptions", {}).get(str(att["chosen_index"]))

    diag = diag or misconception.classify(q, att["chosen_index"], reasoning, cid, prior, language)
    careless = (not correct) and bool(diag["is_careless_error"])
    lucky = correct and not diag["reasoning_sound"]
    mc = None if correct else (diag["misconception_id"] if diag["misconception_id"] not in ("NONE",) else None)
    confident_mc = mc if (mc and mc != "MC_UNKNOWN" and diag["confidence"] >= 0.4) else (prior if (mc is None and not careless and prior != "MC_UNKNOWN") else None)

    # roll back the provisional update and apply the informed one
    mastery = lm.get_mastery(student_id)
    for k, v in meta.get("before", {}).items():
        mastery[k] = v
    deltas = lm.apply_answer(mastery, cid, correct, att["difficulty"], misconception_id=None if correct else (confident_mc or mc), careless=careless, lucky=lucky)
    lm.save_mastery(student_id, {d["concept_id"]: mastery[d["concept_id"]] for d in deltas} | {k: mastery[k] for k in meta.get("before", {})}, when=_iso(when))
    _restore_srs(student_id, cid, meta.get("srs_before"))
    review = srs.record(student_id, cid, srs.quality(correct, careless=careless, has_misconception=bool(confident_mc), fast=False), now=when)

    final_mc = None if careless else (confident_mc or ("MC_UNKNOWN" if not correct else None))
    db.execute("UPDATE attempts SET reasoning_text=?, reasoning_mode=?, misconception_id=?, misconception_confidence=?, is_careless=?, delta_json=? WHERE id=?",
               (reasoning, mode, final_mc, diag["confidence"], 1 if careless else 0, json.dumps({**meta, "deltas": deltas}), attempt_id))
    if not correct and confident_mc:
        _note_misconception(student_id, confident_mc, diag["evidence"] or reasoning, when, mode)
    _prefetch_after(student_id)
    out = {"attempt_id": attempt_id, "diagnosis": {**diag, "misconception_id": final_mc or "NONE", "is_careless_error": careless},
           "misconception": misconception_card(final_mc) if final_mc and final_mc != "MC_UNKNOWN" else None,
           "lucky_guess": lucky, "mastery_changes": deltas, "review": review}
    out["trace"] = agent.steps_for_reasoning(out)
    return out


def reasoning_events(student_id: int, attempt_id: int, reasoning: str, mode: str = "text", language: str = "hinglish"):
    """Streaming version of apply_reasoning: ("quick", diagnosis) at once, ("delta", text) while the AI writes, then ("final", the full result)."""
    att = db.one("SELECT * FROM attempts WHERE id=? AND student_id=?", (attempt_id, student_id))
    if not att:
        raise KeyError("attempt not found")
    q = json.loads(att["question_json"])
    prior = None if att["correct"] else q.get("distractor_misconceptions", {}).get(str(att["chosen_index"]))
    diag = None
    for kind, value in misconception.classify_events(q, att["chosen_index"], reasoning, att["concept_id"], prior, language):
        if kind == "final":
            diag = value
        else:
            yield (kind, value)
    yield ("final", apply_reasoning(student_id, attempt_id, reasoning, mode, diag=diag, language=language))


# ------------------------------------------------------------------ student views
def mastery_view(student_id: int) -> dict:
    details = lm.mastery_details(student_id)
    graph = content.concepts()
    actives = active_misconceptions(student_id)
    due = {r["concept_id"] for r in srs.due_reviews(student_id) if r["due"]}
    doubts_by: dict[str, list[dict]] = {}
    for d in db.query("SELECT concept_id, question, misconception_id FROM doubts WHERE student_id=? AND concept_id IS NOT NULL ORDER BY id DESC", (student_id,)):
        doubts_by.setdefault(d["concept_id"], []).append(d)
    from app.ps02 import traps
    history_rows = [r for r in db.query("SELECT * FROM student_misconceptions WHERE student_id=? AND count>0", (student_id,)) if r["misconception_id"] in content.misconceptions()]
    nodes = []
    for cid, c in graph.items():
        mcs = [m for m in actives if cid in content.misconceptions()[m["id"]]["concept_ids"]]
        chain = [{"id": r["misconception_id"], "label": content.misconceptions()[r["misconception_id"]]["label"], "stage": traps.stage_of(r), "verified_at": r.get("verified_at")}
                 for r in history_rows if cid in content.misconceptions()[r["misconception_id"]]["concept_ids"]]
        nodes.append({**c, **details[cid], "misconceptions": mcs, "misconception_chain": chain, "review_due": cid in due,
                      "doubts_count": len(doubts_by.get(cid, [])), "recent_doubts": doubts_by.get(cid, [])[:3]})
    return {"nodes": nodes, "edges": [{"from": p, "to": c["id"]} for c in graph.values() for p in c["prerequisites"]], "chapters": list({c["chapter"] for c in graph.values()}),
            "weakest": lm.frontier_weakest({k: v["p_known"] for k, v in details.items()}, 3), "time_travel": srs.time_travel()}


def mastery_history(student_id: int, concept_id: str) -> list[dict]:
    """Sparkline data: p_known for the concept after each attempt that changed it, oldest first."""
    out = []
    for r in db.query("SELECT created_at, delta_json FROM attempts WHERE student_id=? ORDER BY id", (student_id,)):
        for d in json.loads(r["delta_json"] or "{}").get("deltas", []):
            if d["concept_id"] == concept_id:
                out.append({"at": r["created_at"], "p_known": d["after"]})
    return out
