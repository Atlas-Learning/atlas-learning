"""Tests Lot B — pipeline crosswalk : validateur B6 (ok/ko) + seed B2 idempotent.

Tourne sur SQLite en mémoire (modèles portables). En prod : Postgres Oracle UAE.
"""
import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from scripts.seed_crosswalk import CrosswalkSeedError
from scripts.seed_crosswalk import load_pivot as load_pivot_seed
from scripts.seed_crosswalk import seed as seed_crosswalk
from scripts.seed_referentiel import seed as seed_referentiel
from scripts.validate_crosswalk import (
    active_competencies_from_json,
    compute_synthesis,
    load_pivot,
    validate_crosswalk,
)
from scripts.validate_crosswalk import main as validate_main
from src.models.base import Base, CurriculumFramework
from src.models.curriculum import legacy_framework_id
from src.models.competency import Competency
from src.models.curriculum import CompetencyCurriculumMap, CurriculumStandard


def _fresh_session() -> Session:
    engine = create_engine("sqlite://")  # mémoire
    Base.metadata.create_all(engine)
    return Session(engine)


def _pivot() -> dict:
    return copy.deepcopy(load_pivot())


COMPETENCIES = active_competencies_from_json()


# --- Validateur B6 : cas OK ---

def test_validator_ok_on_real_pivot():
    # le pivot réconcilié livré passe les 5 règles sans erreur
    assert validate_crosswalk(load_pivot(), COMPETENCIES) == []


def test_validator_synthesis_is_computed():
    # R4 : le recalcul reproduit exactement le computed_synthesis du fichier
    pivot = load_pivot()
    synth = compute_synthesis(pivot["mappings"])
    # depuis la décision Q1 (2026-07-12) : #30/#31 [ccss] et #13 [uk] PARTIAL → PREREQ
    assert synth["CCSS_M"] == {"covered": 32, "EXACT": 18, "PARTIAL": 4, "ENRICH": 8, "PREREQ": 2}
    assert synth["UK_NC"] == {"covered": 32, "EXACT": 22, "PARTIAL": 6, "PREREQ": 1, "ENRICH": 3}
    assert synth["MOE_UAE"]["cognitive_levels"] == {"Applying": 18, "Knowing": 2, "Reasoning": 12}


# --- Validateur B6 : cas KO (une règle violée = au moins une erreur ciblée) ---

def test_r1_unmapped_active_competency_fails():
    pivot = _pivot()
    removed = pivot["mappings"].pop()  # une compétence active n'est plus mappée
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert any(e.startswith("R1") and removed["competency_code"] in e for e in errors)


def test_r2_residual_row_derivation_fails():
    pivot = _pivot()
    pivot["mappings"][0]["ccss_m"]["derivation"] = "row"
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert any(e.startswith("R2") and "'row'" in e for e in errors)


def test_r2_missing_alignment_type_fails():
    pivot = _pivot()
    del pivot["mappings"][0]["uk_nc"]["alignment"]
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert any(e.startswith("R2") and "alignment_type" in e for e in errors)


def test_r3_moe_cognitive_mismatch_without_note_fails():
    pivot = _pivot()
    # 2 = HALVES_QUARTERS : Knowing (RECALL), sans note d'override
    m = pivot["mappings"][1]
    assert not m["moe_uae"].get("cognitive_note")
    m["moe_uae"]["cognitive_level"] = "Reasoning"
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert any(e.startswith("R3") and m["competency_code"] in e for e in errors)


def test_r3_moe_cognitive_mismatch_with_note_is_override():
    pivot = _pivot()
    m = pivot["mappings"][1]
    m["moe_uae"]["cognitive_level"] = "Reasoning"
    m["moe_uae"]["cognitive_note"] = "override expert documenté (test)"
    # la synthèse doit rester calculée : on la recale pour isoler R3
    pivot["reconciliation"]["computed_synthesis"]["MOE_UAE"]["cognitive_levels"] = (
        compute_synthesis(pivot["mappings"])["MOE_UAE"]["cognitive_levels"]
    )
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert not any(e.startswith("R3") for e in errors)


