"""Générateur du plan de la semaine (refonte B2) — fonction PURE, déterministe.

Entrée : pour chaque élève de la classe, ses estimations par compétence (Elo, confiance,
n_direct) ; le graphe des prérequis HARD ; l'UNITÉ (compétences visées par le check-in) ;
les libellés EN et AR. Sortie : 2 à 4 actions `reteach`, chacune = un groupe d'élèves qui
partagent une CAUSE RACINE (diagnostic causal existant, `diagnosis.diagnose_all`, on ne le
réécrit pas) + la compétence où l'erreur se voit + une phrase « parce que » EN et AR.

Règles (docs/refonte/04-plan.md, B2) :
- grouper par cause racine ; une racine compte UNE fois par élève ;
- trier par nombre d'élèves débloquables (puis code de la racine : stable) ;
- `confidence = partly_estimated` si UN membre a la racine estimée (confiance < 0,5 ou jamais
  mesurée directement), `measured` sinon ;
- aucune action sans membre ; aucune action sur une compétence hors unité : la compétence
  bloquée appartient à l'unité ; la racine peut être un prérequis en amont de l'unité (c'est
  tout l'intérêt du diagnostic causal) ;
- même entrée → même plan : aucune dépendance à l'ordre des dicts ou des listes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, NamedTuple, Optional

from src.restitution.diagnosis import MASTERY_ELO, diagnose_all

CONFIDENCE_THRESHOLD = 0.5      # aligné sur web/lib/mastery.ts et scale.py
MIN_ACTIONS, MAX_ACTIONS = 2, 4


class Ability(NamedTuple):
    elo: float
    confidence: float
    n_direct: int


@dataclass(frozen=True)
class MemberDraft:
    student_id: str
    gap: str                     # compétence (de l'unité) où l'erreur se voit pour CET élève
    root_measured: bool          # la racine est mesurée directement avec confiance suffisante


@dataclass
class ActionDraft:
    rank: int
    root_cause: str
    blocked: str
    members: List[MemberDraft]
    confidence: str              # measured | partly_estimated
    because_en: str
    because_ar: str
    kind: str = "reteach"
    n_unlockable: int = field(init=False)

    def __post_init__(self):
        self.n_unlockable = len(self.members)


def _is_measured(ab: Optional[Ability]) -> bool:
    return ab is not None and ab.n_direct > 0 and ab.confidence >= CONFIDENCE_THRESHOLD


def because_sentences(root: str, blocked: str, n: int, labels_en: Dict[str, str],
                      labels_ar: Dict[str, str]) -> "tuple[str, str]":
    """Phrase « parce que » déterministe. Chiffres occidentaux (convention E7) ; les libellés
    arabes des compétences viennent du référentiel (`Competency.label_ar`)."""
    r_en, b_en = labels_en.get(root, root), labels_en.get(blocked, blocked)
    r_ar, b_ar = labels_ar.get(root, root), labels_ar.get(blocked, blocked)
    students_en = "student" if n == 1 else "students"
    if root == blocked:
        en = f"Because {b_en} itself is not mastered yet, {n} {students_en} need to practise it."
        ar = f"لأن «{b_ar}» غير مُتقَن بعد، يحتاج {n} من الطلاب إلى التدرّب عليه."
    else:
        en = f"Because {r_en} is not mastered yet, {n} {students_en} are blocked on {b_en}."
        ar = f"لأن «{r_ar}» غير مُتقَن بعد، يتعثّر {n} من الطلاب في «{b_ar}»."
    return en, ar


class WrongAnswer(NamedTuple):
    stem: str
    selected: str


def observed_error_text(wrong: List[WrongAnswer], n_items: int) -> Optional[str]:
    """« Erreur observée » d'un membre (Q16) : l'erreur la plus fréquente parmi ses réponses
    fausses sur la compétence bloquée pendant le check-in, avec le volume. Déterministe (ex
    aequo : énoncé puis option les plus petits). None sans réponse fausse enregistrée."""
    if not wrong or n_items <= 0:
        return None
    counts: Dict[WrongAnswer, int] = {}
    for w in wrong:
        counts[w] = counts.get(w, 0) + 1
    top = min(counts, key=lambda w: (-counts[w], w.stem, w.selected))
    n_wrong = len(wrong)
    return f"{top.stem} → {top.selected} · {n_wrong} of {n_items} items wrong"


def build_plan(
    abilities_by_student: Dict[str, Dict[str, Ability]],
    hard_prereqs: Dict[str, List[str]],
    unit: Iterable[str],
    labels_en: Dict[str, str],
    labels_ar: Dict[str, str],
    *,
    threshold: float = MASTERY_ELO,
    max_actions: int = MAX_ACTIONS,
) -> List[ActionDraft]:
    """Les actions du plan, triées, numérotées à partir de 1. Peut renvoyer moins de
    MIN_ACTIONS actions si la classe n'a pas assez de causes racines distinctes : on n'invente
    pas d'action (l'écran propose alors le premier check-in ou félicite)."""
    unit_set = set(unit)
    # racine → {student_id → (gap, root_measured)} ; dicts parcourus en ordre trié : déterminisme
    by_root: Dict[str, Dict[str, "tuple[str, bool]"]] = {}
    for sid in sorted(abilities_by_student):
        abs_ = abilities_by_student[sid]
        elos = {code: a.elo for code, a in abs_.items()}
        diags = [d for d in diagnose_all(elos, hard_prereqs, threshold=threshold) if d.gap in unit_set]
        seen: Dict[str, "tuple[str, bool]"] = {}
        # une racine par élève ; la compétence « où l'erreur se voit » est de préférence en aval
        # de la racine (is_self en dernier), puis le code le plus petit : stable
        for d in sorted(diags, key=lambda d: (d.is_self, d.gap)):
            if d.root_cause in seen:
                continue
            root_ab = abs_.get(d.root_cause)
            seen[d.root_cause] = (d.gap, _is_measured(root_ab))
        for root, (gap, measured) in seen.items():
            by_root.setdefault(root, {})[sid] = (gap, measured)

    drafts: List[ActionDraft] = []
    for root in sorted(by_root):
        members_raw = by_root[root]
        if not members_raw:
            continue                                            # aucune action sans membre
        # compétence bloquée de l'action = la plus fréquente parmi les membres (puis code)
        gap_counts: Dict[str, int] = {}
        for gap, _ in members_raw.values():
            gap_counts[gap] = gap_counts.get(gap, 0) + 1
        blocked = min(gap_counts, key=lambda g: (-gap_counts[g], g))
        if blocked not in unit_set:
            continue                                            # jamais hors unité
        members = [MemberDraft(sid, gap, measured) for sid, (gap, measured) in sorted(members_raw.items())]
        confidence = "measured" if all(m.root_measured for m in members) else "partly_estimated"
        en, ar = because_sentences(root, blocked, len(members), labels_en, labels_ar)
        drafts.append(ActionDraft(0, root, blocked, members, confidence, en, ar))

    drafts.sort(key=lambda a: (-a.n_unlockable, a.root_cause))
    drafts = drafts[:max_actions]
    for i, a in enumerate(drafts, start=1):
        a.rank = i
    return drafts
