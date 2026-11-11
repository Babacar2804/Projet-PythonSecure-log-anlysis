# Explications du projet (pour préparer la soutenance)

## 1. L'idée générale en une phrase

On fabrique 12 Go de logs réalistes et volontairement sales, puis on les lit
**une ligne à la fois** à travers une chaîne d'étapes (nettoyer, découper,
normaliser, filtrer, analyser) sans jamais garder les lignes en mémoire :
on ne garde que des **compteurs** et quelques **ensembles** de taille bornée.

```
 fichiers .log (12 Go)
      │  read_sources()           yield from  ─┐
      │  read_log_file()          yield        │ Module 1 : ingestion
      ▼                                        ┘
 map(clean_raw_line)              strip, ANSI, caractères invisibles ─┐
 filter(tracker.keep_line)        lignes vides, commentaires, traces  │
 drop_consecutive_duplicates()    doublons                            │ Module 2
 map(parse_line)                  str -> dict  (match-case)           │
 map(normalize_record)            types + valeurs canoniques          │
 filter(tracker.accept)           rejet des lignes invalides          │
 filter(lambda r: ...)            filtres --level / --service        ─┘
      ▼
 for record in records:           UNE SEULE passe
     stats.update(record)         defaultdict, set          ─ Module 3
     detector.feed(record)        force brute (while)        ─ Module 3
     apply_security_rules(record, *RULES, **config)          ─ Module 4
      ▼
 detector.summarize()             for / break / continue / else
 compare_with_blacklist()         | & - ^ avec un frozenset
 export_audit_report(globals(), locals())                    ─ Module 4
 report.json, alerts.csv, incidents.csv, charts/*.png
```

## 2. Pourquoi la RAM ne sature pas (LA question de la soutenance)

`map()`, `filter()` et les fonctions avec `yield` sont **paresseux** : ils ne
calculent rien tant qu'on ne leur demande pas l'élément suivant.

Dans `main.py`, les lignes `lines = map(...)`, `records = filter(...)` ne
lisent **rien** : elles empilent des "tuyaux". C'est la boucle
`for record in records:` qui tire sur le bout du tuyau. À chaque tour :

1. `filter(tracker.accept)` demande un élément à `map(normalize_record)`,
2. qui en demande un à `map(parse_line)`,
3. ... jusqu'à `read_log_file()` qui lit **une** ligne du disque (`yield`).

Une ligne traverse donc tout le pipeline, puis est oubliée (le ramasse-miettes
la libère). En mémoire il n'y a que la ligne en cours + les compteurs.

Preuve à montrer : `python main.py demo` affiche "Pic mémoire Python"
(mesuré avec `tracemalloc`). Mesures réelles : **12,5 Mo pour 290 000
lignes, 16,1 Mo pour 2 000 000 de lignes** : 7 fois plus de données, presque
la même mémoire. Le pic dépend du nombre d'IP / utilisateurs / heures
distincts (bornés à ~17 000 IP et 5 000 utilisateurs), pas de la taille des
fichiers. (`--trace-memory` ralentit beaucoup l'analyse : à utiliser avec
`--limit`.)

Contre-exemples à citer : `f.read()` ou `f.readlines()` chargeraient tout le
fichier ; `list(records)` aussi ; un `set` de toutes les lignes pour
dédoublonner aussi (c'est pour ça qu'on ne compare qu'avec la ligne
précédente).

## 3. Les données générées (`generator.py`)

### Trois formats de lignes

| Format | Part | Exemple |
|---|---|---|
| app | ~80 % | `2026-10-01T08:15:32.481Z \| INFO \| api-gateway \| 10.0.3.17:51432/TCP \| user=u1042 \| event=http_request \| {"method":"GET","path":"/","status":200,...}` |
| json | ~10 % | `{"ts":"...","lvl":"error","svc":"payment-service","client":{"ip":"...","port":443,"proto":"TCP"},"user":"u12","event":"payment_failed","code":502,...}` |
| firewall | ~10 % | `FW 2026-10-01T08:15:32.481Z DROP TCP 185.23.1.4 4444 10.0.100.5 22 DENY-SSH-EXT` |