def test_r4_hand_written_synthesis_fails():
    pivot = _pivot()
    pivot["reconciliation"]["computed_synthesis"]["CCSS_M"]["EXACT"] = 22  # saisi à la main
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert any(e.startswith("R4") and "CCSS_M" in e for e in errors)


def test_r5_bad_codes_fail():
    pivot = _pivot()
    pivot["mappings"][0]["ccss_m"]["standards"] = ["4.NF.A.1", "NF.4.A"]   # 2e invalide
    pivot["mappings"][0]["uk_nc"]["years"] = "Y7"                          # hors Y1-Y6
    pivot["mappings"][0]["moe_uae"]["grade_band"] = "Cycle1"               # pas une band
    errors = validate_crosswalk(pivot, COMPETENCIES)
    assert any(e.startswith("R5") and "NF.4.A" in e for e in errors)
    assert any(e.startswith("R5") and "Y7" in e for e in errors)
    assert any(e.startswith("R5") and "Cycle1" in e for e in errors)


def test_r5_tolerates_leafless_ccss_code():
    # "3.OA" (sans feuille) et "4.NF.B.3a" (sous-feuille) sont des codes réels
    pivot = load_pivot()
    codes = {c for m in pivot["mappings"] for c in m["ccss_m"]["standards"]}
    assert "3.OA" in codes and "4.NF.B.3a" in codes  # présents ET validés (0 erreur)


# --- Validateur B6 : CLI (la porte CI elle-même — build fail = exit ≠ 0) ---

def _run_cli(argv):
    # main() appelle toujours sys.exit : on capture code de sortie ET stdout
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["validate_crosswalk.py"] + argv
    try:
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit) as exc:
            validate_main()
    finally:
        sys.argv = old
    return exc.value.code, buf.getvalue()


def test_cli_exit_0_et_rapport_json_sur_le_pivot_reel():
    # mode CI (--json) : sortie machine-readable, exit 0 sur le pivot livré
    code, out = _run_cli(["--json"])
    assert code == 0
    report = json.loads(out)
    assert report["ok"] is True and report["errors"] == []
    assert report["competencies_active"] == len(COMPETENCIES)
    assert report["mappings"] == 32


def test_cli_exit_1_sur_pivot_invalide():
    # DoD B6 : compétence active non mappée = build fail (exit 1, erreur R1 affichée)
    pivot = _pivot()
    removed = pivot["mappings"].pop()   # R1 violée
    bad = Path(tempfile.mkdtemp()) / "pivot_invalide.json"
    bad.write_text(json.dumps(pivot), encoding="utf-8")
    code, out = _run_cli(["--pivot", str(bad)])
    assert code == 1
    assert "R1" in out and removed["competency_code"] in out


# --- Seed B2 ---

def test_seed_refuses_invalid_pivot():
    s = _fresh_session()
    seed_referentiel(s)
    pivot = _pivot()
    pivot["mappings"].pop()  # R1 violée
    try:
        seed_crosswalk(s, pivot)
        assert False, "le seed aurait dû refuser un pivot invalide"
    except CrosswalkSeedError:
        pass
    n = s.execute(select(func.count()).select_from(CurriculumStandard)).scalar_one()
    assert n == 0, "rien ne doit être inséré quand le validateur échoue"


def test_seed_refuses_without_active_competencies():
    s = _fresh_session()  # référentiel non seedé → aucune compétence active
    try:
        seed_crosswalk(s)
        assert False
    except CrosswalkSeedError:
        pass


def test_seed_counts_and_idempotence():
    s = _fresh_session()
    seed_referentiel(s)
    r1 = seed_crosswalk(s)
    n_std = s.execute(select(func.count()).select_from(CurriculumStandard)).scalar_one()
    n_map = s.execute(select(func.count()).select_from(CompetencyCurriculumMap)).scalar_one()
    assert n_std == r1["standards_total"] == 32   # 19 CCSS + 6 UK + 7 MoE
    assert n_map == r1["maps_total"] == 115       # 41 CCSS + 42 UK + 32 MoE
    # relance : mêmes comptes, zéro création
    r2 = seed_crosswalk(s)
    assert r2["standards_created"] == 0 and r2["maps_created"] == 0
    assert s.execute(select(func.count()).select_from(CurriculumStandard)).scalar_one() == n_std
    assert s.execute(select(func.count()).select_from(CompetencyCurriculumMap)).scalar_one() == n_map


