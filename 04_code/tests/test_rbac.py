"""Tests Epic 6 — RBAC (T6.2) + auth minimal (T6.3)."""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from src.db import make_engine
from src.models.base import Base, Role
# importe tous les modules de modèles pour enregistrer les tables (FK cross-module)
from src.models import competency as _c, item as _i, measurement as _m, session as _se, org as _o  # noqa: F401
from src.models.measurement import School, Student
from src.models.org import AppUser, Membership, ParentStudent, TeacherClassroom
from src.rbac.auth import make_token, parse_token
from src.rbac.authz import (
    UserContext,
    build_user_context,
    can_access_classroom,
    can_access_school,
    can_access_student,
)

SCHOOL_A, SCHOOL_B = uuid.uuid4(), uuid.uuid4()
CLASS_1, CLASS_2 = uuid.uuid4(), uuid.uuid4()
CHILD, OTHER = uuid.uuid4(), uuid.uuid4()


# ---------- T6.2 RBAC ----------

def test_ac1_parent_cannot_access_other_child():
    parent = UserContext(uuid.uuid4(), roles=frozenset({Role.PARENT}), child_student_ids=frozenset({CHILD}))
    assert can_access_student(parent, CHILD, SCHOOL_A, {CLASS_1}) is True
    assert can_access_student(parent, OTHER, SCHOOL_A, {CLASS_1}) is False   # autre enfant → refus


def test_ac2_teacher_cannot_access_other_class():
    teacher = UserContext(uuid.uuid4(), roles=frozenset({Role.TEACHER}), classroom_ids=frozenset({CLASS_1}))
    assert can_access_classroom(teacher, CLASS_1, SCHOOL_A) is True
    assert can_access_classroom(teacher, CLASS_2, SCHOOL_A) is False       # pas sa classe → refus


def test_ac3_student_only_own_activities():
    student = UserContext(uuid.uuid4(), roles=frozenset({Role.STUDENT}), own_student_id=CHILD)
    assert can_access_student(student, CHILD, SCHOOL_A, {CLASS_1}) is True
    assert can_access_student(student, OTHER, SCHOOL_A, {CLASS_1}) is False


def test_teacher_access_student_via_any_shared_class():
    """Élève multi-classes : le prof y accède s'il partage AU MOINS une classe."""
    teacher = UserContext(uuid.uuid4(), roles=frozenset({Role.TEACHER}),
                          classroom_ids=frozenset({CLASS_1}))
    # élève en CLASS_2 (principale) + CLASS_1 (spécialité du prof) → accès
    assert can_access_student(teacher, CHILD, SCHOOL_A, {CLASS_2, CLASS_1}) is True
    # élève seulement en CLASS_2 → refus
    assert can_access_student(teacher, CHILD, SCHOOL_A, {CLASS_2}) is False


def test_ac4_ped_admin_tenant_isolation():
    admin = UserContext(uuid.uuid4(), roles=frozenset({Role.PED_ADMIN}), school_ids=frozenset({SCHOOL_A}))
    assert can_access_school(admin, SCHOOL_A) is True
    assert can_access_school(admin, SCHOOL_B) is False                     # autre établissement → refus
    assert can_access_student(admin, CHILD, SCHOOL_A, {CLASS_1}) is True
    assert can_access_student(admin, CHILD, SCHOOL_B, {CLASS_1}) is False


def test_super_admin_sees_all():
    su = UserContext(uuid.uuid4(), roles=frozenset({Role.SUPER_ADMIN}))
    assert can_access_school(su, SCHOOL_B) is True
    assert can_access_student(su, OTHER, SCHOOL_B, {CLASS_2}) is True


def test_build_user_context_from_db():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    school = School(name="A"); s.add(school); s.flush()
    teacher = AppUser(email="t@x.io"); s.add(teacher); s.flush()
    from src.models.org import Classroom
    cls = Classroom(school_id=school.id, name="4A"); s.add(cls); s.flush()
    s.add(Membership(user_id=teacher.id, role=Role.TEACHER, school_id=school.id))
    s.add(TeacherClassroom(user_id=teacher.id, classroom_id=cls.id))
    s.commit()
    ctx = build_user_context(s, teacher.id)
    assert Role.TEACHER in ctx.roles
    assert cls.id in ctx.classroom_ids
    assert school.id not in ctx.school_ids   # périmètre admin uniquement


