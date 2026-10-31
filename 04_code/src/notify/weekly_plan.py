"""Message de début de semaine « votre plan est prêt » (refonte B6) — logique pure, cron-able.

Pas de scheduler en process (comme le rostering) : un cron HORAIRE appelle
`scripts/send_weekly_plan.py`, qui appelle `send_due`. Pour chaque école vivante dont le créneau
local (jour, heure) correspond à `now`, chaque enseignant qui a au moins une classe avec un plan
ACTIF récent reçoit UN e-mail listant ses classes. Un enseignant sans plan ne reçoit rien. Un
enseignant déjà notifié pour ce créneau (journal d'audit `notify.weekly_plan`, clé = jour local)
ne l'est pas deux fois : relancer dans l'heure est sans risque.

Réglage par école (Q5) : `School.plan_mail_weekday / plan_mail_hour / timezone`, défauts dérivés
du pays — dimanche pour l'Arabie saoudite, lundi ailleurs ; 7 h ; fuseau du pays, sinon UTC.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit import log_action
from src.models.audit import AuditLog
from src.models.base import PlanStatus, ensure_utc, utcnow
from src.models.measurement import School
from src.models.org import AppUser, Classroom, TeacherClassroom
from src.models.plan import PlanAction, WeeklyPlan
from src.notify.email import EmailSender
from src.notify.templates import weekly_plan_email

ACTION = "notify.weekly_plan"
DEFAULT_HOUR = 7
SUNDAY_START = frozenset({"SA"})                    # semaine qui commence le dimanche
COUNTRY_TZ = {"AE": "Asia/Dubai", "SA": "Asia/Riyadh", "QA": "Asia/Qatar", "KW": "Asia/Kuwait",
              "BH": "Asia/Bahrain", "OM": "Asia/Muscat", "JO": "Asia/Amman", "EG": "Africa/Cairo",
              "MA": "Africa/Casablanca", "FR": "Europe/Paris", "GB": "Europe/London"}
PLAN_MAX_AGE_DAYS = 14                               # un plan plus vieux n'est plus « prêt »


@dataclass(frozen=True)
class Schedule:
    weekday: int        # 0 = lundi … 6 = dimanche
    hour: int           # heure locale
    timezone: str       # IANA


def school_schedule(school: School) -> Schedule:
    country = (school.country or "").upper() or None
    weekday = school.plan_mail_weekday
    if weekday is None:
        weekday = 6 if country in SUNDAY_START else 0
    hour = DEFAULT_HOUR if school.plan_mail_hour is None else school.plan_mail_hour
    tz = school.timezone or COUNTRY_TZ.get(country or "", "UTC")
    try:
        ZoneInfo(tz)
    except Exception:
        tz = "UTC"
    return Schedule(weekday, hour, tz)


def local_now(now: datetime, tz: str) -> datetime:
    return ensure_utc(now).astimezone(ZoneInfo(tz))


def is_due(school: School, now: datetime) -> Tuple[bool, str]:
    """(créneau atteint ?, clé du créneau = date locale ISO)."""
    sch = school_schedule(school)
    loc = local_now(now, sch.timezone)
    return (loc.weekday() == sch.weekday and loc.hour == sch.hour), loc.date().isoformat()


def _already_sent(s: Session, teacher_id: uuid.UUID, week_key: str) -> bool:
    rows = s.execute(select(AuditLog).where(AuditLog.action == ACTION, AuditLog.user_id == teacher_id)
                     .order_by(AuditLog.created_at.desc()).limit(20)).scalars()
    return any((r.details or {}).get("week_key") == week_key for r in rows)


def teacher_classes_with_plan(s: Session, school: School, now: datetime) -> Dict[uuid.UUID, List[dict]]:
    """{teacher_user_id: [{name, classroom_id, n_actions, because_en, because_ar}]} — classes de
    l'école qui ont un plan actif généré il y a moins de PLAN_MAX_AGE_DAYS."""
    since = ensure_utc(now) - timedelta(days=PLAN_MAX_AGE_DAYS)
    plans = s.execute(select(WeeklyPlan).where(WeeklyPlan.school_id == school.id,
                                               WeeklyPlan.status == PlanStatus.ACTIVE)
                      .order_by(WeeklyPlan.generated_at.desc())).scalars().all()
    latest: Dict[uuid.UUID, WeeklyPlan] = {}
    for p in plans:
        if ensure_utc(p.generated_at) >= since and p.classroom_id not in latest:
            latest[p.classroom_id] = p
    if not latest:
        return {}
    classrooms = {c.id: c for c in s.execute(select(Classroom).where(Classroom.id.in_(list(latest)),
                                                                     Classroom.deleted_at.is_(None))).scalars()}
    out: Dict[uuid.UUID, List[dict]] = {}
    for cid, plan in latest.items():
        cls = classrooms.get(cid)
        if cls is None:
            continue
        actions = s.execute(select(PlanAction).where(PlanAction.plan_id == plan.id).order_by(PlanAction.rank)).scalars().all()
        if not actions:
            continue                                   # un plan vide n'est pas « prêt »
        entry = {"name": cls.name, "classroom_id": str(cls.id), "n_actions": len(actions),
                 "because_en": actions[0].because_en, "because_ar": actions[0].because_ar}
        for tid in s.execute(select(TeacherClassroom.user_id).where(TeacherClassroom.classroom_id == cid)).scalars():
            out.setdefault(tid, []).append(entry)
    return out


