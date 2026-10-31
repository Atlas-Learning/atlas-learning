"""Seed des mini-leçons (refonte B3) depuis data/lessons/*.json — idempotent (upsert sur la clé).

Usage : python scripts/seed_lessons.py [--dry-run] [--dir data/lessons]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audit import log_action
from src.api.lesson_service import LESSONS_DIR, seed_lessons
from src.db import SessionLocal, make_engine


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dir", default=str(LESSONS_DIR))
    args = p.parse_args()
    with SessionLocal(bind=make_engine()) as s:
        rep = seed_lessons(s, Path(args.dir), dry_run=args.dry_run)
        if not args.dry_run and not rep["errors"]:
            log_action(s, action="lesson.seed", details=rep)
            s.commit()
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}{len(rep['created'])} créée(s), {len(rep['updated'])} mise(s) à jour")
    for e in rep["errors"]:
        print(f"  ! {e}")
    if rep["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
