"""Point d'entrée : pilote tout le pipeline en ligne de commande (CLI).

Exemples :
    python main.py demo                       # petit jeu de test + analyse
    python main.py generate --size-gb 12      # le gros jeu de données
    python main.py analyze                    # analyse de data/raw
    python main.py analyze --limit 2000000 --level WARNING
"""

import argparse
import csv
import os
import sys
import time
import tracemalloc
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Any

from logengine.aggregation import (LogStatistics, compare_with_blacklist,
                                   load_blacklist)
from logengine.audit import export_audit_report
from logengine.config import (BLACKLIST_NAME, DEMO_DIR, LEVEL_RANK, LEVELS,
                              OUTPUT_DIR, RAW_DIR)
from logengine.detection import BruteForceDetector
from logengine.generator import generate_dataset
from logengine.ingestion import list_log_files, read_sources, with_progress
from logengine.models import LogRecord
from logengine.parsing import parse_line
from logengine.report import make_charts, write_csv, write_json, write_samples
from logengine.rules import DEFAULT_RULES, apply_security_rules
from logengine.transform import (CleaningTracker, clean_raw_line,
                                 drop_consecutive_duplicates,
                                 normalize_record)

ALERT_FIELDS = ["timestamp", "rule", "severity", "ip", "user", "service",
                "detail"]
SAMPLE_FIELDS = ["timestamp", "level", "service", "source", "ip", "port",
                 "protocol", "user", "event", "status", "latency_ms"]


def to_sample_row(record: LogRecord) -> dict[str, Any]:
    """Version "à plat" d'un enregistrement pour l'échantillon CSV."""
    payload = record["payload"]
    details = payload if isinstance(payload, dict) else {}
    return {
        "timestamp": record["timestamp"].isoformat(),
        "level": record["level"], "service": record["service"],
        "source": record["source"], "ip": record["ip"],
        "port": record["port"], "protocol": record["protocol"],
        "user": record["user"] or "", "event": record["event"],
        "status": details.get("status") or details.get("code") or "",
        "latency_ms": details.get("latency_ms") or "",
    }


