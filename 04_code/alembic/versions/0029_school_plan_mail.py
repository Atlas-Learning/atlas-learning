"""school : réglages du message hebdomadaire « votre plan est prêt » (refonte B6, Q5)

Par école (décision 2026-10-31) : `country` (ISO2), `plan_mail_weekday` (0 = lundi … 6 =
dimanche), `plan_mail_hour` (heure locale), `timezone` (IANA). Tout nullable : NULL = défaut
dérivé du pays (dimanche 7 h en Arabie saoudite, lundi 7 h ailleurs, fuseau du pays sinon UTC).

Revision ID: 0029_school_plan_mail
Revises: 0028_mini_lesson
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_school_plan_mail"
down_revision: Union[str, None] = "0028_mini_lesson"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("school") as batch:
        batch.add_column(sa.Column("country", sa.String(length=2), nullable=True))
        batch.add_column(sa.Column("plan_mail_weekday", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("plan_mail_hour", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("timezone", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("school") as batch:
        for col in ("timezone", "plan_mail_hour", "plan_mail_weekday", "country"):
            batch.drop_column(col)
