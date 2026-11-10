# Rapport hebdomadaire Premier League – procédure

Lue par la tâche programmée de Claude (mardi matin). Le VPS OVH collecte les
matchs chaque nuit (`run.sh`) et copie `reports/**/*.pdf` vers Google Drive toutes
les heures (`sync_drive.sh`) : la tâche ne touche ni au VPS ni à Drive.

## 1. Préparer

```bash
pip install -q --break-system-packages -r requirements-report.txt
python report.py --pending --ready --limit 3   # au plus 3 journées prêtes, ou AUCUNE
```

`--ready` : seulement les journées dont tous les matchs ont leurs données WhoScored (ou ont été
abandonnés après 5 essais). Au plus 3 journées par passage pour ménager le quota.

`AUCUNE` : rien de nouveau. Arrêter là et le dire en une phrase.

Sinon, pour **chaque** journée N listée (ordre croissant), faire les étapes 2 à 5.

## 2. Graphes et chiffres

```bash
python report.py --round N        # -> out/JN/*.webp + out/JN/summary.json
```

## 3. Rédiger `out/JN/analysis.json`

Lire `out/JN/summary.json` en entier, puis écrire :

```json
{
  "intro": ["2 paragraphes : le fil rouge de la journée, la surprise au regard du xG, le match marquant (pour une journée ancienne, rester sur ce que dit summary.json, sans référence à la suite de la saison)"],
  "matches": {
    "<matchId>": {
      "headline": "une phrase qui dit ce qui s'est passé",
      "paragraphs": ["le scénario (buts, tournants)", "ce que disent les chiffres (xG, occasions, heatmaps)",
                     "Avec et sans ballon : … (seulement si structure n'est pas null)"],
      "keys": ["3 points courts : joueur clé avec sa note, un chiffre fort, un point faible ou un fait notable"]
    }
  }
}
```

Règles :
- Français simple, pour un fan qui n'est pas analyste. Phrases courtes. Pas d'anglicismes inutiles
  (xG, xGOT et centile sont expliqués sur la page).
- **Chaque chiffre cité vient de `summary.json`.** Aucun contexte inventé (classement, blessures,
  transferts, séries) ; `insights_en` de FotMob seulement si l'équipe concernée est nommée dans la phrase.
- Utiliser ce qui rend le match compréhensible : xG par période, xG coups de pied arrêtés / jeu,
  grosses occasions ratées, `shape` (hauteur du bloc et de la ligne défensive en mètres depuis son but),
  `final_third_share_pct`, `attacking_zones`, `momentum_phases`, cartons rouges.
- `structure` (données WhoScored, peut être `null` si le match n'a pas été récupéré) : `ppda`
  (bas = pressing intense), `high_regains` (ballons récupérés dans le camp adverse),
  `defensive_actions_avg_height_m` (hauteur du bloc sans ballon), `possession_block_height_m`,
  `pass_accuracy_open_play_pct`, `top_pass_links` (duos de passeurs). Le 3e paragraphe commence par
  « Avec et sans ballon : » et dit comment chaque équipe a pressé/défendu et construit. Comparaisons
  « le plus … de la journée » : vérifier sur les 20 équipes.
- Contexte saison (données arrêtées à la journée, `data_until`) :
  - `context.<side>.habits.deviations` : écarts nets à la moyenne des matchs précédents de l'équipe
    (valeur, moyenne, nombre de matchs). C'est souvent la clé d'un match (« Forest a eu 22 % du
    ballon contre 48 % d'habitude »).
  - `context.<side>.form` : 5 derniers matchs (résultats, xG pour/contre).
  - `xg_table` (au niveau de la journée) : points, xPts, écart, rang xG. Un 3e paragraphe d'intro
    peut en tirer 1 ou 2 enseignements (sur- ou sous-performance nette).
- Création (si `structure`) : `key_passes`, `box_entries` (par couloir), `shots_after_regain_10s`
  et `goals_after_regain_10s` (contres), `fast_shots`.
- `substitutions` (minute, entrant, sortant, blessure) : citer un changement quand il a pesé
  (but ou passe décisive d'un entrant, blessure qui change le match). Les entrants figurent dans
  les graphes (cercles creux) et dans `players[*].sub_in`.
- `goalkeepers` : arrêts, xGOT subis, buts évités, erreurs menant à un but. Un gardien décisif
  (buts évités nettement positifs) ou fautif (erreur, buts évités très négatifs) mérite une ligne.
- `matchup` : forces/faiblesses de chaque équipe sur la saison (rangs parmi les 20). Utile pour
  expliquer un match (« la meilleure défense de la ligue a cédé sur coups de pied arrêtés, sa
  faiblesse : 19e »). Ne pas tout recopier, c'est affiché.
- `team_of_round` : l'équipe type est affichée automatiquement, pas besoin de la commenter.
- Points forts : `players[*].profile.strengths`, `profile.similar` (profils proches),
  `profile.history` (notes match par match) (centiles saison par poste) quand ils expliquent
  ce qui s'est passé (ex. un milieu à 95 en passes qui cassent les lignes qui a fait le match).
- « moins bien noté du match » : vérifier sur **tous** les joueurs des deux équipes.
- Format des nombres : virgule décimale (1,43), « 62 % », minutes « 90+2 ».
- Pas de tirets d'incise, pas de « non pas X mais Y », pas de formules toutes faites.

Avant de continuer, relire chaque nombre du texte contre `summary.json` (script Python si besoin).

## 4. Page, PDF, registre

```bash
python render.py --round N --pdf  # -> out/JN/index.html + reports/<saison>/PL <saison> - Journee NN.pdf
```

Regarder une fois la page à largeur téléphone (capture `google-chrome --headless=new
--screenshot --window-size=400,2600`) et corriger ce qui est visiblement cassé.

## 5. Publier

- Artefact (outil claude-artifacts, `publish_files` avec `out/JN/index.html` servi en `index.html`) :
  - si `reports/<saison>/manifest.json` a déjà un `artifact` pour N : republier ce slug
    (`get_artifact` pour la version de base) ;
  - sinon : nouvel artefact, titre « Premier League, journée N », icône `chart`, puis
    `python report.py --record-artifact N <slug>`.
- Git :
  ```bash
  git add reports && git commit -m "Rapport journée N" && git pull --rebase && git push
  ```
  (le VPS enverra le PDF sur Drive à la 20e minute suivante).

## 5 bis. Fiches équipes (une fois par passage, après les journées)

```bash
python teams.py --pdf             # -> out/teams/index.html + reports/<saison>/PL <saison> - Fiches equipes.pdf
```

Republier l'artefact des fiches (`publish_files`, `out/teams/index.html` servi en `index.html`) avec le
slug de `reports/<saison>/teams.json` (`get_artifact` pour la version de base). S'il n'existe pas :
nouvel artefact « Premier League, fiches équipes », icône `chart`, puis
`python teams.py --record-artifact <slug>`. Committer `reports/` avec le reste.

## 6. Terminer

Message final court : les 2-3 faits marquants de la journée en une ligne chacun, le lien de la
page, le lien des fiches équipes, et « PDF sur Drive dans l'heure ». Signaler tout problème (match manquant, erreur de données).
