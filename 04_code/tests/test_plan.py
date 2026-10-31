"""Refonte B2 — générateur du plan de la semaine.

« Fait quand » : même entrée → même plan. Tests : déterminisme (ordre d'entrée indifférent),
aucune action sans membre, aucune action sur une compétence hors unité, regroupement par cause
racine, tri par élèves débloquables, confiance partly_estimated, phrases « parce que » EN/AR,
génération à la clôture d'un check-in full (pas targeted), supersession, corrections enseignant,
RBAC, rétention.
"""
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import plan_service
from src.api.app import app, get_db
from src.compliance.service import erase_student, export_tenant
from src.models import competency, item, measurement, org, session as _se, audit as _au, checkin as _ci, plan as _pl  # noqa: F401
from src.models.base import (
    Base, CompetencyStatus, EdgeType, ItemStatus, AnswerFormat, PlanActionStatus, PlanStatus, Role, Subject,
    WeightSource,
)
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.item import Item
from src.models.measurement import School, Student, StudentCompetencyAbility
from src.models.org import AppUser, Classroom, Membership, Organization, StudentClassroom, TeacherClassroom
from src.models.plan import PlanAction, PlanActionMember, WeeklyPlan
from src.rbac.auth import make_token
from src.restitution.plan import Ability, build_plan

# Graphe : A ← B ← C (HARD), D indépendant, Z hors unité dépend de A.
HARD = {"B": ["A"], "C": ["B"], "Z": ["A"]}
EN = {"A": "Unit fractions", "B": "Add like fractions", "C": "Add unlike fractions", "D": "Compare", "Z": "Decimals"}
AR = {"A": "الكسور الوحدية", "B": "جمع الكسور المتشابهة", "C": "جمع الكسور المختلفة", "D": "المقارنة", "Z": "الأعداد العشرية"}
UNIT = ["B", "C", "D"]


def ab(elo, conf=0.9, n=5):
    return Ability(elo, conf, n)


def _class():
    # s1, s2, s3 : bloqués sur B/C parce que A n'est pas maîtrisé ; s4 : lacune propre sur D ;
    # s5 : A estimé (confiance faible) ; s6 : tout maîtrisé ; s7 : lacune sur Z seulement (hors unité).
    return {
        "s1": {"A": ab(1200), "B": ab(1300), "C": ab(1250)},
        "s2": {"A": ab(1100), "B": ab(1200)},
        "s3": {"A": ab(1150), "C": ab(1300)},
        "s4": {"A": ab(1700), "B": ab(1700), "D": ab(1200)},
        "s5": {"A": ab(1200, conf=0.2, n=1), "B": ab(1300)},
        "s6": {"A": ab(1800), "B": ab(1800), "C": ab(1800), "D": ab(1800)},
        "s7": {"A": ab(1200), "Z": ab(1100)},
    }


def test_groups_by_root_sorts_by_unlockable_and_stays_in_unit():
    actions = build_plan(_class(), HARD, UNIT, EN, AR)
    assert [a.rank for a in actions] == [1, 2]
    a1, a2 = actions
    # racine A : s1, s2, s3, s5 (s7 exclu : sa lacune Z est hors unité) ; bloqué = B (3 sur 4)
    assert a1.root_cause == "A" and a1.blocked == "B" and a1.n_unlockable == 4
    assert [m.student_id for m in a1.members] == ["s1", "s2", "s3", "s5"]
    assert a1.confidence == "partly_estimated"            # s5 : racine estimée
    assert a1.because_en == "Because Unit fractions is not mastered yet, 4 students are blocked on Add like fractions."
    assert a1.because_ar == "لأن «الكسور الوحدية» غير مُتقَن بعد، يتعثّر 4 من الطلاب في «جمع الكسور المتشابهة»."
    # racine D (lacune propre) : s4 seul, mesurée
    assert a2.root_cause == "D" and a2.blocked == "D" and a2.n_unlockable == 1 and a2.confidence == "measured"
    assert a2.because_en == "Because Compare itself is not mastered yet, 1 student need to practise it." or \
        a2.because_en.startswith("Because Compare itself is not mastered yet, 1 student")
    assert all(a.blocked in UNIT for a in actions)          # jamais hors unité
    assert all(a.members for a in actions)                  # jamais sans membre
    assert "Z" not in {a.root_cause for a in actions} | {a.blocked for a in actions}


