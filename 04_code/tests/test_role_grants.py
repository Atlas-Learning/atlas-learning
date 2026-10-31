"""Refonte A1 (Q13) — attribution des rôles hors roster : dept_lead et group_admin.

Couvre src/rbac/grants.py (service), /admin/roles (API, RBAC), l'interaction avec la sync de
rostering (adoption par email, protection, déprovisioning) et l'ouverture de session SANS SSO
par lien magique (/admin/request-link élargi à ces rôles).
"""
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.api.app as appmod
from src.api.app import app, get_db
from src.models import competency, item, measurement, org, session as _se, audit as _au  # noqa: F401
from src.models.audit import AuditLog
from src.models.base import Base, Role
from src.models.measurement import School
from src.models.org import AppUser, Classroom, DeptLeadScope, Membership, Organization
from src.notify.email import FakeEmailSender
from src.rbac import grants
from src.rbac.auth import make_token
from src.rbac.authz import build_user_context, can_access_classroom
from src.rostering.directory import DirectorySnapshot, DirGroup, DirMembership, DirOrgUnit, DirUser
from src.rostering.sync import sync_directory


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _tenants(s):
    oa, ob = Organization(name="Groupe A", domain="a.edu"), Organization(name="Groupe B", domain="b.edu")
    s.add_all([oa, ob]); s.flush()
    s1 = School(name="A1", organization_id=oa.id); s2 = School(name="A2", organization_id=oa.id)
    s3 = School(name="B1", organization_id=ob.id)
    s.add_all([s1, s2, s3]); s.flush()
    s.add_all([Classroom(school_id=s1.id, name="4A", grade=4), Classroom(school_id=s1.id, name="5A", grade=5)])
    s.commit()
    return oa, ob, s1, s2, s3


# ---------- service ----------

def test_grant_dept_lead_creates_account_membership_and_scope_idempotently():
    s = _session(); oa, ob, s1, s2, s3 = _tenants(s)
    res = grants.grant_role(s, email=" Coord@A1.edu ", role=Role.DEPT_LEAD, school_id=s1.id, grades=[5, 4, 4])
    s.commit()
    assert res.created_user and res.created_membership
    assert res.grant.email == "coord@a1.edu" and res.grant.grades == [4, 5]
    assert res.grant.organization_id == oa.id and res.grant.school_name == "A1"
    user = s.execute(select(AppUser).where(AppUser.email == "coord@a1.edu")).scalar_one()
    assert user.external_ref is None                     # compte manuel : protégé du roster
    ctx = build_user_context(s, user.id)
    assert ctx.dept_scopes == {(s1.id, 4), (s1.id, 5)}

    # ré-attribution avec une autre liste : la portée est REMPLACÉE, rien n'est dupliqué
    res2 = grants.grant_role(s, email="coord@a1.edu", role=Role.DEPT_LEAD, school_id=s1.id, grades=[4])
    s.commit()
    assert not res2.created_user and not res2.created_membership
    assert res2.grant.membership_id == res.grant.membership_id
    assert s.execute(select(Membership).where(Membership.user_id == user.id)).scalars().all().__len__() == 1
    assert sorted(s.execute(select(DeptLeadScope.grade)).scalars()) == [4]
    assert build_user_context(s, user.id).dept_scopes == {(s1.id, 4)}
    assert s.execute(select(AuditLog).where(AuditLog.action == "role.grant")).scalars().all().__len__() == 2


