# 06 — Attribution des rôles hors roster (dept_lead, group_admin)

Décision du 2026-10-31 (Q13) : une seule architecture, qui fonctionne **avec rostering et SSO**
comme **sans SSO**. Code : `src/rbac/grants.py`, API `/admin/roles`, CLI `scripts/grant_role.py`.

## Principe

Le roster (Google, OneRoster, Wonde) ne connaît que élève, enseignant, admin IT. Les rôles de
la refonte sont attribués par un humain, **par email** — l'identité stable du projet :

| Rôle | Portée | Qui attribue |
| --- | --- | --- |
| `dept_lead` | une école (`Membership.school_id`) + des niveaux (`dept_lead_scope`) | ped_admin de l'école, admin IT de l'organisation, super admin |
| `group_admin` | une organisation (`Membership.organization_id`) | admin IT de l'organisation, super admin |

L'attribution crée le compte s'il n'existe pas (sans `external_ref`), ou s'appuie sur le compte
existant. Elle est idempotente (la liste de niveaux d'un `dept_lead` **remplace** la précédente),
auditée (`role.grant`, `role.revoke`) et réversible (`DELETE /admin/roles/{membership_id}`).

## Avec SSO et rostering

- L'IdP ne provisionne jamais un compte (`/oauth/{provider}/callback` exige un email connu).
  Le compte créé par l'attribution est retrouvé **par email** à la première connexion SSO.
- Si la personne est aussi dans l'annuaire (prof, admin IT), la sync **adopte** le compte par
  email et pose son `external_ref` ; la membership attribuée n'est pas touchée (la sync n'efface
  jamais une membership, elle n'en ajoute que pour les rôles qu'elle connaît).
- Un compte créé par attribution et jamais vu par l'annuaire n'a pas d'`external_ref` : il est
  **protégé du déprovisioning** (règle « compte bootstrap »).
- Un compte adopté puis disparu de l'annuaire est désactivé comme tout compte rosterisé.
  L'attribution ne le ressuscite pas (`GrantError`) : c'est l'annuaire qui tranche.

## Sans SSO

- La personne demande un lien magique sur la page de connexion (`POST /admin/request-link`,
  réponse constante anti-énumération). Rôles autorisés : `grants.MAGIC_LINK_ROLES` =
  `super_admin`, `group_admin`, `dept_lead`. Même flux single-use que le super admin
  (`GET /admin/login` valide sans consommer → `POST /admin/login/confirm` consomme).
- Avant tout SMTP : `scripts/grant_role.py … --link` mint le lien à remettre à la main.
- Le ped_admin, l'enseignant et l'admin IT restent SSO (ou `/dev/login` en dev) : hors périmètre
  de cette décision.

## Opérations

```bash
# depuis 04_code/
python scripts/grant_role.py --email coord@ecole.ae --role dept_lead --school "École A" --grades 4,5 --link
python scripts/grant_role.py --email dir@groupe.ae --role group_admin --org groupe.ae
python scripts/grant_role.py --list --org groupe.ae
python scripts/grant_role.py --revoke <membership_id>
```

API (admin IT de l'organisation ou super admin ; le ped_admin pour les `dept_lead` de son école, avec `school_id`) :

| Méthode | Route | Corps / paramètres |
| --- | --- | --- |
| `POST` | `/admin/roles` | `{email, role, school_id?, organization_id?, grades?}` |
| `GET` | `/admin/roles?organization_id=` ou `?school_id=` | — |
| `DELETE` | `/admin/roles/{membership_id}` | — |

Le niveau d'une classe (qui définit la portée effective d'un `dept_lead`) vient du roster
(OneRoster `grades`) ou de `PATCH /classrooms/{id}/grade` par un admin de l'école.

## Reste à faire

- Écran admin IT (I1) pour attribuer et révoquer sans CLI : `web/lib/api.ts` expose déjà
  `adminRoles`, `adminGrantRole`, `adminRevokeRole`.
- Les écrans C1 (`/department/[schoolId]`) et G1 (`/group/[organizationId]`) sont en place
  (navigation, i18n EN/AR, données de `/me` et agrégats école) ; leur contenu métier arrive avec
  les API des tickets D1 et D3.
