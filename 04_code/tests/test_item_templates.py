"""Refonte A3 + Q15 — gabarits : backfill des clés sans perte, quarantaine en masse,
régénération en nouvelle version (idempotente), calibration repartant de zéro.

« Fait quand » (A3) : après correction d'un gabarit, la CLI crée N nouvelles versions
`ai_generated` avec `supersedes_id`, les anciennes sont `quarantined`, leurs réponses ne pèsent
plus sur la calibration.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import app, get_db
from src.engine.elo import ITEM_BURN_IN, update_elo
from src.items import deterministic, review, templates
from src.items.generation import GeneratedItem
from src.items.quarantine import active_pool
from src.models import competency, item, measurement, org, session as _se, audit as _au  # noqa: F401
from src.models.base import (
    AnswerFormat, Base, CompetencyStatus, ItemFlagReason, ItemFlagStatus, ItemStatus, Role, Subject,
)
from src.models.competency import Competency
from src.models.item import Item
from src.models.org import AppUser, Membership
from src.rbac.auth import make_token

CODE = "MATH.G3.NS.MULT_FACTS"      # générateur réel : 10 items


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _comp(s, code=CODE):
    c = Competency(code=code, label_en="x", label_ar="س", subject=Subject.MATH, grade=3,
                   difficulty_prior=1100.0, status=CompetencyStatus.ACTIVE)
    s.add(c); s.flush()
    return c


def _seed_bank(s, comp, *, keyed=True, status=ItemStatus.ACTIVE):
    """Banque déterministe telle que generate_bank_deterministic la produit (clés ou non)."""
    gen = [GeneratedItem(competency_id=comp.id, content_en=e["content"], answer_format=AnswerFormat.MCQ,
                         difficulty_prior=e["difficulty_prior"], context_tags=e["context_tags"],
                         provenance={"generator": "deterministic", "method": "exact-fraction"},
                         template_key=e["template_key"] if keyed else None)
           for e in deterministic.bank_items(CODE, comp.difficulty_prior)]
    items = review.insert_generated_items(s, gen)
    for it in items:
        it.status = status
        it.ar_validated = True
        it.content_ar = dict(it.content_en)
    s.commit()
    return items


def _patched_generator(monkeypatch, *, change_rank=0, extra=0):
    """Simule une correction du code : modifie un distracteur du rang `change_rank`, ajoute
    `extra` items en fin de liste."""
    original = deterministic.GENERATORS[CODE]

    def fixed():
        out = [dict(x) for x in original()]
        o = list(out[change_rank]["options"])
        o[-1] = "999"
        out[change_rank]["options"] = o
        for i in range(extra):
            out.append({"stem": f"What is {11 + i} × 2?", "options": [str(22 + 2 * i), "7", "8"],
                        "answer": str(22 + 2 * i)})
        return out
    monkeypatch.setitem(deterministic.GENERATORS, CODE, fixed)


# ---------- clés ----------

def test_parse_key():
    assert templates.parse_key("MATH.G4.NF.ADD_LIKE#03") == ("MATH.G4.NF.ADD_LIKE", 3)
    assert templates.parse_key("MATH.G4.NF.ADD_LIKE") == ("MATH.G4.NF.ADD_LIKE", None)
    for bad in ("", "X#a"):
        with pytest.raises(templates.TemplateError):
            templates.parse_key(bad)


# ---------- Q15 : backfill sans perte ----------

def test_backfill_keys_matches_by_content_and_keeps_everything_else():
    s = _session(); comp = _comp(s)
    items = _seed_bank(s, comp, keyed=False)                    # banque antérieure à A2
    items[0].n_responses, items[0].difficulty_elo = 25, 1234.0  # calibration réelle
    drift = items[1]; drift.content_en = {**drift.content_en, "stem": "Edited by hand"}   # plus apparié
    llm = Item(competency_id=comp.id, content_en={"stem": "llm", "options": ["1", "2"], "answer": "1"},
               answer_format=AnswerFormat.MCQ, difficulty_prior=1100.0,
               provenance={"provider": "groq"})                 # item LLM : ignoré
    s.add(llm); s.commit()

    dry = templates.backfill_template_keys(s, dry_run=True)
    assert dry.matched == 9 and dry.unmatched == [str(drift.id)] and dry.skipped_non_deterministic == 1
    s.expire_all()
    assert all(it.template_key is None for it in s.execute(select(Item)).scalars())   # dry-run : rien écrit

    rep = templates.backfill_template_keys(s); s.commit()
    assert rep.matched == 9 and rep.per_code == {CODE: 9} and rep.unmatched == [str(drift.id)]
    s.expire_all()
    it0 = s.get(Item, items[0].id)
    assert it0.template_key == f"{CODE}#00" and it0.n_responses == 25 and it0.difficulty_elo == 1234.0
    assert it0.status == ItemStatus.ACTIVE and "template_key_backfilled_at" in it0.provenance
    assert s.get(Item, drift.id).template_key is None and s.get(Item, llm.id).template_key is None
    assert len(s.execute(select(Item)).scalars().all()) == 11                      # rien supprimé
    # idempotent
    rep2 = templates.backfill_template_keys(s); s.commit()
    assert rep2.matched == 0 and rep2.already_keyed == 9 and rep2.unmatched == [str(drift.id)]


def test_backfill_flags_ambiguous_signatures(monkeypatch):
    s = _session(); comp = _comp(s)
    original = deterministic.GENERATORS[CODE]
    monkeypatch.setitem(deterministic.GENERATORS, CODE, lambda: original()[:1] * 2)   # 2 rangs identiques
    items = _seed_bank(s, comp, keyed=False)          # 2 items de même signature
    rep = templates.backfill_template_keys(s)
    assert set(rep.ambiguous) == {str(i.id) for i in items} and rep.matched == 0
    assert all(i.template_key is None for i in items)


# ---------- A3 : quarantaine en masse ----------

def test_quarantine_template_goes_through_state_machine():
    s = _session(); comp = _comp(s)
    items = _seed_bank(s, comp)
    items[3].status = ItemStatus.HUMAN_REVIEWED; s.commit()   # en revue : intouchable
    done = templates.quarantine_template(s, CODE, by="ops", reason="distracteur faux"); s.commit()
    assert len(done) == 9 and all(it.status == ItemStatus.QUARANTINED for it in done)
    assert items[3].status == ItemStatus.HUMAN_REVIEWED
    assert active_pool(s) == []
    assert "quarantaine au gabarit" in done[0].provenance["quarantine_reason"]
    # une seule lignée
    s2 = _session(); comp2 = _comp(s2); its = _seed_bank(s2, comp2)
    done = templates.quarantine_template(s2, f"{CODE}#04", by="ops"); s2.commit()
    assert [d.id for d in done] == [its[4].id] and sum(1 for i in its if i.status == ItemStatus.ACTIVE) == 9


# ---------- A3 : régénération ----------

def test_regenerate_is_idempotent_when_code_unchanged():
    s = _session(); comp = _comp(s); _seed_bank(s, comp)
    rep = templates.regenerate_template(s, CODE, by="ops"); s.commit()
    assert rep.regenerated == [] and rep.created == [] and len(rep.unchanged) == 10
    assert len(s.execute(select(Item)).scalars().all()) == 10


def test_regenerate_after_code_fix_creates_versions_and_retires_old(monkeypatch):
    s = _session(); comp = _comp(s)
    items = _seed_bank(s, comp)
    old = items[2]; old.n_responses, old.difficulty_elo = 40, 1300.0
    reviewer = AppUser(email="rev@atlas.io"); s.add(reviewer); s.flush()
    fl = review.flag_item(s, old, raised_by=None, reason=ItemFlagReason.SEVERAL_CORRECT); s.commit()
    _patched_generator(monkeypatch, change_rank=2, extra=1)

    dry = templates.regenerate_template(s, CODE, by="ops", dry_run=True)
    assert dry.regenerated == [(f"{CODE}#02", 1, 2)] and dry.created == [f"{CODE}#10"]
    assert len(s.execute(select(Item)).scalars().all()) == 10 and old.status == ItemStatus.ACTIVE

    rep = templates.regenerate_template(s, CODE, by="ops", resolver_id=reviewer.id); s.commit()
    assert rep.regenerated == [(f"{CODE}#02", 1, 2)] and rep.created == [f"{CODE}#10"]
    assert len(rep.unchanged) == 9 and rep.flags_accepted == 1
    s.expire_all()
    new = [i for i in templates.lineage(s, f"{CODE}#02") if i.version == 2][0]
    old = s.get(Item, old.id)
    assert new.status == ItemStatus.AI_GENERATED and new.supersedes_id == old.id
    assert new.content_en["options"][-1] == "999" and new.ar_validated is False
    assert new.content_ar and new.content_ar["options"][-1] == "999"      # proposition AR déterministe, à valider
    assert new.n_responses == 0 and new.difficulty_elo == new.difficulty_prior       # calibration neuve
    assert old.status == ItemStatus.QUARANTINED and old.n_responses == 40            # réponses conservées
    assert s.get(type(fl), fl.id).status == ItemFlagStatus.ACCEPTED
    created = templates.lineage(s, f"{CODE}#10")
    assert len(created) == 1 and created[0].version == 1 and created[0].status == ItemStatus.AI_GENERATED
    assert templates.current_versions(s, CODE)[f"{CODE}#02"].id == new.id
    assert len(active_pool(s)) == 9

    # relancer sans nouveau changement : rien
    rep2 = templates.regenerate_template(s, CODE, by="ops"); s.commit()
    assert rep2.regenerated == [] and rep2.created == [] and len(rep2.unchanged) == 11
    # une lignée hors du générateur → erreur explicite
    with pytest.raises(templates.TemplateError):
        templates.regenerate_template(s, f"{CODE}#42", by="ops")
    with pytest.raises(templates.TemplateError):
        templates.regenerate_template(s, "MATH.NOPE", by="ops")


def test_regenerate_single_lineage_and_unpublished_old_is_rejected(monkeypatch):
    s = _session(); comp = _comp(s)
    items = _seed_bank(s, comp, status=ItemStatus.HUMAN_REVIEWED)
    _patched_generator(monkeypatch, change_rank=5)
    rep = templates.regenerate_template(s, f"{CODE}#05", by="ops"); s.commit()
    assert rep.regenerated == [(f"{CODE}#05", 1, 2)] and rep.unchanged == []
    s.expire_all()
    old = s.get(Item, items[5].id)
    assert old.deleted_at is not None and old.status == ItemStatus.HUMAN_REVIEWED   # jamais publié : rejeté
    assert len(s.execute(select(Item).where(Item.deleted_at.is_(None))).scalars().all()) == 10


def test_new_version_calibration_starts_frozen_in_burn_in():
    # Les réponses antérieures ne pèsent plus : la nouvelle version (n_responses=0) est en
    # burn-in, sa difficulté ne bouge pas tant que ITEM_BURN_IN réponses ne l'ont pas touchée.
    s = _session(); comp = _comp(s); it = _seed_bank(s, comp)[0]
    it.n_responses, it.difficulty_elo = 60, 1400.0; s.commit()
    review.reset_calibration(s, it, by="ops")
    assert it.n_responses == 0 and it.difficulty_elo == it.difficulty_prior
    _, d = update_elo(1200.0, it.difficulty_elo, True, 0, it.n_responses)
    assert d == it.difficulty_elo                       # gelée pendant le burn-in
    _, d2 = update_elo(1200.0, it.difficulty_elo, True, 0, ITEM_BURN_IN + 1)
    assert d2 != it.difficulty_elo                      # après burn-in : recalibration réelle


# ---------- API /ops/templates ----------

def _auth(uid):
    return {"Authorization": f"Bearer {make_token(str(uid))}"}


def _api(monkeypatch=None):
    s = _session(); comp = _comp(s); _seed_bank(s, comp)
    rev, su, teacher = (AppUser(email=f"{n}@x.io") for n in ("rev", "ops", "t"))
    s.add_all([rev, su, teacher]); s.flush()
    s.add_all([Membership(user_id=rev.id, role=Role.CONTENT_REVIEWER),
               Membership(user_id=su.id, role=Role.SUPER_ADMIN),
               Membership(user_id=teacher.id, role=Role.TEACHER)])
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    return TestClient(app), dict(rev=rev.id, su=su.id, teacher=teacher.id), s


def test_ops_templates_api(monkeypatch):
    client, ids, s = _api()
    try:
        assert client.get(f"/ops/templates/{CODE}", headers=_auth(ids["teacher"])).status_code == 403
        assert client.get("/ops/templates/MATH.NOPE", headers=_auth(ids["rev"])).status_code == 404
        rep = client.get(f"/ops/templates/{CODE}", headers=_auth(ids["rev"]))
        assert rep.status_code == 200 and len(rep.json()["lineages"]) == 10
        assert rep.json()["lineages"][0]["current"]["status"] == "active"

        _patched_generator(monkeypatch, change_rank=1)
        dry = client.post(f"/ops/templates/{CODE}/regenerate?dry_run=true", headers=_auth(ids["rev"])).json()
        assert dry["dry_run"] and len(dry["regenerated"]) == 1
        real = client.post(f"/ops/templates/{CODE}/regenerate", headers=_auth(ids["rev"])).json()
        assert real["regenerated"] == [{"template_key": f"{CODE}#01", "from_version": 1, "to_version": 2}]
        one = client.get(f"/ops/templates/{CODE}%2301", headers=_auth(ids["rev"])).json()["lineages"][0]
        assert [v["version"] for v in one["versions"]] == [1, 2] and one["current"]["status"] == "ai_generated"

        q = client.post(f"/ops/templates/{CODE}/quarantine", json={"reason": "revue"}, headers=_auth(ids["su"]))
        assert q.status_code == 200 and len(q.json()["quarantined"]) == 9      # la v2 en revue n'est pas active
        assert client.post(f"/ops/templates/{CODE}/quarantine", headers=_auth(ids["teacher"])).status_code == 403
        assert active_pool(s) == []
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    print("lancer avec pytest (monkeypatch requis)")
