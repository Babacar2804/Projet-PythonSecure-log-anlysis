"""Module 2 — Nettoyage et normalisation.

Ce module fournit des fonctions "unitaires" (une ligne ou un enregistrement
en entrée, un résultat en sortie). Elles sont branchées dans le pipeline
avec ``map()`` et ``filter()`` (voir ``main.py``) :

    lines   = map(clean_raw_line, lines)          # nettoyage du texte brut
    lines   = filter(tracker.keep_line, lines)    # lignes vides, commentaires
    records = map(normalize_record, records)      # types + valeurs canoniques
    records = filter(tracker.accept, records)     # rejet des lignes invalides
"""

import ipaddress
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from logengine.config import KNOWN_SERVICES, PROTOCOLS
from logengine.models import LogRecord

# ------------------------------------------------- nettoyage du texte brut
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")          # codes couleur de terminal
MULTI_PIPE_RE = re.compile(r"\|{2,}")            # "||" -> "|"
# Table de traduction : caractères de contrôle supprimés, tabulation -> espace
CONTROL_CHARS: dict[int, str | None] = {
    code: None for code in (*range(0, 32), 127, *range(0x80, 0xA0))}
CONTROL_CHARS[ord("\t")] = " "
CONTROL_CHARS[0xFEFF] = None                     # BOM
CONTROL_CHARS[0xFFFD] = None                     # octet invalide remplacé
TRACE_RE = re.compile(
    r'(Traceback \(most recent call last\)|File "|During handling'
    r"|[\w.]+(Error|Exception)\b)")


def clean_raw_line(line: str) -> str:
    """Nettoie le texte d'une ligne avant tout découpage.

    - ``strip()`` retire espaces, tabulations, "\\r" et "\\n" aux extrémités ;
    - les codes couleur ANSI et les caractères invisibles sont supprimés ;
    - les séparateurs doublés "||" sont ramenés à "|".
    Le test ``isprintable()`` (rapide, écrit en C) évite de faire le travail
    coûteux sur les ~95 % de lignes déjà propres.
    """
    line = line.strip()
    if not line.isprintable() or "�" in line:
        line = ANSI_RE.sub("", line).translate(CONTROL_CHARS).strip()
    if "||" in line:
        line = MULTI_PIPE_RE.sub("|", line)
    return line


def drop_consecutive_duplicates(lines: Iterable[str],
                                tracker: "CleaningTracker | None" = None
                                ) -> Iterator[str]:
    """Supprime les lignes identiques à la précédente.

    On ne compare qu'avec la ligne précédente : garder un ``set`` de toutes
    les lignes déjà vues ferait exploser la RAM sur 15 Go de données.
    """
    previous = None
    for line in lines:
        if line == previous:
            if tracker is not None:
                tracker.removed["doublon"] += 1
            continue
        previous = line
        yield line


# ------------------------------------------- normalisation des champs
NULL_TOKENS = frozenset({"", "-", "null", "none", "n/a", "nil", "undefined"})
USER_RE = re.compile(r"(?:u|user)[-_ ]?0*(\d+)", re.IGNORECASE)
LOGIN_RE = re.compile(r"[a-z][a-z0-9_.-]{1,31}")
SERVICE_ALIASES = {"apigw": "api-gateway", "auth": "auth-service",
                   "payment": "payment-service", "fw": "firewall"}


def normalize_level(value: str | None) -> str | None:
    """Ramène toutes les variantes d'un niveau à sa forme canonique."""
    if not isinstance(value, str):
        return None
    match value.strip().upper():
        case "DEBUG" | "DBG" | "TRACE":
            return "DEBUG"
        case "INFO" | "INF" | "INFORMATION" | "NOTICE":
            return "INFO"
        case "WARNING" | "WARN" | "WRN":
            return "WARNING"
        case "ERROR" | "ERR" | "FAIL" | "FAILURE":
            return "ERROR"
        case "CRITICAL" | "CRIT" | "FATAL" | "EMERG" | "ALERT":
            return "CRITICAL"
        case _:
            return None


