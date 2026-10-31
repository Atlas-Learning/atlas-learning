"""Pipeline de génération d'items (T2.2).

Génère N items EN pour une compétence via un LLMClient injectable.
Sortie : objets `GeneratedItem` validés — AUCUNE insertion en base ici
(la revue T2.3 et l'AR T2.4 viennent après).

Garde-fou sécu : le prompt ne contient QUE la compétence + le contexte demandé,
jamais de donnée élève.
"""
from __future__ import annotations

import json
import uuid
from typing import List, Optional, Protocol

from pydantic import BaseModel, Field, ValidationError

from src.llm.client import LLMClient
from src.models.base import AnswerFormat, ItemStatus
from src.models.item import ItemContent


class GenerationError(Exception):
    """Sortie LLM inexploitable (JSON invalide, contenu non conforme, MCQ incohérent)."""


class _CompetencyLike(Protocol):
    id: uuid.UUID
    code: str
    label_en: str
    cognitive_level: object
    difficulty_prior: float


class GeneratedItem(BaseModel):
    """Item généré, validé, prêt pour la revue (pas encore en base)."""

    competency_id: uuid.UUID
    content_en: dict
    answer_format: AnswerFormat
    difficulty_prior: float
    context_tags: dict
    status: ItemStatus = ItemStatus.AI_GENERATED
    provenance: dict = Field(default_factory=dict)
    # Refonte A2 : gabarit d'origine (ex. `MATH.G4.NF.ADD_LIKE#03`), None pour un item LLM.
    template_key: Optional[str] = None


_SYSTEM = (
    "You are an expert K-12 mathematics assessment item writer. "
    "You write a single, self-contained question that measures exactly ONE skill. "
    "Output STRICT JSON only — no prose, no markdown. "
    'Schema: {"stem": string, "options": [string, ...], "answer": string}. '
    "For MCQ: provide 3-4 plausible options and ensure `answer` is EXACTLY one of them."
)


def _build_user_prompt(comp: _CompetencyLike, context: dict, answer_format: AnswerFormat) -> str:
    """Construit le prompt utilisateur. N'inclut QUE compétence + contexte (zéro PII)."""
    cog = getattr(comp.cognitive_level, "value", comp.cognitive_level)
    return (
        f"Skill code: {comp.code}\n"
        f"Skill: {comp.label_en}\n"
        f"Cognitive level: {cog}\n"
        f"Target difficulty (Elo scale ~[1000-1600]): {comp.difficulty_prior}\n"
        f"Answer format: {answer_format.value}\n"
        f"Context constraints (must be respected): {json.dumps(context, ensure_ascii=False)}\n\n"
        "Write ONE English question for this exact skill and context. Return JSON only."
    )


def _finalize(raw: str, answer_format: AnswerFormat) -> dict:
    """Parse + valide la sortie LLM. Lève GenerationError si inexploitable."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise GenerationError(f"JSON invalide : {e}") from e

    try:
        content = ItemContent.model_validate(data)
    except ValidationError as e:
        raise GenerationError(f"Contenu non conforme à ItemContent : {e}") from e

    if answer_format == AnswerFormat.MCQ:
        opts = content.options or []
        if len(opts) < 2:
            raise GenerationError("MCQ : au moins 2 options requises.")
        if content.answer not in opts:
            raise GenerationError("MCQ : `answer` doit faire partie des options.")

    return content.model_dump(exclude_none=True)


def generate_items(
    competency: _CompetencyLike,
    context_targets: List[dict],
    client: LLMClient,
    *,
    answer_format: AnswerFormat = AnswerFormat.MCQ,
    n_per_target: int = 1,
    temperature: float = 0.7,
) -> List[GeneratedItem]:
    """Génère `len(context_targets) * n_per_target` items pour `competency`.

    Chaque cible de `context_targets` est couverte (AC3). Chaque item porte le
    `competency_id` (AC2), parse en `ItemContent` (AC1) et respecte la règle MCQ (AC4).
    """
    items: List[GeneratedItem] = []
    for context in context_targets:
        for _ in range(n_per_target):
            user = _build_user_prompt(competency, context, answer_format)
            raw = client.complete_json(_SYSTEM, user, temperature=temperature)
            content = _finalize(raw, answer_format)
            items.append(
                GeneratedItem(
                    competency_id=competency.id,
                    content_en=content,
                    answer_format=answer_format,
                    difficulty_prior=competency.difficulty_prior,
                    context_tags=dict(context),
                    status=ItemStatus.AI_GENERATED,
                    provenance={
                        "provider": "groq" if "groq" in type(client).__name__.lower() else "llm",
                        "model": client.model,
                        "prompt_id": str(uuid.uuid4()),
                    },
                )
            )
    return items
