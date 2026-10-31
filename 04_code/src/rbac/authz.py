"""Autorisation RBAC (Epic 6, T6.2 ; refonte A1). Logique PURE + résolveur DB.

Rôles : super_admin, it_admin, ped_admin, teacher, parent, student, linguist, et depuis la
refonte (docs/refonte/02-roles-et-ecrans.md) dept_lead et group_admin. Les permissions sont
vérifiées ici (côté serveur), pas seulement masquées en UI. Isolation tenant : un acteur ne
voit que son périmètre (organisation / école / niveaux / classe / enfant / soi).

Portées de la refonte :
- `dept_lead` : UNE école (Membership.school_id) + des niveaux (dept_lead_scope). Sa portée
  effective = les classes vivantes de cette école dont `Classroom.grade` est couvert. Elle est
  résolue à la construction du contexte (`dept_classroom_ids`) : les helpers restent purs.
- `group_admin` : organisation (Membership.organization_id). Lecture de TOUTES les écoles de
  cette organisation (`group_school_ids`), aucune portée classe ni élève (la direction voit des
  niveaux et des écoles, jamais un élève — matrice d'accès de la refonte).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.models.base import Role
from src.models.measurement import School, Student
from src.models.org import Classroom, DeptLeadScope, Membership, ParentStudent, TeacherClassroom


@dataclass(frozen=True)
class UserContext:
    user_id: uuid.UUID
    roles: FrozenSet[Role] = field(default_factory=frozenset)
    school_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)     # ped/it admin
    org_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)
    classroom_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)  # enseignant
    child_student_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)  # parent
    own_student_id: Optional[uuid.UUID] = None                              # élève
    # dept_lead : couples (school_id, grade) couverts, et les classes qu'ils résolvent.
    dept_scopes: FrozenSet[Tuple[uuid.UUID, int]] = field(default_factory=frozenset)
    dept_classroom_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)
    # group_admin : écoles vivantes des organisations de ses memberships group_admin.
    group_school_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)
    # it_admin : organisations qu'il administre (memberships it_admin uniquement — `org_ids`
    # agrège TOUTES les memberships et ne vaut pas portée d'administration).
    admin_org_ids: FrozenSet[uuid.UUID] = field(default_factory=frozenset)

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


def can_flag_item(ctx: UserContext) -> bool:
    """Signaler un item de la banque (refonte A2) : enseignant, coordinateur, linguiste, super
    admin — matrice de docs/refonte/02. (content_reviewer : ticket A4.)"""
    return ctx.has(Role.TEACHER, Role.DEPT_LEAD, Role.LINGUIST, Role.CONTENT_REVIEWER, Role.SUPER_ADMIN)


def can_review_items(ctx: UserContext) -> bool:
    """File de revue de la banque (signalements, gabarits, transitions) : relecteur de contenu
    (staff Atlas global, non tenant-scopé) ou super admin."""
    return ctx.has(Role.CONTENT_REVIEWER, Role.SUPER_ADMIN)


def can_manage_school(ctx: UserContext, school_id) -> bool:
    """Administration d'une école (écriture : réglages, niveau des classes, licences…).

    Admins de l'école seulement (it/ped) ou super admin. Le `group_admin` lit ses écoles mais
    ne les administre pas ; le `dept_lead` n'administre rien."""
    if is_super(ctx):
        return True
    return ctx.has(Role.IT_ADMIN, Role.PED_ADMIN) and school_id in ctx.school_ids


def can_manage_roles(ctx: UserContext, organization_id) -> bool:
    """Attribuer / révoquer les rôles hors roster (dept_lead, group_admin) d'une organisation.

    Admin IT de CETTE organisation ou super admin. Le group_admin ne gère rien (lecture seule).
    Le ped_admin passe par `can_grant_dept_lead` (son école, le seul rôle dept_lead)."""
    if is_super(ctx):
        return True
    return Role.IT_ADMIN in ctx.roles and organization_id in ctx.admin_org_ids


def can_grant_dept_lead(ctx: UserContext, school_id, school_organization_id) -> bool:
    """Nommer / révoquer le coordinateur (`dept_lead`) d'une école : les gestionnaires de rôles de
    l'organisation, ou le ped_admin de CETTE école (décision 2026-10-31)."""
    if can_manage_roles(ctx, school_organization_id):
        return True
    return Role.PED_ADMIN in ctx.roles and school_id in ctx.school_ids


def can_access_school(ctx: UserContext, school_id) -> bool:
    """Lecture des agrégats d'une école (overview, preuves niveau école)."""
    if can_manage_school(ctx, school_id):
        return True
    # group_admin : toutes les écoles de son organisation, et rien d'autre.
    return Role.GROUP_ADMIN in ctx.roles and school_id in ctx.group_school_ids


