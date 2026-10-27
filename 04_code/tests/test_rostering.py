"""Tests du moteur de rostering (Phase A) — pur, idempotent, réversible.

Couvre : création initiale, idempotence (re-sync = no-op), déplacement d'élève,
déprovisioning des absents, protection du compte bootstrap (sans external_ref),
repli mono-école, et la règle de classification par défaut.
"""
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db import make_engine
from src.models.base import Base, Role
from src.models import competency as _c, item as _i, measurement as _m, session as _se, org as _o  # noqa: F401,E501
from src.models.measurement import School, Student
from src.models.org import (
    AppUser, Classroom, Membership, Organization, ParentStudent, StudentClassroom,
    TeacherClassroom, TenantIntegration,
)
from src.rostering.directory import (
    DirectorySnapshot, DirGroup, DirGuardian, DirMembership, DirOrgUnit, DirUser,
)
from src.rostering.mapping import classify_role
from src.rostering.sync import sync_directory
from src.rbac.authz import build_user_context

NOW = datetime(2026, 1, 1, 12, 0, 0)

ROLES = {
    "alice@school.edu": Role.STUDENT,
    "bob@school.edu": Role.STUDENT,
    "carol@school.edu": Role.TEACHER,
    "dan@school.edu": Role.IT_ADMIN,
}


def _classifier(u, ou_by_id):
    return ROLES.get(u.email.lower())


def _setup(with_integration=True):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(bind=engine)
    org = Organization(name="Demo School", domain="school.edu")
    s.add(org); s.flush()
    # Compte bootstrap créé à l'onboarding (PAS de external_ref) → ne doit JAMAIS être désactivé.
    boot = AppUser(email="it@school.edu")
    s.add(boot); s.flush()
    s.add(Membership(user_id=boot.id, role=Role.IT_ADMIN, organization_id=org.id))
    if with_integration:
        s.add(TenantIntegration(organization_id=org.id, admin_email="it@school.edu"))
    s.commit()
    return s, org


def _base_snapshot():
    elem = DirOrgUnit(external_id="ou_elem", name="Elementary")
    users = [
        DirUser("u_alice", "alice@school.edu", "Alice", "ou_elem"),
        DirUser("u_bob", "bob@school.edu", "Bob", "ou_elem"),
        DirUser("u_carol", "carol@school.edu", "Carol", "ou_elem"),
        DirUser("u_dan", "dan@school.edu", "Dan", "ou_elem", is_admin=True),
    ]
    groups = [DirGroup("g_4a", "Grade 4 A")]
    members = [
        DirMembership("g_4a", "u_alice"),
        DirMembership("g_4a", "u_bob"),
        DirMembership("g_4a", "u_carol"),
    ]
    return DirectorySnapshot([elem], users, groups, members)


def test_initial_sync_creates_entities():
    s, org = _setup()
    run = sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW)
    s.commit()

    # 1 école + 4 comptes (3 + admin) + 2 élèves + 1 classe = 8 créations
    assert run.created_count == 8, run.summary
    assert run.updated_count == 0 and run.deactivated_count == 0 and run.error_count == 0

    school = s.execute(select(School).where(School.external_ref == "ou_elem")).scalar_one()
    assert school.name == "Elementary"
    cls = s.execute(select(Classroom).where(Classroom.external_ref == "g_4a")).scalar_one()
    assert cls.school_id == school.id

    alice = s.execute(select(AppUser).where(AppUser.email == "alice@school.edu")).scalar_one()
    assert alice.external_ref == "u_alice"
    st_alice = s.execute(select(Student).where(Student.user_id == alice.id)).scalar_one()
    assert st_alice.classroom_id == cls.id and st_alice.school_id == school.id

    # Carol (prof) reliée à la classe ; pas d'élève créé pour elle
    carol = s.execute(select(AppUser).where(AppUser.email == "carol@school.edu")).scalar_one()
    assert s.get(TeacherClassroom, (carol.id, cls.id)) is not None
    assert s.execute(select(Student).where(Student.user_id == carol.id)).scalar_one_or_none() is None

    # Intégration : statut + horodatage mis à jour
    integ = s.execute(select(TenantIntegration)).scalar_one()
    assert integ.status == "connected" and integ.last_sync_at == NOW


