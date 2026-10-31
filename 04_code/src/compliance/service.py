"""Conformité PDPL (Phase E) — visibilité audit, portabilité, droit à l'oubli. Logique pure.

- `audit_entries` : lecture du journal d'audit scoppé au tenant (la DSI veut voir les accès).
- `export_tenant` : export structuré des données du tenant (portabilité / contrôleur = l'école).
- `erase_student` : effacement d'un sujet (élève) — suppression DURE, cascades incluses.
- `erase_tenant` : purge complète à la fin de contrat (irréversible).

Les FK `ondelete=CASCADE` font le gros du travail ; on supprime explicitement les `AppUser`
(porteurs d'email = PII) que l'org ne cascade pas.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.models.audit import AuditLog
from src.models.checkin import CheckIn
from src.models.measurement import School, Student
from src.models.org import (
    AppUser, Classroom, Membership, Organization, RosterRun, StudentClassroom,
    TenantIntegration,
)


def _school_ids(org: Organization):
    return select(School.id).where(School.organization_id == org.id)


def _user_ids(org: Organization):
    return select(Membership.user_id).where(Membership.organization_id == org.id)


def audit_entries(s: Session, org: Organization, *, limit: int = 100,
                  action: Optional[str] = None) -> List[dict]:
    """Entrées d'audit du tenant (par école OU par utilisateur de l'org), plus récentes d'abord."""
    stmt = select(AuditLog).where(
        or_(AuditLog.school_id.in_(_school_ids(org)), AuditLog.user_id.in_(_user_ids(org)))
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = s.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    return [{
        "id": str(r.id), "action": r.action,
        "user_id": str(r.user_id) if r.user_id else None,
        "school_id": str(r.school_id) if r.school_id else None,
        "resource_type": r.resource_type,
        "resource_id": str(r.resource_id) if r.resource_id else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


def export_tenant(s: Session, org: Organization) -> dict:
    """Bundle de portabilité : structure + comptes + inscriptions du tenant (contrôleur = école)."""
    schools = s.execute(select(School).where(School.organization_id == org.id)).scalars().all()
    school_ids = [sc.id for sc in schools]
    classrooms = s.execute(
        select(Classroom).where(Classroom.school_id.in_(school_ids))
    ).scalars().all() if school_ids else []

    roles_by_user: dict = {}
    for uid, role in s.execute(
        select(Membership.user_id, Membership.role).where(Membership.organization_id == org.id)
    ).all():
        roles_by_user.setdefault(uid, []).append(role.value)
    users = s.execute(
        select(AppUser).where(AppUser.id.in_(_user_ids(org)))
    ).scalars().all()

    students = s.execute(
        select(Student).where(Student.school_id.in_(school_ids))
    ).scalars().all() if school_ids else []
    classes_of: dict = {}
    if students:
        for sid, cid in s.execute(
            select(StudentClassroom.student_id, StudentClassroom.classroom_id)
            .where(StudentClassroom.student_id.in_([st.id for st in students]))
        ).all():
            classes_of.setdefault(sid, []).append(str(cid))

    integ = s.execute(
        select(TenantIntegration).where(TenantIntegration.organization_id == org.id)
    ).scalar_one_or_none()
    runs = s.execute(
        select(RosterRun).where(RosterRun.organization_id == org.id)
        .order_by(RosterRun.started_at.desc())
    ).scalars().all()
    checkins = s.execute(
        select(CheckIn).where(CheckIn.school_id.in_(school_ids)).order_by(CheckIn.opened_at)
    ).scalars().all() if school_ids else []

    return {
        "organization": {"id": str(org.id), "name": org.name, "domain": org.domain,
                         "external_ref": org.external_ref, "seats": org.seats},
        "schools": [{"id": str(sc.id), "name": sc.name, "external_ref": sc.external_ref}
                    for sc in schools],
        "classrooms": [{"id": str(c.id), "name": c.name, "school_id": str(c.school_id),
                        "external_ref": c.external_ref} for c in classrooms],
        "users": [{"id": str(u.id), "email": u.email, "is_active": u.is_active,
                   "external_ref": u.external_ref, "roles": roles_by_user.get(u.id, [])}
                  for u in users],
        "students": [{"id": str(st.id), "external_ref": st.external_ref,
                      "school_id": str(st.school_id),
                      "homeroom_id": str(st.classroom_id) if st.classroom_id else None,
                      "classroom_ids": classes_of.get(st.id, [])} for st in students],
        "integration": None if integ is None else {
            "provider": integ.provider, "status": integ.status,
            "admin_email": integ.admin_email,
            "last_sync_at": integ.last_sync_at.isoformat() if integ.last_sync_at else None},
        "roster_runs": [{"id": str(r.id), "status": r.status, "summary": r.summary,
                         "started_at": r.started_at.isoformat() if r.started_at else None}
                        for r in runs],
        # Refonte B1 : check-ins (structure et membres — données du tenant, contrôleur = école)
        "checkins": [{"id": str(c.id), "school_id": str(c.school_id), "classroom_id": str(c.classroom_id),
                      "kind": c.kind.value, "status": c.status.value, "student_ids": c.student_ids,
                      "opened_at": c.opened_at.isoformat() if c.opened_at else None,
                      "closed_at": c.closed_at.isoformat() if c.closed_at else None}
                     for c in checkins],
    }


def student_in_org(s: Session, org: Organization, student_id: uuid.UUID) -> Optional[Student]:
    """Élève du tenant (isolation : refuse un élève hors org)."""
    st = s.get(Student, student_id)
    if st is None:
        return None
    school = s.get(School, st.school_id)
    if school is None or school.organization_id != org.id:
        return None
    return st


def erase_student(s: Session, student: Student) -> dict:
    """Droit à l'oubli d'un sujet : suppression DURE (réponses/abilities/inscriptions cascade) + compte."""
    student_id, user_id = student.id, student.user_id
    # Refonte B1 : un check-in ciblé porte la liste de ses membres (JSON) → on l'en retire.
    for ci in s.execute(select(CheckIn).where(CheckIn.school_id == student.school_id,
                                               CheckIn.student_ids.is_not(None))).scalars():
        if str(student_id) in (ci.student_ids or []):
            ci.student_ids = [x for x in ci.student_ids if x != str(student_id)]
    s.delete(student)            # cascade : response, ability, student_classroom, parent_student
                                 # ; assessment_session.checkin_id : SET NULL via la session supprimée
    s.flush()
    erased_user = False
    if user_id is not None:
        u = s.get(AppUser, user_id)
        if u is not None:
            s.delete(u); erased_user = True   # email = PII + memberships/teacher_classroom (cascade)
    log_action(s, action="compliance.erase_student", resource_type="student", resource_id=student_id)
    return {"erased_student": str(student_id), "erased_user": erased_user}


def erase_tenant(s: Session, org: Organization) -> dict:
    """Purge complète du tenant (fin de contrat) — IRRÉVERSIBLE."""
    org_id = org.id
    user_ids = list(s.execute(_user_ids(org)).scalars())
    s.delete(org)                # cascade : schools→students→responses/abilities, classrooms,
    s.flush()                    #           memberships, integration, roster_runs
    erased_users = 0
    for uid in set(user_ids):
        u = s.get(AppUser, uid)  # comptes (emails) non cascadés par l'org
        if u is not None:
            s.delete(u); erased_users += 1
    log_action(s, action="compliance.erase_tenant", resource_type="organization", resource_id=org_id)
    return {"erased_organization": str(org_id), "erased_users": erased_users}
