"""Onboarde un membre du STAFF Atlas global : `content_reviewer` (relecteur de la banque) ou
`linguist` (validation de l'arabe). Compte + rôle global + lien magique single-use.

Même contrat que onboard_linguist.py (conservé pour compatibilité) : idempotent, audité, lien
minté à remettre à la main (utile avant le SMTP). Le relecteur se connecte par le flux
« admin » (/admin/request-link → /admin/login), le linguiste par /linguist/login.

Usage :
  python scripts/onboard_staff.py --role content_reviewer --email relecteur@atlaslearning.ae
  python scripts/onboard_staff.py --role linguist --email linguiste@atlaslearning.ae --no-link
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.db import SessionLocal, make_engine
from src.models.base import Role
from src.models.org import AppUser, Membership
from src.rbac.auth import make_single_use_token

STAFF_ROLES = {
    Role.CONTENT_REVIEWER: ("admin_login", "/api/admin/login"),
    Role.LINGUIST: ("linguist_login", "/api/linguist/login"),
}


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def onboard_staff(s: Session, email: str, role: Role, *, mint_link: bool = True,
                  ttl_hours: int = 24) -> dict:
    """Crée/retrouve le compte, garantit le rôle global, mint un lien. Idempotent."""
    if role not in STAFF_ROLES:
        raise ValueError(f"rôle staff attendu : {sorted(r.value for r in STAFF_ROLES)}")
    email = email.strip().lower()
    user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
    created = user is None
    if user is None:
        user = AppUser(email=email)
        s.add(user); s.flush()
    elif user.deleted_at is not None or not user.is_active:
        user.deleted_at, user.is_active = None, True      # compte staff : on le réactive

    has_role = s.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.role == role)
    ).scalar_one_or_none() is not None
    if not has_role:
        s.add(Membership(user_id=user.id, role=role))      # GLOBAL : ni école ni organisation

    link = None
    if mint_link:
        purpose, path = STAFF_ROLES[role]
        token = make_single_use_token(str(user.id), purpose=purpose, ttl_s=ttl_hours * 3600)
        link = f"{_web_base()}{path}?token={token}"

    log_action(s, action="staff.onboard", user_id=user.id, resource_type="app_user",
               resource_id=user.id,
               details={"role": role.value, "created": created, "role_added": not has_role,
                        "link_minted": mint_link})
    s.commit()
    return {"user_id": user.id, "email": email, "role": role.value, "created": created,
            "role_added": not has_role, "link": link}


def main() -> None:
    p = argparse.ArgumentParser(description="Onboarde un relecteur de contenu ou un linguiste.")
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True, choices=sorted(r.value for r in STAFF_ROLES))
    p.add_argument("--no-link", action="store_true")
    p.add_argument("--ttl-hours", type=int, default=24)
    args = p.parse_args()
    with SessionLocal(bind=make_engine()) as s:
        r = onboard_staff(s, args.email, Role(args.role), mint_link=not args.no_link,
                          ttl_hours=args.ttl_hours)
    etat = "créé" if r["created"] else "existant"
    print(f"[{etat}] {r['email']} — {r['role']} "
          f"({'rôle ajouté' if r['role_added'] else 'rôle déjà présent'}, user_id={r['user_id']})")
    if r["link"]:
        print(f"\nLien magique single-use (valide {args.ttl_hours} h) :\n  {r['link']}")


if __name__ == "__main__":
    main()
