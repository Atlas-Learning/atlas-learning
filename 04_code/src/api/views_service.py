"""Vues de restitution (Epic 5, T5.4 enseignant + T5.5 admin).

Réutilise le cœur analytique (diagnose_all, aggregate). Logique testable sans HTTP ;
l'autorisation (RBAC) est appliquée dans les endpoints.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta
from statistics import mean
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.items.quarantine import active_pool
from src.models.base import (
    AlignmentType,
    FrameworkStatus,
    EdgeType,
    MappingConfidence,
    ensure_utc,
    utcnow,
)
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.curriculum import CompetencyCurriculumMap, CurriculumFrameworkDef, CurriculumStandard
from src.models.item import Item
from src.models.measurement import Response, School, Student, StudentCompetencyAbility
from src.models.org import Classroom, Organization, StudentClassroom
from src.restitution.diagnosis import MASTERY_ELO, diagnose, diagnose_all
from src.restitution.scale import DEFAULT_ANCHORS, restitute
from src.restitution.tutor import explain_diagnosis


def _is_mastered(ability_elo: float, n_direct: int) -> bool:
    """Maîtrise AFFICHÉE aux vues (enseignant/admin/parent) : seuil atteint ET mesuré.

    MASTERY_ELO == ELO_START (1500) : une compétence JAMAIS répondue peut être poussée
    juste au-dessus du seuil (~1504) par simple PROPAGATION depuis ses voisines. C'est
    une estimation, pas une mesure — sans réponse directe (n_direct == 0), on n'affiche
    jamais « maîtrisé ». Le diagnostic causal interne (diagnosis.py), lui, travaille
    volontairement sur les estimations EXISTANTES (lignes ability, mesurées ou propagées) —
    et ignore les nœuds sans aucune ligne : cette garde ne s'applique qu'à la restitution.
    (Revue 2026-07-07.)
    """
    return n_direct > 0 and ability_elo >= MASTERY_ELO


# ---------------------------------------------------------------------------
# Lot B (B3/B4/B5) — vue curriculaire par tenant.
# Tables de wording FERMÉES (Cadrage-LotB §3/B4) : le texte par type d'alignement
# n'est jamais libre — c'est le garde-fou anti-sur-claim (« aligned to », jamais
# « meets »). Champs ADDITIFS uniquement : la vue ATLAS reste octet pour octet
# identique à aujourd'hui (zéro régression B3).
# ---------------------------------------------------------------------------

_ALIGNMENT_WORDING_EN = {
    AlignmentType.EXACT: "aligned to {code}",
    AlignmentType.PARTIAL: "covers part of {code}",
    AlignmentType.BROADER: "one of several skills within {code}",
    AlignmentType.PREREQ: "building block for {code}",
    AlignmentType.ENRICH: "beyond {code} expectations",
}
_ALIGNMENT_WORDING_AR = {
    AlignmentType.EXACT: "متوافق مع {code}",
    AlignmentType.PARTIAL: "يغطي جزءًا من {code}",
    AlignmentType.BROADER: "إحدى مهارات {code}",
    AlignmentType.PREREQ: "لبنة أساسية لـ {code}",
    AlignmentType.ENRICH: "يتجاوز متطلبات {code}",
}
# ENRICH-de-grade (M-4) : la compétence est mesurée UN GRADE PLUS TÔT que le standard —
# c'est un argument (« on mesure dès G4 ce que votre programme demande en G5 »), pas un
# « hors programme ». Wording distinct de l'ENRICH-d'exigence (ci-dessus) ; sélectionné
# quand enrich_kind == 'grade'.
_ENRICH_GRADE_WORDING_EN = "taught earlier than {code}"
_ENRICH_GRADE_WORDING_AR = "يُدرَّس قبل {code}"
# Confiance M → mapping indicatif tant que non fiabilisé (B7). Suffixe par langue
# (revue 2026-07-12, MAJ-2 : un suffixe EN concaténé au wording AR injectait de
# l'anglais LTR dans une chaîne RTL — visible sur 100 % des badges MoE, tous en M).
_INDICATIVE_SUFFIX_EN = " (indicative mapping)"
_INDICATIVE_SUFFIX_AR = " (تعيين استرشادي)"  # à confirmer avec la linguiste (Lot 2)

# MoE UAE ne publie AUCUN code de standard (ligne rouge B2 : « affirmer un code MoE
# serait faux »). On n'affiche donc jamais la clé technique NUM_OPS.{band} comme un
# code, et le wording n'insère pas de {code} — il nomme le domaine (revue 2026-07-12,
# CRIT-3). Le libellé du standard (« Numbers & Operations — Cycle 1 (G4-G5) ») porte
# déjà toute l'information affichable.
_MOE_WORDING_EN = "part of {label}"
_MOE_WORDING_AR = "ضمن {label}"

# ordre d'affichage quand une compétence mappe plusieurs standards : le plus
# spécifique d'abord (EXACT), l'enrichissement en dernier
_ALIGNMENT_SPECIFICITY = {
    AlignmentType.EXACT: 0, AlignmentType.PARTIAL: 1, AlignmentType.BROADER: 2,
    AlignmentType.PREREQ: 3, AlignmentType.ENRICH: 4,
}

# sentinelle « contexte non résolu » — distincte de None (= vue ATLAS résolue),
# pour que class_digest puisse passer SON contexte à class_gaps (un seul
# chargement des mappings par appel)
_UNRESOLVED = object()


MOE_KEY = "MOE_UAE"   # framework sans codes officiels : jamais de code affiché


def school_framework(s: Session, school_id) -> Optional[CurriculumFrameworkDef]:
    """Framework d'affichage du tenant propriétaire de l'école (B3 ; refonte C1 : table).

    None = vue neutre ATLAS : école orpheline d'organisation (fixtures legacy), organisation
    sans framework, ou framework non publié — on ne devine jamais un curriculum."""
    school = s.get(School, school_id) if school_id is not None else None
    if school is None or school.organization_id is None:
        return None
    org = s.get(Organization, school.organization_id)
    if org is None or org.curriculum_framework_id is None:
        return None
    fw = s.get(CurriculumFrameworkDef, org.curriculum_framework_id)
    if fw is None or fw.status != FrameworkStatus.PUBLISHED:
        return None
    return fw


def curriculum_view_of_school(s: Session, school_id) -> str:
    """Clé du framework affiché, ou "ATLAS" (compatibilité des payloads)."""
    fw = school_framework(s, school_id)
    return fw.key if fw is not None else "ATLAS"


def _standard_payload(m: CompetencyCurriculumMap, std: CurriculumStandard) -> dict:
    is_moe = std.framework_key == MOE_KEY
    if is_moe:
        # jamais de code affiché ; wording nomme le domaine, pas la clé technique
        wording_en = _MOE_WORDING_EN.format(label=std.label_en)
        wording_ar = _MOE_WORDING_AR.format(label=std.label_ar)
    elif m.alignment_type == AlignmentType.ENRICH and m.enrich_kind == "grade":
        # ENRICH-de-grade : « taught earlier than » plutôt que « beyond … expectations »
        wording_en = _ENRICH_GRADE_WORDING_EN.format(code=std.code)
        wording_ar = _ENRICH_GRADE_WORDING_AR.format(code=std.code)
    else:
        wording_en = _ALIGNMENT_WORDING_EN[m.alignment_type].format(code=std.code)
        wording_ar = _ALIGNMENT_WORDING_AR[m.alignment_type].format(code=std.code)
    if m.confidence == MappingConfidence.M:
        wording_en += _INDICATIVE_SUFFIX_EN
        wording_ar += _INDICATIVE_SUFFIX_AR
    return {
        "framework": std.framework_key,
        "code": std.code,               # clé technique (identité), jamais garantie affichable
        "display_code": None if is_moe else std.code,  # ce que l'UI a le droit d'afficher en code
        "label_en": std.label_en,
        "label_ar": std.label_ar,
        "alignment_type": m.alignment_type.value,
        "wording_en": wording_en,
        "wording_ar": wording_ar,
    }


def _crosswalk_by_code(s: Session, framework: CurriculumFrameworkDef) -> dict:
    """competency_code -> [payloads standard], du plus spécifique au moins spécifique.

    UN chargement par appel de vue (volumes triviaux : 32 compétences) — les vues
    l'attachent ensuite en mémoire, jamais de requête par compétence."""
    rows = s.execute(
        select(Competency.code, CompetencyCurriculumMap, CurriculumStandard)
        .join(CompetencyCurriculumMap, CompetencyCurriculumMap.competency_id == Competency.id)
        .join(CurriculumStandard, CurriculumStandard.id == CompetencyCurriculumMap.standard_id)
        .where(CurriculumStandard.framework_id == framework.id,
               CompetencyCurriculumMap.suggested.is_(False))      # C1 : une ligne suggérée n'est jamais servie
    ).all()
    grouped: dict = {}
    for code, m, std in rows:
        grouped.setdefault(code, []).append((m, std))
    return {
        code: [_standard_payload(m, std) for m, std in
               sorted(pairs, key=lambda p: (_ALIGNMENT_SPECIFICITY[p[0].alignment_type], p[1].code))]
        for code, pairs in grouped.items()
    }


