# 02 — Rôles et écrans

## Rôles

Base : enum `Role` dans `src/models/base.py`, portée via `Membership` (`organization_id`, `school_id`) dans `src/models/org.py`, contrôles dans `src/rbac/authz.py`.

| Persona | Rôle | Portée | Connexion | Statut |
| --- | --- | --- | --- | --- |
| Super admin | `super_admin` | Global | Lien magique | Existe |
| Relecteur de contenu | `content_reviewer` | Global, banque d'items | Lien magique (`/admin/request-link`) ou SSO | Créé (`0024`), onboarding `scripts/onboard_staff.py` |
| Linguiste | `linguist` | Global, arabe de la banque | Lien magique | Existe |
| Admin IT de l'école | `it_admin` | Organisation ou école | SSO OIDC | Existe |
| Direction | `ped_admin` | École | SSO | Existe |
| Enseignant | `teacher` | Ses classes (`TeacherClassroom`) | SSO | Existe |
| Élève | `student` | Lui-même | SSO + code de check-in | Existe, code à ajouter |
| Parent | `parent` | Ses enfants (`ParentStudent`) | Lien magique | Existe |
| Coordinateur maths | `dept_lead` | École + liste de niveaux | SSO, ou lien magique sans SSO | Créé (A1) — attribué hors roster, voir `06` |
| Admin groupe scolaire | `group_admin` | Organisation (toutes ses écoles) | SSO, ou lien magique sans SSO | Créé (A1) — attribué hors roster, voir `06` |

## Matrice d'accès aux nouveaux objets

L = lecture, E = écriture, — = aucun accès.

| Objet | teacher | dept_lead | ped_admin | group_admin | it_admin | super_admin | content_reviewer | linguist |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CheckIn de sa classe | E | L (ses niveaux) | — | — | — | L | — | — |
| WeeklyPlan, PlanAction | E (ses classes) | L (ses niveaux) | — | — | — | L | — | — |
| Proof par élève | L (ses classes) | L (ses niveaux) | — | — | — | L | — | — |
| Proof agrégée par niveau | L | L | L | L (par école) | — | L | — | — |
| DepartmentDecision | L | E | L | — | — | L | — | — |
| Adoption (usage par classe) | — | L | L | L (par école) | L | L | — | — |
| MiniLesson Atlas | L | L | — | — | — | E | E | E (arabe) |
| Item d'école (phase E) | E (les siens) | E (partage département) | — | — | — | E | E | E (arabe) |
| ItemFlag | E | E | — | — | — | E | E | E |
| CurriculumFramework, mapping | L (publié) | L | L | L | — | E | — | — |
| Choix du curriculum affiché par l'école (`POST /admin/curriculum`) | — | — | — | — | — | E (Q14) | — | — |
| Attribution dept_lead / group_admin (`/admin/roles`) | — | — | E (dept_lead de son école) | — | E (son organisation) | E | — | — |
| Réglages SSO, roster, rétention | — | — | — | — | E | E | — | — |

`ped_admin` ne voit jamais de résultat par enseignant ni par élève nominatif dans les vues agrégées (invariant 4).

## Écrans

Chaque écran a sa maquette dans `maquettes/`. « Point de départ » = code existant à faire évoluer.

### Enseignant

**E1 · Cette semaine** — `maquettes/Main.dc.html`, version arabe `maquettes/Main-AR.dc.html`
- Route : `/teacher` (redirige vers la classe par défaut) et `/teacher/[classroomId]/week`
- API : `GET /classrooms/{id}/plan?week=YYYY-MM-DD`, `GET /classrooms/{id}/proofs?since=`
- Acceptation :
  - affiche 2 à 4 `PlanAction` triées par nombre d'élèves débloquables ;
  - chaque action montre cause racine → compétence bloquée, la phrase « parce que », le badge mesuré / partiellement estimé, les membres ;
  - bandeau de la dernière preuve disponible ;
  - « Lancer un check-in » est l'action principale ;
  - compteur de boucles bouclées visible par l'enseignant seul ;
  - aucun plan : état vide qui propose le premier check-in.

**E2 · Check-in projeté** — `maquettes/Checkin.dc.html`
- Route : `/teacher/[classroomId]/checkin/[checkinId]`
- API : `POST /classrooms/{id}/checkins` `{kind: "full" | "targeted", action_id?}` → `{id, code}` ; `GET /checkins/{id}/progress` ; `POST /checkins/{id}/close`
- Acceptation :
  - code à 4 chiffres affiché en grand, unique parmi les check-ins ouverts ;
  - `progress` ne renvoie que des compteurs (rejoints, en cours, terminés, absents) et une tuile anonyme par élève (invariant 5) ;
  - à la clôture, génération du plan (`full`) ou de la preuve (`targeted`) en moins d'une minute.

