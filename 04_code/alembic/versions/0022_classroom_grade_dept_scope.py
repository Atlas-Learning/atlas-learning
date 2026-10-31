"""classroom.grade + dept_lead_scope — portée du coordinateur maths (refonte, A1)

- `classroom.grade` (int, nullable, indexé) : niveau de la classe. Rempli par le roster quand
  la source l'expose (OneRoster `grades`), sinon saisi en admin. NULL = inconnu : une classe
  sans niveau n'entre dans la portée d'AUCUN dept_lead (jamais d'accès par défaut).
- `dept_lead_scope (membership_id FK membership CASCADE, grade)` : les niveaux couverts par
  une membership `dept_lead`. PK composite (une ligne par niveau).

ADD COLUMN nullable → portable SQLite/Postgres via batch (no-op passthrough sur PG).
Downgrade : chemin inverse complet (index, colonne, table) — aucune donnée élève concernée.

Revision ID: 0022_classroom_grade_dept_scope
Revises: 0021_role_dept_lead_group_admin
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_classroom_grade_dept_scope"
down_revision: Union[str, None] = "0021_role_dept_lead_group_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("classroom") as batch:
        batch.add_column(sa.Column("grade", sa.Integer(), nullable=True))
    op.create_index("ix_classroom_grade", "classroom", ["grade"])
    op.create_table(
        "dept_lead_scope",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["membership.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "grade"),
    )


def downgrade() -> None:
    op.drop_table("dept_lead_scope")
    op.drop_index("ix_classroom_grade", table_name="classroom")
    with op.batch_alter_table("classroom") as batch:
        batch.drop_column("grade")
