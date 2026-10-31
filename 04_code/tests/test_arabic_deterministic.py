"""Refonte A3 — version arabe déterministe des gabarits (invariant 2 : aucun LLM au runtime).

Couverture totale des générateurs, fidélité (nombres, structure MCQ, aucun token latin, aucun
glyphe parasite), déterminisme, et intégration : insertion de banque, régénération, proposition
sur une banque existante — toujours `ar_validated=False` (le linguiste valide).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scripts.propose_arabic_deterministic import propose_for_bank
from src.items import arabic_deterministic as ad
from src.items import deterministic, review, templates
from src.items.arabic import ar_fidelity_errors, ar_suspect_glyphs
from src.items.generation import GeneratedItem
from src.models import competency, item, measurement, org, session as _se, audit as _au  # noqa: F401
from src.models.base import AnswerFormat, Base, CompetencyStatus, ItemStatus, Subject
from src.models.competency import Competency
from src.models.item import Item

CODE = "MATH.G4.NF.SUB_SAME_SIMPLIFY"


def test_every_generated_item_has_a_faithful_arabic_rendering():
    done, total, missing = ad.coverage()
    assert missing == [] and done == total >= 300


def test_rendering_is_deterministic_and_faithful():
    for code, gen in deterministic.GENERATORS.items():
        for it in gen():
            ar = ad.render_arabic(it)
            assert ar == ad.render_arabic(it)                    # déterministe
            assert ar_fidelity_errors(it, ar) == []
            assert len(ar["options"]) == len(it["options"])
            assert ar["options"].index(ar["answer"]) == it["options"].index(it["answer"])
            assert ar_suspect_glyphs(ar["stem"]) == []


def test_minus_sign_is_a_legitimate_math_glyph():
    assert ar_suspect_glyphs("ما ناتج 3/4 − 1/4؟") == []


def test_unknown_stem_or_option_is_not_rendered():
    assert ad.render_stem("Translate me please") is None
    assert ad.render_arabic({"stem": "Translate me please", "options": ["1", "2"], "answer": "1"}) is None
    assert ad.render_arabic({"stem": "What is 1/2 + 1/4?", "options": ["3/4", "banana"], "answer": "3/4"}) is None
    assert ad.render_option("They are equal") == "هما متساويان" and ad.render_option("2 1/4") == "2 1/4"


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _comp(s):
    c = Competency(code=CODE, label_en="x", label_ar="س", subject=Subject.MATH, grade=4,
                   difficulty_prior=1300.0, status=CompetencyStatus.ACTIVE)
    s.add(c); s.flush()
    return c


def test_bank_insertion_and_regeneration_carry_a_proposal_never_validated(monkeypatch):
    s = _session(); comp = _comp(s)
    bank = deterministic.bank_items(CODE, comp.difficulty_prior)
    items = review.insert_generated_items(s, [
        GeneratedItem(competency_id=comp.id, content_en=e["content"], answer_format=AnswerFormat.MCQ,
                      difficulty_prior=e["difficulty_prior"], context_tags=e["context_tags"],
                      provenance={"generator": "deterministic"}, template_key=e["template_key"],
                      content_ar=ad.render_arabic(e["content"]))
        for e in bank])
    assert all(it.content_ar and not it.ar_validated for it in items)
    assert all(ar_fidelity_errors(it.content_en, it.content_ar) == [] for it in items)

    # régénération après « correction » : la nouvelle version porte une proposition AR neuve
    for it in items:
        it.status, it.ar_validated = ItemStatus.ACTIVE, True
    s.commit()
    original = deterministic.GENERATORS[CODE]

    def fixed():
        out = [dict(x) for x in original()]
        out[0]["options"] = list(out[0]["options"][:-1]) + ["99/100"]
        return out
    monkeypatch.setitem(deterministic.GENERATORS, CODE, fixed)
    rep = templates.regenerate_template(s, CODE, by="ops"); s.commit()
    assert len(rep.regenerated) == 1
    new = [i for i in templates.lineage(s, f"{CODE}#00") if i.version == 2][0]
    assert new.content_ar["options"][-1] == "99/100" and new.ar_validated is False
    assert ar_fidelity_errors(new.content_en, new.content_ar) == []


def test_propose_for_existing_bank_respects_validated_arabic():
    s = _session(); comp = _comp(s)
    bank = deterministic.bank_items(CODE, comp.difficulty_prior)
    items = review.insert_generated_items(s, [
        GeneratedItem(competency_id=comp.id, content_en=e["content"], answer_format=AnswerFormat.MCQ,
                      difficulty_prior=e["difficulty_prior"], context_tags=e["context_tags"],
                      provenance={"generator": "deterministic"}, template_key=e["template_key"])
        for e in bank])
    validated, llm = items[0], items[1]
    validated.content_ar = ad.render_arabic(validated.content_en); validated.ar_validated = True
    llm.content_ar = {"stem": "ترجمة آلية", "options": llm.content_en["options"], "answer": llm.content_en["answer"]}
    s.commit()
    rep = propose_for_bank(s, dry_run=True)
    assert rep["proposed"] == len(items) - 2 and rep["kept_unvalidated"] == 1 and rep["skipped_validated"] == 1
    assert items[2].content_ar is None                            # dry-run : rien écrit
    rep = propose_for_bank(s); s.commit()
    assert rep["proposed"] == len(items) - 2
    assert all(it.content_ar for it in items) and items[2].provenance["ar_proposed_by"] == "arabic_deterministic"
    assert llm.content_ar["stem"] == "ترجمة آلية"                 # non validée mais conservée sans --replace
    rep = propose_for_bank(s, replace_unvalidated=True); s.commit()
    assert rep["proposed"] == len(items) - 1 and llm.content_ar["stem"] != "ترجمة آلية"
    assert validated.ar_validated is True and s.get(Item, validated.id).content_ar == ad.render_arabic(validated.content_en)
