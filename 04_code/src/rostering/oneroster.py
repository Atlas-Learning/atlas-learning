"""Adapter OneRoster Rostering REST (1EdTech/IMS Global) — implémente le `Protocol` Directory.

Standard de rostering international, souvent mandaté par les ministères (GCC inclus).
Même conception que l'adapter Google, en deux couches :
- **Mapping** (JSON OneRoster → DirectorySnapshot) : pur, testé via un transport factice,
  sans réseau ni credentials. C'est ici que vit la logique.
- **Transport** : un callable `(resource, params) -> json` authentifié OAuth2
  (`client_credentials`). La fabrique réelle (`client_credentials_transport`) utilise httpx.

Modèle OneRoster → Atlas :
  org (type=school) → School,  class → Classroom,  user → AppUser (+ Student/Teacher selon
  le rôle EXPLICITE),  enrollment → inscription (Student↔classe / TeacherClassroom).

Versions : 1.1 (`v1p1`) et 1.2 (`v1p2`). Le rôle est porté par `user.role` (1.1) ou
`user.roles[].role` (1.2, rôle `primary` prioritaire). Le chemin de version est paramétrable.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

from src.models.base import Role
from src.rostering.directory import (
    DirectorySnapshot, DirGroup, DirMembership, DirOrgUnit, DirUser,
)

# Transport authentifié : (resource ex. "users", params) -> dict JSON OneRoster.
Transport = Callable[[str, Dict], Dict]

# OneRoster role → rôle Atlas. guardian/parent/relative/proctor → None (ignorés ici ;
# les tuteurs sont gérés par une source dédiée, jamais auto-inscrits comme utilisateurs).
_ROLE_MAP = {
    "student": Role.STUDENT,
    "teacher": Role.TEACHER,
    "aide": Role.TEACHER,
    "administrator": Role.IT_ADMIN,
    "districtadministrator": Role.IT_ADMIN,
    "siteadministrator": Role.IT_ADMIN,
}

# Statuts OneRoster : on ne fait entrer que les enregistrements actifs. `tobedeleted` est
# donc ABSENT du snapshot → le moteur idempotent le déprovisionne (soft delete) via son
# garde-fou habituel. (Pas d'invention : l'absence = retrait.)
_ACTIVE = ("active", "", None)


def grade_from_codes(codes) -> Optional[int]:
    """Niveau Atlas (int) depuis les codes de niveau OneRoster d'une classe (`grades`).

    Codes CEDS : "KG" (ou "K") = 0, "01"…"13" = 1…13. Multi-niveaux ou code non numérique
    (PK, IT, PS, UG…) → None : on n'invente pas un niveau. Les écoles en curriculum anglais
    (Year N) ne passent pas par ce code : [À CLARIFIER] Q6 Year ↔ Grade."""
    if not codes:
        return None
    if isinstance(codes, str):
        codes = [codes]
    codes = [str(c).strip().upper() for c in codes if str(c).strip()]
    if len(codes) != 1:
        return None
    code = codes[0]
    if code in ("K", "KG"):
        return 0
    if code.isdigit() and 1 <= int(code) <= 13:
        return int(code)
    return None


class OneRosterAdapter:
    """Lit une source OneRoster REST et la normalise en `DirectorySnapshot`."""

    def __init__(self, transport: Transport, *, version: str = "v1p1", page_size: int = 100):
        self._get = transport
        self._version = version
        self._page = page_size

    # --- pagination offset/limit (réponse keyée par le nom pluriel de la ressource) ---
    def _collection(self, resource: str) -> List[dict]:
        items: List[dict] = []
        offset = 0
        while True:
            data = self._get(resource, {"limit": self._page, "offset": offset})
            page = data.get(resource, [])
            items.extend(page)
            if len(page) < self._page:   # dernière page (ou source sans pagination)
                return items
            offset += self._page

    @staticmethod
    def _is_active(rec: dict) -> bool:
        return rec.get("status") in _ACTIVE

    @staticmethod
    def _user_role(u: dict) -> Optional[Role]:
        """Rôle Atlas d'un user OneRoster — gère 1.1 (`role`) et 1.2 (`roles[]`)."""
        roles = u.get("roles")
        if isinstance(roles, list) and roles:
            primary = next((r for r in roles if r.get("roleType") == "primary"), roles[0])
            raw = primary.get("role")
        else:
            raw = u.get("role")
        return _ROLE_MAP.get((raw or "").strip().lower())

    @staticmethod
    def _ref(obj) -> Optional[str]:
        """sourcedId d'un GUIDRef OneRoster (`{"sourcedId": ...}`) ou d'un id nu."""
        if isinstance(obj, dict):
            return obj.get("sourcedId")
        return obj or None

    def _user_school_ref(self, u: dict, school_refs: set) -> Optional[str]:
        """Rattache l'utilisateur à SON école : 1er org appartenant aux orgs de type school."""
        orgs = u.get("orgs") or []
        refs = [self._ref(o) for o in orgs]
        for r in refs:
            if r in school_refs:
                return r
        return refs[0] if refs else None

    def _email(self, u: dict) -> str:
        if u.get("email"):
            return u["email"]
        ids = u.get("userIds") or []   # repli : identifiant fédéré si pas d'email explicite
        if ids and isinstance(ids[0], dict):
            return ids[0].get("identifier", "")
        return u.get("username", "")

    def snapshot(self) -> DirectorySnapshot:
        orgs = [o for o in self._collection("orgs") if self._is_active(o)]
        # Écoles = orgs de type "school". Les districts/départements servent de parent.
        school_orgs = [o for o in orgs if (o.get("type") or "school").lower() == "school"]
        school_refs = {o["sourcedId"] for o in school_orgs}
        org_units = [
            DirOrgUnit(
                external_id=o["sourcedId"],
                name=o.get("name", ""),
                parent_external_id=self._ref(o.get("parent")),
            )
            for o in school_orgs
        ]

        users: List[DirUser] = []
        for u in self._collection("users"):
            if not self._is_active(u):
                continue
            role = self._user_role(u)
            if role is None:
                continue  # rôle non pertinent (tuteur, proctor…) → jamais inscrit
            name = (f"{u.get('givenName', '')} {u.get('familyName', '')}").strip()
            users.append(DirUser(
                external_id=u["sourcedId"],
                email=self._email(u).lower(),
                full_name=name,
                org_unit_external_id=self._user_school_ref(u, school_refs),
                role=role,
            ))

        groups = [
            DirGroup(external_id=c["sourcedId"], name=c.get("title") or c.get("classCode", ""),
                     grade=grade_from_codes(c.get("grades")))
            for c in self._collection("classes") if self._is_active(c)
        ]
        group_refs = {g.external_id for g in groups}
        user_refs = {u.external_id for u in users}

        memberships: List[DirMembership] = []
        for e in self._collection("enrollments"):
            if not self._is_active(e):
                continue
            cls_ref = self._ref(e.get("class"))
            usr_ref = self._ref(e.get("user"))
            # On n'inscrit que des entités présentes & retenues (évite les FK orphelines).
            if cls_ref in group_refs and usr_ref in user_refs:
                memberships.append(DirMembership(cls_ref, usr_ref))

        # guardians=None : OneRoster ne porte pas les tuteurs ici → le moteur ne touche pas
        # aux liens parents (cohérent avec la politique « push-only » d'une autorité de confiance).
        return DirectorySnapshot(org_units, users, groups, memberships)