def test_resync_is_idempotent():
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()
    run = sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()
    assert (run.created_count, run.updated_count, run.deactivated_count, run.error_count) == (0, 0, 0, 0)


def test_student_move_between_classes():
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()

    # Bob passe de g_4a à g_4b (nouvelle classe)
    snap = _base_snapshot()
    snap = DirectorySnapshot(
        snap.org_units, snap.users,
        snap.groups + [DirGroup("g_4b", "Grade 4 B")],
        [DirMembership("g_4a", "u_alice"), DirMembership("g_4a", "u_carol"),
         DirMembership("g_4b", "u_bob")],
    )
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()

    g4b = s.execute(select(Classroom).where(Classroom.external_ref == "g_4b")).scalar_one()
    bob = s.execute(select(AppUser).where(AppUser.email == "bob@school.edu")).scalar_one()
    st_bob = s.execute(select(Student).where(Student.user_id == bob.id)).scalar_one()
    assert st_bob.classroom_id == g4b.id


def test_deprovisioning_and_bootstrap_protection():
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()

    # Bob quitte l'établissement (absent du snapshot)
    snap = _base_snapshot()
    snap = DirectorySnapshot(
        snap.org_units,
        [u for u in snap.users if u.external_id != "u_bob"],
        snap.groups,
        [m for m in snap.memberships if m.user_external_id != "u_bob"],
    )
    run = sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()

    bob = s.execute(select(AppUser).where(AppUser.email == "bob@school.edu")).scalar_one()
    assert bob.deleted_at == NOW and bob.is_active is False
    st_bob = s.execute(select(Student).where(Student.user_id == bob.id)).scalar_one()
    assert st_bob.deleted_at == NOW
    assert run.deactivated_count == 1

    # Le compte bootstrap (sans external_ref) reste actif
    boot = s.execute(select(AppUser).where(AppUser.email == "it@school.edu")).scalar_one()
    assert boot.deleted_at is None and boot.is_active is True


def _enrolled_class_ids(s, email):
    au = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    st = s.execute(select(Student).where(Student.user_id == au.id)).scalar_one()
    ids = set(s.execute(
        select(StudentClassroom.classroom_id).where(StudentClassroom.student_id == st.id)
    ).scalars())
    return st, ids


def _spec_snapshot():
    """Base + une classe de spécialité 'g_sci' où Alice est aussi inscrite."""
    base = _base_snapshot()
    return DirectorySnapshot(
        base.org_units, base.users,
        base.groups + [DirGroup("g_sci", "Science Specialty")],
        base.memberships + [DirMembership("g_sci", "u_alice")],
    )


def test_student_in_multiple_classes():
    s, org = _setup()
    sync_directory(s, org, _spec_snapshot(), classifier=_classifier, now=NOW); s.commit()

    g4a = s.execute(select(Classroom).where(Classroom.external_ref == "g_4a")).scalar_one()
    gsci = s.execute(select(Classroom).where(Classroom.external_ref == "g_sci")).scalar_one()
    st, enrolled = _enrolled_class_ids(s, "alice@school.edu")
    assert enrolled == {g4a.id, gsci.id}        # Alice dans 2 classes (principale + spécialité)
    assert st.classroom_id == g4a.id            # homeroom = ref la plus petite ("g_4a" < "g_sci")
    # Bob, lui, n'a pas la spécialité
    _, bob_classes = _enrolled_class_ids(s, "bob@school.edu")
    assert bob_classes == {g4a.id}


def test_dropping_a_specialty_class():
    s, org = _setup()
    sync_directory(s, org, _spec_snapshot(), classifier=_classifier, now=NOW); s.commit()
    # Alice abandonne la spécialité → retour au snapshot de base
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()

    g4a = s.execute(select(Classroom).where(Classroom.external_ref == "g_4a")).scalar_one()
    st, enrolled = _enrolled_class_ids(s, "alice@school.edu")
    assert enrolled == {g4a.id}                 # inscription spécialité retirée
    assert st.classroom_id == g4a.id            # homeroom recalculé


