"""Génération de la version arabe d'un item (T2.4).

La machine PROPOSE la traduction (modèle arabe natif ALLaM par défaut),
le linguiste humain VALIDE (gate `ar_validated`, voir review.py).

Modèle par défaut : `allam-2-7b` (ALLaM, SDAIA) — arabe natif, aligné GCC.
Client injectable → swappable (Jais/Fanar) sans toucher au pipeline.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from pydantic import ValidationError

from src.llm.client import LLMClient
from src.models.base import AnswerFormat
from src.models.item import ItemContent

ALLAM_MODEL = "allam-2-7b"


class TranslationError(Exception):
    """Sortie de traduction inexploitable (JSON invalide ou contenu non conforme)."""


_SYSTEM = (
    "You translate K-12 mathematics test items from English to Modern Standard Arabic (الفصحى). "
    "Keep ALL numbers, fractions and mathematical symbols identical and untranslated. "
    "Translate only the natural-language wording. Preserve the order of options. "
    "Output STRICT JSON only — no prose, no markdown. "
    'Schema: {"stem": string, "options": [string, ...], "answer": string}.'
)


def _build_prompt(content_en: dict) -> str:
    return (
        "Translate this item to Arabic. The `answer` must stay equal to the matching option.\n"
        f"{json.dumps(content_en, ensure_ascii=False)}\n\nReturn JSON only."
    )


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _norm_digits(s: str) -> str:
    return (s or "").translate(_AR_DIGITS)


# Token numérique : entier, décimal (1.5 / 1,5) ou fraction (3/8), chiffres normalisés.
_NUM_TOKEN = re.compile(r"\d+(?:[.,/]\d+)*")


def _num_multiset(s: Optional[str]) -> tuple:
    """Multiset (trié) des tokens numériques d'une chaîne, chiffres arabes normalisés."""
    return tuple(sorted(_NUM_TOKEN.findall(_norm_digits(s or ""))))


def ar_math_preserved(content_en: dict, content_ar: Optional[dict]) -> bool:
    """Fidélité math EN↔AR (déterministe) : les NOMBRES de la réponse et des options
    doivent être préservés. Comparaison par multisets numériques, PAS par égalité de
    chaînes : une option textuelle légitimement traduite (« They are equal » →
    « هما متساويان ») ne doit pas déclencher de faux positif (revue 2026-07-12 :
    29 faux positifs sur 38 flags avec l'égalité de chaînes). Le texte — stem inclus —
    reste le travail du linguiste : un nombre écrit en toutes lettres (« ثمانية »)
    n'est volontairement pas comparé.
    """
    if not content_ar:
        return False
    if _num_multiset(content_en.get("answer", "")) != _num_multiset(content_ar.get("answer", "")):
        return False
    en_opts = sorted(_num_multiset(o) for o in (content_en.get("options") or []))
    ar_opts = sorted(_num_multiset(o) for o in (content_ar.get("options") or []))
    return en_opts == ar_opts


def ar_stem_numbers_preserved(content_en: dict, content_ar: Optional[dict]) -> bool:
    """L'énoncé AR pose-t-il le MÊME problème que l'énoncé EN ? (revue 2026-07-12, CRIT-1)

    `ar_math_preserved` ne compare QUE answer + options ; il est aveugle au stem. Un
    stem AR peut donc énoncer « ثلث » (un tiers) là où l'anglais dit 3/4, garder la
    clé anglaise, et franchir tous les checks. Invariant : tout token numérique du
    stem EN doit apparaître dans le stem AR (INCLUSION, pas égalité — l'arabe peut
    ajouter un nombre, jamais en perdre). Suppose la convention E7 (chiffres 0-9) :
    un nombre écrit en toutes lettres (« ثمانية ») compte comme perdu — c'est
    intentionnel, il crée exactement l'ambiguïté que ce check traque.
    """
    if not content_ar:
        return False
    en_nums = set(_num_multiset(content_en.get("stem", "")))
    ar_nums = set(_num_multiset(content_ar.get("stem", "")))
    return en_nums <= ar_nums


