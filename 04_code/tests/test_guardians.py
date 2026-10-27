"""Tests liaison parent↔enfant par le staff (autorité de confiance) + multi-enfants (Phase H bis).

Principe vérifié : seul un membre du staff AYANT accès à l'élève peut créer/retirer un lien ;
le parent ne s'auto-déclare jamais. Un parent peut avoir plusieurs enfants.
"""
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from src.db import make_engine
from src.models.base import Base, Role, utcnow
from src.models import competency as _c, item as _i, measurement as _m, session as _se, org as _o  # noqa: F401,E501
from src.models.measurement import School, Student
from src.models.org import (
    AppUser, Classroom, Membership, Organization, ParentStudent, TeacherClassroom,
)
from src.rbac.auth import make_token
from src.notify.email import FakeEmailSender
import src.api.app as appmod

FAKE = FakeEmailSender()


def _setup():
    """Org + école + classe + 2 élèves (alice, bob) + un PED_ADMIN (autorité) + un prof d'une AUTRE classe."""
    FAKE.sent.clear()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    engine = make_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    ids = {}
    with Session(bind=engine) as s:
        org = Organization(name="School", domain="school.edu"); s.add(org); s.flush()
        school = School(name="S1", organization_id=org.id); s.add(school); s.flush()
        cls = Classroom(school_id=school.id, name="4A"); s.add(cls); s.flush()
        other = Classroom(school_id=school.id, name="4B"); s.add(other); s.flush()

        def _student(email):
            u = AppUser(email=email); s.add(u); s.flush()
            st = Student(school_id=school.id, classroom_id=cls.id, user_id=u.id); s.add(st); s.flush()
            return st
        alice, bob = _student("alice@school.edu"), _student("bob@school.edu")

        admin = AppUser(email="ped@school.edu"); s.add(admin); s.flush()
        s.add(Membership(user_id=admin.id, role=Role.PED_ADMIN, school_id=school.id))
        outsider = AppUser(email="other@school.edu"); s.add(outsider); s.flush()
        s.add(Membership(user_id=outsider.id, role=Role.TEACHER, school_id=school.id))
        s.add(TeacherClassroom(user_id=outsider.id, classroom_id=other.id))  # prof de 4B seulement
        s.commit()
        ids = {"alice": str(alice.id), "bob": str(bob.id),
               "admin": make_token(str(admin.id)), "outsider": make_token(str(outsider.id))}

    def _get_db():
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    appmod.app.dependency_overrides[appmod.get_db] = _get_db
    appmod.app.dependency_overrides[appmod.get_email_sender] = lambda: FAKE
    return TestClient(appmod.app), engine, ids


def _clear():
    appmod.app.dependency_overrides.clear()


def test_staff_links_parent_and_invites():
    client, engine, ids = _setup()
    h = {"Authorization": f"Bearer {ids['admin']}"}
    r = client.post(f"/students/{ids['alice']}/guardians",
                    json={"email": "Dad@home.com"}, headers=h)
    assert r.status_code == 200, r.text
    assert FAKE.sent and FAKE.sent[0]["to"] == "dad@home.com"      # invitation envoyée
    g = client.get(f"/students/{ids['alice']}/guardians", headers=h).json()["guardians"]
    assert g[0]["email"] == "dad@home.com" and g[0]["source"] == "staff"
    _clear()


def test_unrelated_teacher_cannot_link():
    client, _, ids = _setup()
    h = {"Authorization": f"Bearer {ids['outsider']}"}  # prof de 4B, pas d'Alice (4A)
    r = client.post(f"/students/{ids['alice']}/guardians", json={"email": "x@home.com"}, headers=h)
    assert r.status_code == 403
    _clear()


def _non_staff_tokens(engine, alice_id):
    """Session élève d'Alice, parent lié d'Alice, et prof de 4B qui est AUSSI parent d'Alice."""
    with Session(bind=engine) as s:
        alice = s.get(Student, uuid.UUID(alice_id))
        s.add(Membership(user_id=alice.user_id, role=Role.STUDENT))
        dad = AppUser(email="dad@home.com"); s.add(dad); s.flush()
        s.add(Membership(user_id=dad.id, role=Role.PARENT))
        s.add(ParentStudent(user_id=dad.id, student_id=alice.id, source="roster"))
        teacher = s.execute(select(AppUser).where(AppUser.email == "other@school.edu")).scalar_one()
        s.add(ParentStudent(user_id=teacher.id, student_id=alice.id, source="roster"))
        s.commit()
        return str(dad.id), {"student": make_token(str(alice.user_id)),
                             "parent": make_token(str(dad.id)),
                             "teacher_parent": make_token(str(teacher.id))}


