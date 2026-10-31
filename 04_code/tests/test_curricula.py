"""Tests refonte C2 — curriculums dynamiques (écran O3) : import, suggestion déterministe,
revue, couverture, publication.

Les deux règles du spec :
- une ligne `suggested` n'est JAMAIS servie aux écoles ;
- la publication est refusée tant qu'un attendu n'est pas revu.
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

from src.api import curricula_service as cs
from src.api.app import app, get_db
from src.models import checkin, competency, curriculum, item, lesson, measurement, org, plan, session as _se  # noqa: F401
from src.models.audit import AuditLog
from src.models.base import (
    AlignmentType, Base, CompetencyStatus, FrameworkStatus, MappingConfidence, Role, Subject, WeightSource, utcnow,
)
from src.models.competency import Competency
from src.models.curriculum import CompetencyCurriculumMap, CurriculumFrameworkDef, CurriculumStandard, ensure_legacy_frameworks
from src.models.measurement import School, Student, StudentCompetencyAbility
from src.models.org import AppUser, Classroom, Membership, Organization, TeacherClassroom
from src.rbac.auth import make_token


def _comp(code, label, grade):
    return Competency(code=code, label_en=label, label_ar="x", subject=Subject.MATH, grade=grade,
                      difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)


STANDARDS = [
    {"code": "IB.4.F.1", "label_en": "Add and subtract fractions with like denominators", "grade_hint": "G4"},
    {"code": "IB.4.F.2", "label_en": "Compare fractions using benchmark fractions", "label_ar": "قارن الكسور", "grade_hint": "G4"},
    {"code": "IB.4.G.9", "label_en": "Classify quadrilaterals by their properties", "grade_hint": "G4"},
]


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    s = Session(bind=engine)
    ensure_legacy_frameworks(s)

    o = Organization(name="Org"); s.add(o); s.flush()
    sch = School(name="A", organization_id=o.id); s.add(sch); s.flush()
    c1 = Classroom(school_id=sch.id, name="4A", grade=4); s.add(c1); s.flush()

    add = _comp("M.ADD", "Add fractions with like denominators", 4)
    cmp_ = _comp("M.CMP", "Compare fractions with benchmarks", 4)
    eqv = _comp("M.EQV", "Equivalent fractions", 3)
    s.add_all([add, cmp_, eqv]); s.flush()

    st = Student(school_id=sch.id, classroom_id=c1.id); s.add(st); s.flush()
    for c in (add, cmp_, eqv):
        s.add(StudentCompetencyAbility(student_id=st.id, competency_id=c.id, school_id=sch.id, ability_elo=1700.0,
                                       n_direct=5, confidence=0.6, last_measured_at=utcnow()))

    teacher, ped, it_, sup = (AppUser(email=e) for e in ("t@x.io", "ped@x.io", "it@x.io", "ops@atlas.io"))
    s.add_all([teacher, ped, it_, sup]); s.flush()
    s.add_all([
        Membership(user_id=teacher.id, role=Role.TEACHER, school_id=sch.id),
        TeacherClassroom(user_id=teacher.id, classroom_id=c1.id),
        Membership(user_id=ped.id, role=Role.PED_ADMIN, organization_id=o.id, school_id=sch.id),
        Membership(user_id=it_.id, role=Role.IT_ADMIN, organization_id=o.id, school_id=sch.id),
        Membership(user_id=sup.id, role=Role.SUPER_ADMIN),
    ])
    s.commit()
    ids = dict(org=o.id, school=sch.id, student=st.id, teacher=teacher.id, ped=ped.id, it=it_.id, sup=sup.id,
               add=add.id, cmp=cmp_.id, eqv=eqv.id)
    app.dependency_overrides[get_db] = lambda: s
    return TestClient(app), ids, s


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _teardown():
    app.dependency_overrides.clear()


def _import(client, ids, **over):
    body = {"key": "IB_PYP", "name_en": "IB PYP maths", "name_ar": "آي بي", "country": "ae", "standards": STANDARDS}
    body.update(over)
    r = client.post("/ops/curricula", json=body, headers=_auth(ids["sup"]))
    assert r.status_code == 200, r.text
    return r.json()


def _std_id(cov, code):
    return next(x for x in cov["standards"] if x["code"] == code)["id"]


# ---------- RBAC : super admin uniquement ----------

def test_ops_curricula_super_admin_only():
    client, ids, s = _setup()
    for uid in (ids["teacher"], ids["ped"], ids["it"]):
        assert client.get("/ops/curricula", headers=_auth(uid)).status_code == 403
        assert client.post("/ops/curricula", json={"key": "X", "name_en": "x", "standards": STANDARDS},
                           headers=_auth(uid)).status_code == 403
    r = client.get("/ops/curricula", headers=_auth(ids["sup"]))
    assert r.status_code == 200
    assert [f["key"] for f in r.json()["frameworks"]] == ["CCSS_M", "UK_NC", "MOE_UAE"]
    assert all(f["status"] == "published" for f in r.json()["frameworks"])
    # aucune ligne n'a été créée par les 403
    assert s.execute(select(CurriculumFrameworkDef).where(CurriculumFrameworkDef.key == "X")).first() is None
    _teardown()


# ---------- import ----------

def test_import_creates_draft_with_deterministic_suggestions():
    client, ids, s = _setup()
    body = _import(client, ids)
    assert body["status"] == "draft" and body["key"] == "IB_PYP" and body["country"] == "AE"
    assert body["import"] == {"created": True, "standards_new": 3, "standards_updated": 0, "suggested": body["import"]["suggested"]}
    assert body["import"]["suggested"] >= 2          # les deux attendus « fractions » trouvent un candidat
    detail = client.get(f"/ops/curricula/{body['id']}", headers=_auth(ids["sup"])).json()
    cov = detail["coverage"]
    by_code = {x["code"]: x for x in cov["standards"]}
    assert by_code["IB.4.F.1"]["state"] == "suggested"
    assert by_code["IB.4.F.1"]["mappings"][0]["competency_code"] == "M.ADD"
    assert by_code["IB.4.F.1"]["mappings"][0]["suggested"] is True
    assert by_code["IB.4.F.1"]["mappings"][0]["alignment_type"] == "PARTIAL"
    # F.2 : M.CMP (meilleur score) et M.ADD (« fraction » + grade) proposées, max 2 par attendu, triées par code
    assert [m["competency_code"] for m in by_code["IB.4.F.2"]["mappings"]] == ["M.ADD", "M.CMP"]
    assert all(m["suggested"] for m in by_code["IB.4.F.2"]["mappings"])
    assert "M.EQV" not in {m["competency_code"] for x in cov["standards"] for m in x["mappings"]}  # G3 + 1 mot : sous le seuil
    assert by_code["IB.4.G.9"]["state"] == "unmapped"       # géométrie : aucun candidat ≥ seuil
    assert by_code["IB.4.F.2"]["label_ar"] == "قارن الكسور"
    assert by_code["IB.4.F.1"]["label_ar"] == by_code["IB.4.F.1"]["label_en"]   # pas d'AR → repli EN, jamais vide
    assert cov["counts"]["standards"] == 3 and cov["counts"]["reviewed"] == 0
    assert cov["publishable"] is False
    # aperçu du wording que verra l'école (même table que les vues)
    assert by_code["IB.4.F.1"]["mappings"][0]["preview_en"] == "covers part of IB.4.F.1 (indicative mapping)"
    entries = s.execute(select(AuditLog).where(AuditLog.action == "curriculum.import")).scalars().all()
    assert len(entries) == 1 and entries[0].user_id == ids["sup"] and entries[0].details["standards_new"] == 3
    _teardown()


def test_suggestion_is_deterministic_and_idempotent():
    client, ids, s = _setup()
    body = _import(client, ids)
    first = client.get(f"/ops/curricula/{body['id']}/mappings", headers=_auth(ids["sup"])).json()
    r = client.post(f"/ops/curricula/{body['id']}/suggest", headers=_auth(ids["sup"]))
    assert r.status_code == 200 and r.json()["suggested"] == 0       # rien de nouveau : ne duplique jamais
    second = client.get(f"/ops/curricula/{body['id']}/mappings", headers=_auth(ids["sup"])).json()
    assert [(x["code"], [m["competency_code"] for m in x["mappings"]]) for x in first["standards"]] == \
           [(x["code"], [m["competency_code"] for m in x["mappings"]]) for x in second["standards"]]
    # score : grade annoncé + lexique ; Year N (UK) ≈ Grade N−1
    add = s.get(Competency, ids["add"])
    st = CurriculumStandard(framework_id=uuid.uuid4(), code="x", label_en="Adding fractions, same denominator", label_ar="x", grade_hint="Y5")
    assert cs.score_match(st, add) == pytest.approx(4 + 1.5)      # add, fraction, same(≈like), denominator + grade exact
    st.grade_hint = "G6"
    assert cs.score_match(st, add) == pytest.approx(4 - 1.0)
    st.grade_hint = None
    assert cs.score_match(st, add) == pytest.approx(4.0)
    _teardown()


def test_import_csv_upserts_and_keeps_reviewed_lines():
    client, ids, s = _setup()
    body = _import(client, ids)
    cov = client.get(f"/ops/curricula/{body['id']}/mappings", headers=_auth(ids["sup"])).json()
    # on valide une ligne, puis on réimporte le même framework via CSV avec un libellé modifié + un code neuf
    r = client.put(f"/ops/curricula/{body['id']}/mappings", json={
        "standard_id": _std_id(cov, "IB.4.F.1"), "competency_id": str(ids["add"]),
        "alignment_type": "EXACT", "confidence": "H"}, headers=_auth(ids["sup"]))
    assert r.status_code == 200
    csv_text = ("﻿code,label_en,grade_hint\n"
                "IB.4.F.1,Add and subtract fractions with LIKE denominators,G4\n"
                "IB.4.F.2,Compare fractions using benchmark fractions,G4\n"
                "IB.4.G.9,Classify quadrilaterals by their properties,G4\n"
                "IB.5.F.3,Multiply a fraction by a whole number,G5\n"
                ",ligne vide ignorée,\n")
    body2 = _import(client, ids, standards=None, csv=csv_text)
    assert body2["id"] == body["id"]
    assert body2["import"]["created"] is False
    assert body2["import"]["standards_new"] == 1 and body2["import"]["standards_updated"] == 1
    cov2 = client.get(f"/ops/curricula/{body['id']}/mappings", headers=_auth(ids["sup"])).json()
    f1 = next(x for x in cov2["standards"] if x["code"] == "IB.4.F.1")
    assert f1["label_en"].endswith("LIKE denominators")
    m_add = next(m for m in f1["mappings"] if m["competency_code"] == "M.ADD")
    assert m_add["suggested"] is False and m_add["alignment_type"] == "EXACT"   # la revue survit au réimport
    # le CSV n'avait pas de colonne label_ar : l'arabe saisi n'est pas écrasé par le repli anglais
    f2 = next(x for x in cov2["standards"] if x["code"] == "IB.4.F.2")
    assert f2["label_ar"] == "قارن الكسور"
    # le nouvel attendu a reçu ses suggestions (et seulement lui : les autres gardent leurs lignes)
    f3 = next(x for x in cov2["standards"] if x["code"] == "IB.5.F.3")
    assert f3["state"] in ("suggested", "unmapped") and body2["import"]["suggested"] == len(f3["mappings"])
    assert any(x["code"] == "IB.5.F.3" for x in cov2["standards"])
    # CSV invalide
    r = client.post("/ops/curricula", json={"key": "BAD", "name_en": "x", "csv": "foo,bar\n1,2\n"}, headers=_auth(ids["sup"]))
    assert r.status_code == 400 and "en-tête" in r.json()["detail"]
    assert client.post("/ops/curricula", json={"key": "bad key!", "name_en": "x", "standards": STANDARDS},
                       headers=_auth(ids["sup"])).status_code == 400
    assert client.post("/ops/curricula", json={"key": "EMPTY", "name_en": "x", "standards": []},
                       headers=_auth(ids["sup"])).status_code == 400
    # import sur un framework publié : refusé
    assert client.post("/ops/curricula", json={"key": "CCSS_M", "name_en": "x", "standards": STANDARDS},
                       headers=_auth(ids["sup"])).status_code == 400
    _teardown()


# ---------- règle 1 : une ligne suggérée n'est jamais servie ----------

def test_suggested_lines_are_never_served_to_schools():
    client, ids, s = _setup()
    body = _import(client, ids)
    fw = s.get(CurriculumFrameworkDef, uuid.UUID(body["id"]))
    s.get(Organization, ids["org"]).curriculum_framework_id = fw.id
    s.commit()
    # brouillon → l'école reste en vue ATLAS
    prof = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    assert prof["curriculum_view"] == "ATLAS" if "curriculum_view" in prof else True
    assert all(c.get("standard") is None for c in prof["competencies"])
    # même publié de force (hors machine à états), les lignes suggérées ne sortent pas
    fw.status = FrameworkStatus.PUBLISHED; s.commit()
    prof = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    assert all(c.get("standard") is None for c in prof["competencies"])
    # validation d'une ligne → elle est servie, et seulement elle
    cov = client.get(f"/ops/curricula/{fw.id}/mappings", headers=_auth(ids["sup"])).json()
    client.put(f"/ops/curricula/{fw.id}/mappings", json={
        "standard_id": _std_id(cov, "IB.4.F.1"), "competency_id": str(ids["add"]),
        "alignment_type": "EXACT", "confidence": "H"}, headers=_auth(ids["sup"]))
    prof = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    by_code = {c["code"]: c for c in prof["competencies"]}
    assert by_code["M.ADD"]["standard"]["code"] == "IB.4.F.1"
    assert by_code["M.ADD"]["standard"]["framework"] == "IB_PYP"
    assert by_code["M.ADD"]["standard"]["wording_en"] == "aligned with IB.4.F.1"
    assert by_code["M.CMP"]["standard"] is None            # encore suggérée
    _teardown()


# ---------- revue ----------

def test_set_mapping_validations_and_no_match():
    client, ids, s = _setup()
    body = _import(client, ids)
    fw_id = body["id"]
    cov = client.get(f"/ops/curricula/{fw_id}/mappings", headers=_auth(ids["sup"])).json()
    f1, g9 = _std_id(cov, "IB.4.F.1"), _std_id(cov, "IB.4.G.9")
    H = _auth(ids["sup"])
    # ENRICH sans enrich_kind, type invalide, attendu d'un autre framework, compétence inconnue
    base = {"standard_id": f1, "competency_id": str(ids["add"]), "confidence": "H"}
    assert client.put(f"/ops/curricula/{fw_id}/mappings", json={**base, "alignment_type": "ENRICH"}, headers=H).status_code == 400
    assert client.put(f"/ops/curricula/{fw_id}/mappings", json={**base, "alignment_type": "NOPE"}, headers=H).status_code == 400
    assert client.put(f"/ops/curricula/{fw_id}/mappings", json={**base, "alignment_type": "EXACT", "competency_id": str(uuid.uuid4())}, headers=H).status_code == 400
    ccss = s.execute(select(CurriculumFrameworkDef).where(CurriculumFrameworkDef.key == "CCSS_M")).scalar_one()
    assert client.put(f"/ops/curricula/{ccss.id}/mappings", json={**base, "alignment_type": "EXACT"}, headers=H).status_code == 400
    assert client.get(f"/ops/curricula/{uuid.uuid4()}", headers=H).status_code == 404
    # ENRICH grade : aperçu « taught earlier »
    r = client.put(f"/ops/curricula/{fw_id}/mappings", json={**base, "alignment_type": "ENRICH", "enrich_kind": "grade",
                                                             "competency_id": str(ids["eqv"])}, headers=H)
    assert r.status_code == 200
    f1_row = next(x for x in r.json()["standards"] if x["code"] == "IB.4.F.1")
    enrich = next(m for m in f1_row["mappings"] if m["competency_code"] == "M.EQV")
    assert enrich["suggested"] is False and enrich["reviewed_by"] == str(ids["sup"]) and "earlier" in enrich["preview_en"]
    assert f1_row["state"] == "suggested"              # les lignes suggérées restent à trancher
    # supprimer chaque suggestion restante → attendu revu (une seule ligne validée suffit)
    for m in [m for m in f1_row["mappings"] if m["suggested"]]:
        r = client.request("DELETE", f"/ops/curricula/{fw_id}/mappings", json={"standard_id": f1, "competency_id": m["competency_id"]}, headers=H)
        assert r.status_code == 200
    assert next(x for x in r.json()["standards"] if x["code"] == "IB.4.F.1")["state"] == "reviewed"
    assert client.request("DELETE", f"/ops/curricula/{fw_id}/mappings", json={"standard_id": f1, "competency_id": str(ids["add"])}, headers=H).status_code == 404
    # sans correspondance : refusé si une ligne validée existe ; sinon purge les suggestions
    assert client.post(f"/ops/curricula/{fw_id}/no-match", json={"standard_id": f1}, headers=H).status_code == 400
    r = client.post(f"/ops/curricula/{fw_id}/no-match", json={"standard_id": g9}, headers=H)
    g9_row = next(x for x in r.json()["standards"] if x["code"] == "IB.4.G.9")
    assert g9_row["state"] == "reviewed" and g9_row["no_match"] is True and g9_row["mappings"] == []
    r = client.post(f"/ops/curricula/{fw_id}/no-match", json={"standard_id": g9, "no_match": False}, headers=H)
    assert next(x for x in r.json()["standards"] if x["code"] == "IB.4.G.9")["state"] == "unmapped"
    actions = {a for (a,) in s.execute(select(AuditLog.action)).all()}
    assert {"curriculum.map", "curriculum.unmap", "curriculum.no_match", "curriculum.reopen"} <= actions
    _teardown()


def test_validating_a_suggested_line_keeps_weight_version_then_bumps_on_change():
    client, ids, s = _setup()
    body = _import(client, ids)
    cov = client.get(f"/ops/curricula/{body['id']}/mappings", headers=_auth(ids["sup"])).json()
    f1 = _std_id(cov, "IB.4.F.1")
    H = _auth(ids["sup"])
    m = s.get(CompetencyCurriculumMap, (ids["add"], uuid.UUID(f1)))
    v0 = m.weight_version
    client.put(f"/ops/curricula/{body['id']}/mappings", json={"standard_id": f1, "competency_id": str(ids["add"]),
                                                              "alignment_type": "EXACT", "confidence": "H"}, headers=H)
    s.expire_all()
    m = s.get(CompetencyCurriculumMap, (ids["add"], uuid.UUID(f1)))
    assert m.weight_version == v0 and m.suggested is False       # valider une suggestion ≠ changer une ligne revue
    client.put(f"/ops/curricula/{body['id']}/mappings", json={"standard_id": f1, "competency_id": str(ids["add"]),
                                                              "alignment_type": "PARTIAL", "confidence": "H"}, headers=H)
    s.expire_all()
    assert s.get(CompetencyCurriculumMap, (ids["add"], uuid.UUID(f1))).weight_version == v0 + 1
    _teardown()


# ---------- règle 2 : publication refusée tant qu'un attendu n'est pas revu ----------

def test_publish_refused_until_every_standard_reviewed_then_unpublish_falls_back_to_atlas():
    client, ids, s = _setup()
    body = _import(client, ids)
    fw_id = body["id"]
    H = _auth(ids["sup"])
    s.get(Organization, ids["org"]).curriculum_framework_id = uuid.UUID(fw_id); s.commit()

    r = client.post(f"/ops/curricula/{fw_id}/publish", headers=H)
    assert r.status_code == 409 and "refusée" in r.json()["detail"]
    assert s.get(CurriculumFrameworkDef, uuid.UUID(fw_id)).status == FrameworkStatus.DRAFT

    cov = client.get(f"/ops/curricula/{fw_id}/mappings", headers=H).json()
    client.put(f"/ops/curricula/{fw_id}/mappings", json={"standard_id": _std_id(cov, "IB.4.F.1"), "competency_id": str(ids["add"]),
                                                         "alignment_type": "EXACT", "confidence": "H"}, headers=H)
    client.put(f"/ops/curricula/{fw_id}/mappings", json={"standard_id": _std_id(cov, "IB.4.F.2"), "competency_id": str(ids["cmp"]),
                                                         "alignment_type": "EXACT", "confidence": "M"}, headers=H)
    # une suggestion non tranchée sur chaque attendu « fractions » + la géométrie non revue → toujours refusé
    r = client.post(f"/ops/curricula/{fw_id}/publish", headers=H)
    assert r.status_code == 409 and "2 attendu(s) avec suggestions" in r.json()["detail"]
    cov = client.get(f"/ops/curricula/{fw_id}/mappings", headers=H).json()
    for x in cov["standards"]:
        for m in x["mappings"]:
            if m["suggested"]:
                client.request("DELETE", f"/ops/curricula/{fw_id}/mappings",
                               json={"standard_id": x["id"], "competency_id": m["competency_id"]}, headers=H)
    r = client.post(f"/ops/curricula/{fw_id}/publish", headers=H)
    assert r.status_code == 409 and "1 sans correspondance ni revue" in r.json()["detail"]
    client.post(f"/ops/curricula/{fw_id}/no-match", json={"standard_id": _std_id(cov, "IB.4.G.9")}, headers=H)
    short = client.get(f"/ops/curricula/{fw_id}/coverage", headers=H).json()
    assert "standards" not in short and short["publishable"] is True
    assert short["counts"] == {"standards": 3, "reviewed": 3, "suggested": 0, "unmapped": 0,
                               "competencies_mapped": 2, "competencies_total": 3}

    r = client.post(f"/ops/curricula/{fw_id}/publish", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["published_at"]
    assert r.json()["n_organizations"] == 1
    # l'école voit maintenant le framework ; le ped admin le lit dans /admin/curriculum
    assert client.get("/admin/curriculum", headers=_auth(ids["ped"])).json()["curriculum_view"] == "IB_PYP"
    prof = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    by_code = {c["code"]: c for c in prof["competencies"]}
    assert by_code["M.CMP"]["standard"]["wording_en"] == "aligned with IB.4.F.2 (indicative mapping)"
    assert by_code["M.EQV"]["standard"] is None

    # dépublication → retour à la vue neutre, sans toucher au choix de l'organisation
    r = client.post(f"/ops/curricula/{fw_id}/unpublish", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["published_at"] is None
    adm = client.get("/admin/curriculum", headers=_auth(ids["ped"])).json()
    assert adm["curriculum_view"] == "ATLAS" and adm["configured_view"] == "IB_PYP" and adm["configured_status"] == "draft"
    assert "IB_PYP" not in adm["available_frameworks"]
    assert s.get(Organization, ids["org"]).curriculum_framework_id == uuid.UUID(fw_id)
    prof = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    assert all(c.get("standard") is None for c in prof["competencies"])
    actions = [a for (a,) in s.execute(select(AuditLog.action).where(AuditLog.action.like("curriculum.%publish"))).all()]
    assert actions == ["curriculum.publish", "curriculum.unpublish"]
    _teardown()


def test_publish_refused_for_empty_framework():
    client, ids, s = _setup()
    fw = CurriculumFrameworkDef(key="EMPTY", name_en="e", name_ar="e", status=FrameworkStatus.DRAFT)
    s.add(fw); s.commit()
    assert client.post(f"/ops/curricula/{fw.id}/publish", headers=_auth(ids["sup"])).status_code == 409
    _teardown()


# ---------- suppression ----------

def test_delete_framework_guards_and_cascade():
    client, ids, s = _setup()
    body = _import(client, ids)
    fw_id = uuid.UUID(body["id"])
    H = _auth(ids["sup"])
    ccss = s.execute(select(CurriculumFrameworkDef).where(CurriculumFrameworkDef.key == "CCSS_M")).scalar_one()
    assert client.delete(f"/ops/curricula/{ccss.id}", headers=H).status_code == 409          # publié
    s.get(Organization, ids["org"]).curriculum_framework_id = fw_id; s.commit()
    assert client.delete(f"/ops/curricula/{fw_id}", headers=H).status_code == 409            # une org pointe dessus
    s.get(Organization, ids["org"]).curriculum_framework_id = None; s.commit()
    n_maps_before = len(s.execute(select(CompetencyCurriculumMap)).all())
    assert n_maps_before > 0
    r = client.delete(f"/ops/curricula/{fw_id}", headers=H)
    assert r.status_code == 200 and r.json()["deleted"] == str(fw_id)
    s.expire_all()
    assert s.get(CurriculumFrameworkDef, fw_id) is None
    assert s.execute(select(CurriculumStandard).where(CurriculumStandard.framework_id == fw_id)).first() is None
    assert s.execute(select(CompetencyCurriculumMap)).first() is None        # cascade attendus → lignes
    assert client.delete(f"/ops/curricula/{fw_id}", headers=H).status_code == 404
    _teardown()


# ---------- C3 : aperçu « ce que voit l'école », vocabulaire fermé côté serveur ----------

def test_preview_wording_follows_spec_vocabulary():
    client, ids, s = _setup()
    body = _import(client, ids)
    fw_id = body["id"]
    H = _auth(ids["sup"])
    cov = client.get(f"/ops/curricula/{fw_id}/mappings", headers=H).json()
    f1 = _std_id(cov, "IB.4.F.1")

    def pv(**q):
        return client.get(f"/ops/curricula/{fw_id}/preview", params={"standard_id": f1, **q}, headers=H)

    expected = {
        ("EXACT", "H", None): ("aligned with IB.4.F.1", "متوافق مع IB.4.F.1"),
        ("PARTIAL", "H", None): ("covers part of IB.4.F.1", "يغطي جزءًا من IB.4.F.1"),
        ("BROADER", "H", None): ("part of IB.4.F.1", "ضمن IB.4.F.1"),
        ("PREREQ", "H", None): ("prerequisite of IB.4.F.1", "متطلب سابق لـ IB.4.F.1"),
        ("ENRICH", "H", "grade"): ("taught earlier than in your curriculum (IB.4.F.1)", "يُدرَّس قبل موعده في منهجكم (IB.4.F.1)"),
        ("ENRICH", "H", "requirement"): ("beyond IB.4.F.1 expectations", "يتجاوز متطلبات IB.4.F.1"),
        ("EXACT", "M", None): ("aligned with IB.4.F.1 (indicative mapping)", "متوافق مع IB.4.F.1 (تعيين استرشادي)"),
    }
    for (at, conf, ek), (en, ar) in expected.items():
        q = {"alignment_type": at, "confidence": conf}
        if ek:
            q["enrich_kind"] = ek
        r = pv(**q)
        assert r.status_code == 200, r.text
        assert (r.json()["preview_en"], r.json()["preview_ar"]) == (en, ar), (at, conf, ek)
        assert "indicative mapping" not in r.json()["preview_ar"]          # jamais d'anglais dans la chaîne RTL
    assert pv(alignment_type="ENRICH", confidence="H").status_code == 400
    assert pv(alignment_type="NOPE", confidence="H").status_code == 400
    assert client.get(f"/ops/curricula/{fw_id}/preview", params={"standard_id": str(uuid.uuid4()), "alignment_type": "EXACT",
                      "confidence": "H"}, headers=H).status_code == 400
    assert client.get(f"/ops/curricula/{fw_id}/preview", params={"standard_id": f1, "alignment_type": "EXACT",
                      "confidence": "H"}, headers=_auth(ids["ped"])).status_code == 403
    # l'aperçu enregistré (mapping_payload) et l'aperçu à blanc viennent du même helper
    client.put(f"/ops/curricula/{fw_id}/mappings", json={"standard_id": f1, "competency_id": str(ids["add"]),
                                                         "alignment_type": "PREREQ", "confidence": "H"}, headers=H)
    cov = client.get(f"/ops/curricula/{fw_id}/mappings", headers=H).json()
    m = next(m for m in next(x for x in cov["standards"] if x["code"] == "IB.4.F.1")["mappings"] if m["competency_code"] == "M.ADD")
    assert m["preview_en"] == "prerequisite of IB.4.F.1"
    _teardown()
