# Telegram Bet Bot — V2 analytique légère

Bot Telegram gratuit hébergé sur GitHub Actions, pensé pour envoyer peu de signaux mais plus propres :
- Premier League
- LaLiga
- Serie A
- Bundesliga
- Ligue 1
- uniquement top teams
- marchés : Over 0.5 et Over 1.5
- exécution automatique toutes les 5 minutes
- anti-doublon via `state.json`

## Ce que fait vraiment cette V2

Le bot ne se base plus seulement sur minute + score.

### Étape 1 — scan léger
Il récupère les matchs live et ne garde que :
- les 5 grands championnats
- les top teams
- les matchs dans une bonne fenêtre minute/score

### Étape 2 — analyse détaillée
Seulement sur 3 matchs maximum par run, il tente de récupérer les stats du match et n’envoie une alerte que si les seuils sont atteints.

### Règles Over 0.5
- 15' à 30'
- score 0-0
- tirs totaux >= 7
- tirs cadrés >= 2
- corners totaux >= 3 **ou** possession dominante >= 55%
- l’équipe qui pousse a au moins 4 tirs et 1 cadré

### Règles Over 1.5
- 28' à 65'
- 0 ou 1 but au total
- tirs totaux >= 10
- tirs cadrés >= 3
- corners totaux >= 4 **ou** possession dominante >= 55%
- l’équipe qui pousse a au moins 5 tirs et 2 cadrés

## Important
Cette version utilise des endpoints non officiels de type SofaScore. Il peut donc y avoir de la maintenance si la source change.

## Déploiement rapide
1. Crée ton bot via BotFather.
2. Récupère ton `chat_id` via `getUpdates`.
3. Crée un dépôt GitHub **public**.
4. Uploade tous les fichiers du projet.
5. Ajoute les secrets :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Lance le workflow manuellement depuis l’onglet Actions.
7. Vérifie les logs.
8. Ensuite le bot tournera tout seul toutes les 5 minutes.

## Variables utiles
- `DEBUG_LOG=1` pour voir plus de détails dans les logs
- `MAX_CANDIDATES_PER_RUN=3` pour limiter la conso
- `MAX_NOTIFICATIONS_PER_RUN=4` pour éviter le spam
