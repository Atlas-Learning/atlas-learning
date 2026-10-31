"""Tests du sender email (src/notify/email.py) — sélection par env + envoi SMTP OCI.

Vérifie la priorité SMTP > Postmark > Noop et que SmtpEmailSender pilote smtplib
correctement (STARTTLS TLS 1.2, login, message multipart) sans toucher au réseau.
"""
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.notify import email as email_mod
from src.notify.email import (
    NoopEmailSender, PostmarkSender, SmtpEmailSender, build_email_sender,
)

_EMAIL_ENV = ("EMAIL_FROM", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME",
              "SMTP_PASSWORD", "POSTMARK_TOKEN")


def _clear_env(monkeypatch):
    for k in _EMAIL_ENV:
        monkeypatch.delenv(k, raising=False)


# ---------- sélection par build_email_sender ----------

def test_selects_smtp_when_configured(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("EMAIL_FROM", "no-reply@mail.atlaslearning.ae")
    monkeypatch.setenv("SMTP_HOST", "smtp.email.me-abudhabi-1.oci.oraclecloud.com")
    monkeypatch.setenv("SMTP_USERNAME", "ocid1.user.smtp")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    sender = build_email_sender()
    assert isinstance(sender, SmtpEmailSender)
    assert sender._host.endswith("oraclecloud.com") and sender._port == 587


def test_smtp_takes_priority_over_postmark(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("EMAIL_FROM", "no-reply@mail.atlaslearning.ae")
    monkeypatch.setenv("SMTP_HOST", "smtp.oci")
    monkeypatch.setenv("SMTP_USERNAME", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setenv("POSTMARK_TOKEN", "tok")
    assert isinstance(build_email_sender(), SmtpEmailSender)


def test_falls_back_to_postmark_then_noop(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("EMAIL_FROM", "no-reply@mail.atlaslearning.ae")
    monkeypatch.setenv("POSTMARK_TOKEN", "tok")
    assert isinstance(build_email_sender(), PostmarkSender)
    monkeypatch.delenv("POSTMARK_TOKEN")
    assert isinstance(build_email_sender(), NoopEmailSender)      # plus rien de configuré


def test_smtp_incomplete_falls_back(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("EMAIL_FROM", "no-reply@mail.atlaslearning.ae")
    monkeypatch.setenv("SMTP_HOST", "smtp.oci")                   # ni user ni password
    assert isinstance(build_email_sender(), NoopEmailSender)


# ---------- envoi SMTP piloté correctement (smtplib mocké) ----------

class _FakeSMTP:
    calls = {}

    def __init__(self, host, port, timeout=None):
        _FakeSMTP.calls = {"host": host, "port": port, "timeout": timeout,
                           "starttls_ctx": None, "login": None, "sent": None}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        _FakeSMTP.calls["starttls_ctx"] = context

    def login(self, user, password):
        _FakeSMTP.calls["login"] = (user, password)

    def send_message(self, msg):
        _FakeSMTP.calls["sent"] = msg


def test_smtp_send_uses_starttls_tls12_login_and_multipart(monkeypatch):
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    sender = SmtpEmailSender("smtp.oci", 587, "user", "pass",
                             "no-reply@mail.atlaslearning.ae")
    sender.send(to="prof@ecole.ae", subject="Lien", html="<b>Bonjour</b>")

    c = _FakeSMTP.calls
    assert c["host"] == "smtp.oci" and c["port"] == 587
    assert isinstance(c["starttls_ctx"], ssl.SSLContext)
    assert c["starttls_ctx"].minimum_version == ssl.TLSVersion.TLSv1_2
    assert c["login"] == ("user", "pass")
    msg = c["sent"]
    assert msg["From"] == "no-reply@mail.atlaslearning.ae"
    assert msg["To"] == "prof@ecole.ae" and msg["Subject"] == "Lien"
    assert msg.is_multipart()
    types = {p.get_content_type() for p in msg.get_payload()}
    assert types == {"text/plain", "text/html"}                  # texte (fallback) + HTML


# ---------- refonte B6 : gabarit « votre plan est prêt » ----------

def test_weekly_plan_email_template_is_bilingual_and_links_each_class():
    from src.notify.templates import weekly_plan_email
    classes = [{"name": "4B", "classroom_id": "c1", "n_actions": 2, "because_en": "Because X is not mastered yet, 4 students are blocked on Y.",
                "because_ar": "لأن «س» غير مُتقَن بعد، يتعثّر 4 من الطلاب في «ص»."},
               {"name": "5A", "classroom_id": "c2", "n_actions": 1, "because_en": "", "because_ar": ""}]
    subject, html, text = weekly_plan_email(classes, "https://app.atlas")
    assert "ready" in subject and "جاهزة" in subject
    assert "https://app.atlas/teacher/c1/week" in html and "https://app.atlas/teacher/c2/week" in html
    assert "2 actions." in html and "1 action." in html and 'dir="rtl"' in html
    assert "4B: 2 action(s)" in text and "5A: 1 action(s)" in text
