"""Plan hebdomadaire (refonte B2) — persistance et lecture ; la génération est dans
`src/restitution/plan.py` (pure). Branché sur la clôture d'un check-in `full`.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.models.base import (
    CheckInKind, EdgeType, MemberSource, PlanActionKind, PlanActionStatus, PlanConfidence, PlanStatus,
    ensure_utc, utcnow,
)
from src.models.checkin import CheckIn
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.measurement import Response, Student, StudentCompetencyAbility
from src.models.org import StudentClassroom
from src.models.plan import PlanAction, PlanActionMember, WeeklyPlan
from src.models.session import AssessmentSession
from src.models.item import Item
from src.models.lesson import MiniLesson
from src.api import lesson_service
from src.restitution.plan import Ability, WrongAnswer, build_plan, observed_error_text


class PlanError(ValueError):
    """Génération impossible (check-in non `full`, classe vide…)."""


def week_start_of(d: date) -> date:
    """Lundi de la semaine ISO de `d`. [À CLARIFIER] Q5 : jour de début de semaine par pays
    (dimanche en Arabie saoudite) — le plan est daté au lundi ISO, l'envoi du message (B6) suit
    le réglage de l'école."""
    return d - timedelta(days=d.weekday())


def _class_students(s: Session, classroom_id: uuid.UUID) -> List[Student]:
    ids = set(s.execute(select(StudentClassroom.student_id)
                        .where(StudentClassroom.classroom_id == classroom_id)).scalars())
    ids |= set(s.execute(select(Student.id).where(Student.classroom_id == classroom_id)).scalars())
    if not ids:
        return []
    return list(s.execute(select(Student).where(Student.id.in_(ids), Student.deleted_at.is_(None))
                          .order_by(Student.id)).scalars())


def _graph(s: Session):
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    code_of = {cid: c.code for cid, c in comps.items()}
    id_of = {c.code: cid for cid, c in comps.items()}
    labels_en = {c.code: c.label_en for c in comps.values()}
    labels_ar = {c.code: c.label_ar for c in comps.values()}
    hard: Dict[str, List[str]] = {}
    for e in s.execute(select(CompetencyPrerequisite)
                       .where(CompetencyPrerequisite.edge_type == EdgeType.HARD)).scalars():
        if e.target_id in code_of and e.source_id in code_of:
            hard.setdefault(code_of[e.target_id], []).append(code_of[e.source_id])
    for v in hard.values():
        v.sort()
    return code_of, id_of, labels_en, labels_ar, hard


def unit_codes(s: Session, ci: CheckIn, code_of: Dict[uuid.UUID, str]) -> List[str]:
    """L'unité du check-in : ses compétences visées ; sinon celles effectivement mesurées
    pendant le check-in (items répondus) ; sinon tout ce qui est estimé pour la classe."""
    if ci.competency_ids:
        return sorted(code_of[uuid.UUID(c)] for c in ci.competency_ids if uuid.UUID(c) in code_of)
    sess_ids = list(s.execute(select(AssessmentSession.id).where(AssessmentSession.checkin_id == ci.id)).scalars())
    if sess_ids:
        measured = set(s.execute(select(Response.competency_id)
                                 .where(Response.session_id.in_(sess_ids))).scalars())
        if measured:
            return sorted(code_of[c] for c in measured if c in code_of)
    return sorted(code_of.values())


def observed_errors(s: Session, ci: CheckIn, student_ids: List[uuid.UUID],
                    competency_id: uuid.UUID) -> Dict[uuid.UUID, Optional[str]]:
    """Q16 : par élève, l'erreur la plus fréquente sur `competency_id` pendant CE check-in
    (réponses des sessions liées au check-in, option choisie connue)."""
    sess_rows = s.execute(select(AssessmentSession.id, AssessmentSession.student_id)
                          .where(AssessmentSession.checkin_id == ci.id,
                                 AssessmentSession.student_id.in_(student_ids))).all()
    if not sess_rows:
        return {sid: None for sid in student_ids}
    student_of = {sess_id: st for sess_id, st in sess_rows}
    rows = s.execute(
        select(Response, Item.content_en).join(Item, Item.id == Response.item_id)
        .where(Response.session_id.in_(list(student_of)), Response.competency_id == competency_id)
    ).all()
    n_items: Dict[uuid.UUID, int] = {sid: 0 for sid in student_ids}
    wrong: Dict[uuid.UUID, List[WrongAnswer]] = {sid: [] for sid in student_ids}
    for resp, content in rows:
        sid = student_of[resp.session_id]
        n_items[sid] += 1
        if not resp.is_correct and resp.selected:
            wrong[sid].append(WrongAnswer(str((content or {}).get("stem", "")), resp.selected))
    return {sid: observed_error_text(wrong[sid], n_items[sid]) for sid in student_ids}


