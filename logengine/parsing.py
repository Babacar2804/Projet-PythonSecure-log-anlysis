"""Module 1 (parsing) + Module 2 (analyse de structure avec match-case).

Étapes pour une ligne :
  1. ``decode_line``  : transforme la chaîne en l'objet Python le plus
     adapté -> un ``dict`` (ligne JSON), un ``tuple`` (ligne pare-feu) ou
     laisse une ``str`` (ligne "app" ou ligne illisible).
  2. ``parse_line``   : un ``match`` route l'objet vers le bon traitement
     selon sa FORME, et renvoie toujours un dictionnaire ``LogRecord``.

Ici on ne fait que découper : la conversion des types (date, port...) et
la validation se font dans ``transform.normalize_record``.
"""

import json
from typing import Any

from logengine.config import APP_FIELD_COUNT
from logengine.models import LogRecord


def decode_line(line: str) -> dict[str, Any] | tuple[str, ...] | str:
    """Première lecture de la ligne selon son préfixe."""
    if line.startswith("{"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return line                     # JSON cassé : reste une chaîne
    if line.startswith("FW "):
        return tuple(line.split())          # gère les espaces multiples
    return line


def split_endpoint(text: str) -> tuple[str, str, str]:
    """Découpe "IP:port/PROTO" en ses trois morceaux (encore en texte).

    >>> split_endpoint("10.0.3.17:51432/TCP")
    ('10.0.3.17', '51432', 'TCP')
    >>> split_endpoint("[2a01:e0a::1]:443/TCP")
    ('2a01:e0a::1', '443', 'TCP')
    """
    address, slash, protocol = text.rpartition("/")
    if not slash:                           # pas de "/PROTO" dans le champ
        address, protocol = text, ""
    host, _, port = address.rpartition(":")
    return host.strip("[]"), port, protocol


def _new_record(line: str, source: str, **fields: Any) -> LogRecord:
    """Crée un enregistrement avec les listes ``errors`` / ``fixes`` vides."""
    return {"raw": line, "source": source, "errors": [], "fixes": [],
            **fields}


def _rejected(line: str, reason: str) -> LogRecord:
    return {"raw": line, "source": "inconnu", "errors": [reason], "fixes": []}


def _parse_app_line(line: str) -> LogRecord:
    """Ligne "app" : 7 champs séparés par des "|".

    ``maxsplit=6`` : on coupe au maximum 6 fois, donc un "|" éventuel dans
    le message final ne casse pas le découpage.
    """
    fields = [field.strip() for field in line.split("|", APP_FIELD_COUNT - 1)]
    if len(fields) < APP_FIELD_COUNT:
        return _rejected(line, "champs_manquants")
    timestamp, level, service, endpoint, user, event, payload = fields
    if not user.startswith("user=") or not event.startswith("event="):
        return _rejected(line, "champs_decales")
    ip, port, protocol = split_endpoint(endpoint)
    return _new_record(
        line, "app", timestamp=timestamp, level=level, service=service,
        ip=ip, port=port, protocol=protocol,
        user=user.removeprefix("user="), event=event.removeprefix("event="),
        payload=payload)


def parse_line(line: str) -> LogRecord:
    """Route une ligne vers le bon parseur grâce au Structural Pattern
    Matching (``match`` / ``case``) au lieu d'une cascade de if/elif.

    Chaque ``case`` décrit une FORME de donnée :
      - un dict qui a les clés ts / lvl / svc / client{ip, port, proto} ;
      - un tuple qui commence par "FW" et contient au moins 9 éléments ;
      - une chaîne qui ressemble à du JSON (mais n'a pas pu être décodée) ;
      - une chaîne quelconque (format "app").
    Les variables (ts, level, ip...) sont capturées automatiquement.
    """
    match decode_line(line):
        case {"ts": timestamp, "lvl": str(level), "svc": str(service),
              "client": {"ip": ip, "port": port, "proto": protocol},
              **rest}:
            return _new_record(
                line, "json", timestamp=timestamp, level=level,
                service=service, ip=str(ip), port=str(port),
                protocol=str(protocol), user=rest.pop("user", None),
                event=str(rest.pop("event", "unknown")), payload=rest)

        case ("FW", timestamp, action, protocol, src_ip, src_port,
              dst_ip, dst_port, *rule):
            # Le tuple de connexion (IP, Port, Protocole) sera construit
            # pendant la normalisation, une fois le port converti en int.
            level = "WARNING" if action.upper() in ("DROP", "REJECT") \
                else "INFO"
            return _new_record(
                line, "firewall", timestamp=timestamp, level=level,
                service="firewall", ip=src_ip, port=src_port,
                protocol=protocol, user=None, event=f"fw_{action.lower()}",
                payload={"action": action, "dst_ip": dst_ip,
                         "dst_port": (int(dst_port) if dst_port.isdigit()
                                      else dst_port),
                         "rule": rule[0] if rule else "-"})

        case tuple():
            return _rejected(line, "pare_feu_incomplet")
        case dict():
            return _rejected(line, "json_structure_inconnue")
        case str() as text if text.startswith("{"):
            return _rejected(line, "json_invalide")
        case str() as text:
            return _parse_app_line(text)
        case _:
            return _rejected(line, "format_inconnu")
