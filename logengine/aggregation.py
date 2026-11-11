"""Module 3 — Agrégation : compteurs, ensembles et liste noire.

``defaultdict(int)`` crée automatiquement la valeur 0 pour une clé absente :
``compteur[cle] += 1`` ne lève donc jamais de ``KeyError``.
"""

from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from logengine.models import Connection, LogRecord
from logengine.transform import validate_ip

LATENCY_BUCKETS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def load_blacklist(path: Path) -> frozenset[str]:
    """Charge la liste noire dans un ``frozenset`` (ensemble immuable).

    Le fichier est lui aussi un peu sale : on enchaîne map / filter / lambda
    pour le nettoyer sans boucle explicite.
    """
    if not path.exists():
        return frozenset()
    with open(path, encoding="utf-8") as file:
        lines: Iterator[str] = map(str.strip, file)
        lines = filter(None, lines)                     # lignes vides
        lines = filter(lambda line: not line.startswith("#"), lines)
        ips = map(lambda line: validate_ip(line.split("#")[0]), lines)
        return frozenset(filter(None, ips))             # IP invalides


def compare_with_blacklist(active_ips: set[str], error_ips: set[str],
                           blacklist: frozenset[str]) -> dict[str, set[str]]:
    """Opérations ensemblistes entre IP actives et liste noire."""
    return {
        # | union : toutes les IP connues (vues dans les logs OU listées)
        "union_actives_blacklist": active_ips | blacklist,
        # & intersection : IP listées qui sont réellement actives
        "blacklist_actives": active_ips & blacklist,
        # & avec les IP en erreur : IP listées ET qui provoquent des erreurs
        "blacklist_en_erreur": error_ips & blacklist,
        # - différence : IP actives absentes de la liste noire
        "actives_non_listees": active_ips - blacklist,
        # - différence : IP listées jamais vues (liste peut-être obsolète)
        # (frozenset - set donne un frozenset : on le convertit en set)
        "blacklist_dormantes": set(blacklist - active_ips),
        # ^ différence symétrique : dans l'un OU l'autre, mais pas les deux
        "difference_symetrique": active_ips ^ blacklist,
    }


def _hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def top(counter: dict[Any, int], n: int = 10) -> list[tuple[Any, int]]:
    """Les ``n`` clés les plus fréquentes (tri par valeur décroissante)."""
    return sorted(counter.items(), key=lambda item: item[1], reverse=True)[:n]


