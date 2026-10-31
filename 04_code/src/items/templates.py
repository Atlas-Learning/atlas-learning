"""Gabarits d'items déterministes (refonte A2/A3, Q15) — logique pure, testable.

Vocabulaire :
- **générateur** = une fonction de `src/items/deterministic.py`, enregistrée sous le code de
  compétence (ex. `MATH.G5.NF.ADD_MIXED`). C'est LE gabarit au sens du spec : une faute se
  corrige là, dans le code.
- **lignée** = un item et ses versions successives, identifiés par `template_key` =
  `code#rang` (rang dans la liste du générateur, cf. `deterministic.template_key`).
- **version courante** d'une lignée = l'item vivant qu'aucun autre item ne remplace
  (`supersedes_id`). C'est lui que l'on compare au code.

Trois opérations :
1. `backfill_template_keys` (Q15) : la banque antérieure à A2 n'a pas de clé. On la retrouve
   par appariement (compétence, énoncé, réponse) avec ce que le générateur produit
   aujourd'hui — sans toucher aux items, à leurs réponses ni à leur calibration. Rien n'est
   supprimé ; les items non appariés sont listés, pas inventés.
2. `quarantine_template` : sortie du pool, en masse, des versions courantes `active` d'un
   gabarit — par la machine à états de review.py (`active → quarantined` seulement).
3. `regenerate_template` (A3) : après correction du code, chaque lignée dont le rendu a
   changé repart en NOUVELLE version `ai_generated` (`review.supersede`) : l'ancienne sort du
   pool, ses réponses lui restent attachées et ne pèsent plus sur la calibration de la
   nouvelle (n_responses = 0). Lignée inchangée → rien (idempotent). Rang nouveau → item
   créé en version 1. La version arabe est PROPOSÉE par `arabic_deterministic.render_arabic`
   (déterministe, nombres préservés) et repasse par la validation du linguiste.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.items import deterministic
from src.items.arabic_deterministic import render_arabic
from src.items.generation import GeneratedItem
from src.items.review import InvalidTransition, insert_generated_items, promote, supersede
from src.models.base import AnswerFormat, ItemFlagStatus, ItemOrigin, ItemStatus, utcnow
from src.models.competency import Competency
from src.models.item import Item, ItemFlag


class TemplateError(ValueError):
    """Clé inconnue, compétence absente, générateur manquant."""


def parse_key(key: str) -> Tuple[str, Optional[int]]:
    """`MATH.G4.NF.ADD_LIKE#03` → (code, 3) ; `MATH.G4.NF.ADD_LIKE` → (code, None)."""
    key = (key or "").strip()
    if not key:
        raise TemplateError("clé vide")
    if "#" in key:
        code, _, rank = key.partition("#")
        if not rank.isdigit():
            raise TemplateError(f"rang invalide dans « {key} »")
        return code, int(rank)
    return key, None


def _signature(content: dict) -> Tuple[str, str]:
    return (str(content.get("stem", "")).strip(), str(content.get("answer", "")).strip())


def _same_content(a: dict, b: dict) -> bool:
    return (_signature(a) == _signature(b)
            and list(a.get("options") or []) == list(b.get("options") or []))


def _competency(s: Session, code: str) -> Competency:
    comp = s.execute(select(Competency).where(Competency.code == code)).scalar_one_or_none()
    if comp is None:
        raise TemplateError(f"compétence inconnue : {code}")
    return comp


def render(s: Session, code: str) -> List[dict]:
    """Ce que le code produit AUJOURD'HUI pour un générateur : bank_items + clé par rang."""
    if code not in deterministic.GENERATORS:
        raise TemplateError(f"aucun générateur déterministe pour {code}")
    comp = _competency(s, code)
    return deterministic.bank_items(code, comp.difficulty_prior)


def current_versions(s: Session, code: str) -> Dict[str, Item]:
    """Version courante de chaque lignée d'un générateur : {template_key: item}."""
    items = s.execute(
        select(Item).where(Item.template_key.like(f"{code}#%"), Item.deleted_at.is_(None))
    ).scalars().all()
    superseded = {it.supersedes_id for it in items if it.supersedes_id is not None}
    # une lignée peut porter plusieurs vivants (ancienne quarantined + nouvelle) : on garde
    # celui que personne ne remplace ; à égalité, la version la plus haute.
    out: Dict[str, Item] = {}
    for it in sorted(items, key=lambda i: i.version):
        if it.id in superseded:
            continue
        if it.template_key not in out or it.version >= out[it.template_key].version:
            out[it.template_key] = it
    return out


