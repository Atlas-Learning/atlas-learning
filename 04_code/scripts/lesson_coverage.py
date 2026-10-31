"""Couverture des mini-leçons (Q3) : quelles causes racines possibles ont une leçon, et son statut.

Une cause racine est un prérequis HARD d'une autre compétence. Classement par ce que la
compétence débloque en aval (clôture transitive). Lecture seule.

Usage : python scripts/lesson_coverage.py [--missing]
"""
import argparse
import sys
from pathlib import Path
from typing import Dict, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from src.db import SessionLocal, make_engine
from src.models.base import EdgeType
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.lesson import MiniLesson


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--missing", action="store_true", help="n'afficher que les racines sans leçon")
    args = p.parse_args()
    with SessionLocal(bind=make_engine()) as s:
        comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
        dep: Dict[object, Set[object]] = {}
        for e in s.execute(select(CompetencyPrerequisite).where(CompetencyPrerequisite.edge_type == EdgeType.HARD)).scalars():
            dep.setdefault(e.source_id, set()).add(e.target_id)
        lessons: Dict[object, list] = {}
        for l in s.execute(select(MiniLesson)).scalars():
            lessons.setdefault(l.competency_id, []).append(l)

        def downstream(c, seen=None):
            seen = seen if seen is not None else set()
            for t in dep.get(c, ()):
                if t not in seen:
                    seen.add(t); downstream(t, seen)
            return seen

        roots = sorted(dep, key=lambda c: (-len(downstream(c)), comps[c].grade, comps[c].code))
        n_missing = 0
        for c in roots:
            ls = lessons.get(c, [])
            status = ", ".join(f"{l.key} [{l.status.value}]" for l in sorted(ls, key=lambda l: l.version)) or "— aucune leçon"
            if not ls:
                n_missing += 1
            if args.missing and ls:
                continue
            print(f"{len(downstream(c)):2d} aval  {comps[c].code:34s} {status}")
        print(f"\n{len(roots)} racines possibles, {len(roots) - n_missing} avec leçon, {n_missing} sans.")


if __name__ == "__main__":
    main()
