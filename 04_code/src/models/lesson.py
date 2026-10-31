"""Mini-leçon (refonte B3, docs/refonte/03 « 0027 », migration 0028).

Leçon courte bilingue rattachée à UNE compétence du graphe. Contenu éditorial : rédigé par un
humain (`data/lessons/*.json`, seedé par scripts/seed_lessons.py), l'arabe validé par le
linguiste. `steps` : liste `{kind: warmup|model|guided|exit, minutes, body_en, body_ar?, items?}`
validée par `lesson_service.LessonDoc` à l'écriture.

Statuts : draft (EN rédigé) → linguist_validated (AR complet et validé) → active (servie dans le
plan). Le plan attache la meilleure leçon disponible de la racine ; l'écran affiche son statut.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, LessonOrigin, LessonStatus, TimestampMixin, native_enum, uuid_pk


class MiniLesson(Base, TimestampMixin):
    __tablename__ = "mini_lesson"
    id: Mapped[uuid.UUID] = uuid_pk()
    competency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competency.id", ondelete="RESTRICT"), index=True
    )
    # Clé éditoriale stable (nom du fichier, ex. `MATH.G3.NF.UNIT_FRACTION.v1`) : upsert du seed.
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    title_en: Mapped[str] = mapped_column(String)
    title_ar: Mapped[Optional[str]] = mapped_column(String, default=None)
    duration_min: Mapped[int] = mapped_column(Integer)
    steps: Mapped[list] = mapped_column(JSON)
    origin: Mapped[LessonOrigin] = mapped_column(
        native_enum(LessonOrigin, "lesson_origin"), default=LessonOrigin.ATLAS, server_default="atlas"
    )
    owner_school_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), default=None
    )
    status: Mapped[LessonStatus] = mapped_column(
        native_enum(LessonStatus, "lesson_status"), default=LessonStatus.DRAFT, server_default="draft", index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