def test_deterministic_regardless_of_input_order():
    base = build_plan(_class(), HARD, UNIT, EN, AR)
    shuffled = {k: _class()[k] for k in reversed(sorted(_class()))}
    shuffled = {k: {c: v[c] for c in reversed(sorted(v))} for k, v in shuffled.items()}
    hard_rev = {k: list(reversed(v)) for k, v in HARD.items()}
    again = build_plan(shuffled, hard_rev, list(reversed(UNIT)), EN, AR)
    assert [(a.rank, a.root_cause, a.blocked, [m.student_id for m in a.members], a.confidence, a.because_en, a.because_ar)
            for a in base] == \
           [(a.rank, a.root_cause, a.blocked, [m.student_id for m in a.members], a.confidence, a.because_en, a.because_ar)
            for a in again]


def test_caps_at_four_actions_and_empty_class_gives_none():
    many = {f"s{i}": {f"R{i}": ab(1100)} for i in range(6)}          # 6 racines distinctes (lacunes propres)
    actions = build_plan(many, {}, [f"R{i}" for i in range(6)], {}, {})
    assert len(actions) == 4 and [a.rank for a in actions] == [1, 2, 3, 4]
    assert build_plan({}, HARD, UNIT, EN, AR) == []
    assert build_plan({"s6": _class()["s6"]}, HARD, UNIT, EN, AR) == []     # tout maîtrisé : rien à ré-enseigner


# ---------- service + API ----------

def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _comp(s, code, label_en, label_ar):
    c = Competency(code=code, label_en=label_en, label_ar=label_ar, subject=Subject.MATH, grade=4,
                   difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)
    s.add(c); s.flush()
    return c


def _setup():
    s = _session()
    org = Organization(name="Org"); s.add(org); s.flush()
    school = School(name="A", organization_id=org.id); s.add(school); s.flush()
    cls = Classroom(school_id=school.id, name="4B", grade=4); other = Classroom(school_id=school.id, name="5A", grade=5)
    s.add_all([cls, other]); s.flush()
    A = _comp(s, "M.A", EN["A"], AR["A"]); B = _comp(s, "M.B", EN["B"], AR["B"]); C = _comp(s, "M.C", EN["C"], AR["C"])
    D = _comp(s, "M.D", EN["D"], AR["D"])
    s.add_all([CompetencyPrerequisite(source_id=A.id, target_id=B.id, edge_type=EdgeType.HARD,
                                      correlation_strength=0.8, weight_source=WeightSource.EXPERT),
               CompetencyPrerequisite(source_id=B.id, target_id=C.id, edge_type=EdgeType.HARD,
                                      correlation_strength=0.8, weight_source=WeightSource.EXPERT)])
    for c in (A, B, C, D):
        s.add(Item(competency_id=c.id, content_en={"stem": "q", "options": ["1", "2"], "answer": "1"},
                   answer_format=AnswerFormat.MCQ, difficulty_prior=1500.0, status=ItemStatus.ACTIVE, ar_validated=True))
    teacher = AppUser(email="t@x.io"); other_t = AppUser(email="t2@x.io"); s.add_all([teacher, other_t]); s.flush()
    s.add_all([Membership(user_id=teacher.id, role=Role.TEACHER, school_id=school.id),
               TeacherClassroom(user_id=teacher.id, classroom_id=cls.id),
               Membership(user_id=other_t.id, role=Role.TEACHER, school_id=school.id),
               TeacherClassroom(user_id=other_t.id, classroom_id=other.id)])
    students = []
    for i in range(4):
        st = Student(school_id=school.id, classroom_id=cls.id, external_ref=f"S{i}"); s.add(st); s.flush()
        s.add(StudentClassroom(student_id=st.id, classroom_id=cls.id)); students.append(st)
    outsider = Student(school_id=school.id, classroom_id=other.id); s.add(outsider); s.flush()
    def abil(st, c, elo, conf=0.9, n=5):
        s.add(StudentCompetencyAbility(student_id=st.id, competency_id=c.id, school_id=school.id,
                                       ability_elo=elo, confidence=conf, n_direct=n))
    # s0, s1 : A faible → bloqués sur B ; s2 : lacune propre D ; s3 : tout maîtrisé
    abil(students[0], A, 1200); abil(students[0], B, 1300)
    abil(students[1], A, 1100); abil(students[1], B, 1250); abil(students[1], C, 1200)
    abil(students[2], A, 1700); abil(students[2], D, 1200)
    abil(students[3], A, 1800); abil(students[3], B, 1800)
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    ids = dict(org=org.id, school=school.id, cls=cls.id, other=other.id, teacher=teacher.id, other_t=other_t.id,
               students=[st.id for st in students], outsider=outsider.id, A=A.id, B=B.id, C=C.id, D=D.id)
    return TestClient(app), ids, s


