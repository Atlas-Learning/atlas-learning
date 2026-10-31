"""Attribue un rôle hors roster — `dept_lead` (école + niveaux) ou `group_admin` (organisation).

Point d'entrée de bootstrap d'un pilote : fonctionne avant tout SMTP ou IdP. Même logique que
l'API `POST /admin/roles` (src/rbac/grants.py) : idempotent, audité, compte créé par email
sans external_ref (jamais désactivé par le roster ; adopté par la sync si l'annuaire le
connaît). Avec `--link`, mint un lien magique single-use (purpose admin_login) à remettre à la
personne — utile « sans SSO » ; avec SSO, elle se connecte simplement via l'IdP de son école.

Usage :
  python scripts/grant_role.py --email coord@ecole.ae --role dept_lead \\
      --school "École A" --grades 4,5 [--link] [--ttl-hours 24]
  python scripts/grant_role.py --email dir@groupe.ae --role group_admin --org "Groupe X" [--link]
  python scripts/grant_role.py --list --org "Groupe X"
  python scripts/grant_role.py --revoke <membership_id>

`--school` / `--org` acceptent un UUID, un nom exact, ou (org) un domaine.
"""
import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import SessionLocal, make_engine
from src.models.base import Role
from src.models.measurement import School
from src.models.org import Organization
from src.rbac import grants
from src.rbac.auth import make_single_use_token


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def _as_uuid(value: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def resolve_org(s: Session, ref: str) -> Organization:
    u = _as_uuid(ref)
    q = select(Organization).where(Organization.deleted_at.is_(None))
    q = q.where(Organization.id == u) if u else q.where(
        (Organization.name == ref) | (Organization.domain == ref.lower()))
    rows = s.execute(q).scalars().all()
    if len(rows) != 1:
        sys.exit(f"organisation « {ref} » : {len(rows)} correspondance(s) — précise un UUID")
    return rows[0]


def resolve_school(s: Session, ref: str, org: Optional[Organization]) -> School:
    u = _as_uuid(ref)
    q = select(School).where(School.deleted_at.is_(None))
    q = q.where(School.id == u) if u else q.where(School.name == ref)
    if org is not None:
        q = q.where(School.organization_id == org.id)
    rows = s.execute(q).scalars().all()
    if len(rows) != 1:
        sys.exit(f"école « {ref} » : {len(rows)} correspondance(s) — précise un UUID ou --org")
    return rows[0]


def mint_link(user_id: uuid.UUID, ttl_hours: int) -> str:
    token = make_single_use_token(str(user_id), purpose="admin_login", ttl_s=ttl_hours * 3600)
    return f"{_web_base()}/api/admin/login?token={token}"


def main() -> None:
    p = argparse.ArgumentParser(description="Attribue / liste / révoque dept_lead et group_admin.")
    p.add_argument("--email")
    p.add_argument("--role", choices=sorted(r.value for r in grants.GRANTABLE_ROLES))
    p.add_argument("--org", help="organisation : UUID, nom exact ou domaine")
    p.add_argument("--school", help="école (dept_lead) : UUID ou nom exact")
    p.add_argument("--grades", help="niveaux (dept_lead), ex. 4,5")
    p.add_argument("--link", action="store_true", help="mint un lien magique single-use")
    p.add_argument("--ttl-hours", type=int, default=24)
    p.add_argument("--list", action="store_true", help="liste les attributions de --org")
    p.add_argument("--revoke", metavar="MEMBERSHIP_ID", help="révoque une attribution")
    args = p.parse_args()

    with SessionLocal(bind=make_engine()) as s:
        if args.revoke:
            mid = _as_uuid(args.revoke) or sys.exit("--revoke attend un UUID de membership")
            try:
                g = grants.revoke_role(s, membership_id=mid)
            except grants.GrantError as e:
                sys.exit(str(e))
            s.commit()
            print(f"révoqué : {g.email} — {g.role.value}" + (f" niveaux {g.grades}" if g.grades else ""))
            return

        if args.list:
            if not args.org:
                sys.exit("--list exige --org")
            org = resolve_org(s, args.org)
            rows = grants.list_grants(s, organization_id=org.id)
            if not rows:
                print(f"aucune attribution dans « {org.name} »")
            for g in rows:
                scope = f"{g.school_name} niveaux {g.grades}" if g.role == Role.DEPT_LEAD else org.name
                print(f"{g.membership_id}  {g.role.value:12} {g.email:40} {scope}  [{'roster' if g.has_external_ref else 'manuel'}]")
            return

        if not (args.email and args.role):
            sys.exit("--email et --role sont requis (ou --list / --revoke)")
        role = Role(args.role)
        org = resolve_org(s, args.org) if args.org else None
        school = None
        grades = None
        if role == Role.DEPT_LEAD:
            if not args.school or not args.grades:
                sys.exit("dept_lead : --school et --grades requis")
            school = resolve_school(s, args.school, org)
            grades = [int(x) for x in args.grades.split(",") if x.strip()]
        elif org is None:
            sys.exit("group_admin : --org requis")
        try:
            res = grants.grant_role(s, email=args.email, role=role,
                                    organization_id=org.id if org else None,
                                    school_id=school.id if school else None, grades=grades)
        except grants.GrantError as e:
            sys.exit(str(e))
        s.commit()
        g = res.grant
        etat = "compte créé" if res.created_user else "compte existant"
        attrib = "rôle attribué" if res.created_membership else "rôle déjà présent (portée mise à jour)"
        scope = f"{g.school_name} niveaux {g.grades}" if role == Role.DEPT_LEAD else f"organisation {org.name}"
        print(f"[{etat}] {g.email} — {role.value} sur {scope} — {attrib} (membership={g.membership_id})")
        if args.link:
            print(f"\nLien magique single-use (valide {args.ttl_hours} h) — à transmettre :\n  "
                  f"{mint_link(g.user_id, args.ttl_hours)}")
        else:
            print("\nConnexion : via l'IdP de l'école (SSO), ou lien magique à demander sur la page "
                  "de connexion (« Get a sign-in link »). Ajoute --link pour en générer un maintenant.")


if __name__ == "__main__":
    main()