def test_admin_role_bound_to_its_own_membership_scope():
    """PED_ADMIN de S1 (ou IT_ADMIN org-only) + TEACHER de S2 : aucune portée admin sur S2."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    from src.models.org import Classroom, Organization
    org = Organization(name="D"); s.add(org); s.flush()
    s1, s2 = School(name="S1"), School(name="S2"); s.add_all([s1, s2]); s.flush()
    own, other = Classroom(school_id=s2.id, name="own"), Classroom(school_id=s2.id, name="other")
    s.add_all([own, other]); s.flush()
    ped = AppUser(email="ped@x.io"); it = AppUser(email="it@x.io"); s.add_all([ped, it]); s.flush()
    s.add_all([
        Membership(user_id=ped.id, role=Role.PED_ADMIN, school_id=s1.id),
        Membership(user_id=ped.id, role=Role.TEACHER, school_id=s2.id),
        TeacherClassroom(user_id=ped.id, classroom_id=own.id),
        Membership(user_id=it.id, role=Role.IT_ADMIN, organization_id=org.id),
        Membership(user_id=it.id, role=Role.TEACHER, school_id=s2.id),
        TeacherClassroom(user_id=it.id, classroom_id=own.id),
    ])
    s.commit()
    ped_ctx = build_user_context(s, ped.id)
    assert can_access_school(ped_ctx, s1.id) is True
    for ctx in (ped_ctx, build_user_context(s, it.id)):
        assert can_access_school(ctx, s2.id) is False
        assert can_access_classroom(ctx, other.id, s2.id) is False
        assert can_access_student(ctx, CHILD, s2.id, {other.id}) is False
        assert can_access_classroom(ctx, own.id, s2.id) is True        # garde l'accès enseignant
        assert can_access_student(ctx, CHILD, s2.id, {own.id}) is True


# ---------- Refonte A1 — dept_lead (école + niveaux) et group_admin (organisation) ----------

from src.models.org import DeptLeadScope  # noqa: E402
from src.rbac.authz import can_manage_school, can_review_department  # noqa: E402

CLASS_G4, CLASS_G5, CLASS_NOGRADE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_dept_lead_reads_only_classes_of_its_grades():
    """Un dept_lead lit les classes de ses niveaux dans son école — et rien d'autre."""
    lead = UserContext(uuid.uuid4(), roles=frozenset({Role.DEPT_LEAD}),
                       dept_scopes=frozenset({(SCHOOL_A, 4)}),
                       dept_classroom_ids=frozenset({CLASS_G4}))
    assert can_access_classroom(lead, CLASS_G4, SCHOOL_A) is True
    assert can_access_classroom(lead, CLASS_G5, SCHOOL_A) is False      # autre niveau, même école
    assert can_access_classroom(lead, CLASS_1, SCHOOL_B) is False       # autre école
    # élève : via une classe couverte seulement
    assert can_access_student(lead, CHILD, SCHOOL_A, {CLASS_G4, CLASS_G5}) is True
    assert can_access_student(lead, CHILD, SCHOOL_A, {CLASS_G5}) is False
    # aucune portée école (overview/proof école = direction), aucune administration
    assert can_access_school(lead, SCHOOL_A) is False
    assert can_manage_school(lead, SCHOOL_A) is False
    # revue de département : son niveau dans son école uniquement ; classe sans niveau → jamais
    assert can_review_department(lead, SCHOOL_A, 4) is True
    assert can_review_department(lead, SCHOOL_A, 5) is False
    assert can_review_department(lead, SCHOOL_B, 4) is False
    assert can_review_department(lead, SCHOOL_A, None) is False


def test_group_admin_reads_all_schools_of_its_org_and_nothing_else():
    ga = UserContext(uuid.uuid4(), roles=frozenset({Role.GROUP_ADMIN}),
                     org_ids=frozenset({uuid.uuid4()}),
                     group_school_ids=frozenset({SCHOOL_A}))
    assert can_access_school(ga, SCHOOL_A) is True
    assert can_access_school(ga, SCHOOL_B) is False                     # école hors organisation
    assert can_manage_school(ga, SCHOOL_A) is False                     # lecture, pas d'administration
    # aucune portée classe ni élève nominatif (matrice d'accès : la direction voit des écoles)
    assert can_access_classroom(ga, CLASS_1, SCHOOL_A) is False
    assert can_access_student(ga, CHILD, SCHOOL_A, {CLASS_1}) is False
    assert can_review_department(ga, SCHOOL_A, 4) is False


