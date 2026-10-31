"""Mini-leçons (refonte B3) — chargement, validation, choix pour le plan, arabe du linguiste.

Le contenu est éditorial : les fichiers `data/lessons/*.json` sont rédigés par un humain
(docs/refonte/data/lessons/README.md), seedés de façon idempotente (upsert sur `key`). La
machine ne rédige rien ; elle valide la forme (pydantic), suit le statut et attache la meilleure
leçon disponible à chaque action du plan.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.models.base import EdgeType, LessonOrigin, LessonStatus
from src.models.competency import Competency, CompetencyPrerequisite
from src.models.lesson import MiniLesson

LESSONS_DIR = Path(__file__).resolve().parents[2] / "data" / "lessons"
STEP_KINDS = ("warmup", "model", "guided", "exit")
_STATUS_RANK = {LessonStatus.ACTIVE: 2, LessonStatus.LINGUIST_VALIDATED: 1, LessonStatus.DRAFT: 0}


class LessonStep(BaseModel):
    kind: Literal["warmup", "model", "guided", "exit"]
    minutes: int = Field(gt=0, le=60)
    body_en: str = Field(min_length=1)
    body_ar: Optional[str] = None
    items: Optional[List[dict]] = None     # questions de sortie (phase E : items d'école)


class LessonDoc(BaseModel):
    """Forme d'un fichier de leçon. `key` = nom du fichier sans extension."""
    key: str = Field(min_length=3)
    competency: str                        # code du référentiel
    title_en: str = Field(min_length=1)
    title_ar: Optional[str] = None
    duration_min: int = Field(gt=0, le=60)
    steps: List[LessonStep] = Field(min_length=1)
    version: int = 1

    @field_validator("steps")
    @classmethod
    def _kinds_in_order(cls, steps):
        order = [STEP_KINDS.index(st.kind) for st in steps]
        if order != sorted(order):
            raise ValueError("étapes dans l'ordre warmup → model → guided → exit")
        return steps


class LessonError(ValueError):
    pass


def arabic_complete(lesson: MiniLesson) -> bool:
    return bool(lesson.title_ar and lesson.title_ar.strip()) and all(
        (st.get("body_ar") or "").strip() for st in (lesson.steps or []))


def load_doc(path: Path) -> LessonDoc:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LessonError(f"{path.name} : JSON invalide ({e})")
    data.setdefault("key", path.stem)
    try:
        return LessonDoc.model_validate(data)
    except ValidationError as e:
        raise LessonError(f"{path.name} : {e.errors()[0].get('msg', e)}")


def upsert_lesson(s: Session, doc: LessonDoc, *, origin: LessonOrigin = LessonOrigin.ATLAS,
                  owner_school_id: Optional[uuid.UUID] = None) -> "tuple[MiniLesson, bool]":
    """Crée ou met à jour la leçon `doc.key`. Le statut n'est jamais rabaissé par un re-seed,
    sauf si le contenu arabe validé a changé (il repasse en draft : à revalider)."""
    comp = s.execute(select(Competency).where(Competency.code == doc.competency)).scalar_one_or_none()
    if comp is None:
        raise LessonError(f"{doc.key} : compétence inconnue {doc.competency}")
    steps = [st.model_dump(exclude_none=True) for st in doc.steps]
    lesson = s.execute(select(MiniLesson).where(MiniLesson.key == doc.key)).scalar_one_or_none()
    created = lesson is None
    if lesson is None:
        lesson = MiniLesson(competency_id=comp.id, key=doc.key, title_en=doc.title_en, title_ar=doc.title_ar,
                            duration_min=doc.duration_min, steps=steps, origin=origin,
                            owner_school_id=owner_school_id, version=doc.version)
        s.add(lesson)
    else:
        ar_changed = (lesson.title_ar != doc.title_ar) or (
            [st.get("body_ar") for st in lesson.steps or []] != [st.get("body_ar") for st in steps])
        lesson.competency_id, lesson.title_en, lesson.title_ar = comp.id, doc.title_en, doc.title_ar
        lesson.duration_min, lesson.steps, lesson.version = doc.duration_min, steps, doc.version
        if ar_changed and lesson.status != LessonStatus.DRAFT:
            lesson.status = LessonStatus.DRAFT
    s.flush()
    return lesson, created


def seed_lessons(s: Session, directory: Path = LESSONS_DIR, *, dry_run: bool = False) -> Dict[str, object]:
    created, updated, errors = [], [], []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue                                  # _TEMPLATE.json et consorts
        try:
            doc = load_doc(path)
            if dry_run:
                comp = s.execute(select(Competency).where(Competency.code == doc.competency)).scalar_one_or_none()
                if comp is None:
                    raise LessonError(f"{doc.key} : compétence inconnue {doc.competency}")
                updated.append(doc.key)
                continue
            _, was_created = upsert_lesson(s, doc)
            (created if was_created else updated).append(doc.key)
        except LessonError as e:
            errors.append(str(e))
    return {"created": created, "updated": updated, "errors": errors}


def pick_lesson(s: Session, competency_id: uuid.UUID) -> Optional[MiniLesson]:
    """La meilleure leçon Atlas de la compétence : statut le plus avancé, puis version la plus
    haute. None s'il n'y en a pas (l'action du plan reste sans leçon)."""
    rows = s.execute(select(MiniLesson).where(MiniLesson.competency_id == competency_id,
                                              MiniLesson.origin == LessonOrigin.ATLAS)).scalars().all()
    if not rows:
        return None
    return max(rows, key=lambda l: (_STATUS_RANK[l.status], l.version, str(l.id)))