def test_parent_and_student_cannot_manage_guardians():
    # Le parent ne s'auto-déclare jamais ; l'élève ne gère pas ses tuteurs : 403 sans écriture ni email.
    client, engine, ids = _setup()
    dad_id, tokens = _non_staff_tokens(engine, ids["alice"])
    for who, tok in tokens.items():
        h = {"Authorization": f"Bearer {tok}"}
        assert client.get(f"/students/{ids['alice']}/guardians", headers=h).status_code == 403, who
        r = client.post(f"/students/{ids['alice']}/guardians",
                        json={"email": "evil@home.com"}, headers=h)
        assert r.status_code == 403, who
        r = client.delete(f"/students/{ids['alice']}/guardians/{dad_id}", headers=h)
        assert r.status_code == 403, who
    assert FAKE.sent == []
    with Session(bind=engine) as s:
        assert s.execute(select(AppUser).where(AppUser.email == "evil@home.com")).first() is None
        assert s.get(ParentStudent, (uuid.UUID(dad_id), uuid.UUID(ids["alice"]))) is not None
    _clear()


def test_staff_unlink_guardian():
    client, engine, ids = _setup()
    h = {"Authorization": f"Bearer {ids['admin']}"}
    client.post(f"/students/{ids['alice']}/guardians", json={"email": "dad@home.com",
                                                             "send_invite": False}, headers=h)
    with Session(bind=engine) as s:
        dad = s.execute(select(AppUser).where(AppUser.email == "dad@home.com")).scalar_one()
    r = client.delete(f"/students/{ids['alice']}/guardians/{dad.id}", headers=h)
    assert r.status_code == 200
    assert client.get(f"/students/{ids['alice']}/guardians", headers=h).json()["guardians"] == []
    _clear()


def test_soft_deleted_guardian_email_hidden():
    # Revue 2026-07-08 : la jointure AppUser × ParentStudent exposait l'email d'un parent
    # SOFT-DELETED au staff (le lien, lui, reste en base — réactivable par add_guardian).
    client, engine, ids = _setup()
    h = {"Authorization": f"Bearer {ids['admin']}"}
    client.post(f"/students/{ids['alice']}/guardians",
                json={"email": "dad@home.com", "send_invite": False}, headers=h)
    client.post(f"/students/{ids['alice']}/guardians",
                json={"email": "mom@home.com", "send_invite": False}, headers=h)
    with Session(bind=engine) as s:
        dad = s.execute(select(AppUser).where(AppUser.email == "dad@home.com")).scalar_one()
        dad.deleted_at, dad.is_active = utcnow(), False    # droit à l'oubli du parent
        s.commit()
    g = client.get(f"/students/{ids['alice']}/guardians", headers=h).json()["guardians"]
    assert [x["email"] for x in g] == ["mom@home.com"]     # dad masqué, mom toujours là
    _clear()


def test_parent_sees_all_children():
    client, engine, ids = _setup()
    h = {"Authorization": f"Bearer {ids['admin']}"}
    # même parent rattaché à Alice ET Bob
    client.post(f"/students/{ids['alice']}/guardians", json={"email": "mom@home.com",
                                                             "send_invite": False}, headers=h)
    client.post(f"/students/{ids['bob']}/guardians", json={"email": "mom@home.com",
                                                           "send_invite": False}, headers=h)
    with Session(bind=engine) as s:
        mom = s.execute(select(AppUser).where(AppUser.email == "mom@home.com")).scalar_one()
        mom_token = make_token(str(mom.id))

    r = client.get("/parent/children", headers={"Authorization": f"Bearer {mom_token}"})
    children = r.json()["children"]
    labels = {c["label"] for c in children}
    assert len(children) == 2 and labels == {"alice@school.edu", "bob@school.edu"}
    _clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
