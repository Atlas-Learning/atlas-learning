"""Tests T4.3 — API de session (désormais protégée RBAC). 1 test = 1 AC."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import app, get_db
from src.models import competency, item, measurement, org, session as _se, audit  # noqa: F401
from src.models.base import (
    AnswerFormat, Base, CompetencyStatus, EdgeType, ItemStatus, Role, Subject, WeightSource,
)
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.item import Item
from src.models.measurement import Response, School, Student, StudentCompetencyAbility
from src.models.org import AppUser, Membership
from src.models.session import AssessmentSession
from src.rbac.auth import make_token

ANSWER = "3/4"
CONTENT = {"stem": "1/4 + 2/4 = ?", "options": ["1/4", "3/4"], "answer": ANSWER}


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    seed = Session(bind=engine)
    school = School(name="S"); seed.add(school); seed.flush()
    student = Student(school_id=school.id); seed.add(student)
    su = AppUser(email="su@x.io"); seed.add(su); seed.flush()
    seed.add(Membership(user_id=su.id, role=Role.SUPER_ADMIN))
    a = Competency(code="X.A", label_en="a", label_ar="ا", subject=Subject.MATH, grade=4,
                   difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)
    b = Competency(code="X.B", label_en="b", label_ar="ب", subject=Subject.MATH, grade=4,
                   difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)
    seed.add_all([a, b]); seed.flush()
    seed.add(CompetencyPrerequisite(source_id=a.id, target_id=b.id, edge_type=EdgeType.HARD,
                                    correlation_strength=0.8, weight_source=WeightSource.EXPERT))
    active = Item(competency_id=b.id, content_en=dict(CONTENT), content_ar=None,
                  answer_format=AnswerFormat.MCQ, difficulty_prior=1500.0, difficulty_elo=1500.0,
                  status=ItemStatus.ACTIVE)
    quar = Item(competency_id=b.id, content_en=dict(CONTENT), content_ar=None,
                answer_format=AnswerFormat.MCQ, difficulty_prior=1500.0, difficulty_elo=1500.0,
                status=ItemStatus.QUARANTINED)
    seed.add_all([active, quar]); seed.commit()
    ids = dict(school=school.id, student=student.id, active=active.id, quar=quar.id,
               token=make_token(str(su.id)))
    seed.close()
    app.dependency_overrides[get_db] = lambda: Session(bind=engine)
    return TestClient(app), engine, ids


def _h(ids):
    return {"Authorization": f"Bearer {ids['token']}"}


def _q(engine):
    return Session(bind=engine)


def _start(client, ids) -> str:
    return client.post("/sessions", json={"student_id": str(ids["student"])},
                       headers=_h(ids)).json()["session_id"]


def test_ac1_create_session():
    client, engine, ids = _client()
    r = client.post("/sessions", json={"student_id": str(ids["student"])}, headers=_h(ids))
    assert r.status_code == 200
    with _q(engine) as s:
        sess = s.get(AssessmentSession, uuid.UUID(r.json()["session_id"]))
        assert sess is not None and sess.school_id == ids["school"]
    app.dependency_overrides.clear()


def test_q16_selected_option_is_recorded():
    client, engine, ids = _client()
    sid = _start(client, ids)
    data = client.get(f"/sessions/{sid}/next-item", headers=_h(ids)).json()
    r = client.post(f"/sessions/{sid}/responses", json={"item_id": data["item_id"], "selected": "1/4"}, headers=_h(ids))
    assert r.status_code == 200 and r.json()["was_correct"] is False
    with _q(engine) as s:
        resp = s.execute(select(Response).where(Response.session_id == uuid.UUID(sid))).scalar_one()
        assert resp.selected == "1/4" and resp.is_correct is False
    app.dependency_overrides.clear()


def test_ac2_next_item_excludes_quarantined():
    client, engine, ids = _client()
    sid = _start(client, ids)
    data = client.get(f"/sessions/{sid}/next-item", headers=_h(ids)).json()
    assert data["done"] is False
    assert data["item_id"] == str(ids["active"])
    assert "answer" not in data["content_en"]
    app.dependency_overrides.clear()


def test_ac3_response_triggers_on_response_and_returns_next():
    client, engine, ids = _client()
    sid = _start(client, ids)
    item_id = client.get(f"/sessions/{sid}/next-item", headers=_h(ids)).json()["item_id"]
    r = client.post(f"/sessions/{sid}/responses", json={"item_id": item_id, "selected": ANSWER}, headers=_h(ids))
    assert r.status_code == 200 and "done" in r.json()
    with _q(engine) as s:
        assert s.execute(select(func.count()).select_from(Response)).scalar_one() == 1
    app.dependency_overrides.clear()


def test_ac5_double_answer_rejected():
    client, engine, ids = _client()
    sid = _start(client, ids)
    item_id = client.get(f"/sessions/{sid}/next-item", headers=_h(ids)).json()["item_id"]
    client.post(f"/sessions/{sid}/responses", json={"item_id": item_id, "selected": ANSWER}, headers=_h(ids))
    again = client.post(f"/sessions/{sid}/responses", json={"item_id": item_id, "selected": ANSWER}, headers=_h(ids))
    assert again.status_code == 409
    app.dependency_overrides.clear()


def test_completed_session_rejects_response_409():
    # Revue 2026-07-08 : une session TERMINÉE (should_stop) n'accepte plus AUCUNE réponse —
    # sinon un client pouvait POSTer après l'arrêt et bouger l'Elo hors flux adaptatif.
    client, engine, ids = _client()
    sid = _start(client, ids)
    item_id = client.get(f"/sessions/{sid}/next-item", headers=_h(ids)).json()["item_id"]
    with _q(engine) as s:  # la session se termine côté serveur (décision should_stop)
        sess = s.get(AssessmentSession, uuid.UUID(sid))
        sess.status = "completed"; sess.stop_reason = "confidence"; s.commit()
    r = client.post(f"/sessions/{sid}/responses",
                    json={"item_id": item_id, "selected": ANSWER}, headers=_h(ids))
    assert r.status_code == 409
    # next-item, lui, garde son contrat de FIN de flux ({done: true}, pas un 409)
    nx = client.get(f"/sessions/{sid}/next-item", headers=_h(ids))
    assert nx.status_code == 200 and nx.json()["done"] is True
    with _q(engine) as s:  # aucun effet : ni Response ni mouvement d'Elo
        assert s.execute(select(func.count()).select_from(Response)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(StudentCompetencyAbility)).scalar_one() == 0
    app.dependency_overrides.clear()


def test_server_side_grading_wrong_answer():
    client, engine, ids = _client()
    sid = _start(client, ids)
    item_id = client.get(f"/sessions/{sid}/next-item", headers=_h(ids)).json()["item_id"]
    client.post(f"/sessions/{sid}/responses", json={"item_id": item_id, "selected": "1/4"}, headers=_h(ids))
    with _q(engine) as s:
        # corrigée CÔTÉ SERVEUR : "1/4" ≠ clé "3/4" → is_correct False, ability pénalisée
        # (la difficulté item, elle, reste gelée au prior pendant le burn-in).
        resp = s.execute(select(Response)).scalar_one()
        assert resp.is_correct is False
        ab = s.execute(select(StudentCompetencyAbility)).scalars().first()
        assert ab is not None and ab.ability_elo < 1500.0
    app.dependency_overrides.clear()


def test_session_requires_auth():
    client, engine, ids = _client()
    assert client.post("/sessions", json={"student_id": str(ids["student"])}).status_code == 401
    app.dependency_overrides.clear()


def test_ac4_ui_handles_rtl():
    html = (Path(__file__).resolve().parents[1] / "src" / "api" / "static" / "index.html").read_text("utf-8")
    assert '"rtl"' in html and '"ltr"' in html and "content_ar" in html


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