def _curriculum_context(s: Session, school_id) -> Optional[dict]:
    """None = vue ATLAS (payloads strictement inchangés) ; sinon crosswalk du framework."""
    fw = school_framework(s, school_id)
    if fw is None:
        return None
    return _crosswalk_by_code(s, fw)


def _classroom_curriculum(s: Session, classroom_id) -> Optional[dict]:
    cls = s.get(Classroom, classroom_id)
    return _curriculum_context(s, cls.school_id) if cls is not None else None


def _attach_standard(entry: dict, competency_code: str, crosswalk: Optional[dict]) -> dict:
    """Champs ADDITIFS `standard` (le plus spécifique) + `standards` (liste complète).

    Jamais présents en vue ATLAS (crosswalk None) — c'est le contrat de non-régression."""
    if crosswalk is None:
        return entry
    stds = crosswalk.get(competency_code, [])
    entry["standard"] = stds[0] if stds else None
    entry["standards"] = stds
    return entry


def _code_maps(s: Session):
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    code_of = {cid: c.code for cid, c in comps.items()}
    label_of = {c.code: c.label_en for c in comps.values()}
    label_ar_of = {c.code: c.label_ar for c in comps.values()}
    hard: dict = {}
    for e in s.execute(
        select(CompetencyPrerequisite).where(CompetencyPrerequisite.edge_type == EdgeType.HARD)
    ).scalars():
        if e.target_id in code_of and e.source_id in code_of:
            hard.setdefault(code_of[e.target_id], []).append(code_of[e.source_id])
    return code_of, label_of, hard, label_ar_of


