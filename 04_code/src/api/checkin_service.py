"""Check-ins de classe (refonte B1) — logique pure, testable sans HTTP.

Boucle : l'enseignant OUVRE un check-in (code à 4 chiffres, unique parmi les check-ins ouverts),
les élèves REJOIGNENT par le code (une AssessmentSession liée au check-in, ciblée sur les
compétences visées), l'écran projeté suit une PROGRESSION ANONYME (invariant 5 : ni nom, ni
identifiant), puis la CLÔTURE termine proprement les sessions encore ouvertes. B2 (plan) et B4
(preuve) se branchent sur `close_checkin` par le résultat qu'il renvoie.
"""
from __future__ import annotations

import random
import uuid
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.session_service import start_session
from src.audit import log_action
from src.models.base import CheckInKind, CheckInStatus, utcnow
from src.models.checkin import CheckIn
from src.models.measurement import Response, Student
from src.models.org import Classroom, StudentClassroom
from src.models.session import AssessmentSession

CODE_SPACE = 10_000          # 0000–9999


class CheckInError(ValueError):
    """Demande invalide (classe sans école, plus de code libre, kind incohérent…)."""


class JoinRefused(Exception):
    """L'élève ne peut pas rejoindre : code inconnu ou clos (`reason='code'`), ou élève hors de
    la classe / du groupe (`reason='membership'`)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --- ouverture ---------------------------------------------------------------------------

def _open_codes(s: Session) -> set:
    return set(s.execute(select(CheckIn.code).where(CheckIn.status == CheckInStatus.OPEN)).scalars())


def allocate_code(s: Session, *, rng: random.Random = random) -> str:
    """Code à 4 chiffres unique parmi les check-ins OUVERTS (un code clos peut être réutilisé)."""
    taken = _open_codes(s)
    if len(taken) >= CODE_SPACE:
        raise CheckInError("plus aucun code libre : clore des check-ins")
    while True:
        code = f"{rng.randrange(CODE_SPACE):04d}"
        if code not in taken:
            return code


def open_checkin(s: Session, *, classroom: Classroom, created_by: Optional[uuid.UUID],
                 kind: CheckInKind, competency_ids: Optional[List[uuid.UUID]] = None,
                 student_ids: Optional[List[uuid.UUID]] = None,
                 plan_action_id: Optional[uuid.UUID] = None,
                 rng: random.Random = random) -> CheckIn:
    """Ouvre un check-in sur une classe. Ne commit pas."""
    if kind == CheckInKind.FULL and (student_ids or plan_action_id):
        raise CheckInError("un check-in `full` porte sur toute la classe, sans action du plan")
    if kind == CheckInKind.TARGETED and not competency_ids:
        raise CheckInError("un check-in `targeted` vise au moins une compétence")
    ci = CheckIn(
        school_id=classroom.school_id, classroom_id=classroom.id, created_by=created_by, kind=kind,
        plan_action_id=plan_action_id,
        competency_ids=[str(c) for c in competency_ids] if competency_ids else None,
        student_ids=[str(x) for x in student_ids] if student_ids else None,
        code=allocate_code(s, rng=rng), status=CheckInStatus.OPEN, opened_at=utcnow(),
    )
    s.add(ci)
    s.flush()
    log_action(s, action="checkin.open", school_id=ci.school_id, user_id=created_by,
               resource_type="checkin", resource_id=ci.id,
               details={"kind": kind.value, "classroom_id": str(classroom.id),
                        "n_competencies": len(ci.competency_ids or []),
                        "n_members": len(ci.student_ids or []) or None})
    return ci


# --- rejoindre ---------------------------------------------------------------------------

def _roster_ids(s: Session, ci: CheckIn) -> List[uuid.UUID]:
    """Élèves attendus : le groupe (targeted) ou toute la classe (inscriptions M:N + homeroom)."""
    if ci.student_ids:
        return [uuid.UUID(x) for x in ci.student_ids]
    ids = set(s.execute(select(StudentClassroom.student_id)
                        .where(StudentClassroom.classroom_id == ci.classroom_id)).scalars())
    ids |= set(s.execute(select(Student.id).where(Student.classroom_id == ci.classroom_id,
                                                  Student.deleted_at.is_(None))).scalars())
    return sorted(ids, key=str)


def _is_member(s: Session, ci: CheckIn, student: Student) -> bool:
    if ci.student_ids is not None:
        return str(student.id) in ci.student_ids
    if student.classroom_id == ci.classroom_id:
        return True
    return s.get(StudentClassroom, (student.id, ci.classroom_id)) is not None


def find_open_by_code(s: Session, code: str) -> Optional[CheckIn]:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 4:
        return None
    return s.execute(select(CheckIn).where(CheckIn.code == code, CheckIn.status == CheckInStatus.OPEN)
                     ).scalar_one_or_none()


def join_checkin(s: Session, *, code: str, student: Student, locale: str = "en") -> AssessmentSession:
    """Rejoint un check-in ouvert : refus clair si code inconnu/clos ou élève hors classe/groupe.
    Idempotent : re-rejoindre renvoie la session déjà ouverte (déconnexion, rechargement)."""
    ci = find_open_by_code(s, code)
    if ci is None:
        raise JoinRefused("code")
    if student.deleted_at is not None or student.school_id != ci.school_id or not _is_member(s, ci, student):
        raise JoinRefused("membership")
    existing = s.execute(select(AssessmentSession).where(
        AssessmentSession.checkin_id == ci.id, AssessmentSession.student_id == student.id,
        AssessmentSession.status == "active")).scalar_one_or_none()
    if existing is not None:
        return existing
    targets = [uuid.UUID(c) for c in ci.competency_ids] if ci.competency_ids else None
    sess = start_session(s, student_id=student.id, school_id=student.school_id,
                         target_competency_ids=targets, locale=locale)      # commit inclus
    sess.checkin_id = ci.id
    log_action(s, action="checkin.join", school_id=ci.school_id, resource_type="checkin",
               resource_id=ci.id, details={"session_id": str(sess.id)})
    s.commit()
    return sess


# --- progression anonyme -----------------------------------------------------------------

#: Seules clés admises dans une tuile (test explicite dans tests/test_checkins.py).
TILE_KEYS = ("state", "n_answered")


def progress(s: Session, ci: CheckIn) -> Dict:
    """Progression d'un check-in pour l'écran projeté : compteurs + une tuile ANONYME par élève
    attendu. Aucun nom, aucun identifiant (invariant 5) ; l'ordre des tuiles ne suit pas la liste
    de classe (trié par état puis avancement) pour ne pas trahir l'élève par sa position."""
    roster = _roster_ids(s, ci)
    sessions = s.execute(select(AssessmentSession).where(AssessmentSession.checkin_id == ci.id)).scalars().all()
    by_student = {sess.student_id: sess for sess in sessions}
    answered: Dict[uuid.UUID, int] = {}
    if sessions:
        for sid, in s.execute(select(Response.session_id)
                              .where(Response.session_id.in_([x.id for x in sessions]))).all():
            answered[sid] = answered.get(sid, 0) + 1
    tiles = []
    for st_id in roster:
        sess = by_student.get(st_id)
        if sess is None:
            tiles.append({"state": "absent", "n_answered": 0})
        else:
            tiles.append({"state": "finished" if sess.status == "completed" else "in_progress",
                          "n_answered": answered.get(sess.id, 0)})
    # sessions d'élèves hors liste (ex. retiré du groupe après avoir rejoint) : comptées, pas nommées
    extra = [sess for st_id, sess in by_student.items() if st_id not in set(roster)]
    for sess in extra:
        tiles.append({"state": "finished" if sess.status == "completed" else "in_progress",
                      "n_answered": answered.get(sess.id, 0)})
    order = {"finished": 0, "in_progress": 1, "absent": 2}
    tiles.sort(key=lambda t: (order[t["state"]], -t["n_answered"]))
    counts = {
        "expected": len(roster),
        "joined": len(sessions),
        "in_progress": sum(1 for t in tiles if t["state"] == "in_progress"),
        "finished": sum(1 for t in tiles if t["state"] == "finished"),
        "absent": sum(1 for t in tiles if t["state"] == "absent"),
    }
    return {"checkin_id": str(ci.id), "kind": ci.kind.value, "status": ci.status.value,
            "counts": counts, "tiles": tiles}


