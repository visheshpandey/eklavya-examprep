"""The tutor as a small agent with tools. Plain Python orchestration: every decision is a sequence of tool calls, and each call is logged
so the student can open "Eklavya's thinking" and see exactly what the tutor did and why.

Tools: get_mastery, trace_root_cause, pick_concept, calibrate_difficulty, generate_question, detect_misconception, schedule_review, start_dialogue.
(The model decides nothing here except the wording of a question or an explanation: which concept comes next is mastery + prerequisites + maths.)
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app import db
from app.ps02 import calibration, content, learner_model as lm, rootcause, srs

TOOLS = {
    "get_mastery": "Read the learner model (p_known per concept).",
    "trace_root_cause": "Walk back through the prerequisite graph and misconception history to find the real cause.",
    "pick_concept": "Choose the concept to work on.",
    "calibrate_difficulty": "Map mastery (and the last answers) to a difficulty level.",
    "generate_question": "Write a question with distractors built from misconceptions.",
    "detect_misconception": "Read the student's reasoning and name the wrong idea.",
    "schedule_review": "Set the next spaced-repetition review (SM-2).",
    "start_dialogue": "Open a Socratic conversation about the misconception.",
}


class Trace:
    """An ordered log of tool calls: [{tool, summary, ms}]."""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def call(self, tool: str, fn: Callable[[], Any], summarise: Callable[[Any], str]) -> Any:
        started = time.perf_counter()
        result = fn()
        self.steps.append({"tool": tool, "summary": summarise(result), "ms": round((time.perf_counter() - started) * 1000)})
        return result

    def note(self, tool: str, summary: str, ms: int | None = None) -> None:
        self.steps.append({"tool": tool, "summary": summary, "ms": ms})


def _pc(p: float) -> str:
    return f"{round(p * 100)}%"


def _last_practice_concept(student_id: int) -> str | None:
    row = db.one("SELECT concept_id FROM attempts WHERE student_id=? AND phase='practice' ORDER BY id DESC LIMIT 1", (student_id,))
    return row["concept_id"] if row else None


def decide_next(student_id: int, review: bool = False, concept_id: str | None = None) -> dict:
    """Decide WHAT to ask next. Returns {concept_id, difficulty, why, trace, root_cause}."""
    graph, mcs = content.concepts(), content.misconceptions()
    t = Trace()
    mastery = t.call("get_mastery", lambda: lm.get_mastery(student_id),
                     lambda m: "Checked mastery across {} concepts; lowest: {}".format(len(m), ", ".join(f"{graph[c].get('short', graph[c]['name'])} {_pc(m[c])}" for c in sorted(m, key=m.get)[:3])))

    reason, root_cause, focus, applied = "", None, None, False
    if concept_id and concept_id in mastery:
        cid = t.call("pick_concept", lambda: concept_id, lambda c: f"You chose {graph[c]['name']}")
        reason = "You picked this concept. "
    else:
        cid = None
        if review:
            due = [r for r in srs.due_reviews(student_id) if r["due"]]
            if due:
                cid = t.call("pick_concept", lambda: due[0]["concept_id"], lambda c: f"{graph[c]['name']} is due for review (SM-2)")
                reason = "This concept is due for review (spaced repetition). "
        if not cid:
            options = lm.frontier_weakest(mastery, 3)
            last = _last_practice_concept(student_id)
            focus = t.call("pick_concept", lambda: next((c for c in options if c != last), options[0]),
                           lambda c: f"Weakest concept you are ready for: {graph[c]['name']} ({_pc(mastery[c])})")
            cid = focus
            active = _active(student_id)
            traced = t.call("trace_root_cause", lambda: rootcause.trace(focus, mastery, active),
                            lambda r: (f"Root cause: {r['root']['name']}" + (f" ({r['root']['misconception']['label']})" if r["root"]["misconception"] else " (weak basics)")
                                       + f", {round(r['root']['score'] * 100)} points of evidence" if r["root"] else "No deeper cause found: the problem is in this concept itself"))
            if traced["root"] and traced["root"]["misconception"] and traced["root"]["concept_id"] != focus:
                root_cause, cid, applied = traced, traced["root"]["concept_id"], True
                t.note("pick_concept", f"Switched to the root concept: {graph[cid]['name']}, because {mcs[traced['root']['misconception']['id']]['label'].lower()} is what is holding {graph[focus]['name']} back")
                reason = f"{graph[focus]['name']} keeps going wrong; the root cause is “{traced['root']['misconception']['label']}” in {graph[cid]['name']}. "

    if root_cause is None:   # the student chose the concept (or it is due): keep it, but still say what the root cause looks like
        suggestion = t.call("trace_root_cause", lambda: rootcause.trace(cid, mastery, _active(student_id)),
                            lambda r: (f"If {graph[cid]['name']} keeps going wrong, look at {r['root']['name']} first ({r['root']['misconception']['label']})"
                                       if r["root"] and r["root"]["misconception"] else "No deeper cause found for this concept"))
        if suggestion["root"] and suggestion["root"]["misconception"] and suggestion["root"]["concept_id"] != cid:
            root_cause = suggestion
            applied = False
    difficulty, why = t.call("calibrate_difficulty", lambda: calibration.target_difficulty(student_id, cid, mastery[cid]),
                             lambda r: f"{_pc(mastery[cid])} mastery on {graph[cid]['name']} → difficulty {r[0]}")
    return {"concept_id": cid, "difficulty": difficulty, "why": (reason + why).strip(), "trace": t.steps, "focus_concept": focus, "root_cause": root_cause, "root_applied": applied}


def _active(student_id: int) -> list[dict]:
    from app.ps02 import service   # late import: service imports this module
    return service.active_misconceptions(student_id)


# ------------------------------------------------------------------ steps recorded after the question was served / answered
def steps_for_generation(q: dict, prefetched: bool, ms: int) -> list[dict]:
    mcs = content.misconceptions()
    used = [mcs[m]["label"] for m in dict.fromkeys(q.get("distractor_misconceptions", {}).values()) if m in mcs and m != "MC_UNKNOWN"]
    src = q.get("source", "ai")
    if src == "ai":
        text = ("Used the question generated while you were reading the last one" if prefetched else "Generated a question") + (f", with wrong options built from: {', '.join(used)}" if used else "")
    else:
        text = "The AI was slow, so I used a prepared question"
    if q.get("note"):
        text += f". Grounded in your notes: {q['note']['file_name']}"
    return [{"tool": "generate_question", "summary": text, "ms": ms}]


def steps_for_answer(result: dict, correct: bool, prior: str | None) -> list[dict]:
    mcs = content.misconceptions()
    steps = []
    deltas = result["deltas"]
    main = deltas[0]
    steps.append({"tool": "update_mastery", "summary": f"{'Correct' if correct else 'Wrong'}: {main['name']} {_pc(main['before'])} → {_pc(main['after'])}"
                  + (f" (the option you picked is built from “{mcs[prior]['label']}”, so I assumed that for now)" if prior and prior in mcs and prior != "MC_UNKNOWN" else "")
                  + "".join(f"; also {d['name']} {_pc(d['before'])} → {_pc(d['after'])} (prerequisite)" for d in deltas[1:]), "ms": None})
    r = result["review"]
    steps.append({"tool": "schedule_review", "summary": f"Next review of this concept in {r['interval_days']:g} {'minute' if srs.time_travel() else 'day'}{'' if r['interval_days'] == 1 else 's'} (SM-2)", "ms": None})
    return steps


def steps_for_reasoning(result: dict) -> list[dict]:
    d, mcs = result["diagnosis"], content.misconceptions()
    steps = []
    if d["is_careless_error"]:
        steps.append({"tool": "detect_misconception", "summary": "Your reasoning was right: treated as a slip, small penalty only", "ms": None})
    elif result.get("misconception"):
        steps.append({"tool": "detect_misconception", "summary": f"“{result['misconception']['label']}” ({d.get('confidence_label', 'Medium')} confidence, {d.get('source', 'ai')}) from: “{(d.get('evidence') or '')[:80]}”", "ms": None})
    else:
        steps.append({"tool": "detect_misconception", "summary": f"No known misconception matched: {d.get('label') or 'new pattern'}", "ms": None})
    main = result["mastery_changes"][0]
    steps.append({"tool": "update_mastery", "summary": f"Revised with your explanation: {main['name']} {_pc(main['before'])} → {_pc(main['after'])}", "ms": None})
    steps.append({"tool": "schedule_review", "summary": "Review rescheduled from the quality of your reasoning (SM-2)", "ms": None})
    if result.get("misconception") and not d["is_careless_error"]:
        steps.append({"tool": "start_dialogue", "summary": "Opening a short conversation so you un-learn it yourself", "ms": None})
    return steps