def _student_of(s, email):
    au = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    return s.execute(select(Student).where(Student.user_id == au.id)).scalar_one()


def _with_guardians(guardians):
    base = _base_snapshot()
    return DirectorySnapshot(base.org_units, base.users, base.groups, base.memberships,
                             guardians=guardians)


def test_guardians_create_parents_and_links():
    s, org = _setup()
    # une mère, tutrice d'Alice ET de Bob
    snap = _with_guardians([
        DirGuardian("u_alice", "mom@home.com", "Mom", "grd1"),
        DirGuardian("u_bob", "mom@home.com", "Mom", "grd1"),
    ])
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()

    mom = s.execute(select(AppUser).where(AppUser.email == "mom@home.com")).scalar_one()
    roles = set(s.execute(select(Membership.role).where(Membership.user_id == mom.id)).scalars())
    assert Role.PARENT in roles
    ctx = build_user_context(s, mom.id)
    assert ctx.child_student_ids == {_student_of(s, "alice@school.edu").id,
                                     _student_of(s, "bob@school.edu").id}


def test_guardian_removal_unlinks_and_deactivates_parent():
    s, org = _setup()
    sync_directory(s, org, _with_guardians([DirGuardian("u_alice", "mom@home.com", "Mom", "grd1")]),
                   classifier=_classifier, now=NOW); s.commit()
    # source gère toujours les tuteurs, mais plus aucun (liste vide) → lien retiré
    sync_directory(s, org, _with_guardians([]), classifier=_classifier, now=NOW); s.commit()

    mom = s.execute(select(AppUser).where(AppUser.email == "mom@home.com")).scalar_one()
    assert mom.deleted_at == NOW and mom.is_active is False
    assert s.execute(select(ParentStudent)).scalars().all() == []


def test_staff_link_survives_classroom_sync():
    """Coexistence : un lien parent posé par le staff n'est PAS effacé par une sync Classroom."""
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()
    alice = _student_of(s, "alice@school.edu")
    dad = AppUser(email="dad@home.com"); s.add(dad); s.flush()
    s.add(Membership(user_id=dad.id, role=Role.PARENT, organization_id=org.id))
    s.add(ParentStudent(user_id=dad.id, student_id=alice.id, source="staff"))
    s.commit()

    # sync Classroom AVEC guardians (mais sans dad) → le lien staff doit survivre
    snap = _with_guardians([DirGuardian("u_bob", "mom@home.com", "Mom", "grd1")])
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()
    assert s.get(ParentStudent, (dad.id, alice.id)) is not None


def test_guardians_none_preserves_existing_parents():
    s, org = _setup()
    sync_directory(s, org, _with_guardians([DirGuardian("u_alice", "mom@home.com", "Mom", "grd1")]),
                   classifier=_classifier, now=NOW); s.commit()
    # re-sync depuis une source SANS gestion des tuteurs (guardians=None) → on ne touche à rien
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()

    mom = s.execute(select(AppUser).where(AppUser.email == "mom@home.com")).scalar_one()
    assert mom.deleted_at is None and mom.is_active is True
    alice = _student_of(s, "alice@school.edu")
    assert s.get(ParentStudent, (mom.id, alice.id)) is not None


_ROLES_BY_ID = {"u_alice": Role.STUDENT, "u_bob": Role.STUDENT,
                "u_carol": Role.TEACHER, "u_dan": Role.IT_ADMIN}


def _classifier_by_id(u, ou_by_id):
    return _ROLES_BY_ID.get(u.external_id)


