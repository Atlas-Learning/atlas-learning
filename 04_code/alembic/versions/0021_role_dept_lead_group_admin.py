"""rôles dept_lead et group_admin — ajoute deux valeurs à l'enum RBAC `role` (refonte, A1)

- `dept_lead` : coordinateur maths, scopé à UNE école (Membership.school_id) + une liste de
  niveaux (table dept_lead_scope, migration 0022) ;
- `group_admin` : admin d'un groupe scolaire, scopé à l'organisation (Membership.organization_id,
  school_id nul) ; ses écoles se résolvent via School.organization_id.

Même patron que 0017_role_linguist : sur Postgres `role` est un TYPE ENUM natif → `ALTER TYPE
role ADD VALUE`, hors transaction (PG < 12) après un COMMIT explicite, protégé par un garde
d'existence (upgrade rejouable). Sur SQLite (dev/CI) la colonne est un VARCHAR sans CHECK
(native_enum sans contrainte) : no-op. Le downgrade est un no-op documenté : Postgres ne sait
pas retirer une valeur d'un enum ; aucune donnée n'est perdue.

Une migration par sujet : le schéma (classroom.grade, dept_lead_scope) est dans 0022, pour ne
pas mélanger du DDL transactionnel avec l'ALTER TYPE émis en autocommit.

Revision ID: 0021_role_dept_lead_group_admin
Revises: 0020_enrich_kind
Create Date: 2026-10-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021_role_dept_lead_group_admin"
down_revision: Union[str, None] = "0020_enrich_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALUES = ("dept_lead", "group_admin")


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
    # No-op assumé : les valeurs restent dans le type, sans membership les utilisant
    # (0022 supprime la table de portée ; les memberships dept_lead/group_admin éventuelles
    # restent des lignes inertes, comme pour tout rôle sans écran).
    pass
