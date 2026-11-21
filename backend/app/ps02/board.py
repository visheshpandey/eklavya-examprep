"""🎯 Board-exam marks impact. Turns mastery into an estimated CBSE Class 10 Physics score and ranks misconceptions by the marks fixing them could win back.

The weightage in data/board_weightage.json is APPROXIMATE (a typical paper pattern, not an official scheme) and everything shown from it is labelled as an estimate.
"""
from __future__ import annotations

from app.ps02 import content, learner_model as lm, service

RECOVER = 0.6          # fixing a misconception wins back about 60% of the marks still missing on its concepts
DEPENDENT_WEIGHT = 0.5  # concepts that build directly on the fixed one benefit half as much


def _data() -> dict:
    return content._load("board_weightage.json")


def marks() -> dict[str, float]:
    return _data()["marks"]


def _dependents() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cid, c in content.concepts().items():
        for p in c["prerequisites"]:
            out.setdefault(p, []).append(cid)
    return out


def _uncertainty(attempts: int) -> float:
    """How far the estimate could be off, as a share of mastery: wide with no evidence, narrower as the student answers more."""
    return max(0.06, 0.28 / (1 + attempts) ** 0.5)


def marks_gain(mc_id: str, p: dict[str, float]) -> float:
    """Estimated marks won back by fixing one misconception, given the student's mastery."""
    m, deps = marks(), _dependents()
    direct = set(content.misconceptions()[mc_id]["concept_ids"])
    nxt = {d for c in direct for d in deps.get(c, [])} - direct
    gain = sum(m[c] * (1 - p[c]) * RECOVER for c in direct) + sum(m[c] * (1 - p[c]) * RECOVER * DEPENDENT_WEIGHT for c in nxt)
    return round(gain, 1)


def student_board(student_id: int) -> dict:
    details = lm.mastery_details(student_id)
    p = {c: d["p_known"] for c, d in details.items()}
    m = marks()
    graph = content.concepts()
    total = sum(m.values())
    predicted = sum(m[c] * p[c] for c in m)
    low = sum(m[c] * max(0.0, p[c] - _uncertainty(details[c]["attempts"])) for c in m)
    high = sum(m[c] * min(1.0, p[c] + _uncertainty(details[c]["attempts"])) for c in m)
    chapters: dict[str, dict] = {}
    for c in m:
        ch = chapters.setdefault(graph[c]["chapter"], {"chapter": graph[c]["chapter"], "marks": 0.0, "predicted": 0.0})
        ch["marks"] += m[c]
        ch["predicted"] += m[c] * p[c]
    fixes = []
    for a in service.active_misconceptions(student_id):
        g = marks_gain(a["id"], p)
        cid = next((c for c in content.misconceptions()[a["id"]]["concept_ids"] if c in m), None)
        fixes.append({"misconception_id": a["id"], "label": a["label"], "concept_id": cid, "concept_name": graph[cid]["name"] if cid else None, "marks": g})
    fixes.sort(key=lambda f: -f["marks"])
    for i, f in enumerate(fixes, 1):
        f["rank"] = i
    return {"label": _data()["label"], "approximate": True, "total": round(total, 1), "predicted": round(predicted, 1), "low": round(low, 1), "high": round(min(high, total), 1),
            "chapters": [{"chapter": c["chapter"], "marks": round(c["marks"], 2), "predicted": round(c["predicted"], 1)} for c in chapters.values()],
            "fixes": fixes, "top_fix": fixes[0] if fixes else None}


def class_board(student_ids: list[int]) -> dict:
    """Class average predicted score and the top misconceptions by total marks at stake across the class."""
    if not student_ids:
        return {"label": _data()["label"], "approximate": True, "total": round(sum(marks().values()), 1), "predicted_avg": 0.0, "top": []}
    boards = [student_board(sid) for sid in student_ids]
    agg: dict[str, dict] = {}
    for b in boards:
        for f in b["fixes"]:
            a = agg.setdefault(f["misconception_id"], {"misconception_id": f["misconception_id"], "label": f["label"], "students": 0, "marks": 0.0})
            a["students"] += 1
            a["marks"] += f["marks"]
    top = sorted(({**a, "marks": round(a["marks"], 1), "marks_each": round(a["marks"] / a["students"], 1)} for a in agg.values()), key=lambda a: -a["marks"])[:3]
    return {"label": _data()["label"], "approximate": True, "total": boards[0]["total"], "predicted_avg": round(sum(b["predicted"] for b in boards) / len(boards), 1), "top": top}
