"""Types de données manipulés par le pipeline.

Un ``TypedDict`` reste un dictionnaire Python normal : il sert seulement à
documenter les clés attendues et à aider l'éditeur / mypy (typage).
"""

from typing import Any, TypedDict

# (IP, Port, Protocole) : un tuple est immuable, donc parfait pour des
# métadonnées fixes. Il est aussi "hashable" : on peut l'utiliser comme clé
# de dictionnaire ou le mettre dans un set.
Connection = tuple[str, int, str]


class LogRecord(TypedDict, total=False):
    """Une ligne de log après parsing."""

    raw: str                      # ligne d'origine (utile pour déboguer)
    source: str                   # "app", "json" ou "firewall"
    timestamp: Any                # str avant normalisation, datetime après
    level: Any                    # str ou None si le niveau est inconnu
    service: str
    ip: Any                       # str ou None si l'IP est invalide
    port: Any                     # str avant normalisation, int après
    protocol: str
    connection: Connection        # créé pendant la normalisation
    user: str | None
    event: str
    payload: dict[str, Any] | str  # JSON décodé ou chaîne brute
    errors: list[str]             # raisons de rejet (vide = ligne valide)
    fixes: list[str]              # corrections appliquées par le nettoyage


class Alert(TypedDict):
    """Alerte levée par une règle de sécurité."""

    rule: str
    severity: str
    timestamp: str
    ip: str
    user: str
    service: str
    detail: str
