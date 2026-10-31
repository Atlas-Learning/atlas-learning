"""Tables de mesure (Epic 3, DataModel §5).

School/Student : socle tenant minimal (RBAC complet = Epic 6).
Response : événement brut, APPEND-ONLY.
StudentCompetencyAbility : état Elo par élève × compétence (direct + propagé).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ResponseLanguage, TimestampMixin, native_enum, utcnow, uuid_pk


class School(Base):
    __tablename__ = "school"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), default=None, index=True
    )
    external_ref: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)  # orgUnit id
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    # Legal hold tenant-large (instruction documentée du controller / litige école) : suspend
    # la purge de rétention de TOUS ses élèves tant qu'il est posé (cf. purge_retention).
    legal_hold: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    legal_hold_reason: Mapped[Optional[str]] = mapped_column(String, default=None)
    # Refonte B6 (Q5) : message « votre plan est prêt », réglé PAR ÉCOLE. NULL = défaut dérivé du
    # pays (dimanche en Arabie saoudite, lundi ailleurs ; 7 h ; fuseau du pays, sinon UTC).
    country: Mapped[Optional[str]] = mapped_column(String(2), default=None)          # ISO 3166-1 alpha-2
    plan_mail_weekday: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # 0 = lundi … 6 = dimanche
    plan_mail_hour: Mapped[Optional[int]] = mapped_column(Integer, default=None)     # heure locale 0–23
    timezone: Mapped[Optional[str]] = mapped_column(String, default=None)            # IANA, ex. Asia/Dubai


class Student(Base):
    __tablename__ = "student"
    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), index=True
    )
    # Classe principale (homeroom). L'ensemble des inscriptions vit dans student_classroom
    # (M:N) — un élève peut suivre des classes de spécialité en plus de sa classe principale.
    classroom_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("classroom.id", ondelete="SET NULL"), default=None, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None, index=True
    )
    external_ref: Mapped[Optional[str]] = mapped_column(String, default=None)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    # Legal hold individuel : suspend la purge de rétention de CET élève (soft-deleted mais
    # sous obligation de conservation/litige) tant qu'il est posé (cf. purge_retention).
    legal_hold: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    legal_hold_reason: Mapped[Optional[str]] = mapped_column(String, default=None)


class Response(Base):
    """Événement de réponse — append-only (ni update, ni delete)."""
    __tablename__ = "response"
    # Anti double-submit atomique (revue 2026-07-07) : au plus UNE réponse par
    # (session_id, item_id) — le doublon simultané échoue au flush (IntegrityError → 409).
    # Les réponses HORS session (session_id NULL : seeds, moteur appelé directement) ne
    # sont pas concernées : SQL (Postgres comme SQLite) autorise les NULL multiples.
    __table_args__ = (
        UniqueConstraint("session_id", "item_id", name="uq_response_session_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("item.id", ondelete="RESTRICT"), index=True
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(index=True)  # dénormalisé (query rapide)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    # Option choisie par l'élève (refonte B2/Q16) : permet l'analyse des distracteurs
    # (« 1/3 + 1/6 = 2/9 on 3 of 4 items »). NULL pour les réponses antérieures.
    selected: Mapped[Optional[str]] = mapped_column(String, default=None)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(default=None)  # FK session = Epic 4
    # Langue SERVIE (C-0) : dérivée de la locale de session, 'en' hors session. Le
    # server_default 'en' couvre les lignes pré-migration (état de fait : UI anglaise).
    language: Mapped[ResponseLanguage] = mapped_column(
        native_enum(ResponseLanguage, "response_language"),
        default=ResponseLanguage.EN, server_default="en",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentCompetencyAbility(Base, TimestampMixin):
    __tablename__ = "student_competency_ability"

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), primary_key=True
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competency.id", ondelete="CASCADE"), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), index=True
    )

    ability_elo: Mapped[float] = mapped_column(Float)
    n_direct: Mapped[int] = mapped_column(Integer, default=0)       # réponses DIRECTES
    confidence: Mapped[float] = mapped_column(Float, default=0.0)   # [0..1]
    last_measured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
