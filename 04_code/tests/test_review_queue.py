"""Refonte A4 — file de revue /ops/review (écran O2).

« Fait quand » : les 4 sources (signalements, échecs de validation, items d'école, arabe à
valider) sont dans une file filtrable ; détail EN/AR ; regroupement par gabarit ; actions selon
le rôle. Tests : RBAC (un teacher reçoit 403), contenu de la file, transitions par la machine
à états uniquement, actions super admin invisibles et refusées pour le relecteur.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import app, get_db
from src.items import review, review_queue
from src.models import competency, item, measurement, org, session as _se, audit as _au  # noqa: F401
from src.models.audit import AuditLog
from src.models.base import (
    AnswerFormat, Base, CompetencyStatus, ItemFlagReason, ItemOrigin, ItemStatus, Role, Subject,
)
from src.models.competency import Competency
from src.models.item import Item
from src.models.measurement import School
from src.models.org import AppUser, Membership
from src.rbac.auth import make_token

EN = {"stem": "What is 1/2 + 1/4?", "options": ["3/4", "2/6"], "answer": "3/4"}
AR = {"stem": "ما ناتج 1/2 + 1/4؟", "options": ["3/4", "2/6"], "answer": "3/4"}
AR_BROKEN = {"stem": "ما ناتج 1/2 + 1/4؟", "options": ["9/9", "2/6"], "answer": "9/9"}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _item(s, comp, *, status=ItemStatus.ACTIVE, content_ar=AR, ar_validated=True, key="MATH.G4.NF.ADD_LIKE#00", **kw):
    it = Item(competency_id=comp.id, content_en=dict(EN), content_ar=dict(content_ar) if content_ar else None,
              answer_format=AnswerFormat.MCQ, difficulty_prior=1200.0, ar_validated=ar_validated,
              status=status, template_key=key, **kw)
    s.add(it); s.flush()
    return it


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _setup():
    s = _session()
    comp = Competency(code="MATH.G4.NF.ADD_LIKE", label_en="x", label_ar="س", subject=Subject.MATH, grade=4,
                      difficulty_prior=1200.0, status=CompetencyStatus.ACTIVE)
    s.add(comp); s.flush()
    school = School(name="Al Noor"); s.add(school); s.flush()
    clean = _item(s, comp)                                                           # hors file
    flagged = _item(s, comp, key="MATH.G4.NF.ADD_LIKE#01")                           # flag
    broken = _item(s, comp, content_ar=AR_BROKEN, key="MATH.G4.NF.ADD_LIKE#02")      # validation
    school_item = _item(s, comp, origin=ItemOrigin.SCHOOL, owner_school_id=school.id, key=None,
                        status=ItemStatus.AI_GENERATED, ar_validated=False)          # school
    arabic = _item(s, comp, status=ItemStatus.HUMAN_REVIEWED, ar_validated=False,
                   key="MATH.G4.NF.ADD_LIKE#03")                                     # arabic
    fresh = _item(s, comp, status=ItemStatus.AI_GENERATED, ar_validated=False, content_ar=None,
                  key="MATH.G4.NF.ADD_LIKE#04")                                      # hors file (rien à signaler)
    ready = _item(s, comp, status=ItemStatus.LINGUIST_VALIDATED, key="MATH.G4.NF.ADD_LIKE#05")  # hors file
    quarantined = _item(s, comp, status=ItemStatus.QUARANTINED, key="MATH.G4.NF.ADD_LIKE#06")
    teacher, rev, su = (AppUser(email=f"{n}@x.io") for n in ("t", "rev", "ops"))
    s.add_all([teacher, rev, su]); s.flush()
    s.add_all([Membership(user_id=teacher.id, role=Role.TEACHER, school_id=school.id),
               Membership(user_id=rev.id, role=Role.CONTENT_REVIEWER),
               Membership(user_id=su.id, role=Role.SUPER_ADMIN)])
    review.flag_item(s, flagged, raised_by=teacher.id, reason=ItemFlagReason.SEVERAL_CORRECT, school_id=school.id)
    review.flag_item(s, flagged, raised_by=teacher.id, reason=ItemFlagReason.WRONG_ANSWER_KEY)
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    ids = dict(clean=clean.id, flagged=flagged.id, broken=broken.id, school=school_item.id, arabic=arabic.id,
               fresh=fresh.id, ready=ready.id, quarantined=quarantined.id, teacher=teacher.id, rev=rev.id, su=su.id)
    return TestClient(app), ids, s


def test_queue_rbac_and_sources():
    client, ids, s = _setup()
    try:
        assert client.get("/ops/review", headers=_auth(ids["teacher"])).status_code == 403
        assert client.get("/ops/review?source=bizarre", headers=_auth(ids["rev"])).status_code == 400
        q = client.get("/ops/review", headers=_auth(ids["rev"])).json()
        assert q["counts"] == {"flag": 1, "validation": 1, "school": 1, "arabic": 1, "all": 4}
        by_id = {e["item_id"]: e for g in q["groups"] for e in g["items"]}
        assert set(by_id) == {str(ids[k]) for k in ("flagged", "broken", "school", "arabic")}
        assert by_id[str(ids["flagged"])]["sources"] == ["flag"]
        assert by_id[str(ids["flagged"])]["open_flags"] == 2 and by_id[str(ids["flagged"])]["flag_schools"] == 1
        assert by_id[str(ids["flagged"])]["flag_reasons"] == ["several_correct", "wrong_answer_key"]
        assert by_id[str(ids["broken"])]["sources"] == ["validation"]
        assert any("altérés" in e for e in by_id[str(ids["broken"])]["validation_errors"])
        assert by_id[str(ids["school"])]["sources"] == ["school"] and by_id[str(ids["school"])]["template"] is None
        assert by_id[str(ids["arabic"])]["sources"] == ["arabic"] and by_id[str(ids["arabic"])]["stem_ar"]
        # regroupement par gabarit : le gabarit signalé en tête, l'item d'école dans son propre groupe
        assert q["groups"][0]["template"] == "MATH.G4.NF.ADD_LIKE" and q["groups"][0]["n_items"] == 3
        assert q["groups"][0]["open_flags"] == 2 and q["groups"][0]["n_active"] == 2
        assert q["groups"][1]["template"] is None
        # filtre par source
        f = client.get("/ops/review?source=flag", headers=_auth(ids["rev"])).json()
        assert f["n_items"] == 1 and f["groups"][0]["items"][0]["item_id"] == str(ids["flagged"])
        assert f["counts"]["all"] == 4                                   # compteurs globaux inchangés
        assert client.get("/ops/review?source=school", headers=_auth(ids["su"])).json()["n_items"] == 1
    finally:
        app.dependency_overrides.clear()


def test_detail_shows_en_ar_flags_versions_and_role_actions():
    client, ids, s = _setup()
    try:
        d = client.get(f"/ops/review/items/{ids['flagged']}", headers=_auth(ids["rev"])).json()
        assert d["content_en"] == EN and d["content_ar"] == AR
        assert [f["reason"] for f in d["flags"]] == ["several_correct", "wrong_answer_key"]
        assert d["lifecycle"] == ["ai_generated", "human_reviewed", "linguist_validated", "active"]
        assert [v["version"] for v in d["versions"]] == [1]
        # relecteur : pas d'action réservée au super admin
        assert d["actions"] == ["quarantine", "reject", "resolve_flag", "quarantine_template"]
        d_su = client.get(f"/ops/review/items/{ids['flagged']}", headers=_auth(ids["su"])).json()
        assert "regenerate" in d_su["actions"]
        q = client.get(f"/ops/review/items/{ids['quarantined']}", headers=_auth(ids["rev"])).json()
        assert "rehabilitate" not in q["actions"]
        assert "rehabilitate" in client.get(f"/ops/review/items/{ids['quarantined']}", headers=_auth(ids["su"])).json()["actions"]
        r = client.get(f"/ops/review/items/{ids['ready']}", headers=_auth(ids["su"])).json()
        assert "activate" in r["actions"]
        assert client.get(f"/ops/review/items/{uuid.uuid4()}", headers=_auth(ids["rev"])).status_code == 404
        assert client.get(f"/ops/review/items/{ids['flagged']}", headers=_auth(ids["teacher"])).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_transitions_go_through_state_machine_with_role_split():
    client, ids, s = _setup()
    try:
        h_rev, h_su = _auth(ids["rev"]), _auth(ids["su"])
        # approve : ai_generated → human_reviewed (relecteur)
        r = client.post(f"/items/{ids['fresh']}/transition", json={"target": "human_reviewed"}, headers=h_rev)
        assert r.status_code == 200 and r.json()["status"] == "human_reviewed"
        # saut d'étape refusé : human_reviewed → active n'existe pas par cette route
        assert client.post(f"/items/{ids['fresh']}/transition", json={"target": "active"}, headers=h_su).status_code == 400
        # linguist_validated reste le geste du linguiste
        assert client.post(f"/items/{ids['fresh']}/transition", json={"target": "linguist_validated"}, headers=h_su).status_code == 400
        # quarantine (relecteur) puis rehabilitate : super admin seulement
        assert client.post(f"/items/{ids['clean']}/transition", json={"target": "quarantined", "reason": "doute"},
                           headers=h_rev).json()["status"] == "quarantined"
        assert client.post(f"/items/{ids['clean']}/transition", json={"target": "active"}, headers=h_rev).status_code == 403
        assert client.post(f"/items/{ids['clean']}/transition", json={"target": "active"}, headers=h_su).json()["status"] == "active"
        # activate : linguist_validated → active, super admin seulement, précondition ar_validated
        assert client.post(f"/items/{ids['ready']}/transition", json={"target": "active"}, headers=h_rev).status_code == 403
        assert client.post(f"/items/{ids['ready']}/transition", json={"target": "active"}, headers=h_su).json()["status"] == "active"
        assert client.post(f"/items/{ids['ready']}/transition", json={"target": "typo"}, headers=h_su).status_code == 400
        assert client.post(f"/items/{ids['ready']}/transition", json={"target": "quarantined"},
                           headers=_auth(ids["teacher"])).status_code == 403
        actions = {a.action for a in s.execute(select(AuditLog)).scalars()}
        assert {"item.approve", "item.quarantine", "item.rehabilitate", "item.activate"} <= actions
        assert s.get(Item, ids["clean"]).provenance["quarantine_reason"] == "doute"
    finally:
        app.dependency_overrides.clear()


def test_reject_is_soft_delete_and_leaves_the_queue():
    client, ids, s = _setup()
    try:
        assert client.post(f"/items/{ids['broken']}/reject", json={"reason": ""}, headers=_auth(ids["rev"])).status_code == 400
        assert client.post(f"/items/{ids['broken']}/reject", json={"reason": "AR cassé"}, headers=_auth(ids["teacher"])).status_code == 403
        r = client.post(f"/items/{ids['broken']}/reject", json={"reason": "AR cassé"}, headers=_auth(ids["rev"]))
        assert r.status_code == 200
        it = s.get(Item, ids["broken"])
        assert it.deleted_at is not None and it.provenance["reject_reason"] == "AR cassé"
        q = client.get("/ops/review", headers=_auth(ids["rev"])).json()
        assert q["counts"]["validation"] == 0 and q["counts"]["all"] == 3
        assert client.get(f"/ops/review/items/{ids['broken']}", headers=_auth(ids["rev"])).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_structural_issue_detection():
    s = _session()
    comp = Competency(code="M.A", label_en="x", label_ar="س", subject=Subject.MATH, grade=4,
                      difficulty_prior=1200.0, status=CompetencyStatus.ACTIVE)
    s.add(comp); s.flush()
    it = _item(s, comp, content_ar=None, ar_validated=False)
    assert review_queue.structural_issue(it) is None
    it.content_en = {"stem": "q", "options": ["3/4", "3/4"], "answer": "3/4"}
    assert review_queue.structural_issue(it) == "options en doublon"
    it.content_en = {"stem": "q", "options": ["1/4"], "answer": "1/4"}
    assert review_queue.structural_issue(it) == "MCQ avec moins de 2 options"
    it.content_en = {"stem": "q", "options": ["1/4", "2/4"], "answer": "9/9"}
    assert review_queue.structural_issue(it) == "réponse absente des options"
    it.provenance = {"ar_math_broken": True}
    assert any("ar_math_broken" in e for e in review_queue.validation_errors(it))