def lessons_for(s: Session, competency_id: uuid.UUID) -> List[MiniLesson]:
    return list(s.execute(select(MiniLesson).where(MiniLesson.competency_id == competency_id)
                          .order_by(MiniLesson.version.desc())).scalars())


def payload(lesson: MiniLesson, comp: Optional[Competency] = None, *, full: bool = True) -> dict:
    out = {"id": str(lesson.id), "key": lesson.key, "competency_id": str(lesson.competency_id),
           "title_en": lesson.title_en, "title_ar": lesson.title_ar, "duration_min": lesson.duration_min,
           "status": lesson.status.value, "origin": lesson.origin.value, "version": lesson.version,
           "arabic_complete": arabic_complete(lesson)}
    if comp is not None:
        out["competency"] = {"code": comp.code, "label_en": comp.label_en, "label_ar": comp.label_ar}
    if full:
        out["steps"] = lesson.steps
    return out


def set_arabic(s: Session, lesson: MiniLesson, *, title_ar: Optional[str], bodies_ar: List[Optional[str]],
               by: uuid.UUID) -> MiniLesson:
    """Le linguiste pose ou corrige l'arabe (titre + une entrée par étape). Repasse en draft : toute
    modification de l'arabe doit être revalidée."""
    if len(bodies_ar) != len(lesson.steps or []):
        raise LessonError(f"{len(lesson.steps or [])} étapes attendues, {len(bodies_ar)} fournies")
    steps = []
    for st, body in zip(lesson.steps, bodies_ar):
        new = dict(st)
        if body is None or not body.strip():
            new.pop("body_ar", None)
        else:
            new["body_ar"] = body.strip()
        steps.append(new)
    lesson.steps, lesson.title_ar = steps, (title_ar or "").strip() or None
    if lesson.status != LessonStatus.DRAFT:
        lesson.status = LessonStatus.DRAFT
    s.flush()
    log_action(s, action="lesson.set_arabic", user_id=by, resource_type="mini_lesson", resource_id=lesson.id)
    return lesson


def validate_arabic(s: Session, lesson: MiniLesson, *, by: uuid.UUID) -> MiniLesson:
    if lesson.status != LessonStatus.DRAFT:
        raise LessonError("seule une leçon `draft` se valide")
    if not arabic_complete(lesson):
        raise LessonError("arabe incomplet : titre et chaque étape doivent être traduits")
    lesson.status = LessonStatus.LINGUIST_VALIDATED
    s.flush()
    log_action(s, action="lesson.validate_ar", user_id=by, resource_type="mini_lesson", resource_id=lesson.id)
    return lesson


def activate(s: Session, lesson: MiniLesson, *, by: uuid.UUID) -> MiniLesson:
    if lesson.status != LessonStatus.LINGUIST_VALIDATED:
        raise LessonError("une leçon s'active après validation de l'arabe")
    lesson.status = LessonStatus.ACTIVE
    s.flush()
    log_action(s, action="lesson.activate", user_id=by, resource_type="mini_lesson", resource_id=lesson.id)
    return lesson


# --- éditeur côté Atlas (O5) : la même validation que les fichiers, sans fichier -----------

def coverage(s: Session) -> List[dict]:
    """Causes racines possibles (prérequis HARD), classées par ce qu'elles débloquent en aval,
    avec leurs leçons et statuts — ce qui manque saute aux yeux (Q3)."""
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    dep: Dict[uuid.UUID, set] = {}
    for e in s.execute(select(CompetencyPrerequisite).where(CompetencyPrerequisite.edge_type == EdgeType.HARD)).scalars():
        dep.setdefault(e.source_id, set()).add(e.target_id)
    lessons: Dict[uuid.UUID, List[MiniLesson]] = {}
    for l in s.execute(select(MiniLesson)).scalars():
        lessons.setdefault(l.competency_id, []).append(l)

    def downstream(c, seen=None):
        seen = seen if seen is not None else set()
        for t in dep.get(c, ()):
            if t not in seen:
                seen.add(t); downstream(t, seen)
        return seen

    out = []
    for cid in sorted(dep, key=lambda c: (-len(downstream(c)), comps[c].grade, comps[c].code)):
        c = comps[cid]
        ls = sorted(lessons.get(cid, []), key=lambda l: (-_STATUS_RANK[l.status], -l.version))
        out.append({"competency_id": str(cid), "code": c.code, "label_en": c.label_en, "label_ar": c.label_ar,
                    "grade": c.grade, "unlocks": len(downstream(cid)),
                    "lessons": [payload(l, full=False) for l in ls],
                    "best_status": ls[0].status.value if ls else None})
    return out


def doc_from_payload(data: dict, *, key: Optional[str] = None) -> LessonDoc:
    """Même forme que les fichiers ; `key` dérivée de la compétence et de la version si absente."""
    data = dict(data)
    if key:
        data["key"] = key
    elif not data.get("key"):
        data["key"] = f"{data.get('competency', 'LESSON')}.v{int(data.get('version', 1))}"
    try:
        return LessonDoc.model_validate(data)
    except ValidationError as e:
        err = e.errors()[0]
        raise LessonError(f"{'.'.join(str(x) for x in err.get('loc', ()))} : {err.get('msg', e)}")


def all_lessons(s: Session) -> List[MiniLesson]:
    return list(s.execute(select(MiniLesson).order_by(MiniLesson.key)).scalars())
