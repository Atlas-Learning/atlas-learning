"""Contenus d'emails (bilingue EN/AR). Aucune PII au-delà du lien personnel."""
from __future__ import annotations

from typing import Optional, Tuple


def parent_login_email(link: str) -> Tuple[str, str, str]:
    """(subject, html, text) — lien magique d'accès à l'espace de l'enfant."""
    subject = "Atlas Learning — access your child's space / الوصول إلى مساحة طفلك"
    html = (
        f'<div style="font-family:system-ui,sans-serif;line-height:1.5">'
        f"<p>You've been given access to follow your child's learning on Atlas Learning.</p>"
        f'<p><a href="{link}">Open my child\'s space →</a></p>'
        f'<p style="color:#888;font-size:13px">This link signs you in directly. '
        f"If it expires, request a new one from the parent page.</p>"
        f'<hr><p dir="rtl">تم منحك صلاحية متابعة تعلّم طفلك على Atlas Learning.</p>'
        f'<p dir="rtl"><a href="{link}">افتح مساحة طفلي ←</a></p>'
        f"</div>"
    )
    text = f"Access your child's space on Atlas Learning: {link}"
    return subject, html, text


def teacher_digest_email(class_name: str, digest: dict, link: Optional[str] = None) -> Tuple[str, str, str]:
    """(subject, html, text) — digest HEBDOMADAIRE enseignant (Mouvement 01).

    Cadence enseignant, jamais boucle élève : un résumé scannable de la semaine + LA priorité.
    `digest` = sortie de views_service.class_digest. Aucune PII élève (agrégats seulement).
    """
    top = digest.get("top_priority")
    emerging = digest.get("emerging_gaps", [])
    n_active = digest.get("n_active_students", 0)
    n_resp = digest.get("n_responses", 0)
    days = digest.get("window_days", 7)

    subject = f"Atlas — {class_name}: this week's focus / تركيز هذا الأسبوع"
    focus_en = (f"Priority: <b>{top['root_cause_label_en']}</b> "
                f"({top['student_count']} students)" if top else "No priority gap this week — nice.")
    focus_ar = (f"الأولوية: <b>{top['root_cause_label_ar']}</b> "
                f"({top['student_count']} طلاب)" if top else "لا ثغرة ذات أولوية هذا الأسبوع.")
    emerging_en = "".join(f"<li>{g['root_cause_label_en']} — {g['student_count']} students</li>"
                          for g in emerging) or "<li>None new this week.</li>"
    emerging_ar = "".join(f"<li>{g['root_cause_label_ar']} — {g['student_count']} طلاب</li>"
                          for g in emerging) or "<li>لا جديد هذا الأسبوع.</li>"
    cta = f'<p><a href="{link}">Open your class →</a></p>' if link else ""

    html = (
        f'<div style="font-family:system-ui,sans-serif;line-height:1.5">'
        f"<p>Your weekly summary for <b>{class_name}</b> "
        f"— {n_active} active students, {n_resp} answers in the last {days} days.</p>"
        f"<p>{focus_en}</p>"
        f"<p><b>Emerging gaps this week:</b></p><ul>{emerging_en}</ul>{cta}"
        f'<hr><div dir="rtl"><p>ملخّصك الأسبوعي لصفّ <b>{class_name}</b> '
        f"— {n_active} طالبًا نشطًا، {n_resp} إجابة خلال {days} أيام.</p>"
        f"<p>{focus_ar}</p><p><b>ثغرات ناشئة هذا الأسبوع:</b></p><ul>{emerging_ar}</ul></div>"
        f"</div>"
    )
    focus_txt = (f"Priority: {top['root_cause_label_en']} ({top['student_count']} students)"
                 if top else "No priority gap this week.")
    text = (f"Atlas weekly — {class_name}: {n_active} active, {n_resp} answers ({days}d). "
            f"{focus_txt}")
    return subject, html, text


def admin_login_email(link: str) -> Tuple[str, str, str]:
    """(subject, html, text) — lien magique d'accès admin Atlas (équipe éditeur, sans mot de passe)."""
    subject = "Atlas Learning — secure admin sign-in link"
    html = (
        f'<div style="font-family:system-ui,sans-serif;line-height:1.5">'
        f"<p>Use this single-use link to sign in to the Atlas Learning admin console.</p>"
        f'<p><a href="{link}">Sign in →</a></p>'
        f'<p style="color:#888;font-size:13px">This link expires shortly and signs in one '
        f"account only. If you didn't request it, ignore this email.</p></div>"
    )
    text = f"Sign in to Atlas Learning admin: {link}"
    return subject, html, text


def staff_login_email(link: str) -> Tuple[str, str, str]:
    """(subject, html, text) — lien magique d'accès pour un rôle d'école ou de groupe scolaire
    attribué hors roster (dept_lead, group_admin) quand aucun IdP ne le porte."""
    subject = "Atlas Learning — your sign-in link / رابط الدخول إلى أطلس"
    html = (
        f'<div style="font-family:system-ui,sans-serif;line-height:1.5">'
        f"<p>Use this single-use link to sign in to Atlas Learning.</p>"
        f'<p><a href="{link}">Sign in →</a></p>'
        f'<p style="color:#888;font-size:13px">This link expires shortly and signs in one '
        f"account only. If you didn't request it, ignore this email.</p>"
        f'<hr><p dir="rtl">استخدم هذا الرابط لمرة واحدة لتسجيل الدخول إلى أطلس للتعلّم.</p>'
        f'<p dir="rtl"><a href="{link}">تسجيل الدخول ←</a></p></div>'
    )
    text = f"Sign in to Atlas Learning: {link}"
    return subject, html, text


def linguist_login_email(link: str) -> Tuple[str, str, str]:
    """(subject, html, text) — lien magique d'accès à la console linguiste (staff Atlas)."""
    subject = "Atlas Learning — linguist review sign-in link / رابط دخول المراجع اللغوي"
    html = (
        f'<div style="font-family:system-ui,sans-serif;line-height:1.5">'
        f"<p>Use this single-use link to open the Atlas Learning Arabic review console.</p>"
        f'<p><a href="{link}">Open the review queue →</a></p>'
        f'<p style="color:#888;font-size:13px">This link expires shortly and signs in one '
        f"account only. If you didn't request it, ignore this email.</p>"
        f'<hr><p dir="rtl">استخدم هذا الرابط لمرة واحدة لفتح لوحة مراجعة المحتوى العربي.</p>'
        f'<p dir="rtl"><a href="{link}">افتح قائمة المراجعة ←</a></p></div>'
    )
    text = f"Sign in to Atlas Learning linguist console: {link}"
    return subject, html, text
