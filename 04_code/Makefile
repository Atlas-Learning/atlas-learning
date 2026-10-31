# Raccourcis de dev — voir ../CLAUDE.md. Tout tourne dans le venv local (.venv/).
PY ?= .venv/bin/python
DB ?= atlas_dev.db

.PHONY: test migrate demo-reset

test:
	$(PY) -m pytest -q

migrate:
	$(PY) -m alembic upgrade head

# Base de démo SQLite (B7) : schéma, référentiel, crosswalk, leçons, puis six semaines de boucle.
demo-reset:
	rm -f $(DB)
	$(PY) -m alembic upgrade head
	$(PY) scripts/seed_referentiel.py
	-$(PY) scripts/seed_crosswalk.py
	$(PY) scripts/seed_lessons.py
	$(PY) demo/seed_demo_school.py
