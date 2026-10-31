"""Alembic environment — Atlas Learning.

URL résolue via src.db (DATABASE_URL en prod, SQLite en dev).
target_metadata = Base.metadata pour autogenerate futur.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# rendre le package src importable quand alembic tourne depuis 04_code/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import get_database_url  # noqa: E402
from src.models.base import Base  # noqa: E402
from src.models import competency as _competency  # noqa: E402,F401  (enregistre les tables)
from src.models import curriculum as _curriculum  # noqa: E402,F401  (curriculum_standard/map)
from src.models import item as _item  # noqa: E402,F401  (enregistre la table item)
from src.models import measurement as _measurement  # noqa: E402,F401  (school/student/response/ability)
from src.models import session as _session  # noqa: E402,F401  (assessment_session)
from src.models import org as _org  # noqa: E402,F401  (organization/classroom/user/membership)
from src.models import audit as _audit  # noqa: E402,F401  (audit_log)
from src.models import checkin as _checkin  # noqa: E402,F401  (checkin, refonte B1)
from src.models import plan as _plan  # noqa: E402,F401  (weekly_plan, plan_action, proof, refonte B2)
from src.models import lesson as _lesson  # noqa: E402,F401  (mini_lesson, refonte B3)

config = context.config
config.set_main_option("sqlalchemy.url", get_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Mode --sql : supporté pour POSTGRES (génération du script prod, chaîne complète
    # 0001→head vérifiée le 2026-07-12). NON supporté en dialecte SQLite : les
    # batch_alter_table historiques (0006, 0009…) réclament la réflexion d'une base
    # vivante (seuls 0003 et 0019 portent un copy_from). SQLite migre ONLINE
    # (dev/CI) — aucun cas d'usage offline.
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # batch mode -> ALTER portables SQLite
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
