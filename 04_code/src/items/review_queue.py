"""File de revue de la banque (refonte A4, écran O2) — logique pure, testable.

Une file UNIQUE, quatre sources :
- `flag`       : items portant au moins un signalement ouvert (enseignants, coordinateurs, staff) ;
- `validation` : items qui échouent aux contrôles automatiques — structure (ItemContent, MCQ)
                 ou fidélité EN↔AR (`ar_fidelity_errors`, drapeau `ar_math_broken`) ;
- `school`     : items d'école (origin = school, phase E) ;
- `arabic`     : arabe à valider (revus en EN, `ar_validated` faux — la file du linguiste).

Regroupement par gabarit (le générateur, `code` de `template_key`) : une faute se corrige au
gabarit, pas item par item. Les actions renvoyées dépendent du rôle : le relecteur de contenu
approuve, rejette, met en quarantaine, tranche les signalements ; le super admin peut aussi
activer, réhabiliter et régénérer. Toute transition passe par `review.promote` (invariant 6).
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.items.arabic import ar_fidelity_errors
from src.models.base import AnswerFormat, ItemFlagStatus, ItemOrigin, ItemStatus
from src.models.competency import Competency
from src.models.item import Item, ItemContent, ItemFlag
from src.rbac.authz import UserContext, is_super

SOURCES = ("flag", "validation", "school", "arabic")

# Transition demandée → action nommée (contrôle par rôle dans `allowed_actions`).
TRANSITION_ACTION = {
    ItemStatus.HUMAN_REVIEWED: "approve",
    ItemStatus.QUARANTINED: "quarantine",
}
SUPER_ONLY_ACTIONS = frozenset({"activate", "rehabilitate", "regenerate"})


def structural_issue(item: Item) -> Optional[str]:
    """Contrôle automatique de structure (même règle que scripts/validate_bank.py)."""
    try:
        c = ItemContent.model_validate(item.content_en or {})
    except ValidationError as e:
        return f"contenu EN invalide : {str(e)[:80]}"
    if item.answer_format == AnswerFormat.MCQ:
        opts = c.options or []
        if len(opts) < 2:
            return "MCQ avec moins de 2 options"
        if c.answer not in opts:
            return "réponse absente des options"
        if len(set(opts)) != len(opts):
            return "options en doublon"
    return None


def validation_errors(item: Item) -> List[str]:
    errs: List[str] = []
    issue = structural_issue(item)
    if issue:
        errs.append(issue)
    if item.content_ar:
        errs.extend(ar_fidelity_errors(item.content_en or {}, item.content_ar))
    if (item.provenance or {}).get("ar_math_broken"):
        errs.append("arabe signalé (ar_math_broken)")
    return errs


def item_sources(item: Item, open_flags: List[ItemFlag]) -> List[str]:
    out: List[str] = []
    if open_flags:
        out.append("flag")
    if validation_errors(item):
        out.append("validation")
    if item.origin == ItemOrigin.SCHOOL:
        out.append("school")
    if item.status == ItemStatus.HUMAN_REVIEWED and not item.ar_validated:
        out.append("arabic")
    return out


def allowed_actions(ctx: UserContext, item: Item, open_flags: int) -> List[str]:
    """Actions possibles pour CE rôle sur CET item. Le relecteur ne voit pas celles du super admin."""
    acts: List[str] = []
    if item.deleted_at is not None:
        return acts
    if item.status == ItemStatus.AI_GENERATED:
        acts.append("approve")
    if item.status == ItemStatus.ACTIVE:
        acts.append("quarantine")
    acts.append("reject")
    if open_flags:
        acts.append("resolve_flag")
    if item.template_key:
        acts.append("quarantine_template")
    if is_super(ctx):
        if item.status == ItemStatus.LINGUIST_VALIDATED and item.ar_validated:
            acts.append("activate")
        if item.status == ItemStatus.QUARANTINED:
            acts.append("rehabilitate")
        if item.template_key:
            acts.append("regenerate")
    return acts


def action_for_transition(item: Item, target: ItemStatus) -> Optional[str]:
    if target == ItemStatus.ACTIVE:
        if item.status == ItemStatus.QUARANTINED:
            return "rehabilitate"
        if item.status == ItemStatus.LINGUIST_VALIDATED:
            return "activate"
        return None
    return TRANSITION_ACTION.get(target)


def _template_of(key: Optional[str]) -> Optional[str]:
    return key.split("#", 1)[0] if key else None


def _entry(item: Item, code_of: Dict[uuid.UUID, str], flags: List[ItemFlag],
           ctx: Optional[UserContext] = None) -> dict:
    return {
        "item_id": str(item.id),
        "competency_id": str(item.competency_id),
        "competency_code": code_of.get(item.competency_id),
        "status": item.status.value,
        "origin": item.origin.value,
        "version": item.version,
        "template_key": item.template_key,
        "template": _template_of(item.template_key),
        "owner_school_id": str(item.owner_school_id) if item.owner_school_id else None,
        "stem_en": (item.content_en or {}).get("stem"),
        "stem_ar": (item.content_ar or {}).get("stem") if item.content_ar else None,
        "ar_validated": item.ar_validated,
        "n_responses": item.n_responses,
        "sources": item_sources(item, flags),
        "open_flags": len(flags),
        "flag_reasons": sorted({f.reason.value for f in flags}),
        "flag_schools": len({f.school_id for f in flags if f.school_id}),
        "validation_errors": validation_errors(item),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "actions": allowed_actions(ctx, item, len(flags)) if ctx is not None else [],
    }


def _open_flags_by_item(s: Session) -> Dict[uuid.UUID, List[ItemFlag]]:
    by: Dict[uuid.UUID, List[ItemFlag]] = {}
    for fl in s.execute(select(ItemFlag).where(ItemFlag.status == ItemFlagStatus.OPEN)
                        .order_by(ItemFlag.created_at)).scalars():
        by.setdefault(fl.item_id, []).append(fl)
    return by


def build_queue(s: Session, *, source: Optional[str] = None, ctx: Optional[UserContext] = None,
                limit: int = 500) -> dict:
    if source is not None and source not in SOURCES:
        raise ValueError(f"source inconnue (attendu : {list(SOURCES)})")
    flags_by = _open_flags_by_item(s)
    code_of = dict(s.execute(select(Competency.id, Competency.code)).all())
    items = s.execute(select(Item).where(Item.deleted_at.is_(None)).order_by(Item.created_at)).scalars().all()

    entries: List[dict] = []
    counts = {k: 0 for k in SOURCES}
    n_all = 0
    for it in items:
        e = _entry(it, code_of, flags_by.get(it.id, []), ctx)
        if not e["sources"]:
            continue
        n_all += 1
        for src in e["sources"]:
            counts[src] += 1
        if source is None or source in e["sources"]:
            entries.append(e)
    counts["all"] = n_all
    entries = entries[:limit]

    groups: Dict[str, dict] = {}
    for e in entries:
        key = e["template"] or "—"
        g = groups.setdefault(key, {"template": e["template"], "competency_code": e["competency_code"],
                                    "items": [], "n_active": 0, "open_flags": 0, "sources": set()})
        g["items"].append(e)
        g["n_active"] += e["status"] == "active"
        g["open_flags"] += e["open_flags"]
        g["sources"].update(e["sources"])
    out_groups = []
    for g in groups.values():
        g["sources"] = sorted(g["sources"])
        g["n_items"] = len(g["items"])
        out_groups.append(g)
    # les gabarits les plus signalés d'abord, puis les plus gros
    out_groups.sort(key=lambda g: (-g["open_flags"], -g["n_items"], g["template"] or "~"))
    return {"source": source or "all", "counts": counts, "groups": out_groups, "n_items": len(entries)}


def item_detail(s: Session, item: Item, ctx: UserContext) -> dict:
    code_of = dict(s.execute(select(Competency.id, Competency.code)
                             .where(Competency.id == item.competency_id)).all())
    flags = list(s.execute(select(ItemFlag).where(ItemFlag.item_id == item.id)
                           .order_by(ItemFlag.created_at)).scalars())
    open_flags = [f for f in flags if f.status == ItemFlagStatus.OPEN]
    e = _entry(item, code_of, open_flags, ctx)
    e["content_en"] = item.content_en
    e["content_ar"] = item.content_ar
    e["difficulty_prior"] = item.difficulty_prior
    e["difficulty_elo"] = item.difficulty_elo
    e["calibration_reset_at"] = item.calibration_reset_at.isoformat() if item.calibration_reset_at else None
    e["provenance"] = {k: v for k, v in (item.provenance or {}).items()
                       if k in ("generator", "reviewer", "reviewed_at", "quarantine_reason", "reject_reason",
                                "ar_proposed_by", "ar_validated_by", "ar_math_broken", "flag_reason",
                                "superseded_from", "regenerated_by")}
    e["flags"] = [{
        "id": str(f.id), "reason": f.reason.value, "comment": f.comment, "status": f.status.value,
        "school_id": str(f.school_id) if f.school_id else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in flags]
    versions = []
    if item.template_key:
        versions = [{"item_id": str(v.id), "version": v.version, "status": v.status.value,
                     "deleted": v.deleted_at is not None, "n_responses": v.n_responses}
                    for v in s.execute(select(Item).where(Item.template_key == item.template_key)
                                       .order_by(Item.version)).scalars()]
    e["versions"] = versions
    e["lifecycle"] = [st.value for st in (ItemStatus.AI_GENERATED, ItemStatus.HUMAN_REVIEWED,
                                           ItemStatus.LINGUIST_VALIDATED, ItemStatus.ACTIVE)]
    return e