def _class_student_ids(s: Session, classroom_id: uuid.UUID) -> set:
    """IDs des élèves vivants d'une classe : inscriptions M:N ∪ classe principale (homeroom)."""
    ids = set(s.execute(
        select(StudentClassroom.student_id).where(StudentClassroom.classroom_id == classroom_id)
    ).scalars())
    ids |= set(s.execute(
        select(Student.id).where(Student.classroom_id == classroom_id)
    ).scalars())
    if not ids:
        return set()
    return set(s.execute(
        select(Student.id).where(Student.id.in_(ids), Student.deleted_at.is_(None))
    ).scalars())


def class_gaps(s: Session, classroom_id: uuid.UUID, *, crosswalk=_UNRESOLVED) -> List[dict]:
    """Lacunes de la classe regroupées par CAUSE RACINE, triées par fréquence (T5.4).

    Chaque entrée porte son diagnostic causal — « où concentrer le cours ».
    B4 : la cause racine est étiquetée avec son code standard si le tenant a une
    vue curriculaire (`crosswalk` : injectable par class_digest, sinon résolu ici).
    """
    if crosswalk is _UNRESOLVED:
        crosswalk = _classroom_curriculum(s, classroom_id)
    code_of, label_of, hard, label_ar_of = _code_maps(s)
    student_ids = _class_student_ids(s, classroom_id)

    counter: Counter = Counter()
    example_gap: dict = {}     # root_cause -> (gap_code, is_self) le plus représentatif
    example_expl: dict = {}
    for sid in student_ids:
        rows = s.execute(
            select(StudentCompetencyAbility).where(StudentCompetencyAbility.student_id == sid)
        ).scalars().all()
        abilities = {code_of[r.competency_id]: r.ability_elo for r in rows if r.competency_id in code_of}
        # Une cause racine compte UNE fois par élève (plusieurs lacunes peuvent y remonter,
        # cf. class_digest ci-dessous) : sinon student_count explose au-delà de n_students.
        seen_roots: dict = {}
        for d in diagnose_all(abilities, hard):
            seen_roots.setdefault(d.root_cause, (d.gap, d.is_self, d.explanation))
        for rc, (gap_code, is_self, explanation) in seen_roots.items():
            counter[rc] += 1
            example_gap.setdefault(rc, (gap_code, is_self))
            example_expl.setdefault(rc, explanation)

    out = []
    for rc, n in counter.most_common():
        gap_code, is_self = example_gap[rc]
        out.append(_attach_standard({
            "root_cause": rc,
            "label": label_of.get(rc, rc),                  # rétro-compat
            "root_cause_label_en": label_of.get(rc, rc),
            "root_cause_label_ar": label_ar_of.get(rc, rc),
            "gap_label_en": label_of.get(gap_code, gap_code),
            "gap_label_ar": label_ar_of.get(gap_code, gap_code),
            "is_self": is_self,
            "student_count": n,
            "diagnosis": example_expl[rc],
        }, rc, crosswalk))
    return out


