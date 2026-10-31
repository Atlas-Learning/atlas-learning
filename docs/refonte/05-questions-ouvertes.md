# 05 — Questions ouvertes

Ne pas trancher ces points dans le code. Les marquer `[À CLARIFIER]` et les remonter.

| # | Question | Bloque | Proposition par défaut |
| --- | --- | --- | --- |
| Q1 | Définition exacte de « débloqué » | B4 | **Proposition par défaut implémentée** (`proof_service.compute_proofs`) : avant Elo < 1500 ; après re-mesure ciblée Elo ≥ 1500 ET confiance ≥ 0,5 ; absent = `not_rechecked`, hors dénominateur. À confirmer avant le pilote |
| Q2 | Nombre d'items par compétence pour une estimation exploitable en 10 min | B1, B2 | Lire `src/engine/stopping.py` et proposer une valeur. B1 livré avec les règles d'arrêt existantes (`StopConfig`) : un check-in `full` sans `competency_ids` couvre toute la banque active ; à resserrer sur l'unité pilote quand Q3 sera tranchée |
| Q3 | Liste des compétences de l'unité pilote qui ont besoin d'une mini-leçon | B3 | **Mode d'emploi dans `08-redaction-lecons.md`** : par défaut les 10 racines les plus débloquantes du référentiel ; `scripts/lesson_coverage.py` suit la couverture ; à resserrer avec le plan de démo (B7) |
| Q4 | Qui rédige et relit les mini-leçons (EN et AR) | B3 | Nassim rédige l'EN (`data/lessons/<CODE>.v1.json`, gabarit `_TEMPLATE.json`), le linguiste traduit et valide l'AR dans son outil, un relecteur active — détail dans `08-redaction-lecons.md` |
| Q5 | ~~Jour et heure du message hebdomadaire~~ **Tranché le 2026-10-31** : par école (`School.country / plan_mail_weekday / plan_mail_hour / timezone`, migration 0029), défauts dérivés du pays : dimanche 7 h Riyad pour SA, lundi 7 h ailleurs, fuseau du pays sinon UTC. `PATCH /schools/{id}/settings` (admins de l'école), cron horaire `scripts/send_weekly_plan.py`, `POST /admin/notify/weekly-plan` (super admin, dry-run, forçage) | — | — |
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
| Q17 | Intervalle exposé sur la carte de preuve : demi-largeur provisoire `150 × (1 − confiance) + 25` Elo (`proof_service.ci_half_width`), même bande que la restitution | B4 → pilote | Remplacer par une erreur-type calibrée sur cohorte réelle |
| Q14 | ~~Lecture du curriculum par `group_admin` et `dept_lead`~~ **Tranché le 2026-10-31** : le choix du curriculum affiché est réservé au super admin Atlas (`POST /admin/curriculum?organization_id=`) ; les admins d'école le lisent ; les autres rôles le verront via la phase C | C2, C3 | — |
