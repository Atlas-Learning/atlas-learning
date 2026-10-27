"""Moteur de rostering — PUR (snapshot annuaire → état Atlas), idempotent et réversible.

Invariants :
- Réconciliation par `external_ref` (jamais par nom) → renommages et déplacements sûrs.
- Idempotent : re-synchroniser le même snapshot ne produit aucun changement.
- Déprovisioning : seules les entités **issues du rostering** (`external_ref` non nul) et
  absentes du snapshot sont désactivées (soft delete). Les comptes créés à la main
  (ex. 1er IT admin de l'onboarding self-service, sans `external_ref`) sont préservés.
- Tout est tracé dans un `RosterRun` (preuve d'audit pour le client).

Aucune connaissance de Google ici : le moteur ne voit que `DirectorySnapshot`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.models.base import Role, ensure_utc, utcnow
from src.models.measurement import School, Student
from src.models.org import (
    AppUser,
    Classroom,
    Membership,
    Organization,
    ParentStudent,
    RosterRun,
    StudentClassroom,
    TeacherClassroom,
    TenantIntegration,
)
from src.rostering.directory import DirectorySnapshot, DirUser
from src.rostering.mapping import classify_role, pick_homeroom, resolve_group_school

_DEFAULT_OU = "__default__"  # école implicite des domaines mono-école (pas d'OrgUnit)

RoleClassifier = Callable[[DirUser, Dict[str, object]], Optional[Role]]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    errors: int = 0

    @property
    def summary(self) -> str:
        return (f"{self.created} créés, {self.updated} màj, "
                f"{self.deactivated} désactivés, {self.errors} erreurs")


_VENDOR_ROLES = (Role.SUPER_ADMIN, Role.LINGUIST)


def _ownership(s: Session, user: AppUser, org: Organization) -> str:
    """"owned" : compte modifiable par la sync de `org` (au moins une membership, TOUTES
    rattachées à `org` directement ou via l'école, aucune hors tenant ni vendor : super_admin,
    linguiste). "shared" : lié à `org` mais aussi ailleurs / vendor. "foreign" : aucun lien.
    `AppUser` est global : sans ce contrôle, un annuaire réécrirait le compte d'un autre tenant."""
    rows = s.execute(
        select(Membership.role, Membership.organization_id, School.organization_id)
        .outerjoin(School, Membership.school_id == School.id)
        .where(Membership.user_id == user.id)
    ).all()
    if rows and all(
        role not in _VENDOR_ROLES and m_org in (None, org.id) and sc_org in (None, org.id)
        and (m_org or sc_org) is not None
        for (role, m_org, sc_org) in rows
    ):
        return "owned"
    return "shared" if any(org.id in (m_org, sc_org) for (_, m_org, sc_org) in rows) else "foreign"


def _owned_by(s: Session, user: AppUser, org: Organization) -> bool:
    return _ownership(s, user, org) == "owned"


def _match_ref(s: Session, ref: str, org: Organization) -> Tuple[Optional[AppUser], Optional[AppUser]]:
    """(compte détenu, compte partagé) portant cet `external_ref` ; homonymes hors `org` ignorés."""
    shared = None
    for a in s.execute(select(AppUser).where(AppUser.external_ref == ref)).scalars():
        kind = _ownership(s, a, org)
        if kind == "owned":
            return a, None
        if kind == "shared" and shared is None:
            shared = a
    return None, shared


def _in_org_domain(email: str, org: Organization) -> bool:
    return bool(org.domain) and email.rpartition("@")[2] == org.domain.lower()


def _ensure_membership(s: Session, user: AppUser, role: Role,
                       org: Organization, school: Optional[School]) -> None:
    m = s.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.role == role)
    ).scalar_one_or_none()
    if m is None:
        s.add(Membership(user_id=user.id, role=role, organization_id=org.id,
                         school_id=school.id if school else None))
    elif school is not None and m.school_id != school.id:
        m.school_id = school.id


