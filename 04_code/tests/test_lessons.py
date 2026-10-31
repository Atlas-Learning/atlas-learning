"""Refonte B3 — mini-leçons : chargement idempotent depuis data/lessons, validation de forme,
choix de la meilleure leçon pour une action du plan, arabe posé et validé par le linguiste,
activation, lecture par les rôles autorisés.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import lesson_service as ls
from src.api.app import app, get_db
from src.models import competency, item, measurement, org, session as _se, audit as _au, checkin as _ci, plan as _pl, lesson as _le  # noqa: F401
from src.models.base import Base, CompetencyStatus, LessonStatus, Role, Subject
from src.models.competency import Competency
from src.models.lesson import MiniLesson
from src.models.measurement import School
from src.models.org import AppUser, Membership
from src.rbac.auth import make_token

REPO_LESSONS = Path(__file__).resolve().parents[1] / "data" / "lessons"


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _comp(s, code="MATH.G3.NF.UNIT_FRACTION"):
    c = Competency(code=code, label_en="Unit fraction", label_ar="الكسر الوحدوي", subject=Subject.MATH, grade=3,
                   difficulty_prior=1300.0, status=CompetencyStatus.ACTIVE)
    s.add(c); s.flush()
    return c


def _doc(key="L.v1", comp="MATH.G3.NF.UNIT_FRACTION", **over):
    d = {"key": key, "competency": comp, "title_en": "T", "title_ar": None, "duration_min": 10, "version": 1,
         "steps": [{"kind": "warmup", "minutes": 2, "body_en": "w"}, {"kind": "model", "minutes": 4, "body_en": "m"},
                   {"kind": "exit", "minutes": 2, "body_en": "e"}]}
    d.update(over)
    return ls.LessonDoc.model_validate(d)


def test_repo_lessons_are_well_formed_and_seed_is_idempotent():
    s = _session(); _comp(s); _comp(s, "MATH.G4.NF.ADD_SAME_SIMPLIFY"); s.commit()
    docs = [ls.load_doc(p) for p in sorted(REPO_LESSONS.glob("*.json")) if not p.name.startswith("_")]
    assert docs and all(d.steps[0].kind == "warmup" and d.steps[-1].kind == "exit" for d in docs)
    rep = ls.seed_lessons(s, REPO_LESSONS); s.commit()
    assert rep["errors"] == [] and rep["created"] == [d.key for d in docs] and rep["updated"] == []
    lesson = s.execute(select(MiniLesson)).scalars().one()
    assert lesson.key == "MATH.G3.NF.UNIT_FRACTION.v1" and lesson.status == LessonStatus.DRAFT
    assert lesson.title_ar is None and not ls.arabic_complete(lesson)
    rep2 = ls.seed_lessons(s, REPO_LESSONS); s.commit()
    assert rep2["created"] == [] and rep2["updated"] == [lesson.key]
    assert len(s.execute(select(MiniLesson)).scalars().all()) == 1          # _TEMPLATE.json ignoré, pas de doublon
    assert ls.seed_lessons(s, REPO_LESSONS, dry_run=True)["updated"] == [lesson.key]


def test_doc_validation_rejects_bad_shape(tmp_path):
    with pytest.raises(Exception):
        _doc(steps=[{"kind": "exit", "minutes": 2, "body_en": "e"}, {"kind": "warmup", "minutes": 2, "body_en": "w"}])
    with pytest.raises(Exception):
        _doc(steps=[{"kind": "warmup", "minutes": 0, "body_en": "w"}])
    with pytest.raises(Exception):
        _doc(steps=[{"kind": "warmup", "minutes": 2, "body_en": ""}])
    with pytest.raises(Exception):
        _doc(steps=[{"kind": "song", "minutes": 2, "body_en": "x"}])
    bad = tmp_path / "X.json"; bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ls.LessonError):
        ls.load_doc(bad)
    s = _session(); _comp(s); s.commit()
    with pytest.raises(ls.LessonError):
        ls.upsert_lesson(s, _doc(comp="MATH.NOPE"))
    # un dossier avec une leçon cassée : l'erreur est rapportée, les autres passent
    good = tmp_path / "MATH.G3.NF.UNIT_FRACTION.v2.json"
    good.write_text(json.dumps({"competency": "MATH.G3.NF.UNIT_FRACTION", "title_en": "T2", "duration_min": 8, "version": 2,
                                "steps": [{"kind": "model", "minutes": 8, "body_en": "m"}]}), encoding="utf-8")
    rep = ls.seed_lessons(s, tmp_path); s.commit()
    assert rep["created"] == ["MATH.G3.NF.UNIT_FRACTION.v2"] and len(rep["errors"]) == 1


def test_pick_lesson_prefers_status_then_version_and_reseed_keeps_status():
    s = _session(); comp = _comp(s); s.commit()
    v1, _ = ls.upsert_lesson(s, _doc("L.v1", version=1))
    v2, _ = ls.upsert_lesson(s, _doc("L.v2", version=2)); s.commit()
    assert ls.pick_lesson(s, comp.id).id == v2.id                             # même statut : version la plus haute
    v1.status = LessonStatus.ACTIVE; s.commit()
    assert ls.pick_lesson(s, comp.id).id == v1.id                             # statut l'emporte
    # re-seed du même contenu : statut conservé ; arabe modifié : retour en draft
    ls.upsert_lesson(s, _doc("L.v1", version=1)); s.commit()
    assert v1.status == LessonStatus.ACTIVE
    ls.upsert_lesson(s, _doc("L.v1", version=1, title_ar="عنوان")); s.commit()
    assert v1.status == LessonStatus.DRAFT
    assert ls.pick_lesson(s, uuid.uuid4()) is None


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _api():
    s = _session(); comp = _comp(s)
    school = School(name="A"); s.add(school); s.flush()
    lesson, _ = ls.upsert_lesson(s, _doc("L.v1"))
    users = {}
    for name, role in (("t", Role.TEACHER), ("lead", Role.DEPT_LEAD), ("ling", Role.LINGUIST),
                       ("rev", Role.CONTENT_REVIEWER), ("su", Role.SUPER_ADMIN), ("stud", Role.STUDENT), ("par", Role.PARENT)):
        u = AppUser(email=f"{name}@x.io"); s.add(u); s.flush()
        s.add(Membership(user_id=u.id, role=role, school_id=school.id if role in (Role.TEACHER, Role.DEPT_LEAD) else None))
        users[name] = u.id
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    return TestClient(app), dict(users, lesson=lesson.id, comp=comp.id), s


def test_lesson_read_rbac_and_lifecycle_via_linguist():
    client, ids, s = _api()
    try:
        for who in ("stud", "par"):
            assert client.get(f"/lessons/{ids['lesson']}", headers=_auth(ids[who])).status_code == 403
        for who in ("t", "lead", "ling", "rev", "su"):
            r = client.get(f"/lessons/{ids['lesson']}", headers=_auth(ids[who]))
            assert r.status_code == 200
        assert r.json()["competency"]["code"] == "MATH.G3.NF.UNIT_FRACTION" and len(r.json()["steps"]) == 3
        assert client.get(f"/lessons/{uuid.uuid4()}", headers=_auth(ids["t"])).status_code == 404
        lst = client.get(f"/lessons?competency_id={ids['comp']}", headers=_auth(ids["t"])).json()
        assert [l["key"] for l in lst["lessons"]] == ["L.v1"] and "steps" not in lst["lessons"][0]

        url = f"/linguist/lessons/{ids['lesson']}"
        # valider sans arabe → 409 ; poser l'arabe (3 étapes) : enseignant 403, linguiste 200
        assert client.post(f"{url}/validate", headers=_auth(ids["ling"])).status_code == 409
        assert client.post(f"{url}/arabic", json={"title_ar": "ع", "bodies_ar": ["أ", "ب", "ج"]}, headers=_auth(ids["t"])).status_code == 403
        assert client.post(f"{url}/arabic", json={"title_ar": "ع", "bodies_ar": ["أ", "ب"]}, headers=_auth(ids["ling"])).status_code == 400
        partial = client.post(f"{url}/arabic", json={"title_ar": "ع", "bodies_ar": ["أ", None, "ج"]}, headers=_auth(ids["ling"])).json()
        assert partial["arabic_complete"] is False and "body_ar" not in partial["steps"][1]
        assert client.post(f"{url}/validate", headers=_auth(ids["ling"])).status_code == 409
        full = client.post(f"{url}/arabic", json={"title_ar": "ع", "bodies_ar": ["أ", "ب", "ج"]}, headers=_auth(ids["ling"])).json()
        assert full["arabic_complete"] is True and full["status"] == "draft"
        v = client.post(f"{url}/validate", headers=_auth(ids["ling"]))
        assert v.status_code == 200 and v.json()["status"] == "linguist_validated"
        # activation : linguiste non, relecteur oui ; une 2e activation → 409
        assert client.post(f"/lessons/{ids['lesson']}/activate", headers=_auth(ids["ling"])).status_code == 403
        a = client.post(f"/lessons/{ids['lesson']}/activate", headers=_auth(ids["rev"]))
        assert a.status_code == 200 and a.json()["status"] == "active"
        assert client.post(f"/lessons/{ids['lesson']}/activate", headers=_auth(ids["su"])).status_code == 409
        # corriger l'arabe d'une leçon active la repasse en draft (à revalider)
        again = client.post(f"{url}/arabic", json={"title_ar": "ع2", "bodies_ar": ["أ", "ب", "ج"]}, headers=_auth(ids["ling"])).json()
        assert again["status"] == "draft"
    finally:
        app.dependency_overrides.clear()


def test_ops_editor_creates_updates_and_reports_coverage():
    client, ids, s = _api()
    try:
        from src.models.base import CompetencyStatus, EdgeType, Subject, WeightSource
        from src.models.competency import Competency, CompetencyPrerequisite
        # A ← B (HARD) : A est une racine possible
        root = s.execute(select(Competency).where(Competency.code == "MATH.G3.NF.UNIT_FRACTION")).scalar_one()
        b = Competency(code="MATH.G3.NF.FRACTION_AS_PART", label_en="Part", label_ar="جزء", subject=Subject.MATH, grade=3,
                       difficulty_prior=1300.0, status=CompetencyStatus.ACTIVE)
        s.add(b); s.flush()
        s.add(CompetencyPrerequisite(source_id=root.id, target_id=b.id, edge_type=EdgeType.HARD,
                                     correlation_strength=0.8, weight_source=WeightSource.EXPERT))
        s.add(CompetencyPrerequisite(source_id=b.id, target_id=ids["comp"] if False else b.id, edge_type=EdgeType.HARD,
                                     correlation_strength=0.8, weight_source=WeightSource.EXPERT)) if False else None
        s.commit()
        assert client.get("/ops/lessons", headers=_auth(ids["t"])).status_code == 403
        lst = client.get("/ops/lessons", headers=_auth(ids["rev"])).json()
        assert [l["key"] for l in lst["lessons"]] == ["L.v1"]
        cov = {c["code"]: c for c in lst["coverage"]}
        assert cov["MATH.G3.NF.UNIT_FRACTION"]["unlocks"] == 1 and cov["MATH.G3.NF.UNIT_FRACTION"]["best_status"] == "draft"
        assert "MATH.G3.NF.FRACTION_AS_PART" not in cov                      # pas prérequis de quoi que ce soit
        # création depuis l'UI : clé dérivée, validation de forme, brouillon
        body = {"competency": "MATH.G3.NF.FRACTION_AS_PART", "title_en": "Parts of a whole", "duration_min": 12,
                "steps": [{"kind": "warmup", "minutes": 2, "body_en": "w"}, {"kind": "exit", "minutes": 2, "body_en": "e"}]}
        assert client.post("/ops/lessons", json=body, headers=_auth(ids["ling"])).status_code == 403
        bad = {**body, "steps": [{"kind": "exit", "minutes": 2, "body_en": "e"}, {"kind": "warmup", "minutes": 2, "body_en": "w"}]}
        assert client.post("/ops/lessons", json=bad, headers=_auth(ids["rev"])).status_code == 400
        r = client.post("/ops/lessons", json=body, headers=_auth(ids["rev"]))
        assert r.status_code == 200 and r.json()["key"] == "MATH.G3.NF.FRACTION_AS_PART.v1" and r.json()["status"] == "draft"
        lid = r.json()["id"]
        # édition : le titre change, la clé reste ; une compétence inconnue → 400
        up = client.put(f"/ops/lessons/{lid}", json={**body, "title_en": "Parts of a whole, v2"}, headers=_auth(ids["su"]))
        assert up.status_code == 200 and up.json()["title_en"] == "Parts of a whole, v2" and up.json()["key"] == "MATH.G3.NF.FRACTION_AS_PART.v1"
        assert client.put(f"/ops/lessons/{lid}", json={**body, "competency": "NOPE"}, headers=_auth(ids["su"])).status_code == 400
        assert client.put(f"/ops/lessons/{uuid.uuid4()}", json=body, headers=_auth(ids["su"])).status_code == 404
        assert len(client.get("/ops/lessons", headers=_auth(ids["su"])).json()["lessons"]) == 2
    finally:
        app.dependency_overrides.clear()