def generate_plan_for_checkin(s: Session, ci: CheckIn, *, by: Optional[uuid.UUID] = None,
                              week_start: Optional[date] = None) -> WeeklyPlan:
    """Produit le plan de la semaine à partir de l'état mesuré de la classe. Le plan actif
    précédent de la même (classe, semaine) passe `superseded`. Ne commit pas."""
    if ci.kind != CheckInKind.FULL:
        raise PlanError("seul un check-in `full` génère un plan")
    code_of, id_of, labels_en, labels_ar, hard = _graph(s)
    students = _class_students(s, ci.classroom_id)
    unit = unit_codes(s, ci, code_of)
    abilities: Dict[str, Dict[str, Ability]] = {}
    if students:
        rows = s.execute(select(StudentCompetencyAbility)
                         .where(StudentCompetencyAbility.student_id.in_([st.id for st in students]))).scalars()
        for r in rows:
            if r.competency_id in code_of:
                abilities.setdefault(str(r.student_id), {})[code_of[r.competency_id]] = Ability(
                    r.ability_elo, r.confidence, r.n_direct)
    drafts = build_plan(abilities, hard, unit, labels_en, labels_ar)

    ws = week_start or week_start_of((ensure_utc(ci.closed_at) or utcnow()).date())
    for old in s.execute(select(WeeklyPlan).where(WeeklyPlan.classroom_id == ci.classroom_id,
                                                  WeeklyPlan.week_start == ws,
                                                  WeeklyPlan.status == PlanStatus.ACTIVE)).scalars():
        old.status = PlanStatus.SUPERSEDED
    plan = WeeklyPlan(school_id=ci.school_id, classroom_id=ci.classroom_id, week_start=ws,
                      source_checkin_id=ci.id, status=PlanStatus.ACTIVE)
    s.add(plan); s.flush()
    for d in drafts:
        lesson = lesson_service.pick_lesson(s, id_of[d.root_cause])                   # B3
        action = PlanAction(
            plan_id=plan.id, school_id=ci.school_id, kind=PlanActionKind(d.kind), rank=d.rank,
            root_cause_competency_id=id_of[d.root_cause], blocked_competency_id=id_of[d.blocked],
            confidence=PlanConfidence(d.confidence), because_en=d.because_en, because_ar=d.because_ar,
            lesson_id=lesson.id if lesson else None,
        )
        s.add(action); s.flush()
        member_ids = [uuid.UUID(m.student_id) for m in d.members]
        errors = observed_errors(s, ci, member_ids, id_of[d.blocked])            # Q16
        for sid in member_ids:
            s.add(PlanActionMember(action_id=action.id, student_id=sid, school_id=ci.school_id,
                                   source=MemberSource.ATLAS, observed_error=errors.get(sid)))
    s.flush()
    log_action(s, action="plan.generate", school_id=ci.school_id, user_id=by, resource_type="weekly_plan",
               resource_id=plan.id, details={"checkin_id": str(ci.id), "week_start": ws.isoformat(),
                                             "n_actions": len(drafts), "n_unit": len(unit)})
    return plan


# --- lecture ---------------------------------------------------------------------------

def active_plan(s: Session, classroom_id: uuid.UUID, week_start: Optional[date] = None) -> Optional[WeeklyPlan]:
    q = select(WeeklyPlan).where(WeeklyPlan.classroom_id == classroom_id, WeeklyPlan.status == PlanStatus.ACTIVE)
    if week_start is not None:
        q = q.where(WeeklyPlan.week_start == week_start)
    return s.execute(q.order_by(WeeklyPlan.week_start.desc(), WeeklyPlan.generated_at.desc())).scalars().first()


def _members(s: Session, action_id: uuid.UUID) -> List[PlanActionMember]:
    return list(s.execute(select(PlanActionMember).where(PlanActionMember.action_id == action_id)
                          .order_by(PlanActionMember.student_id)).scalars())


