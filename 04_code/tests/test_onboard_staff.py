"""Onboarding du staff Atlas global (scripts/onboard_staff.py) : relecteur de contenu et linguiste.

Compte + rôle global, idempotence, lien magique sur le bon flux (admin_login pour le relecteur,
linguist_login pour le linguiste), et connexion effective du relecteur par /admin/login.
"""
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.api.app as appmod
from scripts.onboard_staff import onboard_staff
from src.db import make_engine
from src.models import competency as _c, item as _i, measurement as _m, org as _o, session as _se  # noqa: F401
from src.models.base import Base, Role
from src.models.org import AppUser, Membership
from src.rbac.auth import parse_single_use_token


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def test_reviewer_and_linguist_links_and_idempotence():
    engine = _engine()
    with Session(bind=engine) as s:
        r = onboard_staff(s, "Rev@Atlas.AE", Role.CONTENT_REVIEWER)
        assert r["created"] and r["role_added"] and r["email"] == "rev@atlas.ae"
        assert "/api/admin/login?token=" in r["link"]
        tok = parse_qs(urlparse(r["link"]).query)["token"][0]
        assert parse_single_use_token(tok, purpose="admin_login")[0] == str(r["user_id"])
        r2 = onboard_staff(s, "rev@atlas.ae", Role.CONTENT_REVIEWER, mint_link=False)
        assert not r2["created"] and not r2["role_added"] and r2["link"] is None
        m = s.execute(select(Membership)).scalar_one()
        assert m.role == Role.CONTENT_REVIEWER and m.school_id is None and m.organization_id is None
        l = onboard_staff(s, "ling@atlas.ae", Role.LINGUIST)
        assert "/api/linguist/login?token=" in l["link"]
        with pytest.raises(ValueError):
            onboard_staff(s, "x@atlas.ae", Role.TEACHER)


def test_reviewer_signs_in_with_minted_link():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    engine = make_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    with Session(bind=engine) as s:
        r = onboard_staff(s, "rev@atlas.ae", Role.CONTENT_REVIEWER)
    tok = parse_qs(urlparse(r["link"]).query)["token"][0]

    def _get_db():
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()
    appmod.app.dependency_overrides[appmod.get_db] = _get_db
    client = TestClient(appmod.app)
    try:
        login = client.get(f"/admin/login?token={tok}", follow_redirects=False)
        assert login.status_code == 302 and "/login/confirm#token=" in login.headers["location"]
        link_token = login.headers["location"].split("/login/confirm#token=")[1]
        confirm = client.post("/admin/login/confirm", json={"token": link_token})
        assert confirm.status_code == 200
        me = client.get("/me", headers={"Authorization": f"Bearer {confirm.json()['token']}"}).json()
        assert me["roles"] == ["content_reviewer"]
        assert client.get("/items/flags", headers={"Authorization": f"Bearer {confirm.json()['token']}"}).status_code == 200
    finally:
        appmod.app.dependency_overrides.clear()
        engine.dispose()
        os.unlink(tmp.name)
