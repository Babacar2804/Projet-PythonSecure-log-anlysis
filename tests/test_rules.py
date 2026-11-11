"""Module 4 : moteur de règles (*args, **kwargs)."""

from typing import Any

import pytest

from logengine.models import Alert, LogRecord
from logengine.rules import (DEFAULT_RULES, apply_security_rules,
                             rule_blacklisted_ip, rule_exposed_port,
                             rule_slow_request, rule_sql_injection)
from tests.helpers import app_line, record


def http(path: str, ua: str = "Mozilla/5.0", latency: int = 40,
         ip: str = "88.12.34.56") -> LogRecord:
    return record(app_line(
        endpoint=f"{ip}:5000/TCP",
        payload=f'{{"method":"GET","path":"{path}","status":200,'
                f'"latency_ms":{latency},"bytes":1,"ua":"{ua}"}}'))


def rules_fired(rec: LogRecord, **config: Any) -> set[str]:
    check = apply_security_rules(*DEFAULT_RULES, **config)
    return {a["rule"] for a in check(rec)}


@pytest.mark.parametrize("path, rule", [
    ("/search?q=' OR '1'='1", "sql_injection"),
    ("/p?id=1 UNION SELECT password FROM users", "sql_injection"),
    ("/search?q=<script>alert(1)</script>", "xss"),
    ("/static/../../etc/passwd", "path_traversal"),
    ("/.env", "scanner_probe"),
])
def test_attaques_web_detectees(path: str, rule: str) -> None:
    assert rule in rules_fired(http(path))


def test_requete_normale_sans_alerte() -> None:
    assert rules_fired(http("/api/v1/products")) == set()


def test_outil_offensif() -> None:
    assert "outil_offensif" in rules_fired(http("/", ua="sqlmap/1.8"))


def test_kwargs_transmis_aux_regles() -> None:
    slow = http("/", latency=3000)
    assert rule_slow_request(slow) is None                  # défaut 5000
    assert rule_slow_request(slow, max_latency_ms=1000) is not None
    bad = http("/", ip="185.1.2.3")
    assert rule_blacklisted_ip(bad) is None
    assert rule_blacklisted_ip(bad, blacklist=frozenset({"185.1.2.3"}))


def test_nombre_variable_de_regles() -> None:
    attack = http("/search?q=' OR '1'='1")
    assert apply_security_rules()(attack) == []             # aucune règle
    check = apply_security_rules(rule_sql_injection)
    assert [a["rule"] for a in check(attack)] == ["sql_injection"]


def test_renvoie_une_fonction_reutilisable() -> None:
    check = apply_security_rules(rule_slow_request, max_latency_ms=1000)
    assert callable(check)
    assert check(http("/", latency=3000)) != []             # kwargs retenus
    assert check(http("/", latency=10)) == []


def test_regle_desactivee_par_son_nom() -> None:
    attack = http("/search?q=' OR '1'='1")
    check = apply_security_rules(rule_sql_injection,
                                 disabled={"rule_sql_injection"})
    assert check(attack) == []


def test_argument_qui_n_est_pas_une_fonction() -> None:
    with pytest.raises(TypeError):
        # erreur volontaire : mypy la voit aussi, on lui dit que c'est voulu
        apply_security_rules(rule_sql_injection,
                             "pas une règle")  # type: ignore[arg-type]


def test_une_regle_qui_plante_n_arrete_pas_le_moteur() -> None:
    def rule_buggee(rec: LogRecord, **config: Any) -> Alert | None:
        raise ValueError("bug")

    attack = http("/search?q=' OR '1'='1")
    check = apply_security_rules(rule_buggee, rule_sql_injection)
    assert [a["rule"] for a in check(attack)] == ["sql_injection"]


def test_port_sensible_expose_motif_tuple() -> None:
    line = ("FW 2026-10-01T00:20:12.423Z ACCEPT TCP 102.109.77.236 27409 "
            "10.0.100.29 22 TEMP-ALLOW-DEBUG")
    assert rule_exposed_port(record(line)) is not None
    internal = line.replace("102.109.77.236", "10.0.0.5")
    assert rule_exposed_port(record(internal)) is None      # IP privée
