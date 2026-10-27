"""Autorisation RBAC (Epic 6, T6.2). Logique PURE + résolveur DB.

6 rôles (super_admin, it_admin, ped_admin, teacher, parent, student). Les permissions
sont vérifiées ici (côté serveur), pas seulement masquées en UI. Isolation tenant :
un acteur ne voit que son périmètre (école / classe / enfant / soi).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import FrozenSet, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.models.base import Role
from src.models.measurement import Student
from src.models.org import Membership, ParentStudent, TeacherClassroom


@dataclass(frozen=True)
class UserContext:
    user_id: uuid.UUID
    roles: FrozenSet[Role] = field(default_factory=frozenset)
    school_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)     # ped/it admin
    org_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)
    classroom_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)  # enseignant
    child_student_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)  # parent
    own_student_id: Optional[uuid.UUID] = None                              # élève

    def has(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)


def is_super(ctx: UserContext) -> bool:
    return Role.SUPER_ADMIN in ctx.roles


def can_review_arabic(ctx: UserContext) -> bool:
    """Accès à la banque d'items AR (relecture/validation linguistique).

    Le contenu de la banque n'est PAS tenant-scopé (pas de school_id sur les items) : le
    linguiste est un STAFF Atlas GLOBAL. L'accès n'est donc PAS filtré par école — il suffit
    d'avoir le rôle `linguist` (ou `super_admin`, accès illimité). Cohérent avec le style des
    helpers `can_access_*`, mais sans argument de périmètre (le contenu est global)."""
    return ctx.has(Role.LINGUIST, Role.SUPER_ADMIN)


def can_access_school(ctx: UserContext, school_id) -> bool:
    if is_super(ctx):
        return True
    return ctx.has(Role.IT_ADMIN, Role.PED_ADMIN) and school_id in ctx.school_ids


def can_access_classroom(ctx: UserContext, classroom_id, classroom_school_id) -> bool:
    if is_super(ctx):
        return True
    if ctx.has(Role.IT_ADMIN, Role.PED_ADMIN) and classroom_school_id in ctx.school_ids:
        return True
    if Role.TEACHER in ctx.roles and classroom_id in ctx.classroom_ids:
        return True
    return False


def can_access_student(ctx: UserContext, student_id, student_school_id,
                       student_classroom_ids) -> bool:
    """`student_classroom_ids` : ENSEMBLE des classes de l'élève (principale + spécialités).

    Un enseignant accède à l'élève s'il partage **au moins une** classe avec lui.
    """
    if is_super(ctx):
        return True
    if ctx.has(Role.IT_ADMIN, Role.PED_ADMIN) and student_school_id in ctx.school_ids:
        return True
    if Role.TEACHER in ctx.roles and ctx.classroom_ids & set(student_classroom_ids or ()):
        return True
    if Role.PARENT in ctx.roles and student_id in ctx.child_student_ids:
        return True
    if Role.STUDENT in ctx.roles and student_id == ctx.own_student_id:
        return True
    return False


def build_user_context(session: Session, user_id: uuid.UUID) -> UserContext:
    """Résout le contexte d'autorisation d'un utilisateur depuis la base."""
    memberships = session.execute(
        select(Membership).where(Membership.user_id == user_id)
    ).scalars().all()
    roles = frozenset(m.role for m in memberships)
    # Seules les écoles portées par une membership admin : l'école d'une membership
    # enseignant/élève/parent ne doit jamais recevoir la portée admin d'un autre rôle.
    school_ids = frozenset(m.school_id for m in memberships
                           if m.school_id and m.role in (Role.IT_ADMIN, Role.PED_ADMIN,
                                                         Role.SUPER_ADMIN))
    org_ids = frozenset(m.organization_id for m in memberships if m.organization_id)
    classroom_ids = frozenset(session.execute(
        select(TeacherClassroom.classroom_id).where(TeacherClassroom.user_id == user_id)
    ).scalars())
    child_ids = frozenset(session.execute(
        select(ParentStudent.student_id).where(ParentStudent.user_id == user_id)
    ).scalars())
    own = session.execute(
        select(Student.id).where(Student.user_id == user_id)
    ).scalar_one_or_none()
    return UserContext(user_id, roles, school_ids, org_ids, classroom_ids, child_ids, own)


def revoke_prior_grants(session: Session, user_id: uuid.UUID) -> None:
    """À la RÉACTIVATION d'un compte désactivé : purge rôles et liens d'avant l'offboarding.

    Le soft delete laisse les Memberships en place ; sans cette purge, réactiver le compte
    restaurerait silencieusement tous ses anciens rôles (y compris admin d'un autre tenant).
    L'appelant ré-accorde ensuite uniquement le rôle qu'il affirme.
    """
    for model in (Membership, ParentStudent, TeacherClassroom):
        session.execute(delete(model).where(model.user_id == user_id))