def test_grant_group_admin_and_validation_errors():
    s = _session(); oa, ob, s1, s2, s3 = _tenants(s)
    res = grants.grant_role(s, email="dir@a.edu", role=Role.GROUP_ADMIN, organization_id=oa.id)
    s.commit()
    assert res.grant.role == Role.GROUP_ADMIN and res.grant.school_id is None
    ctx = build_user_context(s, res.grant.user_id)
    assert ctx.group_school_ids == {s1.id, s2.id}

    with pytest.raises(grants.GrantError):     # dept_lead sans école
        grants.grant_role(s, email="x@a.edu", role=Role.DEPT_LEAD, grades=[4])
    with pytest.raises(grants.GrantError):     # dept_lead sans niveau
        grants.grant_role(s, email="x@a.edu", role=Role.DEPT_LEAD, school_id=s1.id, grades=[])
    with pytest.raises(grants.GrantError):     # niveau hors bornes
        grants.grant_role(s, email="x@a.edu", role=Role.DEPT_LEAD, school_id=s1.id, grades=[14])
    with pytest.raises(grants.GrantError):     # école hors de l'organisation annoncée
        grants.grant_role(s, email="x@a.edu", role=Role.DEPT_LEAD, school_id=s3.id, grades=[4],
                          organization_id=oa.id)
    with pytest.raises(grants.GrantError):     # group_admin avec une école
        grants.grant_role(s, email="x@a.edu", role=Role.GROUP_ADMIN, organization_id=oa.id, school_id=s1.id)
    with pytest.raises(grants.GrantError):     # rôle non attribuable ici
        grants.grant_role(s, email="x@a.edu", role=Role.TEACHER, school_id=s1.id)
    with pytest.raises(grants.GrantError):     # email invalide
        grants.grant_role(s, email="pas-un-email", role=Role.GROUP_ADMIN, organization_id=oa.id)
    assert s.execute(select(AppUser).where(AppUser.email == "x@a.edu")).scalar_one_or_none() is None


def test_revoke_and_list():
    s = _session(); oa, ob, s1, s2, s3 = _tenants(s)
    g1 = grants.grant_role(s, email="coord@a1.edu", role=Role.DEPT_LEAD, school_id=s1.id, grades=[4]).grant
    g2 = grants.grant_role(s, email="dir@a.edu", role=Role.GROUP_ADMIN, organization_id=oa.id).grant
    grants.grant_role(s, email="coord@b1.edu", role=Role.DEPT_LEAD, school_id=s3.id, grades=[4])
    s.commit()
    listed = grants.list_grants(s, organization_id=oa.id)
    assert {(g.email, g.role) for g in listed} == {("coord@a1.edu", Role.DEPT_LEAD), ("dir@a.edu", Role.GROUP_ADMIN)}
    assert grants.organization_of_grant(s, g1.membership_id) == oa.id

    revoked = grants.revoke_role(s, membership_id=g1.membership_id); s.commit()
    assert revoked.grades == [4]
    assert s.execute(select(DeptLeadScope).where(
        DeptLeadScope.membership_id == g1.membership_id)).scalars().all() == []   # cascade
    assert len(s.execute(select(DeptLeadScope)).scalars().all()) == 1           # coord@b1 intact
    assert s.execute(select(AppUser).where(AppUser.email == "coord@a1.edu")).scalar_one() is not None  # compte conservé
    assert [g.email for g in grants.list_grants(s, organization_id=oa.id)] == ["dir@a.edu"]
    with pytest.raises(grants.GrantError):
        grants.revoke_role(s, membership_id=g1.membership_id)
    assert g2.membership_id is not None


def test_manual_account_is_reactivated_but_roster_owned_is_not():
    s = _session(); oa, ob, s1, s2, s3 = _tenants(s)
    manual = AppUser(email="old@a.edu", is_active=False); rostered = AppUser(email="gone@a.edu", external_ref="g-1", is_active=False)
    s.add_all([manual, rostered]); s.commit()
    res = grants.grant_role(s, email="old@a.edu", role=Role.GROUP_ADMIN, organization_id=oa.id); s.commit()
    assert not res.created_user and s.get(AppUser, manual.id).is_active is True
    with pytest.raises(grants.GrantError):
        grants.grant_role(s, email="gone@a.edu", role=Role.GROUP_ADMIN, organization_id=oa.id)


# ---------- interaction avec le rostering (SSO) ----------

