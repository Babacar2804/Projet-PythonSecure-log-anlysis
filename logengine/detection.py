"""Module 3 — Détection d'attaques par force brute.

Principe en deux temps :

1. ``feed()`` est appelé sur chaque enregistrement pendant la lecture.
   Pour chaque IP, on garde une *fenêtre glissante* des échecs récents.
   Si une IP accumule ``threshold`` échecs en moins de ``window_seconds``,
   elle devient "suspecte" et on mémorise ensuite ses tentatives.

2. ``summarize()`` est appelé à la fin. Pour chaque suspect, on rejoue ses
   tentatives pour savoir si l'attaque a réussi (une connexion réussie
   juste après une série d'échecs consécutifs = compte compromis).
"""

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from logengine.config import AUTH_FAILURE_EVENTS, AUTH_SUCCESS_EVENTS
from logengine.models import LogRecord

AUTH_EVENTS = AUTH_FAILURE_EVENTS | AUTH_SUCCESS_EVENTS


class BruteForceDetector:
    """Détecteur en flux : mémoire bornée, une seule passe sur les données."""

    def __init__(self, threshold: int = 5, window_seconds: int = 120,
                 history_size: int = 500,
                 whitelist: frozenset[str] = frozenset()) -> None:
        self.threshold = threshold
        self.window = timedelta(seconds=window_seconds)
        self.history_size = history_size
        self.whitelist = whitelist
        # ip -> échecs récents [(horodatage, utilisateur), ...]
        self._recent: defaultdict[str, deque[tuple[datetime, str | None]]] = \
            defaultdict(deque)
        # ip -> informations sur l'IP suspecte
        self._suspects: dict[str, dict[str, Any]] = {}

    def feed(self, record: LogRecord) -> str | None:
        """Met à jour l'état avec un enregistrement (appelé à chaque ligne).

        Renvoie un signal utile au mode temps réel : "suspect" quand une IP
        vient de franchir le seuil, "compromis" quand une connexion réussit
        juste après une série d'échecs, sinon None.
        """
        event = record["event"]
        if event not in AUTH_EVENTS:
            return None
        ip, moment, user = record["ip"], record["timestamp"], record["user"]
        success = event in AUTH_SUCCESS_EVENTS

        suspect = self._suspects.get(ip)
        if suspect is not None:             # IP déjà suspecte : on archive
            suspect["events"].append((moment, user, success))
            suspect["last_seen"] = moment
            if not success:
                suspect["failures"] += 1
                suspect["users"].add(user)

        if success:
            # succès : compteur remis à zéro (on regarde avant s'il suivait
            # une série d'échecs suffisante)
            failures = self._recent.pop(ip, deque())
            if (len(failures) >= self.threshold
                    and moment - failures[-1][0] <= self.window):
                return "compromis"
            return None

        window = self._recent[ip]
        window.append((moment, user))
        # Boucle while : on retire de la fenêtre les échecs trop anciens
        while window and moment - window[0][0] > self.window:
            window.popleft()

        if suspect is None and len(window) >= self.threshold:
            self._suspects[ip] = {
                "first_seen": window[0][0], "last_seen": moment,
                "failures": len(window),
                "users": {u for _, u in window},
                "events": deque(((t, u, False) for t, u in window),
                                maxlen=self.history_size),
            }
            return "suspect"
        return None

    def summarize(self) -> list[dict[str, Any]]:
        """Analyse finale de chaque IP suspecte.

        Combine ``for`` (parcours des suspects puis de leurs tentatives),
        ``continue`` (on saute ce qui ne nous intéresse pas), ``break`` (on
        s'arrête dès qu'une compromission est trouvée) et ``else`` (exécuté
        seulement si la boucle est allée au bout SANS break : le cycle de
        détection est complet et aucune connexion n'a réussi).
        """
        incidents = []
        for ip, suspect in self._suspects.items():
            if ip in self.whitelist:
                continue                    # IP de confiance (supervision...)

            consecutive = 0
            last_failure: datetime | None = None
            compromised_at = compromised_user = None
            for moment, user, success in suspect["events"]:
                if not success:
                    consecutive += 1
                    last_failure = moment
                    continue
                if (consecutive >= self.threshold and last_failure is not None
                        and moment - last_failure <= self.window):
                    # attaque réussie : inutile de chercher plus loin
                    compromised_at, compromised_user = moment, user
                    break
                consecutive = 0             # succès "normal" : on repart à 0
            else:
                # Pas de break : toutes les tentatives ont été analysées et
                # aucune n'a abouti -> attaque bloquée.
                status = "bloquee"

            if compromised_at is not None:
                status = "COMPROMIS"
                severity = "CRITICAL"
            elif suspect["failures"] >= 4 * self.threshold:
                severity = "HIGH"
            else:
                severity = "MEDIUM"

            users = suspect["users"] - {None}
            incidents.append({
                "ip": ip,
                "statut": status,
                "severite": severity,
                "type": ("credential_stuffing" if len(users) > 3
                         else "force_brute"),
                "echecs": suspect["failures"],
                "utilisateurs_cibles": len(users),
                "exemple_utilisateurs": ", ".join(sorted(users)[:5]),
                "premiere_tentative": suspect["first_seen"].isoformat(),
                "derniere_tentative": suspect["last_seen"].isoformat(),
                "compte_compromis": compromised_user or "",
                "compromis_le": (compromised_at.isoformat()
                                 if compromised_at else ""),
            })
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        return sorted(incidents, key=lambda i: (order[i["severite"]],
                                                -i["echecs"]))
