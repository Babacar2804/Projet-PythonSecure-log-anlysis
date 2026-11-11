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

Les dépendances directes sont déclarées dans `requirements.txt`. Ajoutez-y
les bibliothèques nécessaires au projet ; évitez d'y recopier `pip freeze`,
qui épingle aussi les dépendances indirectes et peut empêcher l'installation
sur Python 3.10.

## Utilisation

```bash
python main.py demo                          # jeu de test (~50 Mo) + analyse
python main.py generate --size-gb 12         # gros jeu de données -> data/raw
python main.py analyze                       # analyse de data/raw -> output/
python main.py analyze --limit 2000000       # seulement 2 M de lignes
python main.py analyze --level ERROR --service payment-service
python main.py analyze --trace-memory        # mesure le pic mémoire
python main.py live --duration 60            # analyse en temps réel
python main.py --help                        # toutes les options
```

Pendant la démo, le terminal affiche l'avancement de la génération fichier
par fichier, puis le nombre de lignes analysées, la vitesse et la durée.

Durées mesurées (8 cœurs) : génération de 12 Go (69 M de lignes) en 75 s ;
analyse à ≈ 72 000 lignes/s, soit environ 17 min pour 12 Go (un seul processus).

### Mode temps réel

`python main.py live` simule un serveur qui écrit ses logs en continu
(`data/live/live.log`) pendant que le pipeline suit le fichier comme
`tail -f`. Les alertes s'affichent dès que la ligne est écrite.

## Tests et vérifications

```bash
python -m pytest                              # 75 tests automatiques
python -m mypy                                # vérification du typage
```

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
main.py                  point d'entrée (CLI) : generate / analyze / demo / live
requirements.txt
pyproject.toml           configuration de pytest et mypy
logengine/
    config.py            constantes (dossiers, niveaux, services)
    models.py            types : LogRecord, Alert, Connection
    generator.py         génération du jeu de données
    ingestion.py         Module 1 : yield / yield from, suivi temps réel
    parsing.py           Module 1-2 : ligne -> dict, routage match-case
    transform.py         Module 2 : nettoyage, normalisation (map/filter)
    aggregation.py       Module 3 : defaultdict, set, frozenset, tuples
    detection.py         Module 3 : force brute (while/for/break/continue/else)
    rules.py             Module 4 : apply_security_rules(*args, **kwargs)
    audit.py             Module 4 : globals() / locals()
    report.py            exports JSON / CSV / PNG
tests/                   tests pytest (un fichier par module)
```

## Rapport PDF

Le rapport final est un PDF (pas de notebook, à la demande du professeur).
Il est construit automatiquement à partir des résultats de l'analyse :

```bash
python main.py analyze                       # produit output/
python docs/rapport/build_synthese.py        # -> docs/rapport/Synthese_soutenance.pdf
```

`Synthese_soutenance.pdf` est le support de soutenance (11 pages) : une
ouverture, deux pages par module (ce qu'on présente, puis les résultats et
les questions probables du jury) et une conclusion.
Une version détaillée peut aussi être générée localement avec
`python docs/rapport/build_report.py` (elle n'est pas versionnée).

Les noms de l'équipe, l'enseignant et l'URL GitHub se règlent en haut de
`docs/rapport/build_report.py` (variables `TEAM`, `TEACHER`, `GITHUB_URL`),
utilisées par les deux rapports.
