"""Refonte B1 — check-ins de classe et code.

« Fait quand » : un enseignant ouvre un check-in, 26 élèves rejoignent avec le code, `progress`
ne renvoie aucun identifiant, la clôture termine les sessions ouvertes proprement.
Tests : code unique parmi les ouverts, élève hors classe refusé, `progress` sans PII (test
explicite sur les clés renvoyées), RBAC, rejoindre idempotent, ciblage d'un groupe, effacement.
"""
import json
import random
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import checkin_service as svc
from src.api.app import app, get_db
from src.compliance.service import erase_student, export_tenant
from src.models import competency, item, measurement, org, session as _se, audit as _au, checkin as _ci  # noqa: F401
from src.models.base import (
    AnswerFormat, Base, CheckInKind, CheckInStatus, CompetencyStatus, ItemStatus, Role, Subject, utcnow,
)
from src.models.checkin import CheckIn
from src.models.competency import Competency
from src.models.item import Item
from src.models.measurement import School, Student
from src.models.org import AppUser, Classroom, DeptLeadScope, Membership, Organization, StudentClassroom, TeacherClassroom
from src.models.session import AssessmentSession
from src.rbac.auth import make_token

N_STUDENTS = 26
CONTENT = {"stem": "1/4 + 2/4 = ?", "options": ["1/4", "3/4"], "answer": "3/4"}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _setup():
    s = _session()
    org = Organization(name="Org"); s.add(org); s.flush()
    school = School(name="A", organization_id=org.id); s.add(school); s.flush()
    cls = Classroom(school_id=school.id, name="4B", grade=4); other = Classroom(school_id=school.id, name="5A", grade=5)
    s.add_all([cls, other]); s.flush()
    comp_a = Competency(code="X.A", label_en="a", label_ar="ا", subject=Subject.MATH, grade=4,
                        difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)
    comp_b = Competency(code="X.B", label_en="b", label_ar="ب", subject=Subject.MATH, grade=4,
                        difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)
    s.add_all([comp_a, comp_b]); s.flush()
    for c in (comp_a, comp_b):
        s.add(Item(competency_id=c.id, content_en=dict(CONTENT), content_ar=dict(CONTENT), answer_format=AnswerFormat.MCQ,
                   difficulty_prior=1500.0, difficulty_elo=1500.0, status=ItemStatus.ACTIVE, ar_validated=True))
    teacher = AppUser(email="t@x.io"); other_t = AppUser(email="t2@x.io"); lead = AppUser(email="lead@x.io")
    su = AppUser(email="ops@x.io"); s.add_all([teacher, other_t, lead, su]); s.flush()
    m_lead = Membership(user_id=lead.id, role=Role.DEPT_LEAD, school_id=school.id); s.add(m_lead); s.flush()
    s.add_all([Membership(user_id=teacher.id, role=Role.TEACHER, school_id=school.id),
               TeacherClassroom(user_id=teacher.id, classroom_id=cls.id),
               Membership(user_id=other_t.id, role=Role.TEACHER, school_id=school.id),
               TeacherClassroom(user_id=other_t.id, classroom_id=other.id),
               DeptLeadScope(membership_id=m_lead.id, grade=4),
               Membership(user_id=su.id, role=Role.SUPER_ADMIN)])
    students, student_users = [], []
    for i in range(N_STUDENTS):
        u = AppUser(email=f"s{i}@x.io"); s.add(u); s.flush()
        s.add(Membership(user_id=u.id, role=Role.STUDENT, school_id=school.id))
        st = Student(school_id=school.id, classroom_id=cls.id, user_id=u.id); s.add(st); s.flush()
        s.add(StudentClassroom(student_id=st.id, classroom_id=cls.id))
        students.append(st); student_users.append(u)
    outsider_u = AppUser(email="out@x.io"); s.add(outsider_u); s.flush()
    s.add(Membership(user_id=outsider_u.id, role=Role.STUDENT, school_id=school.id))
    outsider = Student(school_id=school.id, classroom_id=other.id, user_id=outsider_u.id); s.add(outsider); s.flush()
    s.add(StudentClassroom(student_id=outsider.id, classroom_id=other.id))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    ids = dict(org=org.id, school=school.id, cls=cls.id, other=other.id, comp_a=comp_a.id, comp_b=comp_b.id,
               teacher=teacher.id, other_t=other_t.id, lead=lead.id, su=su.id,
               students=[st.id for st in students], student_users=[u.id for u in student_users],
               outsider=outsider.id, outsider_u=outsider_u.id)
    return TestClient(app), ids, s


