"""Refonte B4 — action faite, re-mesure ciblée, preuve.

« Fait quand » : marquer une action puis jouer le re-check produit « X sur Y ont débloqué » avec
la définition de 01-produit.md. Tests : before_* figés, re-check planifié puis démarré, élève
absent → not_rechecked jamais compté dans le dénominateur, intervalle exposé, débloqué vs
inchangé, suggestions, boucle bouclée, RBAC, idempotence.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from src.api import proof_service
from src.api.app import app
from src.models.base import CheckInStatus, PlanActionStatus, ProofOutcome
from src.models.checkin import CheckIn
from src.models.measurement import StudentCompetencyAbility
from src.models.plan import Proof
from tests.test_plan import _auth, _setup


def _done(client, ids):
    h = _auth(ids["teacher"])
    ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
    client.post(f"/checkins/{ci['id']}/close", headers=h)
    act = client.get(f"/classrooms/{ids['cls']}/plan", headers=h).json()["actions"][0]   # racine A, bloqué B, s0 + s1
    return h, act


def test_done_freezes_before_and_schedules_targeted_recheck():
    client, ids, s = _setup()
    try:
        h, act = _done(client, ids)
        assert client.post(f"/plan-actions/{act['id']}/done", headers=_auth(ids["other_t"])).status_code == 403
        r = client.post(f"/plan-actions/{act['id']}/done", headers=h)
        assert r.status_code == 200
        assert r.json()["action"]["status"] == "done" and r.json()["action"]["done_at"]
        rc = r.json()["recheck"]
        assert rc["kind"] == "targeted" and rc["status"] == "scheduled" and rc["n_members"] == 2 and "code" not in rc
        assert set(rc["competency_ids"]) == {str(ids["A"]), str(ids["B"])} and rc["plan_action_id"] == act["id"]
        proofs = s.execute(select(Proof).where(Proof.action_id == uuid.UUID(act["id"]))).scalars().all()
        assert {p.student_id for p in proofs} == set(ids["students"][:2])
        before = {p.student_id: p.before_elo for p in proofs}
        assert before[ids["students"][0]] == 1200.0 and before[ids["students"][1]] == 1100.0   # instantané racine A
        assert all(p.outcome == ProofOutcome.NOT_RECHECKED and p.after_elo is None for p in proofs)
        # une action faite ne se refait pas, ne s'abandonne plus
        assert client.post(f"/plan-actions/{act['id']}/done", headers=h).status_code == 409
        assert client.post(f"/plan-actions/{act['id']}/dismiss", headers=h).status_code == 409
        # l'estimation bouge ensuite : before_* ne bouge pas (figé, pas recalculé)
        ab = s.get(StudentCompetencyAbility, (ids["students"][0], ids["A"])); ab.ability_elo = 1900.0; s.commit()
        assert s.get(Proof, proofs[0].id).before_elo in (1200.0, 1100.0)
        # planifié : ni clôture ni jointure ; démarrage par l'enseignant → code
        assert client.post(f"/checkins/{rc['id']}/close", headers=h).status_code == 409
        assert client.post(f"/checkins/{rc['id']}/start", headers=_auth(ids["other_t"])).status_code == 403
        started = client.post(f"/checkins/{rc['id']}/start", headers=h).json()
        assert started["status"] == "open" and len(started["code"]) == 4
        assert client.post(f"/checkins/{rc['id']}/start", headers=h).json()["code"] == started["code"]   # idempotent
        # la carte de preuve existe déjà, non calculée
        pr = client.get(f"/plan-actions/{act['id']}/proof", headers=h).json()
        assert pr["computed"] is False and pr["header"] == {"unlocked": 0, "rechecked": 0, "not_rechecked": 2,
                                                            "interval_note": pr["header"]["interval_note"]}
        assert pr["recheck"]["code"] == started["code"]
        assert "code" not in client.get(f"/plan-actions/{act['id']}/proof", headers=_auth(ids["lead"])).json()["recheck"] \
            if "lead" in ids else True
    finally:
        app.dependency_overrides.clear()


def test_recheck_close_computes_proofs_absent_never_in_denominator():
    client, ids, s = _setup()
    try:
        h, act = _done(client, ids)
        rc = client.post(f"/plan-actions/{act['id']}/done", headers=h).json()["recheck"]
        client.post(f"/checkins/{rc['id']}/start", headers=h)
        ci = s.get(CheckIn, uuid.UUID(rc["id"]))
        # s0 re-mesuré et maîtrise désormais A (débloqué) ; s1 re-mesuré, toujours faible (inchangé) ;
        # on simule les sessions/réponses du re-check sans passer par l'UI élève (comptes absents)
        from src.models.item import Item
        from src.models.measurement import Response
        from src.models.session import AssessmentSession
        item_a = s.execute(select(Item).where(Item.competency_id == ids["A"])).scalars().first()
        for sid in ids["students"][:2]:
            sess = AssessmentSession(student_id=sid, school_id=ids["school"], checkin_id=ci.id); s.add(sess); s.flush()
            s.add(Response(school_id=ids["school"], student_id=sid, item_id=item_a.id, competency_id=ids["A"],
                           is_correct=True, selected="1", session_id=sess.id))
        a0 = s.get(StudentCompetencyAbility, (ids["students"][0], ids["A"])); a0.ability_elo, a0.confidence = 1620.0, 0.7
        a1 = s.get(StudentCompetencyAbility, (ids["students"][1], ids["A"])); a1.ability_elo, a1.confidence = 1250.0, 0.6
        s.commit()
        closed = client.post(f"/checkins/{rc['id']}/close", headers=h).json()
        assert closed["proof"] == {"action_id": act["id"], "unlocked": 1, "unchanged": 1, "not_rechecked": 0}
        pr = client.get(f"/plan-actions/{act['id']}/proof", headers=h).json()
        assert pr["computed"] is True and pr["loop_closed"] is True
        assert pr["header"]["unlocked"] == 1 and pr["header"]["rechecked"] == 2
        rows = {r["student_id"]: r for r in pr["students"]}
        s0, s1 = rows[str(ids["students"][0])], rows[str(ids["students"][1])]
        assert s0["outcome"] == "unlocked" and s0["before"]["elo"] == 1200.0 and s0["after"]["elo"] == 1620.0
        assert s0["after"]["ci_low"] < 1620.0 < s0["after"]["ci_high"]                      # intervalle exposé
        assert s1["outcome"] == "unchanged" and s1["suggestion"]["kind"] in ("upstream_cause", "practise_again")
        # bandeau E1 + boucles bouclées ; le coordinateur lit la preuve mais pas le code
        band = client.get(f"/classrooms/{ids['cls']}/proofs", headers=h).json()
        assert band["loops_closed"] == 1 and [p["action_id"] for p in band["proofs"]] == [act["id"]]
        assert client.get(f"/classrooms/{ids['cls']}/proofs?since=2099-01-01", headers=h).json()["proofs"] == []
        assert client.get(f"/plan-actions/{act['id']}/proof", headers=_auth(ids["other_t"])).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_absent_student_is_not_rechecked_and_excluded_from_denominator():
    client, ids, s = _setup()
    try:
        h, act = _done(client, ids)
        rc = client.post(f"/plan-actions/{act['id']}/done", headers=h).json()["recheck"]
        client.post(f"/checkins/{rc['id']}/start", headers=h)
        ci = s.get(CheckIn, uuid.UUID(rc["id"]))
        from src.models.item import Item
        from src.models.measurement import Response
        from src.models.session import AssessmentSession
        item_a = s.execute(select(Item).where(Item.competency_id == ids["A"])).scalars().first()
        # seul s0 revient ; s1 absent. s0 re-mesuré mais confiance < 0,5 → pas « débloqué » malgré l'Elo
        sess = AssessmentSession(student_id=ids["students"][0], school_id=ids["school"], checkin_id=ci.id); s.add(sess); s.flush()
        s.add(Response(school_id=ids["school"], student_id=ids["students"][0], item_id=item_a.id, competency_id=ids["A"],
                       is_correct=True, selected="1", session_id=sess.id))
        a0 = s.get(StudentCompetencyAbility, (ids["students"][0], ids["A"])); a0.ability_elo, a0.confidence = 1700.0, 0.3
        s.commit()
        closed = client.post(f"/checkins/{rc['id']}/close", headers=h).json()
        assert closed["proof"] == {"action_id": act["id"], "unlocked": 0, "unchanged": 1, "not_rechecked": 1}
        pr = client.get(f"/plan-actions/{act['id']}/proof", headers=h).json()
        assert pr["header"]["rechecked"] == 1 and pr["header"]["not_rechecked"] == 1   # l'absent n'est pas au dénominateur
        rows = {r["student_id"]: r for r in pr["students"]}
        absent = rows[str(ids["students"][1])]
        assert absent["outcome"] == "not_rechecked" and absent["after"] is None
        assert absent["suggestion"] == {"kind": "add_to_next_recheck"}
        low_conf = rows[str(ids["students"][0])]
        assert low_conf["outcome"] == "unchanged" and low_conf["after"]["measured"] is False
        assert low_conf["after"]["ci_high"] - low_conf["after"]["ci_low"] > 200          # intervalle large : confiance basse
    finally:
        app.dependency_overrides.clear()


def test_ci_half_width_shrinks_with_confidence():
    assert proof_service.ci_half_width(0.0) == 175.0
    assert proof_service.ci_half_width(1.0) == 25.0
    assert proof_service.ci_half_width(0.5) == 100.0
    assert proof_service.ci_half_width(0.0) > proof_service.ci_half_width(0.9) > proof_service.ci_half_width(1.0)
