# Raccourcis de dev — voir ../CLAUDE.md. Tout tourne dans le venv local (.venv/).
PY ?= .venv/bin/python

.PHONY: test migrate

test:
	$(PY) -m pytest -q

migrate:
	$(PY) -m alembic upgrade head
