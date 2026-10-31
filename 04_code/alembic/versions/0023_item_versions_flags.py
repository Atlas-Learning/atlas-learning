"""item : origine, gabarit, versions, calibration ; table item_flag (refonte A2)

Colonnes `item` (docs/refonte/03-modele-de-donnees.md, « 0024 » du spec, décalé de −1 ici) :
- `origin` (enum item_origin : atlas_template | school, défaut atlas_template)
- `template_key` (str nullable, indexé) : gabarit d'origine, ex. `MATH.G4.NF.ADD_LIKE#03`.
  NULL pour la banque antérieure : regénérer (`generate_bank_deterministic.py --reset`).
- `version` (int, défaut 1), `supersedes_id` (FK item.id, SET NULL) : chaîne de versions.
- `calibration_reset_at` (timestamptz nullable) : les réponses antérieures ne pèsent plus.
- `owner_school_id` (FK school.id, CASCADE) : items d'école (phase E).

Table `item_flag` : signalement d'un item (enseignant, coordinateur, staff). Le signalement
n'altère pas le statut de l'item : l'acceptation passe par la machine à états de review.py.

DIALECTES (pattern 0019) : sur Postgres les types enum sont créés explicitement AVANT
(ADD COLUMN ne crée pas le type) et référencés en `create_type=False` ; sur SQLite,
native_enum = VARCHAR sans contrainte. Le batch recrée `item` sur SQLite (FK auto-référente) ;
sur Postgres il se réduit à des ALTER TABLE.

Revision ID: 0023_item_versions_flags
Revises: 0022_classroom_grade_dept_scope
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_item_versions_flags"
down_revision: Union[str, None] = "0022_classroom_grade_dept_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUMS = {
    "item_origin": ("atlas_template", "school"),
    "item_flag_reason": ("wrong_answer_key", "several_correct", "unclear_wording", "arabic", "other"),
    "item_flag_status": ("open", "accepted", "rejected"),
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
                op.execute(
                    f"DO 'BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
                    f"EXCEPTION WHEN duplicate_object THEN NULL; END'"
                )
        else:
            for name, values in ENUMS.items():
                sa.Enum(*values, name=name).create(bind, checkfirst=True)

    with op.batch_alter_table("item") as batch:
        batch.add_column(sa.Column("origin", _enum("item_origin", is_pg),
                                   nullable=False, server_default="atlas_template"))
        batch.add_column(sa.Column("template_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("supersedes_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("calibration_reset_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("owner_school_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_item_supersedes", "item", ["supersedes_id"], ["id"],
                                 ondelete="SET NULL")
        batch.create_foreign_key("fk_item_owner_school", "school", ["owner_school_id"], ["id"],
                                 ondelete="CASCADE")
    op.create_index("ix_item_template_key", "item", ["template_key"])
    op.create_index("ix_item_owner_school_id", "item", ["owner_school_id"])

    op.create_table(
        "item_flag",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=True),
        sa.Column("raised_by", sa.Uuid(), nullable=True),
        sa.Column("reason", _enum("item_flag_reason", is_pg), nullable=False),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("status", _enum("item_flag_status", is_pg), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"], ondelete="CASCADE", name="fk_item_flag_item"),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="SET NULL", name="fk_item_flag_school"),
        sa.ForeignKeyConstraint(["raised_by"], ["app_user.id"], ondelete="SET NULL", name="fk_item_flag_raised_by"),
        sa.ForeignKeyConstraint(["resolved_by"], ["app_user.id"], ondelete="SET NULL", name="fk_item_flag_resolved_by"),
    )
    op.create_index("ix_item_flag_item_id", "item_flag", ["item_id"])
    op.create_index("ix_item_flag_school_id", "item_flag", ["school_id"])
    op.create_index("ix_item_flag_status", "item_flag", ["status"])


def downgrade() -> None:
    from alembic import context

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.drop_index("ix_item_flag_status", table_name="item_flag")
    op.drop_index("ix_item_flag_school_id", table_name="item_flag")
    op.drop_index("ix_item_flag_item_id", table_name="item_flag")
    op.drop_table("item_flag")

    op.drop_index("ix_item_owner_school_id", table_name="item")
    op.drop_index("ix_item_template_key", table_name="item")
    with op.batch_alter_table("item") as batch:
        batch.drop_constraint("fk_item_owner_school", type_="foreignkey")
        batch.drop_constraint("fk_item_supersedes", type_="foreignkey")
        batch.drop_column("owner_school_id")
        batch.drop_column("calibration_reset_at")
        batch.drop_column("supersedes_id")
        batch.drop_column("version")
        batch.drop_column("template_key")
        batch.drop_column("origin")

    if is_pg:
        if context.is_offline_mode():
            for name in ENUMS:
                op.execute(f"DROP TYPE IF EXISTS {name}")
        else:
            for name in ENUMS:
                sa.Enum(name=name).drop(bind, checkfirst=True)