# ---------- service ----------

def test_code_is_four_digits_and_unique_among_open_checkins():
    s = _session()
    school = School(name="A"); s.add(school); s.flush()
    cls = Classroom(school_id=school.id, name="4B"); s.add(cls); s.flush()
    rng = random.Random(7)
    first = svc.open_checkin(s, classroom=cls, created_by=None, kind=CheckInKind.FULL, rng=rng); s.commit()
    assert re.fullmatch(r"\d{4}", first.code)
    # un tirage qui retombe sur le code ouvert est retiré : le second check-in reçoit un autre code
    class Fixed:
        seq = [int(first.code), int(first.code), 42]
        def randrange(self, n):
            return self.seq.pop(0)
    second = svc.open_checkin(s, classroom=cls, created_by=None, kind=CheckInKind.FULL, rng=Fixed()); s.commit()
    assert second.code == "0042" and second.code != first.code
    # un code CLOS redevient disponible
    svc.close_checkin(s, first, by=None); s.commit()
    class Fixed2:
        def randrange(self, n):
            return int(first.code)
    third = svc.open_checkin(s, classroom=cls, created_by=None, kind=CheckInKind.FULL, rng=Fixed2()); s.commit()
    assert third.code == first.code
    assert svc.find_open_by_code(s, first.code).id == third.id
    assert svc.find_open_by_code(s, "12") is None and svc.find_open_by_code(s, "abcd") is None


def test_open_validation():
    s = _session()
    school = School(name="A"); s.add(school); s.flush()
    cls = Classroom(school_id=school.id, name="4B"); s.add(cls); s.flush()
    with pytest.raises(svc.CheckInError):
        svc.open_checkin(s, classroom=cls, created_by=None, kind=CheckInKind.TARGETED)            # sans compétence
    with pytest.raises(svc.CheckInError):
        svc.open_checkin(s, classroom=cls, created_by=None, kind=CheckInKind.FULL, student_ids=[uuid.uuid4()])


# ---------- API : ouverture, 26 élèves, progression anonyme, clôture ----------

def _no_pii(payload, forbidden_ids):
    """Aucune clé évoquant un élève, aucun identifiant d'élève nulle part dans le payload."""
    text = json.dumps(payload)
    for fid in forbidden_ids:
        assert str(fid) not in text and fid.hex not in text
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(w in k.lower() for w in ("student", "name", "email", "user")), k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(payload)


