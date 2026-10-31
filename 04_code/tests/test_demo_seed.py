"""Refonte B7 — la démo produit six semaines de boucle : chaque écran de la phase B a du contenu.

Exécuté en réduit (2 semaines, 8 élèves) sur une base temporaire : banque activée, leçons,
check-ins, plans (le dernier actif), actions faites, preuves calculées, signalements, comptes
de chaque persona, relance idempotente (reconstruction).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def demo_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini")); cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    from scripts.seed_referentiel import load_referentiel, seed
    from src.db import SessionLocal, make_engine
    engine = make_engine(url)
    with SessionLocal(bind=engine) as s:
        seed(s, load_referentiel()); s.commit()
    yield url
    engine.dispose()
    os.unlink(tmp.name)


def test_demo_seed_fills_every_phase_b_screen(demo_db):
    from demo.seed_demo_school import ACCOUNTS, main
    from src.db import SessionLocal, make_engine
    from src.models.base import CheckInKind, CheckInStatus, ItemStatus, PlanStatus, ProofOutcome, Role
    from src.models.checkin import CheckIn
    from src.models.item import Item, ItemFlag
    from src.models.lesson import MiniLesson
    from src.models.org import AppUser, Membership
    from src.models.plan import PlanAction, PlanActionMember, Proof, WeeklyPlan

    summary = main(["--weeks", "2", "--students", "8", "--quiet"])
    assert summary["active_plan"] and summary["plans"] >= 2 and summary["proofs"] > 0 and summary["responses"] > 50

    with SessionLocal(bind=make_engine(demo_db)) as s:
        assert s.execute(select(Item).where(Item.status == ItemStatus.ACTIVE)).scalars().first() is not None
        assert all(it.template_key and it.content_ar for it in s.execute(select(Item)).scalars())
        # un plan actif par classe, daté d'un lundi, avec des actions et une leçon attachée
        # un plan actif par (classe, semaine) : 2 semaines × 2 classes ; tous datés d'un lundi
        active = s.execute(select(WeeklyPlan).where(WeeklyPlan.status == PlanStatus.ACTIVE)).scalars().all()
        assert len(active) == 4 and all(p.week_start.weekday() == 0 for p in active)
        assert len({(p.classroom_id, p.week_start) for p in active}) == 4
        actions = s.execute(select(PlanAction)).scalars().all()
        assert actions and any(a.lesson_id for a in actions)
        assert all(s.execute(select(PlanActionMember).where(PlanActionMember.action_id == a.id)).scalars().first() for a in actions)
        # boucles bouclées : actions faites avec re-check clos et preuves calculées
        done = [a for a in actions if a.status.value == "done"]
        assert done
        rechecks = s.execute(select(CheckIn).where(CheckIn.kind == CheckInKind.TARGETED)).scalars().all()
        assert rechecks and all(c.status == CheckInStatus.CLOSED and c.plan_action_id for c in rechecks)
        outcomes = {p.outcome for p in s.execute(select(Proof)).scalars()}
        assert ProofOutcome.UNLOCKED in outcomes or ProofOutcome.UNCHANGED in outcomes
        # horodatage étalé : le premier check-in date d'au moins une semaine
        from src.models.base import ensure_utc, utcnow
        first = min(ensure_utc(c.opened_at) for c in s.execute(select(CheckIn)).scalars())
        assert (utcnow() - first).days >= 7
        # leçons : chaque racine possible en a une (vraie ou [DEMO]) ; signalements en file
        assert s.execute(select(MiniLesson)).scalars().first() is not None
        assert len(s.execute(select(ItemFlag)).scalars().all()) == 2
        # comptes de chaque persona
        roles = {}
        for email in ACCOUNTS.values():
            u = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
            roles[email] = {m.role for m in s.execute(select(Membership).where(Membership.user_id == u.id)).scalars()}
        assert Role.DEPT_LEAD in roles["coord@demo.atlas"] and Role.GROUP_ADMIN in roles["group@demo.atlas"]
        assert Role.CONTENT_REVIEWER in roles["relecteur@atlas.io"] and Role.SUPER_ADMIN in roles["ops@atlas.io"]

    # relance : la démo est reconstruite, pas dupliquée
    again = main(["--weeks", "2", "--students", "8", "--quiet"])
    assert again["active_plan"] and again["plans"] == summary["plans"]
