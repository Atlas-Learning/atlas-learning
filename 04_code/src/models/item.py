"""Modèle Item (T2.1) — 1 item mesure UNE seule compétence.

Règle stricte (data model §4) : un item multi-compétences pollue le signal Elo.
Le contenu (content_en / content_ar) est du JSONB validé par Pydantic à l'écriture.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from .base import (
    AnswerFormat,
    Base,
    ItemFlagReason,
    ItemFlagStatus,
    ItemOrigin,
    ItemStatus,
    TimestampMixin,
    native_enum,
    utcnow,
    uuid_pk,
)

# JSONB sur Postgres (prod), JSON sur SQLite (dev/CI) — même API côté Python.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class ItemContent(BaseModel):
    """Forme validée du contenu d'un item. Champs métier requis : stem + answer.

    `extra="allow"` : tolère des clés additionnelles (ex. `format`) sans les perdre.
    """
    model_config = ConfigDict(extra="allow")

    stem: str
    options: Optional[List[str]] = None  # pour MCQ
    answer: str


def _default_elo(context) -> float:  # noqa: ANN001
    """difficulty_elo = difficulty_prior à la création si non fourni (AC3)."""
    return context.get_current_parameters()["difficulty_prior"]


class Item(Base, TimestampMixin):
    __tablename__ = "item"

    id: Mapped[uuid.UUID] = uuid_pk()
    competency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competency.id", ondelete="RESTRICT"), index=True
    )  # RESTRICT : interdit de supprimer une compétence qui a des items vivants

    content_en: Mapped[dict] = mapped_column(JSONType)
    # content_ar reste vide jusqu'à la traduction T2.4 (revue EN d'abord, T2.3).
    content_ar: Mapped[Optional[dict]] = mapped_column(JSONType, default=None)
    answer_format: Mapped[AnswerFormat] = mapped_column(
        native_enum(AnswerFormat, "answer_format")
    )

    difficulty_prior: Mapped[float] = mapped_column()
    difficulty_elo: Mapped[float] = mapped_column(default=_default_elo)
    n_responses: Mapped[int] = mapped_column(default=0)

    context_tags: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[ItemStatus] = mapped_column(
        native_enum(ItemStatus, "item_status"), default=ItemStatus.AI_GENERATED
    )
    provenance: Mapped[dict] = mapped_column(JSONType, default=dict)
    ar_validated: Mapped[bool] = mapped_column(default=False)

    # --- Refonte A2 : origine, gabarit, versions (docs/refonte/03, « 0024 ») ---
    origin: Mapped[ItemOrigin] = mapped_column(
        native_enum(ItemOrigin, "item_origin"),
        default=ItemOrigin.ATLAS_TEMPLATE, server_default="atlas_template",
    )
    # Gabarit d'origine (ex. `MATH.G4.NF.ADD_LIKE#03`) : une faute se corrige AU GABARIT, puis
    # tous les items du gabarit repartent en nouvelle version (A3). NULL = banque antérieure
    # à A2, regénérer avec scripts/generate_bank_deterministic.py --reset pour le remplir.
    template_key: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Item remplacé par cette version. Ses réponses restent attachées à l'ancienne version.
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("item.id", ondelete="SET NULL"), default=None
    )
    # Posé par review.reset_calibration : les réponses antérieures ne pèsent plus sur
    # difficulty_elo (n_responses repart de 0, difficulty_elo de difficulty_prior).
    calibration_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Items d'école seulement (phase E) : l'école propriétaire ; l'item part avec elle.
    owner_school_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), default=None, index=True
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    @validates("content_en", "content_ar")
    def _validate_content(self, key: str, value):
        # content_ar peut être None/vide tant que la traduction T2.4 n'est pas faite.
        if key == "content_ar" and not value:
            return value
        # contenu non conforme à ItemContent → rejet (pydantic.ValidationError)
        ItemContent.model_validate(value)
        return value

    def __repr__(self) -> str:
        return f"<Item {self.id} comp={self.competency_id} {self.answer_format} v{self.version}>"


class ItemFlag(Base):
    """Signalement d'un item (refonte A2) : un enseignant, un coordinateur ou le staff signale
    une réponse fausse, plusieurs bonnes réponses, un énoncé ambigu, un problème d'arabe…

    Le signalement n'altère JAMAIS le statut de l'item par lui-même : il entre dans la file de
    revue ; l'acceptation passe par la machine à états (`review.resolve_flag` → quarantaine
    via `promote`). `school_id` et `raised_by` sont informatifs (tenant d'origine, auteur) :
    ils survivent en NULL à la suppression de l'école ou du compte (aucune PII élève ici).
    """
    __tablename__ = "item_flag"
    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("item.id", ondelete="CASCADE"), index=True
    )
    school_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("school.id", ondelete="SET NULL"), default=None, index=True
    )
    raised_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    reason: Mapped[ItemFlagReason] = mapped_column(native_enum(ItemFlagReason, "item_flag_reason"))
    comment: Mapped[Optional[str]] = mapped_column(String, default=None)
    status: Mapped[ItemFlagStatus] = mapped_column(
        native_enum(ItemFlagStatus, "item_flag_status"),
        default=ItemFlagStatus.OPEN, server_default="open", index=True,
    )
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
