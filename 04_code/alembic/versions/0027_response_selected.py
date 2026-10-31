"""response.selected — option choisie par l'élève (refonte B2, Q16)

Sans l'option choisie, aucune analyse des distracteurs n'est possible : l'« erreur observée »
d'un membre du plan (ex. « 1/3 + 1/6 = 2/9 on 3 of 4 items ») en dépend. Colonne nullable :
les réponses antérieures restent sans option (pas de backfill possible). Hors numérotation du
spec (ajoutée pour Q16) : le « 0027 » du spec (mini_lesson) devient 0028.

Revision ID: 0027_response_selected
Revises: 0026_weekly_plan
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_response_selected"
down_revision: Union[str, None] = "0026_weekly_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("response") as batch:
        batch.add_column(sa.Column("selected", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("response") as batch:
        batch.drop_column("selected")
