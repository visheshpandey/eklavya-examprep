"""Ask a doubt: Eklavya's original tutor (notes RAG with a general-knowledge fallback), plus PS02 tagging.

Each doubt is tagged to a concept (so it appears on the concept's detail panel and the teacher dashboard). If the QUESTION itself reveals a
misconception ("why does the bulb use up current?") it is logged to student_misconceptions and mastery is nudged down a little.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app import db
from app.agents import voice_tutor
from app.ai import gemini
from app.domain import retrieval
from app.ps02 import content, learner_model as lm, llm, notes, service

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ps02-doubt")
TAG_DEADLINE_S = 6.0
MIN_MC_CONFIDENCE = 0.6
DOUBT_NUDGE_WEIGHT = 0.15        # a doubt that exposes a misconception is weak evidence: a small push toward "does not know"

TAG_SYSTEM = """You tag a CBSE Class 10 physics student's doubt. Given the question, return the single best concept id from the list (or null if it is not about this syllabus).
Also say whether the QUESTION ITSELF reveals one of the listed misconceptions (the student states or assumes the wrong idea, e.g. "why does the bulb use up the current?").
Only set misconception_id when the wrongness is in what the student says; a neutral question like "what is current?" has none. confidence is 0 to 1.
Return ONLY JSON: {"concept_id": "L1|...|null", "misconception_id": "MC01|...|null", "confidence": number, "evidence": "short quote"}"""


def _tag_prompt(question: str, hint: str | None) -> str:
    concepts = "\n".join(f"- {c['id']}: {c.get('short', c['name'])}: {c['description']}" for c in content.concepts().values())
    mcs = "\n".join(f"- {m['id']}: {m['description']}" for m in content.misconceptions().values() if m["id"] != "MC_UNKNOWN")
    return f"Concepts:\n{concepts}\n\nMisconceptions:\n{mcs}\n\nOn-screen hint (the concept the student was looking at, may be unrelated): {hint or 'none'}\nStudent's doubt: {question}"


def _words(text: str) -> set[str]:
    return {w for w in retrieval.tokenize(text) if len(w) > 2}


def heuristic_tag(question: str, hint: str | None) -> dict:
    """No-LLM tagging: telltale phrases for misconceptions, word overlap with concept names/descriptions for the concept."""
    said = _words(question)
    best_c, best_cs = hint, 0.0
    for c in content.concepts().values():
        pool = _words(f"{c['name']} {c.get('short', '')} {c['description']} {' '.join(c['key_formulas'])}")
        score = len(said & pool) / max(1, min(len(said), 6))
        if score > best_cs:
            best_c, best_cs = c["id"], score
    if best_cs < 0.25 and not hint:
        best_c = None
    mc_id, mc_score = None, 0.0
    for m in content.misconceptions().values():
        for phrase in m["telltale_phrases"]:
            pw = _words(phrase)
            if pw and len(pw & said) / len(pw) > mc_score:
                mc_id, mc_score = m["id"], len(pw & said) / len(pw)
    return {"concept_id": best_c, "misconception_id": mc_id if mc_score >= 0.7 else None, "confidence": round(mc_score, 2), "evidence": ""}


def tag(question: str, hint: str | None) -> dict:
    graph, mcs = content.concepts(), content.misconceptions()
    try:
        raw = llm.hedged_json(TAG_SYSTEM, _tag_prompt(question, hint), ("concept_id",), 0.1, deadline_s=TAG_DEADLINE_S)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError, gemini.LLMError) as exc:
        log.warning("Doubt tagging fell back to the heuristic: %s", str(exc)[:160])
        raw = heuristic_tag(question, hint)
    cid = raw.get("concept_id") if raw.get("concept_id") in graph else (hint if hint in graph else None)
    mc = raw.get("misconception_id") if raw.get("misconception_id") in mcs and raw.get("misconception_id") != "MC_UNKNOWN" else None
    if cid is None:
        cid = heuristic_tag(question, hint)["concept_id"]
    if cid is None and mc:
        cid = next((c for c in mcs[mc]["concept_ids"] if c in graph), None)   # the misconception itself says where it belongs
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {"concept_id": cid, "misconception_id": mc if conf >= MIN_MC_CONFIDENCE else None, "confidence": conf, "evidence": str(raw.get("evidence", ""))[:200]}


def _answer(student_id: int, user_id: int, question: str, language: str) -> dict:
    if not retrieval.has_notes(user_id):   # the original tutor insists on notes; a doubt without any is still answered, from general knowledge
        prompt = voice_tutor._general_prompt(language, question, voice_tutor._earlier(user_id))
        return voice_tutor._general(user_id, question, language, prompt, 0, 0, "No notes uploaded yet")
    return voice_tutor.ask(user_id, question, language)


def ask(student_id: int, question: str, language: str = "hinglish", concept_hint: str | None = None, mode: str = "text") -> dict:
    user_id = notes.user_id_for(student_id)
    tag_job = _pool.submit(tag, question, concept_hint)          # tagging runs while the answer is being written: no extra wait
    out = _answer(student_id, user_id, question, language)
    try:
        t = tag_job.result(timeout=TAG_DEADLINE_S + 4)
    except Exception:  # noqa: BLE001 - tagging is an extra; the answer still goes out
        t = heuristic_tag(question, concept_hint)
        t = {**t, "misconception_id": None}
    cid, mc_id = t["concept_id"], t["misconception_id"]
    db.execute("UPDATE doubts SET student_id=?, concept_id=?, misconception_id=?, mode=? WHERE id=?", (student_id, cid, mc_id, mode, out["doubt_id"]))

    changes = []
    if mc_id and cid:
        service._note_misconception(student_id, mc_id, question)
        mastery = lm.get_mastery(student_id)
        graph = content.concepts()
        before = mastery[cid]
        after = round(lm.bkt_update(before, False, weight=DOUBT_NUDGE_WEIGHT), 4)
        if after < before:
            lm.save_mastery(student_id, {cid: after})
            changes.append({"concept_id": cid, "name": graph[cid]["name"], "before": round(before, 4), "after": after, "reason": "a doubt that shows a misconception"})

    doc_name = None
    if out.get("source_document"):
        row = db.one("SELECT file_name FROM documents WHERE id=?", (out["source_document"],))
        doc_name = row["file_name"] if row else None
    graph = content.concepts()
    return {
        "doubt_id": out["doubt_id"], "answer": out["answer"], "follow_up_question": out.get("follow_up_question"), "grounded": bool(out.get("grounded")),
        "general": bool(out.get("general")), "sources": out.get("sources", []), "source_topic": out.get("source_topic"), "source_document": out.get("source_document"),
        "source_document_name": doc_name, "notes_available": retrieval.has_notes(user_id),
        "concept": {"id": cid, "name": graph[cid]["name"], "short": graph[cid].get("short")} if cid else None,
        "misconception": service.misconception_card(mc_id) if mc_id else None, "mastery_changes": changes,
    }


def list_doubts(student_id: int, concept_id: str | None = None, limit: int = 20) -> dict:
    sql, args = "SELECT id, question, answer, concept_id, misconception_id, grounded, created_at FROM doubts WHERE student_id=?", [student_id]
    if concept_id:
        sql += " AND concept_id=?"
        args.append(concept_id)
    rows = db.query(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
    total = db.one("SELECT COUNT(*) AS n FROM doubts WHERE student_id=?" + (" AND concept_id=?" if concept_id else ""), tuple(args))["n"]
    return {"doubts": [{**r, "grounded": bool(r["grounded"])} for r in rows], "total": total}


def counts_by_concept(student_ids: list[int] | None = None) -> dict[str, int]:
    rows = db.query("SELECT concept_id, COUNT(*) AS n FROM doubts WHERE student_id IS NOT NULL AND concept_id IS NOT NULL GROUP BY concept_id")
    if student_ids is not None:
        marks = ",".join("?" * len(student_ids)) or "NULL"
        rows = db.query(f"SELECT concept_id, COUNT(*) AS n FROM doubts WHERE student_id IN ({marks}) AND concept_id IS NOT NULL GROUP BY concept_id", tuple(student_ids))
    return {r["concept_id"]: r["n"] for r in rows}
