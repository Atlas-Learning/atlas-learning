"""Tests Lot B — B3 (console /admin/curriculum), B4 (badges standards), B5 (couverture).

Fixtures directes (standards + mappings en base) plutôt que scripts/seed_crosswalk :
on teste la mécanique des vues, pas le pivot réel (couvert par test_crosswalk_pipeline).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import app, get_db
from src.models import competency, curriculum, item, measurement, org, session as _se  # noqa: F401
from src.models.audit import AuditLog
from src.models.base import (
    AlignmentType,
    Base,
    CompetencyStatus,
    CurriculumFramework,
    CurriculumView,
    EdgeType,
    MappingConfidence,
    Role,
    Subject,
    WeightSource,
    utcnow,
)
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.curriculum import (
    CompetencyCurriculumMap, CurriculumStandard, ensure_legacy_frameworks, legacy_framework_id,
)
from src.models.measurement import School, Student, StudentCompetencyAbility
from src.models.org import AppUser, Classroom, Membership, Organization, ParentStudent, TeacherClassroom
from src.rbac.auth import make_token


def _comp(code):
    return Competency(code=code, label_en=code, label_ar="x", subject=Subject.MATH, grade=4,
                      difficulty_prior=1500.0, status=CompetencyStatus.ACTIVE)


def _ability(student_id, comp_id, school_id, elo):
    return StudentCompetencyAbility(student_id=student_id, competency_id=comp_id, school_id=school_id,
                                    ability_elo=elo, n_direct=5, confidence=0.5,
                                    last_measured_at=utcnow())


def _std(framework, code):
    return CurriculumStandard(framework_id=legacy_framework_id(framework.value), code=code,
                              label_en=f"label {code}", label_ar=f"ar {code}", grade_hint="G4")


def _map(comp, std, alignment, confidence=MappingConfidence.H, enrich_kind=None):
    return CompetencyCurriculumMap(competency_id=comp.id, standard_id=std.id,
                                   alignment_type=alignment, confidence=confidence,
                                   enrich_kind=enrich_kind,
                                   weight_source=WeightSource.EXPERT, weight_version=1)


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    s = Session(bind=engine)

    ensure_legacy_frameworks(s)   # refonte C1 : frameworks en table (publiés)
    o = Organization(name="Org")  # curriculum_framework_id = NULL → vue ATLAS (défaut)
    s.add(o); s.flush()
    sa_ = School(name="A", organization_id=o.id); s.add(sa_); s.flush()
    c1 = Classroom(school_id=sa_.id, name="4A"); s.add(c1); s.flush()

    # chaîne A(root) <- B <- C ; D indépendant (même graphe que test_views)
    A, B, C, D = _comp("M.A"), _comp("M.B"), _comp("M.C"), _comp("M.D")
    s.add_all([A, B, C, D]); s.flush()
    s.add(CompetencyPrerequisite(source_id=B.id, target_id=C.id, edge_type=EdgeType.HARD,
                                 correlation_strength=0.8, weight_source=WeightSource.EXPERT))
    s.add(CompetencyPrerequisite(source_id=A.id, target_id=B.id, edge_type=EdgeType.HARD,
                                 correlation_strength=0.8, weight_source=WeightSource.EXPERT))

    # cohorte : A et D maîtrisés (1800/1600), B et C non (1200) — cause racine = B
    students = []
    for _ in range(3):
        st = Student(school_id=sa_.id, classroom_id=c1.id); s.add(st); s.flush(); students.append(st)
        s.add_all([_ability(st.id, A.id, sa_.id, 1800), _ability(st.id, B.id, sa_.id, 1200),
                   _ability(st.id, C.id, sa_.id, 1200), _ability(st.id, D.id, sa_.id, 1600)])

    # crosswalk CCSS-M :
    #  S1 4.NF.A.1 : EXACT(A) + EXACT(D), tous deux maîtrisés  → covered=True
    #  S2 4.NF.B.3 : EXACT(B, non maîtrisé) + PARTIAL(A)       → covered=False (1/2)
    #  S3 4.NF.B.4 : PARTIAL(D) seul, maîtrisé                 → covered=False (PARTIAL jamais seul)
    #  S4 4.NF.C.5 : EXACT(C) confiance M                      → suffixe indicatif
    s1 = _std(CurriculumFramework.CCSS_M, "4.NF.A.1")
    s2 = _std(CurriculumFramework.CCSS_M, "4.NF.B.3")
    s3 = _std(CurriculumFramework.CCSS_M, "4.NF.B.4")
    s4 = _std(CurriculumFramework.CCSS_M, "4.NF.C.5")
    suk = _std(CurriculumFramework.UK_NC, "Y5")   # autre framework : ne doit JAMAIS fuir en vue CCSS_M
    s.add_all([s1, s2, s3, s4, suk]); s.flush()
    s.add_all([
        _map(A, s1, AlignmentType.EXACT), _map(D, s1, AlignmentType.EXACT),
        _map(B, s2, AlignmentType.EXACT), _map(A, s2, AlignmentType.PARTIAL),
        _map(D, s3, AlignmentType.PARTIAL),
        _map(C, s4, AlignmentType.EXACT, MappingConfidence.M),
        _map(A, suk, AlignmentType.EXACT),
    ])

    teacher = AppUser(email="t@x.io"); parent = AppUser(email="p@x.io")
    it_admin = AppUser(email="it@x.io"); ped_admin = AppUser(email="ped@x.io")
    super_admin = AppUser(email="ops@atlas.io")
    s.add_all([teacher, parent, it_admin, ped_admin, super_admin]); s.flush()
    s.add_all([
        Membership(user_id=teacher.id, role=Role.TEACHER, school_id=sa_.id),
        TeacherClassroom(user_id=teacher.id, classroom_id=c1.id),
        Membership(user_id=parent.id, role=Role.PARENT, school_id=sa_.id),
        ParentStudent(user_id=parent.id, student_id=students[0].id),
        Membership(user_id=it_admin.id, role=Role.IT_ADMIN, organization_id=o.id, school_id=sa_.id),
        Membership(user_id=ped_admin.id, role=Role.PED_ADMIN, organization_id=o.id, school_id=sa_.id),
        Membership(user_id=super_admin.id, role=Role.SUPER_ADMIN),
    ])
    s.commit()

    ids = dict(org=o.id, school=sa_.id, c1=c1.id, student=students[0].id,
               teacher=teacher.id, parent=parent.id, it_admin=it_admin.id, ped_admin=ped_admin.id,
               super_admin=super_admin.id)
    app.dependency_overrides[get_db] = lambda: s
    return TestClient(app), ids, s


def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _set_view(s, org_id, view):
    s.get(Organization, org_id).curriculum_framework_id = (
        None if view == CurriculumView.ATLAS else legacy_framework_id(view.value))
    s.commit()


def _teardown():
    app.dependency_overrides.clear()


# ---------- B3 : endpoint /admin/curriculum (RBAC, audit, validation) ----------

def test_admin_curriculum_rbac_403_teacher_parent():
    client, ids, _ = _setup()
    for uid in (ids["teacher"], ids["parent"]):
        assert client.get("/admin/curriculum", headers=_auth(uid)).status_code == 403
        r = client.post("/admin/curriculum", json={"curriculum_view": "CCSS_M"}, headers=_auth(uid))
        assert r.status_code == 403
    _teardown()


def test_admin_curriculum_get_current_view_and_frameworks():
    client, ids, _ = _setup()
    for uid in (ids["it_admin"], ids["ped_admin"]):   # IT et ped admin : tous deux autorisés
        r = client.get("/admin/curriculum", headers=_auth(uid))
        assert r.status_code == 200
        body = r.json()
        assert body["curriculum_view"] == "ATLAS"
        assert body["available_frameworks"] == ["ATLAS", "CCSS_M", "UK_NC", "MOE_UAE"]
    _teardown()


def test_admin_curriculum_set_view_is_super_admin_only():
    # Refonte (Q14, 2026-10-31) : le choix du curriculum est une opération Atlas. Les admins de
    # l'école le lisent (GET, test ci-dessus) mais ne le changent pas.
    client, ids, s = _setup()
    for uid in (ids["it_admin"], ids["ped_admin"]):
        r = client.post("/admin/curriculum", json={"curriculum_view": "CCSS_M"}, headers=_auth(uid))
        assert r.status_code == 403
    assert s.get(Organization, ids["org"]).curriculum_framework_id is None  # inchangé


def test_admin_curriculum_set_view_persists_and_audits():
    client, ids, s = _setup()
    # Le super admin n'a pas de membership d'organisation : il nomme le tenant visé.
    assert client.post("/admin/curriculum", json={"curriculum_view": "CCSS_M"},
                       headers=_auth(ids["super_admin"])).status_code == 400
    r = client.post(f"/admin/curriculum?organization_id={ids['org']}",
                    json={"curriculum_view": "CCSS_M"}, headers=_auth(ids["super_admin"]))
    assert r.status_code == 200 and r.json()["curriculum_view"] == "CCSS_M"
    assert s.get(Organization, ids["org"]).curriculum_framework_id == legacy_framework_id("CCSS_M")
    entries = s.execute(select(AuditLog).where(AuditLog.action == "curriculum.set_view")).scalars().all()
    assert len(entries) == 1
    assert entries[0].user_id == ids["super_admin"]
    assert entries[0].details["curriculum_view"] == "CCSS_M"
    _teardown()


def test_admin_curriculum_rejects_unknown_framework():
    client, ids, s = _setup()
    r = client.post(f"/admin/curriculum?organization_id={ids['org']}",
                    json={"curriculum_view": "IB_PYP"}, headers=_auth(ids["super_admin"]))
    assert r.status_code == 400
    assert s.get(Organization, ids["org"]).curriculum_framework_id is None  # inchangé
    _teardown()


# ---------- B4 : vue ATLAS = payloads strictement inchangés ----------

# clés EXACTES des payloads d'AVANT le Lot B (contrat de non-régression : en vue
# ATLAS, aucun champ ne doit apparaître — même avec un crosswalk seedé en base)
PROFILE_COMP_KEYS = {"code", "label_en", "label_ar", "grade", "strand", "ability_elo",
                     "confidence", "n_direct", "measured", "mastered"}
GAP_KEYS = {"root_cause", "label", "root_cause_label_en", "root_cause_label_ar",
            "gap_label_en", "gap_label_ar", "is_self", "student_count", "diagnosis"}
EMERGING_KEYS = GAP_KEYS - {"label", "diagnosis"}
OVERVIEW_COMP_KEYS = {"code", "label", "mean_ability", "mastery_rate", "n_measured"}


def test_atlas_view_payload_keys_strictement_identiques_a_avant():
    # plus fort que l'absence de `standard` : l'ensemble de clés est figé à l'existant
    client, ids, _ = _setup()   # crosswalk EN BASE mais vue ATLAS → invisible
    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    assert profile["competencies"] and all(set(c) == PROFILE_COMP_KEYS for c in profile["competencies"])
    gaps = client.get(f"/classrooms/{ids['c1']}/gaps", headers=_auth(ids["teacher"])).json()["gaps"]
    assert gaps and all(set(g) == GAP_KEYS for g in gaps)
    digest = client.get(f"/classrooms/{ids['c1']}/digest", headers=_auth(ids["teacher"])).json()
    assert set(digest["top_priority"]) == GAP_KEYS
    assert digest["emerging_gaps"] and all(set(g) == EMERGING_KEYS for g in digest["emerging_gaps"])
    overview = client.get(f"/schools/{ids['school']}/overview", headers=_auth(ids["ped_admin"])).json()
    assert overview["competencies"] and all(set(c) == OVERVIEW_COMP_KEYS for c in overview["competencies"])
    _teardown()


def test_atlas_view_payloads_have_no_standard_fields():
    client, ids, _ = _setup()
    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    assert all("standard" not in c and "standards" not in c for c in profile["competencies"])
    gaps = client.get(f"/classrooms/{ids['c1']}/gaps", headers=_auth(ids["teacher"])).json()["gaps"]
    assert gaps and all("standard" not in g for g in gaps)
    overview = client.get(f"/schools/{ids['school']}/overview", headers=_auth(ids["ped_admin"])).json()
    assert all("standard" not in c for c in overview["competencies"])
    proof = client.get(f"/schools/{ids['school']}/proof", headers=_auth(ids["ped_admin"])).json()
    assert "curriculum_coverage" not in proof
    _teardown()


# ---------- B4 : vue CCSS_M = badges + wording des tables du cadrage ----------

def test_ccss_view_profile_badges_wording_and_specific_first():
    client, ids, s = _setup()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)
    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    by_code = {c["code"]: c for c in profile["competencies"]}

    a = by_code["M.A"]  # mappée sur 2 standards : EXACT d'abord (le plus spécifique)
    assert a["standard"]["code"] == "4.NF.A.1"
    assert a["standard"]["framework"] == "CCSS_M"
    assert a["standard"]["alignment_type"] == "EXACT"
    assert a["standard"]["wording_en"] == "aligned to 4.NF.A.1"
    assert a["standard"]["wording_ar"] == "متوافق مع 4.NF.A.1"
    assert [x["code"] for x in a["standards"]] == ["4.NF.A.1", "4.NF.B.3"]
    assert a["standards"][1]["wording_en"] == "covers part of 4.NF.B.3"
    assert a["standards"][1]["wording_ar"] == "يغطي جزءًا من 4.NF.B.3"
    # le standard UK (Y5) mappé sur M.A ne fuit pas dans la vue CCSS_M
    assert all(x["framework"] == "CCSS_M" for x in a["standards"])

    b = by_code["M.B"]
    assert b["standard"]["wording_en"] == "aligned to 4.NF.B.3"
    d = by_code["M.D"]
    assert [x["code"] for x in d["standards"]] == ["4.NF.A.1", "4.NF.B.4"]
    _teardown()


def test_confidence_m_adds_indicative_suffix():
    client, ids, s = _setup()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)
    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    c = next(x for x in profile["competencies"] if x["code"] == "M.C")
    assert c["standard"]["wording_en"] == "aligned to 4.NF.C.5 (indicative mapping)"
    # MAJ-2 : le suffixe AR est en arabe, pas d'anglais LTR injecté dans une chaîne RTL
    assert c["standard"]["wording_ar"].endswith(" (تعيين استرشادي)")
    assert "indicative mapping" not in c["standard"]["wording_ar"]
    _teardown()


def test_ccss_view_class_gaps_and_digest_root_cause_badged():
    client, ids, s = _setup()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)
    gaps = client.get(f"/classrooms/{ids['c1']}/gaps", headers=_auth(ids["teacher"])).json()["gaps"]
    assert gaps[0]["root_cause"] == "M.B"
    assert gaps[0]["standard"]["code"] == "4.NF.B.3"
    assert gaps[0]["standard"]["wording_en"] == "aligned to 4.NF.B.3"

    digest = client.get(f"/classrooms/{ids['c1']}/digest", headers=_auth(ids["teacher"])).json()
    assert digest["top_priority"]["standard"]["code"] == "4.NF.B.3"
    assert digest["emerging_gaps"] and all("standard" in g for g in digest["emerging_gaps"])
    _teardown()


def test_ccss_view_school_overview_standard_column():
    client, ids, s = _setup()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)
    overview = client.get(f"/schools/{ids['school']}/overview", headers=_auth(ids["ped_admin"])).json()
    by_code = {c["code"]: c for c in overview["competencies"]}
    assert by_code["M.A"]["standard"]["code"] == "4.NF.A.1"
    assert by_code["M.B"]["standard"]["alignment_type"] == "EXACT"
    assert all("standards" in c for c in overview["competencies"])
    _teardown()


# ---------- B5 : agrégation « couverture d'un standard » (rapport école) ----------

def test_coverage_covered_only_if_all_exact_mastered():
    client, ids, s = _setup()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)
    proof = client.get(f"/schools/{ids['school']}/proof", headers=_auth(ids["ped_admin"])).json()
    cov = proof["curriculum_coverage"]
    assert cov["framework"] == "CCSS_M"
    by_code = {x["code"]: x for x in cov["standards"]}

    # CCSS a des mappings EXACT → le verdict « covered » est affiché
    assert cov["shows_covered"] is True
    assert cov["coverage_threshold"] == 0.8
    # cas limite couvert : TOUTES les compétences EXACT (A, D) maîtrisées
    assert by_code["4.NF.A.1"] == {"code": "4.NF.A.1", "display_code": "4.NF.A.1",
                                   "label": "label 4.NF.A.1", "label_ar": "ar 4.NF.A.1",
                                   "mastered_count": 2, "total": 2, "covered": True}
    # cas limite non couvert : l'EXACT (B) n'est pas maîtrisé, même si la PARTIAL (A) l'est
    assert by_code["4.NF.B.3"]["mastered_count"] == 1
    assert by_code["4.NF.B.3"]["total"] == 2
    assert by_code["4.NF.B.3"]["covered"] is False
    # EXACT confiance M, non maîtrisé
    assert by_code["4.NF.C.5"]["covered"] is False
    # aucun « meets » individuel : la couverture n'existe qu'agrégée au rapport école
    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    assert "meets" not in str(profile)
    _teardown()


def test_enrich_grade_vs_requirement_wording():
    # M-4 (décision 2026-07-12) : un ENRICH-de-grade dit « taught earlier than »
    # (un argument), un ENRICH-d'exigence dit « beyond … expectations ».
    from src.models.competency import Competency
    from src.models.curriculum import CurriculumStandard
    client, ids, s = _setup()
    grade_std = _std(CurriculumFramework.CCSS_M, "5.NF.A.1")     # Atlas mesure plus tôt
    req_std = _std(CurriculumFramework.CCSS_M, "6.NS.B.4")        # exigence absente en CCSS
    s.add_all([grade_std, req_std]); s.flush()
    a = s.execute(select(Competency).where(Competency.code == "M.A")).scalar_one()
    s.add_all([
        _map(a, grade_std, AlignmentType.ENRICH, enrich_kind="grade"),
        _map(a, req_std, AlignmentType.ENRICH, enrich_kind="requirement"),
    ])
    s.commit()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)

    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    a_comp = next(x for x in profile["competencies"] if x["code"] == "M.A")
    wordings = {std["code"]: std for std in a_comp["standards"]}
    assert wordings["5.NF.A.1"]["wording_en"] == "taught earlier than 5.NF.A.1"
    assert wordings["5.NF.A.1"]["wording_ar"] == "يُدرَّس قبل 5.NF.A.1"
    assert wordings["6.NS.B.4"]["wording_en"] == "beyond 6.NS.B.4 expectations"
    _teardown()


def test_coverage_moe_view_has_no_covered_verdict():
    # CRIT-3b : MoE n'a aucun mapping EXACT → pas de verdict « couvert » (sinon
    # colonne toujours fausse). display_code null (jamais de pseudo-code affiché).
    client, ids, s = _setup()
    # mappe une compétence maîtrisée (A) sur un standard MoE composé, type BROADER
    from src.models.curriculum import (
    CompetencyCurriculumMap, CurriculumStandard, ensure_legacy_frameworks, legacy_framework_id,
)
    from src.models.competency import Competency
    moe = CurriculumStandard(framework_id=legacy_framework_id("MOE_UAE"), code="NUM_OPS.G4",
                             label_en="Numbers & Operations — Cycle 1 (G4)",
                             label_ar="الأعداد والعمليات", grade_hint="G4")
    s.add(moe); s.flush()
    a = s.execute(select(Competency).where(Competency.code == "M.A")).scalar_one()
    s.add(CompetencyCurriculumMap(competency_id=a.id, standard_id=moe.id,
                                  alignment_type=AlignmentType.BROADER,
                                  confidence=MappingConfidence.M,
                                  weight_source=WeightSource.EXPERT, weight_version=1))
    s.commit()
    _set_view(s, ids["org"], CurriculumView.MOE_UAE)

    proof = client.get(f"/schools/{ids['school']}/proof", headers=_auth(ids["ped_admin"])).json()
    cov = proof["curriculum_coverage"]
    assert cov["framework"] == "MOE_UAE"
    assert cov["shows_covered"] is False
    std = next(x for x in cov["standards"] if x["code"] == "NUM_OPS.G4")
    assert std["covered"] is None           # pas de verdict
    assert std["display_code"] is None      # jamais de pseudo-code affiché

    # le badge de profil, en vue MoE, ne porte pas de code affichable et ne dit pas « within {code} »
    profile = client.get(f"/students/{ids['student']}/profile", headers=_auth(ids["teacher"])).json()
    a_comp = next(x for x in profile["competencies"] if x["code"] == "M.A")
    assert a_comp["standard"]["display_code"] is None
    assert "NUM_OPS" not in a_comp["standard"]["wording_en"]
    assert "NUM_OPS" not in a_comp["standard"]["wording_ar"]
    _teardown()


def test_coverage_partial_alone_never_covers():
    client, ids, s = _setup()
    _set_view(s, ids["org"], CurriculumView.CCSS_M)
    proof = client.get(f"/schools/{ids['school']}/proof", headers=_auth(ids["ped_admin"])).json()
    by_code = {x["code"]: x for x in proof["curriculum_coverage"]["standards"]}
    # 4.NF.B.4 : seule mappée = PARTIAL(D) MAÎTRISÉE → k/n = 1/1 mais jamais covered
    assert by_code["4.NF.B.4"]["mastered_count"] == 1
    assert by_code["4.NF.B.4"]["total"] == 1
    assert by_code["4.NF.B.4"]["covered"] is False
    _teardown()