def parse_timestamp(value: Any) -> tuple[datetime | None, bool]:
    """Convertit un horodatage en ``datetime`` UTC.

    Renvoie ``(datetime ou None, reformate)`` où ``reformate`` vaut True si
    la valeur n'était pas au format standard ISO 8601 "...Z".
    Formats acceptés : ISO 8601, ISO avec virgule, "jj/mm/aaaa hh:mm:ss",
    timestamp Unix (epoch). Tout le reste est rejeté.
    """
    if isinstance(value, (int, float)):
        return _from_epoch(float(value)), True
    if not isinstance(value, str) or not value:
        return None, False
    canonical = value.endswith("Z") and "T" in value
    text = value.replace("Z", "+00:00").replace(",", ".")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        moment = _parse_other_formats(value)
    if moment is None:
        return None, False
    if moment.tzinfo is None:               # sans fuseau : on suppose UTC
        moment = moment.replace(tzinfo=timezone.utc)
    if not 2000 <= moment.year <= 2100:
        return None, False
    return moment, not canonical


def _from_epoch(seconds: float) -> datetime | None:
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_other_formats(value: str) -> datetime | None:
    try:
        return _from_epoch(float(value))
    except ValueError:
        pass
    try:
        return datetime.strptime(value, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None


@lru_cache(maxsize=200_000)
def validate_ip(value: str) -> str | None:
    """Renvoie l'IP sous forme canonique, ou None si elle est invalide.

    ``lru_cache`` mémorise les réponses : le nombre d'IP différentes est
    limité, donc après quelques secondes presque tout vient du cache.
    """
    try:
        return str(ipaddress.ip_address(value.strip().strip("[]")))
    except ValueError:
        return None


@lru_cache(maxsize=200_000)
def is_private_ip(value: str) -> bool:
    return ipaddress.ip_address(value).is_private


def normalize_user(value: Any) -> tuple[str | None, bool]:
    """Ramène "U-1042", "USER_1042", "user-01042"... à "u1042".

    Renvoie ``(utilisateur ou None, modifie)``. None = utilisateur anonyme.
    """
    if not isinstance(value, str):
        return None, value is not None
    if value[:1] == "u" and value[1:].isdigit():      # cas déjà propre
        return value, False
    text = value.strip().lower()
    if text in NULL_TOKENS:
        return None, value not in ("-", "")
    if match := USER_RE.fullmatch(text):
        return f"u{int(match.group(1))}", True
    if LOGIN_RE.fullmatch(text):                      # admin, svc_backup...
        return text, text != value
    return None, True


def normalize_service(value: str) -> str:
    text = value.strip().lower().replace("_", "-")
    return SERVICE_ALIASES.get(text, text)


def fix_mojibake(text: str, fixes: list[str]) -> str:
    """Répare un texte UTF-8 qui a été relu comme du latin-1 ("Ã©" -> "é")."""
    if "Ã" not in text:
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    fixes.append("encodage_repare")
    return repaired


def parse_payload(payload: Any, fixes: list[str]) -> dict[str, Any] | str:
    """Décode le payload JSON ; tente de le réparer s'il est abîmé."""
    if isinstance(payload, dict):
        return payload
    text = str(payload)
    if not text.startswith("{"):
        return fix_mojibake(text, fixes)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:                                    # {'a': 1} -> {"a": 1}
        repaired = json.loads(text.replace("'", '"'))
    except json.JSONDecodeError:
        fixes.append("payload_irreparable")
        return text
    fixes.append("payload_repare")
    return repaired


def _clean_payload_fields(payload: dict[str, Any], fixes: list[str]) -> None:
    """Corrige les champs numériques connus du payload (sur place)."""
    for key in ("status", "code", "dst_port"):
        value = payload.get(key)
        if value is None or isinstance(value, int):
            continue
        if isinstance(value, str) and value.strip().isdigit():
            payload[key] = int(value)
            fixes.append(f"{key}_converti")
        else:
            payload[key] = None
            fixes.append(f"{key}_invalide")
    latency = payload.get("latency_ms")
    if latency is not None and not (
            isinstance(latency, (int, float)) and latency == latency
            and latency >= 0):              # latency == latency : False si NaN
        payload["latency_ms"] = None
        fixes.append("latence_invalide")
    if "action" in payload:
        payload["action"] = str(payload["action"]).upper()


def normalize_record(record: LogRecord) -> LogRecord:
    """Convertit les champs texte en types Python et valeurs canoniques.

    Les problèmes bloquants sont ajoutés à ``record["errors"]`` (la ligne
    sera rejetée), les corrections réussies à ``record["fixes"]``.
    """
    if record["errors"]:                    # déjà rejeté au parsing
        return record
    errors, fixes = record["errors"], record["fixes"]

    timestamp, reformatted = parse_timestamp(record["timestamp"])
    if timestamp is None:
        errors.append("horodatage_invalide")
    elif reformatted:
        fixes.append("horodatage_reformate")
    record["timestamp"] = timestamp

    level = normalize_level(record["level"])
    if level is None:
        errors.append("niveau_inconnu")
    else:
        # Le format JSON écrit les niveaux en minuscules : c'est sa
        # convention, pas une erreur, donc on ne compte pas de correction.
        expected = level.lower() if record["source"] == "json" else level
        if record["level"] != expected:
            fixes.append("niveau_normalise")
    record["level"] = level

    service = normalize_service(record["service"])
    if service not in KNOWN_SERVICES:
        errors.append("service_inconnu")
    elif service != record["service"]:
        fixes.append("service_normalise")
    record["service"] = service

    ip = validate_ip(record["ip"])
    if ip is None:
        errors.append("ip_invalide")
    record["ip"] = ip

    port = record["port"]
    if port.isdigit() and 0 <= int(port) <= 65535:
        record["port"] = int(port)
    else:
        errors.append("port_invalide")

    protocol = record["protocol"].strip().upper()
    if not protocol:
        protocol = "TCP"
        fixes.append("protocole_par_defaut")
    elif protocol not in PROTOCOLS:
        errors.append("protocole_inconnu")
    record["protocol"] = protocol

    user, changed = normalize_user(record["user"])
    if changed:
        fixes.append("utilisateur_normalise")
    record["user"] = user

    payload = parse_payload(record["payload"], fixes)
    if isinstance(payload, dict):
        _clean_payload_fields(payload, fixes)
    record["payload"] = payload

    if not errors:
        # Métadonnées fixes de la connexion : un tuple immuable
        record["connection"] = (ip, record["port"], protocol)
    return record


# ------------------------------------------------------ suivi qualité
class CleaningTracker:
    """Compte ce que le nettoyage supprime, rejette ou corrige.

    Ses méthodes ``keep_line`` et ``accept`` sont des prédicats : on les
    passe directement à ``filter()`` (une méthode est un objet comme un
    autre, on peut la donner en argument à une fonction).
    """

    def __init__(self, samples_per_reason: int = 5) -> None:
        self.lines_read = 0
        self.accepted = 0
        self.removed: defaultdict[str, int] = defaultdict(int)
        self.rejected: defaultdict[str, int] = defaultdict(int)
        self.fixes: defaultdict[str, int] = defaultdict(int)
        self.samples: defaultdict[str, list[str]] = defaultdict(list)
        self.samples_per_reason = samples_per_reason

    def _sample(self, reason: str, line: str) -> None:
        if len(self.samples[reason]) < self.samples_per_reason:
            self.samples[reason].append(line[:300])

    def keep_line(self, line: str) -> bool:
        """Prédicat pour ``filter`` : False = ligne supprimée avant parsing."""
        self.lines_read += 1
        if not line:
            reason = "ligne_vide"
        elif line[0] == "#":
            reason = "commentaire"
        elif line[0].isalpha() and not line.startswith("FW ") \
                and TRACE_RE.match(line):
            reason = "stacktrace"
        else:
            return True
        self.removed[reason] += 1
        self._sample(reason, line)
        return False

    def accept(self, record: LogRecord) -> bool:
        """Prédicat pour ``filter`` : True = enregistrement valide."""
        if record["errors"]:
            reason = record["errors"][0]    # on retient la première cause
            self.rejected[reason] += 1
            self._sample(reason, record["raw"])
            return False
        for fix in record["fixes"]:
            self.fixes[fix] += 1
        self.accepted += 1
        return True

    def summary(self) -> dict[str, Any]:
        removed = sum(self.removed.values())
        rejected = sum(self.rejected.values())
        return {
            "lignes_lues": self.lines_read,
            "lignes_supprimees": removed,
            "enregistrements_rejetes": rejected,
            "enregistrements_valides": self.accepted,
            "taux_de_rejet_pct": round(
                100 * (removed + rejected) / max(1, self.lines_read), 2),
            "suppressions": dict(sorted(self.removed.items())),
            "rejets": dict(sorted(self.rejected.items(),
                                  key=lambda kv: kv[1], reverse=True)),
            "corrections": dict(sorted(self.fixes.items(),
                                       key=lambda kv: kv[1], reverse=True)),
            "exemples": dict(self.samples),
        }