Le dernier champ d'une ligne app est soit un **payload JSON**, soit une
**chaîne brute** (`requête lente (2350 ms) sur la table orders`).

### Variété (pour des analyses intéressantes)

- 11 services, 5 000 utilisateurs (loi de Zipf : quelques gros utilisateurs),
  ~17 000 IP (internes, bureau, publiques, IPv6) ;
- profil d'activité : creux la nuit, pics à 10 h et 15 h, week-end à 60 % ;
- scénarios planifiés : **pannes** (payment, db, auth) avec pics d'erreurs,
  **DDoS** (botnet de 400 IP, codes 429/503), **déploiements** quotidiens,
  **disque** qui se remplit jusqu'à saturation ;
- attaques : **force brute** (6 à 40 échecs, ~18 % réussissent puis
  élévation de privilèges + export de données), **credential stuffing**,
  **scans de ports**, **injections SQL**, **XSS**, **path traversal**,
  outils offensifs (sqlmap, Nikto, Hydra) ;
- une **liste noire** (`blacklist.txt`) : 40 attaquants + 150 IP du botnet
  + 300 IP "dormantes" jamais vues + quelques lignes sales.

### Catalogue des défauts injectés (~5 % des lignes, `--dirty-rate`)

| Défaut | Exemple | Traitement | Où |
|---|---|---|---|
| espaces / tabulations / `\r` | `  \t2026-... \r` | réparé | `clean_raw_line` (strip) |
| caractères invisibles, BOM, octets invalides | `\x00`, `﻿`, `\xff` | réparé | `clean_raw_line` (translate) |
| couleurs ANSI | `\x1b[31mERROR\x1b[0m` | réparé | `clean_raw_line` (regex) |
| séparateurs doublés | `\|\|` | réparé | `clean_raw_line` |
| lignes vides, commentaires `#` | | supprimé | `CleaningTracker.keep_line` |
| stack traces Python | `Traceback (...)`, `File "..."` | supprimé | `keep_line` (TRACE_RE) |
| doublons consécutifs | | supprimé | `drop_consecutive_duplicates` |
| casse des niveaux | `err`, `Warning`, `FATAL`, `INF` | réparé | `normalize_level` (match-case) |
| casse des services | `API_GATEWAY`, `Auth-Service` | réparé | `normalize_service` |
| format des utilisateurs | `U-1042`, `USER_1042`, `user-01042` | réparé → `u1042` | `normalize_user` (regex) |
| valeurs nulles | `null`, `None`, `N/A`, vide | → `None` (anonyme) | `normalize_user` |
| autres formats de date | `01/10/2026 08:15:32`, epoch, virgule, sans fuseau | réparé | `parse_timestamp` |
| date impossible | `2026-13-45T25:61:00Z`, `N/A` | rejeté | `parse_timestamp` |
| IP impossible | `999.12.4.1`, `10.0.0`, `localhost` | rejeté | `validate_ip` |
| port impossible | `abc`, `99999` | rejeté | `normalize_record` |
| protocole manquant | `10.0.3.17:51432` | réparé → TCP | `normalize_record` |
| JSON entre guillemets simples | `{'status': 200}` | réparé | `parse_payload` |
| JSON tronqué | `{"status":2` | payload gardé en texte (signalé) ou ligne rejetée | `parse_payload` / `parse_line` |
| nombres en texte | `"status":"200"` | réparé | `_clean_payload_fields` |
| latence absurde | `-1`, `NaN`, `"slow"` | → `None` | `_clean_payload_fields` |
| mauvais encodage | `requÃªte` | réparé → `requête` | `fix_mojibake` |
| champ manquant / ligne tronquée | | rejeté | `_parse_app_line`, `parse_line` |
| JSON sans bloc `client` | | rejeté | `parse_line` (`case dict()`) |

Toutes les suppressions, rejets et corrections sont **comptés** et apparaissent
dans `report.json` → `nettoyage`, dans les graphiques 06 et 07 et, avec des
exemples réels, dans `rejected_samples.txt`.

