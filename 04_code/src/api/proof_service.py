"""Action faite, re-mesure ciblée, preuve (refonte B4) — logique testable sans HTTP.

Boucle : l'enseignant marque une action « faite » → les `before_*` de chaque membre sont FIGÉS
(instantané de son estimation sur la cause racine, jamais recalculé) et un check-in `targeted`
est PLANIFIÉ (membres du groupe, compétences racine + bloquée). L'enseignant le démarre (code),
les membres rejoignent, la clôture calcule la PREUVE par élève :

- `unlocked` : re-mesuré, et la cause racine est maintenant maîtrisée (Elo ≥ MASTERY_ELO) avec
  confiance ≥ 0,5 (définition Q1, proposition par défaut) ;
- `unchanged` : re-mesuré, pas maîtrisé ;
- `not_rechecked` : aucune réponse pendant le re-check (absent) — JAMAIS compté dans le dénominateur.

« Boucle bouclée » (métrique nord) = action faite ET re-check ciblé clos.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api import checkin_service
from src.audit import log_action
from src.engine.service import ELO_START
from src.models.base import (
    CheckInKind, CheckInStatus, EdgeType, PlanActionStatus, ProofOutcome, ensure_utc, utcnow,
)
from src.models.checkin import CheckIn
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.measurement import Response, Student, StudentCompetencyAbility
from src.models.org import Classroom
from src.models.plan import PlanAction, PlanActionMember, Proof, WeeklyPlan
from src.models.session import AssessmentSession
from src.restitution.diagnosis import MASTERY_ELO, diagnose

CONFIDENCE_THRESHOLD = 0.5
SCALE_BAND = 150.0          # même bande que restitution/scale.py


class ProofError(ValueError):
    pass


def ci_half_width(confidence: float) -> float:
    """Demi-largeur de l'intervalle exposé (Elo) : large quand la confiance est basse, jamais
    nulle. [À CLARIFIER] Q17 : provisoire, à remplacer par une erreur-type calibrée sur cohorte."""
    return round(SCALE_BAND * (1.0 - max(0.0, min(1.0, confidence))) + 25.0, 1)


def _ability(s: Session, student_id: uuid.UUID, competency_id: uuid.UUID) -> Optional[StudentCompetencyAbility]:
    return s.get(StudentCompetencyAbility, (student_id, competency_id))


def mark_done(s: Session, action: PlanAction, *, by: uuid.UUID) -> "tuple[PlanAction, CheckIn]":
    """Fige les before_* des membres actifs sur la cause racine et planifie le re-check ciblé.
    Ne commit pas. Une action faite ou abandonnée ne se refait pas (ProofError)."""
    if action.status != PlanActionStatus.PROPOSED:
        raise ProofError(f"action déjà {action.status.value}")
    plan = s.get(WeeklyPlan, action.plan_id)
    classroom = s.get(Classroom, plan.classroom_id)
    members = [m for m in s.execute(select(PlanActionMember).where(PlanActionMember.action_id == action.id)
                                    .order_by(PlanActionMember.student_id)).scalars() if not m.removed_by_teacher]
    if not members:
        raise ProofError("aucun membre dans le groupe")
    now = utcnow()
    for m in members:
        ab = _ability(s, m.student_id, action.root_cause_competency_id)
        before_elo = ab.ability_elo if ab else ELO_START
        before_conf = ab.confidence if ab else 0.0
        s.add(Proof(action_id=action.id, student_id=m.student_id, school_id=action.school_id,
                    competency_id=action.root_cause_competency_id, before_elo=before_elo,
                    before_confidence=before_conf, outcome=ProofOutcome.NOT_RECHECKED, computed_at=now))
    recheck = CheckIn(
        school_id=action.school_id, classroom_id=classroom.id, created_by=by, kind=CheckInKind.TARGETED,
        plan_action_id=action.id,
        competency_ids=sorted({str(action.root_cause_competency_id), str(action.blocked_competency_id)}),
        student_ids=[str(m.student_id) for m in members],
        code="----", status=CheckInStatus.SCHEDULED, opened_at=now,
    )
    s.add(recheck)
    action.status, action.done_at = PlanActionStatus.DONE, now
    s.flush()
    log_action(s, action="plan_action.done", school_id=action.school_id, user_id=by, resource_type="plan_action",
               resource_id=action.id, details={"n_members": len(members), "recheck_checkin_id": str(recheck.id)})
    return action, recheck


def start_checkin(s: Session, ci: CheckIn, *, by: Optional[uuid.UUID]) -> CheckIn:
    """Ouvre un check-in planifié : code alloué, élèves peuvent rejoindre. Idempotent si déjà ouvert."""
    if ci.status == CheckInStatus.OPEN:
        return ci
    if ci.status != CheckInStatus.SCHEDULED:
        raise ProofError("ce check-in est clos")
    ci.code = checkin_service.allocate_code(s)
    ci.status, ci.opened_at = CheckInStatus.OPEN, utcnow()
    s.flush()
    log_action(s, action="checkin.start", school_id=ci.school_id, user_id=by, resource_type="checkin",
               resource_id=ci.id, details={"plan_action_id": str(ci.plan_action_id) if ci.plan_action_id else None})
    return ci


def compute_proofs(s: Session, ci: CheckIn, *, by: Optional[uuid.UUID]) -> Dict:
    """À la clôture d'un re-check ciblé : after_*, intervalle, issue par élève. Ne commit pas."""
    if ci.kind != CheckInKind.TARGETED or ci.plan_action_id is None:
        raise ProofError("pas un re-check d'action")
    action = s.get(PlanAction, ci.plan_action_id)
    proofs = list(s.execute(select(Proof).where(Proof.action_id == action.id)).scalars())
    sessions = {sess.student_id: sess for sess in s.execute(
        select(AssessmentSession).where(AssessmentSession.checkin_id == ci.id)).scalars()}
    answered = set()
    if sessions:
        answered = set(s.execute(select(AssessmentSession.student_id)
                                 .join(Response, Response.session_id == AssessmentSession.id)
                                 .where(AssessmentSession.checkin_id == ci.id,
                                        Response.competency_id == action.root_cause_competency_id)).scalars())
    now = utcnow()
    counts = {"unlocked": 0, "unchanged": 0, "not_rechecked": 0}
    for pr in proofs:
        pr.recheck_checkin_id, pr.computed_at = ci.id, now
        if pr.student_id not in answered:
            pr.outcome, pr.after_elo, pr.after_confidence, pr.ci_low, pr.ci_high = (
                ProofOutcome.NOT_RECHECKED, None, None, None, None)
        else:
            ab = _ability(s, pr.student_id, pr.competency_id)
            pr.after_elo = ab.ability_elo if ab else ELO_START
            pr.after_confidence = ab.confidence if ab else 0.0
            half = ci_half_width(pr.after_confidence)
            pr.ci_low, pr.ci_high = round(pr.after_elo - half, 1), round(pr.after_elo + half, 1)
            unlocked = (pr.after_elo >= MASTERY_ELO and pr.after_confidence >= CONFIDENCE_THRESHOLD
                        and pr.before_elo < MASTERY_ELO)
            pr.outcome = ProofOutcome.UNLOCKED if unlocked else ProofOutcome.UNCHANGED
        counts[pr.outcome.value] += 1
    s.flush()
    log_action(s, action="proof.compute", school_id=ci.school_id, user_id=by, resource_type="plan_action",
               resource_id=action.id, details={"checkin_id": str(ci.id), **counts})
    return {"action_id": str(action.id), **counts}


