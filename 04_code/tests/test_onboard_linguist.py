"""Tests de l'onboarding linguiste (scripts/onboard_linguist.py).

Vérifie la création de compte + rôle global linguist, l'idempotence, le lien magique
minté (parseable, purpose linguist_login, single-use), --no-link, et l'audit.
"""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scripts.onboard_linguist import onboard_linguist
from src.models import competency as _c, item as _i, measurement as _m, org as _o, session as _se  # noqa: F401,E501
from src.models.audit import AuditLog
from src.models.base import Base, Role
from src.models.org import AppUser, Membership
from src.rbac.auth import parse_single_use_token


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def _count(s, model):
    return len(s.execute(select(model)).scalars().all())


def test_creates_account_role_and_link():
    engine = _engine()
    with Session(bind=engine) as s:
        r = onboard_linguist(s, "Ling@Atlas.AE")               # casse mixte → normalisée
    with Session(bind=engine) as s:
        u = s.execute(select(AppUser)).scalar_one()
        assert u.email == "ling@atlas.ae" and r["created"] is True
        m = s.execute(select(Membership)).scalar_one()
        assert m.role == Role.LINGUIST and m.school_id is None and m.organization_id is None
    # le lien minté est parseable, purpose linguist_login, pointe vers le bon user
    assert "/api/linguist/login?token=" in r["link"]
    token = parse_qs(urlparse(r["link"]).query)["token"][0]
    uid = parse_single_use_token(token, purpose="linguist_login")[0]   # (user_id, jti, exp)
    assert str(r["user_id"]) == uid


def test_idempotent_no_duplicate():
    engine = _engine()
    with Session(bind=engine) as s:
        onboard_linguist(s, "ling@atlas.ae")
    with Session(bind=engine) as s:
        r2 = onboard_linguist(s, "ling@atlas.ae")              # 2e passage
        assert r2["created"] is False and r2["role_added"] is False
    with Session(bind=engine) as s:
        assert _count(s, AppUser) == 1 and _count(s, Membership) == 1


def test_reactivates_soft_deleted_account():
    engine = _engine()
    with Session(bind=engine) as s:
        from src.models.base import utcnow
        s.add(AppUser(email="ling@atlas.ae", is_active=False, deleted_at=utcnow()))
        s.commit()
    with Session(bind=engine) as s:
        onboard_linguist(s, "ling@atlas.ae")
    with Session(bind=engine) as s:
        u = s.execute(select(AppUser)).scalar_one()
        assert u.deleted_at is None and u.is_active is True
        assert _count(s, AppUser) == 1                          # pas de doublon


def test_reactivation_does_not_restore_prior_roles():
    engine = _engine()
    with Session(bind=engine) as s:
        from src.models.base import utcnow
        u = AppUser(email="ling@atlas.ae", is_active=False, deleted_at=utcnow())
        s.add(u); s.flush()
        s.add(Membership(user_id=u.id, role=Role.IT_ADMIN))     # rôle d'avant l'offboarding
        s.commit()
    with Session(bind=engine) as s:
        onboard_linguist(s, "ling@atlas.ae")
    with Session(bind=engine) as s:
        assert [m.role for m in s.execute(select(Membership)).scalars()] == [Role.LINGUIST]


def test_no_link_option():
    engine = _engine()
    with Session(bind=engine) as s:
        r = onboard_linguist(s, "ling@atlas.ae", mint_link=False)
    assert r["link"] is None


def test_audit_written():
    engine = _engine()
    with Session(bind=engine) as s:
        onboard_linguist(s, "ling@atlas.ae")
    with Session(bind=engine) as s:
        a = s.execute(select(AuditLog).where(AuditLog.action == "linguist.onboard")).scalar_one()
        assert a.details["created"] is True and a.details["role_added"] is True