def test_full_loop_26_students_join_anonymous_progress_and_close():
    client, ids, s = _setup()
    try:
        # RBAC d'ouverture : un autre enseignant, le coordinateur → 403 ; l'enseignant de la classe → 200
        for who in ("other_t", "lead"):
            assert client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=_auth(ids[who])).status_code == 403
        r = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=_auth(ids["teacher"]))
        assert r.status_code == 200
        ci = r.json()
        assert re.fullmatch(r"\d{4}", ci["code"]) and ci["status"] == "open" and ci["kind"] == "full"
        # le coordinateur voit le check-in sans le code ; l'enseignant avec
        lead_view = client.get(f"/checkins/{ci['id']}", headers=_auth(ids["lead"])).json()
        assert "code" not in lead_view
        assert client.get(f"/checkins/{ci['id']}", headers=_auth(ids["teacher"])).json()["code"] == ci["code"]
        assert client.get(f"/checkins/{ci['id']}", headers=_auth(ids["other_t"])).status_code == 403

        # 26 élèves rejoignent avec le code ; chacun obtient une session ciblée sur le check-in
        session_ids = []
        for u in ids["student_users"]:
            j = client.post("/checkins/join", json={"code": ci["code"]}, headers=_auth(u))
            assert j.status_code == 200, j.text
            assert j.json()["checkin_id"] == ci["id"]
            session_ids.append(j.json()["session_id"])
        assert len(set(session_ids)) == N_STUDENTS
        # re-rejoindre (rechargement) : même session, pas de doublon
        again = client.post("/checkins/join", json={"code": ci["code"]}, headers=_auth(ids["student_users"][0]))
        assert again.json()["session_id"] == session_ids[0]
        # élève hors classe → 403 ; code inconnu → 404 ; enseignant → 403
        assert client.post("/checkins/join", json={"code": ci["code"]}, headers=_auth(ids["outsider_u"])).status_code == 403
        assert client.post("/checkins/join", json={"code": "9999" if ci["code"] != "9999" else "0000"},
                           headers=_auth(ids["student_users"][1])).status_code == 404
        assert client.post("/checkins/join", json={"code": ci["code"]}, headers=_auth(ids["teacher"])).status_code == 403

        # deux élèves répondent à un item, un termine sa session
        for sid in session_ids[:2]:
            h = _auth(ids["student_users"][session_ids.index(sid)])
            nxt = client.get(f"/sessions/{sid}/next-item", headers=h).json()
            assert nxt["done"] is False
            client.post(f"/sessions/{sid}/responses", json={"item_id": nxt["item_id"], "selected": "3/4"}, headers=h)
        with s.begin_nested():
            done_sess = s.get(AssessmentSession, uuid.UUID(session_ids[2]))
            done_sess.status, done_sess.stop_reason, done_sess.ended_at = "completed", "test", utcnow()
        s.commit()

        # progression : compteurs + tuiles anonymes, aucune PII, visible par l'enseignant et le coordinateur
        assert client.get(f"/checkins/{ci['id']}/progress", headers=_auth(ids["other_t"])).status_code == 403
        for who in ("teacher", "lead", "su"):
            p = client.get(f"/checkins/{ci['id']}/progress", headers=_auth(ids[who]))
            assert p.status_code == 200
        p = p.json()
        assert p["counts"] == {"expected": N_STUDENTS, "joined": N_STUDENTS, "in_progress": N_STUDENTS - 1,
                               "finished": 1, "absent": 0}
        assert len(p["tiles"]) == N_STUDENTS
        assert all(tuple(sorted(t)) == tuple(sorted(svc.TILE_KEYS)) for t in p["tiles"])
        assert p["tiles"][0]["state"] == "finished" and {t["n_answered"] for t in p["tiles"][1:3]} == {1}
        _no_pii(p, ids["students"] + ids["student_users"])

        # clôture : réservée à l'enseignant ; termine proprement les sessions actives ; idempotente
        assert client.post(f"/checkins/{ci['id']}/close", headers=_auth(ids["lead"])).status_code == 403
        c = client.post(f"/checkins/{ci['id']}/close", headers=_auth(ids["teacher"]))
        assert c.status_code == 200 and c.json()["closed_sessions"] == N_STUDENTS - 1
        assert c.json()["progress"]["counts"]["finished"] == N_STUDENTS
        s.expire_all()
        sessions = s.execute(select(AssessmentSession).where(AssessmentSession.checkin_id == uuid.UUID(ci["id"]))).scalars().all()
        assert all(x.status == "completed" and x.ended_at is not None for x in sessions)
        assert sum(1 for x in sessions if x.stop_reason == "checkin_closed") == N_STUDENTS - 1
        assert s.get(CheckIn, uuid.UUID(ci["id"])).status == CheckInStatus.CLOSED
        # plus de réponse acceptée, plus de jointure possible, code libéré
        sid0, h0 = session_ids[0], _auth(ids["student_users"][0])
        assert client.get(f"/sessions/{sid0}/next-item", headers=h0).json()["done"] is True
        assert client.post("/checkins/join", json={"code": ci["code"]}, headers=h0).status_code == 404
        c2 = client.post(f"/checkins/{ci['id']}/close", headers=_auth(ids["teacher"])).json()
        assert c2["already_closed"] is True and c2["closed_sessions"] == 0
        # liste des check-ins de la classe
        lst = client.get(f"/classrooms/{ids['cls']}/checkins", headers=_auth(ids["teacher"])).json()
        assert [x["id"] for x in lst["checkins"]] == [ci["id"]] and "code" not in lst["checkins"][0]  # clos : pas de code
    finally:
        app.dependency_overrides.clear()