# --- lecture ---------------------------------------------------------------------------

def _upstream_hint(s: Session, student_id: uuid.UUID, root_id: uuid.UUID) -> Optional[dict]:
    """Pour un élève inchangé : y a-t-il une cause plus en amont que la racine enseignée ?"""
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    code_of = {cid: c.code for cid, c in comps.items()}
    hard: Dict[str, List[str]] = {}
    for e in s.execute(select(CompetencyPrerequisite).where(CompetencyPrerequisite.edge_type == EdgeType.HARD)).scalars():
        if e.target_id in code_of and e.source_id in code_of:
            hard.setdefault(code_of[e.target_id], []).append(code_of[e.source_id])
    abilities = {code_of[a.competency_id]: a.ability_elo for a in s.execute(
        select(StudentCompetencyAbility).where(StudentCompetencyAbility.student_id == student_id)).scalars()
        if a.competency_id in code_of}
    root_code = code_of.get(root_id)
    if root_code is None or root_code not in abilities:
        return None
    d = diagnose(root_code, abilities, hard)
    if d.is_self:
        return None
    c = next(c for c in comps.values() if c.code == d.root_cause)
    return {"competency_id": str(c.id), "code": c.code, "label_en": c.label_en, "label_ar": c.label_ar}


def proof_payload(s: Session, action: PlanAction, *, with_code: bool = False) -> dict:
    """E4 · Carte de preuve : « X sur Y ont débloqué » calculé sur les seuls re-mesurés ; par
    élève avant / après / intervalle / issue ; suggestions pour les inchangés et les absents."""
    proofs = list(s.execute(select(Proof).where(Proof.action_id == action.id).order_by(Proof.student_id)).scalars())
    recheck = s.execute(select(CheckIn).where(CheckIn.plan_action_id == action.id)
                        .order_by(CheckIn.opened_at.desc())).scalars().first()
    students = {st.id: st for st in s.execute(select(Student).where(Student.id.in_([p.student_id for p in proofs]))).scalars()} if proofs else {}
    comp = s.get(Competency, action.root_cause_competency_id)
    rows = []
    for pr in proofs:
        row = {
            "student_id": str(pr.student_id),
            "external_ref": students[pr.student_id].external_ref if pr.student_id in students else None,
            "competency_code": comp.code if comp else None,
            "before": {"elo": pr.before_elo, "confidence": pr.before_confidence,
                       "measured": pr.before_confidence >= CONFIDENCE_THRESHOLD},
            "after": None if pr.after_elo is None else {
                "elo": pr.after_elo, "confidence": pr.after_confidence,
                "measured": (pr.after_confidence or 0.0) >= CONFIDENCE_THRESHOLD,
                "ci_low": pr.ci_low, "ci_high": pr.ci_high},
            "outcome": pr.outcome.value,
            "suggestion": None,
        }
        if pr.outcome == ProofOutcome.UNCHANGED:
            up = _upstream_hint(s, pr.student_id, action.root_cause_competency_id)
            row["suggestion"] = {"kind": "upstream_cause", "competency": up} if up else {"kind": "practise_again"}
        elif pr.outcome == ProofOutcome.NOT_RECHECKED:
            row["suggestion"] = {"kind": "add_to_next_recheck"}
        rows.append(row)
    rechecked = [r for r in rows if r["outcome"] != "not_rechecked"]
    computed = recheck is not None and recheck.status == CheckInStatus.CLOSED
    return {
        "action_id": str(action.id), "status": action.status.value,
        "done_at": action.done_at.isoformat() if action.done_at else None,
        "root_cause": None if comp is None else {"competency_id": str(comp.id), "code": comp.code,
                                                 "label_en": comp.label_en, "label_ar": comp.label_ar},
        "recheck": None if recheck is None else checkin_service.checkin_payload(recheck, with_code=with_code),
        "computed": computed,
        "header": {"unlocked": sum(1 for r in rows if r["outcome"] == "unlocked"),
                   "rechecked": len(rechecked),
                   "not_rechecked": len(rows) - len(rechecked),
                   "interval_note": "ci_low/ci_high : intervalle sur l'estimation après re-mesure "
                                    "(largeur selon la confiance)"},
        "students": rows,
        "loop_closed": action.status == PlanActionStatus.DONE and computed,
    }


def classroom_proofs(s: Session, classroom_id: uuid.UUID, *, since: Optional[date] = None,
                     with_code: bool = False) -> dict:
    """E1 · Bandeau des dernières preuves : actions faites avec re-check clos (plus récentes
    d'abord) + compteur de boucles bouclées de la classe."""
    plans = s.execute(select(WeeklyPlan.id).where(WeeklyPlan.classroom_id == classroom_id)).scalars().all()
    if not plans:
        return {"classroom_id": str(classroom_id), "loops_closed": 0, "proofs": []}
    actions = s.execute(select(PlanAction).where(PlanAction.plan_id.in_(plans),
                                                 PlanAction.status == PlanActionStatus.DONE)
                        .order_by(PlanAction.done_at.desc())).scalars().all()
    out, loops = [], 0
    for a in actions:
        pay = proof_payload(s, a, with_code=with_code)
        if not pay["computed"]:
            continue
        loops += 1
        closed_at = pay["recheck"]["closed_at"]
        if since is not None and closed_at and ensure_utc(datetime.fromisoformat(closed_at)).date() < since:
            continue
        out.append(pay)
    return {"classroom_id": str(classroom_id), "loops_closed": loops, "proofs": out}
