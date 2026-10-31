"""Attribution des rôles hors roster (refonte A1, question Q13) — logique pure, testable.

Problème : le roster (Google, OneRoster, Wonde) ne connaît que élève / enseignant / admin IT.
Les rôles de la refonte — `dept_lead` (coordinateur : une école + des niveaux) et
`group_admin` (groupe scolaire : une organisation) — sont attribués par un humain. Le même
service sert :

- l'API `POST/GET/DELETE /admin/roles` (admin IT de l'organisation, super admin) ;
- la CLI `scripts/grant_role.py` (bootstrap d'un pilote, avant tout SMTP ou IdP).

Il fonctionne AVEC ou SANS SSO, parce qu'il travaille sur l'identité stable du projet :
l'email d'un `AppUser`.

- Avec SSO : l'IdP ne provisionne jamais un compte (cf. /oauth/{provider}/callback : l'email
  doit déjà exister). On crée donc le compte ici, sans `external_ref` ; la personne se connecte
  via l'IdP de son école, qui le retrouve par email. Si le roster la connaît aussi (prof,
  admin IT), la sync ADOPTE ce compte par email (sync.py) et pose l'external_ref : la
  membership attribuée ici n'est pas touchée (la sync n'efface jamais une membership).
- Sans SSO : la personne demande un lien magique sur /admin/request-link (rôles autorisés :
  cf. `MAGIC_LINK_ROLES`), ou l'opérateur mint un lien single-use depuis la CLI.
- Déprovisioning : un compte créé ici n'a pas d'`external_ref` → jamais désactivé par la
  sync (règle « compte bootstrap »). S'il est adopté par le roster puis disparaît de
  l'annuaire, il est désactivé comme tout compte rosterisé — l'attribution de rôle ne le
  ressuscite pas (`GrantError`), c'est à l'annuaire de trancher.

Idempotence : ré-attribuer le même rôle sur la même portée ne duplique rien ; pour un
`dept_lead`, la liste de niveaux fournie REMPLACE la précédente (sémantique d'ensemble).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.models.base import Role
from src.models.measurement import School
from src.models.org import AppUser, DeptLeadScope, Membership, Organization

#: Rôles attribuables par ce service (les autres viennent du roster, de l'onboarding ou
#: d'un script dédié : super_admin, linguist).
GRANTABLE_ROLES: FrozenSet[Role] = frozenset({Role.DEPT_LEAD, Role.GROUP_ADMIN})

#: Rôles qui peuvent ouvrir une session par lien magique (/admin/request-link) quand aucun IdP
#: ne les porte. Le super admin (équipe éditeur) l'avait déjà ; les deux rôles de la refonte
#: s'y ajoutent pour les écoles et groupes « sans SSO ».
MAGIC_LINK_ROLES: FrozenSet[Role] = frozenset({
    Role.SUPER_ADMIN, Role.CONTENT_REVIEWER, Role.GROUP_ADMIN, Role.DEPT_LEAD,
})

GRADE_MIN, GRADE_MAX = 0, 13   # 0 = KG


class GrantError(ValueError):
    """Demande invalide (portée incohérente, école inconnue, compte désactivé par le roster…)."""


@dataclass
class Grant:
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    role: Role
    organization_id: Optional[uuid.UUID]
    school_id: Optional[uuid.UUID]
    school_name: Optional[str] = None
    grades: List[int] = field(default_factory=list)
    has_external_ref: bool = False     # True = identité portée par le roster/IdP

    def as_dict(self) -> dict:
        return {
            "membership_id": str(self.membership_id),
            "user_id": str(self.user_id),
            "email": self.email,
            "role": self.role.value,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "school_id": str(self.school_id) if self.school_id else None,
            "school_name": self.school_name,
            "grades": self.grades,
            "source": "roster" if self.has_external_ref else "manual",
        }


@dataclass
class GrantResult:
    grant: Grant
    created_user: bool
    created_membership: bool


def _normalize_grades(grades: Optional[Iterable[int]]) -> List[int]:
    out = sorted({int(g) for g in (grades or ())})
    bad = [g for g in out if not (GRADE_MIN <= g <= GRADE_MAX)]
    if bad:
        raise GrantError(f"niveaux hors bornes {GRADE_MIN}–{GRADE_MAX} : {bad}")
    return out


def _live_school(s: Session, school_id: uuid.UUID) -> School:
    sch = s.execute(select(School).where(School.id == school_id,
                                         School.deleted_at.is_(None))).scalar_one_or_none()
    if sch is None:
        raise GrantError("école introuvable")
    return sch


def _live_org(s: Session, organization_id: uuid.UUID) -> Organization:
    org = s.execute(select(Organization).where(Organization.id == organization_id,
                                               Organization.deleted_at.is_(None))).scalar_one_or_none()
    if org is None:
        raise GrantError("organisation introuvable")
    return org


def _ensure_user(s: Session, email: str) -> Tuple[AppUser, bool]:
    user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
    if user is None:
        user = AppUser(email=email)      # sans external_ref : protégé du déprovisioning roster
        s.add(user); s.flush()
        return user, True
    if user.deleted_at is not None or not user.is_active:
        if user.external_ref:
            # Identité portée par l'annuaire : c'est lui qui a désactivé, c'est lui qui réactive.
            raise GrantError("compte désactivé par le roster : le réactiver dans l'annuaire d'abord")
        user.deleted_at, user.is_active = None, True   # compte manuel : on le réactive
    return user, False


def _scope_grades(s: Session, membership_id: uuid.UUID) -> List[int]:
    return sorted(s.execute(
        select(DeptLeadScope.grade).where(DeptLeadScope.membership_id == membership_id)
    ).scalars())


def _to_grant(s: Session, m: Membership, user: AppUser, school: Optional[School]) -> Grant:
    return Grant(
        membership_id=m.id, user_id=user.id, email=user.email, role=m.role,
        organization_id=m.organization_id, school_id=m.school_id,
        school_name=school.name if school else None,
        grades=_scope_grades(s, m.id) if m.role == Role.DEPT_LEAD else [],
        has_external_ref=bool(user.external_ref),
    )


def grant_role(s: Session, *, email: str, role: Role,
               organization_id: Optional[uuid.UUID] = None,
               school_id: Optional[uuid.UUID] = None,
               grades: Optional[Iterable[int]] = None,
               actor_user_id: Optional[uuid.UUID] = None) -> GrantResult:
    """Attribue `role` à `email` sur la portée donnée. Ne commit pas (l'appelant décide).

    - `dept_lead` : `school_id` obligatoire, `grades` non vide ; l'organisation est celle de
      l'école (un `organization_id` fourni doit coïncider).
    - `group_admin` : `organization_id` obligatoire ; ni école ni niveaux.
    """
    if role not in GRANTABLE_ROLES:
        raise GrantError(f"rôle non attribuable ici : {role.value}")
    email = (email or "").strip().lower()
    if "@" not in email:
        raise GrantError("email invalide")

    school: Optional[School] = None
    if role == Role.DEPT_LEAD:
        if school_id is None:
            raise GrantError("dept_lead : school_id obligatoire")
        school = _live_school(s, school_id)
        if organization_id is not None and school.organization_id != organization_id:
            raise GrantError("dept_lead : l'école n'appartient pas à cette organisation")
        organization_id = school.organization_id
        grade_list = _normalize_grades(grades)
        if not grade_list:
            raise GrantError("dept_lead : au moins un niveau requis")
    else:  # GROUP_ADMIN
        if organization_id is None:
            raise GrantError("group_admin : organization_id obligatoire")
        if school_id is not None or grades:
            raise GrantError("group_admin : portée = organisation seule (ni école, ni niveaux)")
        _live_org(s, organization_id)
        grade_list = []

    user, created_user = _ensure_user(s, email)

    m = s.execute(select(Membership).where(
        Membership.user_id == user.id, Membership.role == role,
        Membership.organization_id == organization_id,
        Membership.school_id == school_id,
    )).scalar_one_or_none()
    created_membership = m is None
    if m is None:
        m = Membership(user_id=user.id, role=role, organization_id=organization_id,
                       school_id=school_id)
        s.add(m); s.flush()

    if role == Role.DEPT_LEAD:
        current = set(_scope_grades(s, m.id))
        wanted = set(grade_list)
        for g in current - wanted:
            s.delete(s.get(DeptLeadScope, (m.id, g)))
        for g in wanted - current:
            s.add(DeptLeadScope(membership_id=m.id, grade=g))
        s.flush()

    log_action(s, action="role.grant", school_id=school_id, user_id=actor_user_id,
               resource_type="membership", resource_id=m.id,
               details={"email": email, "role": role.value,
                        "organization_id": str(organization_id) if organization_id else None,
                        "school_id": str(school_id) if school_id else None,
                        "grades": grade_list, "created_user": created_user,
                        "created_membership": created_membership})
    return GrantResult(_to_grant(s, m, user, school), created_user, created_membership)


def revoke_role(s: Session, *, membership_id: uuid.UUID,
                actor_user_id: Optional[uuid.UUID] = None) -> Grant:
    """Retire une attribution (membership + niveaux en cascade). Le compte reste : s'il porte
    d'autres rôles il continue de servir ; sinon il ne peut plus ouvrir de session utile."""
    m = s.get(Membership, membership_id)
    if m is None or m.role not in GRANTABLE_ROLES:
        raise GrantError("attribution introuvable")
    user = s.get(AppUser, m.user_id)
    school = s.get(School, m.school_id) if m.school_id else None
    grant = _to_grant(s, m, user, school)
    s.delete(m)
    log_action(s, action="role.revoke", school_id=m.school_id, user_id=actor_user_id,
               resource_type="membership", resource_id=m.id,
               details={"email": user.email, "role": m.role.value, "grades": grant.grades})
    s.flush()
    return grant


def organization_of_grant(s: Session, membership_id: uuid.UUID) -> Optional[uuid.UUID]:
    """Organisation qui porte une attribution (pour le contrôle d'accès avant révocation)."""
    m = s.get(Membership, membership_id)
    if m is None or m.role not in GRANTABLE_ROLES:
        return None
    if m.organization_id is not None:
        return m.organization_id
    if m.school_id is not None:
        sch = s.get(School, m.school_id)
        return sch.organization_id if sch else None
    return None


def list_grants(s: Session, *, organization_id: Optional[uuid.UUID] = None,
                school_id: Optional[uuid.UUID] = None) -> List[Grant]:
    """Attributions dept_lead / group_admin d'une organisation (écoles vivantes incluses), ou
    les seuls dept_lead d'une école (`school_id`, vue du ped_admin)."""
    if school_id is not None:
        scope = (Membership.role == Role.DEPT_LEAD) & (Membership.school_id == school_id)
    elif organization_id is not None:
        school_ids = select(School.id).where(School.organization_id == organization_id)
        scope = ((Membership.organization_id == organization_id)
                 | Membership.school_id.in_(school_ids))
    else:
        raise GrantError("organization_id ou school_id requis")
    rows = s.execute(
        select(Membership, AppUser)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.role.in_(list(GRANTABLE_ROLES)), scope, AppUser.deleted_at.is_(None))
        .order_by(Membership.role, AppUser.email)
    ).all()
    out: List[Grant] = []
    for m, user in rows:
        school = s.get(School, m.school_id) if m.school_id else None
        out.append(_to_grant(s, m, user, school))
    return out
