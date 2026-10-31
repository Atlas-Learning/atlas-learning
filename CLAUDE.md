# CLAUDE.md — Atlas Learning

Consignes pour Claude Code sur ce dépôt. À lire avant toute tâche.

## Le projet

Atlas Learning : évaluation adaptative K-12 en maths (fractions G2–G5), bilingue EN/AR avec RTL natif, vendue aux écoles privées du Golfe.
Backend FastAPI + SQLAlchemy 2 + Alembic (`04_code/src/`), front Next.js 14 + Tailwind (`04_code/web/`).

Le dépôt a cinq dossiers de tête : `01_strategie/` à `05_revue/` (docs) et `04_code/` (l'application). **Tout le code vit dans `04_code/`** : les chemins `src/…`, `web/…`, `tests/…`, `alembic/…`, `scripts/…`, `data/…` cités dans ce fichier et dans `docs/refonte/` sont relatifs à `04_code/`.

Une refonte est en cours. Sa spec complète est dans `docs/refonte/` : commence toujours par `docs/refonte/README.md`, puis `docs/refonte/00-ecarts-depot.md` (ce qui diffère entre le spec et l'état réel du dépôt).

## Langue

- Docs, commentaires de spec, messages de commit : français.
- Code, noms de tables, routes, clés i18n : anglais.
- Tout texte visible par un utilisateur existe en anglais ET en arabe dans `web/lib/i18n.ts`.

## Invariants (ne jamais casser)

1. **Le curriculum n'entre jamais dans `src/engine/`.** Le moteur ne connaît que le graphe de compétences. Les curriculums sont une couche d'affichage (`src/models/curriculum.py`).
2. **Aucun appel LLM sur des données d'élève au runtime.** La génération d'items est déterministe (`src/items/deterministic.py`, version arabe `src/items/arabic_deterministic.py` : un gabarit arabe par forme d'énoncé, proposé puis validé par le linguiste). Le tuteur (`src/restitution/tutor.py`) reste déterministe.
   Les gabarits vivent dans le code : une faute se corrige dans le générateur, puis `scripts/regenerate_template.py` crée les nouvelles versions (`src/items/templates.py`). Jamais d'édition d'item en base pour contourner le gabarit.
3. **Mesuré et estimé sont toujours distingués.** Toute réponse d'API qui expose une maîtrise expose aussi `measured` et la confiance. L'UI hachure l'estimé.
4. **Pas de classement d'enseignants.** Aucun endpoint accessible à `ped_admin` ou `group_admin` ne renvoie de résultat agrégé par enseignant. L'usage (adoption) peut être agrégé par classe ou par école, jamais les résultats.
5. **Mode projection anonyme.** Les endpoints de progression d'un check-in en cours ne renvoient ni nom, ni identifiant d'élève.
6. **Un item n'entre dans la mesure que par la machine à états** de `src/items/review.py` (`ai_generated → human_reviewed → linguist_validated → active`, `quarantined`). Aucun raccourci, aucun `UPDATE` direct du statut.
7. **Isolation tenant.** Chaque nouvel endpoint a un test d'accès croisé entre écoles (voir `tests/test_rbac.py`).
8. **Migrations réversibles.** Chaque migration passe l'aller-retour upgrade → downgrade → upgrade (`tests/test_migrations.py`). IDs de révision ≤ 32 caractères, une seule tête.
9. **Pas de rouge pour une lacune.** Sémantique couleur : teal = maîtrisé, ambre = prochaine étape, sable = non mesuré, hachure = estimé.
10. **Pas de chiffre d'efficacité inventé.** La validation est encore synthétique : aucune copy produit ne promet un gain mesuré.

## Commandes

Depuis `04_code/` :

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
make test          # suite complète (doit rester verte) — alias de .venv/bin/python -m pytest -q
make migrate       # alembic upgrade head (SQLite par défaut, DATABASE_URL pour Postgres)
.venv/bin/python scripts/grant_role.py --help   # attribuer dept_lead / group_admin (docs/refonte/06)
.venv/bin/python scripts/onboard_staff.py --role content_reviewer --email …   # staff Atlas global
.venv/bin/python scripts/backfill_template_keys.py --dry-run   # Q15 : clés de gabarit sans perte
.venv/bin/python scripts/regenerate_template.py --key <code|code#rang> [--dry-run]   # A3
cd web && npm install && npm run dev
```

Contrainte CI : Python 3.9 (`Optional[X]`, pas `X | None`). La CI rejoue aussi upgrade → downgrade 0013 → upgrade sur Postgres.

`make demo-reset` n'existe pas encore `[À CLARIFIER]` : la démo passe aujourd'hui par `scripts/provision_demo.py` (voir son en-tête), le `demo/seed_demo_school.py` du ticket B7 est à créer.

Avant de déclarer une tâche finie : `make test` vert, migration aller-retour OK, écrans vérifiés en EN et en AR.

## Façon de travailler

- Un ticket de `docs/refonte/04-plan.md` à la fois. Lis sa section, les fichiers cités, puis propose un plan court avant de coder.
- Les maquettes de `docs/refonte/maquettes/` sont des références visuelles, pas du code à copier : reconstruis-les avec les composants existants de `web/components/`.
- Une incertitude se marque `[À CLARIFIER]` dans le code ou la doc et se remonte dans le compte rendu. Ne l'invente pas.
- Les questions déjà ouvertes sont listées dans `docs/refonte/05-questions-ouvertes.md`.
