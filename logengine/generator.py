"""Générateur du jeu de données : des logs volumineux, variés et "sales".

Trois formats de lignes cohabitent dans les fichiers (~80 % / 10 % / 10 %) :

  app      2026-10-01T08:15:32.481Z | INFO | api-gateway | 10.0.3.17:51432/TCP
           | user=u1042 | event=http_request | {"method":"GET",...}
  json     {"ts":"2026-10-01T08:15:32.481Z","lvl":"error","svc":"payment-...",
           "client":{"ip":"...","port":443,"proto":"TCP"},"user":"u12",...}
  firewall FW 2026-10-01T08:15:32.481Z DROP TCP 185.23.1.4 4444 10.0.100.5 22
           DENY-SSH-EXT

Le dernier champ d'une ligne "app" est soit un payload JSON, soit une chaîne
brute (message texte).

Pour que les analyses soient intéressantes, le générateur simule :
  - un profil d'activité (heures creuses la nuit, pics en journée, week-end
    plus calme) ;
  - des scénarios : pannes de service, attaques DDoS, déploiements, disque
    qui se remplit ;
  - des attaques : force brute (avec parfois compromission du compte), scans
    de ports, injections SQL, XSS, path traversal, outils de piratage.

Et pour le nettoyage, une partie des lignes est volontairement abîmée par
``NoiseInjector`` (casse des niveaux, IP invalides, JSON cassé, doublons,
lignes vides, caractères de contrôle, mauvais encodage, stack traces...).

Chaque fichier couvre une tranche de temps (comme une rotation de logs) et
est écrit par un processus séparé pour aller plus vite.
"""

import json
import random
import re
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import accumulate
from operator import itemgetter
from pathlib import Path
from typing import Any

from logengine.config import BLACKLIST_NAME, FIELD_SEP

START_DATE = datetime(2026, 10, 1, tzinfo=timezone.utc)
MINUTES_PER_DAY = 24 * 60

# Poids relatif du trafic pour chaque heure de la journée (0h -> 23h)
HOURLY_ACTIVITY = (
    0.25, 0.18, 0.12, 0.10, 0.10, 0.15, 0.30, 0.55, 0.85, 1.00, 1.10, 1.05,
    0.90, 0.95, 1.10, 1.15, 1.05, 0.95, 0.85, 0.80, 0.85, 0.75, 0.55, 0.40,
)
WEEKEND_FACTOR = 0.6
FIREWALL_SHARE = 0.10

# (service, poids dans le trafic)
SERVICE_WEIGHTS = (
    ("api-gateway", 30), ("cdn-edge", 14), ("auth-service", 12),
    ("payment-service", 7), ("user-service", 6), ("inventory-service", 6),
    ("db-cluster", 6), ("cache-redis", 5), ("mail-service", 4),
    ("vpn-gateway", 4), ("scheduler", 3),
)
SERVICE_NAMES = tuple(name for name, _ in SERVICE_WEIGHTS)
SERVICE_CUM = tuple(accumulate(weight for _, weight in SERVICE_WEIGHTS))

# (méthode, chemin, poids, mu de la latence log-normale)
ENDPOINTS = (
    ("GET", "/", 8, 3.5),
    ("GET", "/api/v1/products", 12, 4.0),
    ("GET", "/api/v1/products/{id}", 15, 3.8),
    ("GET", "/api/v1/search?q={term}", 6, 4.6),
    ("GET", "/api/v1/cart", 6, 3.9),
    ("POST", "/api/v1/cart", 5, 4.2),
    ("DELETE", "/api/v1/cart/{id}", 1, 3.9),
    ("POST", "/api/v1/orders", 3, 5.0),
    ("GET", "/api/v1/orders/{id}", 4, 4.1),
    ("GET", "/api/v1/users/me", 7, 3.6),
    ("PUT", "/api/v1/users/me", 1, 4.5),
    ("GET", "/api/v2/recommendations", 3, 5.2),
    ("GET", "/health", 4, 1.5),
)
ENDPOINT_CUM = tuple(accumulate(e[2] for e in ENDPOINTS))
STATIC_PATHS = (
    "/static/js/app.{id}.js", "/static/css/main.css",
    "/img/products/{id}.webp",
    "/img/banners/promo-{id}.jpg", "/fonts/inter.woff2", "/favicon.ico",
)
SEARCH_TERMS = (
    "chaussures", "laptop", "casque", "velo", "montre", "jean", "cafetiere",
    "telephone", "sac", "livre", "lampe", "clavier",
)

# (code HTTP, poids) pour le trafic normal
STATUS_WEIGHTS = (
    (200, 80), (201, 3), (204, 2), (301, 1), (304, 4), (400, 2), (401, 1.5),
    (403, 1), (404, 4), (429, 0.3), (500, 0.7), (502, 0.3), (503, 0.3),
    (504, 0.2),
)
STATUS_CODES = tuple(code for code, _ in STATUS_WEIGHTS)
STATUS_CUM = tuple(accumulate(weight for _, weight in STATUS_WEIGHTS))

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/130.0 Mobile",
    "ShopApp/4.2.1 (Android 14)", "ShopApp/4.2.0 (iOS 18.0)",
    "Googlebot/2.1 (+http://www.google.com/bot.html)", "curl/8.4.0",
    "python-requests/2.32.3",
)
UA_CUM = tuple(accumulate((30, 15, 10, 15, 12, 6, 5, 3, 2, 2)))
ATTACK_AGENTS = (
    "sqlmap/1.8.3#stable", "Nikto/2.5.0", "Hydra v9.5", "masscan/1.3",
    "gobuster/3.6", "curl/8.4.0", "python-requests/2.32.3",
)

SPECIAL_USERS = ("admin", "root", "svc_backup", "svc_deploy", "guest", "test")
USER_COUNT = 5000

SQLI_PAYLOADS = (
    "/api/v1/search?q=' OR '1'='1", "/api/v1/products?id=1 UNION SELECT "
    "username,password FROM users--", "/login?user=admin'--",
    "/api/v1/orders?id=1; DROP TABLE orders", "/api/v1/search?q=1' AND "
    "SLEEP(5)--",
)
XSS_PAYLOADS = (
    "/api/v1/search?q=<script>alert('x')</script>",
    "/api/v1/comments?text=<img src=x onerror=alert(1)>",
    "/profile?name=javascript:alert(document.cookie)",
)
TRAVERSAL_PAYLOADS = (
    "/static/../../../../etc/passwd", "/download?file=..%2f..%2fetc%2fshadow",
    "/img/..\\..\\windows\\win.ini", "/api/v1/files?path=../../../app/.env",
)
PROBE_PATHS = (
    "/wp-admin/install.php", "/.env", "/phpmyadmin/index.php", "/.git/config",
    "/admin.php", "/cgi-bin/test.cgi", "/actuator/env", "/server-status",
)