def can_review_department(ctx: UserContext, school_id, grade: Optional[int]) -> bool:
    """Revue de département : un `dept_lead` sur un niveau qu'il couvre dans cette école.

    `grade` None (classe sans niveau) → jamais couvert. Le super admin lit tout."""
    if is_super(ctx):
        return True
    if grade is None:
        return False
    return Role.DEPT_LEAD in ctx.roles and (school_id, grade) in ctx.dept_scopes


def can_access_classroom(ctx: UserContext, classroom_id, classroom_school_id) -> bool:
    if is_super(ctx):
        return True
    if ctx.has(Role.IT_ADMIN, Role.PED_ADMIN) and classroom_school_id in ctx.school_ids:
        return True
    if Role.TEACHER in ctx.roles and classroom_id in ctx.classroom_ids:
        return True
    # dept_lead : les classes de ses niveaux (résolues dans build_user_context, école incluse).
    if Role.DEPT_LEAD in ctx.roles and classroom_id in ctx.dept_classroom_ids:
        return True
    return False


def can_access_student(ctx: UserContext, student_id, student_school_id,
                       student_classroom_ids) -> bool:
    """`student_classroom_ids` : ENSEMBLE des classes de l'élève (principale + spécialités).

    Un enseignant (ou un dept_lead) accède à l'élève s'il partage **au moins une** classe
    avec lui. Le group_admin n'accède à AUCUN élève nominatif.
    """
    if is_super(ctx):
        return True
    if ctx.has(Role.IT_ADMIN, Role.PED_ADMIN) and student_school_id in ctx.school_ids:
        return True
    classes = set(student_classroom_ids or ())
    if Role.TEACHER in ctx.roles and ctx.classroom_ids & classes:
        return True
    if Role.DEPT_LEAD in ctx.roles and ctx.dept_classroom_ids & classes:
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
    # enseignant/élève/parent/dept_lead ne doit jamais recevoir la portée admin d'un autre rôle.
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

    # dept_lead : (école de la membership, niveau) → classes vivantes de cette école à ce niveau.
    # Une membership dept_lead sans school_id ou sans ligne de portée ne donne AUCUN accès.
    dept_scopes: FrozenSet[Tuple[uuid.UUID, int]] = frozenset()
    dept_classroom_ids: FrozenSet[uuid.UUID] = frozenset()
    dept_memberships = [m for m in memberships if m.role == Role.DEPT_LEAD and m.school_id]
    if dept_memberships:
        school_of = {m.id: m.school_id for m in dept_memberships}
        rows = session.execute(
            select(DeptLeadScope.membership_id, DeptLeadScope.grade)
            .where(DeptLeadScope.membership_id.in_(list(school_of)))
        ).all()
        dept_scopes = frozenset((school_of[mid], grade) for mid, grade in rows)
        if dept_scopes:
            dept_classroom_ids = frozenset(session.execute(
                select(Classroom.id).where(
                    Classroom.deleted_at.is_(None),
                    or_(*[and_(Classroom.school_id == sid, Classroom.grade == g)
                          for sid, g in dept_scopes]),
                )
            ).scalars())

    # group_admin : écoles vivantes des organisations de ses memberships group_admin UNIQUEMENT
    # (l'organisation d'une membership it_admin n'étend pas la portée group_admin).
    group_org_ids = frozenset(m.organization_id for m in memberships
                              if m.role == Role.GROUP_ADMIN and m.organization_id)
    group_school_ids: FrozenSet[uuid.UUID] = frozenset()
    if group_org_ids:
        group_school_ids = frozenset(session.execute(
            select(School.id).where(School.organization_id.in_(list(group_org_ids)),
                                    School.deleted_at.is_(None))
        ).scalars())

    admin_org_ids = frozenset(m.organization_id for m in memberships
                              if m.role == Role.IT_ADMIN and m.organization_id)
    # Un it_admin rosterisé peut n'avoir qu'une école (org + school posés par la sync) : son
    # organisation est alors celle de l'école.
    it_school_ids = [m.school_id for m in memberships if m.role == Role.IT_ADMIN and m.school_id]
    if it_school_ids:
        admin_org_ids = admin_org_ids | frozenset(
            o for o in session.execute(
                select(School.organization_id).where(School.id.in_(it_school_ids))
            ).scalars() if o is not None
        )

    return UserContext(user_id, roles, school_ids, org_ids, classroom_ids, child_ids, own,
                       dept_scopes, dept_classroom_ids, group_school_ids, admin_org_ids)
