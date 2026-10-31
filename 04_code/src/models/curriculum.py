"""Modèles du crosswalk curriculaire (Lot B, B2 — DataModel §7 amendé D-B4 ; refonte C1).

CurriculumFrameworkDef : un framework externe (CCSS-M, UK NC, MoE UAE, ou tout curriculum
importé par le super admin) — TABLE depuis la refonte C1 (plus un enum figé), avec un statut
brouillon → publié.
CurriculumStandard : standard officiel d'un framework.
CompetencyCurriculumMap : alignement compétence Atlas ↔ standard — type + confiance, provenance
versionnée, et depuis C1 la revue (`reviewed_by`, `reviewed_at`, `suggested`).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .base import (
    AlignmentType,
    Base,
    FrameworkStatus,
    MappingConfidence,
    WeightSource,
    native_enum,
    utcnow,
    uuid_pk,
)

# Les trois frameworks livrés avec le crosswalk : clé → (nom EN, nom AR, pays). Ils sont
# PUBLIÉS dès la migration (ils étaient servis aux écoles avant C1 : zéro régression).
LEGACY_FRAMEWORKS: Dict[str, tuple] = {
    "CCSS_M": ("Common Core State Standards — Mathematics",
               "المعايير الأساسية المشتركة — الرياضيات", "US"),
    "UK_NC": ("National Curriculum in England — Mathematics",
              "المنهج الوطني الإنجليزي — الرياضيات", "GB"),
    "MOE_UAE": ("MoE UAE — Mathematics", "وزارة التربية والتعليم (الإمارات) — الرياضيات", "AE"),
}
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "atlas-learning/curriculum_framework")


def legacy_framework_id(key: str) -> uuid.UUID:
    """Identifiant STABLE d'un framework historique (même valeur en migration, seed et tests)."""
    return uuid.uuid5(_NS, key)


class CurriculumFrameworkDef(Base):
    __tablename__ = "curriculum_framework"
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String, unique=True, index=True)      # ex. UK_NC
    name_en: Mapped[str] = mapped_column(String)
    name_ar: Mapped[str] = mapped_column(String)
    country: Mapped[Optional[str]] = mapped_column(String(2), default=None)
    status: Mapped[FrameworkStatus] = mapped_column(
        native_enum(FrameworkStatus, "framework_status"), default=FrameworkStatus.DRAFT,
        server_default="draft", index=True,
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    source_note: Mapped[Optional[str]] = mapped_column(String, default=None)

    def __repr__(self) -> str:
        return f"<Framework {self.key} {self.status.value}>"


def ensure_legacy_frameworks(session: Session) -> Dict[str, CurriculumFrameworkDef]:
    """Garantit les trois frameworks historiques (publiés) — seeds et tests sur base créée
    par `create_all` (sans migration). Idempotent ; ne commit pas."""
    out: Dict[str, CurriculumFrameworkDef] = {}
    for key, (name_en, name_ar, country) in LEGACY_FRAMEWORKS.items():
        fw = session.execute(select(CurriculumFrameworkDef).where(CurriculumFrameworkDef.key == key)).scalar_one_or_none()
        if fw is None:
            fw = CurriculumFrameworkDef(id=legacy_framework_id(key), key=key, name_en=name_en, name_ar=name_ar,
                                        country=country, status=FrameworkStatus.PUBLISHED, published_at=utcnow(),
                                        source_note="crosswalk historique (expert), publié pour continuité (C1)")
            session.add(fw)
        out[key] = fw
    session.flush()
    return out


class CurriculumStandard(Base):
    __tablename__ = "curriculum_standard"
    __table_args__ = (
        # `code` n'est unique QUE par framework ('Y5' UK vs un éventuel 'Y5' ailleurs).
        # MoE UAE n'a pas de codes officiels : `code` y est la clé composée
        # domaine+grade-band (ex. 'NUM_OPS/G4-G5') — jamais un pseudo-code inventé.
        UniqueConstraint("framework_id", "code", name="uq_curriculum_standard_framework_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    framework_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_framework.id", ondelete="CASCADE"), index=True
    )
    framework: Mapped[CurriculumFrameworkDef] = relationship(CurriculumFrameworkDef, lazy="joined")
    code: Mapped[str] = mapped_column(String)   # '4.NF.A.1' | 'Y5' | 'NUM_OPS/G4-G5'
    label_en: Mapped[str] = mapped_column(String)
    label_ar: Mapped[str] = mapped_column(String)
    grade_hint: Mapped[Optional[str]] = mapped_column(String, default=None)  # affichage ('G4', 'Y5', 'G4-G5')

    @property
    def framework_key(self) -> str:
        return self.framework.key

    def __repr__(self) -> str:  # aide au debug, pas de magie
        return f"<CurriculumStandard {self.framework_key}:{self.code}>"


class CompetencyCurriculumMap(Base):
    __tablename__ = "competency_curriculum_map"

    competency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competency.id", ondelete="CASCADE"), primary_key=True
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_standard.id", ondelete="CASCADE"), primary_key=True
    )

    alignment_type: Mapped[AlignmentType] = mapped_column(
        native_enum(AlignmentType, "alignment_type")
    )
    confidence: Mapped[MappingConfidence] = mapped_column(
        native_enum(MappingConfidence, "mapping_confidence")
    )
    note: Mapped[Optional[str]] = mapped_column(String, default=None)

    # ENRICH seulement (M-4) : 'grade' (Atlas mesure un grade plus tôt → « taught earlier
    # than ») vs 'requirement' (exigence absente du standard → « beyond … expectations »).
    # NULL pour tout autre type d'alignement.
    enrich_kind: Mapped[Optional[str]] = mapped_column(String, default=None)

    # même provenance versionnée que les arêtes du graphe (expert aujourd'hui,
    # empirique après calibration) — cf. CompetencyPrerequisite
    weight_source: Mapped[WeightSource] = mapped_column(
        native_enum(WeightSource, "weight_source"), default=WeightSource.EXPERT
    )
    weight_version: Mapped[int] = mapped_column(default=1)

    # Refonte C1 : revue du mapping. `suggested` = proposé automatiquement (import, C2), pas
    # encore validé par un humain — une ligne suggérée n'est JAMAIS servie aux écoles.
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    suggested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Map {self.competency_id}->{self.standard_id} {self.alignment_type}>"
