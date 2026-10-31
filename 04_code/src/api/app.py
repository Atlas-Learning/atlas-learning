"""API de session adaptative (Epic 4, T4.3).

Endpoints : POST /sessions, GET /sessions/{id}/next-item, POST /sessions/{id}/responses.
Sert aussi l'UI élève bilingue (statique) sous /ui.
Aucune donnée élève envoyée à un service externe.
"""
from __future__ import annotations

import os
import secrets
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.session_service import (
    AlreadyAnswered,
    SessionCompleted,
    grade_answer,
    next_item,
    start_session,
    submit_response,
)
from src.api.views_service import (
    class_matrix,
    class_digest,
    class_gaps,
    curriculum_coverage,
    list_students,
    referentiel_graph,
    remediation_preview,
    school_overview,
    student_profile,
    student_trajectory,
    tutor_explanation,
)
from src.audit import log_action
from src.db import active, make_engine
from src.items import review
from src.items import templates as item_templates
from src.items import review_queue
from src.api import checkin_service
from src.api import plan_service
from src.api import proof_service
from src.notify import weekly_plan as weekly_plan_mail
from zoneinfo import ZoneInfo
from src.api import lesson_service
from src.models.lesson import MiniLesson
from src.models.plan import PlanAction, WeeklyPlan
from datetime import date
from src.models.base import CheckInKind, CheckInStatus, ProofOutcome
from src.models.checkin import CheckIn
from src.items.arabic import (
    ALLAM_MODEL,
    TranslationError,
    ar_coverage,
    ar_math_preserved,
    translate_to_arabic,
)
from src.models.base import CurriculumView, ItemFlagReason, ItemFlagStatus, ItemStatus, Role
from src.models.competency import Competency
from src.models.item import Item, ItemFlag
from src.models.measurement import School, Student
from src.models.audit import AuditLog
from src.models.org import (
    AppUser, Classroom, Membership, Organization, ParentStudent, RosterRun, StudentClassroom,
    TenantIntegration,
)
from src.models.session import AssessmentSession
from src.rbac.auth import make_single_use_token, make_token, parse_token
from src.rbac.single_use import (
    TokenAlreadyUsedError,
    consume_single_use_token,
    peek_single_use_token,
)
from src.compliance import service as compliance
from src.licensing import service as licensing
from src.notify.email import build_email_sender
from src.notify.templates import (
    admin_login_email, linguist_login_email, parent_login_email, staff_login_email,
)
from src.onboarding.service import onboard_tenant
from src.restitution.proof import proof_surfaces
from src.rbac import oidc
from src.rostering import google as gdir
from src.rostering import oneroster, oneroster_csv, wonde
from src.rostering.sync import sync_directory
from src.rbac.authz import (
    UserContext,
    build_user_context,
    can_access_classroom,
    can_access_school,
    can_access_student,
    can_flag_item,
    can_grant_dept_lead,
    can_run_checkin,
    can_manage_roles,
    can_manage_school,
    can_review_arabic,
    can_review_items,
    is_super,
)
from src.rbac import grants

_engine = make_engine()


def get_db():
    s = Session(bind=_engine)
    try:
        yield s
    finally:
        s.close()


app = FastAPI(title="Atlas Learning — Session API")

# CORS — autorise le front Next.js (dev) à appeler l'API. Origines restreintes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- auth ----------

def get_context(authorization: str = Header(None), s: Session = Depends(get_db)) -> UserContext:
    """Résout le UserContext depuis le jeton Bearer (RBAC vérifié côté serveur)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="jeton manquant")
    try:
        user_id = parse_token(authorization[len("Bearer "):])
    except ValueError:
        raise HTTPException(status_code=401, detail="jeton invalide")
    # Le jeton de session (TTL 1 h) peut survivre à l'offboarding : on re-vérifie l'état
    # RÉEL du compte à CHAQUE requête — soft-deleted ou désactivé (roster sync, départ,
    # droit à l'oubli) → 401 immédiat, sans attendre l'expiration (revue 2026-07-08).
    # Les jetons de purpose spécial (parent_login, admin_login, oidc_state…) ne passent
    # jamais ici : parse_token (purpose="session") les rejette déjà, et leurs endpoints
    # de login font ce même contrôle AVANT d'émettre le jeton de session.
    user = s.get(AppUser, uuid.UUID(user_id))
    if user is None or user.deleted_at is not None or not user.is_active:
        raise HTTPException(status_code=401, detail="compte inactif ou supprimé")
    return build_user_context(s, user.id)


# ---------- authentification = SSO uniquement ----------
#
# Plus de `/login` mot de passe ni de MFA TOTP applicative : l'identité passe par l'IdP
# (OIDC, plus bas). Deux exceptions SANS mot de passe, par liens magiques signés HMAC,
# À USAGE UNIQUE (jti consommé atomiquement, cf. src/rbac/single_use.py) :
#   - parents (hors Workspace scolaire) ;
#   - super-admin Atlas (équipe éditeur), qui ne peut pas dépendre de l'IdP d'un client.
#
# Pour le DEV / la démo / les tests e2e (sans IdP externe), un simulateur SSO permet
# d'ouvrir une session pour un utilisateur EXISTANT. Il est FERMÉ par défaut et en prod.

def _dev_login_enabled() -> bool:
    is_prod = os.environ.get("ATLAS_ENV", "dev").lower() in ("prod", "production")
    return (not is_prod) and os.environ.get("OIDC_DEV_LOGIN") == "1"


class DevLoginIn(BaseModel):
    email: str


@app.post("/dev/login")
def dev_login(body: DevLoginIn, s: Session = Depends(get_db)):
    """Simulateur SSO (DEV uniquement) : ouvre une session pour un utilisateur existant.

    Remplace l'ancien login mot de passe dans la démo / les tests e2e. Refusé en prod
    et désactivé tant que `OIDC_DEV_LOGIN=1` n'est pas posé (défense en profondeur).
    """
    if not _dev_login_enabled():
        raise HTTPException(status_code=404, detail="indisponible")
    user = s.execute(
        select(AppUser).where(AppUser.email == body.email.strip().lower(),
                              AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="utilisateur inconnu")
    log_action(s, action="auth.dev_login", user_id=user.id)
    s.commit()
    return {"token": make_token(str(user.id)), "user_id": str(user.id)}


# ---------- SSO / OIDC (fallback compte direct conservé) ----------

def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def _oidc_redirect_uri(provider_key: str) -> str:
    # Tout transite par l'origine du front (proxy /api → FastAPI) : same-origin, un seul host.
    base = os.environ.get("OIDC_REDIRECT_BASE", _web_base()).rstrip("/")
    return f"{base}/api/oauth/{provider_key}/callback"


@app.get("/auth/providers")
def auth_providers():
    """Providers SSO activés — pilote l'affichage des boutons côté front."""
    return {"providers": oidc.enabled_providers()}


@app.get("/oauth/{provider_key}/start")
def oauth_start(provider_key: str):
    """Démarre le flux OIDC : redirige vers l'IdP avec un `state` signé (anti-CSRF)."""
    p = oidc.get_provider(provider_key)
    if p is None:
        raise HTTPException(status_code=404, detail="fournisseur SSO non configuré")
    # state = jeton signé HMAC (purpose cloisonné) ; pas de stockage serveur nécessaire.
    # Il PORTE le nonce (anti-rejeu du ID token) : signé par nous, donc non forgeable et
    # revérifiable au callback sans état serveur.
    nonce = secrets.token_urlsafe(16)
    state = make_token(f"{provider_key}|{nonce}", purpose="oidc_state", ttl_s=600)
    url = oidc.authorize_url(p, _oidc_redirect_uri(provider_key), state, nonce=nonce)
    return RedirectResponse(url, status_code=302)