def action_payload(s: Session, a: PlanAction, *, with_members: bool = True) -> dict:
    comps = {c.id: c for c in s.execute(select(Competency).where(
        Competency.id.in_([a.root_cause_competency_id, a.blocked_competency_id]))).scalars()}
    root, blocked = comps[a.root_cause_competency_id], comps[a.blocked_competency_id]
    members = _members(s, a.id)
    active_members = [m for m in members if not m.removed_by_teacher]
    out = {
        "id": str(a.id), "plan_id": str(a.plan_id), "kind": a.kind.value, "rank": a.rank,
        "status": a.status.value, "confidence": a.confidence.value,
        "root_cause": {"competency_id": str(root.id), "code": root.code, "label_en": root.label_en, "label_ar": root.label_ar},
        "blocked": {"competency_id": str(blocked.id), "code": blocked.code, "label_en": blocked.label_en, "label_ar": blocked.label_ar},
        "because_en": a.because_en, "because_ar": a.because_ar,
        "lesson_id": str(a.lesson_id) if a.lesson_id else None,
        "lesson": (lesson_service.payload(s.get(MiniLesson, a.lesson_id), full=False)
                   if a.lesson_id and s.get(MiniLesson, a.lesson_id) else None),
        "n_members": len(active_members),
        "done_at": a.done_at.isoformat() if a.done_at else None,
        "dismissed_at": a.dismissed_at.isoformat() if a.dismissed_at else None,
    }
    if with_members:
        students = {st.id: st for st in s.execute(select(Student).where(
            Student.id.in_([m.student_id for m in members]))).scalars()} if members else {}
        abilities = {a.student_id: a for a in s.execute(select(StudentCompetencyAbility).where(
            StudentCompetencyAbility.competency_id == a.root_cause_competency_id,
            StudentCompetencyAbility.student_id.in_([m.student_id for m in members]))).scalars()} if members else {}
        def _root_state(ab):
            if ab is None:
                return {"state": "unmeasured", "elo": None, "confidence": None}
            estimated = ab.n_direct == 0 or ab.confidence < 0.5
            return {"state": "estimated" if estimated else ("mastered" if ab.ability_elo >= 1500.0 else "progress"),
                    "elo": round(ab.ability_elo, 1), "confidence": round(ab.confidence, 3)}
        out["members"] = [{
            "student_id": str(m.student_id),
            "external_ref": (students.get(m.student_id).external_ref if students.get(m.student_id) else None),
            "source": m.source.value, "removed_by_teacher": m.removed_by_teacher,
            "observed_error": m.observed_error,
            "root": _root_state(abilities.get(m.student_id)),
        } for m in members]
    return out


def plan_payload(s: Session, plan: WeeklyPlan) -> dict:
    actions = list(s.execute(select(PlanAction).where(PlanAction.plan_id == plan.id).order_by(PlanAction.rank)).scalars())
    return {
        "id": str(plan.id), "classroom_id": str(plan.classroom_id), "week_start": plan.week_start.isoformat(),
        "status": plan.status.value, "generated_at": plan.generated_at.isoformat() if plan.generated_at else None,
        "source_checkin_id": str(plan.source_checkin_id) if plan.source_checkin_id else None,
        "actions": [action_payload(s, a) for a in actions],
    }


# --- corrections de l'enseignant ----------------------------------------------------------

def set_members(s: Session, action: PlanAction, *, add: List[uuid.UUID], remove: List[uuid.UUID],
                class_student_ids: set, by: uuid.UUID) -> None:
    """Ajoute / retire des élèves d'un groupe. La correction est ENREGISTRÉE (source
    teacher_added, removed_by_teacher), jamais effacée. Élève hors classe → PlanError."""
    for sid in list(add) + list(remove):
        if sid not in class_student_ids:
            raise PlanError("élève hors de la classe")
    current = {m.student_id: m for m in _members(s, action.id)}
    for sid in add:
        m = current.get(sid)
        if m is None:
            s.add(PlanActionMember(action_id=action.id, student_id=sid, school_id=action.school_id,
                                   source=MemberSource.TEACHER_ADDED))
        else:
            m.removed_by_teacher = False
    for sid in remove:
        m = current.get(sid)
        if m is not None:
            m.removed_by_teacher = True
    s.flush()
    log_action(s, action="plan_action.members", school_id=action.school_id, user_id=by,
               resource_type="plan_action", resource_id=action.id,
               details={"added": [str(x) for x in add], "removed": [str(x) for x in remove]})


def dismiss(s: Session, action: PlanAction, *, by: uuid.UUID) -> None:
    if action.status == PlanActionStatus.DONE:
        raise PlanError("une action faite ne s'abandonne plus")
    if action.status == PlanActionStatus.PROPOSED:
        action.status, action.dismissed_at = PlanActionStatus.DISMISSED, utcnow()
    log_action(s, action="plan_action.dismiss", school_id=action.school_id, user_id=by,
               resource_type="plan_action", resource_id=action.id)
