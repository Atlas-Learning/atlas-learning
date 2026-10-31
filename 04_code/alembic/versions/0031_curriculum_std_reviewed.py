"""curriculum_standard.reviewed_at — attendu revu sans correspondance (refonte C2)

La publication d'un framework exige que chaque attendu soit revu : soit toutes ses lignes de
mapping sont validées, soit le relecteur l'a marqué « sans correspondance » (`reviewed_at`).

Revision ID: 0031_curriculum_std_reviewed
Revises: 0030_curriculum_framework_table
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_curriculum_std_reviewed"
down_revision: Union[str, None] = "0030_curriculum_framework_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("curriculum_standard") as batch:
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("curriculum_standard") as batch:
        batch.drop_column("reviewed_at")
