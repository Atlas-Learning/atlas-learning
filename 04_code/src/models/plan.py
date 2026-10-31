"""Plan hebdomadaire, actions, membres, preuves (refonte B2/B4, docs/refonte/03 « 0026 »).

- `WeeklyPlan` : le plan d'une classe pour une semaine, généré à la clôture d'un check-in
  `full`. Un seul `active` par (classe, semaine) — garanti par le service (le précédent passe
  `superseded`), pas par une contrainte partielle (non portable SQLite).
- `PlanAction` : une action = un groupe d'élèves partageant une cause racine + la compétence où
  l'erreur se voit + la phrase « parce que » (EN et AR, déterministe) + une mini-leçon (B3).
- `PlanActionMember` : les membres (proposés par Atlas, ajoutés ou retirés par l'enseignant —
  la correction est enregistrée, jamais effacée).
- `Proof` (B4) : par élève et par action re-mesurée, avant / après, figé à la création de
  l'action pour `before_*`.

Toutes les tables qui portent un `student_id` cascadent à l'effacement de l'élève (rétention).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base, MemberSource, PlanActionKind, PlanActionStatus, PlanConfidence, PlanStatus, ProofOutcome,
    native_enum, utcnow, uuid_pk,
)


class WeeklyPlan(Base):
    __tablename__ = "weekly_plan"
    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("school.id", ondelete="CASCADE"), index=True)
    classroom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classroom.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    source_checkin_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("checkin.id", ondelete="SET NULL"), default=None
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[PlanStatus] = mapped_column(
        native_enum(PlanStatus, "plan_status"), default=PlanStatus.ACTIVE, index=True
    )


class PlanAction(Base):
    __tablename__ = "plan_action"
    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("weekly_plan.id", ondelete="CASCADE"), index=True)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("school.id", ondelete="CASCADE"), index=True)
    kind: Mapped[PlanActionKind] = mapped_column(native_enum(PlanActionKind, "plan_action_kind"))
    rank: Mapped[int] = mapped_column(Integer)
    root_cause_competency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competency.id", ondelete="RESTRICT")
    )
    blocked_competency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competency.id", ondelete="RESTRICT")
    )
    # Mini-leçon (B3, table mini_lesson à venir) : colonne posée, FK ajoutée par la migration B3.
    lesson_id: Mapped[Optional[uuid.UUID]] = mapped_column(default=None)
    confidence: Mapped[PlanConfidence] = mapped_column(native_enum(PlanConfidence, "plan_confidence"))
    because_en: Mapped[str] = mapped_column(Text)
    because_ar: Mapped[str] = mapped_column(Text)
    status: Mapped[PlanActionStatus] = mapped_column(
        native_enum(PlanActionStatus, "plan_action_status"), default=PlanActionStatus.PROPOSED
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class PlanActionMember(Base):
    __tablename__ = "plan_action_member"
    action_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plan_action.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("school.id", ondelete="CASCADE"), index=True)
    source: Mapped[MemberSource] = mapped_column(
        native_enum(MemberSource, "member_source"), default=MemberSource.ATLAS
    )
    removed_by_teacher: Mapped[bool] = mapped_column(Boolean, default=False)
    # ex. « 1/3 + 1/6 = 2/9 on 3 of 4 items » — rempli quand l'analyse des réponses existera.
    observed_error: Mapped[Optional[str]] = mapped_column(String, default=None)


class Proof(Base):
    __tablename__ = "proof"
    id: Mapped[uuid.UUID] = uuid_pk()
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_action.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("student.id", ondelete="CASCADE"), index=True)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("school.id", ondelete="CASCADE"), index=True)
    competency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competency.id", ondelete="RESTRICT"))
    before_elo: Mapped[float] = mapped_column(Float)
    before_confidence: Mapped[float] = mapped_column(Float)
    after_elo: Mapped[Optional[float]] = mapped_column(Float, default=None)
    after_confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    ci_low: Mapped[Optional[float]] = mapped_column(Float, default=None)
    ci_high: Mapped[Optional[float]] = mapped_column(Float, default=None)
    outcome: Mapped[ProofOutcome] = mapped_column(
        native_enum(ProofOutcome, "proof_outcome"), default=ProofOutcome.NOT_RECHECKED
    )
    recheck_checkin_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("checkin.id", ondelete="SET NULL"), default=None
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