# --- Messages "chaîne brute" (accents en minuscules volontairement : ils
#     servent à tester la réparation d'encodage)
DB_MESSAGES = (
    ("DEBUG", "query_executed", "requête exécutée en {n} ms sur la table {t}"),
    ("INFO", "connection_pool", "pool de connexions : {p}/50 utilisées"),
    ("INFO", "checkpoint", "checkpoint terminé en {n} ms"),
    ("WARNING", "query_slow", "requête lente ({n} ms) sur la table {t}"),
    ("WARNING", "replication_lag", "réplication en retard de {s} s sur "
                                   "db-replica-{r}"),
    ("ERROR", "deadlock", "deadlock détecté sur la table {t}, transaction "
                          "annulée"),
)
DB_CUM = tuple(accumulate((30, 25, 15, 15, 10, 1)))
DB_TABLES = ("orders", "users", "payments", "products", "sessions", "carts")
CACHE_MESSAGES = (
    ("DEBUG", "cache_hit", "taux de succès du cache : {p} %"),
    ("INFO", "cache_stats", "{n} clés en mémoire, {p} % de mémoire utilisée"),
    ("WARNING", "cache_eviction", "éviction de {n} clés (maxmemory atteint)"),
    ("ERROR", "replica_lost", "connexion perdue avec le réplica redis-{r}"),
)
CACHE_CUM = tuple(accumulate((40, 40, 15, 1)))
SCHEDULER_JOBS = (
    "nightly-backup", "invoice-export", "cleanup-sessions", "sitemap-build",
    "newsletter-send", "stock-sync",
)

COMMENT_LINES = (
    "# ---- logrotate : nouveau fichier ----", "### HEALTHCHECK OK ###",
    "# agent de collecte redémarré", "#" * 40,
)
STACKTRACE = (
    "Traceback (most recent call last):",
    '  File "/app/{svc}/handlers.py", line {n}, in handle_request',
    '  File "/app/{svc}/client.py", line {m}, in call_upstream',
    "{exc}: {msg}",
)
EXCEPTIONS = (
    ("TimeoutError", "upstream did not respond within 30s"),
    ("ConnectionResetError", "[Errno 104] Connection reset by peer"),
    ("psycopg2.OperationalError", "could not connect to server"),
    ("KeyError", "'order_id'"),
    ("ValueError", "invalid literal for int() with base 10: 'abc'"),
)

PUBLIC_FIRST_OCTETS = (
    23, 31, 37, 41, 45, 51, 62, 77, 78, 80, 81, 82, 85, 86, 88, 89, 90, 91,
    92, 93, 94, 95, 102, 103, 104, 109, 129, 141, 145, 151, 154, 176, 178,
    185, 188, 193, 194, 195, 196, 197, 212, 213, 217,
)


def _public_ip(rng: random.Random) -> str:
    """Tire une adresse IPv4 publique plausible."""
    first = rng.choice(PUBLIC_FIRST_OCTETS)
    return f"{first}.{rng.randint(0, 255)}.{rng.randint(0, 255)}." \
           f"{rng.randint(1, 254)}"


def _unique(rng: random.Random, maker, count: int,
            exclude: set[str] | None = None) -> list[str]:
    """Construit une liste de ``count`` valeurs distinctes."""
    seen: set[str] = set(exclude or ())
    values: list[str] = []
    while len(values) < count:
        value = maker(rng)
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


class Pools:
    """Populations partagées par tous les fichiers (même graine = mêmes IP).

    Les tailles sont bornées (5 000 utilisateurs, ~17 000 IP) : c'est
    réaliste et ça garantit que les ``set`` et ``defaultdict`` de l'analyse
    restent petits en mémoire, même sur 15 Go de logs.
    """

    def __init__(self, seed: int) -> None:
        rng = random.Random(seed)
        self.users = [f"u{n}" for n in range(1, USER_COUNT + 1)]
        # Loi de Zipf : quelques utilisateurs très actifs, beaucoup de rares
        self.user_cum = list(accumulate(
            1 / rank ** 0.9 for rank in range(1, USER_COUNT + 1)))
        self.internal = _unique(
            rng, lambda r: f"10.0.{r.randint(0, 31)}.{r.randint(1, 254)}",
            1500)
        self.servers = [f"10.0.100.{n}" for n in range(10, 60)]
        self.office = [f"192.168.1.{n}" for n in range(2, 230)]
        self.external = _unique(rng, _public_ip, 15000)
        self.external_cum = list(accumulate(
            1 / rank ** 0.6 for rank in range(1, len(self.external) + 1)))
        self.ipv6 = _unique(
            rng, lambda r: f"2a01:e0a:{r.randint(1, 0xffff):x}:"
                           f"{r.randint(1, 0xffff):x}::"
                           f"{r.randint(1, 0xfff):x}",
            300)
        taken = set(self.external)
        self.attackers = _unique(rng, _public_ip, 60, taken)
        taken.update(self.attackers)
        self.botnet = _unique(rng, _public_ip, 400, taken)
        taken.update(self.botnet)
        # Liste noire : une partie des attaquants connus + des IP "dormantes"
        # qui n'apparaîtront jamais dans les logs.
        self.blacklist = (rng.sample(self.attackers, 40)
                          + rng.sample(self.botnet, 150)
                          + _unique(rng, _public_ip, 300, taken))


