"""A3 — quarantaine en masse et régénération au gabarit (src/items/templates.py).

Les gabarits vivent dans le code (src/items/deterministic.py). Après correction :
  python scripts/regenerate_template.py --key MATH.G5.NF.ADD_MIXED [--dry-run]
  python scripts/regenerate_template.py --key MATH.G5.NF.ADD_MIXED#03         # une lignée
  python scripts/regenerate_template.py --key MATH.G5.NF.ADD_MIXED --quarantine-only --reason "distracteur faux"

Chaque lignée dont le rendu a changé repart en nouvelle version `ai_generated` (revue EN puis
AR) ; l'ancienne sort du pool et garde ses réponses. Relancer sans nouveau changement ne crée
rien. Pré-requis pour une banque antérieure à A2 : scripts/backfill_template_keys.py.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audit import log_action
from src.db import SessionLocal, make_engine
from src.items.templates import TemplateError, quarantine_template, regenerate_template


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, help="code de générateur, ou code#rang pour une lignée")
    p.add_argument("--by", default="cli", help="identité du relecteur (provenance)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--quarantine-only", action="store_true", help="sortir du pool sans régénérer")
    p.add_argument("--reason", default="")
    args = p.parse_args()
    with SessionLocal(bind=make_engine()) as s:
        try:
            if args.quarantine_only:
                done = quarantine_template(s, args.key, by=args.by, reason=args.reason)
                log_action(s, action="item.template_quarantine",
                           details={"key": args.key, "n": len(done), "reason": args.reason})
                s.commit()
                print(f"{len(done)} item(s) actifs du gabarit {args.key} mis en quarantaine")
                return
            rep = regenerate_template(s, args.key, by=args.by, dry_run=args.dry_run)
            if not args.dry_run:
                log_action(s, action="item.template_regenerate", details=rep.as_dict())
                s.commit()
        except TemplateError as e:
            sys.exit(str(e))
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}{args.key} : {len(rep.regenerated)} nouvelle(s) version(s), "
          f"{len(rep.created)} créé(s), {len(rep.unchanged)} inchangé(s)")
    for k, a, b in rep.regenerated:
        print(f"  {k}: v{a} → v{b} (ancienne version hors pool, réponses conservées)")
    for k in rep.created:
        print(f"  {k}: créé (v1)")
    if rep.regenerated or rep.created:
        print("\nLes nouvelles versions sont `ai_generated` : revue EN puis validation AR avant service.")


if __name__ == "__main__":
    main()
