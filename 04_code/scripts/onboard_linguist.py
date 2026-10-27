"""Onboarde un LINGUISTE (staff Atlas global) : compte + rôle + lien magique.

Le back-office linguiste (`/linguist/*`) exige un AppUser portant un Membership `linguist`
(rôle global, sans école — la banque d'items n'est pas tenant-scopée). Aucun parcours
self-service ne CRÉE ce compte : ce script est le point d'entrée d'onboarding.

Il est idempotent (re-lancer ne duplique ni le compte ni le rôle) et, par défaut, mint un
**lien magique single-use** à remettre au linguiste — utile même avant que le SMTP soit
posé (bootstrap out-of-band, comme un premier super-admin). Le lien est à usage unique
(jti consommé au 1er POST /linguist/login/confirm) ; TTL par défaut 24 h (fenêtre plus
large que le self-service 30 min car transmis à la main).

Usage :
  DATABASE_URL=... WEB_BASE_URL=https://app.atlaslearning.ae \
      python scripts/onboard_linguist.py --email linguiste@atlaslearning.ae
  # --no-link : crée seulement le compte (le linguiste passera par /linguist/login)
  # --ttl-hours N : durée de validité du lien (défaut 24)
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.db import SessionLocal, make_engine
from src.models.base import Role
from src.models.org import AppUser, Membership
from src.rbac.auth import make_single_use_token
from src.rbac.authz import revoke_prior_grants


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def onboard_linguist(s: Session, email: str, *, mint_link: bool = True,
                     ttl_hours: int = 24) -> dict:
    """Crée/retrouve le compte, garantit le rôle linguist, mint un lien. Idempotent."""
    email = email.strip().lower()
    user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
    created = user is None
    if user is None:
        user = AppUser(email=email)
        s.add(user); s.flush()
    elif user.deleted_at is not None or not user.is_active:
        # Réactive un compte staff précédemment désactivé plutôt que d'en créer un doublon,
        # sans lui rendre ses rôles d'avant l'offboarding (seul linguist est ré-accordé).
        revoke_prior_grants(s, user.id)
        user.deleted_at = None
        user.is_active = True

    has_role = s.execute(
        select(Membership).where(Membership.user_id == user.id,
                                 Membership.role == Role.LINGUIST)
    ).scalar_one_or_none() is not None
    if not has_role:
        # Rôle GLOBAL : pas de school_id/organization_id (staff éditeur, banque non scopée).
        s.add(Membership(user_id=user.id, role=Role.LINGUIST))

    link = None
    if mint_link:
        token = make_single_use_token(str(user.id), purpose="linguist_login",
                                      ttl_s=ttl_hours * 3600)
        link = f"{_web_base()}/api/linguist/login?token={token}"

    log_action(s, action="linguist.onboard", user_id=user.id,
               resource_type="app_user", resource_id=user.id,
               details={"created": created, "role_added": not has_role,
                        "link_minted": mint_link})
    s.commit()
    return {"user_id": user.id, "email": email, "created": created,
            "role_added": not has_role, "link": link}


def main() -> None:
    parser = argparse.ArgumentParser(description="Onboarde un linguiste (compte + rôle + lien).")
    parser.add_argument("--email", required=True)
    parser.add_argument("--no-link", action="store_true",
                        help="ne pas mint de lien (le linguiste passera par /linguist/login)")
    parser.add_argument("--ttl-hours", type=int, default=24,
                        help="validité du lien magique en heures (défaut 24)")
    args = parser.parse_args()

    with SessionLocal(bind=make_engine()) as s:
        r = onboard_linguist(s, args.email, mint_link=not args.no_link,
                             ttl_hours=args.ttl_hours)

    etat = "créé" if r["created"] else "existant"
    role = "rôle linguist ajouté" if r["role_added"] else "rôle linguist déjà présent"
    print(f"[{etat}] {r['email']} — {role} (user_id={r['user_id']})")
    if r["link"]:
        print(f"\nLien magique single-use (valide {args.ttl_hours} h) — à transmettre au linguiste :\n  {r['link']}")
    else:
        print("\nAucun lien minté (--no-link) : le linguiste demande son lien sur /linguist/login.")


if __name__ == "__main__":
    main()