def lineage(s: Session, key: str) -> List[Item]:
    """Toutes les versions d'une lignée (vivantes ou non), de la plus ancienne à la plus récente."""
    return list(s.execute(
        select(Item).where(Item.template_key == key).order_by(Item.version, Item.created_at)
    ).scalars())


# ---------------------------------------------------------------------------------------
# Q15 — backfill des clés de la banque antérieure à A2
# ---------------------------------------------------------------------------------------

@dataclass
class BackfillReport:
    matched: int = 0
    unmatched: List[str] = field(default_factory=list)     # item ids sans correspondance
    ambiguous: List[str] = field(default_factory=list)     # signature partagée par 2 rangs
    already_keyed: int = 0
    skipped_non_deterministic: int = 0
    per_code: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"matched": self.matched, "unmatched": self.unmatched, "ambiguous": self.ambiguous,
                "already_keyed": self.already_keyed,
                "skipped_non_deterministic": self.skipped_non_deterministic,
                "per_code": self.per_code}


def backfill_template_keys(s: Session, *, codes: Optional[List[str]] = None,
                           dry_run: bool = False) -> BackfillReport:
    """Pose `template_key` sur les items déterministes qui n'en ont pas, par appariement
    (compétence, énoncé, réponse) avec le rendu actuel du générateur. Ne touche à rien
    d'autre : ni statut, ni calibration, ni réponses. Idempotent. Ne commit pas."""
    rep = BackfillReport()
    for code in (codes or deterministic.all_codes()):
        comp = s.execute(select(Competency).where(Competency.code == code)).scalar_one_or_none()
        if comp is None or code not in deterministic.GENERATORS:
            continue
        sig_to_key: Dict[Tuple[str, str], Optional[str]] = {}
        for entry in deterministic.bank_items(code, comp.difficulty_prior):
            sig = _signature(entry["content"])
            sig_to_key[sig] = None if sig in sig_to_key else entry["template_key"]  # doublon → ambigu
        items = s.execute(
            select(Item).where(Item.competency_id == comp.id, Item.deleted_at.is_(None))
        ).scalars().all()
        for it in items:
            if it.template_key:
                rep.already_keyed += 1
                continue
            if (it.provenance or {}).get("generator") != "deterministic":
                rep.skipped_non_deterministic += 1
                continue
            sig = _signature(it.content_en or {})
            if sig not in sig_to_key:
                rep.unmatched.append(str(it.id))
                continue
            key = sig_to_key[sig]
            if key is None:
                rep.ambiguous.append(str(it.id))
                continue
            if not dry_run:
                it.template_key = key
                prov = dict(it.provenance or {})
                prov["template_key_backfilled_at"] = utcnow().isoformat(timespec="seconds")
                it.provenance = prov
            rep.matched += 1
            rep.per_code[code] = rep.per_code.get(code, 0) + 1
    if not dry_run:
        s.flush()
    return rep


# ---------------------------------------------------------------------------------------
# A3 — quarantaine et régénération au gabarit
# ---------------------------------------------------------------------------------------

def _targets(s: Session, key: str) -> Tuple[str, Dict[str, Item]]:
    code, rank = parse_key(key)
    current = current_versions(s, code)
    if rank is not None:
        k = deterministic.template_key(code, rank)
        current = {k: current[k]} if k in current else {}
    return code, current


def quarantine_template(s: Session, key: str, *, by: str, reason: str = "") -> List[Item]:
    """Sort du pool servi les versions courantes `active` du gabarit (ou de la lignée).
    Passe par `promote` : un item en revue n'est pas touché. Retourne les items quarantinés."""
    _, current = _targets(s, key)
    done: List[Item] = []
    for it in current.values():
        if it.status == ItemStatus.ACTIVE:
            promote(s, it, ItemStatus.QUARANTINED, reviewer=by)
            prov = dict(it.provenance or {})
            prov.update(quarantined=True,
                        quarantine_reason=f"quarantaine au gabarit {key}" + (f" : {reason}" if reason else ""))
            it.provenance = prov
            done.append(it)
    s.flush()
    return done


@dataclass
class RegenerationReport:
    key: str
    regenerated: List[Tuple[str, int, int]] = field(default_factory=list)   # (template_key, old v, new v)
    created: List[str] = field(default_factory=list)                        # nouveaux rangs
    unchanged: List[str] = field(default_factory=list)
    flags_accepted: int = 0

    def as_dict(self) -> dict:
        return {"key": self.key,
                "regenerated": [{"template_key": k, "from_version": a, "to_version": b}
                                for k, a, b in self.regenerated],
                "created": self.created, "unchanged": self.unchanged,
                "flags_accepted": self.flags_accepted}


