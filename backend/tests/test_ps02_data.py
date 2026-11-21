"""Validates the hand-authored PS02 data files: graph, misconceptions, diagnostic."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


GRAPH = load("concept_graph.json")["concepts"]
MCS = load("misconceptions.json")["misconceptions"]
QS = load("diagnostic.json")["questions"]
CONCEPT_IDS = {c["id"] for c in GRAPH}
MC_IDS = {m["id"] for m in MCS}


def ancestors(cid, by_id):
    seen, stack = set(), list(by_id[cid]["prerequisites"])
    while stack:
        p = stack.pop()
        if p not in seen:
            seen.add(p)
            stack.extend(by_id[p]["prerequisites"])
    return seen


def test_graph_shape():
    assert len(GRAPH) == 21
    assert len(CONCEPT_IDS) == 21
    for c in GRAPH:
        assert {"id", "name", "chapter", "prerequisites", "description", "key_formulas"} <= c.keys()
        assert set(c["prerequisites"]) <= CONCEPT_IDS


def test_graph_is_acyclic():
    by_id = {c["id"]: c for c in GRAPH}
    for cid in by_id:
        assert cid not in ancestors(cid, by_id)


def test_misconceptions_reference_real_concepts():
    assert "MC_UNKNOWN" in MC_IDS
    for m in MCS:
        assert set(m["concept_ids"]) <= CONCEPT_IDS
        assert m["correction"]
    for i in range(1, 20):
        assert f"MC{i:02d}" in MC_IDS


def test_diagnostic_questions_valid():
    assert len(QS) == 14
    assert {q["concept_id"] for q in QS} <= CONCEPT_IDS
    for q in QS:
        assert len(q["options"]) == 4 and len(set(q["options"])) == 4
        assert 0 <= q["correct_index"] < 4
        assert q["difficulty"] in (1, 2, 3)
        wrong = {str(i) for i in range(4)} - {str(q["correct_index"])}
        assert set(q["distractor_misconceptions"]) == wrong, q["id"]
        assert set(q["distractor_misconceptions"].values()) <= MC_IDS
        assert q["explanation"]


def test_distractor_misconceptions_match_question_concept():
    by_id = {c["id"]: c for c in GRAPH}
    mc = {m["id"]: m for m in MCS}
    for q in QS:
        allowed = {q["concept_id"]} | ancestors(q["concept_id"], by_id)
        for m in q["distractor_misconceptions"].values():
            if m != "MC_UNKNOWN":
                assert set(mc[m]["concept_ids"]) & allowed, (q["id"], m)


def test_every_concept_is_covered_by_a_question_or_ancestor():
    by_id = {c["id"]: c for c in GRAPH}
    tested = {q["concept_id"] for q in QS}
    for cid in CONCEPT_IDS:
        assert cid in tested or ancestors(cid, by_id) & tested, cid


def test_all_chapters_covered():
    chapters = {c["chapter"] for c in GRAPH if c["id"] in {q["concept_id"] for q in QS}}
    assert chapters == {"Light", "Human Eye", "Electricity", "Magnetism"}
