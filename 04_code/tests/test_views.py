"""Tests T5.4 (vue enseignant) + T5.5 (vue admin) + isolation RBAC."""
import json
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
from src.models.base import Base, CompetencyStatus, EdgeType, Role, Subject, WeightSource
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.measurement import School, Student, StudentCompetencyAbility
from src.models.org import AppUser, Classroom, Membership, TeacherClassroom
from src.rbac.auth import make_token


def _comp(code):
    return Competency(code=code, label_en=code, label_ar="x", subject=Subject.MATH, grade=4,
                      difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)


def _ability(student_id, comp_id, school_id, elo):
    return StudentCompetencyAbility(student_id=student_id, competency_id=comp_id, school_id=school_id,
                                    ability_elo=elo, n_direct=5, confidence=0.5)


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    s = Session(bind=engine)
    sa_, sb = School(name="A"), School(name="B"); s.add_all([sa_, sb]); s.flush()
    c1 = Classroom(school_id=sa_.id, name="4A"); c2 = Classroom(school_id=sb.id, name="4B")
    s.add_all([c1, c2]); s.flush()
    # chaîne A(root) <- B <- C ; D indépendant
    A, B, C, D = _comp("M.A"), _comp("M.B"), _comp("M.C"), _comp("M.D")
    s.add_all([A, B, C, D]); s.flush()
    s.add(CompetencyPrerequisite(source_id=B.id, target_id=C.id, edge_type=EdgeType.HARD,
                                 correlation_strength=0.8, weight_source=WeightSource.EXPERT))
    s.add(CompetencyPrerequisite(source_id=A.id, target_id=B.id, edge_type=EdgeType.HARD,
                                 correlation_strength=0.8, weight_source=WeightSource.EXPERT))
    # 3 élèves classe 1 (école A) : lacune rootant sur B ; 1 d'entre eux a aussi lacune D
    students = []
    for i in range(3):
        st = Student(school_id=sa_.id, classroom_id=c1.id); s.add(st); s.flush(); students.append(st)
        s.add(_ability(st.id, A.id, sa_.id, 1800))   # racine maîtrisée
        s.add(_ability(st.id, B.id, sa_.id, 1200))   # lacune
        s.add(_ability(st.id, C.id, sa_.id, 1200))   # lacune (root → B)
    s.add(_ability(students[0].id, D.id, sa_.id, 1200))  # lacune D pour 1 seul élève

    # enseignants : t1 → classe 1 (école A) ; t2 → classe 2 (école B)
    t1 = AppUser(email="t1@x.io"); t2 = AppUser(email="t2@x.io"); adminA = AppUser(email="admin@a.io")
    s.add_all([t1, t2, adminA]); s.flush()
    s.add_all([
        Membership(user_id=t1.id, role=Role.TEACHER, school_id=sa_.id),
        TeacherClassroom(user_id=t1.id, classroom_id=c1.id),
        Membership(user_id=t2.id, role=Role.TEACHER, school_id=sb.id),
        TeacherClassroom(user_id=t2.id, classroom_id=c2.id),
        Membership(user_id=adminA.id, role=Role.PED_ADMIN, school_id=sa_.id),
    ])
    s.commit()
    ids = dict(schoolA=sa_.id, schoolB=sb.id, c1=c1.id, c2=c2.id,
               t1=t1.id, t2=t2.id, adminA=adminA.id, rootB="M.B")
    app.dependency_overrides[get_db] = lambda: s
    return TestClient(app), ids


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def test_t54_ac1_teacher_only_own_class():
    client, ids = _setup()
    assert client.get(f"/classrooms/{ids['c1']}/gaps", headers=_auth(ids["t1"])).status_code == 200
    # enseignant t1 demande la classe de t2 (autre école) → 403
    assert client.get(f"/classrooms/{ids['c2']}/gaps", headers=_auth(ids["t1"])).status_code == 403
    app.dependency_overrides.clear()


def test_t54_ac2_gaps_sorted_by_frequency_ac3_have_diagnosis():
    client, ids = _setup()
    gaps = client.get(f"/classrooms/{ids['c1']}/gaps", headers=_auth(ids["t1"])).json()["gaps"]
    assert gaps[0]["root_cause"] == ids["rootB"]            # cause racine la plus fréquente d'abord
    counts = [g["student_count"] for g in gaps]
    assert counts == sorted(counts, reverse=True)           # tri par fréquence
    assert all("diagnosis" in g and g["diagnosis"] for g in gaps)  # AC3 diagnostic présent
    app.dependency_overrides.clear()


def test_t55_ac1_admin_tenant_isolation():
    client, ids = _setup()
    assert client.get(f"/schools/{ids['schoolA']}/overview", headers=_auth(ids["adminA"])).status_code == 200
    assert client.get(f"/schools/{ids['schoolB']}/overview", headers=_auth(ids["adminA"])).status_code == 403
    app.dependency_overrides.clear()


def test_t55_ac2_no_student_pii_ac3_exportable():
    client, ids = _setup()
    data = client.get(f"/schools/{ids['schoolA']}/overview", headers=_auth(ids["adminA"])).json()
    assert "student_id" not in json.dumps(data)             # aucune PII élève
    assert {"competencies", "classes", "n_students"} <= set(data)  # structure exportable
    assert any(c["mastery_rate"] is not None for c in data["competencies"])
    app.dependency_overrides.clear()


def test_admin_role_not_applied_to_school_of_teacher_membership():
    """PED_ADMIN de A + TEACHER de B (classe c2) : aucune portée admin sur l'école B."""
    client, ids = _setup()
    s = app.dependency_overrides[get_db]()
    c3 = Classroom(school_id=ids["schoolB"], name="4C"); s.add(c3); s.flush()
    st = Student(school_id=ids["schoolB"], classroom_id=c3.id); s.add(st)
    s.add_all([Membership(user_id=ids["adminA"], role=Role.TEACHER, school_id=ids["schoolB"]),
               TeacherClassroom(user_id=ids["adminA"], classroom_id=ids["c2"])])
    s.commit()
    h = _auth(ids["adminA"])
    assert client.get(f"/schools/{ids['schoolB']}/overview", headers=h).status_code == 403
    assert client.get(f"/classrooms/{c3.id}/students", headers=h).status_code == 403
    assert client.get(f"/students/{st.id}/profile", headers=h).status_code == 403
    assert client.get(f"/classrooms/{ids['c2']}/students", headers=h).status_code == 200
    me = client.get("/me", headers=h).json()
    listed = {c["id"] for c in me["classrooms"]}
    assert str(c3.id) not in listed and {str(ids["c1"]), str(ids["c2"])} <= listed
    assert me["schools"][0]["id"] == str(ids["schoolA"])   # le front route l'admin sur schools[0]
    app.dependency_overrides.clear()


def test_no_token_401():
    client, ids = _setup()
    assert client.get(f"/classrooms/{ids['c1']}/gaps").status_code == 401
    app.dependency_overrides.clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