def test_seed_upsert_propagates_pivot_mutation():
    # CRIT-2 (revue 2026-07-12) : reseeder APRÈS une correction du pivot doit
    # propager la mutation en base — l'insert-only l'ignorait silencieusement.
    from src.models.base import AlignmentType

    s = _fresh_session()
    seed_referentiel(s)
    seed_crosswalk(s)

    # mute un type d'alignement dans le pivot (#30 est PREREQ depuis Q1 → on le repasse PARTIAL)
    pivot = _pivot()
    m30 = next(m for m in pivot["mappings"]
               if m["competency_code"] == "MATH.G5.NF.IMPROPER_TO_MIXED")
    assert m30["ccss_m"]["alignment"] == "PREREQ"
    m30["ccss_m"]["alignment"] = "PARTIAL"
    # la synthèse est recalculée (sinon R4 refuse le pivot)
    from scripts.validate_crosswalk import compute_synthesis
    pivot["reconciliation"]["computed_synthesis"] = {
        **pivot["reconciliation"]["computed_synthesis"],
        **{k: v for k, v in compute_synthesis(pivot["mappings"]).items() if k != "MOE_UAE"},
    }

    r = seed_crosswalk(s, pivot)
    assert r["maps_updated"] >= 1 and r["maps_created"] == 0

    # la base reflète bien la mutation PARTIAL, pas l'ancien PREREQ
    comp = s.execute(select(Competency).where(
        Competency.code == "MATH.G5.NF.IMPROPER_TO_MIXED")).scalar_one()
    types = {
        mm.alignment_type
        for mm, in s.execute(
            select(CompetencyCurriculumMap)
            .join(CurriculumStandard,
                  CurriculumStandard.id == CompetencyCurriculumMap.standard_id)
            .where(CompetencyCurriculumMap.competency_id == comp.id,
                   CurriculumStandard.framework_id == legacy_framework_id("CCSS_M"))
        )
    }
    assert AlignmentType.PARTIAL in types and AlignmentType.PREREQ not in types


def test_seed_uk_range_maps_to_two_standards():
    # 'Y5-Y6' (ex. ADD_SAME_SIMPLIFY) → DEUX standards Y5 ET Y6 mappés
    s = _fresh_session()
    seed_referentiel(s)
    seed_crosswalk(s)
    comp = s.execute(
        select(Competency).where(Competency.code == "MATH.G4.NF.ADD_SAME_SIMPLIFY")
    ).scalar_one()
    uk_codes = {
        std.code
        for std, in s.execute(
            select(CurriculumStandard)
            .join(CompetencyCurriculumMap,
                  CompetencyCurriculumMap.standard_id == CurriculumStandard.id)
            .where(CompetencyCurriculumMap.competency_id == comp.id,
                   CurriculumStandard.framework_id == legacy_framework_id("UK_NC"))
        )
    }
    assert uk_codes == {"Y5", "Y6"}


def test_seed_moe_composed_key_and_labels():
    # MoE : clé composée 'NUM_OPS.{band}', jamais un pseudo-code inventé
    s = _fresh_session()
    seed_referentiel(s)
    seed_crosswalk(s)
    std = s.execute(
        select(CurriculumStandard).where(
            CurriculumStandard.framework_id == legacy_framework_id("MOE_UAE"),
            CurriculumStandard.code == "NUM_OPS.G4-G5",
        )
    ).scalar_one()
    assert std.label_en == "Numbers & Operations — Cycle 1 (G4-G5)"
    assert std.label_ar == "الأعداد والعمليات"
    assert std.grade_hint == "G4-G5"


def test_seed_ccss_one_standard_per_distinct_code():
    s = _fresh_session()
    seed_referentiel(s)
    seed_crosswalk(s)
    ccss = s.execute(
        select(CurriculumStandard.code).where(
            CurriculumStandard.framework_id == legacy_framework_id("CCSS_M")
        )
    ).scalars().all()
    pivot = load_pivot_seed()
    distinct = {c for m in pivot["mappings"] for c in m["ccss_m"]["standards"]}
    assert sorted(ccss) == sorted(distinct)   # un standard par code distinct, sans doublon


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)} tests OK")