def _recompute_homeroom(s: Session, student_id) -> None:
    """Recale `Student.classroom_id` (homeroom) sur les inscriptions M:N courantes (classes vivantes)."""
    rows = s.execute(
        select(Classroom.id, Classroom.external_ref)
        .join(StudentClassroom, StudentClassroom.classroom_id == Classroom.id)
        .where(StudentClassroom.student_id == student_id, Classroom.deleted_at.is_(None))
    ).all()
    # clé de tri = external_ref si présent, sinon l'id (classes créées hors rostering)
    ref_to_id = {(ref or str(cid)): cid for (cid, ref) in rows}
    hr_ref = pick_homeroom(list(ref_to_id.keys()))
    st = s.get(Student, student_id)
    if st is not None:
        st.classroom_id = ref_to_id.get(hr_ref) if hr_ref is not None else None


def sync_directory(
    s: Session,
    org: Organization,
    snapshot: DirectorySnapshot,
    *,
    classifier: RoleClassifier = classify_role,
    now: Optional[datetime] = None,
    force: bool = False,
    max_deactivation_ratio: float = 0.25,
    deactivation_floor: int = 8,
) -> RosterRun:
    """Réconcilie l'état Atlas de `org` sur `snapshot`. Crée et renvoie un RosterRun (non commit).

    Garde-fou (fail-safe) : si une sync désactiverait ≥ `deactivation_floor` entités ET
    ≥ `max_deactivation_ratio` de la base active, on **n'applique PAS** les désactivations
    (les ajouts/maj le sont) et le run est marqué `blocked` avec le nombre en attente.
    `force=True` lève le garde-fou (approbation de l'IT admin).
    """
    now = ensure_utc(now) or utcnow()   # naïf accepté (tests) → réinterprété UTC
    run = RosterRun(organization_id=org.id, started_at=now)
    res = SyncResult()
    ou_by_id = {ou.external_id: ou for ou in snapshot.org_units}

    # 1) OrgUnits → Schools (+ école par défaut si domaine mono-école) ------------------
    existing_schools = {
        sc.external_ref: sc for sc in s.execute(
            select(School).where(School.organization_id == org.id,
                                 School.external_ref.is_not(None))
        ).scalars()
    }
    schools_by_ref: Dict[str, School] = {}
    seen_school_refs = set()

    def _upsert_school(ref: str, name: str) -> School:
        nonlocal res
        sc = existing_schools.get(ref)
        if sc is None:
            sc = School(name=name, organization_id=org.id, external_ref=ref)
            s.add(sc); s.flush(); res.created += 1
        elif sc.name != name or sc.deleted_at is not None:
            sc.name, sc.deleted_at = name, None; res.updated += 1
        schools_by_ref[ref] = sc
        seen_school_refs.add(ref)
        return sc

    for ou in snapshot.org_units:
        _upsert_school(ou.external_id, ou.name)
    if not snapshot.org_units:
        _upsert_school(_DEFAULT_OU, org.name)

    only_school = next(iter(schools_by_ref.values())) if len(schools_by_ref) == 1 else None

    def _school_for_user(u: DirUser) -> Optional[School]:
        return schools_by_ref.get(u.org_unit_external_id or "") or only_school

    # 2) Users → AppUser (+ Membership, + Student pour les élèves) -----------------------
    appuser_by_ref: Dict[str, AppUser] = {}
    role_by_ref: Dict[str, Role] = {}
    student_by_ref: Dict[str, Student] = {}
    school_by_ref_user: Dict[str, Optional[School]] = {}
    seen_user_refs = set()
    suspended_shared: List[AppUser] = []   # partagés suspendus (même sans external_ref) → détachés
    org_school_ids = select(School.id).where(School.organization_id == org.id)

    for u in snapshot.users:
        role = classifier(u, ou_by_id)
        if role is None:
            continue  # non classé → jamais inscrit par erreur
        email = u.email.lower()
        # Identité DURABLE : on ancre sur external_ref (id Google immuable), jamais l'email
        # (qui change : mariage, transfert, renommage). Repli email = adoption d'un compte
        # créé à la main (ex. IT admin bootstrap) pour ne pas le dupliquer.
        # Seuls les comptes DÉTENUS par `org` sont adoptés/réécrits ; le repli email exige en
        # plus le domaine vérifié du tenant. Compte d'un autre tenant / vendor → erreur, intact.
        # Compte PARTAGÉ (lié à `org` ET ailleurs) → erreur, jamais réécrit ni étendu ; seuls
        # ses liens dans `org` (classes, élève existant) suivent l'annuaire.
        au, shared = _match_ref(s, u.external_id, org) if u.external_id else (None, None)
        if au is None and shared is None:
            found = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
            if found is not None:
                kind = _ownership(s, found, org) if _in_org_domain(email, org) else "foreign"
                if kind == "foreign":
                    res.errors += 1
                    continue
                au, shared = (found, None) if kind == "owned" else (None, found)
        if shared is not None:
            res.errors += 1
            if u.suspended:
                suspended_shared.append(shared)  # perd son accès à `org` au déprovisioning
                continue
            au = shared
            if au.external_ref:
                seen_user_refs.add(au.external_ref)
        elif au is None:
            au = AppUser(email=email, external_ref=u.external_id, is_active=not u.suspended)
            s.add(au); s.flush(); res.created += 1
        else:
            changed = False
            if au.external_ref != u.external_id:
                au.external_ref = u.external_id; changed = True   # adoption d'un compte email-only
            if au.email != email:
                au.email = email; changed = True                  # l'email a changé → on suit la personne
            if au.is_active == u.suspended:
                au.is_active = not u.suspended; changed = True
            if au.deleted_at is not None:
                au.deleted_at = None; changed = True
            if changed:
                res.updated += 1

        sc = _school_for_user(u)
        if shared is None:
            _ensure_membership(s, au, role, org, sc)
        appuser_by_ref[u.external_id] = au
        role_by_ref[u.external_id] = role
        school_by_ref_user[u.external_id] = sc
        seen_user_refs.add(u.external_id)

        if role == Role.STUDENT:
            if sc is None:
                res.errors += 1  # élève sans école résoluble → on n'invente pas
                continue
            q = select(Student).where(Student.user_id == au.id)
            if shared is not None:
                q = q.where(Student.school_id.in_(org_school_ids))
            st = s.execute(q).scalar_one_or_none()
            if st is None and shared is not None:
                continue
            if st is None:
                st = Student(school_id=sc.id, user_id=au.id, external_ref=u.external_id)
                s.add(st); s.flush(); res.created += 1
            elif st.school_id != sc.id or st.deleted_at is not None:
                st.school_id, st.deleted_at = sc.id, None; res.updated += 1
            student_by_ref[u.external_id] = st

    # 3) Groups → Classroom (+ inscriptions) --------------------------------------------
    existing_classes = {
        c.external_ref: c for c in s.execute(
            select(Classroom).join(School, Classroom.school_id == School.id)
            .where(School.organization_id == org.id, Classroom.external_ref.is_not(None))
        ).scalars()
    }
    seen_class_refs = set()

    scope_class_ids = set()                  # classes traitées ce run (réconciliation in-scope)
    desired_student = set()                   # inscriptions élève voulues : (student_id, classroom_id)
    desired_teacher = set()                   # liens prof voulus : (user_id, classroom_id)
    affected_students = set()                 # homeroom à recalculer

    for g in snapshot.groups:
        member_refs = snapshot.members_of(g.external_id)
        student_schools = [
            school_by_ref_user[r].id for r in member_refs
            if role_by_ref.get(r) == Role.STUDENT and school_by_ref_user.get(r) is not None
        ]
        school_id = resolve_group_school(
            student_schools, only_school.id if only_school else None
        )
        if school_id is None:
            res.errors += 1  # classe sans école rattachable → ignorée
            continue

        c = existing_classes.get(g.external_id)
        if c is None:
            c = Classroom(school_id=school_id, name=g.name, external_ref=g.external_id)
            s.add(c); s.flush(); res.created += 1
        elif c.name != g.name or c.school_id != school_id or c.deleted_at is not None:
            c.name, c.school_id, c.deleted_at = g.name, school_id, None; res.updated += 1
        seen_class_refs.add(g.external_id)
        scope_class_ids.add(c.id)

        for r in member_refs:
            role = role_by_ref.get(r)
            if role == Role.STUDENT:
                st = student_by_ref.get(r)
                if st is not None:
                    desired_student.add((st.id, c.id)); affected_students.add(st.id)
            elif role == Role.TEACHER:
                au = appuser_by_ref.get(r)
                if au is not None:
                    desired_teacher.add((au.id, c.id))

    # Inscriptions M:N : ajouts -----------------------------------------------------------
    for (st_id, c_id) in desired_student:
        if s.get(StudentClassroom, (st_id, c_id)) is None:
            s.add(StudentClassroom(student_id=st_id, classroom_id=c_id))
    for (u_id, c_id) in desired_teacher:
        if s.get(TeacherClassroom, (u_id, c_id)) is None:
            s.add(TeacherClassroom(user_id=u_id, classroom_id=c_id))

    # Inscriptions M:N : retraits sur les classes in-scope (élève/prof sorti d'une classe) -
    if scope_class_ids:
        for sc_row in s.execute(
            select(StudentClassroom).where(StudentClassroom.classroom_id.in_(scope_class_ids))
        ).scalars().all():
            if (sc_row.student_id, sc_row.classroom_id) not in desired_student:
                affected_students.add(sc_row.student_id)
                s.delete(sc_row)
        for tc_row in s.execute(
            select(TeacherClassroom).where(TeacherClassroom.classroom_id.in_(scope_class_ids))
        ).scalars().all():
            if (tc_row.user_id, tc_row.classroom_id) not in desired_teacher:
                s.delete(tc_row)
    s.flush()
    for st_id in affected_students:
        _recompute_homeroom(s, st_id)

    # 3.5) Guardians → comptes PARENT + liens parent↔enfant (si la source les fournit) ----
    if snapshot.guardians is not None:
        desired_parent_links = set()
        for g in snapshot.guardians:
            st = student_by_ref.get(g.student_external_id)
            if st is None:
                continue  # tuteur d'un élève non rosterisé → ignoré
            email = g.email.lower()
            ref = g.external_id or email
            pu, shared = _match_ref(s, ref, org)   # mêmes règles que les users (cf. supra)
            if pu is None and shared is None:
                found = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
                if found is not None:
                    kind = _ownership(s, found, org)
                    if kind == "foreign":
                        res.errors += 1
                        continue
                    pu, shared = (found, None) if kind == "owned" else (None, found)
            if shared is not None:
                res.errors += 1
                pu = shared
                if pu.external_ref:
                    seen_user_refs.add(pu.external_ref)
            elif pu is None:
                pu = AppUser(email=email, external_ref=ref, is_active=True)
                s.add(pu); s.flush(); res.created += 1
            else:
                if pu.external_ref != ref:
                    pu.external_ref = ref
                if pu.email != email:
                    pu.email = email
                if pu.deleted_at is not None:
                    pu.deleted_at, pu.is_active = None, True
            if shared is None:
                _ensure_membership(s, pu, Role.PARENT, org, None)
            link = s.get(ParentStudent, (pu.id, st.id))
            if link is None:
                s.add(ParentStudent(user_id=pu.id, student_id=st.id, source="roster"))
            elif link.source != "roster":
                link.source = "roster"  # le lien staff est désormais confirmé par Classroom
            desired_parent_links.add((pu.id, st.id))
            seen_user_refs.add(ref)
        s.flush()
        # retrait des liens obsolètes — UNIQUEMENT ceux issus du rostering (jamais les liens staff)
        org_student_ids = select(Student.id).where(Student.school_id.in_(org_school_ids))
        for ps in s.execute(
            select(ParentStudent).where(ParentStudent.student_id.in_(org_student_ids),
                                        ParentStudent.source == "roster")
        ).scalars().all():
            if (ps.user_id, ps.student_id) not in desired_parent_links:
                s.delete(ps)
    else:
        # La source ne gère pas les tuteurs → on protège les parents existants du déprovisioning.
        for r in s.execute(
            select(AppUser.external_ref).join(Membership, Membership.user_id == AppUser.id)
            .where(Membership.organization_id == org.id, Membership.role == Role.PARENT,
                   AppUser.external_ref.is_not(None))
        ).scalars():
            if r:
                seen_user_refs.add(r)

    # 4) Déprovisioning : on CALCULE les candidats, on décide, puis on applique -----------
    classes_to_deact = [c for ref, c in existing_classes.items()
                        if ref not in seen_class_refs and c.deleted_at is None]
    schools_to_deact = [sc for ref, sc in existing_schools.items()
                        if ref not in seen_school_refs and sc.deleted_at is None]
    org_users = s.execute(
        select(AppUser).join(Membership, Membership.user_id == AppUser.id)
        .where(Membership.organization_id == org.id, AppUser.external_ref.is_not(None))
    ).scalars().unique().all()
    absent_users = [au for au in org_users
                    if au.external_ref not in seen_user_refs and au.deleted_at is None]
    # Compte détenu → désactivation globale ; compte partagé avec un autre tenant → on ne
    # touche pas l'AppUser global mais on lui RETIRE l'accès à `org` (memberships, classes, élève).
    users_to_deact = [au for au in absent_users if _owned_by(s, au, org)]
    users_to_detach = [au for au in absent_users if not _owned_by(s, au, org)]
    users_to_detach += [au for au in suspended_shared if au not in users_to_detach]

    projected = (len(classes_to_deact) + len(schools_to_deact) + len(users_to_deact)
                 + len(users_to_detach))
    baseline = sum(1 for au in org_users if au.deleted_at is None)
    blocked = (not force and projected >= deactivation_floor and baseline > 0
               and projected / baseline >= max_deactivation_ratio)

    if blocked:
        # Garde-fou : suspect (glitch annuaire ? bascule d'année ?) → on retient les retraits.
        run.pending_deactivations = projected
    else:
        for c in classes_to_deact:
            c.deleted_at = now; res.deactivated += 1
            for sc_row in s.execute(
                select(StudentClassroom).where(StudentClassroom.classroom_id == c.id)
            ).scalars().all():
                affected_students.add(sc_row.student_id); s.delete(sc_row)
            for tc_row in s.execute(
                select(TeacherClassroom).where(TeacherClassroom.classroom_id == c.id)
            ).scalars().all():
                s.delete(tc_row)
        s.flush()
        for st_id in affected_students:
            _recompute_homeroom(s, st_id)

        for sc in schools_to_deact:
            sc.deleted_at = now; res.deactivated += 1

        for au in users_to_deact:
            au.is_active, au.deleted_at = False, now; res.deactivated += 1
            for st in s.execute(select(Student).where(Student.user_id == au.id)).scalars():
                if st.deleted_at is None:
                    st.deleted_at = now
                for sc_row in s.execute(
                    select(StudentClassroom).where(StudentClassroom.student_id == st.id)
                ).scalars().all():
                    s.delete(sc_row)
            for tc_row in s.execute(
                select(TeacherClassroom).where(TeacherClassroom.user_id == au.id)
            ).scalars().all():
                s.delete(tc_row)

        for au in users_to_detach:
            res.deactivated += 1
            for m in s.execute(select(Membership).where(
                Membership.user_id == au.id,
                or_(Membership.organization_id == org.id, Membership.school_id.in_(org_school_ids)),
            )).scalars().all():
                s.delete(m)
            # liens tuteur vers les élèves de `org` : sinon le rôle PARENT d'un autre tenant
            # suffirait à garder la lecture sur ces élèves.
            for ps in s.execute(select(ParentStudent).where(
                ParentStudent.user_id == au.id,
                ParentStudent.student_id.in_(
                    select(Student.id).where(Student.school_id.in_(org_school_ids))),
            )).scalars().all():
                s.delete(ps)
            for st in s.execute(select(Student).where(
                Student.user_id == au.id, Student.school_id.in_(org_school_ids)
            )).scalars().all():
                if st.deleted_at is None:
                    st.deleted_at = now
                for sc_row in s.execute(
                    select(StudentClassroom).where(StudentClassroom.student_id == st.id)
                ).scalars().all():
                    s.delete(sc_row)
            for tc_row in s.execute(select(TeacherClassroom).where(
                TeacherClassroom.user_id == au.id,
                TeacherClassroom.classroom_id.in_(
                    select(Classroom.id).where(Classroom.school_id.in_(org_school_ids))),
            )).scalars().all():
                s.delete(tc_row)

    # 5) Trace + état de l'intégration ---------------------------------------------------
    run.created_count = res.created
    run.updated_count = res.updated
    run.deactivated_count = res.deactivated
    run.error_count = res.errors
    run.status = "blocked" if blocked else ("error" if res.errors else "ok")
    run.summary = (f"BLOQUÉ : {projected} désactivations en attente d'approbation ; {res.summary}"
                   if blocked else res.summary)
    run.finished_at = now
    s.add(run); s.flush()

    integ = s.execute(
        select(TenantIntegration).where(TenantIntegration.organization_id == org.id)
    ).scalar_one_or_none()
    if integ is not None:
        integ.last_sync_at = now
        if blocked:
            integ.status = "blocked"
            integ.last_error = run.summary
        elif res.errors:
            integ.status, integ.last_error = "error", res.summary
        else:
            integ.status, integ.last_error = "connected", None

    return run
