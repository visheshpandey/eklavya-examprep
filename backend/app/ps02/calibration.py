"""Difficulty calibration: mastery -> target difficulty (aim ~70% expected success), nudged by recent streaks, plus a plain-language why."""
from app import db
from app.ps02 import content


def base_difficulty(p: float) -> int:
    return 1 if p < 0.4 else 2 if p <= 0.7 else 3


def adjust_for_streak(base: int, recent: list[dict]) -> int:
    """``recent`` = this student's attempts, newest first. Last 3 at this level all correct -> up; 2 wrong in a row -> down."""
    at_level = [a for a in recent if a["difficulty"] == base]
    if len(at_level) >= 3 and all(a["correct"] for a in at_level[:3]):
        return min(3, base + 1)
    if len(at_level) >= 2 and not at_level[0]["correct"] and not at_level[1]["correct"]:
        return max(1, base - 1)
    return base


def recent_attempts(student_id: int, limit: int = 12) -> list[dict]:
    return db.query("SELECT concept_id, difficulty, correct FROM attempts WHERE student_id=? AND phase='practice' ORDER BY id DESC LIMIT ?",
                    (student_id, limit))


def why(concept_id: str, p: float, base: int, final: int) -> str:
    graph = content.concepts()
    deps = [graph[d]["name"] for d in content.dependents(concept_id)]
    link = f" (prerequisite for {deps[0]})" if deps else ""
    text = f"You're at {round(p * 100)}% on {graph[concept_id]['name']}{link} → difficulty {final}."
    if final > base:
        text += " You got the last 3 right, so we're stepping up."
    elif final < base:
        text += " Two misses in a row, so we're stepping down."
    return text


def target_difficulty(student_id: int, concept_id: str, p: float) -> tuple[int, str]:
    base = base_difficulty(p)
    final = adjust_for_streak(base, recent_attempts(student_id))
    return final, why(concept_id, p, base, final)
