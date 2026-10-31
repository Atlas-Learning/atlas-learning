# 05 — Questions ouvertes

Ne pas trancher ces points dans le code. Les marquer `[À CLARIFIER]` et les remonter.

| # | Question | Bloque | Proposition par défaut |
| --- | --- | --- | --- |
| Q1 | Définition exacte de « débloqué » | B4 | Avant : mesuré et non maîtrisé. Après re-mesure ciblée : Elo ≥ 1500 et confiance ≥ 0,5 |
| Q2 | Nombre d'items par compétence pour une estimation exploitable en 10 min | B1, B2 | Lire `src/engine/stopping.py` et proposer une valeur |
| Q3 | Liste des compétences de l'unité pilote qui ont besoin d'une mini-leçon | B3 | Les racines produites par le plan de démo de la classe 4B |
| Q4 | Qui rédige et relit les mini-leçons (EN et AR) | B3 | Nassim rédige l'EN, le linguiste valide l'AR |
| Q5 | Jour et heure du message hebdomadaire, réglage par école ou par pays | B6 | Par école, défaut lundi 7 h heure locale (dimanche en Arabie saoudite) |
| Q6 | Correspondance Year (UK) ↔ Grade pour `Classroom.grade` | A1 | Year N = Grade N−1 |
| Q7 | Seuil de réponses avant qu'un item d'école puisse entrer en mesure | E3 | À fixer après le pilote |
| Q8 | Format de stockage des critères de succès d'un pilote | D6 | JSON libre sur `Organization`, liste `{label, status}` |
| Q9 | Prochains curriculums à importer | C2 | Selon les écoles ciblées par l'outbound |
| Q10 | Contenu des documents fournisseurs (DPA, réponses §5.5 ADEK, consentement parental) | D5 | À rédiger hors code ; l'écran affiche « à venir » tant qu'ils manquent |
| Q11 | Statut d'Atlas au regard de la Technology and AI Policy de l'ADEK | Commercial | Hors code ; aucune mention « approuvé ADEK » dans l'UI |
| Q12 | Mode tablette partagée si les élèves n'ont pas d'appareil | B1 | Hors périmètre du premier pilote |
| Q13 | ~~Provisioning des memberships `dept_lead` et `group_admin`~~ **Tranché le 2026-10-31** : attribution par email, SSO ou lien magique, voir `06-attribution-des-roles.md` | — | Reste : écran admin IT (I1) |
| Q15 | `template_key` des items déjà en base (banque antérieure à A2) : NULL, la clé n'est posée qu'à la génération (`code#rang`). Regénérer la banque (`generate_bank_deterministic.py --reset`) supprime les items et leurs réponses | A3 | Sur la démo : regénérer. En pilote : backfill par appariement énoncé ↔ générateur, à écrire si des réponses réelles existent |
| Q14 | ~~Lecture du curriculum par `group_admin` et `dept_lead`~~ **Tranché le 2026-10-31** : le choix du curriculum affiché est réservé au super admin Atlas (`POST /admin/curriculum?organization_id=`) ; les admins d'école le lisent ; les autres rôles le verront via la phase C | C2, C3 | — |
