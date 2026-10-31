"""Adapter OneRoster CSV (bulk) — pour les écoles/ministères sans API temps réel.

Le format CSV OneRoster (1EdTech) est un bundle de fichiers (`orgs.csv`, `users.csv`,
`classes.csv`, `enrollments.csv`, …), souvent livré en ZIP. On parse ces fichiers en
enregistrements de MÊME forme que l'API REST, puis on REUTILISE `OneRosterAdapter` via un
transport mémoire — aucune duplication de la logique de rôle/statut/inscription.

Source : un dossier (`from_dir`) ou un ZIP (`from_zip`) de fichiers CSV.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from typing import Dict, List

from src.rostering.oneroster import OneRosterAdapter

# Découpe une liste d'orgSourcedIds (séparateur virgule OU espace selon les exports).
_SPLIT = re.compile(r"[,\s]+")


def _rows(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _orgs(rows: List[Dict[str, str]]) -> List[dict]:
    return [{
        "sourcedId": r["sourcedId"], "status": r.get("status", "active"),
        "type": r.get("type", "school"), "name": r.get("name", ""),
        "parent": {"sourcedId": r["parentSourcedId"]} if r.get("parentSourcedId") else None,
    } for r in rows]


def _users(rows: List[Dict[str, str]]) -> List[dict]:
    out = []
    for r in rows:
        org_ids = [x for x in _SPLIT.split(r.get("orgSourcedIds", "").strip()) if x]
        out.append({
            "sourcedId": r["sourcedId"], "status": r.get("status", "active"),
            "role": r.get("role", ""),
            "givenName": r.get("givenName", ""), "familyName": r.get("familyName", ""),
            "email": r.get("email", "") or r.get("username", ""),
            "orgs": [{"sourcedId": o} for o in org_ids],
        })
    return out


def _classes(rows: List[Dict[str, str]]) -> List[dict]:
    return [{
        "sourcedId": r["sourcedId"], "status": r.get("status", "active"),
        "title": r.get("title", ""),
        "school": {"sourcedId": r.get("schoolSourcedId", "")},
        # colonne optionnelle `grades` (codes CEDS, séparés comme orgSourcedIds)
        "grades": [g for g in _SPLIT.split((r.get("grades") or "").strip()) if g],
    } for r in rows]


def _enrollments(rows: List[Dict[str, str]]) -> List[dict]:
    return [{
        "sourcedId": r["sourcedId"], "status": r.get("status", "active"),
        "role": r.get("role", ""),
        "class": {"sourcedId": r.get("classSourcedId", "")},
        "user": {"sourcedId": r.get("userSourcedId", "")},
    } for r in rows]


# Fichier CSV → (clé de collection OneRoster, parseur).
_FILES = {
    "orgs.csv": ("orgs", _orgs),
    "users.csv": ("users", _users),
    "classes.csv": ("classes", _classes),
    "enrollments.csv": ("enrollments", _enrollments),
}


def _build_collections(read_file) -> Dict[str, List[dict]]:
    """`read_file(name) -> text|None` ; absent = collection vide (bundle partiel toléré)."""
    collections: Dict[str, List[dict]] = {"orgs": [], "users": [], "classes": [], "enrollments": []}
    for fname, (key, parser) in _FILES.items():
        text = read_file(fname)
        if text:
            collections[key] = parser(_rows(text))
    return collections


def _adapter(collections: Dict[str, List[dict]], *, version: str = "v1p1") -> OneRosterAdapter:
    def _transport(resource, params):
        rows = collections.get(resource, [])
        off, lim = params.get("offset", 0), params.get("limit", 100)
        return {resource: rows[off:off + lim]}
    return OneRosterAdapter(_transport, version=version)


def from_dir(path: str, *, version: str = "v1p1") -> OneRosterAdapter:
    """Adapter lisant un dossier de CSV OneRoster."""
    def _read(name):
        fp = os.path.join(path, name)
        if not os.path.exists(fp):
            return None
        with open(fp, "r", encoding="utf-8-sig", newline="") as f:
            return f.read()
    return _adapter(_build_collections(_read), version=version)


def from_zip(path: str, *, version: str = "v1p1") -> OneRosterAdapter:
    """Adapter lisant un ZIP de CSV OneRoster (format de livraison usuel)."""
    with zipfile.ZipFile(path) as z:
        names = {n.split("/")[-1]: n for n in z.namelist()}  # tolère un sous-dossier dans le zip

        def _read(name):
            real = names.get(name)
            if real is None:
                return None
            return z.read(real).decode("utf-8-sig")
        # Tout lire pendant que le zip est ouvert.
        return _adapter(_build_collections(_read), version=version)


def build_from_env(integration=None) -> OneRosterAdapter:
    """Construit l'adapter depuis l'environnement : ONEROSTER_CSV_PATH (dossier ou .zip)."""
    path = os.environ.get("ONEROSTER_CSV_PATH")
    if not path:
        raise RuntimeError("OneRoster CSV non configuré (ONEROSTER_CSV_PATH)")
    version = os.environ.get("ONEROSTER_VERSION", "v1p1")
    if path.lower().endswith(".zip"):
        return from_zip(path, version=version)
    return from_dir(path, version=version)
