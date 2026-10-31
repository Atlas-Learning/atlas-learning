# Refonte Atlas — point d'entrée

Ce dossier contient tout ce qu'il faut pour implémenter la refonte avec Claude Code.

| Fichier | Contenu |
| --- | --- |
| `00-ecarts-depot.md` | Ce qui diffère entre ce spec et le dépôt réel : à lire avant la phase A |
| `01-produit.md` | Le concept, la boucle enseignant, les objets métier, les règles produit |
| `02-roles-et-ecrans.md` | Les 11 personas, leurs rôles RBAC, les 22 écrans avec route, API et critères d'acceptation |
| `03-modele-de-donnees.md` | Les tables à ajouter ou modifier, migration par migration |
| `04-plan.md` | Le plan en 5 phases et ~25 tickets, avec fichiers à toucher et tests |
| `05-questions-ouvertes.md` | Ce qui n'est pas tranché : à ne pas inventer |
| `06-attribution-des-roles.md` | Comment `dept_lead` et `group_admin` sont attribués et se connectent, avec ou sans SSO |
| `07-tests-beta.md` | Ce qui attend la première passe bêta : relecture arabe, vérification des écrans en navigateur |
| `maquettes/` | Les 22 écrans de référence (`.dc.html`) |

Documents de pilotage côté produit (non nécessaires pour coder) :
- Doc stratégique : https://claude.ai/artifact/9cStChrGPBsnst52ZWVsaq
- Canevas des maquettes : https://claude.ai/artifact/LzgwrL9UKM8wMqmXRyC8ns

## Ordre de lecture

1. `../../CLAUDE.md` (invariants) puis `00-ecarts-depot.md`
2. `01-produit.md`
3. Le ticket en cours dans `04-plan.md`, puis les sections de `02` et `03` qu'il cite

## Démarrer une session Claude Code

Prompt type pour un ticket :

```
Lis CLAUDE.md et docs/refonte/README.md.
Implémente le ticket A1 de docs/refonte/04-plan.md.
Commence par lire les fichiers cités, propose ton plan en 5 lignes, puis code.
Termine par make test et un compte rendu : ce qui est fait, ce qui reste, les [À CLARIFIER].
```

Phases, dans l'ordre :

| Phase | Objet | Pourquoi maintenant |
| --- | --- | --- |
| A | Rôles et file de revue | Fiabilise la banque existante, débloque le coordinateur |
| B | Boucle enseignant | Cœur du produit, nécessaire à la démo et au pilote |
| C | Curriculums dynamiques | Nécessaire avant l'outbound : chaque école voit son référentiel |
| D | Vues département, direction, groupe, famille, IT | Nécessaire au pilote et à la conversion |
| E | Exercise builder | Après le premier pilote |
