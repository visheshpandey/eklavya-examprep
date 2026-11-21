"""Loads the hand-authored static data (concept graph, misconceptions, diagnostic) once."""
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def concepts() -> dict[str, dict]:
    return {c["id"]: c for c in _load("concept_graph.json")["concepts"]}


def concept_order() -> list[str]:
    """Topological order (prerequisites first); the JSON is already listed that way, verified by tests."""
    return [c["id"] for c in _load("concept_graph.json")["concepts"]]


def misconceptions() -> dict[str, dict]:
    return {m["id"]: m for m in _load("misconceptions.json")["misconceptions"]}


def diagnostic() -> list[dict]:
    return _load("diagnostic.json")["questions"]


def dependents(concept_id: str) -> list[str]:
    return [c["id"] for c in concepts().values() if concept_id in c["prerequisites"]]


def ancestors(concept_id: str) -> set[str]:
    by_id, seen, stack = concepts(), set(), list(concepts()[concept_id]["prerequisites"])
    while stack:
        p = stack.pop()
        if p not in seen:
            seen.add(p)
            stack.extend(by_id[p]["prerequisites"])
    return seen