# --- clôture -----------------------------------------------------------------------------

def close_checkin(s: Session, ci: CheckIn, *, by: Optional[uuid.UUID]) -> Dict:
    """Clôt le check-in : les sessions encore actives sont terminées proprement
    (`stop_reason='checkin_closed'`), le code est libéré. Idempotent. Ne commit pas."""
    if ci.status == CheckInStatus.CLOSED:
        return {"checkin_id": str(ci.id), "already_closed": True, "closed_sessions": 0}
    now = utcnow()
    closed = 0
    for sess in s.execute(select(AssessmentSession).where(
            AssessmentSession.checkin_id == ci.id, AssessmentSession.status == "active")).scalars():
        sess.status, sess.stop_reason, sess.ended_at = "completed", "checkin_closed", now
        closed += 1
    ci.status, ci.closed_at = CheckInStatus.CLOSED, now
    s.flush()
    log_action(s, action="checkin.close", school_id=ci.school_id, user_id=by, resource_type="checkin",
               resource_id=ci.id, details={"kind": ci.kind.value, "closed_sessions": closed})
    return {"checkin_id": str(ci.id), "already_closed": False, "closed_sessions": closed,
            "kind": ci.kind.value}


def checkin_payload(ci: CheckIn, *, with_code: bool) -> Dict:
    """Vue enseignant d'un check-in. Le code n'est montré qu'à qui peut le projeter."""
    out = {"id": str(ci.id), "classroom_id": str(ci.classroom_id), "kind": ci.kind.value,
           "status": ci.status.value, "n_competencies": len(ci.competency_ids or []),
           "competency_ids": ci.competency_ids, "n_members": len(ci.student_ids) if ci.student_ids else None,
           "plan_action_id": str(ci.plan_action_id) if ci.plan_action_id else None,
           "opened_at": ci.opened_at.isoformat() if ci.opened_at else None,
           "closed_at": ci.closed_at.isoformat() if ci.closed_at else None}
    if with_code and ci.status == CheckInStatus.OPEN:
        out["code"] = ci.code
    return out