def test_grant_survives_roster_sync_and_follows_directory_deprovisioning():
    s = _session()
    org = Organization(name="Demo", domain="school.edu"); s.add(org); s.commit()
    ou = DirOrgUnit(external_id="ou_elem", name="Elementary")
    users = [DirUser("u_carol", "carol@school.edu", "Carol", "ou_elem", role=Role.TEACHER),
             DirUser("u_alice", "alice@school.edu", "Alice", "ou_elem", role=Role.STUDENT)]
    snap = DirectorySnapshot([ou], users, [DirGroup("g_4a", "4A", grade=4)],
                             [DirMembership("g_4a", "u_carol"), DirMembership("g_4a", "u_alice")])
    sync_directory(s, org, snap); s.commit()
    school = s.execute(select(School).where(School.external_ref == "ou_elem")).scalar_one()
    cls = s.execute(select(Classroom).where(Classroom.external_ref == "g_4a")).scalar_one()

    # 1) attribution AVANT que le compte existe : créé par email, puis adopté par la sync
    grants.grant_role(s, email="dan@school.edu", role=Role.DEPT_LEAD, school_id=school.id, grades=[4]); s.commit()
    dan = s.execute(select(AppUser).where(AppUser.email == "dan@school.edu")).scalar_one()
    assert dan.external_ref is None
    snap2 = DirectorySnapshot([ou], users + [DirUser("u_dan", "dan@school.edu", "Dan", "ou_elem", role=Role.TEACHER)],
                              snap.groups, snap.memberships + [DirMembership("g_4a", "u_dan")])
    sync_directory(s, org, snap2); s.commit()
    dan = s.get(AppUser, dan.id)
    assert dan.external_ref == "u_dan"                                  # adopté, pas dupliqué
    roles = set(s.execute(select(Membership.role).where(Membership.user_id == dan.id)).scalars())
    assert roles == {Role.TEACHER, Role.DEPT_LEAD}                     # la sync n'efface pas l'attribution
    ctx = build_user_context(s, dan.id)
    assert ctx.dept_scopes == {(school.id, 4)} and can_access_classroom(ctx, cls.id, school.id)

    # 2) attribution à une enseignante déjà rosterisée : rien ne change côté identité
    grants.grant_role(s, email="carol@school.edu", role=Role.DEPT_LEAD, school_id=school.id, grades=[4]); s.commit()
    carol = s.execute(select(AppUser).where(AppUser.email == "carol@school.edu")).scalar_one()
    assert carol.external_ref == "u_carol"

    # 3) un compte manuel jamais vu par l'annuaire n'est PAS désactivé par la sync
    grants.grant_role(s, email="dir@school.edu", role=Role.GROUP_ADMIN, organization_id=org.id); s.commit()
    sync_directory(s, org, snap2, force=True); s.commit()
    assert s.execute(select(AppUser).where(AppUser.email == "dir@school.edu")).scalar_one().is_active

    # 4) Dan quitte l'annuaire : désactivé comme tout compte rosterisé ; l'attribution ne le ressuscite pas
    sync_directory(s, org, snap, force=True); s.commit()
    assert s.get(AppUser, dan.id).is_active is False
    with pytest.raises(grants.GrantError):
        grants.grant_role(s, email="dan@school.edu", role=Role.DEPT_LEAD, school_id=school.id, grades=[4])


# ---------- API /admin/roles ----------

def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _api():
    s = _session(); oa, ob, s1, s2, s3 = _tenants(s)
    it_a = AppUser(email="it@a.edu"); it_b = AppUser(email="it@b.edu"); ped = AppUser(email="ped@a1.edu")
    teacher = AppUser(email="t@a1.edu"); su = AppUser(email="ops@atlas.io")
    s.add_all([it_a, it_b, ped, teacher, su]); s.flush()
    s.add_all([
        Membership(user_id=it_a.id, role=Role.IT_ADMIN, organization_id=oa.id),
        Membership(user_id=it_b.id, role=Role.IT_ADMIN, organization_id=ob.id, school_id=s3.id),
        Membership(user_id=ped.id, role=Role.PED_ADMIN, school_id=s1.id),
        Membership(user_id=teacher.id, role=Role.TEACHER, school_id=s1.id),
        Membership(user_id=su.id, role=Role.SUPER_ADMIN),
    ])
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    ids = dict(oa=oa.id, ob=ob.id, s1=s1.id, s3=s3.id, it_a=it_a.id, it_b=it_b.id, ped=ped.id,
               teacher=teacher.id, su=su.id)
    return TestClient(app), ids, s


