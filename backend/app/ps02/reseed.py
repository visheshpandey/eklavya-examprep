"""Reset the PS02 data. Run before deploying (or any time the dev database has test students in it):

    python -m app.ps02.reseed                      wipe EVERY student and rebuild the demo class "10-B" from the fixture (a second)
    python -m app.ps02.reseed --delete "A,B"       delete only the students with these names (case-insensitive)
    python -m app.ps02.reseed --regenerate         re-simulate the demo class through the real BKT/SM-2 code (about 25 s) and rewrite demo_class.json
"""
from __future__ import annotations

import argparse

from app import db

LEARNER_TABLES = ("mastery", "attempts", "reviews", "student_misconceptions", "dialogues", "assignment_students")


def delete_students(ids: list[int]) -> int:
    for sid in ids:
        for table in LEARNER_TABLES:
            db.execute(f"DELETE FROM {table} WHERE student_id=?", (sid,))
        db.execute("DELETE FROM students WHERE id=?", (sid,))
    db.execute("DELETE FROM ps02_cache WHERE cache_key LIKE 'reteach:%' OR cache_key LIKE 'lesson:%' OR cache_key LIKE 'q:%'")
    db.execute("DELETE FROM assignments WHERE id NOT IN (SELECT assignment_id FROM assignment_students)")
    return len(ids)


def delete_by_name(names: list[str]) -> list[str]:
    wanted = {n.strip().lower() for n in names if n.strip()}
    rows = [r for r in db.query("SELECT id, name FROM students") if r["name"].strip().lower() in wanted]
    delete_students([r["id"] for r in rows])
    return [r["name"] for r in rows]


def reset_all() -> dict:
    """Every student, test or real, goes; the demo class comes back fresh from the fixture."""
    from app.ps02 import seed
    delete_students([r["id"] for r in db.query("SELECT id FROM students")])
    return seed.reseed()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delete", help="comma-separated student names to delete (nothing else is touched)")
    parser.add_argument("--regenerate", action="store_true", help="re-simulate the demo class and rewrite the fixture")
    args = parser.parse_args()
    db.init_db()
    if args.delete:
        print("deleted:", delete_by_name(args.delete.split(",")) or "nobody matched")
    elif args.regenerate:
        from app.ps02 import seed
        seed.export_fixture()
        print("fixture regenerated; run again without flags to load it")
    else:
        result = reset_all()
        print(f"reset done: class {result['class_section']} with {len(result['students'])} students ->", ", ".join(s["name"] for s in result["students"]))


if __name__ == "__main__":
    main()