def class_digest(s: Session, classroom_id: uuid.UUID, *, days: int = 7,
                 now: Optional[datetime] = None) -> dict:
    """Digest hebdomadaire enseignant — conçu pour SA cadence (Brief : persona de rétention).

    Pas une boucle quotidienne d'élève (refusée) : l'habitude qui compte est celle de
    l'enseignant qui ouvre sa vue classe chaque semaine. Donne l'activité de la semaine,
    les lacunes ÉMERGENTES (re)mesurées dans la fenêtre, et la priorité #1 où agir.
    """
    now = ensure_utc(now) or utcnow()   # naïf accepté (tests) → réinterprété UTC
    since = now - timedelta(days=days)
    crosswalk = _classroom_curriculum(s, classroom_id)   # résolu UNE fois pour tout le digest
    code_of, label_of, hard, label_ar_of = _code_maps(s)
    student_ids = _class_student_ids(s, classroom_id)

    # Activité de la semaine.
    responses = list(s.execute(
        select(Response).where(Response.student_id.in_(student_ids),
                               Response.created_at >= since)
    ).scalars()) if student_ids else []
    active_students = {r.student_id for r in responses}

    # Lacunes émergentes : diagnostic dont la lacune (ou sa racine) a été (re)mesurée cette semaine.
    emerging: Counter = Counter()
    emerging_example: dict = {}
    for sid in student_ids:
        rows = s.execute(
            select(StudentCompetencyAbility).where(
                StudentCompetencyAbility.student_id == sid,
                StudentCompetencyAbility.n_direct > 0,
            )
        ).scalars().all()
        abilities = {code_of[r.competency_id]: r.ability_elo for r in rows if r.competency_id in code_of}
        recent = {code_of[r.competency_id] for r in rows
                  if r.competency_id in code_of and r.last_measured_at
                  and ensure_utc(r.last_measured_at) >= since}  # SQLite relit naïf → UTC
        if not recent:
            continue
        # Une cause racine compte UNE fois par élève (plusieurs lacunes peuvent y remonter).
        seen_roots: dict = {}
        for d in diagnose_all(abilities, hard):
            if d.gap in recent or d.root_cause in recent:
                seen_roots.setdefault(d.root_cause, (d.gap, d.is_self))
        for rc, (gap_code, is_self) in seen_roots.items():
            emerging[rc] += 1
            emerging_example.setdefault(rc, (gap_code, is_self))

    emerging_gaps = []
    for rc, n in emerging.most_common(5):
        gap_code, is_self = emerging_example[rc]
        emerging_gaps.append(_attach_standard({
            "root_cause": rc,
            "root_cause_label_en": label_of.get(rc, rc),
            "root_cause_label_ar": label_ar_of.get(rc, rc),
            "gap_label_en": label_of.get(gap_code, gap_code),
            "gap_label_ar": label_ar_of.get(gap_code, gap_code),
            "is_self": is_self,
            "student_count": n,
        }, rc, crosswalk))

    all_gaps = class_gaps(s, classroom_id, crosswalk=crosswalk)
    return {
        "classroom_id": str(classroom_id),
        "window_days": days,
        "since": since.isoformat(),
        "n_students": len(student_ids),
        "n_active_students": len(active_students),
        "n_responses": len(responses),
        "emerging_gaps": emerging_gaps,
        "top_priority": all_gaps[0] if all_gaps else None,
    }


def school_overview(s: Session, school_id: uuid.UUID) -> dict:
    """Agrégat établissement (T5.5) : maîtrise par compétence et par classe. SANS PII élève."""
    crosswalk = _curriculum_context(s, school_id)   # B4 : colonne « standard » si vue ≠ ATLAS
    code_of, label_of, _, _ = _code_maps(s)
    students = s.execute(
        select(Student).where(Student.school_id == school_id, Student.deleted_at.is_(None))
    ).scalars().all()
    # Appartenance M:N : un élève peut compter dans plusieurs classes (spécialités).
    student_ids = [st.id for st in students]
    classes_of: dict = {}
    if student_ids:
        for sid, cid in s.execute(
            select(StudentClassroom.student_id, StudentClassroom.classroom_id)
            .where(StudentClassroom.student_id.in_(student_ids))
        ).all():
            classes_of.setdefault(sid, set()).add(cid)
    for st in students:
        if st.classroom_id:
            classes_of.setdefault(st.id, set()).add(st.classroom_id)

    # Jointure Student : les abilities d'un élève SOFT-DELETED ne pèsent plus dans les
    # moyennes/taux de maîtrise de l'établissement (revue 2026-07-08) — la liste
    # `students` était déjà filtrée, mais pas cet agrégat.
    rows = [r for r in s.execute(
        select(StudentCompetencyAbility)
        .join(Student, Student.id == StudentCompetencyAbility.student_id)
        .where(StudentCompetencyAbility.school_id == school_id,
               Student.deleted_at.is_(None))
    ).scalars() if r.n_direct > 0]  # mesures directes seulement — même garde que _is_mastered
    # (une ability seulement propagée n'entre ni dans mean_ability ni dans mastery_rate)

    by_comp: dict = {}
    for r in rows:
        by_comp.setdefault(r.competency_id, []).append(r.ability_elo)
    competencies = [
        _attach_standard(
            {"code": code_of.get(cid, str(cid)), "label": label_of.get(code_of.get(cid), ""),
             "mean_ability": round(mean(v), 1),
             "mastery_rate": round(sum(1 for x in v if x >= MASTERY_ELO) / len(v), 2),
             "n_measured": len(v)},
            code_of.get(cid, str(cid)), crosswalk)
        for cid, v in by_comp.items()
    ]
    competencies.sort(key=lambda c: c["mastery_rate"])  # les plus faibles d'abord

    classes = []
    for cls in s.execute(
        select(Classroom).where(Classroom.school_id == school_id, Classroom.deleted_at.is_(None))
    ).scalars():
        vals = [r.ability_elo for r in rows if cls.id in classes_of.get(r.student_id, ())]
        classes.append({
            "classroom_id": str(cls.id), "name": cls.name,
            "n_students": sum(1 for st in students if cls.id in classes_of.get(st.id, ())),
            "mean_ability": round(mean(vals), 1) if vals else None,
        })

    return {"school_id": str(school_id), "n_students": len(students),
            "competencies": competencies, "classes": classes}