def test_build_user_context_resolves_dept_lead_scope_and_group_schools():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    from src.models.org import Classroom, Organization
    org, other_org = Organization(name="Groupe"), Organization(name="Autre")
    s.add_all([org, other_org]); s.flush()
    s1 = School(name="S1", organization_id=org.id)
    s2 = School(name="S2", organization_id=org.id)
    s3 = School(name="S3", organization_id=other_org.id)
    gone = School(name="fermée", organization_id=org.id, deleted_at=datetime.now(timezone.utc))
    s.add_all([s1, s2, s3, gone]); s.flush()
    g4a = Classroom(school_id=s1.id, name="4A", grade=4)
    g4b = Classroom(school_id=s1.id, name="4B", grade=4)
    g5 = Classroom(school_id=s1.id, name="5A", grade=5)
    nograde = Classroom(school_id=s1.id, name="?", grade=None)
    g4_other_school = Classroom(school_id=s2.id, name="4C", grade=4)
    g4_deleted = Classroom(school_id=s1.id, name="4Z", grade=4, deleted_at=datetime.now(timezone.utc))
    s.add_all([g4a, g4b, g5, nograde, g4_other_school, g4_deleted]); s.flush()

    lead = AppUser(email="lead@x.io"); ga = AppUser(email="ga@x.io"); s.add_all([lead, ga]); s.flush()
    m = Membership(user_id=lead.id, role=Role.DEPT_LEAD, school_id=s1.id); s.add(m); s.flush()
    s.add_all([DeptLeadScope(membership_id=m.id, grade=4), DeptLeadScope(membership_id=m.id, grade=6)])
    s.add(Membership(user_id=ga.id, role=Role.GROUP_ADMIN, organization_id=org.id))
    s.commit()

    ctx = build_user_context(s, lead.id)
    assert ctx.dept_scopes == {(s1.id, 4), (s1.id, 6)}
    # classes vivantes de SON école aux niveaux couverts : ni 5A, ni sans niveau, ni l'autre
    # école, ni la classe supprimée
    assert ctx.dept_classroom_ids == {g4a.id, g4b.id}
    assert ctx.school_ids == frozenset()            # jamais de portée admin
    assert ctx.classroom_ids == frozenset()         # pas une portée enseignant non plus

    ctx = build_user_context(s, ga.id)
    assert ctx.group_school_ids == {s1.id, s2.id}   # toutes les écoles vivantes de l'org, pas S3
    assert can_access_school(ctx, s3.id) is False
    assert ctx.school_ids == frozenset()


def test_dept_lead_without_scope_rows_has_no_access():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    from src.models.org import Classroom
    sch = School(name="S"); s.add(sch); s.flush()
    cls = Classroom(school_id=sch.id, name="4A", grade=4); s.add(cls); s.flush()
    lead = AppUser(email="lead@x.io"); s.add(lead); s.flush()
    s.add(Membership(user_id=lead.id, role=Role.DEPT_LEAD, school_id=sch.id))   # aucun niveau
    s.commit()
    ctx = build_user_context(s, lead.id)
    assert ctx.dept_scopes == frozenset() and ctx.dept_classroom_ids == frozenset()
    assert can_access_classroom(ctx, cls.id, sch.id) is False


def test_group_admin_scope_not_widened_by_other_memberships():
    """GROUP_ADMIN de l'org A + IT_ADMIN de l'org B : les écoles de B ne deviennent pas lisibles
    comme group_admin, et l'école d'une membership teacher ne reçoit aucune portée."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    from src.models.org import Classroom, Organization
    oa, ob = Organization(name="A"), Organization(name="B"); s.add_all([oa, ob]); s.flush()
    sa_, sb = School(name="SA", organization_id=oa.id), School(name="SB", organization_id=ob.id)
    s.add_all([sa_, sb]); s.flush()
    cls_b = Classroom(school_id=sb.id, name="4A", grade=4); s.add(cls_b); s.flush()
    u = AppUser(email="u@x.io"); s.add(u); s.flush()
    s.add_all([
        Membership(user_id=u.id, role=Role.GROUP_ADMIN, organization_id=oa.id),
        Membership(user_id=u.id, role=Role.IT_ADMIN, organization_id=ob.id),   # org-only, sans école
        Membership(user_id=u.id, role=Role.TEACHER, school_id=sb.id),
    ])
    s.commit()
    ctx = build_user_context(s, u.id)
    assert ctx.group_school_ids == {sa_.id}
    assert can_access_school(ctx, sa_.id) is True
    assert can_access_school(ctx, sb.id) is False
    assert can_access_classroom(ctx, cls_b.id, sb.id) is False


# ---------- T6.3 auth (jetons de session signés — SSO uniquement) ----------

def test_token_roundtrip_and_tamper():
    uid = str(uuid.uuid4())
    tok = make_token(uid, ttl_s=100, now=1000)
    assert parse_token(tok, now=1050) == uid
    # falsification de signature
    try:
        parse_token(tok[:-1] + ("0" if tok[-1] != "0" else "1"), now=1050)
        assert False
    except ValueError:
        pass


def test_token_expiry():
    tok = make_token("u", ttl_s=100, now=1000)
    try:
        parse_token(tok, now=2000)   # expiré
        assert False
    except ValueError:
        pass


def test_token_purpose_isolation():
    """Un lien magique (purpose dédié) ne doit pas passer pour un jeton de session."""
    magic = make_token("u", purpose="admin_login", ttl_s=100, now=1000)
    assert parse_token(magic, purpose="admin_login", now=1050) == "u"
    try:
        parse_token(magic, purpose="session", now=1050)   # mauvais usage
        assert False
    except ValueError:
        pass


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