def test_closing_a_full_checkin_generates_a_stable_plan():
    client, ids, s = _setup()
    try:
        h = _auth(ids["teacher"])
        assert client.get(f"/classrooms/{ids['cls']}/plan", headers=h).status_code == 404     # pas encore de plan
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        closed = client.post(f"/checkins/{ci['id']}/close", headers=h).json()
        assert closed["plan_id"]
        plan = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()
        assert plan["id"] == closed["plan_id"] and plan["status"] == "active" and plan["source_checkin_id"] == ci["id"]
        assert date.fromisoformat(plan["week_start"]).weekday() == 0                       # un lundi
        acts = plan["actions"]
        assert [a["rank"] for a in acts] == [1, 2]
        assert acts[0]["root_cause"]["code"] == "M.A" and acts[0]["blocked"]["code"] == "M.B"
        assert acts[0]["n_members"] == 2 and acts[0]["confidence"] == "measured"
        assert {m["external_ref"] for m in acts[0]["members"]} == {"S0", "S1"}
        assert acts[0]["because_ar"].startswith("لأن")
        assert acts[1]["root_cause"]["code"] == "M.D" and acts[1]["blocked"]["code"] == "M.D" and acts[1]["n_members"] == 1
        # même entrée (un second check-in clos la même semaine) → même plan ; l'ancien passe superseded
        ci2 = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        closed2 = client.post(f"/checkins/{ci2['id']}/close", headers=h).json()
        plan2 = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()
        assert plan2["id"] == closed2["plan_id"] != plan["id"]
        strip = lambda p: [(a["rank"], a["root_cause"]["code"], a["blocked"]["code"], a["because_en"], a["because_ar"],
                            sorted(m["student_id"] for m in a["members"])) for a in p["actions"]]
        assert strip(plan2) == strip(plan)
        assert s.get(WeeklyPlan, uuid.UUID(plan["id"])).status == PlanStatus.SUPERSEDED
        assert len(s.execute(select(WeeklyPlan).where(WeeklyPlan.status == PlanStatus.ACTIVE)).scalars().all()) == 1
        # un check-in ciblé ne génère pas de plan
        ci3 = client.post(f"/classrooms/{ids['cls']}/checkins",
                          json={"kind": "targeted", "competency_ids": [str(ids["A"])]}, headers=h).json()
        assert client.post(f"/checkins/{ci3['id']}/close", headers=h).json()["plan_id"] is None
        # RBAC lecture : autre enseignant → 403
        assert client.get(f"/classrooms/{ids['cls']}/plan", headers=_auth(ids["other_t"])).status_code == 403
        assert client.get(f"/plan-actions/{acts[0]['id']}", headers=_auth(ids["other_t"])).status_code == 403
        assert client.get(f"/plan-actions/{acts[0]['id']}", headers=h).status_code == 200
        assert client.get(f"/classrooms/{ids['cls']}/plan?week=2020-01-06", headers=h).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_unit_restricts_actions_to_checkin_competencies():
    client, ids, s = _setup()
    try:
        h = _auth(ids["teacher"])
        # check-in full limité à D : les lacunes sur B (racine A) sont hors unité → une seule action (D)
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full", "competency_ids": [str(ids["D"])]},
                         headers=h).json()
        pid = client.post(f"/checkins/{ci['id']}/close", headers=h).json()["plan_id"]
        plan = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()
        assert plan["id"] == pid and [a["blocked"]["code"] for a in plan["actions"]] == ["M.D"]
    finally:
        app.dependency_overrides.clear()


