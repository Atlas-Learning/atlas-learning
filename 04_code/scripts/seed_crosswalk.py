"""Seed du crosswalk curriculaire (Lot B, B2) — pivot JSON → DB.

Porte d'entrée SÛRE : refuse de tourner si le validateur B6 (validate_crosswalk)
remonte la moindre erreur. Vrai UPSERT (revue 2026-07-12) : une clé existante est
MISE À JOUR (labels, type d'alignement, confiance, note), pas seulement créée si
absente — sinon une correction du pivot après confirmation experte ne serait jamais
propagée. Clés : (framework, code) pour les standards, (competency_id, standard_id)
pour les mappings.

Conventions de matérialisation (Cadrage-LotB §3/B2) :
- CCSS-M : un standard par code distinct cité ('4.NF.A.1', '3.OA', ...).
- UK NC : une plage 'Y5-Y6' est mappée vers DEUX standards Y5 ET Y6 (un standard
  = un year group ; la plage est une propriété du mapping, pas du standard).
- MoE UAE : pas de codes officiels publiés → clé composée 'NUM_OPS.{grade_band}',
  jamais un pseudo-code inventé (ligne rouge B2). Sans type d'alignement dans le
  pivot, le type retenu est BROADER (un domaine+band regroupe plusieurs
  compétences Atlas — Atlas plus fin), confiance = min(domaine, grade_band).

Pré-requis : le référentiel est seedé (scripts/seed_referentiel.py) — les
compétences actives doivent exister en base.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# rendre le package `src` importable quand le script est lancé directement
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.validate_crosswalk import (
    MOE_DOMAIN_KEYS,
    PIVOT_PATH,
    active_competencies_from_db,
    moe_composed_key,
    validate_crosswalk,
)
from src.models.base import (
    AlignmentType,
    CurriculumFramework,
    MappingConfidence,
    WeightSource,
)
from src.models.competency import Competency
from src.models.curriculum import CompetencyCurriculumMap, CurriculumStandard, ensure_legacy_frameworks


class CrosswalkSeedError(Exception):
    pass


def load_pivot(path: Path = PIVOT_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _note(entry: dict) -> Optional[str]:
    """Note du mapping = note du pivot + trace de réconciliation (audit B-0)."""
    parts = [p for p in (entry.get("note"), entry.get("reconciliation_note")) if p]
    return " ; ".join(parts) or None


def _standard_defs(pivot: dict) -> dict:
    """(framework, code) -> {label_en, label_ar, grade_hint} depuis le pivot.

    Le pivot ne porte pas les intitulés officiels par code (les descriptors sont
    des propriétés de mapping) : libellés d'affichage neutres, le code reste
    l'identité (B4 affiche le code + wording par type).
    """
    defs: dict = {}
    for m in pivot["mappings"]:
        for code in m["ccss_m"]["standards"]:
            defs[(CurriculumFramework.CCSS_M, code)] = {
                "label_en": f"CCSS-M {code}",
                "label_ar": f"CCSS-M {code}",   # les codes restent en notation latine (E7)
                "grade_hint": f"G{code.split('.')[0]}",
            }
        # plage UK 'Y5-Y6' → DEUX standards Y5 et Y6
        for year in m["uk_nc"]["years"].split("-"):
            defs[(CurriculumFramework.UK_NC, year)] = {
                "label_en": f"National Curriculum in England — Year {year[1:]}",
                "label_ar": f"المنهج الوطني الإنجليزي — السنة {year[1:]}",
                "grade_hint": year,
            }
        moe = m["moe_uae"]
        band = moe["grade_band"]
        defs[(CurriculumFramework.MOE_UAE, moe_composed_key(moe))] = {
            "label_en": f"Numbers & Operations — Cycle 1 ({band})",
            "label_ar": "الأعداد والعمليات",
            "grade_hint": band,
        }
    return defs


def _enrich_kind(entry: dict) -> Optional[str]:
    """enrich_kind du pivot, seulement si la ligne est ENRICH (M-4)."""
    return entry.get("enrich_kind") if entry.get("alignment") == "ENRICH" else None


def _map_defs(pivot: dict) -> list:
    """[(competency_code, framework, standard_code, alignment, confidence, note, enrich_kind)]."""
    rows = []
    for m in pivot["mappings"]:
        code = m["competency_code"]
        ccss = m["ccss_m"]
        for std in ccss["standards"]:
            rows.append((code, CurriculumFramework.CCSS_M, std,
                         AlignmentType(ccss["alignment"]),
                         MappingConfidence(ccss["confidence"]), _note(ccss), _enrich_kind(ccss)))
        uk = m["uk_nc"]
        for year in uk["years"].split("-"):
            rows.append((code, CurriculumFramework.UK_NC, year,
                         AlignmentType(uk["alignment"]),
                         MappingConfidence(uk["confidence"]), _note(uk), _enrich_kind(uk)))
        moe = m["moe_uae"]
        # confiance MoE = min(domaine, grade_band) : M tant que les bands sont estimés (B7)
        conf = m["moe_uae"]["confidence"]
        confidence = MappingConfidence.M if "M" in (conf["domain"], conf["grade_band"]) \
            else MappingConfidence.H
        note_parts = [f"strand={moe['strand']}", f"cognitif={moe['cognitive_level']}"]
        if moe.get("cognitive_note"):
            note_parts.append(moe["cognitive_note"])
        rows.append((code, CurriculumFramework.MOE_UAE, moe_composed_key(moe),
                     AlignmentType.BROADER, confidence, " ; ".join(note_parts), None))
    return rows


def seed(session: Session, pivot: dict | None = None) -> dict:
    """Insère/met à jour le crosswalk. Idempotent. Retourne un compte-rendu."""
    pivot = pivot or load_pivot()

    # porte sûre B6 : les compétences actives de CETTE base font foi
    competencies = active_competencies_from_db(session)
    errors = validate_crosswalk(pivot, competencies)
    if errors:
        raise CrosswalkSeedError(
            f"Validateur B6 : {len(errors)} erreur(s), seed refusé :\n  "
            + "\n  ".join(errors)
        )

    # --- upsert standards (clé = (framework, code)) ---
    # VRAI upsert (revue 2026-07-12, CRIT-2) : une clé existante est MISE À JOUR, pas
    # ignorée — sinon une correction du pivot (confirmation experte, Lot 1) ne serait
    # jamais propagée en base, silencieusement.
    # refonte C1 : les frameworks sont des lignes (publiées) ; clé = (framework_id, code)
    fw_by_key = ensure_legacy_frameworks(session)
    fw_id = {CurriculumFramework(k): fw.id for k, fw in fw_by_key.items()}
    existing_std = {
        (s.framework_id, s.code): s
        for s in session.execute(select(CurriculumStandard)).scalars()
    }
    s_created = s_updated = 0
    defs = _standard_defs(pivot)
    for (framework, code), attrs in defs.items():
        std = existing_std.get((fw_id[framework], code))
        if std is None:
            std = CurriculumStandard(framework_id=fw_id[framework], code=code, **attrs)
            session.add(std)
            existing_std[(fw_id[framework], code)] = std
            s_created += 1
        elif any(getattr(std, k) != v for k, v in attrs.items()):
            for k, v in attrs.items():
                setattr(std, k, v)
            s_updated += 1
    session.flush()

    # --- upsert mappings (clé = (competency_id, standard_id)) ---
    comp_by_code = {c.code: c.id for c in session.execute(select(Competency)).scalars()}
    existing_maps = {
        (mm.competency_id, mm.standard_id): mm
        for mm in session.execute(select(CompetencyCurriculumMap)).scalars()
    }
    m_created = m_updated = 0
    map_rows = _map_defs(pivot)
    for comp_code, framework, std_code, alignment, confidence, note, enrich_kind in map_rows:
        key = (comp_by_code[comp_code], existing_std[(fw_id[framework], std_code)].id)
        mm = existing_maps.get(key)
        if mm is None:
            mm = CompetencyCurriculumMap(
                competency_id=key[0],
                standard_id=key[1],
                alignment_type=alignment,
                confidence=confidence,
                note=note,
                enrich_kind=enrich_kind,
                weight_source=WeightSource.EXPERT,
                weight_version=1,
            )
            session.add(mm)
            existing_maps[key] = mm
            m_created += 1
        elif (mm.alignment_type, mm.confidence, mm.note, mm.enrich_kind) != \
                (alignment, confidence, note, enrich_kind):
            # un changement de type d'alignement incrémente la version (traçabilité B6)
            if mm.alignment_type != alignment:
                mm.weight_version += 1
            mm.alignment_type, mm.confidence, mm.note, mm.enrich_kind = \
                alignment, confidence, note, enrich_kind
            m_updated += 1
    session.commit()

    return {
        "standards_total": len(defs),
        "standards_created": s_created,
        "standards_updated": s_updated,
        "maps_total": len(map_rows),
        "maps_created": m_created,
        "maps_updated": m_updated,
    }


def main() -> None:
    """CLI : seed la DB pointée par DATABASE_URL (SQLite dev par défaut).

    Pré-requis : `alembic upgrade head` + seed_referentiel (compétences actives).
    """
    from src.db import SessionLocal, make_engine

    engine = make_engine()
    with SessionLocal(bind=engine) as session:
        report = seed(session)
    print("Seed crosswalk terminé :", report)


if __name__ == "__main__":
    main()
