"""Module 4 (audit) et test de bout en bout du pipeline."""

import json
from pathlib import Path

from logengine.audit import describe_scope, export_audit_report
from logengine.generator import generate_dataset
from main import run_analysis

CONSTANTE = 42


def test_describe_scope_classe_les_variables() -> None:
    rows = {row["nom"]: row for row in describe_scope(globals())}
    assert "__name__" not in rows                   # dunders ignorés
    assert rows["json"]["categorie"] == "module"
    assert rows["CONSTANTE"]["categorie"] == "donnée"
    assert rows["describe_scope"]["categorie"] == "fonction/classe"


def test_export_audit_report_globals_locals(tmp_path: Path) -> None:
    variable_locale = [1, 2, 3]  # noqa: F841 - lue via locals()
    report = export_audit_report(tmp_path / "audit.json", globals(),
                                 locals())
    saved = json.loads((tmp_path / "audit.json").read_text("utf-8"))
    names = {row["nom"] for row in saved["locales"]}
    assert "variable_locale" in names
    assert report["nb_locales"] == len(saved["locales"])


def test_pipeline_complet(tmp_path: Path) -> None:
    data, out = tmp_path / "data", tmp_path / "out"
    generate_dataset(data, size_gb=0.003, files=1, days=1, workers=1,
                     dirty_rate=0.05, seed=1)
    report = run_analysis(data, out, charts=False)
    clean = report["nettoyage"]
    assert clean["lignes_lues"] > 10_000
    assert clean["enregistrements_valides"] + clean["lignes_supprimees"] \
        + clean["enregistrements_rejetes"] == clean["lignes_lues"]
    assert 0 < clean["taux_de_rejet_pct"] < 5          # nettoyage efficace
    assert report["ensembles_ip"]["blacklist_actives"] > 0
    for name in ("report.json", "alerts.csv", "audit.json",
                 "rejected_samples.txt"):
        assert (out / name).exists()
