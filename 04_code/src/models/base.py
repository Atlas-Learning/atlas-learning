"""Base SQLAlchemy 2.0 + enums du référentiel Atlas Learning.

Conventions projet :
- UUID en PK
- timestamptz (created_at / updated_at)
- enums Postgres natifs
- soft delete via deleted_at

Convention temporelle (revue 2026-07-07 — intégrité d'audit / résidence UAE) :
- TOUT timestamp est produit par `utcnow()` (aware, UTC) — jamais `datetime.now()`
  naïf (heure locale du serveur : ambigu, non auditable) ;
- TOUTE colonne timestamp est `DateTime(timezone=True)` (timestamptz sur Postgres) ;
- SQLite (dev/CI) ne stocke pas l'offset et RESTITUE des datetimes NAÏFS même sur
  colonne tz-aware : un naïf relu de la base est PAR CONVENTION de l'UTC. Toute
  comparaison/soustraction avec un datetime aware passe par `ensure_utc()` —
  sinon TypeError (mélange naïf/aware).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """« Maintenant » AWARE en UTC — l'unique source d'horodatage du projet.

    Remplace tous les `datetime.now()` naïfs (heure locale) : les timestamps de
    mesure/audit/session doivent être non ambigus pour l'audit et le mandat
    timestamptz (résidence UAE de données de mineurs).
    """
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise en aware-UTC un datetime relu de la base (ou fourni par l'appelant).

    Patron unique du projet : Postgres (timestamptz) restitue des datetimes aware ;
    SQLite (dev/CI) restitue des datetimes NAÏFS même sur colonne tz-aware — comme
    tout est écrit en UTC (cf. `utcnow`), un naïf est réinterprété UTC tel quel.
    Un aware non-UTC est converti. À appliquer AVANT toute comparaison/soustraction
    avec un datetime aware (expiration, stopping, rétention, fenêtres d'analyse).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def native_enum(enum_cls, name: str) -> SAEnum:
    """Colonne enum qui stocke la VALEUR du membre (ex. 'active'), pas son nom.

    Aligne le stockage sur les valeurs du data model (draft/active, expert/empirical)
    et garantit la cohérence avec les labels des enums natifs Postgres créés par Alembic.
    Sans ça, SQLAlchemy persisterait le nom du membre ('ACTIVE') → rejet par Postgres.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


# --- Enums métier ---

class Subject(str, enum.Enum):
    MATH = "MATH"


class CognitiveLevel(str, enum.Enum):
    RECALL = "RECALL"
    APPLY = "APPLY"
    REASON = "REASON"


class CompetencyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class EdgeType(str, enum.Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class WeightSource(str, enum.Enum):
    EXPERT = "expert"
    EMPIRICAL = "empirical"


class ItemStatus(str, enum.Enum):
    AI_GENERATED = "ai_generated"
    HUMAN_REVIEWED = "human_reviewed"
    LINGUIST_VALIDATED = "linguist_validated"
    ACTIVE = "active"
    QUARANTINED = "quarantined"


class ItemOrigin(str, enum.Enum):
    """Source d'un item (refonte A2) : gabarit déterministe Atlas, ou item d'école (phase E)."""
    ATLAS_TEMPLATE = "atlas_template"
    SCHOOL = "school"


class ItemFlagReason(str, enum.Enum):
    """Motif d'un signalement d'item par un enseignant, un coordinateur ou le staff (A2)."""
    WRONG_ANSWER_KEY = "wrong_answer_key"
    SEVERAL_CORRECT = "several_correct"
    UNCLEAR_WORDING = "unclear_wording"
    ARABIC = "arabic"
    OTHER = "other"


class ItemFlagStatus(str, enum.Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CheckInKind(str, enum.Enum):
    """Check-in de classe (refonte B1) : diagnostic complet ou re-mesure ciblée d'un groupe."""
    FULL = "full"
    TARGETED = "targeted"


class CheckInStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    OPEN = "open"
    CLOSED = "closed"


class PlanStatus(str, enum.Enum):
    """Plan hebdomadaire d'une classe (refonte B2) : un seul actif par (classe, semaine)."""
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class PlanActionKind(str, enum.Enum):
    RETEACH = "reteach"
    RECHECK = "recheck"


class PlanConfidence(str, enum.Enum):
    MEASURED = "measured"
    PARTLY_ESTIMATED = "partly_estimated"


class PlanActionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    DONE = "done"
    DISMISSED = "dismissed"


class MemberSource(str, enum.Enum):
    ATLAS = "atlas"
    TEACHER_ADDED = "teacher_added"


class ProofOutcome(str, enum.Enum):
    UNLOCKED = "unlocked"
    UNCHANGED = "unchanged"
    NOT_RECHECKED = "not_rechecked"


class AnswerFormat(str, enum.Enum):
    MCQ = "MCQ"
    NUMERIC = "NUMERIC"
    SHORT = "SHORT"


class ResponseLanguage(str, enum.Enum):
    """Langue SERVIE à l'élève (C-0, Lot C) — pas la langue de l'item (bilingue en base).

    Enregistrée sur chaque Response (et comme locale de session) : sans elle, aucune
    analyse DIF EN/AR n'est possible sur un journal append-only (pas de backfill).
    """
    EN = "en"
    AR = "ar"


class Role(str, enum.Enum):
    SUPER_ADMIN = "super_admin"   # Atlas/éditeur — accès illimité
    IT_ADMIN = "it_admin"         # SSO, sécurité globale (gate d'achat)
    PED_ADMIN = "ped_admin"       # établissement : licences, analytics école
    TEACHER = "teacher"           # ses classes
    PARENT = "parent"             # lecture seule sur son enfant
    STUDENT = "student"           # ses propres activités
    LINGUIST = "linguist"         # staff Atlas GLOBAL : relit/valide l'arabe de la banque (pas tenant-scopé)
    # Refonte, phase A (docs/refonte/02) :
    DEPT_LEAD = "dept_lead"       # coordinateur maths : UNE école + une liste de niveaux (dept_lead_scope)
    GROUP_ADMIN = "group_admin"   # admin de groupe scolaire : organisation entière (toutes ses écoles), lecture
    CONTENT_REVIEWER = "content_reviewer"  # staff Atlas GLOBAL : relit la banque d'items (file de revue, pas tenant-scopé)


# --- Enums curriculum (Lot B, B2/B3 — DataModel §7 amendé D-B4) ---

class CurriculumFramework(str, enum.Enum):
    CCSS_M = "CCSS_M"     # Common Core State Standards - Mathematics
    UK_NC = "UK_NC"       # UK National Curriculum
    MOE_UAE = "MOE_UAE"   # MoE UAE — pas de codes officiels : clé composée domaine+band


class AlignmentType(str, enum.Enum):
    """Type d'alignement compétence Atlas ↔ standard (remplace l'alignment_strength
    scalaire du §7 : le crosswalk réel porte un type + une confiance, D-B4)."""
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    BROADER = "BROADER"
    PREREQ = "PREREQ"
    ENRICH = "ENRICH"


class MappingConfidence(str, enum.Enum):
    H = "H"   # haute
    M = "M"   # moyenne


class CurriculumView(str, enum.Enum):
    """Framework d'affichage par tenant (B3). ATLAS = vue neutre actuelle (aucune
    étiquette de standard) — comportement identique à aujourd'hui, zéro régression."""
    ATLAS = "ATLAS"
    CCSS_M = "CCSS_M"
    UK_NC = "UK_NC"
    MOE_UAE = "MOE_UAE"


# Helpers de colonnes communes (mixin léger, pas d'abstraction magique)
def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
