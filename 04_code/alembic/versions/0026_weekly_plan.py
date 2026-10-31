"""weekly_plan, plan_action, plan_action_member, proof (refonte B2/B4, « 0026 » du spec)

Plan hebdomadaire d'une classe généré à la clôture d'un check-in `full`, ses actions (groupe
d'élèves + cause racine + compétence bloquée + phrase « parce que »), ses membres et les
preuves par élève (B4). Pose aussi la FK `checkin.plan_action_id → plan_action.id` (SET NULL),
différée depuis 0025. `plan_action.lesson_id` reste sans FK (table mini_lesson en B3).

Enums créés explicitement sur Postgres (pattern 0019). Downgrade complet.

Revision ID: 0026_weekly_plan
Revises: 0025_checkin
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_weekly_plan"
down_revision: Union[str, None] = "0025_checkin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUMS = {
    "plan_status": ("active", "superseded"),
    "plan_action_kind": ("reteach", "recheck"),
    "plan_confidence": ("measured", "partly_estimated"),
    "plan_action_status": ("proposed", "done", "dismissed"),
    "member_source": ("atlas", "teacher_added"),
    "proof_outcome": ("unlocked", "unchanged", "not_rechecked"),
}


def _enum(name: str, is_pg: bool) -> sa.types.TypeEngine:
    if is_pg:
        return postgresql.ENUM(name=name, create_type=False)
    return sa.Enum(*ENUMS[name], name=name)


def upgrade() -> None:
    from alembic import context

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        if context.is_offline_mode():
            for name, values in ENUMS.items():
                vals = ", ".join(f"''{v}''" for v in values)
                op.execute(f"DO 'BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
                           f"EXCEPTION WHEN duplicate_object THEN NULL; END'")
        else:
            for name, values in ENUMS.items():
                sa.Enum(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "weekly_plan",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("source_checkin_id", sa.Uuid(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", _enum("plan_status", is_pg), nullable=False, server_default="active"),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="CASCADE", name="fk_weekly_plan_school"),
        sa.ForeignKeyConstraint(["classroom_id"], ["classroom.id"], ondelete="CASCADE", name="fk_weekly_plan_classroom"),
        sa.ForeignKeyConstraint(["source_checkin_id"], ["checkin.id"], ondelete="SET NULL", name="fk_weekly_plan_checkin"),
    )
    for col in ("school_id", "classroom_id", "week_start", "status"):
        op.create_index(f"ix_weekly_plan_{col}", "weekly_plan", [col])

    op.create_table(
        "plan_action",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum("plan_action_kind", is_pg), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("root_cause_competency_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_competency_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("confidence", _enum("plan_confidence", is_pg), nullable=False),
        sa.Column("because_en", sa.Text(), nullable=False),
        sa.Column("because_ar", sa.Text(), nullable=False),
        sa.Column("status", _enum("plan_action_status", is_pg), nullable=False, server_default="proposed"),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["weekly_plan.id"], ondelete="CASCADE", name="fk_plan_action_plan"),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="CASCADE", name="fk_plan_action_school"),
        sa.ForeignKeyConstraint(["root_cause_competency_id"], ["competency.id"], ondelete="RESTRICT", name="fk_plan_action_root"),
        sa.ForeignKeyConstraint(["blocked_competency_id"], ["competency.id"], ondelete="RESTRICT", name="fk_plan_action_blocked"),
    )
    op.create_index("ix_plan_action_plan_id", "plan_action", ["plan_id"])
    op.create_index("ix_plan_action_school_id", "plan_action", ["school_id"])

    op.create_table(
        "plan_action_member",
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("source", _enum("member_source", is_pg), nullable=False, server_default="atlas"),
        sa.Column("removed_by_teacher", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("observed_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["action_id"], ["plan_action.id"], ondelete="CASCADE", name="fk_pam_action"),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE", name="fk_pam_student"),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="CASCADE", name="fk_pam_school"),
        sa.PrimaryKeyConstraint("action_id", "student_id"),
    )
    op.create_index("ix_plan_action_member_school_id", "plan_action_member", ["school_id"])

    op.create_table(
        "proof",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("competency_id", sa.Uuid(), nullable=False),
        sa.Column("before_elo", sa.Float(), nullable=False),
        sa.Column("before_confidence", sa.Float(), nullable=False),
        sa.Column("after_elo", sa.Float(), nullable=True),
        sa.Column("after_confidence", sa.Float(), nullable=True),
        sa.Column("ci_low", sa.Float(), nullable=True),
        sa.Column("ci_high", sa.Float(), nullable=True),
        sa.Column("outcome", _enum("proof_outcome", is_pg), nullable=False, server_default="not_rechecked"),
        sa.Column("recheck_checkin_id", sa.Uuid(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["plan_action.id"], ondelete="CASCADE", name="fk_proof_action"),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE", name="fk_proof_student"),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="CASCADE", name="fk_proof_school"),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"], ondelete="RESTRICT", name="fk_proof_competency"),
        sa.ForeignKeyConstraint(["recheck_checkin_id"], ["checkin.id"], ondelete="SET NULL", name="fk_proof_checkin"),
    )
    for col in ("action_id", "student_id", "school_id"):
        op.create_index(f"ix_proof_{col}", "proof", [col])

    # FK différée depuis 0025 : un check-in ciblé pointe l'action du plan qu'il re-mesure.
    with op.batch_alter_table("checkin") as batch:
        batch.create_foreign_key("fk_checkin_plan_action", "plan_action", ["plan_action_id"], ["id"],
                                 ondelete="SET NULL")


def downgrade() -> None:
    from alembic import context

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    with op.batch_alter_table("checkin") as batch:
        batch.drop_constraint("fk_checkin_plan_action", type_="foreignkey")
    for col in ("school_id", "student_id", "action_id"):
        op.drop_index(f"ix_proof_{col}", table_name="proof")
    op.drop_table("proof")
    op.drop_index("ix_plan_action_member_school_id", table_name="plan_action_member")
    op.drop_table("plan_action_member")
    op.drop_index("ix_plan_action_school_id", table_name="plan_action")
    op.drop_index("ix_plan_action_plan_id", table_name="plan_action")
    op.drop_table("plan_action")
    for col in ("status", "week_start", "classroom_id", "school_id"):
        op.drop_index(f"ix_weekly_plan_{col}", table_name="weekly_plan")
    op.drop_table("weekly_plan")
    if is_pg:
        if context.is_offline_mode():
            for name in ENUMS:
                op.execute(f"DROP TYPE IF EXISTS {name}")
        else:
            for name in ENUMS:
                sa.Enum(name=name).drop(bind, checkfirst=True)
