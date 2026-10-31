"""Tests T2.5 — promotion active + garde-fou quarantaine. 1 test = 1 AC."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from src.db import make_engine
from src.items.quarantine import (
    ItemStats,
    active_pool,
    apply_quarantine,
    expected_success,
    is_drifting,
)
from src.items.review import InvalidTransition, promote, promote_to_active
from src.models.base import AnswerFormat, Base, CompetencyStatus, ItemStatus, Subject
from src.models.competency import Competency
from src.models.item import Item

CONTENT = {"stem": "q", "options": ["1/4", "3/4"], "answer": "3/4"}


def _session() -> Session:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _competency(s) -> Competency:
    c = Competency(code="MATH.G4.NF.ADD_LIKE", label_en="x", label_ar="س",
                   subject=Subject.MATH, grade=4, difficulty_prior=1200.0,
                   status=CompetencyStatus.ACTIVE)
    s.add(c); s.commit()
    return c


def _item(s, *, ar_validated=True, status=ItemStatus.LINGUIST_VALIDATED) -> Item:
    c = _competency(s)
    it = Item(competency_id=c.id, content_en=dict(CONTENT), content_ar=dict(CONTENT),
              answer_format=AnswerFormat.MCQ, difficulty_prior=1200.0,
              ar_validated=ar_validated, status=status)
    s.add(it); s.commit()
    return it


# --- fonctions pures ---

def test_expected_success_monotonic():
    # plus l'item est difficile, plus la réussite attendue baisse
    assert expected_success(1200.0) == 0.5
    assert expected_success(2000.0) < 0.1
    assert expected_success(400.0) > 0.9


def test_is_drifting_basic():
    assert is_drifting(ItemStats(50, 0.95, 2000.0)) is True       # facile en pratique, annoncé dur
    assert is_drifting(ItemStats(50, 0.50, 1200.0)) is False      # cohérent
    assert is_drifting(ItemStats(5, 0.95, 2000.0)) is False       # trop peu de réponses


# --- ACs ---

def test_ac1_no_active_without_ar_validated():
    # AC1 : un item sans ar_validated ne peut pas passer active
    s = _session()
    it = _item(s, ar_validated=False)
    try:
        promote_to_active(s, it, reviewer="r")
        assert False, "promotion sans ar_validated aurait dû être refusée"
    except InvalidTransition:
        pass


def test_ac2_drift_triggers_quarantine():
    # AC2 : item active, réussite 95% mais difficulty_elo très élevé, n≥seuil → quarantined
    s = _session()
    it = _item(s)
    promote_to_active(s, it, reviewer="r")
    assert it.status == ItemStatus.ACTIVE
    changed = apply_quarantine(s, it, ItemStats(n_responses=50, success_rate=0.95, difficulty_elo=2000.0))
    assert changed is True
    assert it.status == ItemStatus.QUARANTINED
    assert "dérive" in it.provenance.get("quarantine_reason", "")


def test_ac3_quarantined_excluded_from_pool():
    # AC3 : un item quarantined n'est pas retourné par la sélection
    s = _session()
    it = _item(s)
    promote_to_active(s, it, reviewer="r")
    assert it in active_pool(s)
    apply_quarantine(s, it, ItemStats(50, 0.95, 2000.0))
    assert it not in active_pool(s)
    assert active_pool(s) == []


def test_ac4_no_quarantine_below_threshold():
    # AC4 : sous le seuil de réponses, aucune quarantaine (pas de quarantaine sur du bruit)
    s = _session()
    it = _item(s)
    promote_to_active(s, it, reviewer="r")
    changed = apply_quarantine(s, it, ItemStats(n_responses=5, success_rate=0.95, difficulty_elo=2000.0))
    assert changed is False
    assert it.status == ItemStatus.ACTIVE


def test_quarantine_is_reversible():
    s = _session()
    it = _item(s)
    promote_to_active(s, it, reviewer="r")
    apply_quarantine(s, it, ItemStats(50, 0.95, 2000.0))
    assert it.status == ItemStatus.QUARANTINED
    promote(s, it, ItemStatus.ACTIVE, reviewer="r")  # réhabilitation
    assert it.status == ItemStatus.ACTIVE
    assert it in active_pool(s)


def test_a2_accepted_flag_quarantines_like_drift_and_is_reversible():
    from src.items.review import flag_item, resolve_flag
    from src.models.base import ItemFlagReason
    from src.models.org import AppUser
    s = _session()
    it = _item(s)
    reviewer = AppUser(email="rev@atlas.io"); s.add(reviewer); s.commit()
    promote_to_active(s, it, reviewer="r")
    fl = flag_item(s, it, raised_by=None, reason=ItemFlagReason.WRONG_ANSWER_KEY)
    resolve_flag(s, fl, resolver=reviewer.id, accept=True); s.commit()
    assert it.status == ItemStatus.QUARANTINED and it not in active_pool(s)
    promote(s, it, ItemStatus.ACTIVE, reviewer="r")      # réhabilitation : même chemin
    assert it in active_pool(s)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