def ar_mcq_structure_ok(content_en: dict, content_ar: Optional[dict]) -> bool:
    """Invariant structurel MCQ EN↔AR (revue 2026-07-12, CRIT-1) : la bonne réponse
    AR doit être une des options AR, le nombre d'options doit correspondre, et la
    position de la bonne réponse doit être la même dans les deux langues (le prompt
    de traduction impose « preserve the order of options »). Attrape une clé AR qui
    pointe une mauvaise position. Coût nul, zéro faux positif constaté sur la banque.
    """
    if not content_ar:
        return False
    en_opts = content_en.get("options") or []
    ar_opts = content_ar.get("options") or []
    if not en_opts:  # non-MCQ (NUMERIC/SHORT) : rien à vérifier ici
        return True
    if len(en_opts) != len(ar_opts):
        return False
    ar_answer = content_ar.get("answer")
    if ar_answer not in ar_opts:
        return False
    en_answer = content_en.get("answer")
    return en_answer in en_opts and en_opts.index(en_answer) == ar_opts.index(ar_answer)


# ≥ 2 lettres latines consécutives = mot résiduel non traduit. La notation
# mathématique acceptée (chiffres occidentaux 0-9, point décimal, barres de
# fraction, opérateurs — convention E7) ne contient AUCUNE lettre : zéro faux
# positif sur « 1/2 + 3/4 = ؟ ». Une lettre isolée (variable « x ») est tolérée.
_LATIN_TOKEN = re.compile(r"[A-Za-z]{2,}")


def ar_latin_tokens(text: Optional[str]) -> List[str]:
    """Tokens latins résiduels d'un texte AR (errata E8, gate G3).

    Le check numérique (`ar_math_preserved`) ne peut pas attraper un mot anglais
    non traduit (ex. « ONE » dans un stem de fraction) : cette détection lexicale
    complète la fidélité math. Dédoublonné, ordre d'apparition conservé.
    """
    seen: List[str] = []
    for tok in _LATIN_TOKEN.findall(text or ""):
        if tok not in seen:
            seen.append(tok)
    return seen


def ar_content_latin_tokens(content_ar: Optional[dict]) -> List[str]:
    """Tokens latins sur l'ensemble du contenu AR (stem + options + answer)."""
    if not content_ar:
        return []
    parts = [content_ar.get("stem") or ""]
    parts.extend(content_ar.get("options") or [])
    parts.append(content_ar.get("answer") or "")
    seen: List[str] = []
    for part in parts:
        for tok in ar_latin_tokens(part):
            if tok not in seen:
                seen.append(tok)
    return seen


# Caractères ADMIS dans un contenu AR : écriture arabe (+ formes de présentation,
# marques bidi), chiffres occidentaux 0-9 et point décimal (convention E7), latin
# (les MOTS latins sont le travail de `ar_latin_tokens`), ponctuation et opérateurs
# scolaires. Tout le reste — grec, ±, Ⓒ, fractions unicode ⅕, diacritiques combinantes
# hors arabe… — est la signature d'une traduction corrompue (revue 2026-07-12 :
# 9 items ACTIFS dont les nombres étaient remplacés par des glyphes parasites,
# invisibles au détecteur de tokens latins).
_AR_ALLOWED_CHAR = re.compile(
    "["
    "\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"  # arabe + formes
    "\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069"  # controles bidi
    "0-9A-Za-z\\s"
    "\u2010-\u2015\u2026\u00A0"  # tirets, ellipse, nbsp
    ".,:;!?%()\\[\\]{}\"'\u00AB\u00BB_+\\-\u2212\u00D7\u00F7*/=<>\u2264\u2265\u00B0"  # \u2212 = « − » des énoncés
    "]"
)


def ar_suspect_glyphs(text: Optional[str]) -> List[str]:
    """Glyphes hors alphabet admis dans un texte AR — corruption d'encodage probable."""
    seen: List[str] = []
    for ch in text or "":
        if not _AR_ALLOWED_CHAR.match(ch) and ch not in seen:
            seen.append(ch)
    return seen


