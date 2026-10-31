"""Curriculums dynamiques (refonte C2, écran O3) — import, suggestion, revue, couverture,
publication. Logique testable sans HTTP ; super admin uniquement côté API.

Règles :
- une ligne de mapping `suggested` (proposée par la machine, non revue) n'est JAMAIS servie aux
  écoles (filtre dans views_service) ;
- la publication est refusée tant qu'un attendu n'est pas revu : chaque attendu doit avoir
  toutes ses lignes validées, ou être marqué « sans correspondance » ;
- un framework non publié = vue ATLAS pour les écoles qui l'auraient choisi ;
- l'import est un upsert d'attendus (clé = code) sur un framework en brouillon ; les lignes de
  mapping existantes sont conservées.

La suggestion est DÉTERMINISTE (pas de LLM) : niveau annoncé par l'attendu vs grade de la
compétence, et recouvrement lexical des libellés anglais (avec un petit lexique de synonymes du
domaine fractions). Elle propose, l'humain tranche.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api import views_service as vs
from src.audit import log_action
from src.models.base import AlignmentType, FrameworkStatus, MappingConfidence, WeightSource, utcnow
from src.models.competency import Competency
from src.models.curriculum import CompetencyCurriculumMap, CurriculumFrameworkDef, CurriculumStandard
from src.models.org import Organization


class CurriculaError(ValueError):
    pass


# --- import --------------------------------------------------------------------------------

def parse_standards_csv(text: str) -> List[dict]:
    """CSV `code,label_en[,label_ar][,grade_hint]` (en-tête obligatoire)."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows or "code" not in rows[0] or "label_en" not in rows[0]:
        raise CurriculaError("CSV : en-tête `code,label_en[,label_ar][,grade_hint]` attendu")
    out = []
    for r in rows:
        code = (r.get("code") or "").strip()
        if not code:
            continue
        out.append({"code": code, "label_en": (r.get("label_en") or "").strip() or code,
                    "label_ar": (r.get("label_ar") or "").strip() or None,
                    "grade_hint": (r.get("grade_hint") or "").strip() or None})
    if not out:
        raise CurriculaError("CSV : aucun attendu")
    return out


