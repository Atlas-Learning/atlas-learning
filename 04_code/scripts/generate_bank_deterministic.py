"""Reconstruit la banque d'items avec le générateur DÉTERMINISTE (qualité premium).

Math exacte garantie. Insère en `ai_generated` (le workflow T2.3/T2.4 — revue,
traduction AR, validation linguiste — s'applique ensuite normalement).

Usage :
    python scripts/generate_bank_deterministic.py [--reset]

--reset : supprime d'abord tous les items existants (remplace l'ancienne banque LLM).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

from src.db import SessionLocal, make_engine
from src.items.deterministic import bank_items
from src.items.generation import GeneratedItem
from src.items.review import insert_generated_items
from src.models.base import AnswerFormat
from src.models.competency import Competency
from src.models.item import Item


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="supprime les items existants d'abord")
    args = p.parse_args()

    with SessionLocal(bind=make_engine()) as s:
        if args.reset:
            n = s.execute(delete(Item)).rowcount
            s.commit()
            print(f"reset : {n} items supprimés")

        comps = s.execute(select(Competency).order_by(Competency.code)).scalars().all()
        total = 0
        for comp in comps:
            items = bank_items(comp.code, comp.difficulty_prior)
            if not items:
                print(f"! {comp.code} : aucun générateur")
                continue
            gen = [
                GeneratedItem(
                    competency_id=comp.id,
                    content_en=it["content"],
                    answer_format=AnswerFormat.MCQ,
                    difficulty_prior=it["difficulty_prior"],          # par item (≠ flat)
                    context_tags={**it["context_tags"], "gen": "deterministic"},
                    provenance={"generator": "deterministic", "method": "exact-fraction"},
                    template_key=it["template_key"],
                )
                for it in items
            ]
            insert_generated_items(s, gen)
            diffs = [round(it["difficulty_prior"]) for it in items]
            total += len(gen)
            print(f"+ {comp.code}: {len(gen)} items  (difficulté {min(diffs)}–{max(diffs)})")

        live = s.execute(
            select(func.count()).select_from(Item).where(Item.deleted_at.is_(None))
        ).scalar_one()
    print(f"\nBanque déterministe : {total} items générés, {live} vivants en base.")


if __name__ == "__main__":
    main()
