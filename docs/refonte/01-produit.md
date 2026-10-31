# 01 — Produit

## En une phrase

Atlas devient le **plan du lundi** de l'enseignant de maths : en 10 minutes par semaine, il sait quoi re-enseigner, à qui et pourquoi, puis voit la preuve, re-mesurée, que son action a débloqué des élèves.

Le moteur Elo, le graphe de prérequis, la banque d'items, le RBAC, le SSO et le roster restent. On ajoute la couche d'usage.

## La boucle hebdomadaire

1. **Déclencheur** : message de début de semaine « votre plan est prêt ». Jour réglé par pays (lundi aux Émirats, dimanche en Arabie saoudite).
2. **Plan** : 2 à 4 actions, chacune = un groupe d'élèves partageant une cause racine + une mini-leçon.
3. **Action en classe** : mini-leçon de 10 à 15 min, projetable ou imprimable, marquée « faite » en un clic.
4. **Re-mesure** : check-in ciblé de 5 à 8 min, uniquement sur les élèves du groupe et les compétences concernées.
5. **Preuve** : par élève, avant / après, en trois états : débloqué, inchangé, non re-mesuré. Avec l'incertitude.
6. **Investissement** : corrections de groupes, notes et historique enrichissent le plan suivant.

La re-mesure (étape 4) est ce qui transforme une intuition en preuve. Sans elle, pas de produit.

## Objets métier nouveaux

| Objet | Définition | Créé par |
| --- | --- | --- |
| `CheckIn` | Session de classe lancée par l'enseignant, rejointe par code. Type `full` (diagnostic) ou `targeted` (re-mesure d'un groupe) | Enseignant |
| `WeeklyPlan` | Plan d'une classe pour une semaine, généré après un check-in | Atlas |
| `PlanAction` | Une action du plan : `reteach` ou `recheck`, avec cause racine, compétence bloquée, mini-leçon, membres | Atlas, ajustable par l'enseignant |
| `MiniLesson` | Leçon courte bilingue rattachée à une compétence du graphe | Atlas (puis écoles, phase E) |
| `Proof` | Résultat par élève d'une action après re-mesure | Atlas |
| `DepartmentDecision` | Décision consignée en revue de département | Coordinateur |

Le détail des champs est dans `03-modele-de-donnees.md`.

## Définitions à respecter

- **Maîtrisé** : estimation Elo ≥ `MASTERY_ELO` (1500, voir `src/restitution/diagnosis.py` et `web/lib/mastery.ts`) et compétence mesurée.
- **Estimé** : confiance < `CONFIDENCE_THRESHOLD` (0,5) ou valeur inférée par propagation dans le graphe. Affiché hachuré.
- **Cause racine** : premier prérequis non maîtrisé remonté par `src/restitution/diagnosis.py`. On réutilise le diagnostic existant, on ne le réécrit pas.
- **Débloqué** (proposition, à valider, voir questions ouvertes) : avant l'action, compétence mesurée et non maîtrisée ; après la re-mesure ciblée, compétence maîtrisée avec confiance ≥ 0,5.
- **Boucle bouclée** : une `PlanAction` marquée faite ET suivie d'une re-mesure ciblée terminée. C'est la métrique nord.

## Règles produit

- Une action principale par écran.
- Toute recommandation porte une phrase « parce que » (cause racine → compétence bloquée).
- Aucun nom d'élève associé à un résultat sur un écran projeté.
- L'enseignant peut retirer ou ajouter un élève à un groupe, ou ignorer une action. La correction est enregistrée.
- Pas de badges, pas de séries, pas de classement. Le compteur « boucles bouclées ce trimestre » n'est visible que par l'enseignant.
- La direction voit des niveaux et des écoles, jamais des résultats par enseignant.
- Parents : message mensuel, sans note, sans comparaison, avec une activité de 5 minutes.

## Curriculums et exercices

- Le graphe est unique et neutre. Un curriculum est une correspondance (crosswalk) : attendu officiel ↔ compétences du graphe, avec `alignment_type` (EXACT, PARTIAL, BROADER, PREREQ, ENRICH) et `confidence` (H, M, L).
- Le super admin peut importer n'importe quel curriculum, le mapper, contrôler la couverture et le publier. Une école choisit son curriculum ; l'UI affiche alors ses codes.
- Le vocabulaire affiché suit l'alignement : « aligned with » (EXACT), « covers part of » (PARTIAL), « prerequisite of » (PREREQ), « taught earlier than in your curriculum » (ENRICH), « part of » (BROADER).
  Livré (C3) dans `src/api/views_service.py` (`alignment_wording`). Nuance conservée de la revue 2026-07-12 : un ENRICH porte un `enrich_kind` ; `grade` donne la formule ci-dessus (Atlas mesure un niveau plus tôt), `requirement` (exigence absente du curriculum) garde « beyond … expectations ». [À CLARIFIER] si une seule formule doit rester. MoE UAE n'ayant pas de codes, son libellé nomme le domaine (« part of Numbers & Operations … »). Confiance M → suffixe « (indicative mapping) ».
- Deux sources d'items : gabarits déterministes et écoles (phase E). Un item d'école sert tout de suite en classe mais n'entre dans la mesure qu'après assez de réponses et une revue.
- Une faute dans un item généré se corrige au gabarit. Si énoncé ou réponse change, l'item repart en nouvelle version ; ses anciennes réponses ne servent plus à sa calibration.

## Hors périmètre

- Tout contenu au-delà des fractions G2–G5 (les décimales G4–G5 viendront après, référentiel en brouillon dans `data/`).
- Toute génération par LLM au runtime.
- Le bottom-up enseignant sans contrat école : le produit reste vendu et déployé par l'école.
