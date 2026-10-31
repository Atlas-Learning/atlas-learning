"""rôle content_reviewer — ajoute une valeur à l'enum RBAC `role` (refonte, A2 → A4)

Le relecteur de contenu est un STAFF Atlas GLOBAL (comme le linguiste) : il tient la file de
revue de la banque d'items (signalements, gabarits, transitions de statut). Membership sans
école ni organisation. Connexion par lien magique (/admin/request-link) ou SSO.

Même patron que 0017_role_linguist : sur Postgres `role` est un TYPE ENUM natif → `ALTER TYPE
role ADD VALUE`, hors transaction (PG < 12) après un COMMIT explicite, protégé par un garde
d'existence (upgrade rejouable). Sur SQLite (dev/CI) la colonne est un VARCHAR sans CHECK
(native_enum sans contrainte) : no-op. Le downgrade est un no-op documenté : Postgres ne sait
pas retirer une valeur d'un enum ; aucune donnée n'est perdue.

Revision ID: 0024_role_content_reviewer
Revises: 0023_item_versions_flags
Create Date: 2026-10-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0024_role_content_reviewer"
down_revision: Union[str, None] = "0023_item_versions_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALUES = ("content_reviewer",)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite : `role` est un VARCHAR sans contrainte → rien à faire.
        return
    from alembic import context
    if context.is_offline_mode():
        # --sql : pas de connexion pour interroger pg_enum → SQL statique idempotent (PG ≥ 12).
        op.execute("COMMIT")
        for v in _VALUES:
            op.execute(f"ALTER TYPE role ADD VALUE IF NOT EXISTS '{v}'")
        return
    missing = [
        v for v in _VALUES
        if bind.exec_driver_sql(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'role' AND e.enumlabel = %s", (v,)
        ).first() is None
    ]
    if not missing:
        return
    # `ADD VALUE` ne tourne pas dans une transaction sur PG < 12 : on sort du bloc
    # transactionnel d'Alembic (commit) puis on émet les ALTER en autocommit.
    op.execute("COMMIT")
    for v in missing:
        bind.exec_driver_sql(f"ALTER TYPE role ADD VALUE '{v}'")


def downgrade() -> None:
    # Postgres ne permet pas de RETIRER une valeur d'un enum ; SQLite n'a rien ajouté.
    # No-op assumé : la valeur reste dans le type ; une membership content_reviewer éventuelle
    # reste une ligne inerte (le code antérieur l'ignore).
    pass
