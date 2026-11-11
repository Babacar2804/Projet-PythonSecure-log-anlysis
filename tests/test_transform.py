"""Module 2 : nettoyage et normalisation."""

from datetime import datetime, timezone

import pytest

from logengine.transform import (CleaningTracker, clean_raw_line,
                                 drop_consecutive_duplicates, normalize_level,
                                 normalize_user, parse_payload,
                                 parse_timestamp, validate_ip)
from tests.helpers import app_line, record

EXPECTED_TS = datetime(2026, 10, 1, 8, 15, 32, tzinfo=timezone.utc)


def test_clean_raw_line() -> None:
    dirty = "﻿  \x1b[31mERROR\x1b[0m a\x00b || c\t \r\n"
    assert clean_raw_line(dirty) == "ERROR ab | c"


@pytest.mark.parametrize("value, expected", [
    ("err", "ERROR"), (" INFO ", "INFO"), ("Warning", "WARNING"),
    ("FATAL", "CRITICAL"), ("dbg", "DEBUG"), ("banane", None), (None, None),
])
def test_normalize_level(value: str | None, expected: str | None) -> None:
    assert normalize_level(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("u1042", ("u1042", False)), ("U-1042", ("u1042", True)),
    ("USER_1042", ("u1042", True)), ("user-01042", ("u1042", True)),
    ("null", (None, True)), ("-", (None, False)), ("ADMIN", ("admin", True)),
])
def test_normalize_user(value: str,
                        expected: tuple[str | None, bool]) -> None:
    assert normalize_user(value) == expected


@pytest.mark.parametrize("value", [
    "2026-10-01T08:15:32Z", "01/10/2026 08:15:32", "1790842532",
    "2026-10-01 08:15:32,000", 1790842532.0,
])
def test_parse_timestamp_formats_acceptes(value: str | float) -> None:
    moment, _ = parse_timestamp(value)
    assert moment == EXPECTED_TS


@pytest.mark.parametrize("value", ["2026-13-45T25:61:00Z", "N/A", "", None])
def test_parse_timestamp_rejette(value: str | None) -> None:
    assert parse_timestamp(value) == (None, False)


def test_validate_ip() -> None:
    assert validate_ip("10.0.0.1") == "10.0.0.1"
    assert validate_ip("[2a01:e0a::1]") == "2a01:e0a::1"
    for bad in ("999.1.2.3", "10.0.0", "localhost", "-"):
        assert validate_ip(bad) is None


def test_parse_payload_repare_les_guillemets_simples() -> None:
    fixes: list[str] = []
    assert parse_payload("{'status': 200}", fixes) == {"status": 200}
    assert fixes == ["payload_repare"]


def test_parse_payload_repare_l_encodage() -> None:
    fixes: list[str] = []
    broken = "requête lente".encode("utf-8").decode("latin-1")
    assert parse_payload(broken, fixes) == "requête lente"
    assert fixes == ["encodage_repare"]


def test_ligne_sale_mais_reparable() -> None:
    rec = record(app_line(ts="01/10/2026 08:15:32", level="err",
                          service="API_GATEWAY", user="USER_7",
                          payload='{"status":"500","latency_ms":-1}'))
    assert rec["errors"] == []
    assert rec["level"] == "ERROR"
    assert rec["service"] == "api-gateway"
    assert rec["user"] == "u7"
    assert rec["payload"] == {"status": 500, "latency_ms": None}
    assert rec["connection"] == ("88.12.34.56", 51432, "TCP")
    assert {"horodatage_reformate", "niveau_normalise", "service_normalise",
            "utilisateur_normalise", "status_converti",
            "latence_invalide"} <= set(rec["fixes"])


def test_ligne_avec_ip_impossible_rejetee() -> None:
    rec = record(app_line(endpoint="999.12.4.1:443/TCP"))
    assert rec["errors"] == ["ip_invalide"]
    assert "connection" not in rec


def test_doublons_consecutifs_supprimes() -> None:
    tracker = CleaningTracker()
    lines = ["a", "a", "b", "a", "a"]
    assert list(drop_consecutive_duplicates(lines, tracker)) == \
        ["a", "b", "a"]
    assert tracker.removed["doublon"] == 2


def test_tracker_keep_line_compte_les_causes() -> None:
    tracker = CleaningTracker()
    lines = ["", "# commentaire", "Traceback (most recent call last):",
             "File \"/app/x.py\", line 3, in f", app_line()]
    kept = list(filter(tracker.keep_line, lines))
    assert kept == [app_line()]
    assert dict(tracker.removed) == {"ligne_vide": 1, "commentaire": 1,
                                     "stacktrace": 2}
    assert tracker.lines_read == 5