**E3 · Groupe et mini-leçon** — `maquettes/Group.dc.html`
- Route : `/teacher/[classroomId]/actions/[actionId]`
- API : `GET /plan-actions/{id}`, `PATCH /plan-actions/{id}/members`, `POST /plan-actions/{id}/done`, `POST /plan-actions/{id}/dismiss`, `GET /lessons/{id}`
- Point de départ : `web/components/DiagnosisBlock.tsx`, `RemediationModal.tsx`, `POST /remediation/preview`
- Acceptation :
  - liste des élèves avec l'erreur typique observée et l'état de la compétence racine ;
  - ajout ou retrait d'un élève enregistré avec l'auteur ;
  - mini-leçon en étapes, EN et AR, avec boutons projeter et imprimer ;
  - « Marquer comme enseignée » crée un check-in `targeted` planifié pour les membres.

**E4 · Carte de preuve** — `maquettes/Proof.dc.html`
- Route : `/teacher/[classroomId]/actions/[actionId]/proof`
- API : `GET /plan-actions/{id}/proof`
- Point de départ : `GET /schools/{school_id}/proof` (existant, niveau école)
- Acceptation :
  - par élève : position avant, position après, intervalle de confiance, état (débloqué, inchangé, non re-mesuré) ;
  - en-tête « X sur Y ont débloqué » calculé uniquement sur les élèves re-mesurés ;
  - suggestions pour les inchangés (cause en amont) et les absents (ajout au prochain re-check) ;
  - partage au coordinateur.

**E5 · Ma classe** — `maquettes/Class.dc.html`
- Route : `/teacher/[classroomId]` (refonte de la page existante)
- API : `GET /classrooms/{id}/students`, `GET /classrooms/{id}/gaps` (existants)
- Acceptation : matrice élèves × compétences de l'unité avec 4 états (maîtrisé, prochaine étape, estimé, non mesuré), groupe de la semaine, compétences débloquées ce trimestre.

**E6 · Fiche élève** — `maquettes/Student-profile.dc.html`
- Route : `/teacher/[classroomId]/s/[studentId]` (refonte)
- API : `GET /students/{id}/profile`, `/trajectory`, `/tutor` (existants)
- Acceptation : chaîne causale en héros (maîtrisé → cause racine → où ça se voit), maîtrise par compétence avec fourchette, historique des déblocages, aperçu du message famille.

**E7 · Exercise builder (phase E)** — `maquettes/Builder.dc.html`
- Route : `/teacher/lessons/new`
- API : `POST /school-items`, `POST /school-items/{id}/check`
- Acceptation : compétence obligatoire, format (MCQ, NUMERIC, SHORT), réponse vérifiée par calcul quand c'est possible, unicité de la bonne réponse en MCQ, partage moi seul ou département, mention claire « hors mesure jusqu'à revue ».

### Élève

**S1 · Rejoindre** — `maquettes/Student-join.dc.html`
- Route : `/student/join`
- API : `POST /checkins/join {code}` → `{session_id}` (crée une `AssessmentSession` liée au check-in)
- Acceptation : compte SSO déjà connecté, refus clair si code inconnu, clos, ou si l'élève n'est pas dans la classe.

**S2 · Session** — `maquettes/Student-session.dc.html`
- Route : `/student` (existant)
- API : `GET /sessions/{id}/next-item`, `POST /sessions/{id}/responses` (existants)
- Acceptation : pas de minuteur, pas de score, progression en points, bascule AR, maths toujours LTR.

**S3 · Débloqué** — `maquettes/Student-unlocked.dc.html`
- Fin de session : compétence débloquée mise en avant (or), puis « en progrès » et « prochaine étape ». Jamais de rouge, jamais de note.

### Parent

**P1 · Prochaine étape (mobile)** — `maquettes/Family.dc.html`
- Route : `/parent/[studentId]` (refonte)
- API : `GET /parent/children` (existant) + `GET /students/{id}/family-summary`
- Acceptation : débloqué ce mois, en cours, activité de 5 min, EN/AR, aucun classement. Envoi mensuel par `src/notify/`.

### Coordinateur maths

