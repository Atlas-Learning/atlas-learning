# 00 — Écarts entre le spec et le dépôt

Relevé le 2026-10-31 sur `origin/main` (commit `97773c3`). Le spec de `docs/refonte/` a été écrit contre un état du code **en avance** sur ce qui est poussé sur GitHub. À résoudre avant d'attaquer la phase A.

## Structure

| Spec | Dépôt | Conséquence |
| --- | --- | --- |
| Code à la racine (`src/`, `web/`, …) | Code dans `04_code/` | Tous les chemins du spec se lisent relatifs à `04_code/` (dit dans `CLAUDE.md`) |
| `make test`, `make demo-reset` | Pas de Makefile | `04_code/Makefile` ajouté avec `test` et `migrate` ; `demo-reset` reste à définir |
| `demo/` (dossier de démo isolé) | N'existe pas ; `scripts/provision_demo.py` fait office | Ticket B7 : créer `demo/seed_demo_school.py` ou étendre `provision_demo.py` `[À CLARIFIER]` |

## État des migrations et des rôles

| Spec | Dépôt |
| --- | --- |
| « État de départ : migrations jusqu'à `0022_role_content_reviewer` » | Dernière migration : `0020_enrich_kind`. **0021 et 0022 n'existent pas.** |
| Rôle `content_reviewer` : « Existe » | **Absent** de `Role` (`src/models/base.py`) : 7 rôles (`super_admin`, `it_admin`, `ped_admin`, `teacher`, `parent`, `student`, `linguist`) |
| Suivre le modèle de `0022_role_content_reviewer` | Le modèle disponible est `0017_role_linguist` (ajout d'une valeur d'enum, no-op SQLite, `ALTER TYPE` Postgres) |

**Question bloquante pour A1** : ces migrations et ce rôle existent-ils dans une copie locale non poussée ? Si oui, pousser d'abord ; sinon, numéroter la migration de A1 `0021` et traiter `content_reviewer` comme à créer (ticket A4 en dépend : « super admin et relecteur »).

## Fichiers cités qui n'existent pas

| Fichier | Cité par | Note |
| --- | --- | --- |
| `src/items/arabic_deterministic.py` | CLAUDE.md, A3 | La génération AR passe aujourd'hui par `src/items/arabic.py` et `scripts/translate_bank_ar.py` |
| `tests/test_rbac_write_scope.py` | CLAUDE.md (invariant 7) | Seul `tests/test_rbac.py` existe |
| `tests/test_item_flags.py` | A2 | À créer (normal) |
| `data/crosswalk_fractions_draft.json` | O3 | `data/` ne contient que `referentiel_fractions.json` ; le crosswalk est seedé par `scripts/seed_crosswalk.py` |
| `data/lessons/` | B3 | À créer (normal) |
| `demo/seed_demo_school.py` | B7 | À créer (normal) |

## Fichiers cités qui existent bien

`src/api/session_service.py`, `src/compliance/service.py`, `src/engine/stopping.py`, `src/engine/selection.py`, `src/restitution/proof.py`, `src/items/quarantine.py`, `web/lib/mastery.ts`, `web/components/StandardBadge.tsx`, `web/tailwind.config.ts`, `web/components/DiagnosisBlock.tsx`, `web/components/RemediationModal.tsx`.

## Baseline

`make test` sur ce commit : 454 tests verts, 1 skip (le test de concurrence Postgres, dé-skippé en CI).