def test_identity_survives_email_change():
    """Changement d'email (même id Google) → MÊME compte + MÊME élève, pas de doublon."""
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier_by_id, now=NOW); s.commit()
    au_id = s.execute(select(AppUser).where(AppUser.email == "alice@school.edu")).scalar_one().id
    st_id = _student_of(s, "alice@school.edu").id

    base = _base_snapshot()
    renamed = [DirUser("u_alice", "alice.smith@school.edu", "Alice Smith", "ou_elem")
               if u.external_id == "u_alice" else u for u in base.users]
    sync_directory(s, org, DirectorySnapshot(base.org_units, renamed, base.groups, base.memberships),
                   classifier=_classifier_by_id, now=NOW); s.commit()

    same = s.execute(select(AppUser).where(AppUser.external_ref == "u_alice")).scalars().all()
    assert len(same) == 1 and same[0].id == au_id            # pas de doublon
    assert same[0].email == "alice.smith@school.edu"          # email suivi
    assert s.execute(select(Student).where(Student.user_id == au_id)).scalar_one().id == st_id


def test_student_transfers_between_schools_keeping_record():
    """Transfert d'école (intra-tenant) : MÊME student_id re-pointé, l'historique suit."""
    s, org = _setup()
    ous = [DirOrgUnit("ou_a", "School A"), DirOrgUnit("ou_b", "School B")]

    def _one_user(ou):
        return DirectorySnapshot(ous, [DirUser("u_alice", "alice@school.edu", "Alice", ou)], [], [])

    sync_directory(s, org, _one_user("ou_a"), classifier=_classifier_by_id, now=NOW); s.commit()
    st_id = _student_of(s, "alice@school.edu").id
    school_a = s.execute(select(School).where(School.external_ref == "ou_a")).scalar_one().id

    sync_directory(s, org, _one_user("ou_b"), classifier=_classifier_by_id, now=NOW); s.commit()
    st = _student_of(s, "alice@school.edu")
    school_b = s.execute(select(School).where(School.external_ref == "ou_b")).scalar_one().id
    assert st.id == st_id and st.school_id == school_b and st.school_id != school_a


def test_rostering_adopts_bootstrap_account():
    """L'IT admin créé à l'onboarding (sans external_ref) est ADOPTÉ, pas dupliqué."""
    s, org = _setup()  # 'it@school.edu' existe déjà (bootstrap, external_ref=None)
    snap = DirectorySnapshot(
        [DirOrgUnit("ou_elem", "Students")],
        [DirUser("g_it", "it@school.edu", "IT Admin", "ou_elem", is_admin=True)],
        [], [],
    )
    sync_directory(s, org, snap, now=NOW); s.commit()  # classifieur par défaut (is_admin → IT_ADMIN)
    accounts = s.execute(select(AppUser).where(AppUser.email == "it@school.edu")).scalars().all()
    assert len(accounts) == 1 and accounts[0].external_ref == "g_it"   # adopté, pas de doublon


def _foreign_accounts(s):
    """Comptes HORS tenant : un prof d'un autre tenant + un super_admin vendor (sans org)."""
    other = Organization(name="Other", domain="other.edu"); s.add(other); s.flush()
    victim = AppUser(email="victim@other.edu", external_ref="o_victim")
    sa = AppUser(email="root@vendor.io", is_active=False)   # offboardé
    s.add_all([victim, sa]); s.flush()
    s.add(Membership(user_id=victim.id, role=Role.TEACHER, organization_id=other.id))
    s.add(Membership(user_id=sa.id, role=Role.SUPER_ADMIN))
    s.commit()
    return victim, sa


def _snap_one(ext_id, email):
    return DirectorySnapshot([DirOrgUnit("ou_elem", "Elementary")],
                             [DirUser(ext_id, email, "X", "ou_elem")], [], [])


def _teacher(u, ou_by_id):
    return Role.TEACHER


def test_sync_never_adopts_foreign_or_vendor_account():
    """Une sync ne réécrit JAMAIS un compte d'un autre tenant / vendor, ni ne lui ajoute de rôle."""
    s, org = _setup()
    victim, sa = _foreign_accounts(s)
    for i, target in enumerate((victim, sa)):
        before = (target.email, target.external_ref, target.is_active, target.deleted_at)
        n_memberships = len(s.execute(select(Membership).where(Membership.user_id == target.id)).all())
        # 1) email de la victime (+ id réutilisé de la victime), 2) même id avec un nouvel email
        atk = f"atk_{i}"
        for snap in (_snap_one(atk, target.email), _snap_one("o_victim", target.email),
                     _snap_one(atk, f"attacker{i}@school.edu")):
            run = sync_directory(s, org, snap, classifier=_teacher, now=NOW); s.commit()
            s.refresh(target)
            assert (target.email, target.external_ref, target.is_active, target.deleted_at) == before
            assert len(s.execute(select(Membership).where(Membership.user_id == target.id)
                                 ).all()) == n_memberships
        assert run.error_count == 0  # le dernier snapshot crée simplement un compte local
    assert victim.email == "victim@other.edu" and sa.email == "root@vendor.io"


