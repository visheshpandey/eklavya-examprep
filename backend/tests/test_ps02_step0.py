"""Step 0 of the final build: questions aimed at a misconception, and a demo class whose mastery is consistent along the prerequisite graph."""
import json

import pytest
from fastapi.testclient import TestClient

from app.ai import gemini
from app.main import create_app
from app.ps02 import content, question_gen, seed, service

client = TestClient(create_app())


def question(stem, mapping):
    return {"stem": stem, "options": ["a", "b", "c", "d"], "correct_index": 3, "distractor_misconceptions": mapping, "difficulty": 1, "explanation": "e"}


def test_a_targeted_question_is_retried_until_a_wrong_option_is_built_from_the_misconception(monkeypatch):
    replies = iter([question("Untargeted question A?", {"0": "MC_UNKNOWN", "1": "MC_UNKNOWN", "2": "MC_UNKNOWN"}),
                    question("Targeted question B?", {"0": "MC01", "1": "MC01", "2": "MC_UNKNOWN"})])
    seen_prompts = []

    def fake(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        seen_prompts.append(prompt)
        return next(replies)
    monkeypatch.setattr(gemini, "llm_json", fake)
    q = question_gen.generate("C1", 1, [], [], None, "MC01")
    assert q["stem"] == "Targeted question B?" and q["target_mc"] == "MC01"
    assert list(q["distractor_misconceptions"].values()).count("MC01") == 2
    assert "TARGET" in seen_prompts[0] and "MC01" in seen_prompts[0] and "TWO of the three wrong options" in seen_prompts[0]


def test_an_unknown_target_is_ignored_and_an_untargeted_prompt_has_no_target_line(monkeypatch):
    prompts = []
    monkeypatch.setattr(gemini, "llm_json", lambda s, p, *a, **k: prompts.append(p) or question("Plain question?", {"0": "MC01", "1": "MC_UNKNOWN", "2": "MC_UNKNOWN"}))
    q = question_gen.generate("C1", 1, [], [], None, "NOT_A_REAL_MC")
    assert q["target_mc"] is None and "TARGET" not in prompts[0]


def test_next_question_can_be_aimed_and_says_so_in_the_thinking_panel(monkeypatch):
    n = {"i": 0}

    def fake(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        n["i"] += 1
        return question(f"Aimed question number {n['i']}?", {"0": "MC01", "1": "MC01", "2": "MC_UNKNOWN"})
    monkeypatch.setattr(gemini, "llm_json", fake)
    sid = service.create_student("Aimer", "9-Z")["id"]
    client.post("/api/diagnostic/submit", json={"student_id": sid, "answers": []})
    for _ in range(3):                                            # the next three questions are all aimed
        q = client.get("/api/practice/next", params={"student_id": sid, "concept_id": "C1", "target_mc": "MC01"}).json()
        assert q["concept_id"] == "C1" and q["target"] == {"id": "MC01", "label": "Current gets used up"}
        assert "Aimed at “Current gets used up”" in q["trace"][-1]["summary"]
    plain = client.get("/api/practice/next", params={"student_id": sid, "concept_id": "C1"}).json()
    assert plain["target"] is None


def _fixture_mastery():
    dump = json.loads((content.DATA / "demo_class.json").read_text(encoding="utf-8"))
    by = {}
    for r in dump["mastery"]:
        by.setdefault(r["student_id"], {})[r["concept_id"]] = r["p_known"]
    names = {s["id"]: s["name"] for s in dump["students"]}
    return by, names


def test_no_demo_concept_sits_far_above_its_prerequisites():
    by, names = _fixture_mastery()
    graph = content.concepts()
    assert len(by) == 6
    for sid, m in by.items():
        for cid, c in graph.items():
            for pre in c["prerequisites"]:
                assert m[cid] <= m[pre] + seed.PREREQ_GAP + 1e-6, f"{names[sid]}: {c['name']} {m[cid]:.0%} but prerequisite {graph[pre]['name']} {m[pre]:.0%}"


def test_the_demo_class_is_still_varied_after_the_consistency_pass():
    by, _ = _fixture_mastery()
    avgs = sorted(sum(m.values()) / len(m) for m in by.values())
    assert avgs[-1] - avgs[0] > 0.2                                # a struggling student and a strong one are still different
    distinct = {round(p, 2) for m in by.values() for p in m.values()}
    assert len(distinct) > 25                                      # no wall of identical values


def test_the_demo_students_story_is_deterministic():
    """The Judge tour depends on it: Series circuits keeps going wrong, rooted in 'Current gets used up' in Charge & current."""
    from app import db
    from app.ps02 import copilot, learner_model as lm, reseed, rootcause
    reseed.reset_all()
    sid = db.one("SELECT id FROM students WHERE name='Aarav Sharma' AND is_demo=1")["id"]
    struggling = rootcause.struggling(sid)
    assert struggling == ["C5"]
    t = rootcause.trace("C5", lm.get_mastery(sid), service.active_misconceptions(sid))
    assert t["root"]["concept_id"] == "C1" and t["root"]["misconception"]["id"] == "MC01" and t["path"] == ["C5", "C3", "C1"]
    assert [p["p_known"] for p in service.mastery_history(sid, "C5")] == seed.STORY_C5_PATH
    group = next(g for g in copilot.groups("10-B")["groups"] if g["id"] == "MC01")
    assert {s["name"] for s in group["students"]} == {"Aarav Sharma", "Rohan Verma"} and group["name"] == "Group A"
