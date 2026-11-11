"""Module 3 : compteurs, ensembles et liste noire."""

from pathlib import Path

from logengine.aggregation import (LogStatistics, compare_with_blacklist,
                                   load_blacklist)
from tests.helpers import app_line, record


def firewall_drop(ip: str, port: int) -> str:
    return (f"FW 2026-10-01T00:20:12.423Z DROP TCP {ip} 40000 "
            f"10.0.100.29 {port} DEFAULT-DROP")


def test_compteurs_defaultdict_et_set_des_erreurs() -> None:
    stats = LogStatistics()
    stats.update(record(app_line()))
    stats.update(record(app_line(level="ERROR", endpoint="1.1.1.1:5/TCP")))
    stats.update(record(app_line(level="ERROR", endpoint="1.1.1.1:6/TCP")))
    assert stats.total == 3
    assert stats.by_level == {"INFO": 1, "ERROR": 2}
    assert stats.error_ips == {"1.1.1.1"}        # unique malgré 2 erreurs
    assert stats.by_level["CRITICAL"] == 0       # pas de KeyError
    assert stats.by_protocol["TCP"] == 3


def test_tuple_comme_cle_et_scan_de_ports() -> None:
    stats = LogStatistics()
    for port in range(20, 40):                   # 20 ports différents
        stats.update(record(firewall_drop("185.9.9.9", port)))
    stats.update(record(firewall_drop("185.9.9.9", 20)))  # même flux
    assert stats.blocked_flows[("185.9.9.9", 20, "TCP")] == 2
    assert stats.port_scanners(min_ports=15) == {"185.9.9.9": 20}
    assert stats.port_scanners(min_ports=50) == {}


def test_load_blacklist_nettoie_le_fichier(tmp_path: Path) -> None:
    path = tmp_path / "blacklist.txt"
    path.write_text("# titre\n\n  1.2.3.4  \n5.6.7.8   # CERT\n1.2.3.4\n"
                    "999.1.2.3\nnot-an-ip\n", encoding="utf-8")
    blacklist = load_blacklist(path)
    assert blacklist == frozenset({"1.2.3.4", "5.6.7.8"})
    assert isinstance(blacklist, frozenset)


def test_operations_ensemblistes() -> None:
    active = {"a", "b", "c"}
    errors = {"b"}
    blacklist = frozenset({"b", "z"})
    sets = compare_with_blacklist(active, errors, blacklist)
    assert sets["union_actives_blacklist"] == {"a", "b", "c", "z"}
    assert sets["blacklist_actives"] == {"b"}
    assert sets["blacklist_en_erreur"] == {"b"}
    assert sets["actives_non_listees"] == {"a", "c"}
    assert sets["blacklist_dormantes"] == {"z"}
    assert sets["difference_symetrique"] == {"a", "c", "z"}