def test_foreign_match_is_reported_as_error():
    s, org = _setup()
    victim, _ = _foreign_accounts(s)
    run = sync_directory(s, org, _snap_one("atk_1", victim.email), classifier=_teacher, now=NOW)
    assert run.error_count == 1 and run.status == "error"


def test_guardian_never_adopts_foreign_account():
    s, org = _setup()
    victim, sa = _foreign_accounts(s)
    snap = _with_guardians([DirGuardian("u_alice", victim.email, "V", "grd1"),
                            DirGuardian("u_bob", sa.email, "S", "grd2")])
    run = sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()
    s.refresh(victim); s.refresh(sa)
    assert run.error_count == 2
    assert victim.external_ref == "o_victim" and sa.external_ref is None and sa.is_active is False
    assert s.execute(select(ParentStudent)).scalars().all() == []
    assert Role.PARENT not in build_user_context(s, victim.id).roles


def test_email_fallback_requires_org_domain():
    """Repli email réservé au domaine vérifié du tenant : hors domaine → erreur, compte intact."""
    s, org = _setup()
    off = AppUser(email="it@elsewhere.io"); s.add(off); s.flush()
    s.add(Membership(user_id=off.id, role=Role.IT_ADMIN, organization_id=org.id)); s.commit()
    run = sync_directory(s, org, _snap_one("atk_1", "it@elsewhere.io"), classifier=_teacher, now=NOW)
    s.commit(); s.refresh(off)
    assert run.error_count == 1 and off.external_ref is None


def test_shared_account_leaving_org_loses_org_access_only():
    """Compte partagé (prof ici, parent ailleurs) : présent → pas retiré ; absent → accès `org`
    retiré (membership, classes) sans toucher l'AppUser global ni l'autre tenant."""
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()
    carol = s.execute(select(AppUser).where(AppUser.email == "carol@school.edu")).scalar_one()
    other = Organization(name="Other", domain="other.edu"); s.add(other); s.flush()
    s.add(Membership(user_id=carol.id, role=Role.PARENT, organization_id=other.id)); s.commit()

    run = sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()
    assert run.error_count == 1                       # signalé, compte non réécrit…
    assert s.execute(select(Membership).where(Membership.user_id == carol.id,
                                              Membership.organization_id == org.id)).first()
    assert s.execute(select(TeacherClassroom).where(TeacherClassroom.user_id == carol.id)
                     ).first() is not None            # …et ses classes dans `org` restent

    b = _base_snapshot()
    gone = DirectorySnapshot(b.org_units, [u for u in b.users if u.external_id != "u_carol"],
                             b.groups, [m for m in b.memberships if m.user_external_id != "u_carol"])
    sync_directory(s, org, gone, classifier=_classifier, now=NOW, force=True); s.commit()
    s.refresh(carol)
    assert carol.is_active and carol.deleted_at is None and carol.email == "carol@school.edu"
    roles = [(m.role, m.organization_id) for m in
             s.execute(select(Membership).where(Membership.user_id == carol.id)).scalars()]
    assert roles == [(Role.PARENT, other.id)]
    assert s.execute(select(TeacherClassroom).where(TeacherClassroom.user_id == carol.id)).first() is None


