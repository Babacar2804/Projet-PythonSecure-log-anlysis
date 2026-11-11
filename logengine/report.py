"""Exports : rapport JSON, fichiers CSV et graphiques (matplotlib)."""

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Palette : une seule couleur pour les séries simples, couleurs de statut
# réservées aux niveaux de sévérité (gris = normal).
BLUE = "#2a78d6"
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LEVEL_COLORS = {"DEBUG": "#b5b4ad", "INFO": "#8a8984", "WARNING": "#fab219",
                "ERROR": "#ec835a", "CRITICAL": "#d03b3b"}


def write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False, default=str)


def write_csv(path: Path, rows: Iterable[dict[str, Any]],
              fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_samples(path: Path, samples: dict[str, list[str]]) -> None:
    """Exemples de lignes supprimées / rejetées, classés par raison."""
    with open(path, "w", encoding="utf-8") as file:
        for reason, lines in sorted(samples.items()):
            file.write(f"===== {reason} =====\n")
            for line in lines:
                file.write(f"{line!r}\n")       # repr : montre \t, \x00...
            file.write("\n")


def _style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _barh(plt, data: dict[str, int], title: str, path: Path,
          colors: list[str] | None = None) -> Path:
    """Barres horizontales triées, avec la valeur au bout de chaque barre."""
    items = sorted(data.items(), key=lambda kv: kv[1])
    labels = [str(k) for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(9, max(2.5, 0.38 * len(items) + 1)))
    ax.barh(labels, values, color=colors or BLUE, height=0.6,
            edgecolor=SURFACE, linewidth=2)
    _style(ax, title)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    for y, value in enumerate(values):
        ax.text(value, y, f" {value:,}".replace(",", " "), va="center",
                fontsize=8, color=MUTED)
    ax.margins(x=0.12)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return path


def make_charts(stats: dict[str, Any], cleaning: dict[str, Any],
                alerts_by_rule: dict[str, int], out_dir: Path) -> list[Path]:
    """Génère les graphiques PNG du rapport et renvoie leurs chemins."""
    try:
        import matplotlib
        matplotlib.use("Agg")               # pas de fenêtre : fichiers PNG
        import matplotlib.pyplot as plt
    except ImportError:
        print("[rapport] matplotlib absent : graphiques ignorés")
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # 1. Volume de logs et volume d'erreurs par heure : deux graphiques
    #    l'un sous l'autre (même axe du temps, chacun sa propre échelle).
    timeline = stats["chronologie_par_heure"]
    errors = stats["erreurs_par_heure"]
    if timeline:
        from datetime import datetime
        hours = [datetime.fromisoformat(h) for h in timeline]
        fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
        top.plot(hours, list(timeline.values()), color=BLUE, linewidth=1.5)
        _style(top, "Logs valides par heure")
        bottom.plot(hours, [errors.get(h, 0) for h in timeline],
                    color=LEVEL_COLORS["CRITICAL"], linewidth=1.5)
        _style(bottom, "Erreurs (ERROR + CRITICAL) par heure — les pics "
                       "correspondent aux pannes")
        fig.autofmt_xdate()
        fig.tight_layout()
        paths.append(out_dir / "01_chronologie.png")
        fig.savefig(paths[-1], dpi=120, facecolor=SURFACE)
        plt.close(fig)

    # 2. Répartition par niveau (couleurs de statut)
    levels = {lvl: stats["par_niveau"].get(lvl, 0) for lvl in LEVEL_COLORS}
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(list(levels), list(levels.values()), width=0.6,
           color=[LEVEL_COLORS[lvl] for lvl in levels])
    ax.set_yscale("log")
    _style(ax, "Logs par niveau de sévérité (échelle logarithmique)")
    for x, value in enumerate(levels.values()):
        ax.text(x, value, f"{value:,}".replace(",", " "), ha="center",
                va="bottom", fontsize=8, color=MUTED)
    fig.tight_layout()
    paths.append(out_dir / "02_niveaux.png")
    fig.savefig(paths[-1], dpi=120, facecolor=SURFACE)
    plt.close(fig)

    # 3. Trafic selon l'heure de la journée
    per_hour = stats["par_heure_de_la_journee"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar([int(h) for h in per_hour], list(per_hour.values()), width=0.7,
           color=BLUE)
    ax.set_xticks(range(24))
    _style(ax, "Trafic selon l'heure de la journée (UTC)")
    fig.tight_layout()
    paths.append(out_dir / "03_heures.png")
    fig.savefig(paths[-1], dpi=120, facecolor=SURFACE)
    plt.close(fig)

    # 4. Erreurs par service
    errors_by_service = {
        service: counts.get("ERROR", 0) + counts.get("CRITICAL", 0)
        for service, counts in stats["niveaux_par_service"].items()}
    paths.append(_barh(plt, errors_by_service,
                       "Erreurs (ERROR + CRITICAL) par service",
                       out_dir / "04_erreurs_par_service.png"))

    # 5. Codes HTTP
    codes = {str(code): n for code, n in stats["par_code_http"].items()}
    paths.append(_barh(plt, codes, "Codes de réponse HTTP",
                       out_dir / "05_codes_http.png"))

    # 6. Nettoyage : ce qui a été supprimé ou rejeté
    dropped = {**cleaning["suppressions"], **cleaning["rejets"]}
    if dropped:
        paths.append(_barh(plt, dropped,
                           "Nettoyage : lignes supprimées / rejetées",
                           out_dir / "06_nettoyage.png"))
    if cleaning["corrections"]:
        paths.append(_barh(plt, cleaning["corrections"],
                           "Nettoyage : corrections appliquées",
                           out_dir / "07_corrections.png"))

    # 8. Alertes de sécurité
    if alerts_by_rule:
        paths.append(_barh(plt, alerts_by_rule,
                           "Alertes par règle de sécurité",
                           out_dir / "08_alertes.png"))

    # 9. Histogramme des latences
    buckets = stats["histogramme_latence"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(list(buckets), list(buckets.values()), width=0.7, color=BLUE)
    ax.set_yscale("log")
    _style(ax, "Distribution des temps de réponse (échelle logarithmique)")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    paths.append(out_dir / "09_latences.png")
    fig.savefig(paths[-1], dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return paths
