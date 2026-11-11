"""Module 4 — Moteur de règles de sécurité modulaire.

Une règle est une simple fonction ``regle(record, **config)`` qui renvoie
une alerte (dict) ou ``None``. Les fonctions sont des objets de première
classe : on peut les ranger dans un tuple, les passer en argument, lire
leur nom avec ``__name__``...

    apply_security_rules(record, rule_sql_injection, rule_xss,
                         blacklist=ips, max_latency_ms=5000)
"""

import re
import sys
from collections.abc import Callable
from typing import Any

from logengine.models import Alert, LogRecord
from logengine.transform import is_private_ip

Rule = Callable[..., Alert | None]

SQLI_RE = re.compile(
    r"('|%27)\s*(or|and)\s|union\s+select|;\s*drop\s+table|sleep\(\d+\)"
    r"|'--", re.IGNORECASE)
XSS_RE = re.compile(r"<script|javascript:|onerror\s*=|%3cscript",
                    re.IGNORECASE)
TRAVERSAL_RE = re.compile(r"\.\./|\.\.\\|\.\.%2f|/etc/(passwd|shadow)"
                          r"|win\.ini", re.IGNORECASE)
DEFAULT_PROBE_PATHS = ("/wp-admin", "/.env", "/phpmyadmin", "/.git/",
                       "/admin.php", "/cgi-bin/", "/actuator",
                       "/server-status")
DEFAULT_BAD_AGENTS = ("sqlmap", "nikto", "hydra", "masscan", "gobuster",
                      "nmap", "zgrab")
DEFAULT_SENSITIVE_PORTS = frozenset({22, 23, 3389, 3306, 5432, 6379})


# --------------------------------------------------------------- outils
def make_alert(record: LogRecord, rule: str, severity: str,
               detail: str) -> Alert:
    return {"rule": rule, "severity": severity,
            "timestamp": record["timestamp"].isoformat(),
            "ip": record["ip"], "user": record["user"] or "",
            "service": record["service"], "detail": detail[:200]}


def request_path(record: LogRecord) -> str:
    """Chemin HTTP demandé (ou "" si la ligne n'est pas une requête)."""
    match record["payload"]:
        case {"path": str(path)}:
            return path
        case _:
            return ""


def user_agent(record: LogRecord) -> str:
    match record["payload"]:
        case {"ua": str(agent)}:
            return agent
        case _:
            return ""


# --------------------------------------------------------------- règles
def rule_sql_injection(record: LogRecord, **config: Any) -> Alert | None:
    path = request_path(record)
    if path and SQLI_RE.search(path):
        return make_alert(record, "sql_injection", "HIGH", path)
    return None


def rule_xss(record: LogRecord, **config: Any) -> Alert | None:
    path = request_path(record)
    if path and XSS_RE.search(path):
        return make_alert(record, "xss", "HIGH", path)
    return None


def rule_path_traversal(record: LogRecord, **config: Any) -> Alert | None:
    path = request_path(record)
    if path and TRAVERSAL_RE.search(path):
        return make_alert(record, "path_traversal", "HIGH", path)
    return None


def rule_scanner_probe(record: LogRecord, **config: Any) -> Alert | None:
    """Accès à des fichiers sensibles typiques des scanners automatiques."""
    path = request_path(record)
    probes = config.get("probe_paths", DEFAULT_PROBE_PATHS)
    if path and path.startswith(probes):    # startswith accepte un tuple
        return make_alert(record, "scanner_probe", "MEDIUM", path)
    return None


def rule_malicious_user_agent(record: LogRecord,
                              **config: Any) -> Alert | None:
    agent = user_agent(record).lower()
    bad_agents = config.get("bad_agents", DEFAULT_BAD_AGENTS)
    if agent and any(tool in agent for tool in bad_agents):
        return make_alert(record, "outil_offensif", "MEDIUM", agent)
    return None


def rule_blacklisted_ip(record: LogRecord, **config: Any) -> Alert | None:
    if record["ip"] in config.get("blacklist", frozenset()):
        return make_alert(record, "ip_blacklistee", "HIGH",
                          f"{record['event']} depuis une IP en liste noire")
    return None


def rule_privilege_abuse(record: LogRecord, **config: Any) -> Alert | None:
    match record["event"]:
        case "privilege_escalation":
            return make_alert(record, "elevation_privileges", "CRITICAL",
                              str(record["payload"]))
        case "data_export":
            return make_alert(record, "exfiltration_donnees", "HIGH",
                              request_path(record))
        case _:
            return None


def rule_slow_request(record: LogRecord, **config: Any) -> Alert | None:
    limit = config.get("max_latency_ms", 5000)
    match record["payload"]:
        case {"latency_ms": int() | float() as ms} if ms > limit:
            return make_alert(record, "requete_lente", "LOW",
                              f"{ms:.0f} ms > {limit} ms")
        case _:
            return None


def rule_exposed_port(record: LogRecord, **config: Any) -> Alert | None:
    """Pare-feu qui ACCEPTE un port sensible depuis Internet."""
    ports = config.get("sensitive_ports", DEFAULT_SENSITIVE_PORTS)
    match record["payload"]:
        case {"action": "ACCEPT", "dst_port": int(port)} if (
                port in ports and not is_private_ip(record["ip"])):
            return make_alert(record, "port_sensible_expose", "HIGH",
                              f"port {port} ouvert depuis {record['ip']}")
        case _:
            return None


# Toutes les règles disponibles, dans l'ordre d'exécution
DEFAULT_RULES: tuple[Rule, ...] = (
    rule_sql_injection, rule_xss, rule_path_traversal, rule_scanner_probe,
    rule_malicious_user_agent, rule_blacklisted_ip, rule_privilege_abuse,
    rule_slow_request, rule_exposed_port,
)


# ------------------------------------------------------- fonction maître
def apply_security_rules(record: LogRecord, *rules: Rule,
                         **config: Any) -> list[Alert]:
    """Applique un nombre variable de règles à un enregistrement.

    - ``*rules``   : les fonctions de règles, regroupées dans un tuple ;
    - ``**config`` : les paramètres nommés, regroupés dans un dict, puis
      retransmis tels quels à chaque règle avec ``rule(record, **config)``.
      Chaque règle y prend ce dont elle a besoin (``config.get(...)``).
    - ``config["disabled"]`` permet de désactiver des règles par leur nom.

    Une règle qui plante ne doit pas arrêter tout le moteur : l'exception
    est signalée et on passe à la règle suivante.
    """
    disabled = config.get("disabled", ())
    alerts: list[Alert] = []
    for rule in rules:
        if rule.__name__ in disabled:
            continue
        try:
            alert = rule(record, **config)
        except Exception as exc:            # noqa: BLE001 - robustesse voulue
            print(f"[règles] {rule.__name__} a échoué : {exc!r}",
                  file=sys.stderr)
        else:                               # exécuté seulement sans exception
            if alert is not None:
                alerts.append(alert)
    return alerts
