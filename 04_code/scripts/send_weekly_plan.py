"""Cron HORAIRE : envoie « votre plan est prêt » aux écoles dont le créneau local est atteint (B6).

Idempotent dans l'heure (journal d'audit par enseignant et jour local). Usage :
  python scripts/send_weekly_plan.py [--dry-run] [--now 2026-11-02T03:00:00Z] [--school <uuid>]
Variables : WEB_BASE_URL (liens), SMTP_* / POSTMARK_TOKEN / EMAIL_FROM (sender ; sinon Noop).
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import SessionLocal, make_engine
from src.notify.email import build_email_sender
from src.notify.weekly_plan import send_due


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--now", help="instant UTC ISO 8601 (défaut : maintenant)")
    p.add_argument("--school", help="forcer l'envoi pour cette école (UUID), quelle que soit l'heure")
    args = p.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    web_base = os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")
    with SessionLocal(bind=make_engine()) as s:
        rep = send_due(s, build_email_sender(), now=now, web_base=web_base, dry_run=args.dry_run,
                       force_school_id=uuid.UUID(args.school) if args.school else None)
        if not args.dry_run:
            s.commit()
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}{rep.checked_schools} écoles, {len(rep.due_schools)} au créneau, {len(rep.sent)} e-mail(s), "
          f"{rep.skipped_already} déjà notifié(s), {rep.skipped_no_plan} enseignant(s) sans plan")
    for e in rep.sent:
        print(f"  → {e}")


if __name__ == "__main__":
    main()
