"""Fonctions utilitaires partagées par les tests."""

from logengine.models import LogRecord
from logengine.parsing import parse_line
from logengine.transform import normalize_record


def app_line(ts: str = "2026-10-01T08:15:32.481Z", level: str = "INFO",
             service: str = "api-gateway",
             endpoint: str = "88.12.34.56:51432/TCP", user: str = "u1042",
             event: str = "http_request",
             payload: str = '{"method":"GET","path":"/","status":200,'
                            '"latency_ms":43,"bytes":100,"ua":"Mozilla/5.0"}'
             ) -> str:
    """Construit une ligne au format "app"."""
    return " | ".join((ts, level, service, endpoint, f"user={user}",
                       f"event={event}", payload))


def record(line: str) -> LogRecord:
    """Ligne brute -> enregistrement parsé et normalisé."""
    return normalize_record(parse_line(line))


def login(second: int, ip: str = "185.1.2.3", user: str = "admin",
          success: bool = False, minute: int = 0) -> LogRecord:
    """Enregistrement d'une tentative de connexion à l'instant donné."""
    event = "login_success" if success else "login_failed"
    level = "INFO" if success else "WARNING"
    return record(app_line(ts=f"2026-10-01T08:{minute:02d}:{second:02d}.000Z",
                           level=level, service="auth-service",
                           endpoint=f"{ip}:40000/TCP", user=user,
                           event=event, payload='{"reason":"bad_password"}'))