class LogFactory:
    """Fabrique des lignes de logs propres, sous forme de "morceaux".

    Chaque méthode renvoie un tuple ``(format, parts)`` :
      - ("app", [ts, level, service, endpoint, user, event, payload])
      - ("json", {...})
      - ("fw", [jetons...])
    C'est ``NoiseInjector`` qui assemble la ligne finale (et l'abîme parfois).
    """

    def __init__(self, pools: Pools, rng: random.Random) -> None:
        self.pools = pools
        self.rng = rng

    # ------------------------------------------------------------ outils
    def client_ip(self) -> str:
        rng = self.rng
        r = rng.random()
        if r < 0.70:
            return rng.choices(self.pools.external,
                               cum_weights=self.pools.external_cum)[0]
        if r < 0.88:
            return rng.choice(self.pools.internal)
        if r < 0.97:
            return rng.choice(self.pools.office)
        return rng.choice(self.pools.ipv6)

    def user(self) -> str:
        return self.rng.choices(self.pools.users,
                                cum_weights=self.pools.user_cum)[0]

    def endpoint(self, ip: str, proto: str = "TCP") -> str:
        port = self.rng.randint(1024, 65535)
        if ":" in ip:                       # IPv6 -> notation [ip]:port
            return f"[{ip}]:{port}/{proto}"
        return f"{ip}:{port}/{proto}"

    @staticmethod
    def level_for_status(status: int) -> str:
        if status >= 500:
            return "ERROR"
        if status >= 400:
            return "WARNING"
        return "INFO"

    def app(self, ts: str, level: str, service: str, ip: str,
            user: str | None, event: str, payload: str) -> tuple[str, list]:
        return "app", [ts, level, service, self.endpoint(ip),
                       f"user={user or '-'}", f"event={event}", payload]

    # ------------------------------------------------- trafic normal
    def normal(self, ts: str, ctx: dict) -> tuple[str, Any]:
        """Choisit un évènement "normal" selon le poids des services."""
        rng = self.rng
        if ctx["ddos"] and rng.random() < 0.6:
            return self.ddos_flood(ts)
        if rng.random() < FIREWALL_SHARE:
            return self.firewall_normal(ts)
        service = rng.choices(SERVICE_NAMES, cum_weights=SERVICE_CUM)[0]
        match service:
            case "api-gateway":
                return self.http_request(ts, ctx)
            case "cdn-edge":
                return self.static_request(ts)
            case "auth-service":
                return self.auth_normal(ts, ctx)
            case "payment-service":
                return self.payment_json(ts, ctx)
            case "user-service":
                return self.user_json(ts)
            case "inventory-service":
                return self.inventory(ts)
            case "db-cluster":
                return self.database(ts, ctx)
            case "cache-redis":
                return self.cache(ts)
            case "mail-service":
                return self.mail(ts)
            case "vpn-gateway":
                return self.vpn(ts)
            case _:
                return self.scheduler(ts)

    def http_request(self, ts: str, ctx: dict) -> tuple[str, list]:
        rng = self.rng
        if rng.random() < 0.002:            # rare : une attaque web
            return self.web_attack(ts)
        method, template, _, mu = rng.choices(
            ENDPOINTS, cum_weights=ENDPOINT_CUM)[0]
        path = template.format(id=rng.randint(1, 99999),
                               term=rng.choice(SEARCH_TERMS))
        degraded = ("payment-service" in ctx["outage"] and "orders" in path) \
            or "api-gateway" in ctx["deploy"]
        if degraded and rng.random() < 0.5:
            status = rng.choice((500, 502, 503, 504))
            latency = int(rng.lognormvariate(mu, 0.6) * 8)
        else:
            status = rng.choices(STATUS_CODES, cum_weights=STATUS_CUM)[0]
            latency = int(rng.lognormvariate(mu, 0.6))
        size = rng.randint(300, 60000) if status < 300 else rng.randint(0, 600)
        ua = rng.choices(USER_AGENTS, cum_weights=UA_CUM)[0]
        user = self.user() if rng.random() < 0.6 else None
        level = "DEBUG" if path == "/health" else self.level_for_status(status)
        payload = (f'{{"method":"{method}","path":"{path}","status":{status},'
                   f'"latency_ms":{latency},"bytes":{size},"ua":"{ua}"}}')
        return self.app(ts, level, "api-gateway", self.client_ip(), user,
                        "http_request", payload)

    def static_request(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        path = rng.choice(STATIC_PATHS).format(id=rng.randint(1, 5000))
        status = rng.choices((200, 304, 404), weights=(80, 17, 3))[0]
        level = self.level_for_status(status)
        payload = (f'{{"method":"GET","path":"{path}","status":{status},'
                   f'"latency_ms":{int(rng.lognormvariate(2.2, 0.5))},'
                   f'"bytes":{rng.randint(500, 900000)},"cache":'
                   f'"{rng.choice(("HIT", "HIT", "HIT", "MISS"))}"}}')
        return self.app(ts, level, "cdn-edge", self.client_ip(), None,
                        "http_request", payload)

    def auth_normal(self, ts: str, ctx: dict) -> tuple[str, list]:
        rng = self.rng
        ip, user = self.client_ip(), self.user()
        if "auth-service" in ctx["outage"] and rng.random() < 0.4:
            return self.app(ts, "ERROR", "auth-service", ip, user,
                            "login_error", "annuaire LDAP injoignable, "
                            "authentification impossible")
        r = rng.random()
        if r < 0.55:
            method = rng.choice(("password", "sso", "mfa"))
            return self.app(ts, "INFO", "auth-service", ip, user,
                            "login_success",
                            f'{{"method":"{method}","session":'
                            f'"s-{rng.getrandbits(32):08x}"}}')
        if r < 0.67:
            return self.login_failed(ts, ip, user, 1, None)
        if r < 0.82:
            return self.app(ts, "INFO", "auth-service", ip, user, "logout",
                            f"déconnexion de {user}")
        if r < 0.95:
            return self.app(ts, "DEBUG", "auth-service", ip, user,
                            "token_refresh", '{"ttl_s":3600}')
        if r < 0.98:
            return self.app(ts, "INFO", "auth-service", ip, user,
                            "password_reset", f"mail de réinitialisation "
                            f"envoyé à {user}")
        return self.app(ts, "INFO", "auth-service", ip, user,
                        "mfa_challenge", '{"channel":"totp"}')

    def login_failed(self, ts: str, ip: str, user: str, attempt: int,
                     ua: str | None) -> tuple[str, list]:
        rng = self.rng
        reason = rng.choice(("bad_password", "bad_password", "unknown_user",
                             "account_locked"))
        if ua is None and rng.random() < 0.4:
            # tantôt une chaîne brute, tantôt un JSON : les deux existent
            payload = f"échec de connexion pour {user} : {reason}"
        else:
            payload = (f'{{"reason":"{reason}","attempt":{attempt},'
                       f'"ua":"{ua or rng.choice(USER_AGENTS[:5])}"}}')
        return self.app(ts, "WARNING", "auth-service", ip, user,
                        "login_failed", payload)

    def login_success(self, ts: str, ip: str, user: str) -> tuple[str, list]:
        return self.app(ts, "INFO", "auth-service", ip, user, "login_success",
                        f'{{"method":"password","session":'
                        f'"s-{self.rng.getrandbits(32):08x}"}}')

    def payment_json(self, ts: str, ctx: dict) -> tuple[str, dict]:
        rng = self.rng
        outage = "payment-service" in ctx["outage"]
        deploying = "payment-service" in ctx["deploy"]
        r = rng.random()
        if outage and r < 0.6:
            event, lvl, code, msg = ("payment_failed", "error", 504,
                                     "upstream bank gateway timeout")
        elif deploying and r < 0.2:
            event, lvl, code, msg = ("payment_failed", "error", 500,
                                     "internal error after deployment")
        elif r < 0.80:
            event, lvl, code, msg = ("payment_authorized", "info", 200,
                                     "payment accepted")
        elif r < 0.92:
            event, lvl, code, msg = ("payment_failed", "error",
                                     rng.choice((402, 402, 502)),
                                     rng.choice(("card declined",
                                                 "insufficient funds",
                                                 "bank gateway error")))
        elif r < 0.97:
            event, lvl, code, msg = "refund", "info", 200, "refund issued"
        else:
            event, lvl, code, msg = ("fraud_check", "warning", 403,
                                     "transaction flagged by fraud engine")
        return "json", {
            "ts": ts, "lvl": lvl, "svc": "payment-service",
            "client": {"ip": self.client_ip(), "port": 443, "proto": "TCP"},
            "user": self.user(), "event": event, "code": code, "msg": msg,
            "amount": round(rng.lognormvariate(3.8, 0.9), 2),
            "currency": rng.choices(("EUR", "USD", "GBP"), (80, 15, 5))[0],
            "order_id": f"ORD-{rng.randint(100000, 999999)}",
        }

    def user_json(self, ts: str) -> tuple[str, dict]:
        rng = self.rng
        event, lvl = rng.choices(
            (("profile_update", "info"), ("account_created", "info"),
             ("email_verified", "info"), ("account_deleted", "warning"),
             ("profile_update_failed", "error")),
            (60, 20, 15, 4, 1))[0]
        return "json", {
            "ts": ts, "lvl": lvl, "svc": "user-service",
            "client": {"ip": self.client_ip(), "port": 443, "proto": "TCP"},
            "user": self.user(), "event": event,
            "code": 500 if lvl == "error" else 200,
            "msg": event.replace("_", " "),
        }

    def inventory(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        sku, stock = f"SKU-{rng.randint(10000, 99999)}", rng.randint(0, 500)
        if stock < 10:
            return self.app(ts, "WARNING", "inventory-service",
                            rng.choice(self.pools.servers), "svc_stock",
                            "stock_low", f'{{"sku":"{sku}","stock":{stock}}}')
        return self.app(ts, "INFO", "inventory-service",
                        rng.choice(self.pools.servers), "svc_stock",
                        "stock_update",
                        f'{{"sku":"{sku}","delta":{rng.randint(-5, 20)},'
                        f'"stock":{stock}}}')

    def database(self, ts: str, ctx: dict) -> tuple[str, list]:
        rng = self.rng
        server = rng.choice(self.pools.servers)
        if "db-cluster" in ctx["outage"] and rng.random() < 0.5:
            return self.app(ts, "ERROR", "db-cluster", server, None,
                            "connection_refused", "connexion refusée : trop "
                            "de clients (max_connections=500)")
        level, event, template = rng.choices(DB_MESSAGES,
                                             cum_weights=DB_CUM)[0]
        message = template.format(n=rng.randint(1, 4000), t=rng.choice(
            DB_TABLES), p=rng.randint(5, 50), s=round(rng.uniform(1, 30), 1),
            r=rng.randint(1, 3))
        return self.app(ts, level, "db-cluster", server, "svc_db", event,
                        message)

    def cache(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        level, event, template = rng.choices(CACHE_MESSAGES,
                                             cum_weights=CACHE_CUM)[0]
        message = template.format(n=rng.randint(100, 900000),
                                  p=rng.randint(40, 99), r=rng.randint(1, 3))
        return self.app(ts, level, "cache-redis",
                        rng.choice(self.pools.servers), None, event, message)

    def mail(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        domain = rng.choice(("gmail.com", "outlook.fr", "yahoo.fr",
                             "orange.fr", "free.fr", "proton.me"))
        template = rng.choice(("order_confirmation", "password_reset",
                               "newsletter", "shipping_update"))
        if rng.random() < 0.05:
            return self.app(ts, "WARNING", "mail-service",
                            rng.choice(self.pools.servers), None,
                            "email_bounce",
                            f'{{"to_domain":"{domain}","template":'
                            f'"{template}","smtp_code":550}}')
        return self.app(ts, "INFO", "mail-service",
                        rng.choice(self.pools.servers), None, "email_sent",
                        f'{{"to_domain":"{domain}","template":"{template}"}}')

    def vpn(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        ip, user = self.client_ip(), self.user()
        country = rng.choices(("FR", "FR", "BE", "ES", "DE", "US", "MA", "CN"),
                              (50, 20, 6, 6, 6, 5, 5, 2))[0]
        event, level = rng.choices(
            (("vpn_connect", "INFO"), ("vpn_disconnect", "INFO"),
             ("vpn_auth_failed", "WARNING")), (48, 47, 5))[0]
        return "app", [ts, level, "vpn-gateway", self.endpoint(ip, "UDP"),
                       f"user={user}", f"event={event}",
                       f'{{"country":"{country}","tunnel":"wg0"}}']

    def scheduler(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        job = rng.choice(SCHEDULER_JOBS)
        r = rng.random()
        if r < 0.47:
            level, event, msg = "INFO", "job_started", f"job {job} démarré"
        elif r < 0.95:
            level, event, msg = ("INFO", "job_finished", f"job {job} terminé "
                                 f"en {rng.randint(1, 900)} s")
        else:
            level, event, msg = ("ERROR", "job_failed", f"job {job} échoué : "
                                 f"timeout après 3600 s")
        return self.app(ts, level, "scheduler",
                        rng.choice(self.pools.servers), "svc_cron", event, msg)

    def firewall_normal(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        server = rng.choice(self.pools.servers)
        src = self.client_ip()
        if ":" in src:                      # le pare-feu ne logue que l'IPv4
            src = rng.choice(self.pools.external)
        r = rng.random()
        if r < 0.85:
            port = rng.choice((443, 443, 443, 80))
            return "fw", ["FW", ts, "ACCEPT", "TCP", src,
                          str(rng.randint(1024, 65535)), server, str(port),
                          "ALLOW-HTTPS" if port == 443 else "ALLOW-HTTP"]
        if r < 0.999:
            proto = rng.choices(("TCP", "UDP", "ICMP"), (85, 13, 2))[0]
            port, rule = rng.choice(((22, "DENY-SSH-EXT"), (3389, "DENY-RDP"),
                                     (445, "DENY-SMB"), (23, "DENY-TELNET"),
                                     (8080, "DEFAULT-DROP"),
                                     (1433, "DEFAULT-DROP")))
            if proto == "ICMP":
                port, rule = 0, "DENY-ICMP"
            return "fw", ["FW", ts, "DROP", proto, src,
                          str(rng.randint(1024, 65535)), server, str(port),
                          rule]
        # Très rare : un port sensible ouvert sur Internet (mauvaise config)
        return "fw", ["FW", ts, "ACCEPT", "TCP", src,
                      str(rng.randint(1024, 65535)), server,
                      str(rng.choice((22, 3389, 5432))), "TEMP-ALLOW-DEBUG"]

    # ------------------------------------------------------- attaques
    def web_attack(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        kind = rng.choice((SQLI_PAYLOADS, XSS_PAYLOADS, TRAVERSAL_PAYLOADS,
                           PROBE_PATHS))
        path = rng.choice(kind)
        status = rng.choice((400, 403, 404, 404, 500, 200))
        ua = rng.choice(ATTACK_AGENTS) if rng.random() < 0.6 \
            else rng.choice(USER_AGENTS)
        # json.dumps échappe correctement les guillemets des payloads
        payload = json.dumps({"method": "GET", "path": path, "status": status,
                              "latency_ms": rng.randint(5, 900),
                              "bytes": rng.randint(0, 2000), "ua": ua},
                             separators=(",", ":"))
        return self.app(ts, self.level_for_status(status), "api-gateway",
                        rng.choice(self.pools.attackers), None,
                        "http_request", payload)

    def ddos_flood(self, ts: str) -> tuple[str, list]:
        rng = self.rng
        ip = rng.choice(self.pools.botnet)
        if rng.random() < 0.3:
            return "fw", ["FW", ts, "DROP", "TCP", ip,
                          str(rng.randint(1024, 65535)),
                          rng.choice(self.pools.servers), "443", "RATE-LIMIT"]
        status = rng.choices((429, 503, 200), (60, 25, 15))[0]
        path = rng.choice(("/", "/api/v1/search?q=a", "/api/v1/products"))
        payload = (f'{{"method":"GET","path":"{path}","status":{status},'
                   f'"latency_ms":{rng.randint(1, 30000)},"bytes":0,'
                   f'"ua":"Mozilla/5.0"}}')
        return self.app(ts, self.level_for_status(status), "api-gateway", ip,
                        None, "http_request", payload)

    def port_scan_probe(self, ts: str, ip: str, target: str,
                        port: int) -> tuple[str, list]:
        return "fw", ["FW", ts, "DROP", "TCP", ip,
                      str(self.rng.randint(40000, 65535)), target, str(port),
                      "DEFAULT-DROP"]

    def privilege_escalation(self, ts: str, ip: str,
                             user: str) -> tuple[str, list]:
        return self.app(ts, "CRITICAL", "auth-service", ip, user,
                        "privilege_escalation",
                        f'{{"from_role":"user","to_role":"admin",'
                        f'"account":"{user}"}}')

    def data_export(self, ts: str, ip: str, user: str) -> tuple[str, list]:
        return self.app(ts, "WARNING", "api-gateway", ip, user, "data_export",
                        f'{{"method":"GET","path":"/api/v1/admin/export?table'
                        f'=users","status":200,"latency_ms":'
                        f'{self.rng.randint(2000, 9000)},"bytes":'
                        f'{self.rng.randint(5_000_000, 90_000_000)},'
                        f'"ua":"python-requests/2.32.3"}}')

    def announce(self, ts: str, level: str, service: str, event: str,
                 message: str) -> tuple[str, list]:
        return self.app(ts, level, service,
                        self.rng.choice(self.pools.servers),
                        "svc_deploy" if service == "scheduler" else None,
                        event, message)

    # --------------------------------------------- évènements spéciaux
    def special_events(self, minute: int, ctx: dict) -> list[tuple]:
        """Évènements de scénario à placer dans la minute courante.

        Renvoie une liste de ``(seconde, (méthode, arguments))`` : la ligne
        sera fabriquée plus tard avec ``methode(ts, *arguments)``.
        """
        rng = self.rng
        events: list[tuple] = []
        if rng.random() < 0.02:
            self._brute_force(events)
        if rng.random() < 0.01:
            self._port_scan(events)
        for service in ctx["outage"]:
            for _ in range(rng.randint(2, 6)):
                events.append((rng.uniform(0, 59.9), (
                    self.announce, ("CRITICAL", "api-gateway",
                                    "circuit_breaker_open",
                                    f"circuit breaker ouvert vers {service} "
                                    f"(50 échecs consécutifs)"))))
        for scenario in ctx["starting"]:
            events.append((0.0, (self.announce, self._start_message(
                scenario))))
        if ctx["disk"] is not None:
            pct = ctx["disk"]
            level = "CRITICAL" if pct >= 98 else "WARNING"
            message = ("disque plein, écritures refusées" if pct >= 98 else
                       f"espace disque /var/lib/postgresql à {pct} %")
            events.append((rng.uniform(0, 59.9), (
                self.announce, (level, "db-cluster", "disk_usage", message))))
        return events

    @staticmethod
    def _start_message(scenario: dict) -> tuple:
        match scenario["kind"]:
            case "deploy":
                return ("INFO", "scheduler", "deploy_started",
                        f"déploiement de {scenario['service']} "
                        f"v{scenario['version']} démarré")
            case "outage":
                return ("CRITICAL", scenario["service"], "service_down",
                        f"{scenario['service']} ne répond plus "
                        f"(healthcheck KO)")
            case "ddos":
                return ("WARNING", "api-gateway", "traffic_spike",
                        "pic de trafic anormal détecté, rate limiting activé")
            case _:
                return ("INFO", "scheduler", "maintenance",
                        f"début de scénario {scenario['kind']}")

    def _brute_force(self, events: list[tuple]) -> None:
        """Rafale d'échecs de connexion depuis une même IP."""
        rng = self.rng
        ip = rng.choice(self.pools.attackers)
        # credential stuffing : un compte différent à chaque tentative
        stuffing = rng.random() < 0.3
        target = (rng.choice(SPECIAL_USERS) if rng.random() < 0.6
                  else self.user())
        ua = rng.choice(("Hydra v9.5", "python-requests/2.32.3", "curl/8.4.0",
                         USER_AGENTS[0]))
        sec = rng.uniform(0, 20)
        for attempt in range(1, rng.randint(6, 40) + 1):
            if sec > 59.9:
                break
            user = self.user() if stuffing else target
            events.append((sec, (self.login_failed, (ip, user, attempt, ua))))
            sec += rng.uniform(0.2, 1.2)
        # ~18 % des attaques réussissent... suivies d'actions malveillantes
        if not stuffing and rng.random() < 0.18 and sec < 55:
            events.append((sec, (self.login_success, (ip, target))))
            events.append((sec + 2, (self.privilege_escalation, (ip, target))))
            events.append((sec + 4, (self.data_export, (ip, target))))

    def _port_scan(self, events: list[tuple]) -> None:
        rng = self.rng
        ip = rng.choice(self.pools.attackers)
        target = rng.choice(self.pools.servers)
        first_port = rng.choice((1, 20, 1000, 3000, 8000))
        sec = rng.uniform(0, 30)
        for port in range(first_port, first_port + rng.randint(20, 80)):
            events.append((min(sec, 59.9), (self.port_scan_probe,
                                            (ip, target, port))))
            sec += rng.uniform(0.05, 0.3)


# ---------------------------------------------------------------- bruit
LEVEL_VARIANTS = {
    "DEBUG": ("debug", "DBG", "Debug", "trace"),
    "INFO": ("info", "Info", "INF", "information", " INFO "),
    "WARNING": ("warn", "WARN", "Warning", "wrn"),
    "ERROR": ("error", "ERR", "Error", "err"),
    "CRITICAL": ("crit", "FATAL", "Critical", "CRIT"),
}
BAD_ENDPOINTS = (
    "999.12.4.1:443/TCP", "-", "N/A", "10.0.0:8080/TCP", "localhost:80/TCP",
    "256.256.256.256:22/TCP", "1.2.3.4:abc/TCP", "1.2.3.4:99999/TCP",
)
# (type de défaut, poids) — par format de ligne
APP_NOISE = (
    ("level_case", 14), ("spaces", 10), ("user_noise", 10), ("ts_alt", 8),
    ("ts_bad", 3), ("bad_ip", 5), ("no_proto", 3), ("duplicate", 8),
    ("blank", 6), ("garbage", 6), ("ansi", 4), ("broken_json", 5),
    ("quote_json", 5), ("truncate", 4), ("missing_field", 3),
    ("double_sep", 4), ("service_case", 6), ("status_str", 4),
    ("latency_bad", 3), ("mojibake", 4), ("crlf", 4), ("comment", 2),
)
JSON_NOISE = (
    ("level_case", 20), ("spaces", 10), ("duplicate", 10), ("blank", 5),
    ("ts_epoch", 10), ("user_noise", 10), ("truncate", 10),
    ("missing_client", 5), ("code_str", 10),
)
FW_NOISE = (
    ("action_case", 25), ("spaces", 20), ("duplicate", 15), ("bad_port", 10),
    ("truncate", 15), ("bad_ip", 15),
)
NOISE = {fmt: (tuple(k for k, _ in table),
               tuple(accumulate(w for _, w in table)))
         for fmt, table in (("app", APP_NOISE), ("json", JSON_NOISE),
                            ("fw", FW_NOISE))}
STATUS_RE = re.compile(r'"status":(\d+)')
LATENCY_RE = re.compile(r'"latency_ms":\d+')


class NoiseInjector:
    """Assemble les lignes et en abîme une petite partie (``rate``).

    Toutes les lignes abîmées ne sont pas perdues : certaines sont
    réparables (casse, espaces, format de date, guillemets simples...),
    d'autres doivent être rejetées (IP impossible, ligne tronquée...).
    C'est exactement ce que le nettoyage devra distinguer.
    """

    def __init__(self, rng: random.Random, rate: float) -> None:
        self.rng = rng
        self.rate = rate

    def emit(self, fmt: str, parts: Any, out: list[str]) -> None:
        """Ajoute la (ou les) ligne(s) finale(s) dans ``out``."""
        rng = self.rng
        if rng.random() >= self.rate:       # cas le plus fréquent : propre
            out.append(self.render(fmt, parts))
            return
        kinds, cum = NOISE[fmt]
        kind = rng.choices(kinds, cum_weights=cum)[0]
        match fmt:
            case "app":
                self._noisy_app(kind, parts, out)
            case "json":
                self._noisy_json(kind, parts, out)
            case _:
                self._noisy_fw(kind, parts, out)

    @staticmethod
    def render(fmt: str, parts: Any) -> str:
        match fmt:
            case "app":
                return FIELD_SEP.join(parts)
            case "json":
                return json.dumps(parts, ensure_ascii=False,
                                  separators=(",", ":"))
            case _:
                return " ".join(parts)

    def _noisy_app(self, kind: str, f: list[str], out: list[str]) -> None:
        rng = self.rng
        # 1) défauts sur un champ précis
        match kind:
            case "level_case":
                f[1] = rng.choice(LEVEL_VARIANTS[f[1]])
            case "ansi":                    # couleurs de terminal
                f[1] = f"\x1b[{rng.choice((31, 33, 32))}m{f[1]}\x1b[0m"
            case "service_case":
                f[2] = rng.choice((f[2].upper(), f[2].replace("-", "_"),
                                   f"  {f[2].title()} "))
            case "user_noise":
                f[4] = self._noisy_user(f[4])
            case "ts_alt":                  # autre format de date (réparable)
                f[0] = self._alt_timestamp(f[0])
            case "ts_bad":                  # date impossible (à rejeter)
                f[0] = rng.choice(("2026-13-45T25:61:00Z", "N/A", "",
                                   "timestamp", "2026/10/01"))
            case "bad_ip":
                f[3] = rng.choice(BAD_ENDPOINTS)
            case "no_proto":
                f[3] = f[3].rsplit("/", 1)[0]
            case "broken_json" if f[6].startswith("{"):
                f[6] = f[6][:-rng.randint(2, 12)]
            case "quote_json" if f[6].startswith("{"):
                f[6] = f[6].replace('"', "'")
            case "status_str":
                f[6] = STATUS_RE.sub(r'"status":"\1"', f[6])
            case "latency_bad":
                f[6] = LATENCY_RE.sub(
                    rng.choice(('"latency_ms":-1', '"latency_ms":NaN',
                                '"latency_ms":"slow"')), f[6])
            case "mojibake" if not f[6].startswith("{"):
                # texte UTF-8 relu comme du latin-1 : "é" devient "Ã©"
                f[6] = f[6].encode("utf-8").decode("latin-1")
            case "missing_field":
                del f[rng.randint(1, 5)]
        line = FIELD_SEP.join(f)
        # 2) défauts sur la ligne entière
        match kind:
            case "spaces":
                line = f"  \t{line}   "
            case "crlf":
                line += "\r"
            case "double_sep":
                line = line.replace(" | ", rng.choice((" || ", "|")), 2)
            case "truncate":
                line = line[:rng.randint(10, max(11, len(line) - 5))]
            case "garbage":
                junk = rng.choice(("\x00", "\udcff\udcfe", "﻿", "\x07",
                                   "\x00\x00\x00"))
                line = junk + line if rng.random() < 0.5 else line + junk
            case "blank":
                out.append(rng.choice(("", "   ", "\t", " \t ")))
            case "duplicate":
                out.append(line)
            case "comment":
                out.append(rng.choice(COMMENT_LINES))
        out.append(line)
        # Les erreurs applicatives sont parfois suivies d'une stack trace
        if f[1] in ("ERROR", "CRITICAL") and rng.random() < 0.3:
            exc, msg = rng.choice(EXCEPTIONS)
            for template in STACKTRACE:
                out.append(template.format(
                    svc=f[2], n=rng.randint(10, 400), m=rng.randint(10, 400),
                    exc=exc, msg=msg))

    def _noisy_user(self, field: str) -> str:
        rng = self.rng
        value = field.removeprefix("user=")
        if value.startswith("u") and value[1:].isdigit():
            n = int(value[1:])
            return rng.choice((f"user=U{n}", f"user=U-{n}", f"user=USER_{n}",
                               f"user=user-{n:05d}", f"user= u{n} ",
                               "user=", "user=null"))
        return rng.choice((f"user={value.upper()}", "user=None",
                           "user=N/A", "user="))

    def _alt_timestamp(self, ts: str) -> str:
        moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        match self.rng.randint(1, 4):
            case 1:
                return moment.strftime("%d/%m/%Y %H:%M:%S")
            case 2:
                return f"{moment.timestamp():.3f}"
            case 3:
                return moment.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
            case _:
                return ts.removesuffix("Z")     # sans fuseau horaire

    def _noisy_json(self, kind: str, d: dict, out: list[str]) -> None:
        rng = self.rng
        match kind:
            case "level_case":
                d["lvl"] = rng.choice(LEVEL_VARIANTS[d["lvl"].upper()])
            case "ts_epoch":
                d["ts"] = datetime.fromisoformat(
                    d["ts"].replace("Z", "+00:00")).timestamp()
            case "user_noise":
                d["user"] = rng.choice((None, "", d["user"].upper(),
                                        f"user_{d['user'][1:]}"))
            case "missing_client":
                del d["client"]
            case "code_str":
                d["code"] = str(d["code"])
        line = self.render("json", d)
        match kind:
            case "spaces":
                line = f"   {line}\t"
            case "truncate":
                line = line[:rng.randint(10, len(line) - 3)]
            case "duplicate":
                out.append(line)
            case "blank":
                out.append("")
        out.append(line)

    def _noisy_fw(self, kind: str, t: list[str], out: list[str]) -> None:
        rng = self.rng
        match kind:
            case "action_case":
                t[2] = t[2].lower()
            case "bad_port":
                t[7] = rng.choice(("abc", "70000", "-1"))
            case "bad_ip":
                t[4] = rng.choice(("300.1.2.3", "10.0.0", "unknown"))
            case "truncate":
                t = t[:rng.randint(3, 7)]
        separator = "   " if kind == "spaces" else " "
        line = separator.join(t)
        if kind == "duplicate":
            out.append(line)
        out.append(line)


# ------------------------------------------------------------ scénarios
def build_scenarios(seed: int, total_minutes: int) -> list[dict]:
    """Planifie les incidents sur toute la période (identique pour tous les
    fichiers car calculé une seule fois avec la graine)."""
    rng = random.Random(seed + 7)
    days = max(1, total_minutes // MINUTES_PER_DAY)
    scenarios: list[dict] = []

    def add(kind: str, start: int, duration: int, **extra: Any) -> None:
        start = min(start, max(0, total_minutes - duration))
        scenarios.append({"kind": kind, "start": start,
                          "end": start + duration, **extra})

    for _ in range(max(1, days // 5)):           # une panne tous les ~5 jours
        add("outage", rng.randrange(total_minutes), rng.randint(30, 120),
            service=rng.choice(("payment-service", "db-cluster",
                                "auth-service")))
    for _ in range(max(1, days // 10)):          # un DDoS tous les ~10 jours
        add("ddos", rng.randrange(total_minutes), rng.randint(10, 30))
    for day in range(days):                      # un déploiement par jour
        add("deploy", day * MINUTES_PER_DAY + rng.randint(10, 17) * 60, 15,
            service=rng.choice(("api-gateway", "payment-service",
                                "user-service")),
            version=f"{rng.randint(2, 4)}.{rng.randint(0, 20)}."
                    f"{rng.randint(0, 9)}")
    for _ in range(max(1, days // 15)):          # un disque qui se remplit
        add("disk", rng.randrange(total_minutes), 360)
    return sorted(scenarios, key=lambda s: s["start"])


def minute_context(minute: int, scenarios: list[dict]) -> dict:
    """État du système pendant une minute donnée."""
    ctx: dict[str, Any] = {"outage": set(), "deploy": set(), "ddos": False,
                           "disk": None, "starting": []}
    for s in scenarios:
        if not s["start"] <= minute < s["end"]:
            continue
        if minute == s["start"]:
            ctx["starting"].append(s)
        match s["kind"]:
            case "outage":
                ctx["outage"].add(s["service"])
            case "deploy":
                ctx["deploy"].add(s["service"])
            case "ddos":
                ctx["ddos"] = True
            case "disk":
                progress = (minute - s["start"]) / (s["end"] - s["start"])
                ctx["disk"] = int(80 + 19 * progress)
    return ctx


def activity(minute: int, ctx: dict) -> float:
    """Poids du trafic pour une minute (heure de la journée, week-end...)."""
    moment = START_DATE + timedelta(minutes=minute)
    weight = HOURLY_ACTIVITY[moment.hour]
    if moment.weekday() >= 5:
        weight *= WEEKEND_FACTOR
    if ctx["ddos"]:
        weight *= 2.5
    return weight


def lines_for_minute(factory: LogFactory, noise: NoiseInjector, minute: int,
                     base_rate: float, scenarios: list[dict]) -> list[str]:
    """Produit toutes les lignes d'une minute, triées par horodatage."""
    rng = factory.rng
    ctx = minute_context(minute, scenarios)
    count = int(base_rate * activity(minute, ctx) * rng.uniform(0.85, 1.15))
    # (seconde, None) = évènement normal ; (seconde, (méthode, args)) = spécial
    events: list[tuple] = [(rng.random() * 59.99, None) for _ in range(count)]
    events += factory.special_events(minute, ctx)
    events.sort(key=itemgetter(0))
    prefix = (START_DATE + timedelta(minutes=minute)).strftime(
        "%Y-%m-%dT%H:%M:")
    out: list[str] = []
    for second, special in events:
        ts = f"{prefix}{min(second, 59.998):06.3f}Z"
        if special is None:
            fmt, parts = factory.normal(ts, ctx)
        else:
            method, args = special
            fmt, parts = method(ts, *args)
        noise.emit(fmt, parts, out)
    return out


# ------------------------------------------------------------- écriture
def generate_file(job: dict) -> tuple[str, int, int, float]:
    """Écrit un fichier de logs complet (exécuté dans un processus fils)."""
    started = time.perf_counter()
    pools = Pools(job["seed"])
    rng = random.Random(job["seed"] * 1000 + job["index"])
    factory = LogFactory(pools, rng)
    noise = NoiseInjector(rng, job["dirty_rate"])
    written = lines = 0
    # Mode binaire + "surrogateescape" : permet d'écrire de vrais octets
    # invalides en UTF-8 (pour tester errors="replace" à la lecture).
    with open(job["path"], "wb", buffering=1 << 20) as file:
        for minute in range(job["start"], job["end"]):
            out = lines_for_minute(factory, noise, minute, job["base_rate"],
                                   job["scenarios"])
            data = ("\n".join(out) + "\n").encode("utf-8", "surrogateescape")
            file.write(data)
            written += len(data)
            lines += len(out)
    return job["path"], written, lines, time.perf_counter() - started


def estimate_line_size(seed: int, dirty_rate: float,
                       scenarios: list[dict]) -> float:
    """Mesure la taille moyenne d'une ligne sur un échantillon."""
    rng = random.Random(seed)
    factory = LogFactory(Pools(seed), rng)
    noise = NoiseInjector(rng, dirty_rate)
    total = count = 0
    for minute in range(0, 20 * 60, 60):
        out = lines_for_minute(factory, noise, minute, 300, scenarios)
        total += sum(len(line.encode("utf-8", "surrogateescape")) + 1
                     for line in out)
        count += len(out)
    return total / count


def write_blacklist(path: Path, pools: Pools, rng: random.Random) -> None:
    """Écrit une liste noire volontairement un peu sale (à nettoyer)."""
    lines = ["# Liste noire d'IP - flux threat-intel",
             "# Format : une IP par ligne, commentaires avec #", ""]
    for ip in pools.blacklist:
        r = rng.random()
        if r < 0.05:
            lines.append(f"   {ip}   ")
        elif r < 0.10:
            lines.append(f"{ip}    # signalée par le CERT")
        elif r < 0.13:
            lines.extend((ip, ip))              # doublon
        else:
            lines.append(ip)
        if rng.random() < 0.03:
            lines.append(rng.choice(("", "999.1.2.3", "not-an-ip", "  ")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_dataset(out_dir: Path, size_gb: float, files: int, days: int,
                     workers: int, dirty_rate: float, seed: int,
                     force: bool = False) -> None:
    """Génère tout le jeu de données (point d'entrée appelé par main.py)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target_bytes = int(size_gb * 1024 ** 3)
    existing = sorted(out_dir.glob("*.log"))
    if existing and not force:
        raise SystemExit(f"{out_dir} contient déjà {len(existing)} fichier(s) "
                         ".log : utilisez --force pour les remplacer.")
    free = shutil.disk_usage(out_dir).free
    if free < target_bytes * 1.05:
        raise SystemExit(f"Espace disque insuffisant : {free / 1024 ** 3:.1f} "
                         f"Go libres pour {size_gb} Go demandés.")
    for old in existing:
        old.unlink()

    total_minutes = days * MINUTES_PER_DAY
    scenarios = build_scenarios(seed, total_minutes)
    avg_size = estimate_line_size(seed, dirty_rate, scenarios)
    weight_sum = sum(activity(m, minute_context(m, scenarios))
                     for m in range(total_minutes))
    base_rate = target_bytes / avg_size / weight_sum
    print(f"[générateur] {size_gb} Go, {files} fichiers, {days} jours, "
          f"~{target_bytes / avg_size / 1e6:.0f} M lignes "
          f"(~{avg_size:.0f} octets/ligne), {workers} processus")

    pools = Pools(seed)
    write_blacklist(out_dir / BLACKLIST_NAME, pools, random.Random(seed))
    jobs = []
    for index in range(files):
        start = index * total_minutes // files
        end = (index + 1) * total_minutes // files
        moment = START_DATE + timedelta(minutes=start)
        jobs.append({
            "index": index, "seed": seed, "start": start, "end": end,
            "path": str(out_dir / f"logs-{index:02d}-"
                                  f"{moment:%Y%m%d-%H%M}.log"),
            "base_rate": base_rate, "dirty_rate": dirty_rate,
            "scenarios": [s for s in scenarios
                          if s["start"] < end and s["end"] > start],
        })

    started = time.perf_counter()
    total_bytes = total_lines = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for path, size, lines, seconds in executor.map(generate_file, jobs):
            total_bytes += size
            total_lines += lines
            print(f"  {Path(path).name} : {size / 1024 ** 2:,.0f} Mo, "
                  f"{lines:,} lignes en {seconds:.0f} s")
    elapsed = time.perf_counter() - started
    print(f"[générateur] terminé : {total_bytes / 1024 ** 3:.2f} Go, "
          f"{total_lines:,} lignes en {elapsed:.0f} s")
