# 00 — Écarts entre le spec et le dépôt

Relevé le 2026-10-31 sur `origin/main` (commit `97773c3`). Le spec de `docs/refonte/` a été écrit contre un état du code **en avance** sur ce qui est poussé sur GitHub. À résoudre avant d'attaquer la phase A.

## Structure

| Spec | Dépôt | Conséquence |
| --- | --- | --- |
| Code à la racine (`src/`, `web/`, …) | Code dans `04_code/` | Tous les chemins du spec se lisent relatifs à `04_code/` (dit dans `CLAUDE.md`) |
| `make test`, `make demo-reset` | Pas de Makefile | `04_code/Makefile` ajouté avec `test` et `migrate` ; `demo-reset` reste à définir |
| `demo/` (dossier de démo isolé) | **Créé (B7)** : `demo/seed_demo_school.py`, `make demo-reset` | `scripts/provision_demo.py` reste pour l'ancien parcours (une classe, pas de boucle) |

## État des migrations et des rôles

| Spec | Dépôt |
| --- | --- |
| « État de départ : migrations jusqu'à `0022_role_content_reviewer` » | Dernière migration : `0020_enrich_kind`. **0021 et 0022 n'existent pas.** |
| Rôle `content_reviewer` : « Existe » | **Absent** de `Role` (`src/models/base.py`) : 7 rôles (`super_admin`, `it_admin`, `ped_admin`, `teacher`, `parent`, `student`, `linguist`) |
| Suivre le modèle de `0022_role_content_reviewer` | Le modèle disponible est `0017_role_linguist` (ajout d'une valeur d'enum, no-op SQLite, `ALTER TYPE` Postgres) |

**Tranché le 2026-10-31** (GitHub est à jour, pas de code local en avance) : A1 est livré en deux migrations, `0021_role_dept_lead_group_admin` (enum) et `0022_classroom_grade_dept_scope` (schéma). Les numéros de `03-modele-de-donnees.md` se décalent donc de −1 à partir de là : son « 0024 » (versions et signalements, A2) est `0023_item_versions_flags`, son « 0025 » (check-ins, B1) sera `0024`, etc. Le rôle `content_reviewer` a été créé par `0024_role_content_reviewer` (staff Atlas global, lien magique via `/admin/request-link`, onboarding `scripts/onboard_staff.py`) : il tient la file des signalements et les actions sur les gabarits ; l'écran `/ops/review` (A4) est en place.

## Fichiers cités qui n'existent pas

| Fichier | Cité par | Note |
| --- | --- | --- |
| `src/items/arabic_deterministic.py` | CLAUDE.md, A3 | **Créé le 2026-10-31** : gabarits arabes déterministes (300/300 items couverts), proposition validée par le linguiste ; `scripts/propose_arabic_deterministic.py` pour la banque existante. Le pipeline LLM (`arabic.py`) reste pour les items hors gabarit |
| `tests/test_rbac_write_scope.py` | CLAUDE.md (invariant 7) | Seul `tests/test_rbac.py` existe |
| `tests/test_item_flags.py` | A2 | À créer (normal) |
| `data/crosswalk_fractions_draft.json` | O3 | `data/` ne contient que `referentiel_fractions.json` ; le crosswalk est seedé par `scripts/seed_crosswalk.py` |
| `data/lessons/` | B3 | À créer (normal) |
| `demo/seed_demo_school.py` | B7 | Créé |

## Fichiers cités qui existent bien

`src/api/session_service.py`, `src/compliance/service.py`, `src/engine/stopping.py`, `src/engine/selection.py`, `src/restitution/proof.py`, `src/items/quarantine.py`, `web/lib/mastery.ts`, `web/components/StandardBadge.tsx`, `web/tailwind.config.ts`, `web/components/DiagnosisBlock.tsx`, `web/components/RemediationModal.tsx`.

## Baseline

`make test` sur ce commit : 454 tests verts, 1 skip (le test de concurrence Postgres, dé-skippé en CI).
