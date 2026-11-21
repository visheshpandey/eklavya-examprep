"""Teacher analytics: class heatmap, concept gaps, top misconceptions with quotes, at-risk students, and an LLM 'reteach tomorrow' plan."""
from __future__ import annotations

import json
import logging
import time

from app import db
from app.ai import gemini
from app.ps02 import board, content, learner_model as lm

log = logging.getLogger(__name__)
RETEACH_TTL = 3600


def class_students(class_section: str) -> list[dict]:
    return db.query("SELECT id, name, class_section FROM students WHERE class_section=? ORDER BY id", (class_section,))


def default_class() -> str:
    row = db.one("SELECT class_section FROM students WHERE class_section<>'' ORDER BY is_demo DESC, id LIMIT 1")
    return row["class_section"] if row else "10-B"


def overview(class_section: str | None = None) -> dict:
    class_section = class_section or default_class()
    students = class_students(class_section)
    graph = content.concepts()
    order = content.concept_order()
    matrix = []
    mc_students: dict[str, list[dict]] = {}
    risk = []
    for s in students:
        m = lm.get_mastery(s["id"])
        actives = db.query("SELECT misconception_id, count, last_quote, last_source FROM student_misconceptions WHERE student_id=? AND resolved=0 AND count>0", (s["id"],))
        for a in actives:
            mc_students.setdefault(a["misconception_id"], []).append({"student": s["name"], "student_id": s["id"], "quote": a["last_quote"], "count": a["count"], "source": a["last_source"]})
        avg = sum(m.values()) / len(m)
        matrix.append({"student_id": s["id"], "name": s["name"], "mastery": {c: round(m[c], 3) for c in order}, "average": round(avg, 3)})
        risk.append({"student_id": s["id"], "name": s["name"], "average": round(avg, 3), "active_misconceptions": len(actives),
                     "weakest": [{"concept_id": c, "name": graph[c]["name"], "p_known": round(m[c], 3)} for c in sorted(m, key=m.get)[:3]],
                     "risk_score": round((1 - avg) * 100 + 8 * len(actives), 1)})
    n = max(1, len(students))
    gaps = sorted(({"concept_id": c, "name": graph[c]["name"], "chapter": graph[c]["chapter"],
                    "average": round(sum(r["mastery"][c] for r in matrix) / n, 3),
                    "below_half": sum(1 for r in matrix if r["mastery"][c] < 0.5)} for c in order), key=lambda g: g["average"])
    mcs = content.misconceptions()
    mcs_all = mcs
    top = sorted(({"id": mid, "label": mcs[mid]["label"], "description": mcs[mid]["description"], "concept_ids": mcs[mid]["concept_ids"], "students": len(v),
                   "examples": v[:3]} for mid, v in mc_students.items() if mid in mcs), key=lambda x: -x["students"])
    ids = [s["id"] for s in students]
    marks = ",".join("?" * len(ids)) or "NULL"
    counts = {r["concept_id"]: r["n"] for r in db.query(f"SELECT concept_id, COUNT(*) AS n FROM doubts WHERE student_id IN ({marks}) AND concept_id IS NOT NULL GROUP BY concept_id", tuple(ids))}
    recent = db.query(f"SELECT d.question, d.concept_id, d.misconception_id, s.name AS student FROM doubts d JOIN students s ON s.id = d.student_id WHERE d.student_id IN ({marks}) ORDER BY d.id DESC LIMIT 8", tuple(ids))
    doubts = {"total": db.one(f"SELECT COUNT(*) AS n FROM doubts WHERE student_id IN ({marks})", tuple(ids))["n"],
              "by_concept": sorted(({"concept_id": c, "name": graph[c]["name"], "count": n} for c, n in counts.items()), key=lambda x: -x["count"]),
              "recent": [{"student": r["student"], "question": r["question"], "concept_name": graph[r["concept_id"]]["name"] if r["concept_id"] else None,
                          "misconception": mcs_all[r["misconception_id"]]["label"] if r["misconception_id"] in mcs_all else None} for r in recent]}
    return {"class_section": class_section, "doubts": doubts, "student_count": len(students), "concepts": [{"id": c, "name": graph[c]["name"], "chapter": graph[c]["chapter"]} for c in order],
            "board": board.class_board(ids), "heatmap": matrix, "gaps": gaps, "top_misconceptions": top, "at_risk": sorted(risk, key=lambda r: -r["risk_score"])[:5]}


# ------------------------------------------------------------------ reteach plan
SYSTEM = """You help a CBSE Class 10 physics teacher plan tomorrow's reteaching, from class-wide data.
For each of the top gaps/misconceptions give: what to reteach, ONE concrete demo or analogy a teacher can do in class with simple materials, and 2 quick check questions
(short, with the expected answer). Keep it practical and brief. Write plain text only: no LaTeX and no $ signs; write maths with Unicode symbols (Ω, ², ×, ₁, ÷). Return ONLY JSON:
{"headline": str, "items": [{"topic": str, "why": str, "demo": str, "check_questions": [{"q": str, "a": str}]}]}"""


def _static_plan(ov: dict) -> dict:
    items = [{"topic": g["name"], "why": f"Class average {round(g['average'] * 100)}%; {g['below_half']} of {ov['student_count']} students below 50%.",
              "demo": "Re-explain with a worked example on the board, then let students try one in pairs.", "check_questions": []} for g in ov["gaps"][:3]]
    return {"headline": "Reteach the weakest concepts first", "items": items}


def reteach(class_section: str | None = None, force: bool = False) -> dict:
    ov = overview(class_section)
    key = f"reteach:{ov['class_section']}:{int(time.time() // RETEACH_TTL)}"
    if not force:
        row = db.one("SELECT payload FROM ps02_cache WHERE cache_key=?", (key,))
        if row:
            return {**json.loads(row["payload"]), "cached": True}
    gaps = ov["gaps"][:3]
    mcs = ov["top_misconceptions"][:3]
    prompt = ("Top class gaps (lowest average mastery):\n" + "\n".join(f"- {g['name']}: {round(g['average'] * 100)}% average, {g['below_half']}/{ov['student_count']} below 50%" for g in gaps)
              + "\nTop misconceptions:\n" + "\n".join(f"- {m['label']}: {m['description']} ({m['students']} students; e.g. \"{(m['examples'][0]['quote'] if m['examples'] else '')}\")" for m in mcs))
    try:
        data = gemini.llm_json(SYSTEM, prompt, required_keys=("items",), temperature=0.5, timeout_ms=20000)
        plan = {"headline": str(data.get("headline", "Reteach plan")), "items": list(data["items"])[:3], "source": "ai"}
    except Exception as exc:  # noqa: BLE001 - the dashboard must never dead-end: show a plain top-gaps list instead
        log.warning("Reteach plan fell back to the static list: %s", str(exc)[:200])
        return {**_static_plan(ov), "source": "static", "cached": False}
    with db.get_conn() as c:
        c.execute("DELETE FROM ps02_cache WHERE cache_key=?", (key,))
        c.execute("INSERT INTO ps02_cache (cache_key, payload, created_at) VALUES (?,?,?)", (key, json.dumps(plan), time.time()))
    return {**plan, "cached": False}
