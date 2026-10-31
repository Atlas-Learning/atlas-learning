# 03 — Modèle de données

État de départ : migrations jusqu'à `0022_role_content_reviewer`. Les numéros ci-dessous sont indicatifs ; garder une migration par sujet, chacune réversible.

Noms de champs en anglais, types SQLAlchemy 2 (`Mapped[...]`), UUID en clé primaire comme le reste du schéma, `school_id` dénormalisé sur toute table élève pour l'isolation tenant et la rétention.

## 0023 — Rôles `dept_lead` et `group_admin` (phase A)

- `Role` (`src/models/base.py`) : ajouter `DEPT_LEAD = "dept_lead"` et `GROUP_ADMIN = "group_admin"`. Suivre le modèle de `0022_role_content_reviewer`.
- `Classroom` (`src/models/org.py`) : ajouter `grade: Optional[int]` (indexé). Rempli par le roster quand la source le fournit, sinon saisi en admin. `[À CLARIFIER]` mapping Year ↔ Grade pour les écoles en curriculum anglais.
- Nouvelle table `dept_lead_scope` : `membership_id` (FK), `grade` (int). Un `dept_lead` couvre une ou plusieurs années d'une école.
- `group_admin` : `Membership.organization_id` renseigné, `school_id` nul. `src/rbac/authz.py` résout ses écoles via `School.organization_id`.

## 0024 — Versions et signalements d'items (phase A)

Table `item` (`src/models/item.py`) :

| Champ | Type | Rôle |
| --- | --- | --- |
| `origin` | enum `atlas_template` \| `school` | Source de l'item |
| `template_key` | str, nullable, indexé | Gabarit d'origine (ex. `EQUIV-MCQ-03`) |
| `version` | int, défaut 1 | Version de l'item |
| `supersedes_id` | UUID nullable, FK `item.id` | Item remplacé par cette version |
| `calibration_reset_at` | datetime nullable | Les réponses antérieures ne comptent plus pour `difficulty_elo` |
| `owner_school_id` | UUID nullable, FK `school.id` | Items d'école seulement |

Nouvelle table `item_flag` : `id`, `item_id`, `school_id` nullable, `raised_by` (user), `reason` (enum `wrong_answer_key` \| `several_correct` \| `unclear_wording` \| `arabic` \| `other`), `comment`, `status` (`open` \| `accepted` \| `rejected`), `resolved_by`, `created_at`, `resolved_at`.

Règle : corriger un gabarit crée de nouvelles versions des items concernés (nouveau statut `ai_generated`), passe les anciens en `quarantined` et pose `supersedes_id`. Les réponses existantes restent attachées à l'ancienne version.

## 0025 — Check-ins (phase B)

Nouvelle table `checkin` :

| Champ | Type | Rôle |
| --- | --- | --- |
| `id` | UUID | |
| `school_id`, `classroom_id` | UUID FK | |
| `created_by` | UUID FK `app_user` | Enseignant |
| `kind` | enum `full` \| `targeted` | Diagnostic ou re-mesure |
| `plan_action_id` | UUID nullable FK | Pour un `targeted` |
| `competency_ids` | JSON | Compétences visées |
| `student_ids` | JSON nullable | Restriction aux membres pour un `targeted` |
| `code` | str(4) | Unique parmi les check-ins `open` |
| `status` | enum `scheduled` \| `open` \| `closed` | |
| `opened_at`, `closed_at` | datetime | |

`AssessmentSession` (`src/models/session.py`) : ajouter `checkin_id: Optional[UUID]` (FK, indexé). Une session d'élève rejoint au plus un check-in.

## 0026 — Plans, actions, preuves (phase B)

`weekly_plan` : `id`, `school_id`, `classroom_id`, `week_start` (date), `source_checkin_id`, `generated_at`, `status` (`active` \| `superseded`). Unique (`classroom_id`, `week_start`, `status=active`).

`plan_action` :