class LogStatistics:
    """Accumule les statistiques en une seule passe sur le flux.

    Seuls des compteurs sont gardés en mémoire, jamais les lignes : la RAM
    utilisée dépend du nombre de clés distinctes (services, IP, heures...),
    pas de la taille des fichiers.
    """

    def __init__(self) -> None:
        self.total = 0
        self.by_level: defaultdict[str, int] = defaultdict(int)
        self.by_service: defaultdict[str, int] = defaultdict(int)
        self.by_source: defaultdict[str, int] = defaultdict(int)
        self.by_event: defaultdict[str, int] = defaultdict(int)
        self.by_user: defaultdict[str, int] = defaultdict(int)
        self.by_ip: defaultdict[str, int] = defaultdict(int)
        self.by_status: defaultdict[int, int] = defaultdict(int)
        self.by_hour_of_day: defaultdict[int, int] = defaultdict(int)
        self.timeline: defaultdict[datetime, int] = defaultdict(int)
        self.error_timeline: defaultdict[datetime, int] = defaultdict(int)
        # defaultdict imbriqué : service -> niveau -> nombre
        self.levels_by_service: defaultdict[str, defaultdict[str, int]] = \
            defaultdict(lambda: defaultdict(int))
        # service -> [nombre de mesures, somme, maximum]
        self.latency: defaultdict[str, list[float]] = \
            defaultdict(lambda: [0, 0.0, 0.0])
        self.latency_buckets: defaultdict[str, int] = defaultdict(int)
        self.by_protocol: defaultdict[str, int] = defaultdict(int)
        # (IP source, port de destination, protocole) -> nombre de blocages.
        # Un tuple peut servir de clé de dictionnaire car il est immuable
        # (donc "hashable") ; une liste ne le pourrait pas.
        self.blocked_flows: defaultdict[Connection, int] = defaultdict(int)
        self.error_ips: set[str] = set()
        self.first_seen: datetime | None = None
        self.last_seen: datetime | None = None

    @property
    def active_ips(self) -> set[str]:
        """Ensemble des IP uniques vues dans les logs valides."""
        return set(self.by_ip)

    def update(self, record: LogRecord) -> None:
        """Ajoute un enregistrement valide aux statistiques."""
        self.total += 1
        moment, level, service = (record["timestamp"], record["level"],
                                  record["service"])
        hour = _hour(moment)
        self.by_level[level] += 1
        self.by_service[service] += 1
        self.by_source[record["source"]] += 1
        self.by_event[record["event"]] += 1
        self.by_ip[record["ip"]] += 1
        self.by_hour_of_day[moment.hour] += 1
        self.timeline[hour] += 1
        self.levels_by_service[service][level] += 1
        if record["user"]:
            self.by_user[record["user"]] += 1
        # Déballage du tuple de connexion (IP, Port, Protocole)
        ip, _source_port, protocol = record["connection"]
        self.by_protocol[protocol] += 1
        if self.first_seen is None or moment < self.first_seen:
            self.first_seen = moment
        if self.last_seen is None or moment > self.last_seen:
            self.last_seen = moment

        # match-case sur un dict : le motif vérifie la présence des clés et
        # la valeur de "level" ("ERROR" OU "CRITICAL") en une seule ligne.
        match record:
            case {"level": "ERROR" | "CRITICAL", "ip": ip}:
                self.error_ips.add(ip)
                self.error_timeline[hour] += 1

        match record["payload"]:
            case {"status": int(status), "latency_ms": int() | float() as ms}:
                self.by_status[status] += 1
                self._add_latency(service, ms)
            case {"status": int(status)} | {"code": int(status)}:
                self.by_status[status] += 1
            case {"action": "DROP", "dst_port": int(port)}:
                # nouveau tuple : la cible visée (port de destination)
                self.blocked_flows[(ip, port, protocol)] += 1

    def _add_latency(self, service: str, ms: float) -> None:
        stats = self.latency[service]
        stats[0] += 1
        stats[1] += ms
        stats[2] = max(stats[2], ms)
        for limit in LATENCY_BUCKETS:
            if ms <= limit:
                self.latency_buckets[f"<= {limit} ms"] += 1
                break
        else:
            # else d'un for : exécuté seulement si la boucle n'a pas fait
            # de break, donc si la latence dépasse toutes les limites
            self.latency_buckets[f"> {LATENCY_BUCKETS[-1]} ms"] += 1

    def port_scanners(self, min_ports: int = 15) -> dict[str, int]:
        """IP qui ont tenté beaucoup de ports différents (scan de ports).

        On parcourt les clés de ``blocked_flows`` : chaque clé est un tuple
        qu'on déballe directement dans la boucle for.
        """
        ports_by_ip: defaultdict[str, set[int]] = defaultdict(set)
        for ip, port, _protocol in self.blocked_flows:
            ports_by_ip[ip].add(port)
        return {ip: len(ports) for ip, ports in ports_by_ip.items()
                if len(ports) >= min_ports}

    def summary(self) -> dict[str, Any]:
        """Résumé sérialisable en JSON pour le rapport."""
        latency = {
            service: {"mesures": int(n), "moyenne_ms": round(total / n, 1),
                      "max_ms": int(maximum)}
            for service, (n, total, maximum) in self.latency.items() if n}
        bucket_order = [f"<= {b} ms" for b in LATENCY_BUCKETS] + \
            [f"> {LATENCY_BUCKETS[-1]} ms"]
        return {
            "total_valides": self.total,
            "periode": {"debut": str(self.first_seen),
                        "fin": str(self.last_seen)},
            "par_niveau": dict(self.by_level),
            "par_service": dict(top(self.by_service, 50)),
            "par_source": dict(self.by_source),
            "par_evenement": dict(top(self.by_event, 60)),
            "par_code_http": dict(sorted(self.by_status.items())),
            "par_heure_de_la_journee": dict(sorted(
                self.by_hour_of_day.items())),
            "niveaux_par_service": {s: dict(levels) for s, levels in
                                    self.levels_by_service.items()},
            "latence_par_service": latency,
            "histogramme_latence": {b: self.latency_buckets[b]
                                    for b in bucket_order},
            "top_utilisateurs": top(self.by_user, 20),
            "top_ip": top(self.by_ip, 20),
            "nb_ip_uniques": len(self.by_ip),
            "nb_utilisateurs_uniques": len(self.by_user),
            "nb_ip_en_erreur": len(self.error_ips),
            "scans_de_ports": dict(top(self.port_scanners(), 30)),
            "par_protocole": dict(self.by_protocol),
            "nb_flux_bloques_distincts": len(self.blocked_flows),
            "top_flux_bloques": [
                {"ip": ip, "port": port, "protocole": protocol,
                 "blocages": count}
                for (ip, port, protocol), count in top(self.blocked_flows,
                                                       15)],
            "chronologie_par_heure": {
                h.isoformat(): n for h, n in sorted(self.timeline.items())},
            "erreurs_par_heure": {
                h.isoformat(): n for h, n in
                sorted(self.error_timeline.items())},
        }