def ar_content_suspect_glyphs(content_ar: Optional[dict]) -> List[str]:
    """Glyphes suspects sur l'ensemble du contenu AR (stem + options + answer)."""
    if not content_ar:
        return []
    parts = [content_ar.get("stem") or ""]
    parts.extend(content_ar.get("options") or [])
    parts.append(content_ar.get("answer") or "")
    seen: List[str] = []
    for part in parts:
        for g in ar_suspect_glyphs(part):
            if g not in seen:
                seen.append(g)
    return seen


def ar_fidelity_errors(content_en: dict, content_ar: Optional[dict]) -> List[str]:
    """Liste des défauts de fidélité EN↔AR (vide = fidèle). Gate G3 (revue 2026-07-12).

    Agrège tous les checks déterministes : nombres answer/options, nombres du stem
    (CRIT-1), structure MCQ, tokens latins résiduels, glyphes parasites. Le linguiste
    ne peut valider un item que si cette liste est vide.
    """
    if not content_ar:
        return ["content_ar absent"]
    errs: List[str] = []
    if not ar_math_preserved(content_en, content_ar):
        errs.append("nombres de la réponse/options altérés")
    if not ar_stem_numbers_preserved(content_en, content_ar):
        errs.append("l'énoncé AR ne reprend pas tous les nombres de l'énoncé EN "
                    "(problème mathématique différent, ou nombre écrit en toutes lettres)")
    if not ar_mcq_structure_ok(content_en, content_ar):
        errs.append("structure MCQ incohérente (réponse absente des options, "
                    "nombre d'options différent, ou position de la bonne réponse décalée)")
    latin = ar_content_latin_tokens(content_ar)
    if latin:
        errs.append(f"tokens latins résiduels : {latin}")
    glyphs = ar_content_suspect_glyphs(content_ar)
    if glyphs:
        errs.append(f"glyphes parasites (corruption d'encodage) : {glyphs}")
    return errs


def ar_coverage(session) -> dict:
    """Couverture arabe de la banque d'items — rend la « descente » de l'AR MESURABLE.

    Prérequis de vente KSA (bench, Mouvement 02) : on veut prouver que l'arabe est dans le
    contenu (questions validées par un linguiste), pas seulement dans le chrome. Agrégat
    bank-level (les items ne sont pas scopés école).
    """
    from sqlalchemy import select
    from src.models.base import ItemStatus
    from src.models.item import Item

    items = list(session.execute(select(Item).where(Item.deleted_at.is_(None))).scalars())
    total = len(items)
    with_ar = sum(1 for it in items if it.content_ar)
    validated = sum(1 for it in items if it.ar_validated and it.content_ar)
    active = sum(1 for it in items if it.status == ItemStatus.ACTIVE)
    math_ok = sum(1 for it in items
                  if it.content_ar and ar_math_preserved(it.content_en, it.content_ar))
    return {
        "total_items": total,
        "with_ar": with_ar,
        "ar_validated": validated,
        "active": active,
        "math_preserved": math_ok,
        "pct_validated": round(validated / total, 3) if total else 0.0,
    }


def translate_to_arabic(
    content_en: dict,
    client: LLMClient,
    *,
    answer_format: Optional[AnswerFormat] = None,
    temperature: float = 0.2,
) -> dict:
    """Propose `content_ar` à partir de `content_en`. Valide ItemContent + règle MCQ.

    Ne persiste rien : la sortie part en validation linguiste (review.set_arabic).
    """
    raw = client.complete_json(_SYSTEM, _build_prompt(content_en), temperature=temperature)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise TranslationError(f"JSON invalide : {e}") from e

    try:
        content = ItemContent.model_validate(data)
    except ValidationError as e:
        raise TranslationError(f"Contenu AR non conforme : {e}") from e

    if answer_format == AnswerFormat.MCQ:
        opts = content.options or []
        if len(opts) < 2 or content.answer not in opts:
            raise TranslationError("MCQ AR : `answer` doit faire partie des options.")

    return content.model_dump(exclude_none=True)