# --- Fabrique (voie réelle : OAuth2 client_credentials over httpx) --------------------------

def client_credentials_transport(
    *, base_url: str, token_url: str, client_id: str, client_secret: str,
    version: str = "v1p1", scope: Optional[str] = None, timeout: float = 30.0,
) -> Transport:
    """Transport OneRoster REST authentifié par OAuth2 `client_credentials`.

    `base_url` = racine du serveur OneRoster ; le chemin standard
    `/ims/oneroster/rostering/{version}/{resource}` est construit ici. Le jeton d'accès est
    obtenu au 1er appel et mis en cache pour la durée de la sync (renouvelé si 401).
    """
    import httpx

    base = base_url.rstrip("/")
    state: Dict[str, Optional[str]] = {"token": None}

    def _fetch_token() -> str:
        data = {"grant_type": "client_credentials"}
        if scope:
            data["scope"] = scope
        r = httpx.post(token_url, data=data, auth=(client_id, client_secret),
                       headers={"Accept": "application/json"}, timeout=timeout)
        r.raise_for_status()
        return r.json()["access_token"]

    def _get(resource: str, params: Dict) -> Dict:
        if not state["token"]:
            state["token"] = _fetch_token()
        url = f"{base}/ims/oneroster/rostering/{version}/{resource}"
        headers = {"Authorization": f"Bearer {state['token']}", "Accept": "application/json"}
        r = httpx.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code == 401:  # jeton expiré → un renouvellement
            state["token"] = _fetch_token()
            headers["Authorization"] = f"Bearer {state['token']}"
            r = httpx.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()

    return _get


def build_from_env(integration=None):
    """Construit l'adapter OneRoster depuis l'environnement (secrets jamais en dur).

    ONEROSTER_BASE_URL, ONEROSTER_TOKEN_URL, ONEROSTER_CLIENT_ID, ONEROSTER_CLIENT_SECRET,
    ONEROSTER_VERSION (défaut v1p1), ONEROSTER_SCOPE (optionnel).
    """
    base = os.environ.get("ONEROSTER_BASE_URL")
    token_url = os.environ.get("ONEROSTER_TOKEN_URL")
    cid = os.environ.get("ONEROSTER_CLIENT_ID")
    csec = os.environ.get("ONEROSTER_CLIENT_SECRET")
    if not all((base, token_url, cid, csec)):
        raise RuntimeError("OneRoster non configuré (ONEROSTER_BASE_URL/TOKEN_URL/CLIENT_ID/SECRET)")
    version = os.environ.get("ONEROSTER_VERSION", "v1p1")
    transport = client_credentials_transport(
        base_url=base, token_url=token_url, client_id=cid, client_secret=csec,
        version=version, scope=os.environ.get("ONEROSTER_SCOPE"),
    )
    return OneRosterAdapter(transport, version=version)
