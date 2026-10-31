# 04 — Plan d'implémentation

Un ticket = une session Claude Code = une PR. Chaque ticket se termine par `make test` vert et, s'il touche le front, une vérification EN et AR.

Format : **Objectif** · **Fichiers** · **Fait quand** · **Tests**.

## Phase A — Rôles et file de revue

**A1 · Rôles `dept_lead` et `group_admin`**
- Objectif : créer les deux rôles, leur portée et le niveau des classes.
- Fichiers : `src/models/base.py`, `src/models/org.py`, `alembic/versions/0023_*`, `src/rbac/authz.py`, `src/rostering/` (remplir `Classroom.grade` si la source le donne).
- Fait quand : un `dept_lead` lit les classes de ses niveaux et rien d'autre ; un `group_admin` lit toutes les écoles de son organisation et rien d'autre.
- Tests : `tests/test_rbac.py` (accès croisés), `tests/test_migrations.py`.

**A2 · Versions d'items et signalements**
- Objectif : champs de version et table `item_flag` (voir `03`, migration 0024).
- Fichiers : `src/models/item.py`, `alembic/versions/0024_*`, `src/items/review.py`, `src/api/app.py` (`POST /items/{id}/flags`).
- Fait quand : un enseignant signale un item ; le signalement apparaît dans la file ; aucune transition de statut ne contourne `ALLOWED_TRANSITIONS`.
- Tests : `tests/test_review.py`, `tests/test_quarantine.py`, nouveau `tests/test_item_flags.py`.

**A3 · Correction au gabarit et régénération**
- Objectif : quarantaine en masse des items d'un gabarit, puis régénération en nouvelle version après correction du gabarit dans le code.
- Fichiers : `src/items/deterministic.py`, `src/items/arabic_deterministic.py`, `src/items/quarantine.py`, `scripts/` (CLI `regenerate-template --key`).
- Fait quand : après correction de `EQUIV-MCQ-03`, la CLI crée N nouvelles versions `ai_generated` avec `supersedes_id`, les anciennes sont `quarantined`, leurs réponses ne pèsent plus sur la calibration.
- Tests : régénération idempotente, `calibration_reset_at` respecté par la mise à jour de `difficulty_elo`.
- Note : les gabarits vivent dans le code ; l'UI ne les édite pas, elle déclenche quarantaine et suivi.