def test_api_grant_requires_it_admin_of_the_organization():
    client, ids, s = _api()
    try:
        body = {"email": "coord@a1.edu", "role": "dept_lead", "school_id": str(ids["s1"]), "grades": [4]}
        for who in ("teacher", "it_b"):                  # enseignant, IT d'une AUTRE org
            assert client.post("/admin/roles", json=body, headers=_auth(ids[who])).status_code == 403
        # ped_admin : coordinateur de SON école oui, d'une autre école non, group_admin jamais
        other = {**body, "email": "coord@b1.edu", "school_id": str(ids["s3"])}
        assert client.post("/admin/roles", json=other, headers=_auth(ids["ped"])).status_code == 403
        assert client.post("/admin/roles", json={"email": "dir@a.edu", "role": "group_admin",
                                                 "organization_id": str(ids["oa"])},
                           headers=_auth(ids["ped"])).status_code == 403
        r_ped = client.post("/admin/roles", json={**body, "email": "coord2@a1.edu"}, headers=_auth(ids["ped"]))
        assert r_ped.status_code == 200 and r_ped.json()["created_user"]
        r = client.post("/admin/roles", json=body, headers=_auth(ids["it_a"]))
        assert r.status_code == 200
        assert r.json()["role"] == "dept_lead" and r.json()["grades"] == [4] and r.json()["created_user"]
        # IT de A sur l'org B → 403 ; super admin → 200
        gb = {"email": "dir@b.edu", "role": "group_admin", "organization_id": str(ids["ob"])}
        assert client.post("/admin/roles", json=gb, headers=_auth(ids["it_a"])).status_code == 403
        assert client.post("/admin/roles", json=gb, headers=_auth(ids["su"])).status_code == 200
        # erreurs : rôle non attribuable, portée incohérente
        assert client.post("/admin/roles", json={"email": "x@a.edu", "role": "teacher", "school_id": str(ids["s1"])},
                           headers=_auth(ids["it_a"])).status_code == 400
        assert client.post("/admin/roles", json={"email": "x@a.edu", "role": "dept_lead", "school_id": str(ids["s1"])},
                           headers=_auth(ids["it_a"])).status_code == 400
        assert client.post("/admin/roles", json={"email": "x@a.edu", "role": "group_admin"},
                           headers=_auth(ids["it_a"])).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_api_list_and_revoke_scoped_to_organization():
    client, ids, s = _api()
    try:
        r = client.post("/admin/roles", json={"email": "coord@a1.edu", "role": "dept_lead",
                                              "school_id": str(ids["s1"]), "grades": [4, 5]},
                        headers=_auth(ids["it_a"]))
        mid = r.json()["membership_id"]
        lst = client.get(f"/admin/roles?organization_id={ids['oa']}", headers=_auth(ids["it_a"]))
        assert lst.status_code == 200 and [g["email"] for g in lst.json()["grants"]] == ["coord@a1.edu"]
        assert client.get(f"/admin/roles?organization_id={ids['oa']}", headers=_auth(ids["it_b"])).status_code == 403
        # ped_admin : pas la vue organisation, mais les dept_lead de SON école
        assert client.get(f"/admin/roles?organization_id={ids['oa']}", headers=_auth(ids["ped"])).status_code == 403
        by_school = client.get(f"/admin/roles?school_id={ids['s1']}", headers=_auth(ids["ped"]))
        assert by_school.status_code == 200 and [g["email"] for g in by_school.json()["grants"]] == ["coord@a1.edu"]
        assert client.get(f"/admin/roles?school_id={ids['s3']}", headers=_auth(ids["ped"])).status_code == 403
        assert client.get("/admin/roles", headers=_auth(ids["it_a"])).status_code == 400
        # révocation : IT d'une autre org → 403 ; IT de l'org → 200 ; deuxième fois → 404
        assert client.delete(f"/admin/roles/{mid}", headers=_auth(ids["it_b"])).status_code == 403
        assert client.delete(f"/admin/roles/{mid}", headers=_auth(ids["teacher"])).status_code == 403
        assert client.delete(f"/admin/roles/{mid}", headers=_auth(ids["ped"])).status_code == 200   # son école
        r = client.post("/admin/roles", json={"email": "coord@a1.edu", "role": "dept_lead",
                                              "school_id": str(ids["s1"]), "grades": [4]}, headers=_auth(ids["it_a"]))
        mid = r.json()["membership_id"]
        assert client.delete(f"/admin/roles/{mid}", headers=_auth(ids["it_a"])).status_code == 200
        assert client.delete(f"/admin/roles/{mid}", headers=_auth(ids["it_a"])).status_code == 404
        assert client.get(f"/admin/roles?organization_id={ids['oa']}", headers=_auth(ids["it_a"])).json()["grants"] == []
    finally:
        app.dependency_overrides.clear()