# Une compétence est « maîtrisée par la cohorte » si au moins ce taux d'élèves
# MESURÉS la maîtrisent (revue 2026-07-12, MAJ-1 : l'ancienne règle appliquait
# _is_mastered à la MOYENNE de l'école — une classe 50/50 ressortait « couverte »).
# Seuil explicite et affiché dans le rapport, jamais implicite.
COHORT_MASTERY_THRESHOLD = 0.8


def curriculum_coverage(s: Session, school_id: uuid.UUID) -> Optional[dict]:
    """Section « Couverture du programme » du rapport école (B5). None en vue ATLAS.

    Par standard S dont les compétences mappées sont {c₁…cₙ} : « k/n compétences
    alignées sur S maîtrisées ». Une compétence est maîtrisée par la cohorte si
    ≥ COHORT_MASTERY_THRESHOLD des élèves MESURÉS la maîtrisent (règle par ÉLÈVE —
    _is_mastered — puis TAUX, pas maîtrise de la moyenne : MAJ-1). Mêmes gardes que
    school_overview (élèves vivants, mesures directes).

    `covered` (booléen, rapport école UNIQUEMENT) : vrai SEULEMENT si toutes les
    compétences EXACT de S sont maîtrisées par la cohorte. Un framework SANS codes
    ni mapping EXACT (MoE UAE : tout est BROADER) n'a pas de notion de « couvert » —
    `covered` vaut alors None et le rapport n'affiche PAS de verdict (CRIT-3b : une
    colonne toujours fausse est un bug déguisé en verdict). JAMAIS de « meets {code} »
    au niveau élève individuel en v1 : le standard-setting appartient au Lot C.
    Agrégation en lecture (volumes triviaux, 32 compétences).
    """
    framework = school_framework(s, school_id)
    if framework is None:
        return None

    # taux de maîtrise PAR ÉLÈVE et par compétence — mêmes filtres que school_overview
    rows = [r for r in s.execute(
        select(StudentCompetencyAbility)
        .join(Student, Student.id == StudentCompetencyAbility.student_id)
        .where(StudentCompetencyAbility.school_id == school_id,
               Student.deleted_at.is_(None))
    ).scalars() if r.n_direct > 0]
    by_comp: dict = {}
    for r in rows:
        by_comp.setdefault(r.competency_id, []).append(r)
    # compétence maîtrisée par la cohorte = ≥ seuil d'élèves mesurés la maîtrisent
    comp_mastered = {
        cid: (sum(1 for r in rr if _is_mastered(r.ability_elo, r.n_direct)) / len(rr))
             >= COHORT_MASTERY_THRESHOLD
        for cid, rr in by_comp.items()
    }

    # UN chargement du crosswalk (standard → mappings), pas de N+1
    maps = s.execute(
        select(CompetencyCurriculumMap, CurriculumStandard)
        .join(CurriculumStandard, CurriculumStandard.id == CompetencyCurriculumMap.standard_id)
        .where(CurriculumStandard.framework_id == framework.id,
               CompetencyCurriculumMap.suggested.is_(False))
    ).all()
    by_std: dict = {}
    for m, std in maps:
        by_std.setdefault(std.id, (std, []))[1].append(m)

    has_exact = framework.key != MOE_KEY
    standards = []
    for std, ms in by_std.values():
        mastered = [bool(comp_mastered.get(m.competency_id, False)) for m in ms]
        exact_mastered = [ok for m, ok in zip(ms, mastered)
                          if m.alignment_type == AlignmentType.EXACT]
        standards.append({
            "code": std.code,
            "display_code": None if std.framework_key == MOE_KEY else std.code,
            "label": std.label_en,
            "label_ar": std.label_ar,
            "mastered_count": sum(mastered),
            "total": len(ms),
            # None (pas False) quand la notion n'a pas de sens → l'UI n'affiche rien
            "covered": (bool(exact_mastered) and all(exact_mastered)) if has_exact else None,
        })
    standards.sort(key=lambda x: x["code"])
    return {
        "framework": framework.key,
        "shows_covered": has_exact,
        "coverage_threshold": COHORT_MASTERY_THRESHOLD,
        "standards": standards,
    }