def test_teacher_corrections_are_recorded_and_dismiss():
    client, ids, s = _setup()
    try:
        h = _auth(ids["teacher"])
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        client.post(f"/checkins/{ci['id']}/close", headers=h)
        act = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()["actions"][0]
        aid = act["id"]
        s3, s0 = str(ids["students"][3]), str(ids["students"][0])
        assert client.patch(f"/plan-actions/{aid}/members", json={"add": [s3]}, headers=_auth(ids["other_t"])).status_code == 403
        assert client.patch(f"/plan-actions/{aid}/members", json={"add": [str(ids["outsider"])]}, headers=h).status_code == 400
        r = client.patch(f"/plan-actions/{aid}/members", json={"add": [s3], "remove": [s0]}, headers=h).json()
        by_id = {m["student_id"]: m for m in r["members"]}
        assert by_id[s3]["source"] == "teacher_added" and by_id[s0]["removed_by_teacher"] is True
        assert r["n_members"] == 2 and len(r["members"]) == 3                         # la correction est enregistrée, pas effacée
        r = client.patch(f"/plan-actions/{aid}/members", json={"add": [s0]}, headers=h).json()   # ré-ajout : annule le retrait
        assert {m["student_id"]: m["removed_by_teacher"] for m in r["members"]}[s0] is False
        assert client.post(f"/plan-actions/{aid}/dismiss", headers=_auth(ids["other_t"])).status_code == 403
        d = client.post(f"/plan-actions/{aid}/dismiss", headers=h).json()
        assert d["status"] == "dismissed" and d["dismissed_at"]
        assert client.get(f"/plan-actions/{uuid.uuid4()}", headers=h).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_retention_cascades_members_and_export_lists_plans():
    client, ids, s = _setup()
    try:
        h = _auth(ids["teacher"])
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        client.post(f"/checkins/{ci['id']}/close", headers=h)
        victim = s.get(Student, ids["students"][0])
        erase_student(s, victim); s.commit(); s.expire_all()
        assert s.execute(select(PlanActionMember).where(PlanActionMember.student_id == ids["students"][0])).scalars().all() == []
        assert len(s.execute(select(PlanAction)).scalars().all()) == 2                 # les actions restent
        export = export_tenant(s, s.get(Organization, ids["org"]))
        assert len(export["weekly_plans"]) == 1 and len(export["weekly_plans"][0]["actions"]) == 2
        assert str(ids["students"][0]) not in sum((a["student_ids"] for a in export["weekly_plans"][0]["actions"]), [])
    finally:
        app.dependency_overrides.clear()