def test_me_exposes_department_scopes_and_organizations():
    client, ids, s = _api()
    try:
        client.post("/admin/roles", json={"email": "coord@a1.edu", "role": "dept_lead",
                                          "school_id": str(ids["s1"]), "grades": [4]}, headers=_auth(ids["it_a"]))
        client.post("/admin/roles", json={"email": "dir@a.edu", "role": "group_admin",
                                          "organization_id": str(ids["oa"])}, headers=_auth(ids["it_a"]))
        coord = s.execute(select(AppUser).where(AppUser.email == "coord@a1.edu")).scalar_one()
        me = client.get("/me", headers=_auth(coord.id)).json()
        assert me["department_scopes"] == [{"school_id": str(ids["s1"]), "grade": 4}]
        assert [c["name"] for c in me["classrooms"]] == ["4A"] and me["organizations"] == []
        dir_ = s.execute(select(AppUser).where(AppUser.email == "dir@a.edu")).scalar_one()
        me = client.get("/me", headers=_auth(dir_.id)).json()
        assert [o["name"] for o in me["organizations"]] == ["Groupe A"]
        assert len(me["schools"]) == 2 and me["department_scopes"] == []
        me = client.get("/me", headers=_auth(ids["it_a"])).json()
        assert [o["name"] for o in me["organizations"]] == ["Groupe A"]
    finally:
        app.dependency_overrides.clear()


# ---------- sans SSO : lien magique pour dept_lead / group_admin ----------

def test_magic_link_signs_in_dept_lead_without_sso():
    fake = FakeEmailSender()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    from src.db import make_engine
    engine = make_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    with Session(bind=engine) as s:
        oa, ob, s1, s2, s3 = _tenants(s)
        grants.grant_role(s, email="coord@a1.edu", role=Role.DEPT_LEAD, school_id=s1.id, grades=[4])
        t = AppUser(email="t@a1.edu"); s.add(t); s.flush()
        s.add(Membership(user_id=t.id, role=Role.TEACHER, school_id=s1.id))
        s.commit()

    def _get_db():
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()
    appmod.app.dependency_overrides[get_db] = _get_db
    appmod.app.dependency_overrides[appmod.get_email_sender] = lambda: fake
    client = TestClient(appmod.app)
    try:
        # enseignant : réponse constante, aucun email (le lien magique n'est pas pour lui)
        assert client.post("/admin/request-link", json={"email": "t@a1.edu"}).json() == {"ok": True}
        assert not fake.sent
        # dept_lead : email bilingue « staff », puis GET (sans consommer) → POST (consomme) → session
        client.post("/admin/request-link", json={"email": "coord@a1.edu"})
        assert fake.sent and "رابط الدخول" in fake.sent[-1]["subject"]
        tok = re.search(r"/api/admin/login\?token=([^\"\s]+)", fake.sent[-1]["html"]).group(1)
        login = client.get(f"/admin/login?token={tok}", follow_redirects=False)
        assert login.status_code == 302 and "/login/confirm#token=" in login.headers["location"]
        link_token = login.headers["location"].split("/login/confirm#token=")[1]
        confirm = client.post("/admin/login/confirm", json={"token": link_token})
        assert confirm.status_code == 200
        me = client.get("/me", headers={"Authorization": f"Bearer {confirm.json()['token']}"}).json()
        assert me["roles"] == ["dept_lead"] and me["department_scopes"][0]["grade"] == 4
    finally:
        appmod.app.dependency_overrides.clear()
        engine.dispose()
        os.unlink(tmp.name)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests OK")