### Comment le générateur fonctionne

- `Pools` : populations fixes (utilisateurs, IP). Même graine → mêmes IP dans
  tous les fichiers, donc les analyses croisées ont du sens.
- `LogFactory` : une méthode par type d'évènement. Elle renvoie des
  "morceaux" (`("app", [champs])`, `("json", dict)`, `("fw", [jetons])`).
- `NoiseInjector.emit` : assemble la ligne et, avec une probabilité
  `dirty_rate`, l'abîme (choix du défaut pondéré, puis `match` sur le défaut).
- `lines_for_minute` : pour chaque minute, calcule combien de lignes produire
  (profil horaire × scénarios), tire leurs secondes au hasard, ajoute les
  évènements spéciaux (rafale de force brute...), trie par horodatage.
- `generate_dataset` : estime la taille moyenne d'une ligne, en déduit le
  nombre de lignes par minute pour atteindre la taille demandée, découpe la
  période en fichiers et les écrit **en parallèle** (`ProcessPoolExecutor`,
  un processus par fichier). C'est pour ça que `main.py` a
  `if __name__ == "__main__":` (obligatoire sous Windows).
- Le fichier est ouvert en binaire avec `"surrogateescape"` pour pouvoir écrire
  de vrais octets invalides et tester `errors="replace"` à la lecture.

## 4. Module par module

### Module 1 — Ingestion (`ingestion.py`)

```python
def read_log_file(path):
    with open(path, encoding="utf-8", errors="replace", newline="") as file:
        for line in file:
            yield line

def read_sources(paths):
    for path in paths:
        yield from read_log_file(path)
```

- `yield` met la fonction en pause et renvoie une ligne ; elle reprend au même
  endroit à l'appel suivant. Le `with` reste ouvert tant que le générateur
  n'est pas terminé, puis ferme le fichier.
- `yield from` délègue à un sous-générateur : équivalent à
  `for line in read_log_file(path): yield line`, en plus court.
- `with_progress` est une étape transparente qui affiche l'avancement.

### Module 1/2 — Parsing et match-case (`parsing.py`)

`decode_line` transforme le texte en l'objet le plus naturel :
JSON → `dict`, ligne `FW` → `tuple`, sinon `str`. Puis `parse_line` route
selon la **forme** de l'objet :

```python
match decode_line(line):
    case {"ts": timestamp, "lvl": str(level), "svc": str(service),
          "client": {"ip": ip, "port": port, "proto": protocol}, **rest}:
        ...                                  # dictionnaire (JSON)
    case ("FW", timestamp, action, protocol, src_ip, src_port,
          dst_ip, dst_port, *rule):
        ...                                  # tuple de connexion
    case str() as text if text.startswith("{"):
        ...                                  # JSON cassé -> rejet
    case str() as text:
        return _parse_app_line(text)         # chaîne brute
```

- Un motif **dict** vérifie que les clés existent (les autres clés vont dans
  `**rest`) ; un motif imbriqué vérifie même le sous-dictionnaire `client`.
- Un motif **tuple** vérifie la longueur et le premier élément ; `*rule`
  capture le reste (0 ou 1 élément).
- `str(level)` vérifie le type ET capture la valeur.
- `if ...` après un motif s'appelle une **garde**.
- L'ordre des `case` compte : le premier qui correspond gagne.

Le résultat est toujours un `dict` (`LogRecord`) avec `errors` (raisons de
rejet) et `fixes` (corrections). Le **tuple immuable** `(IP, Port,
Protocole)` est stocké dans `record["connection"]`.

### Module 2 — Nettoyage et normalisation (`transform.py`)

- `map(clean_raw_line, lines)` : la même fonction est appliquée à chaque
  ligne. `isprintable()` sert de raccourci : 95 % des lignes sont propres et
  ne paient pas le coût de la regex.
- `filter(tracker.keep_line, lines)` : on passe une **méthode** comme
  prédicat. Elle renvoie False pour supprimer la ligne, et en profite pour
  compter la cause (lignes vides, commentaires, stack traces).
