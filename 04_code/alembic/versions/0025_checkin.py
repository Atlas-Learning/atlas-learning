"""checkin — sessions de classe par code (refonte B1, « 0025 » du spec)

Table `checkin` (école, classe, auteur, kind full|targeted, action du plan (FK en B2),
compétences visées, restriction aux membres, code à 4 chiffres, statut, horodatages) et
`assessment_session.checkin_id` (FK SET NULL, indexé) : une session d'élève rejoint au plus un
check-in. Enums créés explicitement sur Postgres (pattern 0019). Downgrade complet.

Revision ID: 0025_checkin
Revises: 0024_role_content_reviewer
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_checkin"
down_revision: Union[str, None] = "0024_role_content_reviewer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUMS = {
    "checkin_kind": ("full", "targeted"),
    "checkin_status": ("scheduled", "open", "closed"),
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
        "checkin",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("kind", _enum("checkin_kind", is_pg), nullable=False),
        sa.Column("plan_action_id", sa.Uuid(), nullable=True),
        sa.Column("competency_ids", sa.JSON(), nullable=True),
        sa.Column("student_ids", sa.JSON(), nullable=True),
        sa.Column("code", sa.String(length=4), nullable=False),
        sa.Column("status", _enum("checkin_status", is_pg), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="CASCADE", name="fk_checkin_school"),
        sa.ForeignKeyConstraint(["classroom_id"], ["classroom.id"], ondelete="CASCADE", name="fk_checkin_classroom"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="SET NULL", name="fk_checkin_created_by"),
    )
    op.create_index("ix_checkin_school_id", "checkin", ["school_id"])
    op.create_index("ix_checkin_classroom_id", "checkin", ["classroom_id"])
    op.create_index("ix_checkin_code", "checkin", ["code"])
    op.create_index("ix_checkin_status", "checkin", ["status"])

    with op.batch_alter_table("assessment_session") as batch:
        batch.add_column(sa.Column("checkin_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_assessment_session_checkin", "checkin", ["checkin_id"], ["id"],
                                 ondelete="SET NULL")
    op.create_index("ix_assessment_session_checkin_id", "assessment_session", ["checkin_id"])


def downgrade() -> None:
    from alembic import context

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.drop_index("ix_assessment_session_checkin_id", table_name="assessment_session")
    with op.batch_alter_table("assessment_session") as batch:
        batch.drop_constraint("fk_assessment_session_checkin", type_="foreignkey")
        batch.drop_column("checkin_id")
    for ix in ("ix_checkin_status", "ix_checkin_code", "ix_checkin_classroom_id", "ix_checkin_school_id"):
        op.drop_index(ix, table_name="checkin")
    op.drop_table("checkin")
    if is_pg:
        if context.is_offline_mode():
            for name in ENUMS:
                op.execute(f"DROP TYPE IF EXISTS {name}")
        else:
            for name in ENUMS:
                sa.Enum(name=name).drop(bind, checkfirst=True)