# ---------------------------------------------------------------------------
# T5.x — vues UI complémentaires (fiche élève, trajectoire parent, listings)
# Wrappers minces sur le cœur analytique (diagnose / restitute / aggregate).
# ---------------------------------------------------------------------------

def _competency_meta(s: Session) -> dict:
    """code -> {label_en, label_ar, grade, strand}."""
    out = {}
    for c in s.execute(select(Competency)).scalars():
        out[c.code] = {
            "label_en": c.label_en, "label_ar": c.label_ar,
            "grade": c.grade, "strand": ".".join(c.code.split(".")[:3]),
        }
    return out


def list_students(s: Session, classroom_id: uuid.UUID) -> List[dict]:
    """Élèves d'une classe (sans PII inutile : ref externe seulement)."""
    ids = _class_student_ids(s, classroom_id)
    rows = s.execute(select(Student).where(Student.id.in_(ids))).scalars().all() if ids else []
    out = []
    for st in rows:
        abilities = s.execute(
            select(StudentCompetencyAbility).where(
                StudentCompetencyAbility.student_id == st.id,
                StudentCompetencyAbility.n_direct > 0,
            )
        ).scalars().all()
        measured = [a for a in abilities]
        mean_elo = round(mean([a.ability_elo for a in measured]), 1) if measured else None
        n_gaps = sum(1 for a in measured if a.ability_elo < MASTERY_ELO)
        out.append({
            "student_id": str(st.id), "external_ref": st.external_ref or "—",
            "mean_ability": mean_elo, "n_measured": len(measured), "n_gaps": n_gaps,
        })
    out.sort(key=lambda x: (x["mean_ability"] is None, x["mean_ability"] or 0))
    return out


def student_profile(s: Session, student_id: uuid.UUID) -> dict:
    """Fiche élève (écran héros) : profil de maîtrise + diagnostic causal + restitution."""
    st = s.get(Student, student_id)
    # B4 : badge standard par compétence si le tenant a une vue curriculaire
    crosswalk = _curriculum_context(s, st.school_id) if st is not None else None
    code_of, label_of, hard_codes, label_ar_of = _code_maps(s)
    meta = _competency_meta(s)
    rows = s.execute(
        select(StudentCompetencyAbility).where(StudentCompetencyAbility.student_id == student_id)
    ).scalars().all()

    abilities_by_code = {code_of[r.competency_id]: r.ability_elo
                         for r in rows if r.competency_id in code_of}

    competencies = []
    for r in rows:
        code = code_of.get(r.competency_id)
        if code is None:
            continue
        m = meta.get(code, {})
        competencies.append(_attach_standard({
            "code": code, "label_en": m.get("label_en", code), "label_ar": m.get("label_ar", code),
            "grade": m.get("grade"), "strand": m.get("strand", code),
            "ability_elo": round(r.ability_elo, 1), "confidence": round(r.confidence, 3),
            "n_direct": r.n_direct, "measured": r.n_direct > 0,
            # propagation ≠ mesure : jamais « maîtrisé » sans réponse directe
            "mastered": _is_mastered(r.ability_elo, r.n_direct),
        }, code, crosswalk))
    competencies.sort(key=lambda c: (c["grade"] or 0, c["ability_elo"]))

    # Diagnostics causaux sur les lacunes mesurées
    diagnoses = []
    for d in diagnose_all(abilities_by_code, hard_codes):
        diagnoses.append({
            "gap": d.gap,
            "gap_label": label_of.get(d.gap, d.gap),
            "gap_label_ar": label_ar_of.get(d.gap, d.gap),
            "root_cause": d.root_cause,
            "root_cause_label": label_of.get(d.root_cause, d.root_cause),
            "root_cause_label_ar": label_ar_of.get(d.root_cause, d.root_cause),
            "is_self": d.is_self, "chain": d.chain,
            "chain_labels": [label_of.get(c, c) for c in d.chain],
            "chain_labels_ar": [label_ar_of.get(c, c) for c in d.chain],
            "explanation": d.explanation,
        })
    diagnoses.sort(key=lambda d: (d["is_self"], len(d["chain"])), reverse=True)

    restitution = _overall_restitution(rows)
    return {
        "student_id": str(student_id),
        "external_ref": (st.external_ref if st and st.external_ref else "—"),
        "restitution": restitution,
        "competencies": competencies,
        "diagnoses": diagnoses,
        "n_measured": sum(1 for c in competencies if c["measured"]),
        "n_gaps": len(diagnoses),
    }


