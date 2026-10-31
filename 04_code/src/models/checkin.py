"""Check-in de classe (refonte B1, docs/refonte/03 « 0025 »).

Session de classe lancée par l'enseignant et rejointe par un code à 4 chiffres. `full` =
diagnostic (génère le plan de la semaine à la clôture, B2) ; `targeted` = re-mesure d'un groupe
d'une action du plan (calcule la preuve à la clôture, B4). Chaque élève qui rejoint ouvre une
`AssessmentSession` liée au check-in ; la progression exposée pendant le check-in est ANONYME
(invariant 5 : ni nom, ni identifiant d'élève).

`student_ids` (targeted) porte des identifiants d'élèves : couvert par l'effacement
(`compliance.erase_student`) — rétention, docs/refonte/03.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CheckInKind, CheckInStatus, native_enum, utcnow, uuid_pk


class CheckIn(Base):
    __tablename__ = "checkin"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), index=True
    )
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[CheckInKind] = mapped_column(native_enum(CheckInKind, "checkin_kind"))
    # Action du plan re-mesurée (targeted). FK posée par 0026 (table plan_action, B2).
    plan_action_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("plan_action.id", ondelete="SET NULL", use_alter=True, name="fk_checkin_plan_action"),
        default=None,
    )
    # Compétences visées (liste d'UUID en str). Vide/None = toute la banque active (diagnostic).
    competency_ids: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    # Restriction aux membres du groupe (targeted) ; None = toute la classe.
    student_ids: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    code: Mapped[str] = mapped_column(String(4), index=True)
    status: Mapped[CheckInStatus] = mapped_column(
        native_enum(CheckInStatus, "checkin_status"), default=CheckInStatus.OPEN, index=True,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