def test_targeted_checkin_restricts_to_group_and_competencies():
    client, ids, s = _setup()
    try:
        group = [str(x) for x in ids["students"][:5]]
        body = {"kind": "targeted", "competency_ids": [str(ids["comp_a"])], "student_ids": group}
        r = client.post(f"/classrooms/{ids['cls']}/checkins", json=body, headers=_auth(ids["teacher"]))
        assert r.status_code == 200 and r.json()["n_members"] == 5 and r.json()["n_competencies"] == 1
        code = r.json()["code"]
        # membre → session ciblée sur comp_a ; élève de la classe hors groupe → 403
        j = client.post("/checkins/join", json={"code": code, "locale": "ar"}, headers=_auth(ids["student_users"][0]))
        assert j.status_code == 200 and j.json()["locale"] == "ar"
        sess = s.get(AssessmentSession, uuid.UUID(j.json()["session_id"]))
        assert sess.target_competency_ids == [str(ids["comp_a"])]
        assert client.post("/checkins/join", json={"code": code}, headers=_auth(ids["student_users"][10])).status_code == 403
        p = client.get(f"/checkins/{r.json()['id']}/progress", headers=_auth(ids["teacher"])).json()
        assert p["counts"] == {"expected": 5, "joined": 1, "in_progress": 1, "finished": 0, "absent": 4}
        _no_pii(p, ids["students"])
        # targeted sans compétence → 400 ; full avec membres → 400
        assert client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "targeted"}, headers=_auth(ids["teacher"])).status_code == 400
        assert client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full", "student_ids": group},
                           headers=_auth(ids["teacher"])).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_two_open_checkins_get_distinct_codes_and_each_routes_its_students():
    client, ids, s = _setup()
    try:
        a = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=_auth(ids["teacher"])).json()
        b = client.post(f"/classrooms/{ids['other']}/checkins", json={"kind": "full"}, headers=_auth(ids["other_t"])).json()
        assert a["code"] != b["code"]
        # l'élève de 5A rejoint B, pas A
        assert client.post("/checkins/join", json={"code": a["code"]}, headers=_auth(ids["outsider_u"])).status_code == 403
        j = client.post("/checkins/join", json={"code": b["code"]}, headers=_auth(ids["outsider_u"]))
        assert j.status_code == 200 and j.json()["checkin_id"] == b["id"]
    finally:
        app.dependency_overrides.clear()


# ---------- rétention : student_ids d'un check-in ciblé, export ----------

def test_erase_student_removes_them_from_targeted_checkins_and_export_lists_checkins():
    client, ids, s = _setup()
    try:
        group = [str(x) for x in ids["students"][:3]]
        r = client.post(f"/classrooms/{ids['cls']}/checkins",
                        json={"kind": "targeted", "competency_ids": [str(ids["comp_a"])], "student_ids": group},
                        headers=_auth(ids["teacher"])).json()
        client.post("/checkins/join", json={"code": r["code"]}, headers=_auth(ids["student_users"][0]))
        victim = s.get(Student, ids["students"][0])
        erase_student(s, victim); s.commit(); s.expire_all()
        ci = s.get(CheckIn, uuid.UUID(r["id"]))
        assert str(ids["students"][0]) not in ci.student_ids and len(ci.student_ids) == 2
        assert s.execute(select(AssessmentSession).where(AssessmentSession.checkin_id == ci.id)).scalars().all() == []
        org = s.get(Organization, ids["org"])
        export = export_tenant(s, org)
        assert [c["id"] for c in export["checkins"]] == [r["id"]] and export["checkins"][0]["kind"] == "targeted"
    finally:
        app.dependency_overrides.clear()
