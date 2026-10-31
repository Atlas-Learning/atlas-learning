"""Propose la version arabe DÉTERMINISTE des items de gabarit qui n'en ont pas (A3).

Pour chaque item vivant porteur d'un `template_key` dont `content_ar` est vide, pose la
proposition de `src/items/arabic_deterministic.py` (ar_validated reste False : le linguiste
valide). `--replace-unvalidated` remplace aussi une proposition existante NON validée (ex. une
traduction LLM douteuse) ; une version validée par le linguiste n'est jamais touchée.

Usage : python scripts/propose_arabic_deterministic.py [--dry-run] [--replace-unvalidated]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from src.audit import log_action
from src.db import SessionLocal, make_engine
from src.items.arabic_deterministic import render_arabic
from src.models.item import Item


def propose_for_bank(s, *, replace_unvalidated: bool = False, dry_run: bool = False) -> dict:
    items = s.execute(select(Item).where(Item.template_key.is_not(None),
                                         Item.deleted_at.is_(None))).scalars().all()
    proposed, skipped_validated, no_template, kept = 0, 0, 0, 0
    for it in items:
        if it.ar_validated and it.content_ar:
            skipped_validated += 1
            continue
        if it.content_ar and not replace_unvalidated:
            kept += 1
            continue
        ar = render_arabic(it.content_en or {})
        if ar is None:
            no_template += 1
            continue
        if not dry_run:
            it.content_ar = ar
            it.ar_validated = False
            prov = dict(it.provenance or {})
            prov["ar_proposed_by"] = "arabic_deterministic"
            it.provenance = prov
        proposed += 1
    if not dry_run:
        s.flush()
    return {"proposed": proposed, "kept_unvalidated": kept, "skipped_validated": skipped_validated,
            "no_template": no_template}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--replace-unvalidated", action="store_true")
    args = p.parse_args()
    with SessionLocal(bind=make_engine()) as s:
        rep = propose_for_bank(s, replace_unvalidated=args.replace_unvalidated, dry_run=args.dry_run)
        if not args.dry_run:
            log_action(s, action="item.ar_propose_deterministic", details=rep)
            s.commit()
    print(f"{'[dry-run] ' if args.dry_run else ''}{rep['proposed']} proposition(s) AR posée(s), "
          f"{rep['kept_unvalidated']} non validée(s) conservée(s), {rep['skipped_validated']} validée(s) intacte(s), "
          f"{rep['no_template']} sans gabarit arabe")


if __name__ == "__main__":
    main()
