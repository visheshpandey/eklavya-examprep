"""Teacher co-pilot: close the loop between what the class holds and what the teacher does about it.

1. groups      students grouped by a shared, still-active misconception ("Group A, 3 students: believe current is used up")
2. lesson      one click -> a 10-minute mini-lesson for that group (hook demo, analogy, 3 check questions, a Hinglish teacher script), cached
3. assign      push targeted practice + a Socratic dialogue on that misconception to the group's students ("Your teacher assigned this")
4. status      after they attempt it: before -> after ("3 held MC01, 1 still holds it")
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from app import db
from app.ai import gemini
from app.ps02 import content, llm, teacher

log = logging.getLogger(__name__)
MIN_GROUP = 2
LESSON_DEADLINE_S = 25.0


def _letter(i: int) -> str:
    return chr(ord("A") + i) if i < 26 else str(i + 1)


# ------------------------------------------------------------------ groups
def _holders(student_ids: list[int]) -> dict[str, list[dict]]:
    if not student_ids:
        return {}
    marks = ",".join("?" * len(student_ids))
    rows = db.query(f"SELECT sm.student_id, sm.misconception_id, sm.count, sm.last_quote, s.name FROM student_misconceptions sm JOIN students s ON s.id = sm.student_id "
                    f"WHERE sm.student_id IN ({marks}) AND sm.resolved = 0 AND sm.count > 0 ORDER BY sm.count DESC", tuple(student_ids))
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["misconception_id"], []).append({"student_id": r["student_id"], "name": r["name"], "count": r["count"], "quote": r["last_quote"]})
    return out


def _assignment_state(class_section: str, mc_id: str) -> dict | None:
    """The latest assignment for this misconception in this class, with its before -> after numbers."""
    a = db.one("SELECT * FROM assignments WHERE class_section=? AND misconception_id=? ORDER BY id DESC LIMIT 1", (class_section, mc_id))
    if not a:
        return None
    rows = db.query("SELECT a.student_id, a.status, a.outcome, s.name FROM assignment_students a JOIN students s ON s.id = a.student_id WHERE a.assignment_id=?", (a["id"],))
    ids = [r["student_id"] for r in rows]
    still = {h["student_id"] for h in _holders(ids).get(mc_id, [])}
    return {"id": a["id"], "created_at": a["created_at"], "concept_id": a["concept_id"], "assigned": len(rows), "done": sum(1 for r in rows if r["status"] == "done"),
            "resolved": sum(1 for r in rows if r["outcome"] == "resolved"), "before": len(rows), "after": len(still),
            "students": [{"student_id": r["student_id"], "name": r["name"], "status": r["status"], "outcome": r["outcome"], "still_holds": r["student_id"] in still} for r in rows]}


def groups(class_section: str | None = None) -> dict:
    class_section = class_section or teacher.default_class()
    students = teacher.class_students(class_section)
    held = _holders([s["id"] for s in students])
    mcs = content.misconceptions()
    ranked = sorted(((mid, hs) for mid, hs in held.items() if mid in mcs and len(hs) >= MIN_GROUP), key=lambda kv: (-len(kv[1]), -sum(h["count"] for h in kv[1])))
    # a group that was assigned work stays on the dashboard even after it shrinks (that is the before -> after the teacher wants to see), emptiest last
    assigned = [r["misconception_id"] for r in db.query("SELECT DISTINCT misconception_id FROM assignments WHERE class_section=? ORDER BY misconception_id", (class_section,))]
    ranked += sorted(((mid, held.get(mid, [])) for mid in assigned if mid in mcs and mid not in {m for m, _ in ranked}), key=lambda kv: -len(kv[1]))
    out = []
    for i, (mid, hs) in enumerate(ranked):
        m = mcs[mid]
        out.append({"id": mid, "name": f"Group {_letter(i)}", "misconception": {"id": mid, "label": m["label"], "description": m["description"], "correction": m["correction"], "analogy": m["analogy"]},
                    "concept_ids": m["concept_ids"], "concept_names": [content.concepts()[c]["name"] for c in m["concept_ids"] if c in content.concepts()],
                    "students": hs, "size": len(hs), "assignment": _assignment_state(class_section, mid), "lesson_ready": _cached_lesson(class_section, mid) is not None})
    # stable order and letters: an assigned group keeps its place (ranked by its size when it was assigned), so "Group A" is still Group A after it shrinks
    out.sort(key=lambda g: (-max(g["size"], (g["assignment"] or {}).get("before", 0)), g["id"]))
    for i, g in enumerate(out):
        g["name"] = f"Group {_letter(i)}"
    singles = sum(1 for mid, hs in held.items() if mid in mcs and len(hs) < MIN_GROUP)
    return {"class_section": class_section, "groups": out, "individual_misconceptions": singles}


# ------------------------------------------------------------------ mini-lesson
LESSON_SYSTEM = """You help a CBSE Class 10 physics teacher run a 10-minute mini-lesson for a small group of students who share ONE misconception.
Make it concrete and doable with simple classroom materials. Use ONLY the facts given about the misconception; never state anything physically wrong. Write plain text only: no LaTeX and no $ signs; write maths with Unicode symbols (Ω, ², ×, ₁, ÷). 
Return ONLY JSON: {"title": str, "hook_demo": "a 2-3 minute demo or question that makes the wrong idea visibly fail", "analogy": "one clear everyday analogy",
"check_questions": [{"q": str, "a": str}, {"q": str, "a": str}, {"q": str, "a": str}], "script_hinglish": "what the teacher can SAY, in friendly Hinglish (Roman script), about 120-160 words, step by step through the 10 minutes",
"board_notes": [str, str, str]}"""


def _cached_lesson(class_section: str, mc_id: str) -> dict | None:
    row = db.one("SELECT payload FROM ps02_cache WHERE cache_key=?", (f"lesson:{class_section}:{mc_id}",))
    return json.loads(row["payload"]) if row else None


def _fallback_lesson(mc: dict) -> dict:
    """The same shape without the model, built from the hand-written catalogue entry."""
    return {"title": f"Fixing: {mc['label']}", "source": "catalogue",
            "hook_demo": f"Ask the group: “{mc['probe_english']}” and let them commit to an answer on paper before you reveal anything.",
            "analogy": mc["analogy"] or "Relate it to a situation the students know well and ask them to predict the outcome first.",
            "check_questions": [{"q": mc["probe_english"], "a": mc["correction"]},
                                {"q": f"In your own words, what is wrong with this idea: “{mc['description']}”?", "a": mc["correction"]},
                                {"q": "Give one everyday example that shows the correct idea.", "a": mc["analogy"] or mc["correction"]}],
            "script_hinglish": f"Aaj hum ek common galat-fehmi par baat karenge: {mc['description']} Pehle mai ek sawaal puchhta/puchhti hoon: {mc['probe_hinglish']} "
                               f"Sabko apna jawab likhne do. Ab dekhte hain sahi baat kya hai: {mc['correction']} Isse samajhne ke liye ek example: {mc['analogy']} "
                               f"Ab dobara apne jawab ko check karo aur apne shabdon mein samjhao.",
            "board_notes": [mc["label"], mc["correction"], mc["analogy"] or "Everyday example"]}


def lesson(class_section: str | None, mc_id: str, refresh: bool = False) -> dict:
    class_section = class_section or teacher.default_class()
    mc = content.misconceptions().get(mc_id)
    if not mc or mc_id == "MC_UNKNOWN":
        raise KeyError("unknown misconception")
    if not refresh:
        cached = _cached_lesson(class_section, mc_id)
        if cached:
            return {**cached, "cached": True}
    holders = _holders([s["id"] for s in teacher.class_students(class_section)]).get(mc_id, [])
    facts = (f"Misconception: {mc['label']}: {mc['description']}\nThe correct idea: {mc['correction']}\nA good analogy: {mc['analogy']}\n"
             f"Students holding it: {len(holders)}. What they said: " + "; ".join(f"“{h['quote']}”" for h in holders[:3] if h["quote"]))
    try:
        data = llm.hedged_json(LESSON_SYSTEM, facts, ("title", "hook_demo", "check_questions", "script_hinglish"), 0.5, deadline_s=LESSON_DEADLINE_S, hedge_after_s=6.0)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        questions = [{"q": str(q.get("q", "")), "a": str(q.get("a", ""))} for q in data["check_questions"] if isinstance(q, dict) and q.get("q")][:3]
        if len(questions) < 3:
            raise ValueError("need three check questions")
        out = {"title": str(data["title"]), "hook_demo": str(data["hook_demo"]), "analogy": str(data.get("analogy") or mc["analogy"]), "check_questions": questions,
               "script_hinglish": str(data["script_hinglish"]), "board_notes": [str(n) for n in data.get("board_notes", [])][:4], "source": "ai"}
    except (ValueError, TypeError, KeyError, AttributeError, gemini.LLMError) as exc:
        log.warning("Mini-lesson fell back to the catalogue version: %s", str(exc)[:160])
        return {**_fallback_lesson(mc), "cached": False}     # not cached: a retry can still get the AI version
    out["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_conn() as c:
        c.execute("DELETE FROM ps02_cache WHERE cache_key=?", (f"lesson:{class_section}:{mc_id}",))
        c.execute("INSERT INTO ps02_cache (cache_key, payload, created_at) VALUES (?,?,?)", (f"lesson:{class_section}:{mc_id}", json.dumps(out, ensure_ascii=False), time.time()))
    return {**out, "cached": False}


# ------------------------------------------------------------------ assign
def assign(class_section: str | None, mc_id: str, student_ids: list[int] | None = None) -> dict:
    class_section = class_section or teacher.default_class()
    group = next((g for g in groups(class_section)["groups"] if g["id"] == mc_id), None)
    if not group:
        raise ValueError("no group holds this misconception right now")
    members = {s["student_id"] for s in group["students"]}
    chosen = list(dict.fromkeys(student_ids)) if student_ids else sorted(members)
    if not chosen or not set(chosen) <= members:
        raise ValueError("students must belong to the group")
    concept = next((c for c in group["concept_ids"] if c in content.concepts()), None)
    existing = db.one("SELECT id FROM assignments WHERE class_section=? AND misconception_id=? ORDER BY id DESC LIMIT 1", (class_section, mc_id))
    pending = existing and db.one("SELECT 1 AS x FROM assignment_students WHERE assignment_id=? AND status='pending' LIMIT 1", (existing["id"],))
    if pending:      # an open assignment for this group already exists: top it up instead of creating a duplicate
        aid = existing["id"]
        have = {r["student_id"] for r in db.query("SELECT student_id FROM assignment_students WHERE assignment_id=?", (aid,))}
    else:
        aid = db.execute("INSERT INTO assignments (class_section, misconception_id, concept_id, created_at) VALUES (?,?,?,?)", (class_section, mc_id, concept, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        have = set()
    for sid in chosen:
        if sid not in have:
            db.execute("INSERT INTO assignment_students (assignment_id, student_id, status) VALUES (?,?,'pending')", (aid, sid))
    return {"assignment_id": aid, "topped_up": bool(pending), "students": chosen, "state": _assignment_state(class_section, mc_id)}


def student_assignments(student_id: int) -> list[dict]:
    rows = db.query("SELECT a.id, a.misconception_id, a.concept_id, a.class_section, a.created_at FROM assignments a JOIN assignment_students x ON x.assignment_id = a.id "
                    "WHERE x.student_id=? AND x.status='pending' ORDER BY a.id DESC", (student_id,))
    mcs, graph = content.misconceptions(), content.concepts()
    return [{"assignment_id": r["id"], "misconception": {"id": r["misconception_id"], "label": mcs[r["misconception_id"]]["label"]}, "concept_id": r["concept_id"],
             "concept_name": graph[r["concept_id"]]["name"] if r["concept_id"] in graph else None, "assigned_at": r["created_at"]} for r in rows]


def on_dialogue_end(student_id: int, mc_id: str, status: str) -> None:
    """A student finished the conversation about a misconception their teacher assigned: mark it done with the outcome."""
    outcome = "resolved" if status == "resolved" else "unresolved"
    db.execute("UPDATE assignment_students SET status='done', outcome=?, done_at=? WHERE student_id=? AND status='pending' AND assignment_id IN "
               "(SELECT id FROM assignments WHERE misconception_id=?)", (outcome, datetime.now(timezone.utc).isoformat(timespec="seconds"), student_id, mc_id))
