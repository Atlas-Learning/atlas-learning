"""Refonte A2 — signalements d'items et versions.

« Fait quand » : un enseignant signale un item ; le signalement apparaît dans la file ; aucune
transition de statut ne contourne ALLOWED_TRANSITIONS. Couvre le service (review.py) et l'API
(/items/{id}/flags, /items/flags, /items/flags/{id}/resolve) avec RBAC.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import app, get_db
from src.items import review
from src.items.quarantine import active_pool
from src.models import competency, item, measurement, org, session as _se, audit as _au  # noqa: F401
from src.models.audit import AuditLog
from src.models.base import (
    AnswerFormat, Base, CompetencyStatus, ItemFlagReason, ItemFlagStatus, ItemOrigin, ItemStatus,
    Role, Subject,
)
from src.models.competency import Competency
from src.models.item import Item, ItemFlag
from src.models.measurement import School, Student
from src.models.org import AppUser, Classroom, DeptLeadScope, Membership, TeacherClassroom
from src.rbac.auth import make_token

CONTENT = {"stem": "What is 1/2 + 1/4?", "options": ["3/4", "2/6"], "answer": "3/4"}
AR = {"stem": "ما هو ١/٢ + ١/٤؟", "options": ["3/4", "2/6"], "answer": "3/4"}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _comp(s):
    c = Competency(code="MATH.G4.NF.ADD_LIKE", label_en="x", label_ar="س", subject=Subject.MATH, grade=4,
                   difficulty_prior=1200.0, status=CompetencyStatus.ACTIVE)
    s.add(c); s.flush()
    return c


def _item(s, comp, status=ItemStatus.ACTIVE, **kw):
    it = Item(competency_id=comp.id, content_en=dict(CONTENT), content_ar=dict(AR),
              answer_format=AnswerFormat.MCQ, difficulty_prior=1200.0, ar_validated=True,
              status=status, template_key="MATH.G4.NF.ADD_LIKE#03", **kw)
    s.add(it); s.flush()
    return it


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _reviewer(s):
    u = AppUser(email=f"rev-{uuid.uuid4().hex[:6]}@atlas.io"); s.add(u); s.flush()
    return u.id


def _api():
    s = _session()
    comp = _comp(s)
    school = School(name="A"); s.add(school); s.flush()
    cls = Classroom(school_id=school.id, name="4A", grade=4); s.add(cls); s.flush()
    active = _item(s, comp)
    pending = _item(s, comp, status=ItemStatus.AI_GENERATED)
    teacher, lead, parent, su, ling = (AppUser(email=f"{n}@x.io") for n in ("t", "lead", "p", "ops", "ling"))
    stud_user = AppUser(email="s@x.io"); rev = AppUser(email="rev@x.io")
    s.add_all([teacher, lead, parent, su, ling, stud_user, rev]); s.flush()
    s.add(Membership(user_id=rev.id, role=Role.CONTENT_REVIEWER))
    m_lead = Membership(user_id=lead.id, role=Role.DEPT_LEAD, school_id=school.id); s.add(m_lead); s.flush()
    s.add_all([
        Membership(user_id=teacher.id, role=Role.TEACHER, school_id=school.id),
        TeacherClassroom(user_id=teacher.id, classroom_id=cls.id),
        DeptLeadScope(membership_id=m_lead.id, grade=4),
        Membership(user_id=parent.id, role=Role.PARENT),
        Membership(user_id=su.id, role=Role.SUPER_ADMIN),
        Membership(user_id=ling.id, role=Role.LINGUIST),
        Membership(user_id=stud_user.id, role=Role.STUDENT),
        Student(school_id=school.id, classroom_id=cls.id, user_id=stud_user.id),
    ])
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    ids = dict(school=school.id, active=active.id, pending=pending.id, teacher=teacher.id, lead=lead.id,
               parent=parent.id, su=su.id, ling=ling.id, student=stud_user.id, rev=rev.id)
    return TestClient(app), ids, s


# ---------- service ----------

def test_flag_does_not_touch_item_status_or_content():
    s = _session(); comp = _comp(s); it = _item(s, comp)
    fl = review.flag_item(s, it, raised_by=None, reason=ItemFlagReason.WRONG_ANSWER_KEY, comment="  2/6 ?  ")
    s.commit()
    assert fl.status == ItemFlagStatus.OPEN and fl.comment == "2/6 ?"
    assert it.status == ItemStatus.ACTIVE and it.content_en == CONTENT
    assert [f.id for f in review.list_flags(s)] == [fl.id]
    assert review.open_flag_count(s, it.id) == 1


def test_accept_quarantines_only_through_state_machine():
    s = _session(); comp = _comp(s)
    active = _item(s, comp); pending = _item(s, comp, status=ItemStatus.AI_GENERATED)
    reviewer = _reviewer(s)
    f1 = review.flag_item(s, active, raised_by=None, reason=ItemFlagReason.SEVERAL_CORRECT)
    f2 = review.flag_item(s, pending, raised_by=None, reason=ItemFlagReason.UNCLEAR_WORDING)
    review.resolve_flag(s, f1, resolver=reviewer, accept=True); s.commit()
    assert active.status == ItemStatus.QUARANTINED                 # active → quarantined : autorisé
    assert active.provenance["reviewer"] == str(reviewer) and "signalement" in active.provenance["quarantine_reason"]
    assert active not in active_pool(s)
    review.resolve_flag(s, f2, resolver=reviewer, accept=True); s.commit()
    assert pending.status == ItemStatus.AI_GENERATED               # pas de saut vers quarantined
    assert f1.status == f2.status == ItemFlagStatus.ACCEPTED and f1.resolved_by == reviewer and f1.resolved_at
    with pytest.raises(review.InvalidTransition):
        review.resolve_flag(s, f1, resolver=reviewer, accept=False)   # déjà tranché
    assert review.list_flags(s) == [] and len(review.list_flags(s, status=None)) == 2


def test_reject_leaves_item_untouched():
    s = _session(); comp = _comp(s); it = _item(s, comp)
    fl = review.flag_item(s, it, raised_by=None, reason=ItemFlagReason.OTHER)
    review.resolve_flag(s, fl, resolver=_reviewer(s), accept=False); s.commit()
    assert fl.status == ItemFlagStatus.REJECTED and it.status == ItemStatus.ACTIVE and it in active_pool(s)


def test_supersede_creates_version_and_retires_old_through_state_machine():
    s = _session(); comp = _comp(s)
    old = _item(s, comp); old.n_responses = 12; s.commit()
    fixed = {**CONTENT, "options": ["3/4", "1/3"]}
    new = review.supersede(s, old, content_en=fixed, by="ops")
    assert new.version == 2 and new.supersedes_id == old.id and new.template_key == old.template_key
    assert new.status == ItemStatus.AI_GENERATED and new.ar_validated is False and new.content_ar is None
    assert new.n_responses == 0 and new.origin == ItemOrigin.ATLAS_TEMPLATE
    assert new.provenance["superseded_from"] == str(old.id)
    assert old.status == ItemStatus.QUARANTINED and old.n_responses == 12   # réponses attachées à l'ancienne
    assert old not in active_pool(s) and new not in active_pool(s)
    # version jamais publiée : rejetée (soft delete), jamais détruite
    draft = _item(s, comp, status=ItemStatus.HUMAN_REVIEWED)
    new2 = review.supersede(s, draft, content_en=fixed, by="ops")
    assert draft.deleted_at is not None and draft.status == ItemStatus.HUMAN_REVIEWED
    assert s.get(Item, draft.id) is not None and new2.version == 2
    with pytest.raises(Exception):
        review.supersede(s, new, content_en={"options": ["a"]}, by="ops")   # contenu invalide


def test_reset_calibration():
    s = _session(); comp = _comp(s); it = _item(s, comp)
    it.n_responses, it.difficulty_elo = 40, 1480.0; s.commit()
    review.reset_calibration(s, it, by="ops")
    assert it.calibration_reset_at is not None and it.n_responses == 0 and it.difficulty_elo == 1200.0
    assert it.provenance["calibration_reset"] is True and it.status == ItemStatus.ACTIVE


# ---------- API ----------

def test_teacher_flags_item_and_it_appears_in_queue():
    client, ids, s = _api()
    try:
        r = client.post(f"/items/{ids['active']}/flags", json={"reason": "wrong_answer_key", "comment": "2/6 is also right?"},
                        headers=_auth(ids["teacher"]))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "open" and body["school_id"] == str(ids["school"])   # école dérivée de ses classes
        assert body["raised_by"] == str(ids["teacher"]) and body["item"]["template_key"] == "MATH.G4.NF.ADD_LIKE#03"
        assert s.get(Item, ids["active"]).status == ItemStatus.ACTIVE               # rien ne bouge
        # file : super admin oui, enseignant non
        assert client.get("/items/flags", headers=_auth(ids["teacher"])).status_code == 403
        q = client.get("/items/flags", headers=_auth(ids["su"]))
        assert q.status_code == 200 and [f["id"] for f in q.json()["flags"]] == [body["id"]]
        assert q.json()["flags"][0]["item"]["stem_en"] == CONTENT["stem"]
        assert client.get("/items/flags?status=bizarre", headers=_auth(ids["su"])).status_code == 400
        audit = s.execute(select(AuditLog).where(AuditLog.action == "item.flag")).scalars().all()
        assert len(audit) == 1 and audit[0].school_id == ids["school"]
    finally:
        app.dependency_overrides.clear()


def test_flag_rbac_and_validation():
    client, ids, s = _api()
    try:
        url = f"/items/{ids['active']}/flags"
        for who in ("parent", "student"):
            assert client.post(url, json={"reason": "other"}, headers=_auth(ids[who])).status_code == 403
        for who in ("lead", "ling", "su", "rev"):
            assert client.post(url, json={"reason": "arabic"}, headers=_auth(ids[who])).status_code == 200
        assert client.post(url, json={"reason": "typo"}, headers=_auth(ids["teacher"])).status_code == 400
        assert client.post(f"/items/{uuid.uuid4()}/flags", json={"reason": "other"},
                           headers=_auth(ids["teacher"])).status_code == 404
        # le coordinateur : école de sa portée ; le staff global : aucune école
        flags = client.get("/items/flags", headers=_auth(ids["su"])).json()["flags"]
        by_user = {f["raised_by"]: f["school_id"] for f in flags}
        assert by_user[str(ids["lead"])] == str(ids["school"]) and by_user[str(ids["ling"])] is None
    finally:
        app.dependency_overrides.clear()


def test_resolve_accept_quarantines_active_item_only():
    client, ids, s = _api()
    try:
        f_active = client.post(f"/items/{ids['active']}/flags", json={"reason": "several_correct"},
                               headers=_auth(ids["teacher"])).json()["id"]
        f_pending = client.post(f"/items/{ids['pending']}/flags", json={"reason": "unclear_wording"},
                                headers=_auth(ids["teacher"])).json()["id"]
        assert client.post(f"/items/flags/{f_active}/resolve", json={"accept": True},
                           headers=_auth(ids["teacher"])).status_code == 403
        # le relecteur de contenu tient la file : il voit et tranche
        assert client.get("/items/flags", headers=_auth(ids["rev"])).status_code == 200
        r = client.post(f"/items/flags/{f_active}/resolve", json={"accept": True}, headers=_auth(ids["rev"]))
        assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["item"]["status"] == "quarantined"
        assert r.json()["resolved_by"] == str(ids["rev"])
        r = client.post(f"/items/flags/{f_pending}/resolve", json={"accept": True}, headers=_auth(ids["su"]))
        assert r.json()["item"]["status"] == "ai_generated"                # aucun raccourci
        assert client.post(f"/items/flags/{f_active}/resolve", json={"accept": False},
                           headers=_auth(ids["su"])).status_code == 400   # déjà tranché
        assert client.post(f"/items/flags/{uuid.uuid4()}/resolve", json={"accept": True},
                           headers=_auth(ids["su"])).status_code == 404
        assert client.get("/items/flags", headers=_auth(ids["su"])).json()["flags"] == []
        assert len(client.get("/items/flags?status=all", headers=_auth(ids["su"])).json()["flags"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_flag_survives_school_and_user_deletion():
    s = _session(); comp = _comp(s); it = _item(s, comp)
    school = School(name="A"); user = AppUser(email="t@x.io"); s.add_all([school, user]); s.flush()
    fl = review.flag_item(s, it, raised_by=user.id, reason=ItemFlagReason.OTHER, school_id=school.id); s.commit()
    s.delete(user); s.delete(school); s.commit(); s.expire_all()
    fl = s.get(ItemFlag, fl.id)
    assert fl is not None and fl.raised_by is None and fl.school_id is None   # SET NULL, pas de cascade


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests OK")
