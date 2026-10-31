"""Session d'évaluation (Epic 4). Lie un élève à une suite de réponses adaptatives."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ResponseLanguage, native_enum, utcnow, uuid_pk


class AssessmentSession(Base):
    __tablename__ = "assessment_session"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String, default="active")  # active | completed
    # Langue de l'UI pendant la session (C-0) : chaque Response créée dans la session
    # en hérite — traçabilité de la langue servie, prérequis des analyses DIF EN/AR.
    locale: Mapped[ResponseLanguage] = mapped_column(
        native_enum(ResponseLanguage, "response_language"),
        default=ResponseLanguage.EN, server_default="en",
    )
    target_competency_ids: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    # Refonte B1 : une session d'élève rejoint au plus un check-in de classe.
    checkin_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("checkin.id", ondelete="SET NULL"), default=None, index=True
    )
    stop_reason: Mapped[Optional[str]] = mapped_column(String, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