def _overall_restitution(rows: List[StudentCompetencyAbility]) -> dict:
    """Restitution globale (percentile/niveau/fourchette) pondérée par la confiance."""
    measured = [r for r in rows if r.n_direct > 0]
    pool = measured or list(rows)
    if not pool:
        return {"ability": None, "confidence": 0.0, "percentile": None,
                "level": None, "is_range": True, "percentile_range": None, "measured": False}
    total_w = sum(r.confidence for r in pool)
    if total_w > 0:
        ability = sum(r.ability_elo * r.confidence for r in pool) / total_w
    else:
        ability = sum(r.ability_elo for r in pool) / len(pool)
    confidence = sum(r.confidence for r in pool) / len(pool)
    rest = restitute(ability, confidence, DEFAULT_ANCHORS)
    return {
        "ability": round(ability, 1), "confidence": round(confidence, 3),
        "percentile": rest.percentile, "level": rest.level,
        "is_range": rest.is_range, "percentile_range": list(rest.percentile_range) if rest.percentile_range else None,
        "measured": bool(measured),
    }


def student_trajectory(s: Session, student_id: uuid.UUID) -> dict:
    """Vue parent (lecture seule) : trajectoire vers le supérieur, lacunes en comblement."""
    profile = student_profile(s, student_id)
    rest = profile["restitution"]
    # Lacunes « en cours de comblement » = mesurées, non maîtrisées, présentées positivement.
    closing = [
        {"label_en": c["label_en"], "label_ar": c["label_ar"],
         "ability_elo": c["ability_elo"], "confidence": c["confidence"],
         "progress": _progress_pct(c["ability_elo"])}
        for c in profile["competencies"] if c["measured"] and not c["mastered"]
    ]
    mastered = [
        {"label_en": c["label_en"], "label_ar": c["label_ar"]}
        for c in profile["competencies"] if c["measured"] and c["mastered"]
    ]
    return {
        "student_id": str(student_id), "restitution": rest,
        "n_mastered": len(mastered), "mastered": mastered,
        "closing_gaps": sorted(closing, key=lambda x: -x["progress"]),
        "next_step": _parent_next_step(s, profile["diagnoses"]),
    }


def _parent_next_step(s: Session, diagnoses: List[dict]) -> Optional[dict]:
    """« Prochaine étape » côté parent : la lacune prioritaire + une activité maison ~10 min.

    Le brief fait du parent un bénéficiaire qu'on rassure : on ne montre pas « 24 % en échec »
    mais UNE chose concrète à faire à la maison, ciblée sur la cause racine. Bilingue, sans PII,
    sans la réponse de l'exercice (l'enfant la cherche).
    """
    if not diagnoses:
        return None
    top = diagnoses[0]  # déjà trié par priorité (is_self, longueur de chaîne) dans student_profile
    return {
        "competency_code": top["root_cause"],
        "skill_label_en": top["root_cause_label"],
        "skill_label_ar": top["root_cause_label_ar"],
        "is_self": top["is_self"],
        "gap_label_en": top["gap_label"],
        "gap_label_ar": top["gap_label_ar"],
        "minutes": 10,
        "activity": _home_activity(s, top["root_cause"]),
    }


def _home_activity(s: Session, competency_code: str) -> Optional[dict]:
    """Un exercice validé de la banque (sans la réponse), présenté pour un parent, bilingue."""
    comp = s.execute(
        select(Competency).where(Competency.code == competency_code)
    ).scalar_one_or_none()
    if comp is None:
        return None
    items = [it for it in active_pool(s) if it.competency_id == comp.id]
    if not items:
        return None
    it = items[0]
    return {
        "item_id": str(it.id),
        "answer_format": it.answer_format.value,
        "example_en": (it.content_en or {}).get("stem"),
        "example_ar": (it.content_ar or {}).get("stem") if it.content_ar else None,
    }


def _progress_pct(ability_elo: float) -> int:
    """Position 0..100 d'une ability sur l'échelle d'ancrage (pour une jauge lisible parent)."""
    return int(max(0.0, min(100.0, DEFAULT_ANCHORS.percentile(ability_elo))))


def tutor_explanation(s: Session, student_id: uuid.UUID, gap_code: str) -> dict:
    """Tuteur causal (Mouvement 04) : « pourquoi cet exercice ? » pour la lacune `gap_code`.

    Déterministe, sans PII dans la sortie (seulement des libellés de compétences).
    """
    code_of, label_of, hard, label_ar_of = _code_maps(s)
    rows = s.execute(
        select(StudentCompetencyAbility).where(StudentCompetencyAbility.student_id == student_id)
    ).scalars().all()
    abilities = {code_of[r.competency_id]: r.ability_elo for r in rows if r.competency_id in code_of}
    if gap_code not in abilities or abilities[gap_code] >= MASTERY_ELO:
        # rien à expliquer : compétence non mesurée, inconnue, ou déjà maîtrisée
        return {"available": False, "competency_code": gap_code}
    d = diagnose(gap_code, abilities, hard)
    return {"available": True, **explain_diagnosis(d, label_of, label_ar_of)}


