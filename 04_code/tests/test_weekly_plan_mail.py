"""Refonte B6 — message de début de semaine « votre plan est prêt ».

Q5 par défaut : réglage par école, lundi 7 h local (dimanche en Arabie saoudite), fuseau du pays.
Tests : dérivation du créneau, correspondance horaire en UTC, un enseignant avec plan reçoit UN
e-mail listant ses classes, un enseignant sans plan ne reçoit rien, pas de doublon dans l'heure,
plan trop ancien ignoré, dry-run, forçage admin, réglages d'école (RBAC et validation).
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from src.api.app import app, get_email_sender
from src.models.audit import AuditLog
from src.models.base import utcnow
from src.models.measurement import School
from src.models.org import AppUser, Classroom, Membership, TeacherClassroom
from src.models.plan import WeeklyPlan
from src.notify import weekly_plan as wp
from src.notify.email import FakeEmailSender
from tests.test_plan import _auth, _setup

Role = __import__("src.models.base", fromlist=["Role"]).Role


def test_schedule_defaults_by_country_and_overrides():
    s = School(name="AE"); s.country = "AE"
    assert wp.school_schedule(s) == wp.Schedule(0, 7, "Asia/Dubai")
    s.country = "SA"
    assert wp.school_schedule(s) == wp.Schedule(6, 7, "Asia/Riyadh")           # semaine qui commence le dimanche
    s.country = None
    assert wp.school_schedule(s) == wp.Schedule(0, 7, "UTC")
    s.country, s.plan_mail_weekday, s.plan_mail_hour, s.timezone = "SA", 1, 18, "Europe/Paris"
    assert wp.school_schedule(s) == wp.Schedule(1, 18, "Europe/Paris")
    s.timezone = "Mars/Olympus"
    assert wp.school_schedule(s).timezone == "UTC"                              # fuseau inconnu : repli


def test_is_due_uses_local_time():
    ae = School(name="AE"); ae.country = "AE"                                   # lundi 7 h Dubaï = dimanche 03:00 UTC… non : lundi 03:00 UTC
    monday_0300_utc = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)           # 2026-11-02 est un lundi
    due, key = wp.is_due(ae, monday_0300_utc)
    assert due and key == "2026-11-02"
    assert wp.is_due(ae, monday_0300_utc + timedelta(hours=1))[0] is False      # 8 h local
    assert wp.is_due(ae, monday_0300_utc - timedelta(days=1))[0] is False       # dimanche
    sa = School(name="SA"); sa.country = "SA"
    sunday_0400_utc = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)           # dimanche 7 h Riyad
    assert wp.is_due(sa, sunday_0400_utc) == (True, "2026-11-01")
    assert wp.is_due(sa, monday_0300_utc)[0] is False


def _with_plan(client, ids, s):
    h = _auth(ids["teacher"])
    ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
    client.post(f"/checkins/{ci['id']}/close", headers=h)
    school = s.get(School, ids["school"]); school.country = "AE"; s.commit()
    return school


def test_teacher_with_plan_gets_one_email_teacher_without_plan_gets_nothing():
    client, ids, s = _setup()
    try:
        school = _with_plan(client, ids, s)
        sender = FakeEmailSender()
        monday = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
        rep = wp.send_due(s, sender, now=monday, web_base="https://app.test"); s.commit()
        assert rep.due_schools == [str(school.id)] and rep.sent == ["t@x.io"]
        assert rep.skipped_no_plan == 1                                          # other_t : classe 5A sans plan
        mail = sender.sent[0]
        assert mail["to"] == "t@x.io" and "خطة أسبوعك جاهزة" in mail["subject"]
        assert f"https://app.test/teacher/{ids['cls']}/week" in mail["html"] and "4B" in mail["html"]
        assert "2 actions" in mail["html"] and "لأن" in mail["html"]
        assert "S0" not in mail["html"] and str(ids["students"][0]) not in mail["html"]   # aucune PII élève
        # relance dans l'heure : rien de plus ; heure suivante : hors créneau
        rep2 = wp.send_due(s, sender, now=monday + timedelta(minutes=30), web_base="https://app.test"); s.commit()
        assert rep2.sent == [] and rep2.skipped_already == 1 and len(sender.sent) == 1
        assert wp.send_due(s, sender, now=monday + timedelta(hours=1), web_base="x").due_schools == []
        # semaine suivante : renvoyé
        rep3 = wp.send_due(s, sender, now=monday + timedelta(days=7), web_base="https://app.test"); s.commit()
        assert rep3.sent == ["t@x.io"] and len(sender.sent) == 2
        audits = s.execute(select(AuditLog).where(AuditLog.action == wp.ACTION)).scalars().all()
        assert {a.details["week_key"] for a in audits} == {"2026-11-02", "2026-11-09"}
    finally:
        app.dependency_overrides.clear()


def test_stale_plan_dry_run_force_and_inactive_teacher():
    client, ids, s = _setup()
    try:
        school = _with_plan(client, ids, s)
        sender = FakeEmailSender()
        # plan de plus de 14 jours : plus « prêt »
        far = datetime(2027, 3, 1, 3, 0, tzinfo=timezone.utc)                      # un lundi, 4 mois plus tard
        assert wp.send_due(s, sender, now=far, web_base="x").sent == []
        # dry-run : liste les destinataires, n'envoie rien, n'écrit rien
        monday = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
        rep = wp.send_due(s, sender, now=monday, web_base="x", dry_run=True)
        assert rep.sent == ["t@x.io"] and sender.sent == []
        assert s.execute(select(AuditLog).where(AuditLog.action == wp.ACTION)).scalars().all() == []
        # forçage pour une école hors créneau (démo)
        rep = wp.send_due(s, sender, now=monday + timedelta(hours=5), web_base="x", force_school_id=school.id); s.commit()
        assert rep.sent == ["t@x.io"] and len(sender.sent) == 1
        # enseignant désactivé : ignoré
        t = s.get(AppUser, ids["teacher"]); t.is_active = False; s.commit()
        assert wp.send_due(s, FakeEmailSender(), now=monday + timedelta(days=7), web_base="x").sent == []
    finally:
        app.dependency_overrides.clear()


def test_settings_api_and_admin_trigger():
    client, ids, s = _setup()
    try:
        ped = AppUser(email="ped@x.io"); su = AppUser(email="ops@x.io"); s.add_all([ped, su]); s.flush()
        s.add_all([Membership(user_id=ped.id, role=Role.PED_ADMIN, school_id=ids["school"]),
                   Membership(user_id=su.id, role=Role.SUPER_ADMIN)])
        s.commit()
        url = f"/schools/{ids['school']}/settings"
        g = client.get(url, headers=_auth(ids["teacher"]))
        assert g.status_code == 403                                                # l'enseignant n'a pas la vue école
        g = client.get(url, headers=_auth(ped.id)).json()
        assert g["effective"] == {"weekday": 0, "hour": 7, "timezone": "UTC"} and g["country"] is None
        assert client.patch(url, json={"country": "SA"}, headers=_auth(ids["teacher"])).status_code == 403
        assert client.patch(url, json={"plan_mail_weekday": 9}, headers=_auth(ped.id)).status_code == 400
        assert client.patch(url, json={"timezone": "Nowhere/City"}, headers=_auth(ped.id)).status_code == 400
        assert client.patch(url, json={"country": "saudi"}, headers=_auth(ped.id)).status_code == 400
        r = client.patch(url, json={"country": "sa", "plan_mail_hour": 8}, headers=_auth(ped.id)).json()
        assert r["country"] == "SA" and r["effective"] == {"weekday": 6, "hour": 8, "timezone": "Asia/Riyadh"}
        # déclenchement admin : super admin seulement ; dry-run par défaut ; forçage école
        h = _auth(ids["teacher"])
        ci = client.post(f"/classrooms/{ids['cls']}/checkins", json={"kind": "full"}, headers=h).json()
        client.post(f"/checkins/{ci['id']}/close", headers=h)
        fake = FakeEmailSender()
        app.dependency_overrides[get_email_sender] = lambda: fake
        assert client.post("/admin/notify/weekly-plan", headers=_auth(ped.id)).status_code == 403
        dry = client.post(f"/admin/notify/weekly-plan?school_id={ids['school']}", headers=_auth(su.id)).json()
        assert dry["dry_run"] is True and dry["recipients"] == ["t@x.io"] and fake.sent == []
        real = client.post(f"/admin/notify/weekly-plan?school_id={ids['school']}&dry_run=false", headers=_auth(su.id)).json()
        assert real["sent"] == 1 and len(fake.sent) == 1 and fake.sent[0]["to"] == "t@x.io"
    finally:
        app.dependency_overrides.clear()


def test_org_level_it_admin_lists_and_edits_school_settings():
    client, ids, s = _setup()
    try:
        from src.models.org import Organization
        it = AppUser(email="it@x.io"); other_it = AppUser(email="it2@x.io"); s.add_all([it, other_it]); s.flush()
        other_org = Organization(name="Other"); s.add(other_org); s.flush()
        s.add_all([Membership(user_id=it.id, role=Role.IT_ADMIN, organization_id=ids["org"]),       # org seule, sans école
                   Membership(user_id=other_it.id, role=Role.IT_ADMIN, organization_id=other_org.id)])
        s.commit()
        lst = client.get("/admin/schools", headers=_auth(it.id)).json()
        assert [x["id"] for x in lst["schools"]] == [str(ids["school"])] and lst["schools"][0]["effective"]["hour"] == 7
        assert client.get("/admin/schools", headers=_auth(other_it.id)).json()["schools"] == []
        assert client.get("/admin/schools", headers=_auth(ids["teacher"])).status_code == 403
        url = f"/schools/{ids['school']}/settings"
        assert client.get(url, headers=_auth(it.id)).status_code == 200
        r = client.patch(url, json={"country": "AE", "plan_mail_hour": 6}, headers=_auth(it.id))
        assert r.status_code == 200 and r.json()["effective"] == {"weekday": 0, "hour": 6, "timezone": "Asia/Dubai"}
        assert client.patch(url, json={"plan_mail_hour": 9}, headers=_auth(other_it.id)).status_code == 403
        # effacer un réglage : retour au défaut du pays
        r = client.patch(url, json={"plan_mail_hour": None}, headers=_auth(it.id)).json()
        assert r["plan_mail_hour"] is None and r["effective"]["hour"] == 7
    finally:
        app.dependency_overrides.clear()
