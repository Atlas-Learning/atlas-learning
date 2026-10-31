"""Workflow de revue humaine des items (T2.3).

- Persiste les items générés (T2.2) en base, statut `ai_generated`.
- Machine à états des statuts : aucune transition ne saute d'étape.
- Approuver / rejeter (soft delete, jamais détruit) / éditer.
- Trace le reviewer dans `provenance`.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.items.arabic import ar_fidelity_errors
from src.items.generation import GeneratedItem
from src.models.base import ItemFlagReason, ItemFlagStatus, ItemStatus, utcnow
from src.models.item import Item, ItemContent, ItemFlag

# Cycle de vie autorisé : ai_generated → human_reviewed → linguist_validated → active.
# quarantined : sortie/réhabilitation du pool. Aucun saut d'étape.
ALLOWED_TRANSITIONS = {
    ItemStatus.AI_GENERATED: {ItemStatus.HUMAN_REVIEWED},
    ItemStatus.HUMAN_REVIEWED: {ItemStatus.LINGUIST_VALIDATED},
    ItemStatus.LINGUIST_VALIDATED: {ItemStatus.ACTIVE},
    ItemStatus.ACTIVE: {ItemStatus.QUARANTINED},
    ItemStatus.QUARANTINED: {ItemStatus.ACTIVE},
}

# Préconditions par statut cible. L'AR doit être validée pour franchir l'étape linguiste.
TRANSITION_GUARDS = {
    ItemStatus.LINGUIST_VALIDATED: lambda it: bool(it.ar_validated and it.content_ar),
}


class InvalidTransition(Exception):
    """Transition de statut interdite (saut d'étape, cible non autorisée, ou précondition non remplie)."""


def _stamp_reviewer(item: Item, reviewer: str, **extra) -> None:
    """Écrit l'identité du reviewer dans provenance (réassignation = change tracking)."""
    prov = dict(item.provenance or {})
    prov["reviewer"] = reviewer
    prov["reviewed_at"] = utcnow().isoformat(timespec="seconds")
    prov.update(extra)
    item.provenance = prov


def insert_generated_items(session: Session, generated: List[GeneratedItem]) -> List[Item]:
    """Persiste des GeneratedItem en Item (statut ai_generated, content_ar en attente T2.4)."""
    items: List[Item] = []
    for g in generated:
        item = Item(
            competency_id=g.competency_id,
            content_en=g.content_en,
            content_ar=g.content_ar,  # None (T2.4 : LLM) ou proposition déterministe (A3), non validée
            answer_format=g.answer_format,
            difficulty_prior=g.difficulty_prior,
            context_tags=dict(g.context_tags),
            status=ItemStatus.AI_GENERATED,
            provenance=dict(g.provenance or {}),
            template_key=g.template_key,
            ar_validated=False,
        )
        session.add(item)
        items.append(item)
    session.commit()
    return items


def list_pending(session: Session) -> List[Item]:
    """Items à revoir : ai_generated, non supprimés."""
    return list(
        session.execute(
            select(Item)
            .where(Item.status == ItemStatus.AI_GENERATED, Item.deleted_at.is_(None))
            .order_by(Item.created_at)
        ).scalars()
    )


def promote(session: Session, item: Item, target: ItemStatus, reviewer: str) -> Item:
    """Fait avancer l'item d'un cran. Lève InvalidTransition si le saut est interdit."""
    allowed = ALLOWED_TRANSITIONS.get(item.status, set())
    if target not in allowed:
        raise InvalidTransition(
            f"{item.status.value} → {target.value} interdit "
            f"(autorisé : {sorted(s.value for s in allowed) or 'aucun'})"
        )
    guard = TRANSITION_GUARDS.get(target)
    if guard is not None and not guard(item):
        raise InvalidTransition(
            f"{item.status.value} → {target.value} bloqué : précondition non remplie "
            "(AR non validée : ar_validated requis)."
        )
    item.status = target
    _stamp_reviewer(item, reviewer)
    session.commit()
    return item


def approve(session: Session, item: Item, reviewer: str) -> Item:
    """Raccourci : ai_generated → human_reviewed (AC1)."""
    return promote(session, item, ItemStatus.HUMAN_REVIEWED, reviewer)


def reject(session: Session, item: Item, reviewer: str, reason: str) -> Item:
    """Rejette un item : soft delete (jamais détruit), trace reviewer + raison (AC3)."""
    item.deleted_at = utcnow()
    _stamp_reviewer(item, reviewer, rejected=True, reject_reason=reason)
    session.commit()
    return item


def edit(
    session: Session,
    item: Item,
    reviewer: str,
    *,
    content_en: Optional[dict] = None,
    context_tags: Optional[dict] = None,
) -> Item:
    """Corrige un item pendant la revue (le contenu reste validé par ItemContent)."""
    if content_en is not None:
        ItemContent.model_validate(content_en)  # garde-fou
        item.content_en = content_en
    if context_tags is not None:
        item.context_tags = dict(context_tags)
    _stamp_reviewer(item, reviewer, edited=True)
    session.commit()
    return item


# --- T2.4 : version arabe ---

def list_pending_arabic(session: Session) -> List[Item]:
    """Worklist du linguiste : items revus en EN (human_reviewed) dont l'AR n'est pas validée.

    C'est là que se joue la « descente » de l'arabe : ces items attendent une traduction
    proposée puis validée avant de pouvoir être servis (gate ar_validated).
    """
    return list(
        session.execute(
            select(Item)
            .where(
                Item.status == ItemStatus.HUMAN_REVIEWED,
                Item.ar_validated.is_(False),
                Item.deleted_at.is_(None),
            )
            .order_by(Item.created_at)
        ).scalars()
    )


def set_arabic(session: Session, item: Item, content_ar: dict, *, by: str) -> Item:
    """Pose/corrige `content_ar` (validé ItemContent). N'altère JAMAIS content_en (AC3).

    Repose ar_validated à False : toute modification AR doit être re-validée.
    """
    ItemContent.model_validate(content_ar)  # garde-fou
    item.content_ar = content_ar
    item.ar_validated = False
    _stamp_reviewer(item, by, ar_proposed_by=by)
    session.commit()
    return item


def validate_arabic(session: Session, item: Item, *, linguist: str) -> Item:
    """Le linguiste valide l'AR : ar_validated=True puis human_reviewed → linguist_validated.

    Exige un `content_ar` présent, conforme, ET fidèle à l'EN (gate G3, revue 2026-07-12,
    CRIT-1) : nombres du stem préservés, structure MCQ cohérente, pas de token latin ni
    de glyphe parasite. C'est le garde-fou qui aurait empêché les 5 items au stem faux
    de devenir `active`.
    """
    if not item.content_ar:
        raise InvalidTransition("Pas de content_ar à valider.")
    ItemContent.model_validate(item.content_ar)
    errors = ar_fidelity_errors(item.content_en, item.content_ar)
    if errors:
        raise InvalidTransition(
            "Validation AR refusée — défauts de fidélité EN↔AR : " + " ; ".join(errors)
        )
    item.ar_validated = True
    _stamp_reviewer(item, linguist, ar_validated_by=linguist)
    session.commit()
    return promote(session, item, ItemStatus.LINGUIST_VALIDATED, reviewer=linguist)


# --- T2.5 : promotion en pool actif ---

def promote_to_active(session: Session, item: Item, reviewer: str) -> Item:
    """Promeut un item en `active` (servi aux élèves).

    Précondition explicite (AC1) : `ar_validated` requis. L'item doit aussi être
    `linguist_validated` (garanti par la machine à états : on n'y arrive qu'après
    revue EN + validation AR).
    """
    if not item.ar_validated:
        raise InvalidTransition("Promotion active refusée : ar_validated requis.")
    return promote(session, item, ItemStatus.ACTIVE, reviewer=reviewer)


# --- Refonte A2 : signalements et versions ---------------------------------------------
#
# Un signalement n'altère JAMAIS le statut d'un item par lui-même. Il entre dans la file de
# revue ; son acceptation passe par la machine à états (`promote` → quarantined, uniquement
# depuis `active`). Aucun raccourci, aucun UPDATE direct du statut (invariant 6).

def flag_item(session: Session, item: Item, *, raised_by: Optional[uuid.UUID],
              reason: ItemFlagReason, comment: Optional[str] = None,
              school_id: Optional[uuid.UUID] = None) -> ItemFlag:
    """Signale un item. Ne touche ni au statut ni au contenu. Ne commit pas."""
    if item.deleted_at is not None:
        raise InvalidTransition("Item supprimé : signalement impossible.")
    flag = ItemFlag(item_id=item.id, school_id=school_id, raised_by=raised_by,
                    reason=reason, comment=(comment or "").strip() or None)
    session.add(flag)
    session.flush()
    return flag


def list_flags(session: Session, *, status: Optional[ItemFlagStatus] = ItemFlagStatus.OPEN,
               limit: int = 200) -> List[ItemFlag]:
    """File des signalements (les plus anciens d'abord). `status=None` = tous."""
    stmt = select(ItemFlag)
    if status is not None:
        stmt = stmt.where(ItemFlag.status == status)
    return list(session.execute(stmt.order_by(ItemFlag.created_at).limit(limit)).scalars())


def open_flag_count(session: Session, item_id: uuid.UUID) -> int:
    return len(session.execute(
        select(ItemFlag.id).where(ItemFlag.item_id == item_id, ItemFlag.status == ItemFlagStatus.OPEN)
    ).all())


def resolve_flag(session: Session, flag: ItemFlag, *, resolver: uuid.UUID, accept: bool,
                 quarantine: bool = True) -> ItemFlag:
    """Tranche un signalement. Accepté + `quarantine` : l'item sort du pool servi — par
    `promote(... QUARANTINED)`, donc seulement s'il est `active` ; un item encore en revue
    garde son statut (il sera corrigé au gabarit, A3). Refusé : l'item n'est pas touché."""
    if flag.status != ItemFlagStatus.OPEN:
        raise InvalidTransition("Signalement déjà tranché.")
    item = session.get(Item, flag.item_id)
    flag.status = ItemFlagStatus.ACCEPTED if accept else ItemFlagStatus.REJECTED
    flag.resolved_by = resolver
    flag.resolved_at = utcnow()
    if accept and quarantine and item is not None and item.status == ItemStatus.ACTIVE:
        promote(session, item, ItemStatus.QUARANTINED, reviewer=str(resolver))
        _stamp_reviewer(item, str(resolver), quarantined=True,
                        quarantine_reason=f"signalement accepté : {flag.reason.value}")
    session.flush()
    return flag


def supersede(session: Session, old: Item, *, content_en: dict, by: str,
              content_ar: Optional[dict] = None, context_tags: Optional[dict] = None,
              difficulty_prior: Optional[float] = None) -> Item:
    """Nouvelle version d'un item (énoncé ou réponse corrigés au gabarit, A3).

    La nouvelle version repart en `ai_generated` (revue complète), `version + 1`,
    `supersedes_id` posé, même gabarit et même compétence. L'ancienne version sort du pool :
    `active → quarantined` par la machine à états ; une version jamais publiée est rejetée
    (soft delete, jamais détruite). Les réponses existantes restent attachées à l'ancienne."""
    ItemContent.model_validate(content_en)
    if content_ar:
        ItemContent.model_validate(content_ar)
    new = Item(
        competency_id=old.competency_id,
        content_en=content_en,
        content_ar=content_ar,
        answer_format=old.answer_format,
        difficulty_prior=old.difficulty_prior if difficulty_prior is None else difficulty_prior,
        context_tags=dict(context_tags if context_tags is not None else (old.context_tags or {})),
        status=ItemStatus.AI_GENERATED,
        provenance={**{k: v for k, v in (old.provenance or {}).items()
                       if k in ("generator", "method", "provider", "model")},
                    "superseded_from": str(old.id), "regenerated_by": by},
        origin=old.origin,
        template_key=old.template_key,
        version=old.version + 1,
        supersedes_id=old.id,
        owner_school_id=old.owner_school_id,
    )
    session.add(new)
    if old.status == ItemStatus.ACTIVE:
        promote(session, old, ItemStatus.QUARANTINED, reviewer=by)
        _stamp_reviewer(old, by, quarantined=True, quarantine_reason="remplacé par une nouvelle version")
    elif old.status != ItemStatus.QUARANTINED and old.deleted_at is None:
        reject(session, old, reviewer=by, reason="remplacé par une nouvelle version")
    session.commit()
    return new


def reset_calibration(session: Session, item: Item, *, by: str) -> Item:
    """Remet la calibration à zéro sans changer de version (correction qui ne touche ni
    l'énoncé ni la réponse) : les réponses antérieures ne pèsent plus sur `difficulty_elo`."""
    item.calibration_reset_at = utcnow()
    item.n_responses = 0
    item.difficulty_elo = item.difficulty_prior
    _stamp_reviewer(item, by, calibration_reset=True)
    session.commit()
    return item
