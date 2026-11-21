"""Root-cause tracer: when a student keeps failing a concept, walk BACK through the prerequisite graph and the student's misconception history
to find what is really wrong ("you don't have a series-circuits problem: you believe current gets used up, in Charge & current").

Scoring (deterministic): for every ancestor A of the failing concept,
    score(A) = (1 - p_known(A)) x evidence(A) x DECAY^(distance - 1)
where evidence(A) = 1 - 0.5^(number of times the student has shown an active misconception that belongs to A), or a small baseline when A has none.
Only the one-or-two-line explanation is written by the LLM; the choice of root is plain maths.
"""
from __future__ import annotations

import logging
from collections import deque

from app.ai import gemini
from app.ps02 import content, learner_model as lm, llm

log = logging.getLogger(__name__)
DECAY = 0.8
BASE_EVIDENCE = 0.15          # a weak prerequisite with no known misconception still counts a little
MIN_ROOT_SCORE = 0.2          # below this there is no convincing deeper cause
STRUGGLE_P = 0.4
_explain_cache: dict[tuple, str] = {}


def _bfs(concept_id: str) -> tuple[dict[str, int], dict[str, str]]:
    """Distance of every ancestor from ``concept_id`` and, for each, the node one step closer to it (to rebuild the path)."""
    graph = content.concepts()
    dist, via, queue = {concept_id: 0}, {}, deque([concept_id])
    while queue:
        cur = queue.popleft()
        for pre in graph[cur]["prerequisites"]:
            if pre not in dist:
                dist[pre], via[pre] = dist[cur] + 1, cur
                queue.append(pre)
    dist.pop(concept_id)
    return dist, via


def _path(concept_id: str, root: str, via: dict[str, str]) -> list[str]:
    """concept -> ... -> root along prerequisite edges."""
    nodes, cur = [root], root
    while cur != concept_id:
        cur = via[cur]
        nodes.append(cur)
    return list(reversed(nodes))


def trace(concept_id: str, mastery: dict[str, float], active: list[dict]) -> dict:
    """Pure: the ranked ancestors and the chosen root cause (or None). ``active`` = the student's unresolved misconceptions (service.active_misconceptions)."""
    graph, mcs = content.concepts(), content.misconceptions()
    dist, via = _bfs(concept_id)
    candidates = []
    for anc, d in dist.items():
        held = [m for m in active if anc in mcs[m["id"]]["concept_ids"]]
        times = sum(m["count"] for m in held)
        evidence = 1 - 0.5 ** times if held else BASE_EVIDENCE
        score = (1 - mastery.get(anc, lm.DEFAULT_P)) * evidence * DECAY ** (d - 1)
        top = max(held, key=lambda m: m["count"], default=None)
        candidates.append({"concept_id": anc, "name": graph[anc]["name"], "short": graph[anc].get("short"), "p_known": round(mastery.get(anc, lm.DEFAULT_P), 3), "distance": d,
                           "evidence": round(evidence, 3), "score": round(score, 3), "misconception": {"id": top["id"], "label": top["label"], "quote": top.get("quote")} if top else None})
    candidates.sort(key=lambda c: -c["score"])
    root = candidates[0] if candidates and candidates[0]["score"] >= MIN_ROOT_SCORE else None
    return {"concept_id": concept_id, "name": graph[concept_id]["name"], "p_known": round(mastery.get(concept_id, lm.DEFAULT_P), 3),
            "root": root, "path": _path(concept_id, root["concept_id"], via) if root else [concept_id], "candidates": candidates[:3]}


SYSTEM = """You are Eklavya, a physics tutor. In ONE or TWO short sentences, in the requested language, tell the student what is really wrong, in the form:
"You don't have a <failing concept> problem. You believe <the wrong idea in plain words> (in <root concept>). Fix that and <failing concept> will follow."
Use ONLY the facts given. If no misconception is named, say the <root concept> basics are weak and need fixing first. Friendly, never harsh.
Return ONLY JSON: {"text": str}"""


def template(t: dict, language: str = "hinglish") -> str:
    """The same sentence without the LLM (used when the model is slow or down)."""
    root = t["root"]
    if not root:
        return f"{t['name']} needs more practice. Keep going on it."
    idea = (root["misconception"] or {}).get("label")
    if language == "english":
        return (f"You don't have a {t['name']} problem. " + (f"The idea “{idea}” in {root['name']} is the cause. " if idea else f"Your {root['name']} basics are weak. ") + f"Fix that first and {t['name']} will follow.")
    return (f"Tumhe {t['name']} ki problem nahi hai. " + (f"Asli wajah “{idea}” hai, {root['name']} mein. " if idea else f"{root['name']} ke basics kamzor hain. ") + f"Pehle use theek karo, to {t['name']} khud aasan ho jayega.")


def explain(t: dict, language: str = "hinglish") -> tuple[str, str]:
    """(sentence, source) with source 'ai' or 'template'. Cached per (concept, root, misconception, language)."""
    root = t["root"]
    if not root:
        return template(t, language), "template"
    key = (t["concept_id"], root["concept_id"], (root["misconception"] or {}).get("id"), language)
    if key in _explain_cache:
        return _explain_cache[key], "ai"
    facts = (f"Language: {'English' if language == 'english' else 'Hinglish (Roman script)'}\nFailing concept: {t['name']} ({round(t['p_known'] * 100)}% mastery)\n"
             f"Root concept: {root['name']} ({round(root['p_known'] * 100)}% mastery)\nMisconception there: {(root['misconception'] or {}).get('label', 'none recorded')}"
             + (f"\nIt showed up as: “{root['misconception']['quote']}”" if root["misconception"] and root["misconception"].get("quote") else ""))
    try:
        data = llm.hedged_json(SYSTEM, facts, ("text",), 0.4, deadline_s=5.0)
        text = str(data["text"]).strip() if isinstance(data, dict) else ""
        if len(text) < 15:
            raise ValueError("too short")
        _explain_cache[key] = text
        return text, "ai"
    except (ValueError, TypeError, KeyError, gemini.LLMError) as exc:
        log.warning("Root-cause explanation fell back to the template: %s", str(exc)[:160])
        return template(t, language), "template"


def struggling(student_id: int, limit: int = 3) -> list[str]:
    """Concepts the student keeps failing: two or more misses in their recent practice, or low mastery after real attempts. Worst first."""
    from app import db
    mastery = lm.get_mastery(student_id)
    details = lm.mastery_details(student_id)
    recent = db.query("SELECT concept_id, correct FROM attempts WHERE student_id=? AND phase='practice' ORDER BY id DESC LIMIT 12", (student_id,))
    misses: dict[str, int] = {}
    for r in recent:
        if not r["correct"]:
            misses[r["concept_id"]] = misses.get(r["concept_id"], 0) + 1
    out = [c for c in content.concept_order() if misses.get(c, 0) >= 2 or (details[c]["attempts"] >= 2 and mastery[c] < STRUGGLE_P)]
    return sorted(out, key=lambda c: mastery[c])[:limit]
