"""mini_lesson (refonte B3, « 0027 » du spec) + FK plan_action.lesson_id

Table des mini-leçons bilingues (contenu éditorial seedé depuis data/lessons/*.json) et
contrainte différée depuis 0026 : `plan_action.lesson_id → mini_lesson.id` (SET NULL).
Enums créés explicitement sur Postgres (pattern 0019). Downgrade complet.

Revision ID: 0028_mini_lesson
Revises: 0027_response_selected
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_mini_lesson"
down_revision: Union[str, None] = "0027_response_selected"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUMS = {
    "lesson_origin": ("atlas", "school"),
    "lesson_status": ("draft", "linguist_validated", "active"),
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
        "mini_lesson",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("competency_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("title_en", sa.String(), nullable=False),
        sa.Column("title_ar", sa.String(), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("origin", _enum("lesson_origin", is_pg), nullable=False, server_default="atlas"),
        sa.Column("owner_school_id", sa.Uuid(), nullable=True),
        sa.Column("status", _enum("lesson_status", is_pg), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"], ondelete="RESTRICT", name="fk_mini_lesson_competency"),
        sa.ForeignKeyConstraint(["owner_school_id"], ["school.id"], ondelete="CASCADE", name="fk_mini_lesson_school"),
        sa.UniqueConstraint("key", name="uq_mini_lesson_key"),
    )
    op.create_index("ix_mini_lesson_competency_id", "mini_lesson", ["competency_id"])
    op.create_index("ix_mini_lesson_key", "mini_lesson", ["key"])
    op.create_index("ix_mini_lesson_status", "mini_lesson", ["status"])
    with op.batch_alter_table("plan_action") as batch:
        batch.create_foreign_key("fk_plan_action_lesson", "mini_lesson", ["lesson_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    from alembic import context

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    with op.batch_alter_table("plan_action") as batch:
        batch.drop_constraint("fk_plan_action_lesson", type_="foreignkey")
    for ix in ("ix_mini_lesson_status", "ix_mini_lesson_key", "ix_mini_lesson_competency_id"):
        op.drop_index(ix, table_name="mini_lesson")
    op.drop_table("mini_lesson")
    if is_pg:
        if context.is_offline_mode():
            for name in ENUMS:
                op.execute(f"DROP TYPE IF EXISTS {name}")
        else:
            for name in ENUMS:
                sa.Enum(name=name).drop(bind, checkfirst=True)