**C1 · Revue de département** — `maquettes/Department.dc.html`
- Route : `/department/[schoolId]?grade=4`
- API : `GET /schools/{id}/department-review?grade=&month=`, `POST /schools/{id}/department-decisions`
- Acceptation : causes racines communes × classes avec effectifs, actions menées et effet mesuré par leçon et classe (sans nom d'enseignant), décision consignée, la revue suivante s'ouvre sur l'effet de la décision.

### Direction

**D1 · Preuves par niveau** — `maquettes/Leadership.dc.html`
- Route : `/admin/[schoolId]/report` (refonte)
- API : `GET /schools/{id}/overview`, `GET /schools/{id}/proof` (existants, à étendre)
- Acceptation : enseignants actifs (total école), boucles bouclées, déblocages mesurés, tableau par niveau, pack de preuves exportable. Aucun résultat par enseignant.

**D2 · Classes et licences** — `maquettes/Licences.dc.html`
- Route : `/admin/[schoolId]/classes` (refonte)
- API : licences existantes (`src/licensing/`, `POST /admin/organizations/{id}/seats`) + statut d'usage par classe
- Acceptation : sièges utilisés / total, statut par classe (actif, enseignant invité, non démarré), dernier check-in. Usage seulement, pas de résultats.

### Groupe scolaire

**G1 · Vue multi-écoles** — `maquettes/School-group.dc.html`
- Route : `/group/[organizationId]`
- API : `GET /organizations/{id}/overview`
- Acceptation : par école : curriculum, niveaux, classes actives, déblocages par élève, causes communes entre écoles. Comparaison sur le graphe, jamais sur des scores bruts de curriculum.

### Admin IT

**I1 · SSO et roster** — `maquettes/IT-sso.dc.html`
- Route : `/it` (refonte)
- API : `/admin/integration`, `/admin/rostering/sync`, `/admin/rostering/runs`, `/admin/setup` (existants)
- Acceptation : 4 étapes (OIDC, source de roster, domaines, accès parents), avertissements de synchronisation actionnables, test de connexion.

**I2 · Données et conformité** — `maquettes/IT-data.dc.html`
- Route : `/it/data`
- API : `/admin/export`, `/admin/students/{id}/erase`, rétention et legal hold (`src/compliance/`, `scripts/`)
- Acceptation : région d'hébergement, données collectées et non collectées, réglage de rétention, export et effacement par élève, documents fournisseurs. Les documents eux-mêmes sont `[À CLARIFIER]` (à rédiger).

### Équipe Atlas

**O1 · Écoles et pilotes** — `maquettes/Admin-tenants.dc.html`
- Route : `/ops/tenants`
- API : `GET /ops/tenants`, `GET /ops/tenants/{id}/pilot`
- Acceptation : étape commerciale par école (démo, onboarding, pilote semaine N, licence), classes en boucle hebdo, critères de succès du pilote avec leur état, brouillon de rapport de pilote.

**O2 · File de revue** — `maquettes/Admin-review.dc.html` (super admin et relecteur)
- Route : `/ops/review`
- API : `GET /ops/review?source=flag|validation|school|arabic`, `POST /ops/templates/{key}/quarantine`, `POST /items/{id}/transition`
- Acceptation : une file unique, filtres par source, détail EN/AR côte à côte, regroupement par gabarit, quarantaine en masse, rappel du cycle de statuts. Le relecteur ne voit pas les actions réservées au super admin.

**O3 · Mapping d'un curriculum** — `maquettes/Admin-curriculum.dc.html`
- Route : `/ops/curricula/[frameworkId]`
- API : `POST /ops/curricula` (import), `GET/PUT /ops/curricula/{id}/mappings`, `GET /ops/curricula/{id}/coverage`, `POST /ops/curricula/{id}/publish`
- Point de départ : `scripts/` du crosswalk, `data/crosswalk_fractions_draft.json`, `GET/POST /admin/curriculum`
- Acceptation : liste des référentiels avec statut brouillon / publié, table compétence ↔ attendu avec alignement et confiance, édition d'une ligne, aperçu du libellé vu par l'école, publication bloquée tant que la couverture n'est pas revue.

**O4 · Validation de l'arabe** — `maquettes/Linguist.dc.html`
- Route : `/linguist` (refonte)
- API : `/linguist/queue`, `/linguist/items/{id}`, `/linguist/items/{id}/arabic`, `/validate`, `/flag` (existants)
- Acceptation : source EN et texte AR éditable côte à côte, contrôles automatiques (`ar_fidelity_errors`), glossaire, validation ou renvoi commenté.
