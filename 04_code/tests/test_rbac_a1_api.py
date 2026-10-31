"""Refonte A1 — accès croisés HTTP des rôles dept_lead et group_admin (invariant 7).

Deux organisations, trois écoles. Vérifie sur l'API réelle (TestClient) que :
- un group_admin lit les écoles de SON organisation (200) et pas une école d'une autre
  organisation (403), et n'a aucune portée classe ;
- un dept_lead lit les classes de SES niveaux (200), pas un autre niveau de la même école
  ni une classe d'une autre école (403) ;
- le niveau d'une classe se saisit en admin de l'école seulement (PATCH) ;
- /me expose ces périmètres au front.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import app, get_db
from src.models import competency, item, measurement, org, session as _se  # noqa: F401  (register tables)
from src.models.base import Base, Role
from src.models.measurement import School, Student
from src.models.org import (
    AppUser, Classroom, DeptLeadScope, Membership, Organization, StudentClassroom, TeacherClassroom,
)
from src.rbac.auth import make_token


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    s = Session(bind=engine)
    org_a, org_b = Organization(name="Groupe A"), Organization(name="Groupe B")
    s.add_all([org_a, org_b]); s.flush()
    s1 = School(name="A1", organization_id=org_a.id)
    s2 = School(name="A2", organization_id=org_a.id)
    s3 = School(name="B1", organization_id=org_b.id)
    s.add_all([s1, s2, s3]); s.flush()
    g4 = Classroom(school_id=s1.id, name="4A", grade=4)
    g5 = Classroom(school_id=s1.id, name="5A", grade=5)
    g4_s3 = Classroom(school_id=s3.id, name="4B", grade=4)
    s.add_all([g4, g5, g4_s3]); s.flush()
    st4 = Student(school_id=s1.id, classroom_id=g4.id); st5 = Student(school_id=s1.id, classroom_id=g5.id)
    s.add_all([st4, st5]); s.flush()
    s.add_all([StudentClassroom(student_id=st4.id, classroom_id=g4.id),
               StudentClassroom(student_id=st5.id, classroom_id=g5.id)])

    ga = AppUser(email="ga@a.io"); lead = AppUser(email="lead@a1.io")
    ped = AppUser(email="ped@a1.io"); teacher = AppUser(email="t@a1.io")
    s.add_all([ga, lead, ped, teacher]); s.flush()
    m_lead = Membership(user_id=lead.id, role=Role.DEPT_LEAD, school_id=s1.id); s.add(m_lead); s.flush()
    s.add_all([
        Membership(user_id=ga.id, role=Role.GROUP_ADMIN, organization_id=org_a.id),
        DeptLeadScope(membership_id=m_lead.id, grade=4),
        Membership(user_id=ped.id, role=Role.PED_ADMIN, school_id=s1.id),
        Membership(user_id=teacher.id, role=Role.TEACHER, school_id=s1.id),
        TeacherClassroom(user_id=teacher.id, classroom_id=g5.id),
    ])
    s.commit()
    ids = dict(s1=s1.id, s2=s2.id, s3=s3.id, g4=g4.id, g5=g5.id, g4_s3=g4_s3.id,
               st4=st4.id, st5=st5.id, ga=ga.id, lead=lead.id, ped=ped.id, teacher=teacher.id)
    app.dependency_overrides[get_db] = lambda: s
    return TestClient(app), ids


def test_group_admin_reads_schools_of_its_org_only():
    client, ids = _setup()
    try:
        for sid in ("s1", "s2"):
            assert client.get(f"/schools/{ids[sid]}/overview", headers=_auth(ids["ga"])).status_code == 200
            assert client.get(f"/schools/{ids[sid]}/proof", headers=_auth(ids["ga"])).status_code == 200
        # école d'une AUTRE organisation → 403
        assert client.get(f"/schools/{ids['s3']}/overview", headers=_auth(ids["ga"])).status_code == 403
        assert client.get(f"/schools/{ids['s3']}/proof", headers=_auth(ids["ga"])).status_code == 403
        # aucune portée classe ni élève nominatif, même dans son organisation
        assert client.get(f"/classrooms/{ids['g4']}/students", headers=_auth(ids["ga"])).status_code == 403
        assert client.get(f"/classrooms/{ids['g4']}/gaps", headers=_auth(ids["ga"])).status_code == 403
        assert client.get(f"/students/{ids['st4']}/profile", headers=_auth(ids["ga"])).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_dept_lead_reads_classes_of_its_grades_only():
    client, ids = _setup()
    try:
        h = _auth(ids["lead"])
        assert client.get(f"/classrooms/{ids['g4']}/students", headers=h).status_code == 200
        assert client.get(f"/classrooms/{ids['g4']}/gaps", headers=h).status_code == 200
        assert client.get(f"/students/{ids['st4']}/profile", headers=h).status_code == 200
        # autre niveau de la même école → 403 ; même niveau, autre école → 403
        assert client.get(f"/classrooms/{ids['g5']}/students", headers=h).status_code == 403
        assert client.get(f"/students/{ids['st5']}/profile", headers=h).status_code == 403
        assert client.get(f"/classrooms/{ids['g4_s3']}/students", headers=h).status_code == 403
        # pas de vue école (direction)
        assert client.get(f"/schools/{ids['s1']}/overview", headers=h).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_classroom_grade_is_set_by_school_admin_only():
    client, ids = _setup()
    try:
        url = f"/classrooms/{ids['g5']}/grade"
        for who in ("teacher", "lead", "ga"):
            assert client.patch(url, json={"grade": 4}, headers=_auth(ids[who])).status_code == 403
        assert client.patch(url, json={"grade": 42}, headers=_auth(ids["ped"])).status_code == 400
        r = client.patch(url, json={"grade": 4}, headers=_auth(ids["ped"]))
        assert r.status_code == 200 and r.json()["grade"] == 4
        # la classe 5A reniveauée en 4 entre dans la portée du dept_lead (contexte par requête)
        assert client.get(f"/classrooms/{ids['g5']}/students", headers=_auth(ids["lead"])).status_code == 200
        # niveau effacé → la classe sort de toute portée dept_lead
        assert client.patch(url, json={"grade": None}, headers=_auth(ids["ped"])).json()["grade"] is None
        assert client.get(f"/classrooms/{ids['g5']}/students", headers=_auth(ids["lead"])).status_code == 403
        # admin d'une autre école → 403
        assert client.patch(f"/classrooms/{ids['g4_s3']}/grade", json={"grade": 4},
                            headers=_auth(ids["ped"])).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_me_exposes_group_and_department_scopes():
    client, ids = _setup()
    try:
        me = client.get("/me", headers=_auth(ids["ga"])).json()
        assert me["roles"] == ["group_admin"]
        assert {sc["id"] for sc in me["schools"]} == {str(ids["s1"]), str(ids["s2"])}
        assert me["classrooms"] == []                 # l'école oui, ses classes non

        me = client.get("/me", headers=_auth(ids["lead"])).json()
        assert me["roles"] == ["dept_lead"]
        assert [c["id"] for c in me["classrooms"]] == [str(ids["g4"])]
        assert me["classrooms"][0]["grade"] == 4
        assert [sc["id"] for sc in me["schools"]] == [str(ids["s1"])]
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests OK")