def run_analysis(input_dir: Path, output_dir: Path, limit: int | None = None,
                 min_level: str = "DEBUG", services: list[str] | None = None,
                 disabled_rules: list[str] | None = None,
                 sample_every: int = 2000, charts: bool = True,
                 trace_memory: bool = False) -> dict[str, Any]:
    """Exécute tout le pipeline sur les fichiers de ``input_dir``."""
    files = list_log_files(input_dir)
    if not files:
        raise SystemExit(f"Aucun fichier .log dans {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    size_gb = sum(f.stat().st_size for f in files) / 1024 ** 3
    print(f"[analyse] {len(files)} fichier(s), {size_gb:.2f} Go")
    if trace_memory:
        tracemalloc.start()
    started = time.perf_counter()

    blacklist = load_blacklist(input_dir / BLACKLIST_NAME)
    tracker = CleaningTracker()
    stats = LogStatistics()
    detector = BruteForceDetector(threshold=5, window_seconds=120)
    rule_config = {
        "blacklist": blacklist,
        "max_latency_ms": 5000,
        "disabled": frozenset(disabled_rules or ()),
    }

    # ---- 1) Construction du pipeline : RIEN n'est lu à cette étape ! -----
    # Chaque ligne ci-dessous enveloppe l'itérateur précédent. Les données
    # ne commenceront à circuler qu'au moment de la boucle for plus bas,
    # une ligne à la fois, de bout en bout.
    lines = read_sources(files)                       # yield / yield from
    if limit:
        lines = islice(lines, limit)                  # N premières lignes
    lines = with_progress(lines)
    lines = map(clean_raw_line, lines)                # map : nettoyage texte
    lines = filter(tracker.keep_line, lines)          # filter : vides, #...
    lines = drop_consecutive_duplicates(lines, tracker)
    records = map(parse_line, lines)                  # str -> dict
    records = map(normalize_record, records)          # types + casse
    records = filter(tracker.accept, records)         # rejet des invalides
    min_rank = LEVEL_RANK[min_level]
    records = filter(lambda r: LEVEL_RANK[r["level"]] >= min_rank, records)
    if services:
        wanted = frozenset(services)
        records = filter(lambda r: r["service"] in wanted, records)

    # ---- 2) Exécution : une seule passe sur les données ------------------
    alerts_by_rule: defaultdict[str, int] = defaultdict(int)
    with open(output_dir / "alerts.csv", "w", newline="",
              encoding="utf-8") as alerts_file, \
         open(output_dir / "sample_clean.csv", "w", newline="",
              encoding="utf-8") as sample_file:
        alert_writer = csv.DictWriter(alerts_file, fieldnames=ALERT_FIELDS)
        sample_writer = csv.DictWriter(sample_file, fieldnames=SAMPLE_FIELDS)
        alert_writer.writeheader()
        sample_writer.writeheader()
        for index, record in enumerate(records):
            stats.update(record)
            detector.feed(record)
            for alert in apply_security_rules(record, *DEFAULT_RULES,
                                              **rule_config):
                alert_writer.writerow(alert)
                alerts_by_rule[alert["rule"]] += 1
            if index % sample_every == 0:
                sample_writer.writerow(to_sample_row(record))

    # ---- 3) Résultats -----------------------------------------------------
    elapsed = time.perf_counter() - started
    incidents = detector.summarize()
    ip_sets = compare_with_blacklist(stats.active_ips, stats.error_ips,
                                     blacklist)
    cleaning = tracker.summary()
    summary = stats.summary()
    peak_mb = None
    if trace_memory:
        peak_mb = round(tracemalloc.get_traced_memory()[1] / 1024 ** 2, 1)
        tracemalloc.stop()

    report = {
        "execution": {
            "fichiers": [f.name for f in files],
            "taille_go": round(size_gb, 2),
            "duree_s": round(elapsed, 1),
            "lignes_par_seconde": round(cleaning["lignes_lues"]
                                        / max(elapsed, 1e-9)),
            "pic_memoire_python_mo": peak_mb,
            "filtres": {"niveau_min": min_level, "services": services,
                        "limite": limit},
        },
        "nettoyage": {k: v for k, v in cleaning.items() if k != "exemples"},
        "statistiques": summary,
        "ensembles_ip": {
            "taille_blacklist": len(blacklist),
            **{name: len(values) for name, values in ip_sets.items()},
            "exemples_blacklist_actives": sorted(
                ip_sets["blacklist_actives"])[:20],
        },
        "force_brute": {
            "nb_incidents": len(incidents),
            "nb_comptes_compromis": sum(
                1 for i in incidents if i["statut"] == "COMPROMIS"),
            "top_incidents": incidents[:15],
        },
        "alertes_par_regle": dict(sorted(alerts_by_rule.items(),
                                         key=lambda kv: kv[1], reverse=True)),
    }
    write_json(output_dir / "report.json", report)
    write_samples(output_dir / "rejected_samples.txt", cleaning["exemples"])
    if incidents:
        write_csv(output_dir / "incidents.csv", incidents,
                  list(incidents[0].keys()))
    if charts:
        make_charts(summary, cleaning, alerts_by_rule, output_dir / "charts")

    # Audit : on passe les portées globale (module main) et locale (cette
    # fonction) au module d'audit, qui les décrit dans un fichier JSON.
    export_audit_report(output_dir / "audit.json", globals(), locals(),
                        pid=os.getpid())
    print_summary(report, output_dir)
    return report


def print_summary(report: dict[str, Any], output_dir: Path) -> None:
    run, clean = report["execution"], report["nettoyage"]
    stats, ips = report["statistiques"], report["ensembles_ip"]
    brute = report["force_brute"]
    print(f"\n=== Résumé ({run['duree_s']} s, "
          f"{run['lignes_par_seconde']:,} lignes/s) ===")
    print(f"Lignes lues          : {clean['lignes_lues']:,}")
    print(f"Supprimées / rejetées: {clean['lignes_supprimees']:,} / "
          f"{clean['enregistrements_rejetes']:,} "
          f"({clean['taux_de_rejet_pct']} %)")
    print(f"Enregistrements OK   : {clean['enregistrements_valides']:,}")
    print("Par niveau           : " + ", ".join(
        f"{lvl}={stats['par_niveau'].get(lvl, 0):,}" for lvl in LEVELS))
    print(f"IP uniques / erreur  : {stats['nb_ip_uniques']:,} / "
          f"{stats['nb_ip_en_erreur']:,}")
    print(f"Blacklist actives    : {ips['blacklist_actives']} "
          f"sur {ips['taille_blacklist']}")
    print(f"Force brute          : {brute['nb_incidents']} IP suspectes, "
          f"{brute['nb_comptes_compromis']} ayant compromis un compte")
    print("Alertes              : " + ", ".join(
        f"{k}={v:,}" for k, v in report["alertes_par_regle"].items()))
    if run["pic_memoire_python_mo"] is not None:
        print(f"Pic mémoire Python   : {run['pic_memoire_python_mo']} Mo")
    print(f"Résultats dans       : {output_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Moteur d'ingestion et d'analyse de logs")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="génère le jeu de données")
    gen.add_argument("--out", type=Path, default=RAW_DIR)
    gen.add_argument("--size-gb", type=float, default=12.0)
    gen.add_argument("--files", type=int, default=12)
    gen.add_argument("--days", type=int, default=30)
    gen.add_argument("--workers", type=int,
                     default=max(1, (os.cpu_count() or 2) - 1))
    gen.add_argument("--dirty-rate", type=float, default=0.05,
                     help="part des lignes abîmées volontairement (0-1)")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--force", action="store_true",
                     help="remplace les fichiers .log existants")

    ana = sub.add_parser("analyze", help="analyse un dossier de logs")
    ana.add_argument("--input", type=Path, default=RAW_DIR)
    ana.add_argument("--output", type=Path, default=OUTPUT_DIR)
    ana.add_argument("--limit", type=int, default=None,
                     help="ne lire que les N premières lignes")
    ana.add_argument("--level", choices=LEVELS, default="DEBUG",
                     help="niveau minimum conservé")
    ana.add_argument("--service", action="append",
                     help="ne garder que ce service (répétable)")
    ana.add_argument("--disable-rule", action="append",
                     help="désactive une règle (ex : rule_slow_request)")
    ana.add_argument("--sample-every", type=int, default=2000)
    ana.add_argument("--no-charts", action="store_true")
    ana.add_argument("--trace-memory", action="store_true",
                     help="mesure le pic mémoire (ralentit l'analyse)")

    sub.add_parser("demo", help="petit jeu de test (~50 Mo) + analyse")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    match args.command:
        case "generate":
            generate_dataset(args.out, args.size_gb, args.files, args.days,
                             args.workers, args.dirty_rate, args.seed,
                             args.force)
        case "analyze":
            run_analysis(args.input, args.output, args.limit, args.level,
                         args.service, args.disable_rule, args.sample_every,
                         not args.no_charts, args.trace_memory)
        case "demo":
            if not list_log_files(DEMO_DIR):
                generate_dataset(DEMO_DIR, size_gb=0.05, files=3, days=3,
                                 workers=3, dirty_rate=0.05, seed=42)
            run_analysis(DEMO_DIR, OUTPUT_DIR / "demo", sample_every=50,
                         trace_memory=True)
    return 0


if __name__ == "__main__":       # obligatoire sous Windows (multiprocessing)
    sys.exit(main())
