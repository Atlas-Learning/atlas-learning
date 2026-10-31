"""Orchestrateur on_response (Epic 3, T3.4).

À la réception d'une réponse : écrit la `response`, met à jour l'Elo direct (T3.1),
la confiance (T3.2), propage aux voisins (T3.3) — le tout en UNE transaction atomique.
Aucun LLM. Isolation tenant (school_id sur toutes les écritures).
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from src.engine.elo import Neighbor, confidence, propagate, update_elo
from src.models.base import ResponseLanguage, utcnow
from src.models.competency import CompetencyPrerequisite
from src.models.item import Item
from src.models.measurement import Response, StudentCompetencyAbility

ELO_START = 1500.0  # ability initiale (centre de l'échelle) tant que jamais mesurée


def _ability(session: Session, student_id, competency_id, school_id) -> StudentCompetencyAbility:
    row = session.get(StudentCompetencyAbility, (student_id, competency_id))
    if row is None:
        row = StudentCompetencyAbility(
            student_id=student_id, competency_id=competency_id, school_id=school_id,
            ability_elo=ELO_START, n_direct=0, confidence=0.0,
        )
        session.add(row)
    return row


def on_response(
    session: Session,
    *,
    student_id: uuid.UUID,
    item_id: uuid.UUID,
    is_correct: bool,
    school_id: uuid.UUID,
    response_time_ms: Optional[int] = None,
    session_id: Optional[uuid.UUID] = None,
    response_id: Optional[uuid.UUID] = None,
    language: ResponseLanguage = ResponseLanguage.EN,
    selected: Optional[str] = None,
) -> Response:
    """Applique une réponse de bout en bout (transaction atomique). Retourne la Response.

    Idempotent : rejouer la même `response_id` ne réapplique pas l'effet. Le rejeu est
    SIGNALÉ à l'appelant par l'attribut transitoire `replayed` (True = Response existante,
    rien réappliqué) — sans ce signal, session_service ré-émettait une entrée AuditLog
    et répondait 200 alors que le même rejeu plus tard donne 409 (revue 2026-07-08).
    """
    if response_id is not None:
        existing = session.get(Response, response_id)
        if existing is not None:
            # Rejeu : rien n'est réappliqué. Attribut NON MAPPÉ (jamais persisté),
            # porté par l'instance seulement — l'appelant convertit en 409 uniforme.
            existing.replayed = True
            return existing  # déjà appliquée

    try:
        # --- verrouillage pessimiste (revue concurrence 2026-07-07) ---
        # Toutes les lignes lues-puis-écrites ici (item, ability élève, abilities des
        # voisins touchés par la propagation) sont verrouillées via SELECT ... FOR UPDATE :
        # sans verrou, deux réponses simultanées font un read-modify-write last-write-wins
        # en READ COMMITTED (Elo/compteurs écrasés, pire sur un item populaire).
        # Ordre DÉTERMINISTE d'acquisition : l'item d'abord (une seule ligne par
        # transaction), puis les abilities triées par competency_id — deux transactions
        # concurrentes prennent toujours les verrous dans le même ordre → pas de deadlock.
        # NB : SQLite (dev/CI) ignore FOR UPDATE silencieusement — acceptable, la prod
        # tourne sur Postgres où le verrou est effectif.
        item = session.get(Item, item_id, with_for_update=True)
        if item is None:
            raise ValueError(f"item {item_id} introuvable")
        comp_id = item.competency_id

        # Arêtes du graphe : lecture SEULE (jamais réécrites ici) → pas de verrou.
        # On les lit AVANT les updates pour connaître l'ensemble des abilities à verrouiller.
        edges = session.execute(
            select(CompetencyPrerequisite).where(
                or_(CompetencyPrerequisite.source_id == comp_id,
                    CompetencyPrerequisite.target_id == comp_id)
            )
        ).scalars().all()
        neighbor_comp_ids = [
            e.target_id if e.source_id == comp_id else e.source_id for e in edges
        ]

        # Verrouille les abilities (élève + tous les voisins candidats à la propagation),
        # une par une, en ordre trié (déterministe). Une ligne encore absente ne peut pas
        # être verrouillée : on la crée et on la flushe ICI MÊME, dans le MÊME ordre trié
        # que les verrous — deux transactions concurrentes émettent donc leurs INSERTs
        # dans le même ordre (pas d'attente croisée sur la PK composite → pas de
        # deadlock ; l'ordre source-d'abord-puis-edges-DB de l'ancienne version en créait
        # un, cf. revue adversariale 2026-07-07). La course résiduelle sur une MÊME ligne
        # reste rejetée par la PK composite (student_id, competency_id) :
        # IntegrityError → rollback complet → l'appelant rejoue (session_service).
        for cid in sorted({comp_id, *neighbor_comp_ids}, key=str):
            row = session.get(StudentCompetencyAbility, (student_id, cid), with_for_update=True)
            if row is None:
                _ability(session, student_id, cid, school_id)
                session.flush()

        # --- update Elo direct (T3.1 + T3.2) ---
        ability = _ability(session, student_id, comp_id, school_id)
        old_ability = ability.ability_elo
        new_ability, new_item_diff = update_elo(
            ability.ability_elo, item.difficulty_elo, is_correct,
            ability.n_direct, item.n_responses,
        )
        ability.ability_elo = new_ability
        ability.n_direct += 1
        ability.confidence = confidence(ability.n_direct)
        ability.last_measured_at = utcnow()
        item.difficulty_elo = new_item_diff
        item.n_responses += 1
        delta = new_ability - old_ability

        # --- propagation 1-saut (T3.3) ---
        neighbors = []
        for e in edges:
            nb_comp = e.target_id if e.source_id == comp_id else e.source_id
            nb_row = session.get(StudentCompetencyAbility, (student_id, nb_comp))
            neighbors.append(Neighbor(
                competency_id=nb_comp,
                ability=nb_row.ability_elo if nb_row else ELO_START,
                confidence=nb_row.confidence if nb_row else 0.0,
                correlation_strength=e.correlation_strength,
                edge_type=e.edge_type.value,
            ))
        for p in propagate(delta, ability.confidence, neighbors):
            nb_row = _ability(session, student_id, p.competency_id, school_id)
            nb_row.ability_elo = p.new_ability      # inféré : on ne touche PAS n_direct ni confidence

        # --- response append-only ---
        # `language` (C-0) : locale de la session appelante, 'en' hors session — coercition
        # par VALEUR ('en'/'ar') pour les appels directs (scripts, seeds) passant un str.
        resp = Response(
            id=response_id or uuid.uuid4(),
            school_id=school_id, student_id=student_id, item_id=item_id,
            competency_id=comp_id, is_correct=is_correct, selected=selected,
            response_time_ms=response_time_ms, session_id=session_id,
            language=ResponseLanguage(language),
            created_at=utcnow(),
        )
        resp.replayed = False   # première application (cf. docstring : signal de rejeu)
        session.add(resp)
        session.commit()
        return resp
    except Exception:
        session.rollback()
        raise