@app.get("/oauth/{provider_key}/callback")
def oauth_callback(provider_key: str, code: Optional[str] = None, state: Optional[str] = None,
                   error: Optional[str] = None, s: Session = Depends(get_db)):
    """Retour de l'IdP : valide le state, échange le code, résout l'utilisateur, ouvre la session."""
    web = _web_base()
    if error:
        return RedirectResponse(f"{web}/login?sso_error={error}", status_code=302)

    p = oidc.get_provider(provider_key)
    if p is None:
        raise HTTPException(status_code=404, detail="fournisseur SSO non configuré")

    # 1) state : signé par nous, du bon purpose, lié au bon provider → anti-CSRF/forge.
    #    Le state porte le nonce attendu dans le ID token.
    try:
        marker = parse_token(state or "", purpose="oidc_state")
    except ValueError:
        raise HTTPException(status_code=400, detail="state invalide")
    if not marker.startswith(f"{provider_key}|"):
        raise HTTPException(status_code=400, detail="state/provider incohérent")
    nonce = marker.split("|", 1)[1]
    if not code:
        raise HTTPException(status_code=400, detail="code manquant")

    # 2) échange code → tokens, puis résolution d'identité selon le provider :
    #    - id_token (Entra/Google/IdP conformes) : validation crypto stricte (JWKS + nonce) ;
    #    - userinfo (UAE PASS) : identité via userinfo over TLS (pas de id_token signé).
    try:
        tokens = oidc.exchange_code(p, code, _oidc_redirect_uri(provider_key))
        claims = oidc.resolve_identity(p, tokens, nonce=nonce)
    except oidc.IdTokenError:
        return RedirectResponse(f"{web}/login?sso_error=token", status_code=302)
    except Exception:
        return RedirectResponse(f"{web}/login?sso_error=exchange", status_code=302)
    email = oidc.extract_email(claims)
    if not email:
        return RedirectResponse(f"{web}/login?sso_error=email", status_code=302)

    # 3) l'utilisateur doit déjà exister (pas d'auto-provisioning d'un email inconnu).
    user = s.execute(
        select(AppUser).where(AppUser.email == email, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return RedirectResponse(f"{web}/login?sso_error=unknown", status_code=302)

    # MFA porté par l'IdP côté SSO : on ouvre directement la session applicative.
    log_action(s, action="auth.sso_login", user_id=user.id)
    s.commit()
    session_token = make_token(str(user.id))
    # token dans le fragment (#) : jamais envoyé au serveur ni journalisé.
    return RedirectResponse(f"{web}/oauth/callback#token={session_token}", status_code=302)


# ---------- onboarding self-service (création de tenant par l'IT admin) ----------

# Scopes onboarding = OIDC + lecture annuaire (pour vérifier le statut admin Workspace).
_ONBOARDING_SCOPES = ("openid email profile "
                      "https://www.googleapis.com/auth/admin.directory.user.readonly")


def _onboarding_redirect_uri() -> str:
    base = os.environ.get("OIDC_REDIRECT_BASE", _web_base()).rstrip("/")
    return f"{base}/api/onboarding/google/callback"


@app.get("/onboarding/google/start")
def onboarding_start():
    """L'IT admin lance la création de son établissement via Sign-in Google (scopes admin)."""
    p = oidc.get_provider("google")
    if p is None:
        raise HTTPException(status_code=404, detail="SSO Google non configuré")
    nonce = secrets.token_urlsafe(16)
    state = make_token(f"google|{nonce}", purpose="onboarding", ttl_s=600)
    url = oidc.authorize_url(p, _onboarding_redirect_uri(), state,
                             scopes=_ONBOARDING_SCOPES, nonce=nonce)
    return RedirectResponse(url, status_code=302)


@app.get("/onboarding/google/callback")
def onboarding_callback(code: Optional[str] = None, state: Optional[str] = None,
                        error: Optional[str] = None, s: Session = Depends(get_db)):
    """Retour Google : exige un compte Workspace ADMIN, puis crée/retrouve le tenant."""
    web = _web_base()
    if error:
        return RedirectResponse(f"{web}/login?onboarding_error={error}", status_code=302)
    p = oidc.get_provider("google")
    if p is None:
        raise HTTPException(status_code=404, detail="SSO Google non configuré")
    try:
        marker = parse_token(state or "", purpose="onboarding")
    except ValueError:
        raise HTTPException(status_code=400, detail="state invalide")
    nonce = marker.split("|", 1)[1] if "|" in marker else None
    if not code:
        raise HTTPException(status_code=400, detail="code manquant")

    try:
        tokens = oidc.exchange_code(p, code, _onboarding_redirect_uri())
        claims = oidc.validate_id_token(p, tokens["id_token"], nonce=nonce)
        me = gdir.get_user_self(tokens["access_token"])  # statut admin réel (Directory API)
    except oidc.IdTokenError:
        return RedirectResponse(f"{web}/login?onboarding_error=token", status_code=302)
    except Exception:
        return RedirectResponse(f"{web}/login?onboarding_error=exchange", status_code=302)

    email = oidc.extract_email(claims)
    hd = claims.get("hd")  # domaine Workspace (claim signé ; absent pour un compte perso)
    if not email or not hd:
        return RedirectResponse(f"{web}/login?onboarding_error=workspace", status_code=302)
    if not me.get("isAdmin"):
        # hd prouve l'appartenance, PAS l'admin → on refuse tout non-admin (anti-escalade).
        return RedirectResponse(f"{web}/login?onboarding_error=not_admin", status_code=302)

    default_seats = os.environ.get("DEFAULT_SEATS")
    res = onboard_tenant(s, email=email, domain=hd, customer_id=me.get("customerId"),
                         seats=int(default_seats) if default_seats else None)
    log_action(s, action="onboarding.tenant_created" if res.created else "onboarding.admin_login",
               user_id=res.user.id)
    s.commit()
    token = make_token(str(res.user.id))
    return RedirectResponse(f"{web}/oauth/callback#token={token}", status_code=302)


# ---------- console IT admin : rostering (statut, sync, historique) ----------

# Connecteurs de rostering STANDARDS : chacun produit le même `DirectorySnapshot`, le
# moteur de sync ne connaît aucune source. `TenantIntegration.provider` choisit l'adapter.
_DIRECTORY_BUILDERS = {
    "google": lambda integ: gdir.build_from_env(integ.admin_email, integ.customer_id),
    "oneroster": lambda integ: oneroster.build_from_env(integ),
    "oneroster_csv": lambda integ: oneroster_csv.build_from_env(integ),
    "wonde": lambda integ: wonde.build_from_env(integ),
}


def directory_for(integ: TenantIntegration):
    """Construit l'adapter d'annuaire correspondant au provider du tenant."""
    builder = _DIRECTORY_BUILDERS.get(integ.provider)
    if builder is None:
        raise RuntimeError(f"provider de rostering inconnu : {integ.provider!r}")
    return builder(integ)


def get_directory_factory() -> Callable:
    """Injectable (tests : FakeDirectory ; prod : Google / OneRoster / Wonde selon le tenant)."""
    return directory_for


def _require_it_admin_org(ctx: UserContext, s: Session) -> Organization:
    if not ctx.has(Role.IT_ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="rôle IT admin requis")
    if len(ctx.org_ids) != 1:
        raise HTTPException(status_code=400, detail="organisation non résolue")
    org = s.get(Organization, next(iter(ctx.org_ids)))
    if org is None or org.deleted_at is not None:
        raise HTTPException(status_code=404, detail="organisation introuvable")
    return org


def _integration_of(s: Session, org: Organization) -> Optional[TenantIntegration]:
    return s.execute(
        select(TenantIntegration).where(TenantIntegration.organization_id == org.id)
    ).scalar_one_or_none()


def _run_payload(run: RosterRun) -> dict:
    return {
        "id": str(run.id), "status": run.status, "summary": run.summary,
        "created": run.created_count, "updated": run.updated_count,
        "deactivated": run.deactivated_count, "errors": run.error_count,
        "pending_deactivations": run.pending_deactivations,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@app.get("/admin/integration")
def admin_integration(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Statut de l'intégration d'annuaire + occupation des sièges (console IT)."""
    org = _require_it_admin_org(ctx, s)
    integ = _integration_of(s, org)
    usage = licensing.seat_usage(s, org)
    return {
        "organization": {"id": str(org.id), "name": org.name, "domain": org.domain,
                         "seats": usage["seats"], "seats_used": usage["used"],
                         "over_capacity": usage["over"]},
        "integration": None if integ is None else {
            "provider": integ.provider, "status": integ.status,
            "admin_email": integ.admin_email,
            "last_sync_at": integ.last_sync_at.isoformat() if integ.last_sync_at else None,
            "last_error": integ.last_error,
        },
    }


class IntegrationIn(BaseModel):
    provider: str                       # google | oneroster | oneroster_csv | wonde
    admin_email: Optional[str] = None   # google : admin à impersonner
    customer_id: Optional[str] = None   # google customer / id école Wonde


@app.post("/admin/integration")
def admin_set_integration(body: IntegrationIn,
                          ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Configure le connecteur de rostering du tenant (IT admin) parmi les standards supportés."""
    org = _require_it_admin_org(ctx, s)
    if body.provider not in _DIRECTORY_BUILDERS:
        raise HTTPException(status_code=400,
                            detail=f"provider non supporté (attendu : {sorted(_DIRECTORY_BUILDERS)})")
    integ = _integration_of(s, org)
    if integ is None:
        integ = TenantIntegration(organization_id=org.id)
        s.add(integ)
    integ.provider = body.provider
    integ.admin_email = body.admin_email
    integ.customer_id = body.customer_id
    integ.status = "pending"      # (re)connexion : la 1re sync repassera en connected
    integ.last_error = None
    log_action(s, action="rostering.configure", user_id=ctx.user_id,
               resource_type="organization", resource_id=org.id)
    s.commit()
    return {"provider": integ.provider, "status": integ.status}


def _require_curriculum_admin_org(ctx: UserContext, s: Session,
                                  organization_id: Optional[uuid.UUID] = None) -> Organization:
    """Console curriculum (B3) : réglage d'AFFICHAGE pédagogique — ouvert au ped admin
    en plus de l'IT admin (même résolution de tenant que _require_it_admin_org).

    Le ped admin est scopé par `school_id` (jamais `organization_id` — aucun chemin de
    provisioning ne le pose, cf. provision_demo.py/provision_prod_tenant.py/rostering) :
    on résout donc l'org via ses écoles quand `org_ids` est vide, sinon ce rôle ne peut
    jamais atteindre cette console malgré le docstring qui le promet.
    """
    if not ctx.has(Role.IT_ADMIN, Role.PED_ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="rôle admin requis")
    # Super admin Atlas : il n'a pas de membership d'organisation → il NOMME le tenant visé.
    if organization_id is not None and is_super(ctx):
        org = s.get(Organization, organization_id)
        if org is None or org.deleted_at is not None:
            raise HTTPException(status_code=404, detail="organisation introuvable")
        return org
    org_ids = set(ctx.org_ids)
    if not org_ids and ctx.school_ids:
        schools = s.execute(select(School).where(School.id.in_(ctx.school_ids))).scalars().all()
        org_ids = {sch.organization_id for sch in schools if sch.organization_id}
    if len(org_ids) != 1:
        raise HTTPException(status_code=400, detail="organisation non résolue")
    org = s.get(Organization, next(iter(org_ids)))
    if org is None or org.deleted_at is not None:
        raise HTTPException(status_code=404, detail="organisation introuvable")
    return org


@app.get("/admin/curriculum")
def admin_curriculum(organization_id: Optional[uuid.UUID] = None,
                     ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Vue curriculaire du tenant (B3) : framework affiché + frameworks disponibles.
    `organization_id` : requis seulement pour un super admin (qui nomme le tenant)."""
    org = _require_curriculum_admin_org(ctx, s, organization_id)
    return {
        "organization": {"id": str(org.id), "name": org.name},
        "curriculum_view": org.curriculum_view.value,
        "available_frameworks": [v.value for v in CurriculumView],
    }


class CurriculumViewIn(BaseModel):
    curriculum_view: str    # validé contre l'enum ci-dessous (400 explicite, pas 422)


@app.post("/admin/curriculum")
def admin_set_curriculum(body: CurriculumViewIn, organization_id: Optional[uuid.UUID] = None,
                         ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Bascule la vue curriculaire du tenant (B3) — un seul framework actif en v1 (D-B3).

    Refonte (Q14, décision 2026-10-31) : le choix du curriculum est une opération Atlas —
    réservée au super admin. Les admins de l'école le LISENT (GET) sans le modifier."""
    if not is_super(ctx):
        raise HTTPException(status_code=403, detail="réservé au super admin Atlas")
    org = _require_curriculum_admin_org(ctx, s, organization_id)
    try:
        view = CurriculumView(body.curriculum_view)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"curriculum_view non supporté (attendu : {[v.value for v in CurriculumView]})",
        )
    org.curriculum_view = view
    log_action(s, action="curriculum.set_view", user_id=ctx.user_id,
               resource_type="organization", resource_id=org.id,
               details={"curriculum_view": view.value})
    s.commit()
    return {"curriculum_view": org.curriculum_view.value}


@app.post("/admin/rostering/sync")
def admin_rostering_sync(force: bool = False, ctx: UserContext = Depends(get_context),
                         s: Session = Depends(get_db),
                         factory: Callable = Depends(get_directory_factory)):
    """Déclenche une sync (IT admin). `force=true` = approuver des désactivations massives bloquées."""
    org = _require_it_admin_org(ctx, s)
    integ = _integration_of(s, org)
    if integ is None:
        raise HTTPException(status_code=400, detail="intégration non configurée")
    try:
        directory = factory(integ)
        run = sync_directory(s, org, directory.snapshot(), force=force)
        if run.status != "blocked":
            licensing.flag_overage(s, org)  # dépassement de licence → statut/alerte visible
        log_action(s, action="rostering.sync_forced" if force else "rostering.sync",
                   user_id=ctx.user_id)
        s.commit()
    except Exception as exc:  # adapter indisponible / erreur Google → on trace et on remonte
        integ.status, integ.last_error = "error", str(exc)[:500]
        s.commit()
        raise HTTPException(status_code=502, detail="échec de la synchronisation")
    return _run_payload(run)


@app.get("/admin/rostering/runs")
def admin_rostering_runs(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Historique des synchronisations (audit, console IT)."""
    org = _require_it_admin_org(ctx, s)
    runs = s.execute(
        select(RosterRun).where(RosterRun.organization_id == org.id)
        .order_by(RosterRun.started_at.desc()).limit(20)
    ).scalars().all()
    return {"runs": [_run_payload(r) for r in runs]}


class SeatsIn(BaseModel):
    seats: Optional[int] = None  # None = illimité (essai)


@app.post("/admin/organizations/{org_id}/seats")
def admin_set_seats(org_id: uuid.UUID, body: SeatsIn,
                    ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Pose le quota de sièges contractuel — RÉSERVÉ au vendeur (SUPER_ADMIN)."""
    if Role.SUPER_ADMIN not in ctx.roles:
        raise HTTPException(status_code=403, detail="réservé au vendeur")
    org = s.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise HTTPException(status_code=404, detail="organisation introuvable")
    try:
        licensing.set_seats(s, org, body.seats)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    licensing.flag_overage(s, org)  # recalcule l'état si le nouveau quota change la donne
    log_action(s, action="licensing.set_seats", resource_type="organization", resource_id=org_id)
    s.commit()
    return licensing.seat_usage(s, org)


# ---------- conformité PDPL : audit, export, droit à l'oubli (IT admin) ----------

@app.get("/admin/audit")
def admin_audit(limit: int = 100, action: Optional[str] = None,
                ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Vue du journal d'audit du tenant (la DSI veut voir les accès/actions)."""
    org = _require_it_admin_org(ctx, s)
    return {"entries": compliance.audit_entries(s, org, limit=min(max(limit, 1), 500),
                                                action=action)}


@app.get("/admin/export")
def admin_export(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Export structuré des données du tenant (portabilité PDPL)."""
    org = _require_it_admin_org(ctx, s)
    log_action(s, action="compliance.export", user_id=ctx.user_id)
    s.commit()
    return compliance.export_tenant(s, org)


@app.post("/admin/students/{student_id}/erase")
def admin_erase_student(student_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                        s: Session = Depends(get_db)):
    """Droit à l'oubli d'un élève (suppression DURE, isolation tenant vérifiée)."""
    org = _require_it_admin_org(ctx, s)
    st = compliance.student_in_org(s, org, student_id)
    if st is None:
        raise HTTPException(status_code=404, detail="élève introuvable dans ce tenant")
    res = compliance.erase_student(s, st)
    s.commit()
    return res


class TenantEraseIn(BaseModel):
    confirm_domain: str  # garde-fou : doit égaler le domaine du tenant


@app.post("/admin/tenant/erase")
def admin_erase_tenant(body: TenantEraseIn, ctx: UserContext = Depends(get_context),
                       s: Session = Depends(get_db)):
    """Purge complète du tenant (fin de contrat) — IRRÉVERSIBLE. Confirmé par le domaine."""
    org = _require_it_admin_org(ctx, s)
    if not org.domain or body.confirm_domain.strip().lower() != org.domain.lower():
        raise HTTPException(status_code=400, detail="confirmation du domaine invalide")
    res = compliance.erase_tenant(s, org)
    s.commit()
    return res


# ---------- accès parent : lien magique (sans mot de passe, hors Workspace) ----------

def get_email_sender():
    """Injectable (tests : FakeEmailSender ; prod : provider via env)."""
    return build_email_sender()


def get_llm_client():
    """Client LLM arabe injectable (tests : FakeLLMClient ; prod : Groq/ALLaM via env).

    Défaut = modèle arabe natif ALLaM, servi via Groq (cf. items/arabic.py).
    """
    from src.llm.client import GroqClient
    return GroqClient(model=ALLAM_MODEL)


_PARENT_LINK_TTL = 14 * 24 * 3600  # 14 jours pour cliquer UNE fois (single-use) ; ensuite le parent redemande un lien


def _send_parent_link(sender, user: AppUser) -> None:
    # Lien magique SINGLE-USE : le jti est consommé au premier login (anti-rejeu).
    token = make_single_use_token(str(user.id), purpose="parent_login", ttl_s=_PARENT_LINK_TTL)
    link = f"{_web_base()}/api/parent/login?token={token}"
    subject, html, text = parent_login_email(link)
    sender.send(to=user.email, subject=subject, html=html, text=text)


class ParentRequestIn(BaseModel):
    email: str


@app.post("/parent/request-link")
def parent_request_link(body: ParentRequestIn, s: Session = Depends(get_db),
                        sender=Depends(get_email_sender)):
    """Auto-demande d'un lien magique. Réponse constante → pas d'énumération de comptes."""
    user = s.execute(
        select(AppUser).where(AppUser.email == body.email.strip().lower(),
                              AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is not None and user.is_active:
        ctx = build_user_context(s, user.id)
        if Role.PARENT in ctx.roles:
            _send_parent_link(sender, user)
            log_action(s, action="parent.request_link", user_id=user.id)
            s.commit()
    return {"ok": True}


class MagicLinkConfirmIn(BaseModel):
    token: str


@app.get("/parent/login")
def parent_login(token: str, s: Session = Depends(get_db)):
    """Valide le lien magique SANS le consommer → étape de confirmation humaine.

    Anti-préchargement (revue adversariale 2026-07-07) : les scanners d'emails
    (Outlook SafeLinks, prévisualisation) suivent les liens en GET — si le GET
    consommait le jti, 100 % des liens de ces tenants seraient brûlés AVANT le clic
    du parent. Ce GET est donc IDEMPOTENT et sans effet de bord (lecture seule) ;
    la consommation atomique du jti se fait au POST /parent/login/confirm, déclenché
    par le bouton « Continuer » de la page de confirmation (action humaine).
    """
    web = _web_base()
    try:
        uid = peek_single_use_token(s, token, purpose="parent_login")
    except TokenAlreadyUsedError:
        # Lien déjà consommé (rejeu) : refus vers l'UI — cet endpoint s'ouvre dans un
        # NAVIGATEUR depuis l'email, un 401 JSON brut laisserait le parent (persona la
        # moins technique) sans moyen de redemander un lien. Même redirection qu'avant.
        return RedirectResponse(f"{web}/parent?error=used", status_code=302)
    except ValueError:
        return RedirectResponse(f"{web}/parent?error=invalid", status_code=302)
    user = s.get(AppUser, uuid.UUID(uid))
    if user is None or not user.is_active or user.deleted_at is not None:
        return RedirectResponse(f"{web}/parent?error=invalid", status_code=302)
    # Jeton de LIEN passé dans le fragment (#…) : jamais envoyé aux serveurs ni journalisé.
    return RedirectResponse(f"{web}/parent/confirm#token={token}", status_code=302)


@app.post("/parent/login/confirm")
def parent_login_confirm(body: MagicLinkConfirmIn, s: Session = Depends(get_db)):
    """CONSOMME le lien magique (single-use, atomique) → jeton de session parent.

    Déclenché par le bouton « Continuer » (action humaine — les scanners d'emails ne
    POSTent pas). `detail` = code machine (`used` / `invalid`) : le front le mappe sur
    la redirection UI (`/parent?error=…`), cohérente avec le GET.
    """
    try:
        uid = consume_single_use_token(s, body.token, purpose="parent_login")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=401, detail="used")
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid")
    # Le jeton est déjà brûlé (commit dans consume) : même si les contrôles suivants
    # échouent, un rejeu ne pourra jamais réussir.
    user = s.get(AppUser, uuid.UUID(uid))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="invalid")
    log_action(s, action="parent.login", user_id=user.id)
    s.commit()
    # La racine route le parent → /parent/{enfant}.
    return {"token": make_token(str(user.id))}


# ---------- accès par lien magique : super-admin Atlas, et rôles attribués hors roster ----------
#
# Les SUPER_ADMIN ne peuvent pas dépendre de l'IdP d'un CLIENT. Plutôt qu'un mot de passe
# (interdit par la revue DSI), ils se connectent par un lien magique signé envoyé à leur
# email d'éditeur — court-vécu, à usage unique, cloisonné (purpose=admin_login).
#
# Refonte A1 (Q13) : les rôles `dept_lead` et `group_admin` sont attribués hors roster
# (src/rbac/grants.py). Quand aucun IdP ne les porte (école ou groupe « sans SSO »), ils
# ouvrent leur session par le même lien magique. Rôles autorisés : grants.MAGIC_LINK_ROLES.
# Avec SSO, ces mêmes comptes passent par /oauth/{provider} comme tout le monde.

_ADMIN_LINK_TTL = 30 * 60  # 30 min : fenêtre courte


def _magic_link_role(ctx: UserContext) -> Optional[Role]:
    """Rôle qui ouvre droit au lien magique (super_admin prioritaire pour le wording), ou None."""
    if Role.SUPER_ADMIN in ctx.roles:
        return Role.SUPER_ADMIN
    for r in (Role.CONTENT_REVIEWER, Role.GROUP_ADMIN, Role.DEPT_LEAD):
        if r in ctx.roles and r in grants.MAGIC_LINK_ROLES:
            return r
    return None


@app.post("/admin/request-link")
def admin_request_link(body: ParentRequestIn, s: Session = Depends(get_db),
                       sender=Depends(get_email_sender)):
    """Auto-demande d'un lien magique. Réservé aux rôles de `grants.MAGIC_LINK_ROLES`
    (super_admin, group_admin, dept_lead).

    Réponse constante (anti-énumération) : on ne révèle jamais si l'email y a droit.
    """
    user = s.execute(
        select(AppUser).where(AppUser.email == body.email.strip().lower(),
                              AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is not None and user.is_active:
        role = _magic_link_role(build_user_context(s, user.id))
        if role is not None:
            token = make_single_use_token(str(user.id), purpose="admin_login",
                                          ttl_s=_ADMIN_LINK_TTL)
            link = f"{_web_base()}/api/admin/login?token={token}"
            template = admin_login_email if role == Role.SUPER_ADMIN else staff_login_email
            subject, html, text = template(link)
            sender.send(to=user.email, subject=subject, html=html, text=text)
            log_action(s, action="admin.request_link", user_id=user.id,
                       details={"role": role.value})
            s.commit()
    return {"ok": True}


@app.get("/admin/login")
def admin_login(token: str, s: Session = Depends(get_db)):
    """Valide le lien magique éditeur SANS le consommer → confirmation humaine.

    Même patron anti-préchargement que /parent/login : GET idempotent (lecture seule),
    consommation atomique au POST /admin/login/confirm (bouton « Continuer »).
    """
    web = _web_base()
    try:
        uid = peek_single_use_token(s, token, purpose="admin_login")
    except TokenAlreadyUsedError:
        # Rejeu → UI (même logique que /parent/login : endpoint navigateur, pas d'API).
        return RedirectResponse(f"{web}/login?admin_error=used", status_code=302)
    except ValueError:
        return RedirectResponse(f"{web}/login?admin_error=invalid", status_code=302)
    user = s.get(AppUser, uuid.UUID(uid))
    if user is None or not user.is_active or user.deleted_at is not None:
        return RedirectResponse(f"{web}/login?admin_error=invalid", status_code=302)
    # Contrôle du rôle en LECTURE (le POST re-vérifie au moment de la connexion).
    if _magic_link_role(build_user_context(s, user.id)) is None:
        return RedirectResponse(f"{web}/login?admin_error=forbidden", status_code=302)
    # Jeton de LIEN dans le fragment (#…) : jamais envoyé aux serveurs ni journalisé.
    return RedirectResponse(f"{web}/login/confirm#token={token}", status_code=302)


@app.post("/admin/login/confirm")
def admin_login_confirm(body: MagicLinkConfirmIn, s: Session = Depends(get_db)):
    """CONSOMME le lien magique éditeur (single-use) → jeton de session SUPER_ADMIN."""
    try:
        uid = consume_single_use_token(s, body.token, purpose="admin_login")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=401, detail="used")
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid")
    # Jeton brûlé dès la consommation : les contrôles suivants ne le « rendent » pas.
    user = s.get(AppUser, uuid.UUID(uid))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="invalid")
    # Re-vérifie le rôle au moment de la connexion (révocation possible entre-temps).
    role = _magic_link_role(build_user_context(s, user.id))
    if role is None:
        raise HTTPException(status_code=403, detail="forbidden")
    log_action(s, action="admin.login", user_id=user.id, details={"role": role.value})
    s.commit()
    return {"token": make_token(str(user.id))}


# ---------- accès linguiste Atlas (staff éditeur global) : lien magique interne ----------
#
# Le linguiste relit/valide l'arabe de la banque d'items — contenu Atlas GLOBAL, pas
# tenant-scopé. Comme le super-admin, il ne peut pas dépendre de l'IdP d'un CLIENT :
# même mécanisme de lien magique signé HMAC, single-use, cloisonné (purpose=linguist_login),
# anti-préchargement (GET valide sans consommer, POST consomme). Le rôle est revérifié.

_LINGUIST_LINK_TTL = 30 * 60  # 30 min : accès éditeur, fenêtre courte (comme le super-admin)


@app.post("/linguist/request-link")
def linguist_request_link(body: ParentRequestIn, s: Session = Depends(get_db),
                          sender=Depends(get_email_sender)):
    """Auto-demande d'un lien magique d'accès linguiste. Réservé aux comptes `linguist`.

    Réponse constante (anti-énumération) : on ne révèle jamais si l'email est linguiste.
    """
    user = s.execute(
        select(AppUser).where(AppUser.email == body.email.strip().lower(),
                              AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is not None and user.is_active:
        ctx = build_user_context(s, user.id)
        # super_admin OU linguist : le staff Atlas global peut accéder à la console.
        if can_review_arabic(ctx):
            token = make_single_use_token(str(user.id), purpose="linguist_login",
                                          ttl_s=_LINGUIST_LINK_TTL)
            link = f"{_web_base()}/api/linguist/login?token={token}"
            subject, html, text = linguist_login_email(link)
            sender.send(to=user.email, subject=subject, html=html, text=text)
            log_action(s, action="linguist.request_link", user_id=user.id)
            s.commit()
    return {"ok": True}


@app.get("/linguist/login")
def linguist_login(token: str, s: Session = Depends(get_db)):
    """Valide le lien magique linguiste SANS le consommer → confirmation humaine.

    Même patron anti-préchargement que /parent/login et /admin/login : GET idempotent
    (lecture seule), consommation atomique au POST /linguist/login/confirm.
    """
    web = _web_base()
    try:
        uid = peek_single_use_token(s, token, purpose="linguist_login")
    except TokenAlreadyUsedError:
        return RedirectResponse(f"{web}/login?linguist_error=used", status_code=302)
    except ValueError:
        return RedirectResponse(f"{web}/login?linguist_error=invalid", status_code=302)
    user = s.get(AppUser, uuid.UUID(uid))
    if user is None or not user.is_active or user.deleted_at is not None:
        return RedirectResponse(f"{web}/login?linguist_error=invalid", status_code=302)
    # Contrôle du rôle en LECTURE (le POST re-vérifie au moment de la connexion).
    if not can_review_arabic(build_user_context(s, user.id)):
        return RedirectResponse(f"{web}/login?linguist_error=forbidden", status_code=302)
    # Jeton de LIEN dans le fragment (#…) : jamais envoyé aux serveurs ni journalisé.
    return RedirectResponse(f"{web}/linguist/confirm#token={token}", status_code=302)


@app.post("/linguist/login/confirm")
def linguist_login_confirm(body: MagicLinkConfirmIn, s: Session = Depends(get_db)):
    """CONSOMME le lien magique linguiste (single-use) → jeton de session linguiste."""
    try:
        uid = consume_single_use_token(s, body.token, purpose="linguist_login")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=401, detail="used")
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid")
    # Jeton brûlé dès la consommation : les contrôles suivants ne le « rendent » pas.
    user = s.get(AppUser, uuid.UUID(uid))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="invalid")
    # Re-vérifie le rôle au moment de la connexion (révocation possible entre-temps).
    if not can_review_arabic(build_user_context(s, user.id)):
        raise HTTPException(status_code=403, detail="forbidden")
    log_action(s, action="linguist.login", user_id=user.id)
    s.commit()
    return {"token": make_token(str(user.id))}


@app.post("/admin/parents/invite")
def admin_parents_invite(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db),
                         sender=Depends(get_email_sender)):
    """Envoie un lien magique à tous les parents actifs du tenant (IT admin)."""
    org = _require_it_admin_org(ctx, s)
    parents = s.execute(
        select(AppUser).join(Membership, Membership.user_id == AppUser.id)
        .where(Membership.organization_id == org.id, Membership.role == Role.PARENT,
               AppUser.deleted_at.is_(None), AppUser.is_active.is_(True))
    ).scalars().unique().all()
    for p in parents:
        _send_parent_link(sender, p)
    log_action(s, action="parents.invite", user_id=ctx.user_id, details={"count": len(parents)})
    s.commit()
    return {"invited": len(parents)}


@app.get("/parent/children")
def parent_children(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Enfants du parent connecté (étiquette = email scolaire ; on ne stocke pas de nom)."""
    if Role.PARENT not in ctx.roles:
        raise HTTPException(status_code=403, detail="réservé aux parents")
    out = []
    for sid in ctx.child_student_ids:
        st = s.get(Student, sid)
        if st is None or st.deleted_at is not None:
            continue
        school = s.get(School, st.school_id)
        if school is None or school.deleted_at is not None:   # école supprimée → enfant masqué
            continue
        label = st.external_ref or "—"
        if st.user_id:
            child = s.get(AppUser, st.user_id)
            if child is not None:
                label = child.email
        out.append({"student_id": str(sid), "label": label})
    return {"children": out}


# ---------- liaison parent↔enfant par le staff (autorité de confiance, audité) ----------

class GuardianIn(BaseModel):
    email: str
    send_invite: bool = True


@app.get("/students/{student_id}/guardians")
def list_guardians(student_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                   s: Session = Depends(get_db)):
    """Tuteurs d'un élève (prof/admin de l'élève)."""
    _authorize_student(ctx, s, student_id, staff_only=True)
    rows = s.execute(
        select(AppUser, ParentStudent.source)
        .join(ParentStudent, ParentStudent.user_id == AppUser.id)
        # Parent soft-deleted : le lien est conservé (réactivable par add_guardian)
        # mais son email n'est plus exposé au staff (revue 2026-07-08).
        .where(ParentStudent.student_id == student_id,
               AppUser.deleted_at.is_(None))
    ).all()
    return {"guardians": [{"user_id": str(u.id), "email": u.email, "source": src}
                          for (u, src) in rows]}


@app.post("/students/{student_id}/guardians")
def add_guardian(student_id: uuid.UUID, body: GuardianIn,
                 ctx: UserContext = Depends(get_context), s: Session = Depends(get_db),
                 sender=Depends(get_email_sender)):
    """Rattache un email parent à l'élève — c'est le STAFF qui établit la confiance. Audité."""
    st = _authorize_student(ctx, s, student_id, staff_only=True)   # 403/404 si pas staff de l'élève
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email requis")
    pu = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
    if pu is None:
        pu = AppUser(email=email); s.add(pu); s.flush()  # staff-managed → pas d'external_ref
    elif pu.deleted_at is not None:
        pu.deleted_at, pu.is_active = None, True
    school = s.get(School, st.school_id)
    org_id = school.organization_id if school is not None else None
    if s.execute(select(Membership).where(Membership.user_id == pu.id,
                                          Membership.role == Role.PARENT)).scalar_one_or_none() is None:
        s.add(Membership(user_id=pu.id, role=Role.PARENT, organization_id=org_id))
    if s.get(ParentStudent, (pu.id, st.id)) is None:
        s.add(ParentStudent(user_id=pu.id, student_id=st.id, source="staff"))
    log_action(s, action="guardian.link", user_id=ctx.user_id, school_id=st.school_id,
               resource_type="student", resource_id=st.id, details={"parent": email})
    if body.send_invite:
        _send_parent_link(sender, pu)
    s.commit()
    return {"student_id": str(st.id), "parent_user_id": str(pu.id), "email": email}


@app.delete("/students/{student_id}/guardians/{user_id}")
def remove_guardian(student_id: uuid.UUID, user_id: uuid.UUID,
                    ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Retire un lien tuteur (prof/admin de l'élève). Audité."""
    st = _authorize_student(ctx, s, student_id, staff_only=True)
    ps = s.get(ParentStudent, (user_id, st.id))
    if ps is None:
        raise HTTPException(status_code=404, detail="lien introuvable")
    s.delete(ps)
    log_action(s, action="guardian.unlink", user_id=ctx.user_id, school_id=st.school_id,
               resource_type="student", resource_id=st.id, details={"parent_user_id": str(user_id)})
    s.commit()
    return {"ok": True}


# ---------- onboarding IT : checklist guidée (état dérivé) ----------

@app.get("/admin/setup")
def admin_setup(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Étapes de mise en route, cochées automatiquement depuis l'état réel du tenant."""
    org = _require_it_admin_org(ctx, s)
    integ = _integration_of(s, org)
    usage = licensing.seat_usage(s, org)
    synced = integ is not None and integ.last_sync_at is not None
    invited = s.execute(
        select(AuditLog.id).where(
            AuditLog.action == "parents.invite",
            AuditLog.user_id.in_(
                select(Membership.user_id).where(Membership.organization_id == org.id)),
        ).limit(1)
    ).first() is not None
    steps = [
        {"key": "connect", "done": integ is not None},
        {"key": "sync", "done": synced},
        {"key": "verify", "done": usage["used"] > 0},
        {"key": "parents", "done": invited},
    ]
    return {"steps": steps, "done": sum(1 for x in steps if x["done"]), "total": len(steps)}


@app.get("/me")
def me(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Identité + périmètre de l'utilisateur courant — pilote la navigation du front."""
    from src.models.measurement import School

    def _cls_payload(cls: Classroom) -> dict:
        return {"id": str(cls.id), "name": cls.name, "school_id": str(cls.school_id),
                "grade": cls.grade}

    classrooms = []
    # enseignant : ses classes ; dept_lead : les classes de ses niveaux (refonte A1)
    own_class_ids = list(ctx.classroom_ids) + [c for c in ctx.dept_classroom_ids
                                               if c not in ctx.classroom_ids]
    for cid in own_class_ids:
        cls = s.get(Classroom, cid)
        if cls is not None and cls.deleted_at is None:
            classrooms.append(_cls_payload(cls))

    schools = []
    # admin : écoles de son périmètre (en tête — le front route l'admin sur schools[0]) ;
    # group_admin : toutes les écoles de son organisation ; enseignant/dept_lead : écoles de
    # ses classes
    seen = list(ctx.school_ids) + [x for x in ctx.group_school_ids if x not in ctx.school_ids]
    for cid in own_class_ids:
        cls = s.get(Classroom, cid)
        if cls is not None and cls.deleted_at is None and cls.school_id not in seen:
            seen.append(cls.school_id)
    for sid in seen:
        sch = s.get(School, sid)
        if sch is not None and sch.deleted_at is None:
            schools.append({"id": str(sch.id), "name": sch.name})
            for cls in s.execute(active(Classroom).where(Classroom.school_id == sch.id)).scalars():
                # Seules les classes réellement accessibles : un group_admin voit l'école,
                # pas ses classes (aucune portée élève).
                if not any(c["id"] == str(cls.id) for c in classrooms) \
                        and can_access_classroom(ctx, cls.id, sch.id):
                    classrooms.append(_cls_payload(cls))

    # Organisations : celles qu'un group_admin lit ou qu'un it_admin administre (refonte A1).
    org_ids = sorted(ctx.admin_org_ids | frozenset(
        m.organization_id for m in s.execute(
            select(Membership).where(Membership.user_id == ctx.user_id,
                                     Membership.role == Role.GROUP_ADMIN,
                                     Membership.organization_id.is_not(None))
        ).scalars()), key=str)
    organizations = []
    for oid in org_ids:
        org = s.get(Organization, oid)
        if org is not None and org.deleted_at is None:
            organizations.append({"id": str(org.id), "name": org.name})

    return {
        "user_id": str(ctx.user_id),
        "roles": sorted(r.value for r in ctx.roles),
        "schools": schools,
        "classrooms": classrooms,
        "organizations": organizations,
        # dept_lead : couples (école, niveau) couverts — pilote l'écran de département
        "department_scopes": sorted(
            ({"school_id": str(sid), "grade": g} for sid, g in ctx.dept_scopes),
            key=lambda d: (d["school_id"], d["grade"])),
        "child_student_ids": [str(x) for x in ctx.child_student_ids],
        "own_student_id": str(ctx.own_student_id) if ctx.own_student_id else None,
    }


def _authorize_student(ctx: UserContext, s: Session, student_id: uuid.UUID,
                       staff_only: bool = False) -> Student:
    # staff_only (gestion des tuteurs) : seules les branches staff de can_access_student
    # comptent — jamais le lien parent ni l'identité élève, même cumulés à un rôle staff.
    if staff_only:
        ctx = replace(ctx, child_student_ids=frozenset(), own_student_id=None)
    # Soft delete filtré (revue sécurité) : un élève supprimé — ou dont l'école est
    # supprimée — n'est plus accessible par AUCUN endpoint (sessions, vues, parent).
    st = s.execute(active(Student).where(Student.id == student_id)).scalar_one_or_none()
    if st is None:
        raise HTTPException(status_code=404, detail="élève introuvable")
    if s.execute(active(School).where(School.id == st.school_id)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="élève introuvable")
    # Ensemble des classes de l'élève (principale + spécialités) pour le contrôle enseignant.
    class_ids = set(s.execute(
        select(StudentClassroom.classroom_id).where(StudentClassroom.student_id == st.id)
    ).scalars())
    if st.classroom_id:
        class_ids.add(st.classroom_id)
    if not can_access_student(ctx, st.id, st.school_id, class_ids):
        raise HTTPException(status_code=403, detail="accès refusé à cet élève")
    return st


def _get_live_classroom(s: Session, classroom_id: uuid.UUID) -> Classroom:
    """Classe vivante (soft delete filtré, y compris l'école porteuse) ou 404."""
    cls = s.execute(active(Classroom).where(Classroom.id == classroom_id)).scalar_one_or_none()
    if cls is None:
        raise HTTPException(status_code=404, detail="classe introuvable")
    if s.execute(active(School).where(School.id == cls.school_id)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="classe introuvable")
    return cls


def _get_live_school(s: Session, school_id: uuid.UUID) -> School:
    """École vivante (soft delete filtré) ou 404."""
    sch = s.execute(active(School).where(School.id == school_id)).scalar_one_or_none()
    if sch is None:
        raise HTTPException(status_code=404, detail="établissement introuvable")
    return sch


# ---------- session (protégée RBAC) ----------

class StartSessionIn(BaseModel):
    student_id: uuid.UUID                # school_id dérivé de l'élève (pas de confiance au client)
    target_competency_ids: Optional[List[uuid.UUID]] = None
    locale: Literal["en", "ar"] = "en"   # langue servie (C-0) — validée ici (422 sinon)


class ResponseIn(BaseModel):
    item_id: uuid.UUID
    selected: str                       # option choisie ; correction côté serveur
    lang: str = "en"                    # "en" | "ar"
    response_time_ms: Optional[int] = None


def _get_session(s: Session, session_id: uuid.UUID) -> AssessmentSession:
    sess = s.get(AssessmentSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session introuvable")
    return sess


@app.post("/sessions")
def create_session(body: StartSessionIn, ctx: UserContext = Depends(get_context),
                   s: Session = Depends(get_db)):
    st = _authorize_student(ctx, s, body.student_id)
    sess = start_session(s, student_id=st.id, school_id=st.school_id,
                         target_competency_ids=body.target_competency_ids,
                         locale=body.locale)
    return {"session_id": str(sess.id), "status": sess.status, "locale": sess.locale.value}


@app.get("/sessions/{session_id}/next-item")
def get_next_item(session_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                  s: Session = Depends(get_db)):
    sess = _get_session(s, session_id)
    _authorize_student(ctx, s, sess.student_id)
    return next_item(s, sess)


@app.post("/sessions/{session_id}/responses")
def post_response(session_id: uuid.UUID, body: ResponseIn,
                  ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    sess = _get_session(s, session_id)
    _authorize_student(ctx, s, sess.student_id)
    item = s.get(Item, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item introuvable")
    is_correct = grade_answer(item, body.selected, body.lang)   # correction serveur
    try:
        result = submit_response(s, sess, item_id=body.item_id, is_correct=is_correct,
                                 response_time_ms=body.response_time_ms, selected=body.selected)
        # `was_correct` = correction de la réponse qu'on vient de soumettre (feedback élève) ;
        # le reste du payload décrit l'item SUIVANT.
        return {**result, "was_correct": is_correct}
    except AlreadyAnswered:
        raise HTTPException(status_code=409, detail="item déjà répondu dans cette session")
    except SessionCompleted:
        # Session terminée : plus aucune réponse acceptée (l'Elo ne bouge que dans le
        # flux adaptatif) — next-item, lui, continue de répondre {done: true}.
        raise HTTPException(status_code=409, detail="session terminée")


@app.get("/classrooms/{classroom_id}/gaps")
def classroom_gaps(classroom_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                   s: Session = Depends(get_db)):
    """T5.4 — vue enseignant : lacunes de SA classe (RBAC)."""
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    log_action(s, action="classroom.view_gaps", school_id=cls.school_id, user_id=ctx.user_id,
               resource_type="classroom", resource_id=classroom_id)
    s.commit()
    return {"classroom_id": str(classroom_id), "gaps": class_gaps(s, classroom_id)}


@app.get("/classrooms/{classroom_id}/digest")
def classroom_digest(classroom_id: uuid.UUID, days: int = 7,
                     ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Digest hebdomadaire enseignant (Mouvement 01) : activité, lacunes émergentes, priorité #1."""
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    log_action(s, action="classroom.view_digest", school_id=cls.school_id, user_id=ctx.user_id,
               resource_type="classroom", resource_id=classroom_id)
    s.commit()
    return class_digest(s, classroom_id, days=min(max(days, 1), 90))


@app.get("/classrooms/{classroom_id}/students")
def classroom_students(classroom_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                       s: Session = Depends(get_db)):
    """Liste des élèves d'une classe (enseignant/admin)."""
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    return {"classroom_id": str(classroom_id), "name": cls.name,
            "students": list_students(s, classroom_id)}


# ---------- rôles attribués hors roster : dept_lead, group_admin (refonte A1, Q13) ----------
#
# Le roster ne connaît pas ces rôles ; un admin IT de l'organisation (ou le super admin) les
# attribue par email ; le ped_admin nomme le coordinateur (dept_lead) de SON école. Fonctionne
# avec SSO (l'IdP retrouve le compte par email) ou sans (lien magique, cf. /admin/request-link).
# Logique dans src/rbac/grants.py.

class RoleGrantIn(BaseModel):
    email: str
    role: str                              # "dept_lead" | "group_admin"
    organization_id: Optional[uuid.UUID] = None
    school_id: Optional[uuid.UUID] = None
    grades: Optional[List[int]] = None     # dept_lead uniquement


def _live_school_org(s: Session, school_id: uuid.UUID) -> uuid.UUID:
    sch = s.execute(active(School).where(School.id == school_id)).scalar_one_or_none()
    if sch is None or sch.organization_id is None:
        raise HTTPException(status_code=404, detail="école introuvable")
    return sch.organization_id


def _can_act_on_grant(ctx: UserContext, s: Session, role: Role,
                      organization_id: Optional[uuid.UUID], school_id: Optional[uuid.UUID]) -> bool:
    """Contrôle d'accès AVANT d'agir : org pour tout rôle ; école (ped_admin) pour un dept_lead."""
    if school_id is not None:
        org_id = _live_school_org(s, school_id)
        if role == Role.DEPT_LEAD:
            return can_grant_dept_lead(ctx, school_id, org_id)
        return can_manage_roles(ctx, org_id)
    if organization_id is None:
        raise HTTPException(status_code=400, detail="organization_id ou school_id requis")
    return can_manage_roles(ctx, organization_id)


@app.post("/admin/roles")
def admin_grant_role(body: RoleGrantIn, ctx: UserContext = Depends(get_context),
                     s: Session = Depends(get_db)):
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="rôle inconnu")
    if role not in grants.GRANTABLE_ROLES:
        raise HTTPException(status_code=400,
                            detail=f"rôle non attribuable ici (attendu : "
                                   f"{sorted(r.value for r in grants.GRANTABLE_ROLES)})")
    if not _can_act_on_grant(ctx, s, role, body.organization_id, body.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette portée")
    try:
        res = grants.grant_role(s, email=body.email, role=role,
                                organization_id=body.organization_id,
                                school_id=body.school_id, grades=body.grades,
                                actor_user_id=ctx.user_id)
    except grants.GrantError as e:
        raise HTTPException(status_code=400, detail=str(e))
    s.commit()
    return {**res.grant.as_dict(), "created_user": res.created_user,
            "created_membership": res.created_membership}


@app.get("/admin/roles")
def admin_list_roles(organization_id: Optional[uuid.UUID] = None,
                     school_id: Optional[uuid.UUID] = None,
                     ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Par organisation (gestionnaires de rôles) ou par école (ped_admin : ses dept_lead)."""
    if school_id is not None:
        if not can_grant_dept_lead(ctx, school_id, _live_school_org(s, school_id)):
            raise HTTPException(status_code=403, detail="accès refusé à cette école")
        return {"school_id": str(school_id),
                "grants": [g.as_dict() for g in grants.list_grants(s, school_id=school_id)]}
    if organization_id is None:
        raise HTTPException(status_code=400, detail="organization_id ou school_id requis")
    if not can_manage_roles(ctx, organization_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette organisation")
    return {"organization_id": str(organization_id),
            "grants": [g.as_dict() for g in grants.list_grants(s, organization_id=organization_id)]}


@app.delete("/admin/roles/{membership_id}")
def admin_revoke_role(membership_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                      s: Session = Depends(get_db)):
    org_id = grants.organization_of_grant(s, membership_id)
    if org_id is None:
        raise HTTPException(status_code=404, detail="attribution introuvable")
    m = s.get(Membership, membership_id)
    if not _can_act_on_grant(ctx, s, m.role, org_id, m.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette portée")
    g = grants.revoke_role(s, membership_id=membership_id, actor_user_id=ctx.user_id)
    s.commit()
    return {"revoked": g.as_dict()}


class ClassroomGradeIn(BaseModel):
    grade: Optional[int] = None    # None = niveau inconnu (la classe sort de toute portée dept_lead)


@app.patch("/classrooms/{classroom_id}/grade")
def set_classroom_grade(classroom_id: uuid.UUID, body: ClassroomGradeIn,
                        ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Niveau d'une classe, saisi en admin quand le roster ne le fournit pas (refonte A1).

    Réservé aux admins de l'école (it/ped) et au super admin : il pilote la portée des
    coordinateurs (dept_lead_scope), un enseignant ou un dept_lead ne le modifie pas."""
    cls = _get_live_classroom(s, classroom_id)
    if not can_manage_school(ctx, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    if body.grade is not None and not (0 <= body.grade <= 13):
        raise HTTPException(status_code=400, detail="grade attendu entre 0 (KG) et 13")
    cls.grade = body.grade
    log_action(s, action="classroom.set_grade", school_id=cls.school_id, user_id=ctx.user_id,
               resource_type="classroom", resource_id=cls.id, details={"grade": body.grade})
    s.commit()
    return {"classroom_id": str(cls.id), "grade": cls.grade}


@app.get("/classrooms/{classroom_id}/matrix")
def classroom_matrix_ep(classroom_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                        s: Session = Depends(get_db)):
    """E5 · Matrice élèves × compétences (4 états). Lisible par qui lit la classe."""
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    return class_matrix(s, classroom_id)


@app.get("/students/{student_id}/unlocks")
def student_unlocks_ep(student_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                       s: Session = Depends(get_db)):
    """E6 / S3 · Historique des déblocages prouvés d'un élève (preuves `unlocked`)."""
    from src.models.plan import Proof
    st = _authorize_student(ctx, s, student_id)
    rows = s.execute(select(Proof).where(Proof.student_id == st.id, Proof.outcome == ProofOutcome.UNLOCKED)
                     .order_by(Proof.computed_at.desc())).scalars().all()
    comps = {c.id: c for c in s.execute(select(Competency).where(
        Competency.id.in_([p.competency_id for p in rows]))).scalars()} if rows else {}
    return {"student_id": str(st.id), "unlocks": [{
        "competency_code": comps[p.competency_id].code if p.competency_id in comps else None,
        "label_en": comps[p.competency_id].label_en if p.competency_id in comps else None,
        "label_ar": comps[p.competency_id].label_ar if p.competency_id in comps else None,
        "before_elo": p.before_elo, "after_elo": p.after_elo,
        "unlocked_at": p.computed_at.isoformat() if p.computed_at else None,
    } for p in rows]}


@app.get("/students/{student_id}/profile")
def get_student_profile(student_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                        s: Session = Depends(get_db)):
    """Fiche élève — profil de maîtrise + diagnostic causal (écran héros). RBAC."""
    st = _authorize_student(ctx, s, student_id)
    log_action(s, action="student.view_profile", school_id=st.school_id, user_id=ctx.user_id,
               resource_type="student", resource_id=st.id)
    s.commit()
    return student_profile(s, student_id)


@app.get("/students/{student_id}/trajectory")
def get_student_trajectory(student_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                           s: Session = Depends(get_db)):
    """Trajectoire (vue parent, lecture seule). RBAC."""
    st = _authorize_student(ctx, s, student_id)
    log_action(s, action="student.view_trajectory", school_id=st.school_id, user_id=ctx.user_id,
               resource_type="student", resource_id=st.id)
    s.commit()
    return student_trajectory(s, student_id)


@app.get("/students/{student_id}/tutor")
def student_tutor(student_id: uuid.UUID, competency_code: str,
                  ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Tuteur causal (Mouvement 04) : explique « pourquoi cet exercice » pour une lacune.

    Déterministe, sans PII (sortie = libellés de compétences). Accessible à qui peut déjà
    voir l'élève (élève lui-même, enseignant, parent) — l'autorisation est vérifiée.
    """
    _authorize_student(ctx, s, student_id)
    return tutor_explanation(s, student_id, competency_code)


class RemediationIn(BaseModel):
    competency_code: str
    lang: str = "en"


@app.post("/remediation/preview")
def post_remediation(body: RemediationIn, ctx: UserContext = Depends(get_context),
                     s: Session = Depends(get_db)):
    """Aperçu d'un exercice de remédiation pour la compétence ciblée (cause racine)."""
    if not ctx.has(Role.TEACHER, Role.PED_ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="rôle non autorisé")
    return remediation_preview(s, body.competency_code, body.lang)


@app.get("/competencies")
def get_competencies(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Graphe du référentiel (nœuds + arêtes) — support de la viz diagnostic."""
    return referentiel_graph(s)


# ---------- console linguiste : descente de l'arabe dans le contenu (Mouvement 02) ----------
#
# Le pipeline AR existe (items/arabic.py + review.py) mais n'était exposé nulle part : un
# linguiste ne pouvait pas travailler. Ici on l'ouvre, sous garde-fou pédagogique. La machine
# PROPOSE (Groq/ALLaM), le linguiste VALIDE — le gate ar_validated reste la seule porte d'entrée
# au pool servi (cf. review.promote_to_active).

def _require_linguist(ctx: UserContext) -> None:
    if not ctx.has(Role.PED_ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="rôle pédagogique requis (validation linguistique)")


def _ar_item_payload(it: Item) -> dict:
    return {
        "item_id": str(it.id),
        "competency_id": str(it.competency_id),
        "status": it.status.value,
        "answer_format": it.answer_format.value,
        "content_en": it.content_en,
        "content_ar": it.content_ar,
        "ar_validated": it.ar_validated,
        # Fidélité math déterministe EN↔AR : priorise la revue (un nombre altéré = à corriger).
        "math_preserved": ar_math_preserved(it.content_en, it.content_ar) if it.content_ar else False,
    }


@app.get("/admin/arabic/coverage")
def admin_arabic_coverage(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Couverture arabe de la banque (preuve de la « descente » AR — prérequis KSA)."""
    _require_linguist(ctx)
    return ar_coverage(s)


@app.get("/admin/arabic/pending")
def admin_arabic_pending(limit: int = 50, ctx: UserContext = Depends(get_context),
                         s: Session = Depends(get_db)):
    """Worklist du linguiste : items revus EN en attente de traduction/validation AR."""
    _require_linguist(ctx)
    items = review.list_pending_arabic(s)[: min(max(limit, 1), 200)]
    return {"items": [_ar_item_payload(it) for it in items], "coverage": ar_coverage(s)}


@app.post("/admin/arabic/{item_id}/propose")
def admin_arabic_propose(item_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                         s: Session = Depends(get_db), client=Depends(get_llm_client)):
    """Propose un content_ar via Groq/ALLaM (machine PROPOSE). Repose ar_validated à False."""
    _require_linguist(ctx)
    it = s.get(Item, item_id)
    if it is None or it.deleted_at is not None:
        raise HTTPException(status_code=404, detail="item introuvable")
    try:
        content_ar = translate_to_arabic(it.content_en, client, answer_format=it.answer_format)
    except TranslationError as exc:
        raise HTTPException(status_code=502, detail=f"traduction inexploitable : {exc}")
    review.set_arabic(s, it, content_ar, by=str(ctx.user_id))
    log_action(s, action="arabic.propose", user_id=ctx.user_id,
               resource_type="item", resource_id=it.id)
    s.commit()
    return _ar_item_payload(it)


@app.post("/admin/arabic/{item_id}/validate")
def admin_arabic_validate(item_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                          s: Session = Depends(get_db)):
    """Le linguiste VALIDE l'AR : ar_validated=True, human_reviewed → linguist_validated."""
    _require_linguist(ctx)
    it = s.get(Item, item_id)
    if it is None or it.deleted_at is not None:
        raise HTTPException(status_code=404, detail="item introuvable")
    try:
        review.validate_arabic(s, it, linguist=str(ctx.user_id))
    except review.InvalidTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_action(s, action="arabic.validate", user_id=ctx.user_id,
               resource_type="item", resource_id=it.id)
    s.commit()
    return _ar_item_payload(it)


# ---------- back-office LINGUISTE : file de validation AR (Mouvement 02, persona dédié) ----------
#
# Équivalent web de `scripts/review_items.py ar-pending`. Le linguiste (staff Atlas global,
# rôle `linguist` OU super_admin) relit/corrige/valide les traductions AR de la banque. La
# banque n'étant PAS tenant-scopée, aucun filtrage par école : l'autorisation ne dépend que
# du rôle (cf. can_review_arabic). Le gate ar_validated reste la seule porte vers le pool servi.


def require_linguist(ctx: UserContext) -> None:
    """403 si l'appelant n'est pas linguiste (ou super_admin). Pas de périmètre école."""
    if not can_review_arabic(ctx):
        raise HTTPException(status_code=403, detail="rôle linguiste requis")


def _linguist_queue_payload(it: Item) -> dict:
    """Item pour la file linguiste. Inclut la réponse : l'audience est STAFF (pas élève),
    et le linguiste a besoin de `answer`/`options` pour juger la fidélité de la traduction.
    Ce n'est PAS une clé de correction exposée à un élève — choix assumé (spec §3)."""
    prov = it.provenance or {}
    return {
        "item_id": str(it.id),
        "competency_id": str(it.competency_id),
        "status": it.status.value,
        "answer_format": it.answer_format.value,
        "content_en": it.content_en,
        "content_ar": it.content_ar,
        "ar_validated": it.ar_validated,
        # Flag de fidélité math posé par scripts/check_ar_fidelity.py (provenance) OU calculé.
        "ar_math_broken": bool(prov.get("ar_math_broken")),
        "math_preserved": ar_math_preserved(it.content_en, it.content_ar) if it.content_ar else False,
        # Provenance utile à la revue (qui a proposé/flaggé, raison) — jamais de PII élève.
        "provenance": {k: prov[k] for k in (
            "ar_proposed_by", "ar_validated_by", "ar_math_broken", "flag_reason", "flagged_by",
        ) if k in prov},
    }


def _linguist_item_or_404(s: Session, item_id: uuid.UUID) -> Item:
    it = s.get(Item, item_id)
    if it is None or it.deleted_at is not None:
        raise HTTPException(status_code=404, detail="item introuvable")
    return it


@app.get("/linguist/queue")
def linguist_queue(limit: int = 100, ctx: UserContext = Depends(get_context),
                   s: Session = Depends(get_db)):
    """File des items à valider (ar_validated=False), flaggés `ar_math_broken` d'abord.

    Mime `scripts/review_items.py ar-pending` : items non validés, priorité aux traductions
    dont la fidélité math est douteuse. Tri secondaire par contenu (déterministe)."""
    require_linguist(ctx)
    items = list(s.execute(
        select(Item).where(Item.ar_validated.is_(False), Item.deleted_at.is_(None))
    ).scalars())
    # Flaggés en tête (ar_math_broken via provenance), puis ordre stable par item_id.
    items.sort(key=lambda it: (not bool((it.provenance or {}).get("ar_math_broken")), str(it.id)))
    payload = [_linguist_queue_payload(it) for it in items[: min(max(limit, 1), 500)]]
    return {"items": payload, "remaining": len(items), "coverage": ar_coverage(s)}


@app.get("/linguist/items/{item_id}")
def linguist_item_detail(item_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                         s: Session = Depends(get_db)):
    """Détail EN+AR côte à côte + fidélité math déterministe (ar_math_preserved)."""
    require_linguist(ctx)
    it = _linguist_item_or_404(s, item_id)
    return _linguist_queue_payload(it)


class LinguistArabicIn(BaseModel):
    content_ar: dict


@app.post("/linguist/items/{item_id}/arabic")
def linguist_edit_arabic(item_id: uuid.UUID, body: LinguistArabicIn,
                         ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Corrige la traduction AR (review.set_arabic : repose ar_validated=False, n'altère
    jamais content_en). Audité `linguist.edit_ar`."""
    require_linguist(ctx)
    it = _linguist_item_or_404(s, item_id)
    try:
        review.set_arabic(s, it, body.content_ar, by=str(ctx.user_id))
    except ValidationError as exc:  # content_ar non conforme à ItemContent
        raise HTTPException(status_code=422, detail=f"contenu AR non conforme : {exc}")
    log_action(s, action="linguist.edit_ar", user_id=ctx.user_id,
               resource_type="item", resource_id=it.id)
    s.commit()
    return _linguist_queue_payload(it)


@app.post("/linguist/items/{item_id}/validate")
def linguist_validate(item_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                      s: Session = Depends(get_db)):
    """Valide l'AR (review.validate_arabic : ar_validated=True + human_reviewed →
    linguist_validated). Respecte la machine à états. Audité `linguist.validate_ar`."""
    require_linguist(ctx)
    it = _linguist_item_or_404(s, item_id)
    try:
        review.validate_arabic(s, it, linguist=str(ctx.user_id))
    except review.InvalidTransition as exc:
        # Saut d'état / précondition non remplie (pas d'AR, mauvais statut) → 409 propre.
        raise HTTPException(status_code=409, detail=str(exc))
    log_action(s, action="linguist.validate_ar", user_id=ctx.user_id,
               resource_type="item", resource_id=it.id)
    s.commit()
    return _linguist_queue_payload(it)


class LinguistFlagIn(BaseModel):
    reason: str


@app.post("/linguist/items/{item_id}/flag")
def linguist_flag(item_id: uuid.UUID, body: LinguistFlagIn,
                  ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Signale un problème de traduction : repose ar_validated=False + raison en provenance.
    N'altère jamais content_en/content_ar. Audité `linguist.flag_ar`."""
    require_linguist(ctx)
    it = _linguist_item_or_404(s, item_id)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="raison requise")
    prov = dict(it.provenance or {})
    prov["ar_math_broken"] = True          # remonte l'item en tête de file
    prov["flag_reason"] = reason
    prov["flagged_by"] = str(ctx.user_id)
    it.provenance = prov
    it.ar_validated = False                # un item signalé n'est plus « bon à servir »
    log_action(s, action="linguist.flag_ar", user_id=ctx.user_id,
               resource_type="item", resource_id=it.id, details={"reason": reason[:200]})
    s.commit()
    return _linguist_queue_payload(it)


# ---------- signalements d'items (refonte A2) ----------
#
# Un enseignant (ou un coordinateur, un linguiste, le super admin) signale un item ; le
# signalement entre dans la file (super admin aujourd'hui, relecteur au ticket A4). Son
# acceptation sort l'item du pool par la machine à états (review.resolve_flag → promote).

class ItemFlagIn(BaseModel):
    reason: str                        # wrong_answer_key | several_correct | unclear_wording | arabic | other
    comment: Optional[str] = None


class ItemFlagResolveIn(BaseModel):
    accept: bool
    quarantine: bool = True            # accepté → sortie du pool si l'item est `active`


def _actor_school_id(ctx: UserContext, s: Session) -> Optional[uuid.UUID]:
    """École d'origine d'un signalement : celle de l'acteur si elle est unique, sinon None."""
    schools = set(ctx.school_ids) | {sid for sid, _ in ctx.dept_scopes}
    if ctx.classroom_ids:
        schools |= set(s.execute(
            select(Classroom.school_id).where(Classroom.id.in_(list(ctx.classroom_ids)))
        ).scalars())
    return next(iter(schools)) if len(schools) == 1 else None


def _flag_payload(fl: ItemFlag, it: Optional[Item]) -> dict:
    out = {
        "id": str(fl.id), "item_id": str(fl.item_id),
        "school_id": str(fl.school_id) if fl.school_id else None,
        "raised_by": str(fl.raised_by) if fl.raised_by else None,
        "reason": fl.reason.value, "comment": fl.comment, "status": fl.status.value,
        "created_at": fl.created_at.isoformat() if fl.created_at else None,
        "resolved_by": str(fl.resolved_by) if fl.resolved_by else None,
        "resolved_at": fl.resolved_at.isoformat() if fl.resolved_at else None,
    }
    if it is not None:
        out["item"] = {
            "competency_id": str(it.competency_id), "status": it.status.value,
            "version": it.version, "template_key": it.template_key, "origin": it.origin.value,
            "stem_en": (it.content_en or {}).get("stem"),
            "stem_ar": (it.content_ar or {}).get("stem") if it.content_ar else None,
        }
    return out


@app.post("/items/{item_id}/flags")
def flag_item_ep(item_id: uuid.UUID, body: ItemFlagIn, ctx: UserContext = Depends(get_context),
                 s: Session = Depends(get_db)):
    if not can_flag_item(ctx):
        raise HTTPException(status_code=403, detail="rôle enseignant, coordinateur ou staff requis")
    it = s.get(Item, item_id)
    if it is None or it.deleted_at is not None:
        raise HTTPException(status_code=404, detail="item introuvable")
    try:
        reason = ItemFlagReason(body.reason)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"motif inconnu (attendu : {[r.value for r in ItemFlagReason]})")
    school_id = _actor_school_id(ctx, s)
    fl = review.flag_item(s, it, raised_by=ctx.user_id, reason=reason, comment=body.comment,
                          school_id=school_id)
    log_action(s, action="item.flag", school_id=school_id, user_id=ctx.user_id,
               resource_type="item", resource_id=it.id,
               details={"flag_id": str(fl.id), "reason": reason.value})
    s.commit()
    return _flag_payload(fl, it)


@app.get("/items/flags")
def list_item_flags(status: str = "open", limit: int = 200,
                    ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """File des signalements (relecteur de contenu, super admin). `status=all` pour tout."""
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    st: Optional[ItemFlagStatus]
    if status == "all":
        st = None
    else:
        try:
            st = ItemFlagStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="statut inconnu (open | accepted | rejected | all)")
    flags = review.list_flags(s, status=st, limit=min(max(limit, 1), 1000))
    items = {it.id: it for it in s.execute(
        select(Item).where(Item.id.in_([f.item_id for f in flags]))).scalars()} if flags else {}
    return {"status": status, "flags": [_flag_payload(f, items.get(f.item_id)) for f in flags]}


@app.post("/items/flags/{flag_id}/resolve")
def resolve_item_flag(flag_id: uuid.UUID, body: ItemFlagResolveIn,
                      ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    fl = s.get(ItemFlag, flag_id)
    if fl is None:
        raise HTTPException(status_code=404, detail="signalement introuvable")
    try:
        review.resolve_flag(s, fl, resolver=ctx.user_id, accept=body.accept, quarantine=body.quarantine)
    except review.InvalidTransition as e:
        raise HTTPException(status_code=400, detail=str(e))
    it = s.get(Item, fl.item_id)
    log_action(s, action="item.flag_resolve", user_id=ctx.user_id, resource_type="item",
               resource_id=fl.item_id,
               details={"flag_id": str(fl.id), "accepted": body.accept,
                        "item_status": it.status.value if it else None})
    s.commit()
    return _flag_payload(fl, it)


# ---------- check-ins de classe (refonte B1, écrans E2 et S1) ----------
#
# L'enseignant ouvre un check-in sur SA classe (code à 4 chiffres, unique parmi les ouverts),
# les élèves rejoignent par le code (session liée), l'écran projeté suit une progression
# ANONYME (invariant 5), la clôture termine les sessions ouvertes. Logique : checkin_service.py.

class CheckInOpenIn(BaseModel):
    kind: Literal["full", "targeted"] = "full"
    competency_ids: Optional[List[uuid.UUID]] = None   # targeted : obligatoire ; full : optionnel
    student_ids: Optional[List[uuid.UUID]] = None      # targeted : membres du groupe
    action_id: Optional[uuid.UUID] = None              # targeted : action du plan (B2/B4)


class CheckInJoinIn(BaseModel):
    code: str
    locale: Literal["en", "ar"] = "en"


def _get_checkin(s: Session, checkin_id: uuid.UUID) -> CheckIn:
    ci = s.get(CheckIn, checkin_id)
    if ci is None:
        raise HTTPException(status_code=404, detail="check-in introuvable")
    _get_live_classroom(s, ci.classroom_id)      # classe ou école supprimée → 404
    return ci


@app.post("/classrooms/{classroom_id}/checkins")
def open_checkin_ep(classroom_id: uuid.UUID, body: CheckInOpenIn,
                    ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    cls = _get_live_classroom(s, classroom_id)
    if not can_run_checkin(ctx, classroom_id):
        raise HTTPException(status_code=403, detail="réservé à l'enseignant de cette classe")
    try:
        ci = checkin_service.open_checkin(
            s, classroom=cls, created_by=ctx.user_id, kind=CheckInKind(body.kind),
            competency_ids=body.competency_ids, student_ids=body.student_ids,
            plan_action_id=body.action_id)
    except checkin_service.CheckInError as e:
        raise HTTPException(status_code=400, detail=str(e))
    s.commit()
    return checkin_service.checkin_payload(ci, with_code=True)


@app.get("/classrooms/{classroom_id}/checkins")
def list_checkins_ep(classroom_id: uuid.UUID, limit: int = 20,
                     ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    rows = s.execute(select(CheckIn).where(CheckIn.classroom_id == classroom_id)
                     .order_by(CheckIn.opened_at.desc()).limit(min(max(limit, 1), 200))).scalars().all()
    show_code = can_run_checkin(ctx, classroom_id)
    return {"classroom_id": str(classroom_id),
            "checkins": [checkin_service.checkin_payload(c, with_code=show_code) for c in rows]}


@app.get("/checkins/{checkin_id}")
def get_checkin_ep(checkin_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                   s: Session = Depends(get_db)):
    ci = _get_checkin(s, checkin_id)
    if not can_access_classroom(ctx, ci.classroom_id, ci.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à ce check-in")
    return checkin_service.checkin_payload(ci, with_code=can_run_checkin(ctx, ci.classroom_id))


@app.get("/checkins/{checkin_id}/progress")
def checkin_progress_ep(checkin_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                        s: Session = Depends(get_db)):
    """Progression ANONYME (écran projeté) : compteurs + tuiles {state, n_answered}. Jamais de
    nom ni d'identifiant d'élève (invariant 5)."""
    ci = _get_checkin(s, checkin_id)
    if not can_access_classroom(ctx, ci.classroom_id, ci.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à ce check-in")
    return checkin_service.progress(s, ci)


@app.post("/checkins/{checkin_id}/close")
def close_checkin_ep(checkin_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                     s: Session = Depends(get_db)):
    ci = _get_checkin(s, checkin_id)
    if not can_run_checkin(ctx, ci.classroom_id):
        raise HTTPException(status_code=403, detail="réservé à l'enseignant de cette classe")
    if ci.status == CheckInStatus.SCHEDULED:
        raise HTTPException(status_code=409, detail="check-in planifié, pas encore démarré")
    result = checkin_service.close_checkin(s, ci, by=ctx.user_id)
    plan_id, proof = None, None
    if not result["already_closed"]:
        if ci.kind == CheckInKind.FULL:
            plan_id = str(plan_service.generate_plan_for_checkin(s, ci, by=ctx.user_id).id)   # B2
        elif ci.plan_action_id is not None:
            proof = proof_service.compute_proofs(s, ci, by=ctx.user_id)                    # B4
    s.commit()
    return {**result, "plan_id": plan_id, "proof": proof, "progress": checkin_service.progress(s, ci)}


@app.post("/checkins/{checkin_id}/start")
def start_checkin_ep(checkin_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                     s: Session = Depends(get_db)):
    """Démarre un re-check planifié (B4) : code alloué, les membres peuvent rejoindre."""
    ci = _get_checkin(s, checkin_id)
    if not can_run_checkin(ctx, ci.classroom_id):
        raise HTTPException(status_code=403, detail="réservé à l'enseignant de cette classe")
    try:
        proof_service.start_checkin(s, ci, by=ctx.user_id)
    except proof_service.ProofError as e:
        raise HTTPException(status_code=409, detail=str(e))
    s.commit()
    return checkin_service.checkin_payload(ci, with_code=True)


@app.post("/checkins/join")
def join_checkin_ep(body: CheckInJoinIn, ctx: UserContext = Depends(get_context),
                    s: Session = Depends(get_db)):
    """S1 · Rejoindre : compte élève déjà connecté (SSO) + code. Refus clair si le code est
    inconnu ou clos, ou si l'élève n'est pas dans la classe (ou le groupe) du check-in."""
    if Role.STUDENT not in ctx.roles or ctx.own_student_id is None:
        raise HTTPException(status_code=403, detail="compte élève requis")
    st = s.execute(active(Student).where(Student.id == ctx.own_student_id)).scalar_one_or_none()
    if st is None:
        raise HTTPException(status_code=403, detail="compte élève requis")
    try:
        sess = checkin_service.join_checkin(s, code=body.code, student=st, locale=body.locale)
    except checkin_service.JoinRefused as e:
        if e.reason == "code":
            raise HTTPException(status_code=404, detail="code inconnu ou check-in clos")
        raise HTTPException(status_code=403, detail="vous n'êtes pas dans la classe de ce check-in")
    return {"session_id": str(sess.id), "checkin_id": str(sess.checkin_id), "status": sess.status,
            "locale": sess.locale.value}


# ---------- plan de la semaine (refonte B2, écrans E1 et E3) ----------

def _get_action(s: Session, action_id: uuid.UUID) -> "tuple[PlanAction, WeeklyPlan]":
    a = s.get(PlanAction, action_id)
    if a is None:
        raise HTTPException(status_code=404, detail="action introuvable")
    plan = s.get(WeeklyPlan, a.plan_id)
    _get_live_classroom(s, plan.classroom_id)
    return a, plan


@app.get("/classrooms/{classroom_id}/plan")
def classroom_plan_ep(classroom_id: uuid.UUID, week: Optional[date] = None,
                      ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """E1 · Le plan actif de la classe (semaine donnée, sinon le plus récent). 404 explicite si
    aucun plan : l'écran propose alors le premier check-in."""
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    plan = plan_service.active_plan(s, classroom_id, week)
    if plan is None:
        raise HTTPException(status_code=404, detail="aucun plan pour cette classe")
    return plan_service.plan_payload(s, plan)


@app.get("/plan-actions/{action_id}")
def plan_action_ep(action_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                   s: Session = Depends(get_db)):
    a, plan = _get_action(s, action_id)
    if not can_access_classroom(ctx, plan.classroom_id, plan.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette action")
    return plan_service.action_payload(s, a)


class MembersPatchIn(BaseModel):
    add: List[uuid.UUID] = []
    remove: List[uuid.UUID] = []


@app.patch("/plan-actions/{action_id}/members")
def plan_action_members_ep(action_id: uuid.UUID, body: MembersPatchIn,
                           ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """E3 · L'enseignant ajoute ou retire un élève du groupe ; la correction est enregistrée."""
    a, plan = _get_action(s, action_id)
    if not can_run_checkin(ctx, plan.classroom_id):
        raise HTTPException(status_code=403, detail="réservé à l'enseignant de cette classe")
    class_ids = {st.id for st in plan_service._class_students(s, plan.classroom_id)}
    try:
        plan_service.set_members(s, a, add=body.add, remove=body.remove, class_student_ids=class_ids,
                                 by=ctx.user_id)
    except plan_service.PlanError as e:
        raise HTTPException(status_code=400, detail=str(e))
    s.commit()
    return plan_service.action_payload(s, a)


@app.post("/plan-actions/{action_id}/done")
def plan_action_done_ep(action_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                        s: Session = Depends(get_db)):
    """E3 · « Marquer comme enseignée » : fige les before_* des membres et planifie le re-check
    ciblé (B4). Renvoie l'action et le check-in planifié (à démarrer : POST /checkins/{id}/start)."""
    a, plan = _get_action(s, action_id)
    if not can_run_checkin(ctx, plan.classroom_id):
        raise HTTPException(status_code=403, detail="réservé à l'enseignant de cette classe")
    try:
        _, recheck = proof_service.mark_done(s, a, by=ctx.user_id)
    except proof_service.ProofError as e:
        raise HTTPException(status_code=409, detail=str(e))
    s.commit()
    return {"action": plan_service.action_payload(s, a),
            "recheck": checkin_service.checkin_payload(recheck, with_code=True)}


@app.get("/plan-actions/{action_id}/proof")
def plan_action_proof_ep(action_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                         s: Session = Depends(get_db)):
    """E4 · Carte de preuve (lisible par qui lit la classe : enseignant, coordinateur, super admin)."""
    a, plan = _get_action(s, action_id)
    if not can_access_classroom(ctx, plan.classroom_id, plan.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette action")
    return proof_service.proof_payload(s, a, with_code=can_run_checkin(ctx, plan.classroom_id))


@app.get("/classrooms/{classroom_id}/proofs")
def classroom_proofs_ep(classroom_id: uuid.UUID, since: Optional[date] = None,
                        ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    cls = _get_live_classroom(s, classroom_id)
    if not can_access_classroom(ctx, classroom_id, cls.school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cette classe")
    return proof_service.classroom_proofs(s, classroom_id, since=since,
                                          with_code=can_run_checkin(ctx, classroom_id))


@app.post("/plan-actions/{action_id}/dismiss")
def plan_action_dismiss_ep(action_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                           s: Session = Depends(get_db)):
    a, plan = _get_action(s, action_id)
    if not can_run_checkin(ctx, plan.classroom_id):
        raise HTTPException(status_code=403, detail="réservé à l'enseignant de cette classe")
    try:
        plan_service.dismiss(s, a, by=ctx.user_id)
    except plan_service.PlanError as e:
        raise HTTPException(status_code=409, detail=str(e))
    s.commit()
    return plan_service.action_payload(s, a)


# ---------- mini-leçons (refonte B3) ----------
#
# Lecture : enseignant, coordinateur, staff Atlas (matrice de docs/refonte/02). Arabe : le
# linguiste pose et valide. Activation : super admin ou relecteur de contenu.

def _get_lesson(s: Session, lesson_id: uuid.UUID) -> MiniLesson:
    lesson = s.get(MiniLesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="leçon introuvable")
    return lesson


def _can_read_lessons(ctx: UserContext) -> bool:
    return ctx.has(Role.TEACHER, Role.DEPT_LEAD, Role.SUPER_ADMIN, Role.CONTENT_REVIEWER, Role.LINGUIST)


@app.get("/lessons/{lesson_id}")
def get_lesson_ep(lesson_id: uuid.UUID, ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not _can_read_lessons(ctx):
        raise HTTPException(status_code=403, detail="accès refusé")
    lesson = _get_lesson(s, lesson_id)
    return lesson_service.payload(lesson, s.get(Competency, lesson.competency_id))


@app.get("/lessons")
def list_lessons_ep(competency_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                    s: Session = Depends(get_db)):
    if not _can_read_lessons(ctx):
        raise HTTPException(status_code=403, detail="accès refusé")
    comp = s.get(Competency, competency_id)
    return {"competency_id": str(competency_id),
            "lessons": [lesson_service.payload(l, comp, full=False) for l in lesson_service.lessons_for(s, competency_id)]}


class LessonArabicIn(BaseModel):
    title_ar: Optional[str] = None
    bodies_ar: List[Optional[str]]       # une entrée par étape, dans l'ordre


@app.post("/linguist/lessons/{lesson_id}/arabic")
def linguist_lesson_arabic(lesson_id: uuid.UUID, body: LessonArabicIn,
                           ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    require_linguist(ctx)
    lesson = _get_lesson(s, lesson_id)
    try:
        lesson_service.set_arabic(s, lesson, title_ar=body.title_ar, bodies_ar=body.bodies_ar, by=ctx.user_id)
    except lesson_service.LessonError as e:
        raise HTTPException(status_code=400, detail=str(e))
    s.commit()
    return lesson_service.payload(lesson, s.get(Competency, lesson.competency_id))


@app.post("/linguist/lessons/{lesson_id}/validate")
def linguist_lesson_validate(lesson_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                             s: Session = Depends(get_db)):
    require_linguist(ctx)
    lesson = _get_lesson(s, lesson_id)
    try:
        lesson_service.validate_arabic(s, lesson, by=ctx.user_id)
    except lesson_service.LessonError as e:
        raise HTTPException(status_code=409, detail=str(e))
    s.commit()
    return lesson_service.payload(lesson, s.get(Competency, lesson.competency_id))


@app.post("/lessons/{lesson_id}/activate")
def lesson_activate(lesson_id: uuid.UUID, ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    lesson = _get_lesson(s, lesson_id)
    try:
        lesson_service.activate(s, lesson, by=ctx.user_id)
    except lesson_service.LessonError as e:
        raise HTTPException(status_code=409, detail=str(e))
    s.commit()
    return lesson_service.payload(lesson, s.get(Competency, lesson.competency_id))


# ---------- éditeur de leçons côté Atlas (O5, refonte B3/B5) ----------
#
# Même validation que les fichiers data/lessons/*.json (lesson_service.LessonDoc), sans fichier.
# Relecteur de contenu et super admin. La couverture des racines (Q3) est servie avec.

@app.get("/ops/lessons")
def ops_lessons_ep(ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    comps = {c.id: c for c in s.execute(select(Competency)).scalars()}
    return {"lessons": [lesson_service.payload(l, comps.get(l.competency_id), full=False)
                        for l in lesson_service.all_lessons(s)],
            "coverage": lesson_service.coverage(s)}


@app.post("/ops/lessons")
def ops_lesson_create(body: dict, ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    try:
        doc = lesson_service.doc_from_payload(body)
        lesson, created = lesson_service.upsert_lesson(s, doc)
    except lesson_service.LessonError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_action(s, action="lesson.create" if created else "lesson.update", user_id=ctx.user_id,
               resource_type="mini_lesson", resource_id=lesson.id, details={"key": lesson.key})
    s.commit()
    return lesson_service.payload(lesson, s.get(Competency, lesson.competency_id))


@app.put("/ops/lessons/{lesson_id}")
def ops_lesson_update(lesson_id: uuid.UUID, body: dict, ctx: UserContext = Depends(get_context),
                      s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    lesson = _get_lesson(s, lesson_id)
    try:
        doc = lesson_service.doc_from_payload(body, key=lesson.key)
        lesson_service.upsert_lesson(s, doc)
    except lesson_service.LessonError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_action(s, action="lesson.update", user_id=ctx.user_id, resource_type="mini_lesson",
               resource_id=lesson.id, details={"key": lesson.key})
    s.commit()
    return lesson_service.payload(lesson, s.get(Competency, lesson.competency_id))


# ---------- file de revue (refonte A4, écran O2) ----------
#
# Une file unique, quatre sources (signalements, échecs de validation, items d'école, arabe à
# valider), regroupée par gabarit. Relecteur de contenu et super admin ; les actions réservées
# au super admin (activer, réhabiliter, régénérer) ne sont ni listées ni acceptées pour le
# relecteur. Toute transition passe par review.promote (invariant 6).

def _review_item_or_404(s: Session, item_id: uuid.UUID) -> Item:
    it = s.get(Item, item_id)
    if it is None or it.deleted_at is not None:
        raise HTTPException(status_code=404, detail="item introuvable")
    return it


@app.get("/ops/review")
def ops_review_queue(source: Optional[str] = None, limit: int = 500,
                     ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    try:
        return review_queue.build_queue(s, source=source, ctx=ctx, limit=min(max(limit, 1), 2000))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/ops/review/items/{item_id}")
def ops_review_item(item_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                    s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    return review_queue.item_detail(s, _review_item_or_404(s, item_id), ctx)


class ItemTransitionIn(BaseModel):
    target: str                      # human_reviewed | quarantined | active
    reason: Optional[str] = None


@app.post("/items/{item_id}/transition")
def item_transition(item_id: uuid.UUID, body: ItemTransitionIn,
                    ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Fait avancer un item d'un cran par la machine à états. La validation de l'arabe
    (→ linguist_validated) reste le geste du linguiste (/linguist/items/{id}/validate)."""
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    it = _review_item_or_404(s, item_id)
    try:
        target = ItemStatus(body.target)
    except ValueError:
        raise HTTPException(status_code=400, detail="statut cible inconnu")
    action = review_queue.action_for_transition(it, target)
    if action is None:
        raise HTTPException(status_code=400, detail=f"{it.status.value} → {target.value} : pas par cette route")
    if action in review_queue.SUPER_ONLY_ACTIONS and not is_super(ctx):
        raise HTTPException(status_code=403, detail="réservé au super admin Atlas")
    before = it.status.value
    try:
        if action == "activate":
            review.promote_to_active(s, it, reviewer=str(ctx.user_id))
        else:
            review.promote(s, it, target, reviewer=str(ctx.user_id))
    except review.InvalidTransition as e:
        raise HTTPException(status_code=400, detail=str(e))
    if body.reason:
        prov = dict(it.provenance or {}); prov[f"{action}_reason"] = body.reason.strip()[:300]
        it.provenance = prov
    log_action(s, action=f"item.{action}", user_id=ctx.user_id, resource_type="item", resource_id=it.id,
               details={"from": before, "to": target.value, "reason": body.reason})
    s.commit()
    return review_queue.item_detail(s, it, ctx)


class ItemRejectIn(BaseModel):
    reason: str


@app.post("/items/{item_id}/reject")
def item_reject(item_id: uuid.UUID, body: ItemRejectIn,
                ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Rejette un item : soft delete (jamais détruit), raison en provenance."""
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    it = _review_item_or_404(s, item_id)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="raison requise")
    review.reject(s, it, reviewer=str(ctx.user_id), reason=reason)
    log_action(s, action="item.reject", user_id=ctx.user_id, resource_type="item", resource_id=it.id,
               details={"reason": reason[:200]})
    s.commit()
    return {"item_id": str(it.id), "rejected": True, "reason": reason}


# ---------- gabarits (refonte A3) : état, quarantaine en masse, régénération ----------
#
# Les gabarits vivent dans le code ; l'UI (file de revue, A4) déclenche quarantaine et suivi.
# La régénération suit une correction du code déployée : elle est exposée pour le relecteur,
# et reste idempotente (rendu inchangé → rien).

class TemplateActionIn(BaseModel):
    reason: Optional[str] = None


@app.get("/ops/templates/{key}")
def ops_template_report(key: str, ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    try:
        return item_templates.template_report(s, key)
    except item_templates.TemplateError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/ops/templates/{key}/quarantine")
def ops_template_quarantine(key: str, body: Optional[TemplateActionIn] = None,
                            ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    try:
        done = item_templates.quarantine_template(s, key, by=str(ctx.user_id),
                                                  reason=(body.reason if body else "") or "")
    except item_templates.TemplateError as e:
        raise HTTPException(status_code=404, detail=str(e))
    log_action(s, action="item.template_quarantine", user_id=ctx.user_id,
               details={"key": key, "n": len(done), "reason": (body.reason if body else None)})
    s.commit()
    return {"key": key, "quarantined": [str(it.id) for it in done]}


@app.post("/ops/templates/{key}/regenerate")
def ops_template_regenerate(key: str, dry_run: bool = False,
                            ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    if not can_review_items(ctx):
        raise HTTPException(status_code=403, detail="rôle relecteur requis")
    try:
        rep = item_templates.regenerate_template(s, key, by=str(ctx.user_id),
                                                 resolver_id=ctx.user_id, dry_run=dry_run)
    except item_templates.TemplateError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not dry_run:
        log_action(s, action="item.template_regenerate", user_id=ctx.user_id, details=rep.as_dict())
        s.commit()
    return {**rep.as_dict(), "dry_run": dry_run}


# ---------- réglages d'école : message hebdomadaire (refonte B6, Q5) ----------

class SchoolSettingsIn(BaseModel):
    country: Optional[str] = None             # ISO 3166-1 alpha-2
    plan_mail_weekday: Optional[int] = None   # 0 = lundi … 6 = dimanche ; None = défaut du pays
    plan_mail_hour: Optional[int] = None      # heure locale ; None = 7 h
    timezone: Optional[str] = None            # IANA ; None = fuseau du pays


@app.get("/schools/{school_id}/settings")
def school_settings_ep(school_id: uuid.UUID, ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    sch = _get_live_school(s, school_id)
    if not can_access_school(ctx, school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cet établissement")
    return weekly_plan_mail.settings_payload(sch)


@app.patch("/schools/{school_id}/settings")
def school_settings_patch_ep(school_id: uuid.UUID, body: SchoolSettingsIn,
                             ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    sch = _get_live_school(s, school_id)
    if not can_manage_school(ctx, school_id):
        raise HTTPException(status_code=403, detail="réservé aux admins de l'établissement")
    data = body.model_dump(exclude_unset=True)
    if "country" in data and data["country"] is not None:
        c = data["country"].strip().upper()
        if len(c) != 2 or not c.isalpha():
            raise HTTPException(status_code=400, detail="country : code ISO à 2 lettres")
        data["country"] = c
    if data.get("plan_mail_weekday") is not None and not 0 <= data["plan_mail_weekday"] <= 6:
        raise HTTPException(status_code=400, detail="plan_mail_weekday : 0 (lundi) à 6 (dimanche)")
    if data.get("plan_mail_hour") is not None and not 0 <= data["plan_mail_hour"] <= 23:
        raise HTTPException(status_code=400, detail="plan_mail_hour : 0 à 23")
    if data.get("timezone") is not None:
        try:
            ZoneInfo(data["timezone"])
        except Exception:
            raise HTTPException(status_code=400, detail="timezone : identifiant IANA attendu (ex. Asia/Dubai)")
    for k, v in data.items():
        setattr(sch, k, v)
    log_action(s, action="school.settings", school_id=sch.id, user_id=ctx.user_id, resource_type="school",
               resource_id=sch.id, details=data)
    s.commit()
    return weekly_plan_mail.settings_payload(sch)


@app.post("/admin/notify/weekly-plan")
def admin_notify_weekly_plan(dry_run: bool = True, school_id: Optional[uuid.UUID] = None,
                             ctx: UserContext = Depends(get_context), s: Session = Depends(get_db),
                             sender=Depends(get_email_sender)):
    """Déclenche (ou simule) l'envoi « votre plan est prêt ». Super admin. `school_id` force
    l'envoi pour une école quelle que soit l'heure (démo, pilote)."""
    if not is_super(ctx):
        raise HTTPException(status_code=403, detail="réservé au super admin Atlas")
    rep = weekly_plan_mail.send_due(s, sender, web_base=_web_base(), dry_run=dry_run, force_school_id=school_id)
    if not dry_run:
        s.commit()
    return {**rep.as_dict(), "dry_run": dry_run, "recipients": rep.sent if dry_run else len(rep.sent)}


@app.get("/schools/{school_id}/overview")
def school_overview_ep(school_id: uuid.UUID, ctx: UserContext = Depends(get_context),
                       s: Session = Depends(get_db)):
    """T5.5 — vue admin pédagogique : agrégat établissement (RBAC + tenant)."""
    _get_live_school(s, school_id)   # école soft-deleted → 404 (soft delete filtré)
    if not can_access_school(ctx, school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cet établissement")
    log_action(s, action="school.view_overview", school_id=school_id, user_id=ctx.user_id,
               resource_type="school", resource_id=school_id)
    s.commit()
    return school_overview(s, school_id)


@app.get("/schools/{school_id}/proof")
def school_proof_ep(school_id: uuid.UUID, window_days: int = 30,
                    ctx: UserContext = Depends(get_context), s: Session = Depends(get_db)):
    """Surfaces de preuve (Mouvement 03) : avant/après cohorte + gains + projection trajectoire."""
    _get_live_school(s, school_id)   # école soft-deleted → 404 (soft delete filtré)
    if not can_access_school(ctx, school_id):
        raise HTTPException(status_code=403, detail="accès refusé à cet établissement")
    log_action(s, action="school.view_proof", school_id=school_id, user_id=ctx.user_id,
               resource_type="school", resource_id=school_id)
    s.commit()
    payload = proof_surfaces(s, school_id, window_days=min(max(window_days, 1), 365))
    # B5 : section « Couverture du programme » — ADDITIVE, absente en vue ATLAS
    coverage = curriculum_coverage(s, school_id)
    if coverage is not None:
        payload["curriculum_coverage"] = coverage
    return payload


_static = Path(__file__).resolve().parent / "static"
if _static.exists():
    app.mount("/ui", StaticFiles(directory=str(_static), html=True), name="ui")
