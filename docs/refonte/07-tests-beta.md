# 07 — Bucket « tests bêta » (première passe)

Ce qui est livré en code mais n'a pas encore été vérifié par un humain ou en navigateur. À
dérouler d'un bloc lors de la première passe bêta, pas au fil des tickets (décision 2026-10-31 :
« on finit le dev et on passera aux interfaces »).

## Relecture par un locuteur natif

| Quoi | Où | Note |
| --- | --- | --- |
| Les 37 gabarits d'énoncé arabes et les 4 options textuelles | `src/items/arabic_deterministic.py` (`_STEMS`, `_OPTIONS`) | Toute correction se fait dans le code puis `scripts/regenerate_template.py` ; la fidélité (nombres, structure) est garantie par test, la langue ne l'est pas |
| Textes AR des maquettes `Main-AR` et `Linguist` | `docs/refonte/maquettes/` | Référence de copy, pas de code |
| Clés i18n ajoutées en phase A (`review.*`, `department.*`, `group.*`, `staff.*`, `curriculum.readonly`) | `web/lib/i18n.ts` | Rédigées sans relecture |
| E-mail `staff_login_email` (partie arabe) | `src/notify/templates.py` | |

## Vérification en navigateur (EN et AR, RTL)

| Écran | Route | Compte de test |
| --- | --- | --- |
| O2 file de revue | `/ops/review` | `scripts/onboard_staff.py --role content_reviewer` et un super admin |
| C1 revue de département (structure) | `/department/[schoolId]` | `scripts/grant_role.py --role dept_lead` |
| G1 vue groupe (structure) | `/group/[organizationId]` | `scripts/grant_role.py --role group_admin` |
| Connexion sans SSO | `/staff/login` → e-mail → `/login/confirm` | un des comptes ci-dessus, SMTP factice |
| Page IT : sélecteur de curriculum en lecture seule | `/it` | it_admin |

Pré-requis : `make migrate`, `scripts/seed_referentiel.py`, `scripts/generate_bank_deterministic.py`
(pose les clés de gabarit et la proposition arabe), `scripts/provision_demo.py`, `OIDC_DEV_LOGIN=1`.

## Points à observer pendant la passe

- Aucun rouge pour une lacune ; hachure pour l'estimé (invariant 9).
- Aucun nom d'élève sur un écran projeté (invariant 5) — à vérifier dès les écrans de la phase B.
- Les actions réservées au super admin n'apparaissent pas pour le relecteur (O2).