def test_suspended_shared_account_loses_org_access():
    """Compte partagé SUSPENDU dans l'annuaire : non réécrit, mais son accès à `org` est retiré."""
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier, now=NOW); s.commit()
    carol = s.execute(select(AppUser).where(AppUser.email == "carol@school.edu")).scalar_one()
    other = Organization(name="Other", domain="other.edu"); s.add(other); s.flush()
    s.add(Membership(user_id=carol.id, role=Role.PARENT, organization_id=other.id)); s.commit()

    b = _base_snapshot()
    users = [DirUser(u.external_id, u.email, u.full_name, u.org_unit_external_id,
                     suspended=(u.external_id == "u_carol")) for u in b.users]
    sync_directory(s, org, DirectorySnapshot(b.org_units, users, b.groups, b.memberships),
                   classifier=_classifier, now=NOW, force=True); s.commit()
    s.refresh(carol)
    assert carol.is_active and carol.deleted_at is None          # AppUser global intact
    ctx = build_user_context(s, carol.id)
    assert Role.TEACHER not in ctx.roles and org.id not in ctx.org_ids and not ctx.classroom_ids


def _share_with_other_org(s, email, role=Role.PARENT):
    au = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    other = Organization(name="Other", domain="other.edu"); s.add(other); s.flush()
    s.add(Membership(user_id=au.id, role=role, organization_id=other.id)); s.commit()
    return au, other


def test_shared_account_email_change_does_not_duplicate_identity():
    s, org = _setup()
    sync_directory(s, org, _base_snapshot(), classifier=_classifier_by_id, now=NOW); s.commit()
    _share_with_other_org(s, "carol@school.edu")
    b = _base_snapshot()
    renamed = [DirUser("u_carol", "carol.new@school.edu", "Carol", "ou_elem")
               if u.external_id == "u_carol" else u for u in b.users]
    run = sync_directory(s, org, DirectorySnapshot(b.org_units, renamed, b.groups, b.memberships),
                         classifier=_classifier_by_id, now=NOW); s.commit()
    assert run.error_count == 1
    assert len(s.execute(select(AppUser).where(AppUser.external_ref == "u_carol")).all()) == 1


def test_shared_student_keeps_guardian_links_and_parent():
    s, org = _setup()
    snap = _with_guardians([DirGuardian("u_alice", "mom@home.com", "Mom", "grd1")])
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()
    _share_with_other_org(s, "alice@school.edu", Role.STUDENT)
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()
    mom = s.execute(select(AppUser).where(AppUser.email == "mom@home.com")).scalar_one()
    assert mom.is_active and mom.deleted_at is None
    assert s.get(ParentStudent, (mom.id, _student_of(s, "alice@school.edu").id)) is not None


def test_detached_shared_parent_loses_child_links():
    s, org = _setup()
    sync_directory(s, org, _with_guardians([DirGuardian("u_alice", "mom@home.com", "Mom", "grd1")]),
                   classifier=_classifier, now=NOW); s.commit()
    mom, _ = _share_with_other_org(s, "mom@home.com")
    sync_directory(s, org, _with_guardians([]), classifier=_classifier, now=NOW, force=True); s.commit()
    assert mom.is_active and not build_user_context(s, mom.id).child_student_ids


def test_suspended_shared_manual_account_loses_org_access():
    """Compte manuel (sans external_ref) partagé avec un autre tenant et SUSPENDU dans l'annuaire :
    il échappe à `org_users` mais doit quand même perdre son accès à `org`."""
    s, org = _setup()
    t = AppUser(email="t@school.edu"); s.add(t); s.flush()
    other = Organization(name="Other", domain="other.edu"); s.add(other); s.flush()
    s.add_all([Membership(user_id=t.id, role=Role.TEACHER, organization_id=org.id),
               Membership(user_id=t.id, role=Role.PARENT, organization_id=other.id)]); s.commit()
    snap = DirectorySnapshot([DirOrgUnit("ou_elem", "Elementary")],
                             [DirUser("g_t", "t@school.edu", "T", "ou_elem", suspended=True)], [], [])
    sync_directory(s, org, snap, classifier=_teacher, now=NOW, force=True); s.commit()
    s.refresh(t)
    assert t.is_active and t.external_ref is None                 # AppUser global intact
    assert org.id not in build_user_context(s, t.id).org_ids


