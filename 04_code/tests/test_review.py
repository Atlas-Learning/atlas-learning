"""Tests T2.3 — workflow de revue. 1 test = 1 AC (+ chaîne complète)."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db import make_engine
from src.items.generation import GeneratedItem
from src.items.review import (
    InvalidTransition,
    approve,
    edit,
    insert_generated_items,
    list_pending,
    promote,
    reject,
)
from src.models.base import AnswerFormat, Base, CompetencyStatus, ItemStatus, Subject
from src.models.competency import Competency
from src.models.item import Item


def _session() -> Session:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _competency(s: Session) -> Competency:
    c = Competency(code="MATH.G4.NF.ADD_LIKE", label_en="x", label_ar="س",
                   subject=Subject.MATH, grade=4, difficulty_prior=1200.0,
                   status=CompetencyStatus.ACTIVE)
    s.add(c); s.commit()
    return c


def _generated(cid, n=2):
    return [
        GeneratedItem(
            competency_id=cid,
            content_en={"stem": f"q{i}", "options": ["1/4", "3/4"], "answer": "3/4"},
            answer_format=AnswerFormat.MCQ,
            difficulty_prior=1180.0,
            context_tags={"simplify": bool(i % 2)},
            provenance={"provider": "groq", "model": "m", "prompt_id": str(uuid.uuid4())},
        )
        for i in range(n)
    ]


def _seed_items(s):
    c = _competency(s)
    return insert_generated_items(s, _generated(c.id, 2))


def test_insert_and_list_pending():
    s = _session()
    items = _seed_items(s)
    assert len(items) == 2
    assert all(it.status == ItemStatus.AI_GENERATED for it in items)
    assert all(it.content_ar is None for it in items)  # AR en attente T2.4
    assert len(list_pending(s)) == 2


def test_ac1_approve_sets_human_reviewed():
    # AC1 : ai_generated approuvé → human_reviewed
    s = _session()
    it = _seed_items(s)[0]
    approve(s, it, reviewer="nassim")
    assert it.status == ItemStatus.HUMAN_REVIEWED


def test_ac2_no_skip_to_active():
    # AC2 : ai_generated → active directement → refusé
    s = _session()
    it = _seed_items(s)[0]
    try:
        promote(s, it, ItemStatus.ACTIVE, reviewer="nassim")
        assert False, "le saut d'étape aurait dû être refusé"
    except InvalidTransition:
        pass
    assert it.status == ItemStatus.AI_GENERATED  # inchangé


def test_ac3_reject_is_soft_delete_not_destroyed():
    # AC3 : item rejeté marqué (soft delete), pas détruit
    s = _session()
    it = _seed_items(s)[0]
    iid = it.id
    reject(s, it, reviewer="nassim", reason="énoncé ambigu")
    total = s.execute(select(func.count()).select_from(Item).where(Item.id == iid)).scalar_one()
    assert total == 1, "l'item rejeté doit rester en base"
    assert it.deleted_at is not None
    assert it not in list_pending(s)
    assert it.provenance.get("reject_reason") == "énoncé ambigu"


def test_ac4_provenance_records_reviewer():
    # AC4 : provenance contient l'identité du reviewer après action
    s = _session()
    items = _seed_items(s)
    approve(s, items[0], reviewer="alice")
    reject(s, items[1], reviewer="bob", reason="hors compétence")
    assert items[0].provenance["reviewer"] == "alice"
    assert "reviewed_at" in items[0].provenance
    assert items[1].provenance["reviewer"] == "bob"


def test_full_lifecycle_step_by_step():
    # chaîne complète sans saut : ai_generated → human_reviewed → linguist_validated → active
    s = _session()
    it = _seed_items(s)[0]
    promote(s, it, ItemStatus.HUMAN_REVIEWED, "r")
    # étape linguiste : l'AR doit être posée + validée (garde TRANSITION_GUARDS)
    it.content_ar = {"stem": "؟", "options": ["1/4", "3/4"], "answer": "3/4"}
    it.ar_validated = True
    promote(s, it, ItemStatus.LINGUIST_VALIDATED, "r")
    promote(s, it, ItemStatus.ACTIVE, "r")
    assert it.status == ItemStatus.ACTIVE


def test_edit_revalidates_content():
    s = _session()
    it = _seed_items(s)[0]
    edit(s, it, reviewer="nassim", content_en={"stem": "fixed", "options": ["a", "b"], "answer": "a"})
    assert it.content_en["stem"] == "fixed"
    assert it.provenance.get("edited") is True
    # contenu invalide rejeté
    try:
        edit(s, it, reviewer="nassim", content_en={"options": ["a"]})
        assert False, "contenu invalide aurait dû être rejeté"
    except Exception:
        pass


def test_a2_resolve_flag_never_bypasses_allowed_transitions():
    # Refonte A2 : accepter un signalement ne « saute » jamais d'étape — seul active → quarantined
    # est possible ; tout autre statut reste tel quel, et ALLOWED_TRANSITIONS est inchangé.
    from src.items.review import ALLOWED_TRANSITIONS, flag_item, resolve_flag
    from src.models.base import ItemFlagReason
    from src.models.org import AppUser
    assert ALLOWED_TRANSITIONS == {
        ItemStatus.AI_GENERATED: {ItemStatus.HUMAN_REVIEWED},
        ItemStatus.HUMAN_REVIEWED: {ItemStatus.LINGUIST_VALIDATED},
        ItemStatus.LINGUIST_VALIDATED: {ItemStatus.ACTIVE},
        ItemStatus.ACTIVE: {ItemStatus.QUARANTINED},
        ItemStatus.QUARANTINED: {ItemStatus.ACTIVE},
    }
    s = _session()
    reviewer = AppUser(email="rev@atlas.io"); s.add(reviewer); s.commit()
    c = _competency(s)
    items = insert_generated_items(s, _generated(c.id, 3))
    for it, status in zip(items, (ItemStatus.AI_GENERATED, ItemStatus.HUMAN_REVIEWED,
                                  ItemStatus.LINGUIST_VALIDATED)):
        it.status = status; s.commit()
        fl = flag_item(s, it, raised_by=None, reason=ItemFlagReason.WRONG_ANSWER_KEY)
        resolve_flag(s, fl, resolver=reviewer.id, accept=True); s.commit()
        assert it.status == status


def test_a2_inserted_items_carry_template_key():
    s = _session()
    c = _competency(s)
    gen = _generated(c.id, 1)
    gen[0].template_key = "MATH.G4.NF.ADD_LIKE#00"
    it = insert_generated_items(s, gen)[0]
    assert it.template_key == "MATH.G4.NF.ADD_LIKE#00" and it.version == 1 and it.supersedes_id is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