**A4 · File de revue (`/ops/review`)**
- Objectif : écran O2 pour super admin et relecteur.
- Fichiers : `src/api/app.py` (routes `/ops/review*`), `web/app/ops/review/page.tsx`, `web/components/`.
- Fait quand : les 4 sources (signalements, échecs de validation, items d'école, arabe à valider) sont dans une file filtrable ; détail EN/AR ; regroupement par gabarit ; actions selon le rôle.
- Tests : RBAC (un `teacher` reçoit 403), contenu de la file.

## Phase B — Boucle enseignant

**B1 · Check-ins et code de classe**
- Objectif : table `checkin`, création, code, rejoindre, progression anonyme, clôture.
- Fichiers : `src/models/` (nouveau `checkin.py`), `src/models/session.py`, `alembic/versions/0025_*`, `src/api/session_service.py`, `src/api/app.py`.
- Fait quand : un enseignant ouvre un check-in, 26 élèves rejoignent avec le code, `progress` ne renvoie aucun identifiant, la clôture termine les sessions ouvertes proprement.
- Tests : code unique parmi les ouverts, élève hors classe refusé, `progress` sans PII (test explicite sur les clés renvoyées).

**B2 · Générateur de plan**
- Objectif : à la clôture d'un check-in `full`, produire `WeeklyPlan` + 2 à 4 `PlanAction`.
- Fichiers : nouveau `src/restitution/plan.py`, réutiliser `src/restitution/diagnosis.py`, `aggregate.py`, `remediation.py`.
- Règles : grouper les élèves par cause racine ; trier par nombre d'élèves débloquables ; `confidence = partly_estimated` si un membre a la racine estimée ; phrase « parce que » déterministe EN et AR.
- Fait quand : sur la base de démo, la classe 4B produit un plan stable (même entrée → même plan).
- Tests : déterminisme, aucune action sans membre, aucune action sur une compétence hors unité, `tests/test_restitution.py` étendu.

**B3 · Mini-leçons**
- Objectif : table `mini_lesson`, chargement depuis `data/lessons/*.json`, endpoint `GET /lessons/{id}`.
- Fichiers : `src/models/`, `alembic/versions/0027_*`, `scripts/seed_lessons.py`, `data/lessons/`.
- Fait quand : chaque compétence racine du plan de démo a une leçon EN ; l'AR passe par le linguiste.
- Contenu : `[À CLARIFIER]` liste des compétences à couvrir pour l'unité pilote ; la rédaction est humaine.

**B4 · Action faite, re-mesure, preuve**
- Objectif : `POST /plan-actions/{id}/done` fige les `before_*`, planifie un check-in `targeted` ; sa clôture calcule les `proof`.
- Fichiers : `src/restitution/proof.py` (existe, à étendre), `src/api/app.py`.
- Fait quand : sur la démo, marquer une action puis jouer le re-check produit « X sur Y ont débloqué » avec la définition de `01-produit.md`.
- Tests : élève absent → `not_rechecked`, jamais compté dans le dénominateur ; intervalle exposé.

**B5 · Écrans enseignant et élève**
- Objectif : E1 à E6, S1 à S3 (voir `02`), maquettes dans `maquettes/`.
- Fichiers : `web/app/teacher/**`, `web/app/student/**`, `web/components/`, `web/lib/i18n.ts`, `web/lib/types.ts`, `web/lib/api.ts`.
- Composants à créer : `CausalThread` (fil causal, miroir RTL), `GroupCard`, `ProofCard`, `MasteryRange` (barre avec fourchette, hachurée si estimée), `ProjectionLayout`.
- Fait quand : parcours démo complet en EN et AR : plan → check-in projeté → groupe → marquer fait → re-check → preuve.
- Tests : rendu RTL vérifié à la main, pas de rouge, mode projection sans nom.

**B6 · Message de début de semaine**
- Objectif : e-mail « votre plan est prêt », jour d'envoi par pays de l'école.
- Fichiers : `src/notify/templates.py`, `src/notify/email.py`, réglage de jour sur `School` ou `Organization` `[À CLARIFIER]`.
- Tests : `tests/test_email_sender.py` étendu, un enseignant sans plan ne reçoit rien.

**B7 · Démo**
- Objectif : `demo/seed_demo_school.py` produit des plans, des actions faites et des preuves sur 6 semaines.
- Fait quand : `make demo-reset` donne une école où chaque écran de la phase B a du contenu. **Livré** : `demo/seed_demo_school.py` (profils latents par élève, six semaines, deux écoles, rejouable).

## Phase C — Curriculums dynamiques

**C1 · Frameworks en table**
- Objectif : migration 0029 (voir `03`), sans régression sur les 3 frameworks existants.
- Fichiers : `src/models/base.py`, `src/models/curriculum.py`, `src/models/org.py`, `alembic/versions/0029_*`, tous les usages de `CurriculumFramework` et `CurriculumView`.
- Tests : `tests/test_curriculum_views.py`, `tests/test_crosswalk_pipeline.py`, aller-retour de migration avec données. **Livré** : `0030_curriculum_framework_table` (copie des données, downgrade refusé si un framework importé existe), `CurriculumFrameworkDef`, `school_framework()` (un framework non publié = vue ATLAS), `suggested` jamais servi, console `/admin/curriculum` sur la table.

**C2 · Import, mapping, couverture, publication**
- Objectif : API `/ops/curricula/*` (voir écran O3).
- Fait quand : importer un CSV d'attendus, mapper, voir la couverture, publier ; une école voit le framework publié dans son choix.
- Tests : une ligne `suggested` n'est jamais servie aux écoles ; publication refusée si des attendus restent non revus.

**C3 · Écran O3 et libellés par alignement**
- Objectif : UI `/ops/curricula/[id]` et libellés côté école selon `alignment_type` (voir `01`).
- Fichiers : `web/app/ops/curricula/**`, `web/components/StandardBadge.tsx`.

## Phase D — Département, direction, groupe, famille, IT

**D1 · Revue de département** (écran C1, migration 0028)
**D2 · Preuves par niveau et licences** (écrans D1, D2) — vérifier l'invariant 4 par un test explicite.
**D3 · Vue groupe** (écran G1)
**D4 · Message famille mensuel** (écran P1) — via `src/notify/`, opt-in de l'école.
**D5 · IT : SSO, roster, données** (écrans I1, I2) — réutilise les endpoints existants.
**D6 · Écoles et pilotes** (écran O1) — critères de succès du pilote stockés par école `[À CLARIFIER]` format.

Pour chacun : routes et critères dans `02-roles-et-ecrans.md`, tests RBAC obligatoires.

## Phase E — Exercise builder (après le premier pilote)

**E1 · Items d'école** — migration 0030, statut `CLASS_USE`, `POST /school-items`, contrôles automatiques (réponse calculée, unicité en MCQ).
**E2 · Écran builder** (écran E7) et intégration dans les mini-leçons.
**E3 · Passage en mesure** — transition `CLASS_USE → HUMAN_REVIEWED` après seuil de réponses, via la file de revue.