def import_framework(s: Session, *, key: str, name_en: str, name_ar: Optional[str], country: Optional[str],
                     source_note: Optional[str], standards: List[dict], by: Optional[uuid.UUID],
                     suggest: bool = True) -> Tuple[CurriculumFrameworkDef, dict]:
    """Crée ou complète (brouillon) un framework et ses attendus ; propose des mappings pour les
    attendus nouveaux. Ne commit pas."""
    key = (key or "").strip().upper().replace(" ", "_")
    if not re.fullmatch(r"[A-Z0-9_\-]{2,40}", key):
        raise CurriculaError("clé de framework : lettres, chiffres, _ ou -, 2 à 40 caractères")
    if not standards:
        raise CurriculaError("aucun attendu à importer")
    fw = s.execute(select(CurriculumFrameworkDef).where(CurriculumFrameworkDef.key == key)).scalar_one_or_none()
    created = fw is None
    if fw is None:
        fw = CurriculumFrameworkDef(key=key, name_en=(name_en or key).strip(), name_ar=(name_ar or name_en or key).strip(),
                                    country=(country or "").strip().upper()[:2] or None, source_note=source_note,
                                    status=FrameworkStatus.DRAFT)
        s.add(fw); s.flush()
    elif fw.status == FrameworkStatus.PUBLISHED:
        raise CurriculaError("framework publié : dépublier avant de réimporter")
    else:
        fw.name_en, fw.name_ar = (name_en or fw.name_en).strip(), (name_ar or fw.name_ar).strip()
        if country:
            fw.country = country.strip().upper()[:2]
        if source_note:
            fw.source_note = source_note
    existing = {st.code: st for st in s.execute(select(CurriculumStandard).where(
        CurriculumStandard.framework_id == fw.id)).scalars()}
    n_new = n_upd = 0
    new_ids = []
    seen = set()
    for row in standards:
        code = (row.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        label_en = (row.get("label_en") or code).strip()
        st = existing.get(code)
        # champs optionnels absents du fichier : on ne perd jamais une valeur déjà saisie
        # (un CSV sans colonne label_ar ne doit pas écraser l'arabe par le repli anglais)
        label_ar = (row.get("label_ar") or (st.label_ar if st is not None else label_en)).strip()
        hint = (row.get("grade_hint") or (st.grade_hint if st is not None else None)) or None
        if st is None:
            st = CurriculumStandard(framework_id=fw.id, code=code, label_en=label_en, label_ar=label_ar, grade_hint=hint)
            s.add(st); s.flush(); existing[code] = st; new_ids.append(st.id); n_new += 1
        elif (st.label_en, st.label_ar, st.grade_hint) != (label_en, label_ar, hint):
            st.label_en, st.label_ar, st.grade_hint = label_en, label_ar, hint; n_upd += 1
    s.flush()
    n_sugg = suggest_mappings(s, fw, only_standard_ids=new_ids) if (suggest and new_ids) else 0
    log_action(s, action="curriculum.import", user_id=by, resource_type="curriculum_framework", resource_id=fw.id,
               details={"key": fw.key, "created": created, "standards_new": n_new, "standards_updated": n_upd,
                        "suggested": n_sugg})
    return fw, {"created": created, "standards_new": n_new, "standards_updated": n_upd, "suggested": n_sugg}


# --- suggestion déterministe -------------------------------------------------------------------

_STOP = {"the", "a", "an", "and", "or", "of", "to", "with", "in", "on", "by", "for", "as", "is", "are", "be",
         "that", "than", "two", "using", "use", "understand", "recognize", "recognise", "find", "write", "give",
         "whole", "numbers", "number"}
_SYN = {"adding": "add", "addition": "add", "sum": "add", "subtracting": "subtract", "subtraction": "subtract",
        "difference": "subtract", "comparing": "compare", "comparison": "compare", "equivalent": "equivalence",
        "equivalence": "equivalence", "simplifying": "simplify", "simplest": "simplify", "lowest": "simplify",
        "terms": "simplify", "denominators": "denominator", "denominator": "denominator", "unlike": "different",
        "different": "different", "like": "same", "same": "same", "common": "common", "multiples": "multiple",
        "multiple": "multiple", "factors": "factor", "factor": "factor", "mixed": "mixed", "improper": "improper",
        "line": "numberline", "fractions": "fraction", "fraction": "fraction", "unit": "unit", "parts": "part",
        "part": "part", "shares": "part", "share": "part", "halves": "half", "half": "half", "quarters": "quarter",
        "quarter": "quarter", "benchmark": "benchmark", "benchmarks": "benchmark", "multiply": "multiplication",
        "multiplication": "multiplication", "divisor": "divisor", "gcd": "divisor", "lcm": "multiple",
        "convert": "convert", "converting": "convert", "visual": "model", "models": "model", "model": "model",
        "shaded": "model", "set": "set", "objects": "set"}


def _tokens(text: str) -> set:
    out = set()
    for t in re.findall(r"[a-z]+", (text or "").lower()):
        if t in _STOP:
            continue
        out.add(_SYN.get(t, t))
    return out


def _grade_of_hint(hint: Optional[str]) -> Optional[int]:
    m = re.search(r"(\d{1,2})", hint or "")
    if not m:
        return None
    g = int(m.group(1))
    # Year N (UK) ≈ Grade N−1 : proposition par défaut Q6, utilisée seulement pour SUGGÉRER
    if (hint or "").strip().upper().startswith("Y"):
        g -= 1
    return g


def score_match(standard: CurriculumStandard, comp: Competency) -> float:
    lex = len(_tokens(standard.label_en) & _tokens(comp.label_en))
    g = _grade_of_hint(standard.grade_hint)
    grade = 0.0 if g is None else (1.5 if g == comp.grade else (0.5 if abs(g - comp.grade) == 1 else -1.0))
    return lex + grade


def suggest_mappings(s: Session, fw: CurriculumFrameworkDef, *, only_standard_ids: Optional[List[uuid.UUID]] = None,
                     threshold: float = 2.0, max_per_standard: int = 2) -> int:
    """Propose des lignes `suggested` (PARTIAL, confiance M) pour les attendus sans mapping.
    Déterministe ; ne remplace jamais une ligne existante. Retourne le nombre de lignes créées."""
    comps = list(s.execute(select(Competency)).scalars())
    q = select(CurriculumStandard).where(CurriculumStandard.framework_id == fw.id)
    if only_standard_ids is not None:
        q = q.where(CurriculumStandard.id.in_(only_standard_ids))
    n = 0
    for st in s.execute(q).scalars():
        if s.execute(select(CompetencyCurriculumMap.competency_id).where(CompetencyCurriculumMap.standard_id == st.id)).first():
            continue
        scored = sorted(((score_match(st, c), c) for c in comps), key=lambda x: (-x[0], x[1].code))
        for score, comp in scored[:max_per_standard]:
            if score < threshold:
                break
            s.add(CompetencyCurriculumMap(competency_id=comp.id, standard_id=st.id, alignment_type=AlignmentType.PARTIAL,
                                          confidence=MappingConfidence.M, note=f"suggestion automatique (score {score:.1f})",
                                          weight_source=WeightSource.EXPERT, suggested=True))
            n += 1
    s.flush()
    return n


# --- revue ------------------------------------------------------------------------------------

def set_mapping(s: Session, fw: CurriculumFrameworkDef, *, standard_id: uuid.UUID, competency_id: uuid.UUID,
                alignment_type: str, confidence: str, enrich_kind: Optional[str], note: Optional[str],
                by: uuid.UUID) -> CompetencyCurriculumMap:
    """Crée ou valide une ligne : elle devient revue (suggested=False, reviewed_by/at)."""
    st = s.get(CurriculumStandard, standard_id)
    if st is None or st.framework_id != fw.id:
        raise CurriculaError("attendu hors de ce framework")
    if s.get(Competency, competency_id) is None:
        raise CurriculaError("compétence inconnue")
    try:
        at, conf = AlignmentType(alignment_type), MappingConfidence(confidence)
    except ValueError:
        raise CurriculaError("alignment_type ou confidence invalide")
    if at == AlignmentType.ENRICH and enrich_kind not in ("grade", "requirement"):
        raise CurriculaError("ENRICH exige enrich_kind = grade | requirement")
    if at != AlignmentType.ENRICH:
        enrich_kind = None
    m = s.get(CompetencyCurriculumMap, (competency_id, standard_id))
    if m is None:
        m = CompetencyCurriculumMap(competency_id=competency_id, standard_id=standard_id, alignment_type=at, confidence=conf,
                                    weight_source=WeightSource.EXPERT)
        s.add(m)
    else:
        if m.alignment_type != at and not m.suggested:
            m.weight_version += 1
        m.alignment_type, m.confidence = at, conf
    m.enrich_kind, m.note = enrich_kind, (note or None)
    m.suggested, m.reviewed_by, m.reviewed_at = False, by, utcnow()
    st.reviewed_at = None            # revu via ses lignes, pas « sans correspondance »
    s.flush()
    log_action(s, action="curriculum.map", user_id=by, resource_type="curriculum_standard", resource_id=st.id,
               details={"competency_id": str(competency_id), "alignment_type": at.value, "confidence": conf.value})
    return m


def delete_mapping(s: Session, fw: CurriculumFrameworkDef, *, standard_id: uuid.UUID, competency_id: uuid.UUID,
                   by: uuid.UUID) -> None:
    m = s.get(CompetencyCurriculumMap, (competency_id, standard_id))
    st = s.get(CurriculumStandard, standard_id)
    if m is None or st is None or st.framework_id != fw.id:
        raise CurriculaError("ligne introuvable")
    s.delete(m); s.flush()
    log_action(s, action="curriculum.unmap", user_id=by, resource_type="curriculum_standard", resource_id=st.id,
               details={"competency_id": str(competency_id)})


def mark_standard_no_match(s: Session, fw: CurriculumFrameworkDef, *, standard_id: uuid.UUID, by: uuid.UUID,
                           no_match: bool = True) -> CurriculumStandard:
    """Attendu revu SANS correspondance dans le graphe (ex. hors fractions). Supprime ses lignes
    suggérées ; refusé s'il a une ligne validée."""
    st = s.get(CurriculumStandard, standard_id)
    if st is None or st.framework_id != fw.id:
        raise CurriculaError("attendu hors de ce framework")
    maps = list(s.execute(select(CompetencyCurriculumMap).where(CompetencyCurriculumMap.standard_id == st.id)).scalars())
    if no_match:
        if any(not m.suggested for m in maps):
            raise CurriculaError("cet attendu a des lignes validées : les supprimer d'abord")
        for m in maps:
            s.delete(m)
        st.reviewed_at = utcnow()
    else:
        st.reviewed_at = None
    s.flush()
    log_action(s, action="curriculum.no_match" if no_match else "curriculum.reopen", user_id=by,
               resource_type="curriculum_standard", resource_id=st.id)
    return st


# --- couverture et publication ----------------------------------------------------------------

def _standard_state(st: CurriculumStandard, maps: List[CompetencyCurriculumMap]) -> str:
    """reviewed | suggested | unmapped — « revu » = toutes les lignes validées (≥ 1), ou marqué sans correspondance."""
    if maps and all(not m.suggested for m in maps):
        return "reviewed"
    if not maps and st.reviewed_at is not None:
        return "reviewed"
    return "suggested" if maps else "unmapped"


def coverage(s: Session, fw: CurriculumFrameworkDef) -> dict:
    standards = list(s.execute(select(CurriculumStandard).where(CurriculumStandard.framework_id == fw.id)
                               .order_by(CurriculumStandard.code)).scalars())
    maps_by_std: Dict[uuid.UUID, List[CompetencyCurriculumMap]] = {}
    if standards:
        for m in s.execute(select(CompetencyCurriculumMap).where(
                CompetencyCurriculumMap.standard_id.in_([st.id for st in standards]))).scalars():
            maps_by_std.setdefault(m.standard_id, []).append(m)
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    states = {st.id: _standard_state(st, maps_by_std.get(st.id, [])) for st in standards}
    counts = {"standards": len(standards),
              "reviewed": sum(1 for v in states.values() if v == "reviewed"),
              "suggested": sum(1 for v in states.values() if v == "suggested"),
              "unmapped": sum(1 for v in states.values() if v == "unmapped")}
    mapped_comp_ids = {m.competency_id for ms in maps_by_std.values() for m in ms if not m.suggested}
    counts["competencies_mapped"] = len(mapped_comp_ids)
    counts["competencies_total"] = len(comps)
    return {
        "framework_id": str(fw.id), "key": fw.key, "status": fw.status.value, "counts": counts,
        "publishable": counts["standards"] > 0 and counts["reviewed"] == counts["standards"],
        "standards": [{"id": str(st.id), "code": st.code, "label_en": st.label_en, "label_ar": st.label_ar,
                       "grade_hint": st.grade_hint, "state": states[st.id],
                       "no_match": st.reviewed_at is not None and not maps_by_std.get(st.id),
                       "mappings": [mapping_payload(m, st, comps.get(m.competency_id)) for m in
                                    sorted(maps_by_std.get(st.id, []), key=lambda m: comps[m.competency_id].code)]}
                      for st in standards],
    }


def mapping_payload(m: CompetencyCurriculumMap, st: CurriculumStandard, comp: Optional[Competency]) -> dict:
    """Ligne de mapping + aperçu du libellé que verra l'école (même helper que les vues)."""
    wording_en, wording_ar = vs.alignment_wording(st, m.alignment_type, m.confidence, m.enrich_kind)
    return {
        "competency_id": str(m.competency_id), "competency_code": comp.code if comp else None,
        "competency_label_en": comp.label_en if comp else None, "competency_label_ar": comp.label_ar if comp else None,
        "competency_grade": comp.grade if comp else None,
        "alignment_type": m.alignment_type.value, "confidence": m.confidence.value, "enrich_kind": m.enrich_kind,
        "note": m.note, "suggested": m.suggested,
        "reviewed_by": str(m.reviewed_by) if m.reviewed_by else None,
        "reviewed_at": m.reviewed_at.isoformat() if m.reviewed_at else None,
        "weight_version": m.weight_version,
        "preview_en": wording_en, "preview_ar": wording_ar,
    }


def preview(s: Session, fw: CurriculumFrameworkDef, *, standard_id: uuid.UUID, alignment_type: str, confidence: str,
            enrich_kind: Optional[str]) -> dict:
    """Aperçu « ce que voit l'école » pour une ligne PAS ENCORE enregistrée (éditeur O3).
    Le vocabulaire reste côté serveur : l'UI ne porte aucune table de libellés."""
    st = s.get(CurriculumStandard, standard_id)
    if st is None or st.framework_id != fw.id:
        raise CurriculaError("attendu hors de ce framework")
    try:
        at, conf = AlignmentType(alignment_type), MappingConfidence(confidence)
    except ValueError:
        raise CurriculaError("alignment_type ou confidence invalide")
    if at == AlignmentType.ENRICH and enrich_kind not in ("grade", "requirement"):
        raise CurriculaError("ENRICH exige enrich_kind = grade | requirement")
    en, ar = vs.alignment_wording(st, at, conf, enrich_kind if at == AlignmentType.ENRICH else None)
    return {"preview_en": en, "preview_ar": ar}


def framework_payload(s: Session, fw: CurriculumFrameworkDef) -> dict:
    n_std = len(s.execute(select(CurriculumStandard.id).where(CurriculumStandard.framework_id == fw.id)).all())
    n_orgs = len(s.execute(select(Organization.id).where(Organization.curriculum_framework_id == fw.id,
                                                          Organization.deleted_at.is_(None))).all())
    return {"id": str(fw.id), "key": fw.key, "name_en": fw.name_en, "name_ar": fw.name_ar, "country": fw.country,
            "status": fw.status.value, "imported_at": fw.imported_at.isoformat() if fw.imported_at else None,
            "published_at": fw.published_at.isoformat() if fw.published_at else None,
            "source_note": fw.source_note, "n_standards": n_std, "n_organizations": n_orgs}


def publish(s: Session, fw: CurriculumFrameworkDef, *, by: uuid.UUID) -> CurriculumFrameworkDef:
    cov = coverage(s, fw)
    if not cov["publishable"]:
        c = cov["counts"]
        raise CurriculaError(f"publication refusée : {c['suggested']} attendu(s) avec suggestions non revues, "
                             f"{c['unmapped']} sans correspondance ni revue, sur {c['standards']}")
    fw.status, fw.published_at = FrameworkStatus.PUBLISHED, utcnow()
    s.flush()
    log_action(s, action="curriculum.publish", user_id=by, resource_type="curriculum_framework", resource_id=fw.id,
               details={"key": fw.key, **cov["counts"]})
    return fw


def unpublish(s: Session, fw: CurriculumFrameworkDef, *, by: uuid.UUID) -> CurriculumFrameworkDef:
    """Repasse en brouillon : les écoles qui l'avaient choisi retombent en vue neutre ATLAS."""
    fw.status, fw.published_at = FrameworkStatus.DRAFT, None
    s.flush()
    log_action(s, action="curriculum.unpublish", user_id=by, resource_type="curriculum_framework", resource_id=fw.id,
               details={"key": fw.key})
    return fw


def delete_framework(s: Session, fw: CurriculumFrameworkDef, *, by: uuid.UUID) -> None:
    if fw.status == FrameworkStatus.PUBLISHED:
        raise CurriculaError("framework publié : dépublier d'abord")
    if s.execute(select(Organization.id).where(Organization.curriculum_framework_id == fw.id)).first():
        raise CurriculaError("des organisations pointent ce framework")
    s.delete(fw); s.flush()                      # cascade : attendus → lignes de mapping
    log_action(s, action="curriculum.delete", user_id=by, resource_type="curriculum_framework", resource_id=fw.id,
               details={"key": fw.key})