def test_observed_error_from_checkin_responses_and_lesson_attached():
    # Q16 : l'erreur observée vient des réponses FAUSSES du check-in sur la compétence bloquée,
    # option choisie connue ; B3 : la meilleure leçon de la racine est attachée à l'action.
    from src.api import lesson_service
    from src.models.checkin import CheckIn
    from src.models.measurement import Response
    from src.models.session import AssessmentSession
    from src.restitution.plan import WrongAnswer, observed_error_text
    assert observed_error_text([], 3) is None
    assert observed_error_text([WrongAnswer("What is 1/3 + 1/6?", "2/9")] * 3 + [WrongAnswer("What is 1/2 + 1/4?", "2/6")], 4) == \
        "What is 1/3 + 1/6? → 2/9 · 4 of 4 items wrong"
    assert observed_error_text([WrongAnswer("b", "x"), WrongAnswer("a", "x")], 2) == "a → x · 2 of 2 items wrong"   # ex aequo : énoncé min

    client, ids, s = _setup()
    try:
        h = _auth(ids["teacher"])
        lesson, _ = lesson_service.upsert_lesson(s, lesson_service.LessonDoc.model_validate({
            "key": "M.A.v1", "competency": "M.A", "title_en": "Unit fractions in 10 minutes", "duration_min": 10,
            "steps": [{"kind": "model", "minutes": 10, "body_en": "..."}]}))
        s.commit()
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        # s0 a répondu 2 items de B pendant le check-in, dont 1 faux (option 2) ; s1 rien
        item_b = s.execute(select(Item).where(Item.competency_id == ids["B"])).scalars().first()
        item_b2 = Item(competency_id=ids["B"], content_en={"stem": "q2", "options": ["1", "2"], "answer": "1"},
                       answer_format=AnswerFormat.MCQ, difficulty_prior=1500.0, status=ItemStatus.ACTIVE, ar_validated=True)
        s.add(item_b2); s.flush()
        sess = AssessmentSession(student_id=ids["students"][0], school_id=ids["school"], checkin_id=uuid.UUID(ci["id"]))
        s.add(sess); s.flush()
        s.add_all([Response(school_id=ids["school"], student_id=ids["students"][0], item_id=item_b.id, competency_id=ids["B"],
                            is_correct=False, selected="2", session_id=sess.id),
                   Response(school_id=ids["school"], student_id=ids["students"][0], item_id=item_b2.id, competency_id=ids["B"],
                            is_correct=True, selected="1", session_id=sess.id)])
        s.commit()
        client.post(f"/checkins/{ci['id']}/close", headers=h)
        act = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()["actions"][0]
        by_id = {m["student_id"]: m for m in act["members"]}
        assert by_id[str(ids["students"][0])]["observed_error"] == "q → 2 · 1 of 2 items wrong"
        assert by_id[str(ids["students"][1])]["observed_error"] is None
        assert act["lesson_id"] == str(lesson.id) and act["lesson"]["title_en"] == "Unit fractions in 10 minutes"
        assert act["lesson"]["status"] == "draft"
        assert client.get(f"/plan-actions/{act['id']}", headers=h).json()["lesson"]["key"] == "M.A.v1"
    finally:
        app.dependency_overrides.clear()


def test_class_matrix_states_and_member_root_state():
    client, ids, s = _setup()
    try:
        h = _auth(ids["teacher"])
        m = client.get(f"/classrooms/{ids['cls']}/matrix", headers=h).json()
        assert [c["code"] for c in m["competencies"]] == ["M.A", "M.B", "M.C", "M.D"]
        by_ref = {st["external_ref"]: st for st in m["students"]}
        assert by_ref["S0"]["cells"]["M.A"]["state"] == "progress" and by_ref["S0"]["cells"]["M.D"]["state"] == "unmeasured"
        assert by_ref["S3"]["cells"]["M.A"]["state"] == "mastered" and by_ref["S3"]["n_mastered"] == 2
        assert client.get(f"/classrooms/{ids['cls']}/matrix", headers=_auth(ids["other_t"])).status_code == 403
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        client.post(f"/checkins/{ci['id']}/close", headers=h)
        act = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()["actions"][0]
        roots = {mm["external_ref"]: mm["root"] for mm in act["members"]}
        assert roots["S0"] == {"state": "progress", "elo": 1200.0, "confidence": 0.9}
    finally:
        app.dependency_overrides.clear()


def test_week_start_is_iso_monday():
    assert plan_service.week_start_of(date(2026, 11, 5)) == date(2026, 11, 2)     # jeudi → lundi
    assert plan_service.week_start_of(date(2026, 11, 2)) == date(2026, 11, 2)
    assert plan_service.week_start_of(date(2026, 11, 8)) == date(2026, 11, 2)     # dimanche → lundi précédent
