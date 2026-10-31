"""Hiérarchie tenant + utilisateurs (Epic 6, T6.1).

organization → school → classroom → student. Users + memberships (rôle scopé).
Liens spécifiques : enseignant→classes, parent→enfants, élève→compte.
Toute donnée élève porte déjà school_id (response/ability/session). Soft delete sur
les entités importantes.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CurriculumView, Role, TimestampMixin, native_enum, utcnow, uuid_pk


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String)
    # Domaine Google Workspace primaire (ex. "school.edu") — clé de résolution du tenant.
    domain: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, default=None)
    external_ref: Mapped[Optional[str]] = mapped_column(String, default=None)  # Google customer id
    seats: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # sièges sous licence
    # Framework curriculaire affiché aux vues de restitution (B3) — un seul par tenant
    # en v1 ; ATLAS = vue neutre historique (défauts python + serveur : zéro régression).
    curriculum_view: Mapped[CurriculumView] = mapped_column(
        native_enum(CurriculumView, "curriculum_view"),
        default=CurriculumView.ATLAS, server_default="ATLAS",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class Classroom(Base):
    __tablename__ = "classroom"
    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String)
    external_ref: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)  # group id
    # Niveau (grade) de la classe — rempli par le roster quand la source l'expose (OneRoster
    # `grades`), sinon saisi en admin (PATCH /classrooms/{id}/grade). Pilote la portée du
    # `dept_lead` (dept_lead_scope). [À CLARIFIER] Year (UK) ↔ Grade : aucune conversion
    # ici (Q6 de docs/refonte/05-questions-ouvertes.md).
    grade: Mapped[Optional[int]] = mapped_column(Integer, index=True, default=None)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class AppUser(Base, TimestampMixin):
    """Identité applicative. Auth = SSO (IdP) uniquement : plus de mot de passe ni de secret
    TOTP en base (MFA portée par l'IdP). L'identité durable est ancrée sur `external_ref`
    (id immuable de la source : IdP / annuaire de rostering), jamais l'email."""
    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    external_ref: Mapped[Optional[str]] = mapped_column(String, index=True, default=None)  # id IdP/annuaire
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


class Membership(Base):
    """Rôle d'un utilisateur, scopé à une organisation et/ou une école."""
    __tablename__ = "membership"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(native_enum(Role, "role"))
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), default=None, index=True
    )
    school_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("school.id", ondelete="CASCADE"), default=None, index=True
    )


class DeptLeadScope(Base):
    """Niveaux couverts par une membership `dept_lead`.

    Un coordinateur couvre une ou plusieurs années d'UNE école : la membership porte
    `school_id`, cette table porte les grades. Sa portée effective = les classes vivantes de
    cette école dont `Classroom.grade` est dans la liste (résolue par `build_user_context`).
    """
    __tablename__ = "dept_lead_scope"
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("membership.id", ondelete="CASCADE"), primary_key=True
    )
    grade: Mapped[int] = mapped_column(Integer, primary_key=True)


class TeacherClassroom(Base):
    """Affectation enseignant → classe."""
    __tablename__ = "teacher_classroom"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.id", ondelete="CASCADE"), primary_key=True
    )


class StudentClassroom(Base):
    """Inscription élève → classe (M:N).

    Source de vérité des inscriptions : un élève peut être dans **plusieurs** classes
    (classe principale + spécialités). La « classe principale » (homeroom) reste pointée
    par `Student.classroom_id` ; cette table porte l'ensemble complet des inscriptions.
    """
    __tablename__ = "student_classroom"
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), primary_key=True
    )
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.id", ondelete="CASCADE"), primary_key=True
    )


class ParentStudent(Base):
    """Lien parent → enfant (lecture seule).

    `source` = autorité qui a établi le lien : "roster" (Google Classroom, miroir) ou
    "staff" (rattachement manuel par un prof/admin). Une sync Classroom ne réconcilie QUE
    les liens "roster" → elle n'efface jamais un lien "staff". Jamais auto-déclaré par le parent.
    """
    __tablename__ = "parent_student"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String, default="roster")


class TenantIntegration(Base, TimestampMixin):
    """Configuration de l'intégration d'annuaire (Google Workspace) d'une organisation.

    `status` opérationnel (pending → connected → error), pas un enum métier.
    Le secret d'accès (service account) est GLOBAL au vendeur (app Marketplace), donc
    ici on ne stocke que le ciblage : domaine, admin à impersonner, customer id.
    """
    __tablename__ = "tenant_integration"
    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String, default="google")
    status: Mapped[str] = mapped_column(String, default="pending")
    admin_email: Mapped[Optional[str]] = mapped_column(String, default=None)  # impersonation
    customer_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[Optional[str]] = mapped_column(String, default=None)


class RosterRun(Base):
    """Trace d'audit d'une synchronisation de rostering (must-have : preuve d'achat)."""
    __tablename__ = "roster_run"
    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String, default="ok")  # ok | error
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    deactivated_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_deactivations: Mapped[int] = mapped_column(Integer, default=0)  # retenues (garde-fou)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[str]] = mapped_column(String, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
