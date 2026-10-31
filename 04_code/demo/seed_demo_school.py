"""Démo (refonte B7) : une école qui a vécu six semaines de boucle hebdomadaire.

Produit, sur la base courante (SQLite par défaut) :
- un groupe scolaire « Al Noor Education » (AE) avec deux écoles : Al Noor Academy (classe 4B,
  26 élèves, 6 semaines) et Riverside School (classe 4A, 10 élèves, 2 semaines) ;
- la banque déterministe activée (clés de gabarit, arabe proposé puis validé) si elle est vide ;
- une leçon par cause racine possible (fichiers data/lessons/ s'ils existent, sinon une leçon
  « [DEMO] » clairement marquée, version 0 pour céder la place à une vraie leçon) ;
- pour chaque semaine : check-in complet (les élèves répondent selon un profil latent), plan,
  actions enseignées, re-checks ciblés (quelques absents), preuves, une correction de groupe,
  une action abandonnée, deux signalements d'items ;
- des comptes pour chaque persona (SSO simulé : OIDC_DEV_LOGIN=1, POST /dev/login {"email"}).

Tout est horodaté sur les six dernières semaines. Relancer reconstruit la démo (l'organisation
demo.atlas est effacée puis recréée ; la banque est conservée). Données fictives.

Usage : python demo/seed_demo_school.py [--weeks 6] [--students 26] [--seed 42]
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.api import checkin_service, lesson_service, plan_service, proof_service
from src.api.session_service import grade_answer, next_item, submit_response
from src.compliance.service import erase_tenant
from src.db import SessionLocal, make_engine
from src.engine.stopping import StopConfig
from src.items import deterministic, review
from src.items.arabic_deterministic import render_arabic
from src.items.generation import GeneratedItem
from src.models.audit import AuditLog
from src.models.base import AnswerFormat, CheckInKind, EdgeType, ItemFlagReason, ItemStatus, Role, utcnow
from src.models.checkin import CheckIn
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.item import Item
from src.models.measurement import Response, School, Student
from src.models.org import (
    AppUser, Classroom, DeptLeadScope, Membership, Organization, ParentStudent, StudentClassroom,
    TeacherClassroom,
)
from src.models.plan import PlanAction, PlanActionMember, PlanStatus, Proof, WeeklyPlan
from src.models.session import AssessmentSession

DOMAIN = "demo.atlas"
ACCOUNTS = {
    "super": "ops@atlas.io", "reviewer": "relecteur@atlas.io", "linguist": "linguiste@atlas.io",
    "it": "it@demo.atlas", "ped": "admin@demo.atlas", "coord": "coord@demo.atlas", "group": "group@demo.atlas",
    "teacher": "prof@demo.atlas", "teacher2": "prof2@demo.atlas", "parent": "parent1@demo.atlas",
}
# Profils latents : (racine en déficit, part de la classe). Le reste est « fluide ».
PROFILES = [("MATH.G3.NF.EQUIVALENCE_VISUAL", 0.30), ("MATH.G3.NF.UNIT_FRACTION", 0.23), ("MATH.G4.NS.LCM", 0.27)]
STOP = StopConfig()


# --- utilitaires -------------------------------------------------------------------------

def _user(s: Session, email: str) -> AppUser:
    u = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
    if u is None:
        u = AppUser(email=email); s.add(u); s.flush()
    u.is_active, u.deleted_at = True, None
    return u


def _membership(s: Session, user: AppUser, role: Role, **scope) -> Membership:
    m = s.execute(select(Membership).where(Membership.user_id == user.id, Membership.role == role)).scalar_one_or_none()
    if m is None:
        m = Membership(user_id=user.id, role=role, **scope); s.add(m); s.flush()
    else:
        for k, v in scope.items():
            setattr(m, k, v)
    return m


def _backdate(s: Session, since: datetime, target: datetime) -> None:
    """Décale vers `target` tout ce qui a été horodaté depuis `since` (la simulation tourne
    « maintenant », la démo doit s'étaler sur six semaines)."""
    delta = target - since
    for model, cols in ((CheckIn, ("opened_at", "closed_at")), (AssessmentSession, ("started_at", "ended_at")),
                        (Response, ("created_at",)), (WeeklyPlan, ("generated_at",)),
                        (PlanAction, ("done_at", "dismissed_at")), (Proof, ("computed_at",)),
                        (AuditLog, ("created_at",))):
        for col in cols:
            column = getattr(model, col)
            rows = s.execute(select(model).where(column >= since)).scalars().all()
            for r in rows:
                v = getattr(r, col)
                if v is not None:
                    if v.tzinfo is None:
                        v = v.replace(tzinfo=timezone.utc)
                    setattr(r, col, v + delta)
    s.flush()


def _graph(s: Session):
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    code_of = {cid: c.code for cid, c in comps.items()}
    down: Dict[str, set] = {}
    for e in s.execute(select(CompetencyPrerequisite).where(CompetencyPrerequisite.edge_type == EdgeType.HARD)).scalars():
        if e.source_id in code_of and e.target_id in code_of:
            down.setdefault(code_of[e.source_id], set()).add(code_of[e.target_id])

    def closure(code: str) -> set:
        seen, stack = set(), [code]
        while stack:
            c = stack.pop()
            for t in down.get(c, ()):
                if t not in seen:
                    seen.add(t); stack.append(t)
        return seen
    return comps, code_of, closure


# --- banque ------------------------------------------------------------------------------

def ensure_bank(s: Session) -> int:
    comps = {c.code: c for c in s.execute(select(Competency)).scalars()}
    if not comps:
        raise SystemExit("référentiel absent : lancer scripts/seed_referentiel.py d'abord")
    n_items = s.execute(select(Item).where(Item.deleted_at.is_(None))).scalars().all()
    if not n_items:
        gen: List[GeneratedItem] = []
        for code in deterministic.all_codes():
            comp = comps.get(code)
            if comp is None:
                continue
            for e in deterministic.bank_items(code, comp.difficulty_prior):
                gen.append(GeneratedItem(competency_id=comp.id, content_en=e["content"], answer_format=AnswerFormat.MCQ,
                                         difficulty_prior=e["difficulty_prior"], context_tags={**e["context_tags"], "gen": "deterministic"},
                                         provenance={"generator": "deterministic", "method": "exact-fraction"},
                                         template_key=e["template_key"], content_ar=render_arabic(e["content"])))
        review.insert_generated_items(s, gen)
    activated = 0
    for it in s.execute(select(Item).where(Item.deleted_at.is_(None), Item.status != ItemStatus.ACTIVE,
                                           Item.status != ItemStatus.QUARANTINED)).scalars().all():
        if not it.content_ar:
            continue
        try:
            if it.status == ItemStatus.AI_GENERATED:
                review.approve(s, it, reviewer="demo")
            if it.status == ItemStatus.HUMAN_REVIEWED:
                review.validate_arabic(s, it, linguist="demo")
            if it.status == ItemStatus.LINGUIST_VALIDATED:
                review.promote_to_active(s, it, reviewer="demo")
            activated += 1
        except review.InvalidTransition:
            continue
    s.commit()
    return activated


def ensure_lessons(s: Session) -> int:
    rep = lesson_service.seed_lessons(s, lesson_service.LESSONS_DIR)
    created = len(rep["created"])
    for cov in lesson_service.coverage(s):
        if cov["lessons"]:
            continue
        doc = lesson_service.doc_from_payload({
            "key": f"{cov['code']}.demo", "competency": cov["code"], "version": 0, "duration_min": 12,
            "title_en": f"[DEMO] Reteach: {cov['label_en']}", "title_ar": f"[عرض] إعادة تدريس: {cov['label_ar']}",
            "steps": [
                {"kind": "warmup", "minutes": 2, "body_en": "[DEMO] One quick whole-class question on the skill.", "body_ar": "[عرض] سؤال سريع للصف كله عن المهارة."},
                {"kind": "model", "minutes": 4, "body_en": "[DEMO] Teacher models the move, thinking aloud.", "body_ar": "[عرض] يعرض المعلّم الخطوة مفكّرًا بصوت عالٍ."},
                {"kind": "guided", "minutes": 4, "body_en": "[DEMO] Pairs try two items; teacher listens for the typical error.", "body_ar": "[عرض] يحلّ الطلاب سؤالَين في أزواج؛ ويستمع المعلّم للخطأ النمطي."},
                {"kind": "exit", "minutes": 2, "body_en": "[DEMO] One exit question per student.", "body_ar": "[عرض] سؤال خروج واحد لكل طالب."},
            ]})
        lesson_service.upsert_lesson(s, doc)
        created += 1
    s.commit()
    return created


# --- tenant ------------------------------------------------------------------------------

def reset_tenant(s: Session) -> None:
    org = s.execute(select(Organization).where(Organization.domain == DOMAIN)).scalar_one_or_none()
    if org is not None:
        erase_tenant(s, org)
        s.commit()


def build_tenant(s: Session, *, n_students: int, rng: random.Random):
    org = Organization(name="Al Noor Education", domain=DOMAIN, seats=80); s.add(org); s.flush()
    alnoor = School(name="Al Noor Academy", organization_id=org.id, country="AE")
    riverside = School(name="Riverside School", organization_id=org.id, country="AE")
    s.add_all([alnoor, riverside]); s.flush()
    cls4b = Classroom(school_id=alnoor.id, name="4B", grade=4)
    cls4a = Classroom(school_id=riverside.id, name="4A", grade=4)
    s.add_all([cls4b, cls4a]); s.flush()

    # staff Atlas (global) et rôles du tenant
    _membership(s, _user(s, ACCOUNTS["super"]), Role.SUPER_ADMIN)
    _membership(s, _user(s, ACCOUNTS["reviewer"]), Role.CONTENT_REVIEWER)
    _membership(s, _user(s, ACCOUNTS["linguist"]), Role.LINGUIST)
    _membership(s, _user(s, ACCOUNTS["it"]), Role.IT_ADMIN, organization_id=org.id)
    _membership(s, _user(s, ACCOUNTS["ped"]), Role.PED_ADMIN, school_id=alnoor.id)
    m_coord = _membership(s, _user(s, ACCOUNTS["coord"]), Role.DEPT_LEAD, school_id=alnoor.id)
    s.add(DeptLeadScope(membership_id=m_coord.id, grade=4))
    _membership(s, _user(s, ACCOUNTS["group"]), Role.GROUP_ADMIN, organization_id=org.id)
    t1 = _user(s, ACCOUNTS["teacher"]); _membership(s, t1, Role.TEACHER, school_id=alnoor.id)
    s.add(TeacherClassroom(user_id=t1.id, classroom_id=cls4b.id))
    t2 = _user(s, ACCOUNTS["teacher2"]); _membership(s, t2, Role.TEACHER, school_id=riverside.id)
    s.add(TeacherClassroom(user_id=t2.id, classroom_id=cls4a.id))

    def make_students(school, cls, n, prefix, offset=0):
        out = []
        for i in range(n):
            u = _user(s, f"{prefix}{i + 1 + offset:02d}@demo.atlas")
            _membership(s, u, Role.STUDENT, school_id=school.id)
            st = Student(school_id=school.id, classroom_id=cls.id, user_id=u.id, external_ref=f"{cls.name}-{i + 1:02d}")
            s.add(st); s.flush()
            s.add(StudentClassroom(student_id=st.id, classroom_id=cls.id))
            out.append(st)
        return out
    students_4b = make_students(alnoor, cls4b, n_students, "eleve")
    students_4a = make_students(riverside, cls4a, max(6, n_students // 3), "eleve", offset=n_students)
    parent = _user(s, ACCOUNTS["parent"]); _membership(s, parent, Role.PARENT, organization_id=org.id)
    s.add(ParentStudent(user_id=parent.id, student_id=students_4b[0].id, source="staff"))
    s.commit()
    return org, alnoor, riverside, cls4b, cls4a, t1, t2, students_4b, students_4a


# --- simulation --------------------------------------------------------------------------

class Latent:
    """Niveau latent par élève et compétence : un profil de déficit (racine + aval) ou fluide."""

    def __init__(self, students: List[Student], code_of_ids: List[str], closure, rng: random.Random):
        self.rng = rng
        self.level: Dict[uuid.UUID, Dict[str, float]] = {}
        order = list(students); rng.shuffle(order)
        i = 0
        for root, share in PROFILES:
            n = round(len(order) * share)
            weak = {root} | closure(root)
            for st in order[i:i + n]:
                self.level[st.id] = {c: (rng.gauss(1150, 70) if c in weak else rng.gauss(1560, 70)) for c in code_of_ids}
            i += n
        for st in order[i:]:
            self.level[st.id] = {c: rng.gauss(1760, 60) for c in code_of_ids}

    def answer(self, student_id: uuid.UUID, item: Item, code: str) -> str:
        p = 1.0 / (1.0 + 10 ** ((item.difficulty_elo - self.level[student_id][code]) / 400.0))
        content = item.content_en
        if self.rng.random() < p:
            return content["answer"]
        wrong = [o for o in content.get("options", []) if o != content["answer"]] or [content["answer"]]
        return self.rng.choice(wrong)

    def teach(self, student_ids: List[uuid.UUID], root: str, closure, rng: random.Random) -> None:
        """Effet d'une mini-leçon : 70 % des membres progressent nettement sur la racine (et un
        peu en aval), les autres peu."""
        for sid in student_ids:
            gain = rng.gauss(330, 60) if rng.random() < 0.7 else rng.gauss(50, 30)
            self.level[sid][root] += gain
            for c in closure(root):
                self.level[sid][c] += gain * 0.35


def run_session(s: Session, sess: AssessmentSession, latent: Latent, code_of, max_items: int = 14) -> int:
    n = 0
    nxt = next_item(s, sess, STOP)
    while not nxt.get("done") and n < max_items:
        item = s.get(Item, uuid.UUID(nxt["item_id"]))
        selected = latent.answer(sess.student_id, item, code_of[item.competency_id])
        correct = grade_answer(item, selected, "en")
        nxt = submit_response(s, sess, item_id=item.id, is_correct=correct, config=STOP, selected=selected)
        n += 1
    return n


def simulate_class(s: Session, *, school: School, cls: Classroom, teacher: AppUser, students: List[Student],
                   weeks: int, latent: Latent, closure, code_of, comps, rng: random.Random, log) -> None:
    now = utcnow()
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for k in range(weeks, 0, -1):
        monday = this_monday - timedelta(weeks=k)
        # --- jeudi : check-in complet → plan pour la semaine suivante ---
        marker = utcnow()
        ci = checkin_service.open_checkin(s, classroom=cls, created_by=teacher.id, kind=CheckInKind.FULL, rng=rng)
        s.commit()
        joined = 0
        for st in students:
            if rng.random() < 0.08:
                continue                                                     # absent ce jour-là
            sess = checkin_service.join_checkin(s, code=ci.code, student=st, locale=rng.choice(["en", "en", "ar"]))
            run_session(s, sess, latent, code_of); joined += 1
        checkin_service.close_checkin(s, ci, by=teacher.id)
        plan = plan_service.generate_plan_for_checkin(s, ci, by=teacher.id, week_start=(monday + timedelta(weeks=1)).date())
        s.commit()
        _backdate(s, marker, monday + timedelta(days=3, hours=10)); s.commit()
        actions = s.execute(select(PlanAction).where(PlanAction.plan_id == plan.id).order_by(PlanAction.rank)).scalars().all()
        log(f"  {cls.name} · semaine du {monday.date()} : {joined} élèves, plan {len(actions)} action(s)")
        if k == 1:
            break                                                            # le plan courant reste « à faire »
        # --- semaine suivante : enseigner les 2 premières actions, re-mesurer ---
        for j, action in enumerate(actions):
            marker = utcnow()
            if j >= 2:
                if j == 2 and rng.random() < 0.5:
                    plan_service.dismiss(s, action, by=teacher.id); s.commit()
                    _backdate(s, marker, monday + timedelta(weeks=1, days=1, hours=8)); s.commit()
                continue
            if k == weeks - 1 and j == 0:                                    # une correction de groupe enregistrée
                members = plan_service._members(s, action.id)
                others = [st.id for st in students if st.id not in {m.student_id for m in members}]
                if members and others:
                    plan_service.set_members(s, action, add=[rng.choice(others)], remove=[members[0].student_id],
                                             class_student_ids={st.id for st in students}, by=teacher.id)
                    s.commit()
            _, recheck = proof_service.mark_done(s, action, by=teacher.id); s.commit()
            root_code = code_of[action.root_cause_competency_id]
            member_ids = [uuid.UUID(x) for x in recheck.student_ids]
            latent.teach(member_ids, root_code, closure, rng)
            proof_service.start_checkin(s, recheck, by=teacher.id); s.commit()
            for sid in member_ids:
                if rng.random() < 0.15:
                    continue                                                 # absent au re-check
                st = s.get(Student, sid)
                sess = checkin_service.join_checkin(s, code=recheck.code, student=st)
                run_session(s, sess, latent, code_of, max_items=8)
            checkin_service.close_checkin(s, recheck, by=teacher.id)
            proof_service.compute_proofs(s, recheck, by=teacher.id)
            s.commit()
            _backdate(s, marker, monday + timedelta(weeks=1, days=1 + j, hours=9)); s.commit()


def add_flags(s: Session, teacher: AppUser, school: School, rng: random.Random) -> None:
    items = s.execute(select(Item).where(Item.status == ItemStatus.ACTIVE)).scalars().all()
    rng.shuffle(items)
    for it, reason, comment in ((items[0], ItemFlagReason.SEVERAL_CORRECT, "Two options are equivalent (same value)."),
                                (items[1], ItemFlagReason.UNCLEAR_WORDING, "Students read 'lowest terms' as 'smallest numbers'.")):
        review.flag_item(s, it, raised_by=teacher.id, reason=reason, comment=comment, school_id=school.id)
    s.commit()


def main(argv: Optional[List[str]] = None) -> dict:
    p = argparse.ArgumentParser()
    p.add_argument("--weeks", type=int, default=6)
    p.add_argument("--students", type=int, default=26)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    rng = random.Random(args.seed)
    log = (lambda *_: None) if args.quiet else print

    with SessionLocal(bind=make_engine()) as s:
        activated = ensure_bank(s)
        n_lessons = ensure_lessons(s)
        reset_tenant(s)
        org, alnoor, riverside, cls4b, cls4a, t1, t2, st4b, st4a = build_tenant(s, n_students=args.students, rng=rng)
        comps, code_of, closure = _graph(s)
        codes = list(code_of.values())
        log(f"Banque : {activated} items activés ; leçons créées : {n_lessons}")
        simulate_class(s, school=alnoor, cls=cls4b, teacher=t1, students=st4b, weeks=args.weeks,
                       latent=Latent(st4b, codes, closure, rng), closure=closure, code_of=code_of, comps=comps, rng=rng, log=log)
        simulate_class(s, school=riverside, cls=cls4a, teacher=t2, students=st4a, weeks=min(2, args.weeks),
                       latent=Latent(st4a, codes, closure, rng), closure=closure, code_of=code_of, comps=comps, rng=rng, log=log)
        add_flags(s, t1, alnoor, rng)
        summary = {
            "organization_id": str(org.id), "school_id": str(alnoor.id), "classroom_id": str(cls4b.id),
            "plans": len(s.execute(select(WeeklyPlan)).scalars().all()),
            "active_plan": s.execute(select(WeeklyPlan).where(WeeklyPlan.classroom_id == cls4b.id,
                                                              WeeklyPlan.status == PlanStatus.ACTIVE)).scalars().first() is not None,
            "proofs": len(s.execute(select(Proof)).scalars().all()),
            "checkins": len(s.execute(select(CheckIn)).scalars().all()),
            "responses": len(s.execute(select(Response)).scalars().all()),
        }
    log("\nDémo prête." + "".join(f"\n  {k}: {v}" for k, v in summary.items()))
    log("\nComptes (SSO simulé : OIDC_DEV_LOGIN=1, POST /dev/login) :")
    for k, v in ACCOUNTS.items():
        log(f"  {k:9s} {v}")
    log(f"  élèves    eleve01@demo.atlas … eleve{args.students:02d}@demo.atlas")
    return summary


if __name__ == "__main__":
    main()
