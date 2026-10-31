# Mini-leçons (`data/lessons/*.json`)

Une leçon de 10 à 15 minutes par compétence **racine** du graphe, projetable ou imprimable
(écran E3). Le contenu est **éditorial** : rédigé par un humain (Q4 : Nassim rédige l'anglais,
le linguiste traduit et valide l'arabe). La machine ne rédige rien ; elle valide la forme et
suit le statut.

## Fichier

Un fichier = une leçon. Nom = sa clé stable, ex. `MATH.G3.NF.UNIT_FRACTION.v1.json`.

```json
{
  "competency": "MATH.G3.NF.UNIT_FRACTION",
  "title_en": "…", "title_ar": null,
  "duration_min": 12,
  "version": 1,
  "steps": [
    {"kind": "warmup", "minutes": 2, "body_en": "…", "body_ar": null},
    {"kind": "model",  "minutes": 4, "body_en": "…"},
    {"kind": "guided", "minutes": 4, "body_en": "…"},
    {"kind": "exit",   "minutes": 2, "body_en": "…", "items": []}
  ]
}
```

- `steps` dans l'ordre `warmup → model → guided → exit` ; `minutes` > 0 ; `body_en` obligatoire.
- `body_ar` et `title_ar` optionnels à la rédaction : le linguiste les complète dans l'outil
  (`POST /linguist/lessons/{id}/arabic`) ou ici, puis valide (`…/validate`).
- Les nombres restent en chiffres 0-9 dans les deux langues (convention E7).
- Un fichier dont le nom commence par `_` est ignoré (`_TEMPLATE.json`).

## Cycle

`draft` (EN rédigé) → `linguist_validated` (AR complet, validé) → `active` (servie dans le plan,
super admin ou relecteur). Re-seeder un fichier ne rabaisse jamais le statut, sauf si son arabe a
changé (retour en `draft`, à revalider).

```bash
python scripts/seed_lessons.py [--dry-run]
```

## À rédiger (Q3)

La liste des compétences racines à couvrir pour l'unité pilote vient du plan de la classe de
démo (B7). `MATH.G3.NF.UNIT_FRACTION.v1.json` est un **exemple** de forme, à relire comme le reste.
