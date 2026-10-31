"""Tests adapter OneRoster REST — mapping JSON → snapshot + passage dans le moteur réel.

Aucun réseau : transport factice servant des collections OneRoster en mémoire (pagination
incluse). Couvre v1.1 (`role`) et v1.2 (`roles[]`), le filtrage des statuts et le branchement
sur le moteur de sync idempotent existant.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import make_engine
from src.models.base import Base, Role
from src.models import competency as _c, item as _i, measurement as _m, session as _se, org as _o  # noqa: F401,E501
from src.models.measurement import School, Student
from src.models.org import AppUser, Classroom, Membership, Organization, StudentClassroom
from src.rostering.oneroster import OneRosterAdapter
from src.rostering.sync import sync_directory


def _transport(collections: dict):
    """Transport factice paginé : `collections` = {"orgs": [...], "users": [...], ...}."""
    def _get(resource, params):
        rows = collections.get(resource, [])
        off = params.get("offset", 0)
        lim = params.get("limit", 100)
        return {resource: rows[off:off + lim]}
    return _get


def _v11_collections():
    return {
        "orgs": [
            {"sourcedId": "dist-1", "status": "active", "type": "district", "name": "District"},
            {"sourcedId": "sch-1", "status": "active", "type": "school", "name": "École A",
             "parent": {"sourcedId": "dist-1"}},
        ],
        "users": [
            {"sourcedId": "u-stud", "status": "active", "role": "student",
             "givenName": "Sara", "familyName": "K", "email": "sara@sch.edu",
             "orgs": [{"sourcedId": "sch-1"}]},
            {"sourcedId": "u-teach", "status": "active", "role": "teacher",
             "givenName": "Omar", "familyName": "B", "email": "omar@sch.edu",
             "orgs": [{"sourcedId": "sch-1"}]},
            {"sourcedId": "u-guard", "status": "active", "role": "parent",
             "givenName": "P", "familyName": "P", "email": "parent@x.io",
             "orgs": [{"sourcedId": "sch-1"}]},
            {"sourcedId": "u-old", "status": "tobedeleted", "role": "student",
             "givenName": "Z", "familyName": "Z", "email": "z@sch.edu",
             "orgs": [{"sourcedId": "sch-1"}]},
        ],
        "classes": [
            {"sourcedId": "cls-1", "status": "active", "title": "Maths 4A",
             "school": {"sourcedId": "sch-1"}},
        ],
        "enrollments": [
            {"sourcedId": "e1", "status": "active", "role": "student",
             "user": {"sourcedId": "u-stud"}, "class": {"sourcedId": "cls-1"}},
            {"sourcedId": "e2", "status": "active", "role": "teacher",
             "user": {"sourcedId": "u-teach"}, "class": {"sourcedId": "cls-1"}},
        ],
    }


def test_snapshot_maps_orgs_users_classes_enrollments():
    snap = OneRosterAdapter(_transport(_v11_collections()), version="v1p1").snapshot()
    # 1 école (le district n'est pas une école), les tuteurs/tobedeleted exclus
    assert [o.external_id for o in snap.org_units] == ["sch-1"]
    refs = {u.external_id: u for u in snap.users}
    assert set(refs) == {"u-stud", "u-teach"}            # parent + tobedeleted exclus
    assert refs["u-stud"].role == Role.STUDENT and refs["u-teach"].role == Role.TEACHER
    assert refs["u-stud"].org_unit_external_id == "sch-1"
    assert [g.external_id for g in snap.groups] == ["cls-1"]
    assert len(snap.memberships) == 2
    assert snap.guardians is None                         # OneRoster ne porte pas les tuteurs ici


def test_v12_roles_array_primary():
    cols = _v11_collections()
    cols["users"] = [
        {"sourcedId": "u-a", "status": "active", "givenName": "A", "familyName": "A",
         "email": "a@sch.edu", "orgs": [{"sourcedId": "sch-1"}],
         "roles": [{"roleType": "secondary", "role": "aide"},
                   {"roleType": "primary", "role": "teacher"}]},
    ]
    snap = OneRosterAdapter(_transport(cols), version="v1p2").snapshot()
    assert snap.users[0].role == Role.TEACHER     # le rôle `primary` l'emporte


def test_pagination_walks_all_pages():
    cols = {"orgs": [{"sourcedId": "sch-1", "status": "active", "type": "school", "name": "A"}],
            "users": [
                {"sourcedId": f"u{i}", "status": "active", "role": "student",
                 "givenName": "x", "familyName": "y", "email": f"u{i}@s.edu",
                 "orgs": [{"sourcedId": "sch-1"}]} for i in range(250)
            ], "classes": [], "enrollments": []}
    snap = OneRosterAdapter(_transport(cols), version="v1p1", page_size=100).snapshot()
    assert len(snap.users) == 250


def _mem_org():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    engine = make_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    s = Session(bind=engine)
    org = Organization(name="District", domain="sch.edu"); s.add(org); s.flush()
    return s, org


def test_engine_provisions_from_oneroster_snapshot():
    s, org = _mem_org()
    snap = OneRosterAdapter(_transport(_v11_collections()), version="v1p1").snapshot()
    run = sync_directory(s, org, snap)
    s.commit()
    assert run.status == "ok"
    # école, classe, élève, prof créés ; inscriptions M:N posées
    assert s.execute(select(School).where(School.external_ref == "sch-1")).scalar_one() is not None
    stud = s.execute(select(AppUser).where(AppUser.email == "sara@sch.edu")).scalar_one()
    assert stud.external_ref == "u-stud"
    roles = set(s.execute(select(Membership.role).where(Membership.user_id == stud.id)).scalars())
    assert roles == {Role.STUDENT}
    st = s.execute(select(Student).where(Student.external_ref == "u-stud")).scalar_one()
    enr = s.execute(select(StudentClassroom).where(StudentClassroom.student_id == st.id)).scalars().all()
    assert len(enr) == 1


def test_engine_idempotent_second_run_no_change():
    s, org = _mem_org()
    snap = OneRosterAdapter(_transport(_v11_collections()), version="v1p1").snapshot()
    sync_directory(s, org, snap); s.commit()
    run2 = sync_directory(s, org, snap); s.commit()
    assert run2.created_count == 0 and run2.updated_count == 0 and run2.deactivated_count == 0


# ---------- Refonte A1 : niveau de la classe (OneRoster `grades` → Classroom.grade) ----------

def test_grade_from_codes_ceds():
    from src.rostering.oneroster import grade_from_codes
    assert grade_from_codes(["04"]) == 4
    assert grade_from_codes(["4"]) == 4
    assert grade_from_codes("KG") == 0 and grade_from_codes(["K"]) == 0
    assert grade_from_codes(["13"]) == 13
    # multi-niveaux, code non numérique, vide, absent → on n'invente pas
    assert grade_from_codes(["04", "05"]) is None
    assert grade_from_codes(["PK"]) is None and grade_from_codes(["UG"]) is None
    assert grade_from_codes([]) is None and grade_from_codes(None) is None
    assert grade_from_codes(["99"]) is None


def test_snapshot_and_sync_carry_class_grade():
    cols = _v11_collections()
    cols["classes"][0]["grades"] = ["04"]
    cols["classes"].append({"sourcedId": "cls-2", "status": "active", "title": "Club",
                            "school": {"sourcedId": "sch-1"}})          # sans `grades`
    snap = OneRosterAdapter(_transport(cols), version="v1p1").snapshot()
    by_ref = {g.external_id: g for g in snap.groups}
    assert by_ref["cls-1"].grade == 4 and by_ref["cls-2"].grade is None

    s, org = _mem_org()
    sync_directory(s, org, snap); s.commit()
    cls1 = s.execute(select(Classroom).where(Classroom.external_ref == "cls-1")).scalar_one()
    cls2 = s.execute(select(Classroom).where(Classroom.external_ref == "cls-2")).scalar_one()
    assert cls1.grade == 4 and cls2.grade is None

    # la source change le niveau → suivi (et compté comme mise à jour)
    cols["classes"][0]["grades"] = ["05"]
    run = sync_directory(s, org, OneRosterAdapter(_transport(cols), version="v1p1").snapshot())
    s.commit()
    assert run.updated_count == 1
    assert s.get(Classroom, cls1.id).grade == 5


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
