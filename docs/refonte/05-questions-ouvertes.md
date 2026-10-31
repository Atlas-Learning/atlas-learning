# 05 — Questions ouvertes

Ne pas trancher ces points dans le code. Les marquer `[À CLARIFIER]` et les remonter.

| # | Question | Bloque | Proposition par défaut |
| --- | --- | --- | --- |
| Q1 | Définition exacte de « débloqué » | B4 | Avant : mesuré et non maîtrisé. Après re-mesure ciblée : Elo ≥ 1500 et confiance ≥ 0,5 |
| Q2 | Nombre d'items par compétence pour une estimation exploitable en 10 min | B1, B2 | Lire `src/engine/stopping.py` et proposer une valeur. B1 livré avec les règles d'arrêt existantes (`StopConfig`) : un check-in `full` sans `competency_ids` couvre toute la banque active ; à resserrer sur l'unité pilote quand Q3 sera tranchée |
| Q3 | Liste des compétences de l'unité pilote qui ont besoin d'une mini-leçon | B3 | Les racines produites par le plan de démo de la classe 4B |
| Q4 | Qui rédige et relit les mini-leçons (EN et AR) | B3 | Nassim rédige l'EN, le linguiste valide l'AR |
| Q5 | Jour et heure du message hebdomadaire, réglage par école ou par pays | B6 | Par école, défaut lundi 7 h heure locale (dimanche en Arabie saoudite). B2 date le plan au lundi ISO de la semaine de clôture (`plan_service.week_start_of`) ; si la semaine commence le dimanche pour l'école, seule la date affichée changera |
| Q6 | Correspondance Year (UK) ↔ Grade pour `Classroom.grade` | A1 | Year N = Grade N−1 |
| Q7 | Seuil de réponses avant qu'un item d'école puisse entrer en mesure | E3 | À fixer après le pilote |
| Q8 | Format de stockage des critères de succès d'un pilote | D6 | JSON libre sur `Organization`, liste `{label, status}` |
| Q9 | Prochains curriculums à importer | C2 | Selon les écoles ciblées par l'outbound |
| Q10 | Contenu des documents fournisseurs (DPA, réponses §5.5 ADEK, consentement parental) | D5 | À rédiger hors code ; l'écran affiche « à venir » tant qu'ils manquent |
| Q11 | Statut d'Atlas au regard de la Technology and AI Policy de l'ADEK | Commercial | Hors code ; aucune mention « approuvé ADEK » dans l'UI |
| Q12 | Mode tablette partagée si les élèves n'ont pas d'appareil | B1 | Hors périmètre du premier pilote |
| Q13 | ~~Provisioning des memberships `dept_lead` et `group_admin`~~ **Tranché le 2026-10-31** : attribution par email, SSO ou lien magique, voir `06-attribution-des-roles.md` | — | Reste : écran admin IT (I1) |
| Q15 | ~~`template_key` de la banque antérieure à A2~~ **Tranché le 2026-10-31** : `scripts/backfill_template_keys.py` apparie (compétence, énoncé, réponse) avec le rendu des générateurs et pose la clé sans toucher aux items, réponses ni calibration ; les non-appariés et ambigus sont listés, jamais inventés (`src/items/templates.py`) | — | Lancer le backfill avant toute régénération (A3) |
| Q16 | ~~`observed_error` d'un membre~~ **Tranché le 2026-10-31** : `response.selected` (0027) mémorise l'option choisie ; à la génération du plan, l'erreur la plus fréquente de l'élève sur la compétence bloquée pendant le check-in est écrite (« What is 1/3 + 1/6? → 2/9 · 3 of 4 items wrong »). Les réponses antérieures à 0027 n'ont pas d'option : pas d'erreur observée pour elles | — | — |
| Q14 | ~~Lecture du curriculum par `group_admin` et `dept_lead`~~ **Tranché le 2026-10-31** : le choix du curriculum affiché est réservé au super admin Atlas (`POST /admin/curriculum?organization_id=`) ; les admins d'école le lisent ; les autres rôles le verront via la phase C | C2, C3 | — |