- `normalize_record` convertit les types (`datetime`, `int`), met les valeurs
  sous forme canonique et remplit `errors` / `fixes`.
- `normalize_level` remplace un long `if/elif` par un `match` avec des motifs
  "OU" : `case "WARNING" | "WARN" | "WRN": return "WARNING"`.
- `filter(tracker.accept, records)` rejette les enregistrements avec des
  erreurs, en comptant la cause.
- Dans `main.py` : `filter(lambda r: LEVEL_RANK[r["level"]] >= min_rank, ...)`
  pour l'option `--level`.
- Dans `aggregation.load_blacklist` : `filter(None, lines)` (supprime les
  chaînes vides, car `""` est "faux"), `map(str.strip, file)`,
  `map(lambda line: validate_ip(...), lines)`.

### Module 3 — Agrégation (`aggregation.py`)

- `defaultdict(int)` : `compteur[cle] += 1` sans `KeyError`, la valeur 0 est
  créée automatiquement. Utilisé pour niveaux, services, utilisateurs, IP,
  codes HTTP, heures...
- `defaultdict(lambda: defaultdict(int))` : compteur à deux niveaux
  (service → niveau → nombre).
- `defaultdict(set)` : pour chaque IP, l'ensemble des ports bloqués → une IP
  qui a tenté ≥ 15 ports différents est un **scanner**.
- `self.error_ips` est un `set` : `add()` ignore les doublons, donc on obtient
  directement les IP **uniques** ayant généré des erreurs.
- `match record: case {"level": "ERROR" | "CRITICAL", "ip": ip}:` — c'est le
  motif `{'level': 'ERROR', 'code': code}` de l'énoncé.
- `_add_latency` utilise un `for ... else` : le `else` ne s'exécute que si la
  boucle n'a pas fait `break` (latence plus grande que toutes les limites).
