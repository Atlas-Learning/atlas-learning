"""Adapter d'annuaire — frontière entre le moteur de rostering et la source externe.

Le moteur ne connaît QUE ce snapshot normalisé (jamais l'API Google directement) :
- Phase A : `FakeDirectory` alimenté en mémoire → moteur testable sans réseau.
- Phase B : `GoogleDirectoryAdapter` (Admin SDK) implémentera le même `Protocol`.

Modèle Workspace → Atlas :
  OrgUnit → School,  Group → Classroom,  User → AppUser (+ Student/Teacher selon le rôle),
  appartenance à un groupe → inscription (Student dans la classe / TeacherClassroom).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Protocol

if TYPE_CHECKING:  # éviter un cycle d'import (mapping/models) au runtime
    from src.models.base import Role


@dataclass(frozen=True)
class DirOrgUnit:
    external_id: str                 # id de l'OrgUnit (stable)
    name: str
    parent_external_id: Optional[str] = None


@dataclass(frozen=True)
class DirUser:
    external_id: str                 # id source stable (Google user id, OneRoster/Wonde sourcedId)
    email: str
    full_name: str
    org_unit_external_id: Optional[str] = None
    is_admin: bool = False           # Workspace super/delegated admin (sources sans rôle explicite)
    suspended: bool = False
    # Rôle FOURNI par la source quand elle l'expose explicitement (OneRoster `role`,
    # Wonde `student`/`employee`). None = à déduire par heuristique (cas Google : nom d'OU).
    role: "Optional[Role]" = None


@dataclass(frozen=True)
class DirGroup:
    external_id: str                 # id/email du groupe (= une classe)
    name: str
    # Niveau (grade) de la classe quand la source l'expose (OneRoster `grades`). None = la
    # source ne le fournit pas : le moteur ne touche PAS à un niveau déjà saisi en admin.
    grade: Optional[int] = None


@dataclass(frozen=True)
class DirMembership:
    group_external_id: str
    user_external_id: str


@dataclass(frozen=True)
class DirGuardian:
    """Lien tuteur → élève (source Google Classroom guardians, pas l'Admin SDK)."""
    student_external_id: str          # élève (user id, = DirUser.external_id)
    email: str                        # email du tuteur (identité)
    full_name: str = ""
    external_id: Optional[str] = None  # guardianId Classroom (défaut : email)


@dataclass(frozen=True)
class DirectorySnapshot:
    org_units: List[DirOrgUnit] = field(default_factory=list)
    users: List[DirUser] = field(default_factory=list)
    groups: List[DirGroup] = field(default_factory=list)
    memberships: List[DirMembership] = field(default_factory=list)
    # None = la source ne gère PAS les tuteurs (ne rien toucher) ; [] = gère, aucun pour l'instant.
    guardians: Optional[List[DirGuardian]] = None

    def members_of(self, group_external_id: str) -> List[str]:
        return [m.user_external_id for m in self.memberships
                if m.group_external_id == group_external_id]


class Directory(Protocol):
    """Toute source de rostering expose un instantané complet du domaine."""
    def snapshot(self) -> DirectorySnapshot: ...


class FakeDirectory:
    """Source en mémoire pour les tests (et les démos hors-ligne)."""
    def __init__(self, snapshot: DirectorySnapshot):
        self._snapshot = snapshot

    def snapshot(self) -> DirectorySnapshot:
        return self._snapshot
