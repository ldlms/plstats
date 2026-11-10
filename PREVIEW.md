# Aperçu de la journée suivante – procédure

Lue par la tâche programmée « Aperçu Premier League » (lundi et jeudi). Le VPS met à jour
`data/fixtures/<saison>.json` chaque nuit.

## 1. Y a-t-il un aperçu à faire ?

```bash
pip install -q --break-system-packages -r requirements-report.txt
python preview.py --due     # numéro de journée (premier match dans moins de 96 h, pas d'aperçu récent), ou AUCUNE
```

`AUCUNE` : s'arrêter et le dire en une phrase.

## 2. Construire

```bash
python preview.py --round N       # -> out/PN/summary.json + out/PN/index.html
```

## 3. Rédiger `out/PN/analysis.json`

Lire `out/PN/summary.json`, puis écrire :

```json
{
  "intro": ["1 ou 2 paragraphes : l'affiche phare, le match le plus déséquilibré, une tendance"],
  "matches": {"<fixtureId>": {"headline": "une phrase", "paragraph": "2 ou 3 phrases : ce qui devrait décider du match"}}
}
```

Règles :
- Français simple. **Chaque chiffre vient de `summary.json`** (rangs, xG moyens, forme, projection).
- S'appuyer sur `keys` (avantages, verrous, couloirs), `matchup` (forces/faiblesses), `style`,
  `record.form`, `players` (joueurs à suivre et leurs points forts).
- Pas de pronostic affirmé : la projection est indicative (pas d'absents ni de blessés dans les données) ;
  on peut dire « favori d'après les occasions » quand l'écart est net (plus de 15 points).
- Pas de contexte inventé (blessures, transferts, enjeux de classement non visibles dans les données).

Relire chaque chiffre contre `summary.json`.

## 4. Page, PDF, publication

```bash
python preview.py --round N --pdf   # -> reports/<saison>/PL <saison> - Apercu journee NN.pdf + registre previews.json
```

- Artefact (`publish_files`, `out/PN/index.html` servi en `index.html`) : si `reports/<saison>/previews.json`
  a un `artifact` pour N, republier ce slug (`get_artifact` pour la version de base) ; sinon nouvel artefact
  « Premier League, aperçu journée N », icône `chart`, puis `python preview.py --record-artifact N <slug>`.
- `git add reports && git commit -m "Aperçu journée N" && git pull --rebase && git push`
  (le VPS enverra le PDF sur Drive dans l'heure).

## 5. Terminer

Message court : l'affiche à suivre et 2 « clés » marquantes (une ligne chacune), le lien de la page.