@dataclass
class SendReport:
    checked_schools: int = 0
    due_schools: List[str] = field(default_factory=list)
    sent: List[str] = field(default_factory=list)       # emails
    skipped_already: int = 0
    skipped_no_plan: int = 0

    def as_dict(self) -> dict:
        return {"checked_schools": self.checked_schools, "due_schools": self.due_schools,
                "sent": len(self.sent), "skipped_already": self.skipped_already,
                "skipped_no_plan": self.skipped_no_plan}


def send_for_school(s: Session, sender: EmailSender, school: School, *, now: datetime, web_base: str,
                    week_key: str, dry_run: bool = False, report: Optional[SendReport] = None) -> SendReport:
    report = report or SendReport()
    by_teacher = teacher_classes_with_plan(s, school, now)
    teacher_ids = set(s.execute(select(TeacherClassroom.user_id).join(Classroom, Classroom.id == TeacherClassroom.classroom_id)
                                .where(Classroom.school_id == school.id)).scalars())
    report.skipped_no_plan += len(teacher_ids - set(by_teacher))
    for tid, classes in sorted(by_teacher.items(), key=lambda kv: str(kv[0])):
        user = s.get(AppUser, tid)
        if user is None or not user.is_active or user.deleted_at is not None:
            continue
        if _already_sent(s, tid, week_key):
            report.skipped_already += 1
            continue
        subject, html, text = weekly_plan_email(sorted(classes, key=lambda c: c["name"]), web_base)
        if not dry_run:
            sender.send(to=user.email, subject=subject, html=html, text=text)
            log_action(s, action=ACTION, school_id=school.id, user_id=tid, resource_type="school",
                       resource_id=school.id, details={"week_key": week_key, "n_classes": len(classes)})
        report.sent.append(user.email)
    return report


def send_due(s: Session, sender: EmailSender, *, now: Optional[datetime] = None, web_base: str,
             dry_run: bool = False, force_school_id: Optional[uuid.UUID] = None) -> SendReport:
    """Envoie pour toutes les écoles dont le créneau est atteint. `force_school_id` : envoie
    pour cette école quelle que soit l'heure (bouton d'admin). Ne commit pas."""
    now = ensure_utc(now) or utcnow()
    report = SendReport()
    for school in s.execute(select(School).where(School.deleted_at.is_(None))).scalars():
        report.checked_schools += 1
        due, week_key = is_due(school, now)
        if force_school_id is not None:
            if school.id != force_school_id:
                continue
            due = True
        if not due:
            continue
        report.due_schools.append(str(school.id))
        send_for_school(s, sender, school, now=now, web_base=web_base, week_key=week_key,
                        dry_run=dry_run, report=report)
    return report


def settings_payload(school: School) -> dict:
    sch = school_schedule(school)
    return {"school_id": str(school.id), "country": school.country,
            "plan_mail_weekday": school.plan_mail_weekday, "plan_mail_hour": school.plan_mail_hour,
            "timezone": school.timezone,
            "effective": {"weekday": sch.weekday, "hour": sch.hour, "timezone": sch.timezone}}
