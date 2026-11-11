"""Modules 1 et 2 : découpage des lignes et routage par match-case."""

import pytest

from logengine.parsing import decode_line, parse_line, split_endpoint
from tests.helpers import app_line

JSON_LINE = ('{"ts":"2026-10-01T08:15:32.481Z","lvl":"error","svc":'
             '"payment-service","client":{"ip":"95.5.28.176","port":443,'
             '"proto":"TCP"},"user":"u9","event":"payment_failed",'
             '"code":502,"msg":"bank gateway error"}')
FW_LINE = ("FW 2026-10-01T00:20:12.423Z DROP TCP 102.109.77.236 27409 "
           "10.0.100.29 22 DENY-SSH-EXT")


@pytest.mark.parametrize("text, expected", [
    ("10.0.3.17:51432/TCP", ("10.0.3.17", "51432", "TCP")),
    ("[2a01:e0a::1]:443/TCP", ("2a01:e0a::1", "443", "TCP")),
    ("10.0.3.17:51432", ("10.0.3.17", "51432", "")),
])
def test_split_endpoint(text: str, expected: tuple[str, str, str]) -> None:
    assert split_endpoint(text) == expected


def test_decode_line_choisit_le_bon_type() -> None:
    assert isinstance(decode_line(JSON_LINE), dict)
    assert isinstance(decode_line(FW_LINE), tuple)
    assert isinstance(decode_line(app_line()), str)


def test_ligne_app() -> None:
    rec = parse_line(app_line())
    assert rec["source"] == "app"
    assert rec["errors"] == []
    assert (rec["ip"], rec["port"], rec["protocol"]) == \
        ("88.12.34.56", "51432", "TCP")
    assert rec["user"] == "u1042"
    assert rec["event"] == "http_request"


def test_ligne_json_routee_par_motif_dict() -> None:
    rec = parse_line(JSON_LINE)
    assert rec["source"] == "json"
    assert rec["service"] == "payment-service"
    assert rec["ip"] == "95.5.28.176"
    payload = rec["payload"]
    assert isinstance(payload, dict)
    assert payload["code"] == 502              # le reste va dans **rest


def test_ligne_pare_feu_routee_par_motif_tuple() -> None:
    rec = parse_line(FW_LINE)
    assert rec["source"] == "firewall"
    assert rec["level"] == "WARNING"            # DROP -> WARNING
    payload = rec["payload"]
    assert isinstance(payload, dict)
    assert payload["dst_port"] == 22
    assert rec["event"] == "fw_drop"


@pytest.mark.parametrize("line, reason", [
    ("FW 2026-10-01T00:20:12.423Z DROP TCP", "pare_feu_incomplet"),
    ('{"ts":"2026-10-01T08:15:32Z","lvl":"info"', "json_invalide"),
    ('{"ts":"2026-10-01T08:15:32Z","lvl":"info","svc":"user-service"}',
     "json_structure_inconnue"),
    ("2026-10-01T08:15:32Z | INFO | api-gateway | user=u1",
     "champs_manquants"),
])
def test_lignes_rejetees(line: str, reason: str) -> None:
    assert parse_line(line)["errors"] == [reason]