def regenerate_template(s: Session, key: str, *, by: str, resolver_id: Optional[uuid.UUID] = None,
                        dry_run: bool = False) -> RegenerationReport:
    """Après correction du code : nouvelle version pour chaque lignée dont le rendu a changé.

    - rendu identique → rien (idempotent : relancer ne crée pas de version) ;
    - rendu différent → `review.supersede` : nouvelle version `ai_generated` (revue complète,
      AR à refaire), l'ancienne `active → quarantined` ou rejetée si jamais publiée ; ses
      réponses lui restent, la nouvelle repart avec `n_responses = 0` ;
    - rang sans lignée → item créé en version 1 ;
    - les signalements ouverts d'une version remplacée sont acceptés (`resolver_id`).
    """
    code, rank = parse_key(key)
    rendered = render(s, code)
    if rank is not None:
        if rank >= len(rendered):
            raise TemplateError(f"rang {rank} hors du générateur {code} ({len(rendered)} items)")
        rendered = [rendered[rank]]
    current = current_versions(s, code)
    comp = _competency(s, code)
    rep = RegenerationReport(key=key)
    to_create: List[GeneratedItem] = []

    for entry in rendered:
        tkey = entry["template_key"]
        cur = current.get(tkey)
        if cur is None:
            rep.created.append(tkey)
            if not dry_run:
                to_create.append(GeneratedItem(
                    competency_id=comp.id, content_en=entry["content"],
                    content_ar=render_arabic(entry["content"]),
                    answer_format=AnswerFormat.MCQ, difficulty_prior=entry["difficulty_prior"],
                    context_tags={**entry["context_tags"], "gen": "deterministic"},
                    provenance={"generator": "deterministic", "method": "exact-fraction",
                                "regenerated_by": by},
                    template_key=tkey,
                ))
            continue
        if _same_content(cur.content_en or {}, entry["content"]):
            rep.unchanged.append(tkey)
            continue
        rep.regenerated.append((tkey, cur.version, cur.version + 1))
        if dry_run:
            continue
        supersede(s, cur, content_en=entry["content"], by=by,
                  content_ar=render_arabic(entry["content"]),
                  context_tags={**entry["context_tags"], "gen": "deterministic"},
                  difficulty_prior=entry["difficulty_prior"])
        if resolver_id is not None:
            for fl in s.execute(select(ItemFlag).where(ItemFlag.item_id == cur.id,
                                                       ItemFlag.status == ItemFlagStatus.OPEN)).scalars():
                fl.status, fl.resolved_by, fl.resolved_at = ItemFlagStatus.ACCEPTED, resolver_id, utcnow()
                rep.flags_accepted += 1
    if to_create and not dry_run:
        insert_generated_items(s, to_create)
    if not dry_run:
        s.flush()
    return rep


def template_report(s: Session, key: str) -> dict:
    """État d'un gabarit ou d'une lignée pour l'UI de revue : versions, statuts, signalements."""
    code, rank = parse_key(key)
    if code not in deterministic.GENERATORS:
        raise TemplateError(f"aucun générateur déterministe pour {code}")
    current = current_versions(s, code)
    keys = sorted(current) if rank is None else [deterministic.template_key(code, rank)]
    out = []
    for k in keys:
        versions = lineage(s, k)
        open_flags = []
        if versions:
            open_flags = s.execute(
                select(ItemFlag).where(ItemFlag.item_id.in_([v.id for v in versions]),
                                       ItemFlag.status == ItemFlagStatus.OPEN)
            ).scalars().all()
        cur = current.get(k)
        out.append({
            "template_key": k,
            "current": None if cur is None else {
                "item_id": str(cur.id), "version": cur.version, "status": cur.status.value,
                "stem_en": (cur.content_en or {}).get("stem"), "n_responses": cur.n_responses,
                "calibration_reset_at": cur.calibration_reset_at.isoformat() if cur.calibration_reset_at else None,
            },
            "versions": [{"item_id": str(v.id), "version": v.version, "status": v.status.value,
                          "deleted": v.deleted_at is not None, "n_responses": v.n_responses}
                         for v in versions],
            "open_flags": len(open_flags),
        })
    return {"key": key, "code": code, "lineages": out}