def _active_students(s):
    return s.execute(select(func.count()).select_from(Student)
                     .where(Student.deleted_at.is_(None))).scalar()


def test_mass_deprovision_is_blocked_then_approved():
    """Garde-fou : un départ massif (glitch / bascule d'année) est retenu jusqu'à approbation."""
    s, org = _setup()
    big = DirectorySnapshot([DirOrgUnit("ou_s", "Students")],
                            [DirUser(f"u{i}", f"s{i}@school.edu", f"S{i}", "ou_s") for i in range(12)],
                            [], [])
    sync_directory(s, org, big, now=NOW); s.commit()
    assert _active_students(s) == 12

    # ne reste qu'1 ancien + 1 NOUVEL arrivant → 11 partiraient (>25 %, ≥8) → BLOQUÉ
    blocked_snap = DirectorySnapshot([DirOrgUnit("ou_s", "Students")], [
        DirUser("u0", "s0@school.edu", "S0", "ou_s"),
        DirUser("u_new", "new@school.edu", "New", "ou_s"),
    ], [], [])
    run = sync_directory(s, org, blocked_snap, now=NOW); s.commit()
    assert run.status == "blocked" and run.pending_deactivations == 11
    assert _active_students(s) == 13                      # rien désactivé (fail-safe)…
    assert s.execute(select(AppUser).where(AppUser.email == "new@school.edu")
                     ).scalar_one_or_none() is not None    # …mais l'arrivée EST appliquée

    # approbation explicite → on applique les retraits
    run2 = sync_directory(s, org, blocked_snap, now=NOW, force=True); s.commit()
    assert run2.status == "ok" and run2.deactivated_count == 11
    assert _active_students(s) == 2                        # u0 + new


def test_normal_departure_not_blocked():
    """Un départ isolé (sous le seuil) passe sans blocage."""
    s, org = _setup()
    base = _base_snapshot()
    sync_directory(s, org, base, classifier=_classifier, now=NOW); s.commit()
    # Bob part (1 sur ~3 classés, mais < floor=8) → pas de blocage
    snap = DirectorySnapshot(base.org_units,
                             [u for u in base.users if u.external_id != "u_bob"],
                             base.groups,
                             [m for m in base.memberships if m.user_external_id != "u_bob"])
    run = sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()
    assert run.status == "ok" and run.pending_deactivations == 0 and run.deactivated_count == 1


def test_unclassified_user_is_ignored():
    s, org = _setup()
    snap = _base_snapshot()
    snap = DirectorySnapshot(
        snap.org_units,
        snap.users + [DirUser("u_x", "ghost@school.edu", "Ghost", "ou_elem")],
        snap.groups, snap.memberships,
    )
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()
    assert s.execute(
        select(AppUser).where(AppUser.email == "ghost@school.edu")
    ).scalar_one_or_none() is None


def test_single_school_fallback_without_orgunits():
    s, org = _setup()
    base = _base_snapshot()
    snap = DirectorySnapshot([], base.users, base.groups, base.memberships)  # aucune OU
    sync_directory(s, org, snap, classifier=_classifier, now=NOW); s.commit()

    school = s.execute(select(School).where(School.external_ref == "__default__")).scalar_one()
    assert school.name == "Demo School"
    cls = s.execute(select(Classroom).where(Classroom.external_ref == "g_4a")).scalar_one()
    assert cls.school_id == school.id


def test_default_classifier_uses_orgunit_hints():
    ou_by_id = {
        "s": DirOrgUnit("s", "Students 2026"),
        "t": DirOrgUnit("t", "Teaching Staff"),
        "x": DirOrgUnit("x", "Contractors"),
    }
    assert classify_role(DirUser("1", "a@x.io", "A", "s"), ou_by_id) == Role.STUDENT
    assert classify_role(DirUser("2", "b@x.io", "B", "t"), ou_by_id) == Role.TEACHER
    assert classify_role(DirUser("3", "c@x.io", "C", "x"), ou_by_id) is None
    assert classify_role(DirUser("4", "d@x.io", "D", "x", is_admin=True), ou_by_id) == Role.IT_ADMIN


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
