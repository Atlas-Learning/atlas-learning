"""Q15 — pose `template_key` sur la banque antérieure à A2, SANS rien supprimer.

Appariement (compétence, énoncé, réponse) avec le rendu actuel des générateurs
(src/items/templates.backfill_template_keys). Items, réponses et calibration sont conservés ;
les items sans correspondance sont listés, jamais inventés. Idempotent.

Usage :
  python scripts/backfill_template_keys.py [--dry-run] [--code MATH.G4.NF.ADD_LIKE ...]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audit import log_action
from src.db import SessionLocal, make_engine
from src.items.templates import backfill_template_keys


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--code", action="append", help="limiter à un ou plusieurs générateurs")
    args = p.parse_args()
    with SessionLocal(bind=make_engine()) as s:
        rep = backfill_template_keys(s, codes=args.code, dry_run=args.dry_run)
        if not args.dry_run:
            log_action(s, action="item.template_key_backfill", details=rep.as_dict())
            s.commit()
    print(f"{'[dry-run] ' if args.dry_run else ''}{rep.matched} items appariés, "
          f"{rep.already_keyed} déjà clés, {rep.skipped_non_deterministic} non déterministes ignorés")
    for code, n in sorted(rep.per_code.items()):
        print(f"  {code}: {n}")
    if rep.unmatched:
        print(f"\n{len(rep.unmatched)} item(s) SANS correspondance (générateur modifié depuis ?) :")
        for i in rep.unmatched:
            print(f"  {i}")
    if rep.ambiguous:
        print(f"\n{len(rep.ambiguous)} item(s) AMBIGUS (même énoncé/réponse sur deux rangs) :")
        for i in rep.ambiguous:
            print(f"  {i}")


if __name__ == "__main__":
    main()
