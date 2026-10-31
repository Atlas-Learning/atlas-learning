# 08 — Rédiger les mini-leçons (Q3, Q4) : mode d'emploi

Le code est prêt ; il manque le **contenu**. Voici exactement quoi faire, dans l'ordre.

## 1. Pour quelles compétences ?

Une mini-leçon sert à ré-enseigner une **cause racine**. Une cause racine est toujours un
prérequis HARD d'une autre compétence. Le référentiel en compte 21 sur 32 ; classées par ce
qu'elles débloquent en aval, ce sont d'abord :

| Priorité | Compétence | Libellé | Débloque (aval) |
| --- | --- | --- | --- |
| 1 | `MATH.G3.NF.FRACTION_AS_PART` | Represent a fraction a/b of a whole | 16 |
| 2 | `MATH.G3.NF.UNIT_FRACTION` | Understand a unit fraction 1/b | 18 (exemple fourni) |
| 3 | `MATH.G4.NF.EQUIVALENCE_COMPUTE` | Generate equivalent fractions by multiplication | 10 |
| 4 | `MATH.G3.NF.EQUIVALENCE_VISUAL` | Recognize equivalent fractions with models | 11 |
| 5 | `MATH.G4.NF.SIMPLIFY_FRACTION` | Simplify a fraction to lowest terms | 5 |
| 6 | `MATH.G4.NS.FACTORS` | Find factors of a number | 7 |
| 7 | `MATH.G3.NS.MULT_FACTS` | Recall multiplication facts to 100 | 8 |
| 8 | `MATH.G4.NS.LCM` | Find least common multiple | 5 |
| 9 | `MATH.G4.NF.COMMON_DENOM` | Find a common denominator for two fractions | 4 |
| 10 | `MATH.G3.NF.ADD_SAME_NOSIMP` | Add fractions, same denominator, no simplifying | 5 |
| 11 | `MATH.G2.NS.EQUAL_SHARES`, `HALVES_QUARTERS`, `NAME_FRACTION_VISUAL` | Bases G2 | 19–21 (rarement racine en G4) |
| 12 | les 8 autres (`ADD_UNLIKE_*`, `IMPROPER_TO_MIXED`, `MIXED_TO_IMPROPER`, `SUB_SAME_*`, `WHOLE_AS_FRACTION`, `ADD_UNLIKE_LCM`) | | 1–3 |

**Décision par défaut (Q3)** : les 10 premières pour le pilote fractions G4. La liste exacte se
resserrera avec le plan de la classe de démo (B7) : `python scripts/lesson_coverage.py` dit à
tout moment quelles racines ont une leçon, dans quel statut, et lesquelles manquent.

## 2. Quoi écrire ?

**Le plus simple : l'éditeur `/ops/lessons`** (compte relecteur ou super admin). Il affiche les
racines à couvrir, ouvre un formulaire par leçon (titre, 4 étapes, minutes, arabe optionnel) et
enregistre en `draft` avec la même validation. Les fichiers JSON restent possibles pour un import
en masse ou une revue en Git.

En fichier : un JSON par leçon dans `04_code/data/lessons/`, nommé `<CODE>.v1.json`. Copie
`_TEMPLATE.json`, puis remplis en **anglais** :

- `title_en` : ce que l'enseignant lit dans son plan (une ligne).
- 4 étapes, 10 à 15 minutes au total :
  - `warmup` (2 min) : une question posée à toute la classe, sans corriger.
  - `model` (4 min) : l'enseignant montre le geste en pensant à voix haute. Dis où pointer, quoi
    dire, dans quel ordre.
  - `guided` (4 min) : les élèves essaient en binôme ; dis ce que l'enseignant doit écouter
    (l'erreur typique) et quoi donner à ceux qui finissent.
  - `exit` (2 min) : une question de sortie par élève.
- Nombres en chiffres 0-9. Pas de « il faut » : des consignes directes à l'enseignant.
- `title_ar` et `body_ar` : laisse `null`. Le linguiste traduit dans son outil
  (`POST /linguist/lessons/{id}/arabic`) puis valide.

`MATH.G3.NF.UNIT_FRACTION.v1.json` est l'exemple de forme : relis-le, corrige-le, c'est le
gabarit de ton style.

## 3. Comment vérifier ?

```bash
cd 04_code
.venv/bin/python scripts/seed_lessons.py --dry-run   # forme : erreurs listées, rien écrit
.venv/bin/python scripts/seed_lessons.py             # charge (idempotent)
.venv/bin/python scripts/lesson_coverage.py          # quelles racines ont une leçon, statut
```

Une leçon chargée est `draft`. Elle apparaît déjà dans le plan (avec son statut) ; elle devient
`active` quand le linguiste a validé l'arabe et qu'un relecteur l'active (`/ops/review` ou
`POST /lessons/{id}/activate`).

## 4. Qui fait quoi (Q4)

| Étape | Qui | Où |
| --- | --- | --- |
| Rédiger l'EN | Nassim (ou un enseignant pilote) | `data/lessons/*.json` |
| Traduire et valider l'AR | linguiste | outil linguiste |
| Activer | relecteur de contenu ou super admin | file de revue |
| Relire la langue de l'exemple fourni | locuteur natif | bucket `07-tests-beta.md` |
