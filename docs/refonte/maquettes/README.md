# Maquettes

22 écrans de référence, exportés du canevas Design (https://claude.ai/artifact/LzgwrL9UKM8wMqmXRyC8ns).

## Format

Chaque `.dc.html` est une page HTML avec styles en ligne. Les balises `<x-dc>`, `<helmet>`, `<sc-for>` et le bloc `<script type="text/x-dc">` appartiennent au moteur du canevas : ils ne s'exécutent pas hors du canevas. Pour lire une maquette, regarder la structure, les textes et les styles en ligne ; pour les listes générées (`<sc-for>`), les données sont dans `renderVals()` en bas du fichier.

Ce sont des références visuelles. Reconstruire chaque écran avec Tailwind et les composants de `web/components/`, en respectant les tokens de `web/tailwind.config.ts`. Toutes les données affichées sont fictives.

## Écrans par persona

| Persona | Fichiers |
| --- | --- |
| Enseignant | `Main.dc.html`, `Checkin.dc.html`, `Group.dc.html`, `Proof.dc.html`, `Class.dc.html`, `Student-profile.dc.html`, `Builder.dc.html`, `Main-AR.dc.html` |
| Élève | `Student-join.dc.html`, `Student-session.dc.html`, `Student-unlocked.dc.html` |
| Parent | `Family.dc.html` |
| Coordinateur | `Department.dc.html` |
| Direction | `Leadership.dc.html`, `Licences.dc.html` |
| Groupe scolaire | `School-group.dc.html` |
| Admin IT | `IT-sso.dc.html`, `IT-data.dc.html` |
| Équipe Atlas | `Admin-tenants.dc.html`, `Admin-review.dc.html`, `Admin-curriculum.dc.html`, `Linguist.dc.html` |

Le texte arabe de `Main-AR.dc.html` et `Linguist.dc.html` doit être relu par un locuteur natif avant de servir de référence de copy.
