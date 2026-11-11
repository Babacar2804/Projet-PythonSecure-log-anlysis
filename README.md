# Engine de traitement et d'analyse de logs

Plateforme CLI d'ingestion, de nettoyage, de transformation et d'analyse de
logs volumineux (10 à 15 Go), sans jamais charger les fichiers en RAM.

## Installation (environnement virtuel obligatoire)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

Python 3.10 minimum (le code utilise `match` / `case`).

Si vous ajoutez une bibliothèque, régénérez le fichier :
`pip freeze > requirements.txt`.

## Utilisation

```bash
python main.py demo                          # jeu de test (~50 Mo) + analyse
python main.py generate --size-gb 12         # gros jeu de données -> data/raw
python main.py analyze                       # analyse de data/raw -> output/
python main.py analyze --limit 2000000       # seulement 2 M de lignes
python main.py analyze --level ERROR --service payment-service
python main.py analyze --trace-memory        # mesure le pic mémoire
python main.py --help                        # toutes les options
```

Durées mesurées (8 cœurs) : génération de 12 Go (69 M de lignes) en 75 s ;
analyse à ≈ 72 000 lignes/s, soit 16 min pour 12 Go (un seul processus).

## Résultats (dossier `output/`)

| Fichier | Contenu |
|---|---|
| `report.json` | toutes les statistiques, le bilan du nettoyage, les ensembles d'IP, les incidents |
| `alerts.csv` | une ligne par alerte de sécurité |
| `incidents.csv` | les IP suspectes de force brute (et les comptes compromis) |
| `rejected_samples.txt` | exemples de lignes supprimées / rejetées, par cause |
| `sample_clean.csv` | échantillon de lignes propres (1 sur N), pour des analyses complémentaires |
| `audit.json` | audit des variables globales / locales (`globals()` / `locals()`) |
| `charts/*.png` | graphiques |

## Arborescence

```
main.py                  point d'entrée (CLI) : generate / analyze / demo
requirements.txt
logengine/
    config.py            constantes (dossiers, niveaux, services)
    models.py            types : LogRecord, Alert, Connection
    generator.py         génération du jeu de données
    ingestion.py         Module 1 : yield / yield from
    parsing.py           Module 1-2 : ligne -> dict, routage match-case
    transform.py         Module 2 : nettoyage, normalisation (map/filter)
    aggregation.py       Module 3 : defaultdict, set, frozenset
    detection.py         Module 3 : force brute (while/for/break/continue/else)
    rules.py             Module 4 : apply_security_rules(*args, **kwargs)
    audit.py             Module 4 : globals() / locals()
    report.py            exports JSON / CSV / PNG
docs/EXPLICATIONS.md     explication détaillée pour la soutenance
```

## Rapport PDF

Le rapport final est un PDF (pas de notebook, à la demande du professeur).
Il est construit automatiquement à partir des résultats de l'analyse :

```bash
python main.py analyze                       # produit output/
python docs/rapport/build_report.py          # -> docs/rapport/Rapport_projet_logs.pdf
```

Les noms de l'équipe, l'enseignant et l'URL GitHub se règlent en haut de
`docs/rapport/build_report.py` (variables `TEAM`, `TEACHER`, `GITHUB_URL`).