def referentiel_graph(s: Session) -> dict:
    """Graphe de compétences (nœuds + arêtes typées) — pour la viz du diagnostic causal."""
    nodes, edges = [], []
    for c in s.execute(select(Competency)).scalars():
        nodes.append({"code": c.code, "label_en": c.label_en, "label_ar": c.label_ar,
                      "grade": c.grade, "strand": ".".join(c.code.split(".")[:3])})
    code_of = {c.id: c.code for c in s.execute(select(Competency)).scalars()}
    for e in s.execute(select(CompetencyPrerequisite)).scalars():
        if e.source_id in code_of and e.target_id in code_of:
            edges.append({"source": code_of[e.source_id], "target": code_of[e.target_id],
                          "type": e.edge_type.value, "strength": round(e.correlation_strength, 2)})
    return {"nodes": nodes, "edges": edges}


def remediation_preview(s: Session, competency_code: str, lang: str = "en") -> dict:
    """Exercice de remédiation : sert un item actif de la compétence ciblée (cause racine).

    Pas d'appel LLM ni de donnée élève : on puise dans la banque déjà validée.
    """
    comp = s.execute(select(Competency).where(Competency.code == competency_code)).scalar_one_or_none()
    if comp is None:
        return {"available": False, "competency_code": competency_code}
    items = [it for it in active_pool(s) if it.competency_id == comp.id]
    if not items:
        return {"available": False, "competency_code": competency_code,
                "competency_label_en": comp.label_en, "competency_label_ar": comp.label_ar}
    it = items[0]
    content = it.content_ar if (lang == "ar" and it.content_ar) else it.content_en
    public = {k: v for k, v in (content or {}).items() if k != "answer"}
    return {
        "available": True, "competency_code": competency_code,
        "competency_label_en": comp.label_en, "competency_label_ar": comp.label_ar,
        "item_id": str(it.id), "answer_format": it.answer_format.value,
        "content": public,
    }


def class_matrix(s: Session, classroom_id: uuid.UUID) -> dict:
    """E5 · Matrice élèves × compétences (refonte B5) avec 4 états : mastered (mesuré et
    maîtrisé), progress (mesuré, prochaine étape), estimated (propagé ou confiance < 0,5),
    unmeasured (aucune ligne). Colonnes = compétences estimées pour au moins un élève de la classe,
    par niveau puis code. Ni rouge ni classement : des états, pas des scores."""
    student_ids = sorted(_class_student_ids(s, classroom_id), key=str)
    if not student_ids:
        return {"classroom_id": str(classroom_id), "competencies": [], "students": []}
    students = {st.id: st for st in s.execute(select(Student).where(Student.id.in_(student_ids))).scalars()}
    rows = s.execute(select(StudentCompetencyAbility)
                     .where(StudentCompetencyAbility.student_id.in_(student_ids))).scalars().all()
    code_of, label_of, _, label_ar_of = _code_maps(s)
    meta = _competency_meta(s)
    comp_ids = sorted({r.competency_id for r in rows if r.competency_id in code_of},
                      key=lambda c: (meta.get(code_of[c], {}).get("grade") or 0, code_of[c]))
    by_student: dict = {}
    for r in rows:
        by_student.setdefault(r.student_id, {})[r.competency_id] = r

    def state(r: Optional[StudentCompetencyAbility]) -> str:
        if r is None:
            return "unmeasured"
        if r.n_direct == 0 or r.confidence < 0.5:
            return "estimated"
        return "mastered" if r.ability_elo >= MASTERY_ELO else "progress"

    out_students = []
    for sid in student_ids:
        cells = {}
        for cid in comp_ids:
            r = by_student.get(sid, {}).get(cid)
            cells[code_of[cid]] = {"state": state(r), "elo": round(r.ability_elo, 1) if r else None,
                                   "confidence": round(r.confidence, 3) if r else None}
        st = students.get(sid)
        out_students.append({"student_id": str(sid), "external_ref": (st.external_ref if st else None) or "—",
                             "cells": cells,
                             "n_mastered": sum(1 for c in cells.values() if c["state"] == "mastered")})
    return {
        "classroom_id": str(classroom_id),
        "competencies": [{"code": code_of[c], "label_en": label_of.get(code_of[c], code_of[c]),
                          "label_ar": label_ar_of.get(code_of[c], code_of[c]),
                          "grade": meta.get(code_of[c], {}).get("grade")} for c in comp_ids],
        "students": out_students,
    }