| Champ | Type | Rôle |
| --- | --- | --- |
| `id`, `plan_id`, `school_id` | | |
| `kind` | enum `reteach` \| `recheck` | |
| `rank` | int | Ordre d'affichage |
| `root_cause_competency_id` | UUID | Prérequis manquant |
| `blocked_competency_id` | UUID | Où l'erreur se voit |
| `lesson_id` | UUID nullable FK `mini_lesson` | |
| `confidence` | enum `measured` \| `partly_estimated` | Badge de l'écran |
| `because_en`, `because_ar` | text | Phrase « parce que » générée de façon déterministe |
| `status` | enum `proposed` \| `done` \| `dismissed` | |
| `done_at`, `dismissed_at` | datetime | |

`plan_action_member` : `action_id`, `student_id`, `school_id`, `source` (`atlas` \| `teacher_added`), `removed_by_teacher` (bool), `observed_error` (text nullable, ex. `1/3 + 1/6 = 2/9 on 3 of 4 items`).

`proof` (une ligne par élève et par action re-mesurée) : `id`, `action_id`, `student_id`, `school_id`, `competency_id`, `before_elo`, `before_confidence`, `after_elo` nullable, `after_confidence` nullable, `ci_low`, `ci_high`, `outcome` (`unlocked` \| `unchanged` \| `not_rechecked`), `recheck_checkin_id`, `computed_at`.

Les valeurs `before_*` sont figées à la création de l'action (snapshot de `StudentCompetencyAbility`), pas recalculées.

## 0027 — Mini-leçons (phase B)

`mini_lesson` : `id`, `competency_id`, `title_en`, `title_ar`, `duration_min`, `steps` (JSON : liste `{kind: warmup|model|guided|exit, minutes, body_en, body_ar, items?: [...] }`), `origin` (`atlas` \| `school`), `owner_school_id` nullable, `status` (`draft` \| `linguist_validated` \| `active`), `version`.

Le contenu des leçons est une tâche éditoriale, pas de code : seed dans `data/lessons/*.json` relus par un humain.

## 0028 — Revue de département (phase D)

`department_decision` : `id`, `school_id`, `grade`, `month` (date, 1er du mois), `text`, `root_cause_competency_id` nullable, `created_by`, `created_at`.

## 0029 — Curriculums dynamiques (phase C)

Aujourd'hui `CurriculumFramework` et `CurriculumView` sont des enums figés (`CCSS_M`, `UK_NC`, `MOE_UAE`). Pour importer n'importe quel curriculum, ils deviennent une table.

`curriculum_framework` : `id`, `key` (unique, ex. `UK_NC`), `name_en`, `name_ar`, `country` nullable, `status` (`draft` \| `published`), `imported_at`, `published_at`, `source_note`.

Migration :
1. Créer la table et y insérer les 3 frameworks existants (statut `draft`, comme le crosswalk actuel).
2. `curriculum_standard.framework` (enum) → `framework_id` (FK). Recopier les valeurs.
3. `organization.curriculum_view` (enum) → `curriculum_framework_id` nullable. Nul = vue neutre `ATLAS`, comportement actuel conservé.
4. Downgrade : chemin inverse vers les enums, refusé si un framework hors des 3 historiques existe.

`competency_curriculum_map` garde ses champs (`alignment_type`, `confidence`, `enrich_kind`, `note`, `weight_source`, `weight_version`) ; ajouter `reviewed_by`, `reviewed_at`, `suggested` (bool : proposé automatiquement, non encore validé).

Import : CSV ou JSON avec `code, label_en, label_ar, grade_hint`. Le mapping suggéré peut réutiliser la logique de `scripts/` du crosswalk ; une ligne `suggested=true` n'est jamais affichée aux écoles.

## 0030 — Items d'école (phase E)

`ItemStatus` : ajouter `CLASS_USE` (utilisable en mini-leçon et question de sortie, jamais servi par `src/engine/selection.py` en session de mesure). Transition `CLASS_USE → HUMAN_REVIEWED` autorisée seulement si `n_responses ≥ SCHOOL_ITEM_MIN_RESPONSES` `[À CLARIFIER]`. Mettre à jour `ALLOWED_TRANSITIONS` dans `src/items/review.py` et ses tests.

## Rétention

Toute nouvelle table qui porte un `student_id` doit être couverte par la suppression et l'export existants (`src/compliance/service.py`, `POST /admin/students/{id}/erase`, `GET /admin/export`) et respecter `legal_hold`. Ajouter les tests correspondants dans `tests/test_retention.py` et `tests/test_compliance.py`.