- `compare_with_blacklist` : la liste noire est un **`frozenset`** (ensemble
  immuable : personne ne peut la modifier par erreur pendant l'analyse).

| Opération | Résultat |
|---|---|
| `actives \| blacklist` | toutes les IP connues |
| `actives & blacklist` | IP listées réellement actives (≈ 190 attendues) |
| `erreurs & blacklist` | IP listées qui provoquent des erreurs |
| `actives - blacklist` | IP actives inconnues de la liste |
| `blacklist - actives` | IP listées jamais vues (≈ 300 "dormantes") |
| `actives ^ blacklist` | dans l'une OU l'autre, pas les deux |

### Module 3 — Force brute (`detection.py`)

Pendant la lecture, `feed()` garde pour chaque IP une **fenêtre glissante**
(`deque`) des échecs des 120 dernières secondes :

```python
window.append((moment, user))
while window and moment - window[0][0] > self.window:   # while
    window.popleft()                                   # on oublie le trop vieux
if len(window) >= self.threshold: ...                  # -> IP suspecte
```

Une connexion réussie vide la fenêtre. À la fin, `summarize()` rejoue les
tentatives de chaque suspect :

```python
for ip, suspect in self._suspects.items():
    if ip in self.whitelist:
        continue                         # on saute les IP de confiance
    for moment, user, success in suspect["events"]:
        if not success:
            consecutive += 1
            continue                     # échec : on passe au suivant
        if consecutive >= self.threshold and ...:
            compromised_at = moment
            break                        # succès après X échecs : COMPROMIS
        consecutive = 0
    else:
        status = "bloquee"               # boucle allée au bout sans break :
                                         # cycle complet, aucune réussite
```

Résultats : `incidents.csv` + `report.json` → `force_brute`. Le type
`credential_stuffing` est donné quand une IP essaie plus de 3 comptes.

### Module 4 — Moteur de règles (`rules.py`)

Une règle = une fonction `regle(record, **config) -> alerte | None`.

```python
def apply_security_rules(record, *rules, **config):
    for rule in rules:                          # rules est un tuple
        if rule.__name__ in config.get("disabled", ()):
            continue
        try:
            alert = rule(record, **config)      # on retransmet **config
        except Exception as exc:
            print(...)                          # une règle qui plante
        else:                                   # n'arrête pas le moteur
            if alert is not None:
                alerts.append(alert)
    return alerts

apply_security_rules(record, *DEFAULT_RULES, blacklist=bl, max_latency_ms=5000)
```

- `*rules` regroupe les arguments positionnels dans un **tuple**,
  `**config` les arguments nommés dans un **dict**.
- À l'appel, `*DEFAULT_RULES` fait l'inverse : il "déballe" le tuple.
- Les fonctions sont des **objets de première classe** : rangées dans un
  tuple, passées en argument, nom lu avec `__name__`.
- `try / except / else` : le `else` s'exécute seulement s'il n'y a pas eu
  d'exception.
- Ajouter une règle = écrire une fonction et l'ajouter à `DEFAULT_RULES` ;
  la désactiver = `--disable-rule rule_slow_request`.

Règles : injection SQL, XSS, path traversal, fichiers sensibles (scanners),
outils offensifs, IP en liste noire, élévation de privilèges / exfiltration,
requêtes lentes, port sensible exposé sur Internet.

### Module 4 — Audit (`audit.py`)

À la fin de `run_analysis`, on appelle
`export_audit_report(path, globals(), locals())` :

- `globals()` = noms du module `main` (imports, fonctions, constantes) ;
- `locals()` = variables de `run_analysis` à cet instant (`stats`,
  `detector`, `blacklist`, `report`, les itérateurs `lines` / `records`...).

C'est l'appelant qui fait `globals()` / `locals()` : si on les appelait
dans `audit.py`, on inspecterait la portée d'`audit.py`. Le rapport donne
nom, catégorie, type, taille (`sys.getsizeof`, taille de l'objet seul),
longueur et un aperçu limité par `reprlib` (sinon le `repr` d'un dict de
17 000 IP serait énorme). On y voit d'ailleurs que `lines` et `records`
sont de minuscules objets `generator` / `filter` : la preuve qu'ils ne
contiennent pas les données.

## 5. Correspondance avec le barème

| Critère (points) | Où le montrer |
|---|---|
| Environnement (2) | `.venv`, `requirements.txt` (pip freeze), uniquement des scripts `.py` (aucun notebook), rapport final en PDF |
| Générateurs (4) | `ingestion.read_log_file` (yield), `read_sources` (yield from), `with_progress`, `drop_consecutive_duplicates`, pic mémoire ~12 Mo |
| Structures (4) | `set` (`error_ips`), `frozenset` (blacklist, `KNOWN_SERVICES`), `defaultdict` (aggregation), tuple `connection`, `match` (parsing, transform, aggregation, rules, generator) |
| Fonctionnel (4) | pipeline `map`/`filter` dans `main.run_analysis`, `load_blacklist`, `lambda` (tris, filtres), prédicats `tracker.keep_line` / `tracker.accept` passés à `filter`, règles passées à `apply_security_rules` |
| Règles & introspection (3) | `rules.apply_security_rules(*rules, **config)`, `audit.export_audit_report(globals(), locals())` |
| Qualité (3) | PEP 8, annotations de type partout, `try/except/else`, `for/else`, `while`, `break`/`continue` (detection.py), aucune exception non gérée sur les données sales |

## 6. Notions utilisées qui ne sont peut-être pas dans les slides

| Notion | En deux mots |
|---|---|
| `re` (regex) | motifs de texte : `USER_RE.fullmatch("user-01042")` capture `01042` |
| `ipaddress.ip_address` | valide une IP v4/v6, lève `ValueError` sinon |
| `@lru_cache` | décorateur qui mémorise le résultat d'une fonction pour une entrée donnée |
| `deque` | file à deux bouts : `append` à droite, `popleft` à gauche en temps constant |
| `TypedDict` | documente les clés d'un dict pour le typage (reste un dict normal) |
| `argparse` | lecture des options de la ligne de commande |
| `ProcessPoolExecutor` | exécute une fonction dans plusieurs processus en parallèle |
| `@property`, `@staticmethod` | attribut calculé / méthode sans `self` |
| `tracemalloc` | mesure la mémoire allouée par Python |
| `reprlib` | `repr` raccourci |
| `x == x` | faux uniquement si `x` est NaN (astuce pour détecter NaN) |
| `:=` (morse) | affecte et teste en une fois : `if match := USER_RE.fullmatch(t):` |

## 7. Proposition de répartition à 4

| Personne | Fichiers | À savoir expliquer |
|---|---|---|
| A | `generator.py` | format des lignes, scénarios, défauts injectés, parallélisme |
| B | `ingestion.py`, `parsing.py` | yield / yield from, match-case, tuple de connexion |
| C | `transform.py`, `aggregation.py` | map / filter / lambda, normalisation, defaultdict, set / frozenset |
| D | `detection.py`, `rules.py`, `audit.py`, `main.py`, rapport | while / for / else, *args / **kwargs, globals / locals, CLI |

Chacun doit quand même savoir dérouler le **schéma de la section 1** et
répondre à la question de la **section 2**.

## 8. Questions probables du jury

**Pourquoi un générateur plutôt qu'une liste ?** Une liste stocke tous les
éléments en même temps (12 Go → plantage). Un générateur produit un élément à
la demande et l'oublie.

**Que se passe-t-il si on fait `list(records)` ?** Toutes les lignes seraient
chargées en mémoire. Et un générateur ne se parcourt qu'une fois : une
deuxième boucle ne trouverait rien. C'est pourquoi tout est calculé en une
seule passe.

**Pourquoi un tuple pour (IP, Port, Protocole) ?** C'est une métadonnée fixe :
immuable donc protégée, et hashable donc utilisable comme clé de dict ou dans
un set (une liste ne l'est pas).

**Pourquoi un frozenset pour la blacklist ?** Elle ne doit pas changer
pendant l'analyse ; un frozenset ne peut pas être modifié. Le test `ip in`
est en temps constant, comme pour un set.

**Différence `set` / `defaultdict` dans votre code ?** Le set répond à "quelles
IP ?" (unicité), le defaultdict à "combien de fois ?" (comptage).

**Pourquoi `match` plutôt que `if/elif` ?** On décrit la forme attendue des
données (clés, longueur, types) et on capture les valeurs en même temps ;
avec des `if`, il faudrait tester `isinstance`, `len`, `in` et extraire à la
main.

**À quoi sert le `else` d'une boucle ?** Il s'exécute si la boucle se termine
normalement, sans `break`. Dans la détection : "j'ai parcouru toutes les
tentatives sans trouver de succès → attaque bloquée".

**Pourquoi ne pas dédoublonner avec un set de toutes les lignes ?** 60 M de
lignes dans un set = plusieurs Go de RAM. On compare avec la ligne précédente
(les doublons de logs sont presque toujours consécutifs).

**Comment ajouter une règle ?** Écrire `def rule_x(record, **config)`, la
mettre dans `DEFAULT_RULES`. Rien d'autre à changer.

**Comment savoir que le nettoyage marche ?** `report.json` → `nettoyage`
(compteurs par cause), `rejected_samples.txt` (vrais exemples), graphiques 06
et 07.

**Combien de temps pour 12 Go ?** Génération : 75 s (7 processus, 69 M de
lignes). Analyse : ≈ 72 000 lignes/s, 16 min sur un seul processus ; pour la
démo on utilise
`--limit`.

## 9. Limites et pistes d'amélioration (bon à dire spontanément)

- **Analyse en parallèle** : un processus par fichier, puis fusion des
  compteurs. Gain ≈ ×6 sur 8 cœurs, mais les attaques à cheval sur deux
  fichiers seraient vues en deux morceaux.
- Une IP qui attaque plusieurs fois sur 30 jours donne **un seul** incident
  (les campagnes sont fusionnées) ; on pourrait les séparer par période
  d'inactivité.
- Le dédoublonnage ne voit que les doublons consécutifs.
- Les stack traces sont supprimées ; on pourrait les rattacher à la ligne
  d'erreur précédente.
