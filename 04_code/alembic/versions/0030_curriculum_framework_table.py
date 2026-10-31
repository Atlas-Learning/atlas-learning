"""curriculum_framework en table (refonte C1, « 0029 » du spec)

Aujourd'hui `CurriculumFramework` et `CurriculumView` sont des enums figés (CCSS_M, UK_NC,
MOE_UAE). Pour importer n'importe quel curriculum (C2), ils deviennent une table :

1. `curriculum_framework` (id, key unique, noms EN/AR, pays, statut draft|published,
   imported_at, published_at, source_note) + les 3 frameworks historiques, identifiants
   STABLES (uuid5), statut `published` : ils étaient servis aux écoles avant C1 — le spec
   disait « draft comme le crosswalk actuel », mais un brouillon ne sera plus servi (C2) ;
   publié = zéro régression, note de source explicite.
2. `curriculum_standard.framework` (enum) → `framework_id` (FK CASCADE), valeurs recopiées,
   contrainte d'unicité (framework_id, code).
3. `organization.curriculum_view` (enum) → `curriculum_framework_id` (FK SET NULL, nullable) ;
   ATLAS → NULL (vue neutre conservée).
4. `competency_curriculum_map` += reviewed_by, reviewed_at, suggested (défaut faux).
5. Downgrade : chemin inverse vers les enums, REFUSÉ si un framework hors des 3 historiques
   existe (il n'aurait pas de valeur d'enum). Les types Postgres `curriculum_view` et
   `curriculum_framework` sont supprimés à l'upgrade et recréés au downgrade.

Revision ID: 0030_curriculum_framework_table
Revises: 0029_school_plan_mail
Create Date: 2026-10-31
"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_curriculum_framework_table"
down_revision: Union[str, None] = "0029_school_plan_mail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "atlas-learning/curriculum_framework")
LEGACY = {
    "CCSS_M": ("Common Core State Standards — Mathematics", "المعايير الأساسية المشتركة — الرياضيات", "US"),
    "UK_NC": ("National Curriculum in England — Mathematics", "المنهج الوطني الإنجليزي — الرياضيات", "GB"),
    "MOE_UAE": ("MoE UAE — Mathematics", "وزارة التربية والتعليم (الإمارات) — الرياضيات", "AE"),
}
OLD_ENUMS = {
    "curriculum_view": ("ATLAS", "CCSS_M", "UK_NC", "MOE_UAE"),
    "curriculum_framework": ("CCSS_M", "UK_NC", "MOE_UAE"),
}


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enum(name: str, values, is_pg: bool) -> sa.types.TypeEngine:
    return postgresql.ENUM(name=name, create_type=False) if is_pg else sa.Enum(*values, name=name)


def _create_pg_enum(name: str, values) -> None:
    from alembic import context
    if context.is_offline_mode():
        vals = ", ".join(f"''{v}''" for v in values)
        op.execute(f"DO 'BEGIN CREATE TYPE {name} AS ENUM ({vals}); EXCEPTION WHEN duplicate_object THEN NULL; END'")
    else:
        sa.Enum(*values, name=name).create(op.get_bind(), checkfirst=True)


def _drop_pg_enum(name: str) -> None:
    from alembic import context
    if context.is_offline_mode():
        op.execute(f"DROP TYPE IF EXISTS {name}")
    else:
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)


def upgrade() -> None:
    is_pg = _is_pg()
    if is_pg:
        _create_pg_enum("framework_status", ("draft", "published"))

    # 1. table des frameworks + 3 historiques (publiés, ids stables)
    fw = op.create_table(
        "curriculum_framework",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name_en", sa.String(), nullable=False),
        sa.Column("name_ar", sa.String(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("status", _enum("framework_status", ("draft", "published"), is_pg), nullable=False, server_default="draft"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_note", sa.String(), nullable=True),
        sa.UniqueConstraint("key", name="uq_curriculum_framework_key"),
    )
    op.create_index("ix_curriculum_framework_key", "curriculum_framework", ["key"])
    op.create_index("ix_curriculum_framework_status", "curriculum_framework", ["status"])
    now = datetime.now(timezone.utc)
    op.bulk_insert(fw, [{
        "id": uuid.uuid5(_NS, key), "key": key, "name_en": en, "name_ar": ar, "country": cc, "status": "published",
        "imported_at": now, "published_at": now,
        "source_note": "crosswalk historique (expert), publié pour continuité (C1)",
    } for key, (en, ar, cc) in LEGACY.items()])

    # 2. curriculum_standard.framework → framework_id
    with op.batch_alter_table("curriculum_standard") as batch:
        batch.add_column(sa.Column("framework_id", sa.Uuid(), nullable=True))
    cast = "::text" if is_pg else ""
    for key in LEGACY:
        op.execute(sa.text(
            f"UPDATE curriculum_standard SET framework_id = :fid WHERE framework{cast} = :key"
        ).bindparams(fid=_uuid_param(uuid.uuid5(_NS, key), is_pg), key=key))
    with op.batch_alter_table("curriculum_standard") as batch:
        batch.drop_constraint("uq_curriculum_standard_framework_code", type_="unique")
        batch.drop_column("framework")
        batch.alter_column("framework_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_curriculum_standard_framework", "curriculum_framework", ["framework_id"], ["id"],
                                 ondelete="CASCADE")
        batch.create_unique_constraint("uq_curriculum_standard_framework_code", ["framework_id", "code"])
    op.create_index("ix_curriculum_standard_framework_id", "curriculum_standard", ["framework_id"])

    # 3. organization.curriculum_view → curriculum_framework_id (ATLAS → NULL)
    with op.batch_alter_table("organization") as batch:
        batch.add_column(sa.Column("curriculum_framework_id", sa.Uuid(), nullable=True))
    for key in LEGACY:
        op.execute(sa.text(
            f"UPDATE organization SET curriculum_framework_id = :fid WHERE curriculum_view{cast} = :key"
        ).bindparams(fid=_uuid_param(uuid.uuid5(_NS, key), is_pg), key=key))
    with op.batch_alter_table("organization") as batch:
        batch.drop_column("curriculum_view")
        batch.create_foreign_key("fk_organization_curriculum_framework", "curriculum_framework",
                                 ["curriculum_framework_id"], ["id"], ondelete="SET NULL")

    # 4. revue des mappings
    with op.batch_alter_table("competency_curriculum_map") as batch:
        batch.add_column(sa.Column("reviewed_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("suggested", sa.Boolean(), nullable=False, server_default="0"))
        batch.create_foreign_key("fk_ccm_reviewed_by", "app_user", ["reviewed_by"], ["id"], ondelete="SET NULL")

    # 5. les anciens types enum ne servent plus
    if is_pg:
        _drop_pg_enum("curriculum_view")
        _drop_pg_enum("curriculum_framework")


def _uuid_param(u: uuid.UUID, is_pg: bool):
    # sa.Uuid stocke l'UUID en hex 32 caractères sur SQLite, en uuid natif sur Postgres.
    return u if is_pg else u.hex


def downgrade() -> None:
    is_pg = _is_pg()
    bind = op.get_bind()
    # refus explicite si un framework hors des 3 historiques existe : il n'aurait pas d'enum
    foreign = bind.execute(sa.text("SELECT key FROM curriculum_framework WHERE key NOT IN ('CCSS_M','UK_NC','MOE_UAE')")).fetchall()
    if foreign:
        raise RuntimeError(
            "downgrade 0030 refusé : frameworks hors enum historique : "
            + ", ".join(r[0] for r in foreign) + " — les supprimer d'abord")
    if is_pg:
        for name, values in OLD_ENUMS.items():
            _create_pg_enum(name, values)

    with op.batch_alter_table("competency_curriculum_map") as batch:
        batch.drop_constraint("fk_ccm_reviewed_by", type_="foreignkey")
        batch.drop_column("suggested")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by")

    # organization : recréer l'enum, recopier, retirer la FK
    with op.batch_alter_table("organization") as batch:
        batch.add_column(sa.Column("curriculum_view", _enum("curriculum_view", OLD_ENUMS["curriculum_view"], is_pg),
                                   nullable=False, server_default="ATLAS"))
    for key in LEGACY:
        op.execute(sa.text(
            "UPDATE organization SET curriculum_view = :key WHERE curriculum_framework_id = :fid"
        ).bindparams(key=key, fid=_uuid_param(uuid.uuid5(_NS, key), is_pg)))
    with op.batch_alter_table("organization") as batch:
        batch.drop_constraint("fk_organization_curriculum_framework", type_="foreignkey")
        batch.drop_column("curriculum_framework_id")

    # curriculum_standard : enum recréé, recopié depuis la table, FK retirée
    op.drop_index("ix_curriculum_standard_framework_id", table_name="curriculum_standard")
    with op.batch_alter_table("curriculum_standard") as batch:
        batch.add_column(sa.Column("framework", _enum("curriculum_framework", OLD_ENUMS["curriculum_framework"], is_pg),
                                   nullable=True))
    for key in LEGACY:
        op.execute(sa.text(
            "UPDATE curriculum_standard SET framework = :key WHERE framework_id = :fid"
        ).bindparams(key=key, fid=_uuid_param(uuid.uuid5(_NS, key), is_pg)))
    with op.batch_alter_table("curriculum_standard") as batch:
        batch.drop_constraint("uq_curriculum_standard_framework_code", type_="unique")
        batch.drop_constraint("fk_curriculum_standard_framework", type_="foreignkey")
        batch.drop_column("framework_id")
        batch.alter_column("framework", existing_type=_enum("curriculum_framework", OLD_ENUMS["curriculum_framework"], is_pg),
                           nullable=False)
        batch.create_unique_constraint("uq_curriculum_standard_framework_code", ["framework", "code"])

    op.drop_index("ix_curriculum_framework_status", table_name="curriculum_framework")
    op.drop_index("ix_curriculum_framework_key", table_name="curriculum_framework")
    op.drop_table("curriculum_framework")
    if is_pg:
        _drop_pg_enum("framework_status")
