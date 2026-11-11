"""Constantes partagées par tous les modules du projet."""

from pathlib import Path

# --- Dossiers du projet (calculés à partir de l'emplacement de ce fichier)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # gros jeu de données (10-15 Go)
DEMO_DIR = DATA_DIR / "demo"        # petit jeu de test pour la démo
OUTPUT_DIR = PROJECT_ROOT / "output"
BLACKLIST_NAME = "blacklist.txt"    # écrit par le générateur à côté des logs

# --- Niveaux de sévérité, du moins grave au plus grave
LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LEVEL_RANK: dict[str, int] = {level: rank for rank, level in enumerate(LEVELS)}

# --- Services connus du système d'information simulé
KNOWN_SERVICES: frozenset[str] = frozenset({
    "api-gateway", "cdn-edge", "auth-service", "payment-service",
    "user-service", "inventory-service", "db-cluster", "cache-redis",
    "mail-service", "vpn-gateway", "scheduler", "firewall",
})

PROTOCOLS: frozenset[str] = frozenset({"TCP", "UDP", "ICMP"})

# --- Évènements d'authentification utilisés par la détection force brute
AUTH_FAILURE_EVENTS: frozenset[str] = frozenset({"login_failed"})
AUTH_SUCCESS_EVENTS: frozenset[str] = frozenset({"login_success"})

# --- Format "app" : 7 champs séparés par " | "
FIELD_SEP = " | "
APP_FIELD_COUNT = 7
