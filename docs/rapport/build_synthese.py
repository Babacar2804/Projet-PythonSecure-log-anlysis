"""Construit le rapport de synthèse (7 pages) pour la soutenance orale.

Mise en page "affiche" dessinée directement sur le canevas reportlab :
couverture sombre, bandeaux numérotés, cartes de chiffres, blocs terminal.
Tous les chiffres sont lus dans les résultats de l'analyse.

    python docs/rapport/build_synthese.py
    python docs/rapport/build_synthese.py --results output --out synthese.pdf
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from reportlab.lib.colors import Color, HexColor, white  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen.canvas import Canvas  # noqa: E402
from reportlab.platypus import Paragraph  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from build_report import (GITHUB_URL, MEMORY_MEASURES, TEACHER,  # noqa: E402
                          TEAM, TESTS_COUNT)
from logengine.parsing import parse_line  # noqa: E402
from logengine.transform import normalize_record  # noqa: E402

W, H = A4
M = 40                                   # marge
INK = HexColor("#1B1F3B")                # bleu nuit
ORANGE = HexColor("#FF7A3D")
TEAL = HexColor("#12B5A6")
YELLOW = HexColor("#FFC94A")
CORAL = HexColor("#EF476F")
PAPER = HexColor("#FFFDF8")
MUTED = HexColor("#5B5F7A")
TINTS = {ORANGE: HexColor("#FFEDE3"), TEAL: HexColor("#E2F6F4"),
         YELLOW: HexColor("#FFF6DC"), CORAL: HexColor("#FDE6EB"),
         INK: HexColor("#E7E8F0")}
HEX = {"ink": "#1B1F3B", "orange": "#FF7A3D", "teal": "#12B5A6",
       "yellow": "#FFC94A", "coral": "#EF476F", "muted": "#5B5F7A",
       "grid": "#E4E2DA", "paper": "#FFFDF8"}


# ------------------------------------------------------------------ polices
def register_fonts() -> dict[str, str]:
    wanted = {"Head": "bahnschrift.ttf", "Body": "segoeui.ttf",
              "Bold": "segoeuib.ttf", "Semi": "seguisb.ttf",
              "Light": "segoeuil.ttf", "Mono": "consola.ttf",
              "MonoB": "consolab.ttf"}
    fallback = {"Head": "Helvetica-Bold", "Body": "Helvetica",
                "Bold": "Helvetica-Bold", "Semi": "Helvetica-Bold",
                "Light": "Helvetica", "Mono": "Courier",
                "MonoB": "Courier-Bold"}
    fonts = {}
    for name, file in wanted.items():
        path = Path("C:/Windows/Fonts") / file
        try:
            pdfmetrics.registerFont(TTFont(f"S-{name}", str(path)))
            fonts[name] = f"S-{name}"
        except Exception:                # police absente (macOS / Linux)
            fonts[name] = fallback[name]
    if fonts["Body"] == "S-Body":        # pour que <b> fonctionne
        pdfmetrics.registerFontFamily("S-Body", normal="S-Body",
                                      bold="S-Bold", italic="S-Body",
                                      boldItalic="S-Bold")
    return fonts


F = register_fonts()
plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"],
                     "axes.edgecolor": HEX["grid"],
                     "axes.labelcolor": HEX["muted"],
                     "xtick.color": HEX["muted"],
                     "ytick.color": HEX["muted"]})


def style(size: float = 10, font: str = "Body", color: Color = INK,
          leading: float | None = None) -> ParagraphStyle:
    return ParagraphStyle("s", fontName=F[font], fontSize=size,
                          leading=leading or size * 1.38, textColor=color,
                          alignment=TA_LEFT)


def fr(n: float, decimals: int = 0) -> str:
    """12345.6 -> '12 345,6' (espaces insécables)."""
    text = f"{n:,.{decimals}f}".replace(",", "\u00a0").replace(".", ",")
    return text


def millions(n: float) -> str:
    return fr(n / 1e6, 1) + "\u00a0M"


# ------------------------------------------------------------ primitives
def para(c: Canvas, text: str, x: float, top: float, width: float,
         st: ParagraphStyle) -> float:
    """Dessine un paragraphe à partir de ``top`` et renvoie son bas."""
    p = Paragraph(text, st)
    _, height = p.wrap(width, 2000)
    p.drawOn(c, x, top - height)
    return top - height


def page_background(c: Canvas) -> None:
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)


def header(c: Canvas, number: str, title: str, kicker: str) -> float:
    """Bandeau de page ; renvoie l'ordonnée où commence le contenu."""
    page_background(c)
    c.setFillColor(INK)
    c.rect(0, H - 92, W, 92, fill=1, stroke=0)
    c.setFillColor(ORANGE)
    c.circle(M + 24, H - 46, 24, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(F["Head"], 20)
    c.drawCentredString(M + 24, H - 53, number)
    c.setFillColor(white)
    c.setFont(F["Head"], 25)
    c.drawString(M + 62, H - 44, title)
    c.setFillColor(YELLOW)
    c.setFont(F["Semi"], 10.5)
    c.drawString(M + 62, H - 63, kicker)
    # liseré coloré sous le bandeau
    for i, color in enumerate((ORANGE, YELLOW, TEAL, CORAL)):
        c.setFillColor(color)
        c.rect(i * W / 4, H - 97, W / 4, 5, fill=1, stroke=0)
    return H - 120


def footer(c: Canvas, page: int) -> None:
    c.setFillColor(MUTED)
    c.setFont(F["Body"], 8)
    c.drawString(M, 22, "Engine d'analyse de logs sécurisé · Python ING3")
    c.setFillColor(INK)
    c.roundRect(W - M - 46, 15, 46, 18, 9, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont(F["Semi"], 8.5)
    c.drawCentredString(W - M - 23, 21, f"{page} / 7")


def subtitle(c: Canvas, text: str, x: float, top: float,
             color: Color = ORANGE) -> float:
    c.setFillColor(color)
    c.rect(x, top - 13, 4, 14, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(F["Head"], 14)
    c.drawString(x + 11, top - 11, text)
    return top - 24


def kpi(c: Canvas, x: float, top: float, w: float, h: float, color: Color,
        value: str, label: str) -> None:
    c.setFillColor(TINTS[color])
    c.roundRect(x, top - h, w, h, 10, fill=1, stroke=0)
    c.setFillColor(color)
    c.roundRect(x, top - 7, w, 7, 3, fill=1, stroke=0)
    c.rect(x, top - 7, w, 3, fill=1, stroke=0)
    c.setFillColor(INK if color != YELLOW else INK)
    c.setFont(F["Head"], 22)
    c.drawString(x + 12, top - 36, value)
    para(c, label, x + 12, top - 44, w - 20, style(8.5, "Semi", MUTED, 10.5))


def kpi_row(c: Canvas, top: float, items: list[tuple[Color, str, str]],
            h: float = 74) -> float:
    gap = 10
    w = (W - 2 * M - gap * (len(items) - 1)) / len(items)
    for i, (color, value, label) in enumerate(items):
        kpi(c, M + i * (w + gap), top, w, h, color, value, label)
    return top - h - 16


def terminal(c: Canvas, x: float, top: float, w: float,
             lines: list[tuple[str, Color]], size: float = 7.6,
             title: str = "") -> float:
    """Bloc façon terminal (fond sombre, police à chasse fixe)."""
    line_h = size * 1.45
    h = 22 + line_h * len(lines) + 10
    c.setFillColor(INK)
    c.roundRect(x, top - h, w, h, 8, fill=1, stroke=0)
    for i, color in enumerate((CORAL, YELLOW, TEAL)):
        c.setFillColor(color)
        c.circle(x + 12 + i * 11, top - 11, 3.3, fill=1, stroke=0)
    if title:
        c.setFillColor(HexColor("#9DA3C7"))
        c.setFont(F["Mono"], 7.5)
        c.drawString(x + 50, top - 13.5, title)
    y = top - 22 - size
    for text, color in lines:
        c.setFillColor(color)
        c.setFont(F["Mono"], size)
        c.drawString(x + 12, y, text)
        y -= line_h
    return top - h


def callout(c: Canvas, x: float, top: float, w: float, text: str,
            color: Color = TEAL, title: str = "À retenir") -> float:
    st = style(9.6, "Body", INK, 13.5)
    p = Paragraph(text, st)
    _, ph = p.wrap(w - 34, 2000)
    h = ph + 34
    c.setFillColor(TINTS[color])
    c.roundRect(x, top - h, w, h, 8, fill=1, stroke=0)
    c.setFillColor(color)
    c.roundRect(x, top - h, 6, h, 3, fill=1, stroke=0)
    c.setFont(F["Head"], 11)
    c.drawString(x + 18, top - 17, title.upper())
    p.drawOn(c, x + 18, top - 24 - ph)
    return top - h


def info_card(c: Canvas, x: float, top: float, w: float, h: float,
              color: Color, title: str, text: str) -> None:
    """Carte avec un titre coloré et un court texte."""
    c.setFillColor(white)
    c.setStrokeColor(TINTS[color])
    c.setLineWidth(1.5)
    c.roundRect(x, top - h, w, h, 8, fill=1, stroke=1)
    c.setFillColor(color)
    c.circle(x + 16, top - 17, 5, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(F["Head"], 11.5)
    c.drawString(x + 27, top - 21, title)
    para(c, text, x + 11, top - 31, w - 20, style(8.4, color=MUTED,
                                                  leading=11.2))


def chip(c: Canvas, x: float, y: float, text: str, color: Color) -> float:
    """Petite étiquette arrondie ; renvoie la position x suivante."""
    c.setFont(F["Semi"], 8)
    w = pdfmetrics.stringWidth(text, F["Semi"], 8) + 14
    c.setFillColor(color)
    c.roundRect(x, y, w, 15, 7.5, fill=1, stroke=0)
    c.setFillColor(white if color != YELLOW else INK)
    c.drawString(x + 7, y + 4.3, text)
    return x + w + 5


def image(c: Canvas, path: Path, x: float, top: float, w: float) -> float:
    from reportlab.lib.utils import ImageReader
    reader = ImageReader(str(path))
    iw, ih = reader.getSize()
    h = w * ih / iw
    c.drawImage(reader, x, top - h, w, h, mask="auto")
    return top - h


def check_mark(c: Canvas, x: float, y: float, color: Color = TEAL) -> None:
    c.setFillColor(color)
    c.circle(x, y, 7, fill=1, stroke=0)
    c.setStrokeColor(white)
    c.setLineWidth(1.8)
    path = c.beginPath()
    path.moveTo(x - 3.2, y + 0.2)
    path.lineTo(x - 0.8, y - 2.6)
    path.lineTo(x + 3.6, y + 2.8)
    c.drawPath(path, stroke=1, fill=0)


# ----------------------------------------------------------- graphiques
def _clean_axes(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=8.5, length=0)
    ax.set_facecolor("none")


def chart_timeline(stats: dict[str, Any], path: Path) -> Path:
    timeline = stats["chronologie_par_heure"]
    errors = stats["erreurs_par_heure"]
    hours = [datetime.fromisoformat(h) for h in timeline]
    volume = list(timeline.values())
    err = [errors.get(h, 0) for h in timeline]
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(10, 4.6), sharex=True,
        gridspec_kw={"height_ratios": [1, 1.15], "hspace": 0.28})
    top.fill_between(hours, volume, color=HEX["teal"], alpha=0.25, lw=0)
    top.plot(hours, volume, color=HEX["teal"], lw=1.3)
    top.set_title("Logs par heure : le rythme jour / nuit et les week-ends",
                  loc="left", fontsize=10.5, color=HEX["ink"],
                  fontweight="bold")
    peak = volume.index(max(volume))
    top.annotate("pic de trafic\n(DDoS simulé)", (hours[peak], volume[peak]),
                 xytext=(25, -8), textcoords="offset points", fontsize=8,
                 color=HEX["ink"], arrowprops={"arrowstyle": "-",
                                               "color": HEX["muted"]})
    bottom.fill_between(hours, err, color=HEX["coral"], alpha=0.25, lw=0)
    bottom.plot(hours, err, color=HEX["coral"], lw=1.3)
    bottom.set_title("Erreurs par heure : chaque pic est un incident",
                     loc="left", fontsize=10.5, color=HEX["ink"],
                     fontweight="bold")
    ranked = sorted(range(len(err)), key=lambda i: err[i], reverse=True)
    shown: list[int] = []
    for i in ranked:
        if len(shown) == 3:
            break
        if all(abs(i - j) > 36 for j in shown):
            shown.append(i)
            bottom.annotate("incident", (hours[i], err[i]), xytext=(8, 2),
                            textcoords="offset points", fontsize=8,
                            color=HEX["coral"], fontweight="bold")
    for ax in (top, bottom):
        _clean_axes(ax)
        ax.grid(axis="y", color=HEX["grid"], lw=0.7)
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    fig.autofmt_xdate(rotation=0, ha="center")
    bottom.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m"))
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def chart_cleaning(clean: dict[str, Any], path: Path) -> Path:
    labels = {"doublon": "doublons", "ligne_vide": "lignes vides",
              "stacktrace": "stack traces", "commentaire": "commentaires",
              "ip_invalide": "IP invalide", "champs_manquants":
              "champs manquants", "horodatage_invalide": "date invalide",
              "pare_feu_incomplet": "pare-feu incomplet",
              "json_invalide": "JSON cassé", "port_invalide":
              "port invalide", "json_structure_inconnue": "JSON inconnu"}
    items = [(labels.get(k, k), v, HEX["orange"])
             for k, v in clean["suppressions"].items()]
    items += [(labels.get(k, k), v, HEX["coral"])
              for k, v in clean["rejets"].items()]
    items.sort(key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    ax.barh([t[0] for t in items], [t[1] for t in items],
            color=[t[2] for t in items], height=0.62)
    for y, (_, value, _) in enumerate(items):
        ax.text(value, y, f"  {fr(value)}", va="center", fontsize=8,
                color=HEX["ink"])
    _clean_axes(ax)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.margins(x=0.22)
    handles = [plt.Rectangle((0, 0), 1, 1, color=HEX["orange"]),
               plt.Rectangle((0, 0), 1, 1, color=HEX["coral"])]
    ax.legend(handles, ["supprimé avant parsing", "rejeté après contrôle"],
              loc="lower right", frameon=False, fontsize=8)
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def chart_alerts(alerts: dict[str, int], path: Path) -> Path:
    critical = {"elevation_privileges", "exfiltration_donnees"}
    items = sorted(alerts.items(), key=lambda kv: kv[1])
    names = [k.replace("_", " ") for k, _ in items]
    values = [v for _, v in items]
    colors = [HEX["coral"] if k in critical else HEX["orange"]
              for k, _ in items]
    fig, ax = plt.subplots(figsize=(5.4, 3.9))
    ax.hlines(names, 0, values, color=HEX["grid"], lw=2.2)
    ax.scatter(values, names, color=colors, s=70, zorder=3)
    for y, value in enumerate(values):
        ax.text(value, y, f"   {fr(value)}", va="center", fontsize=8,
                color=HEX["ink"])
    _clean_axes(ax)
    ax.set_xscale("log")
    ax.set_xticks([])
    ax.minorticks_off()
    ax.spines["bottom"].set_visible(False)
    ax.margins(x=0.35)
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def chart_errors(stats: dict[str, Any], path: Path) -> Path:
    counts = {service: levels.get("ERROR", 0) + levels.get("CRITICAL", 0)
              for service, levels in stats["niveaux_par_service"].items()}
    items = sorted(counts.items(), key=lambda kv: kv[1])[-8:]
    top_services = {name for name, _ in items[-2:]}
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    ax.barh([k for k, _ in items], [v for _, v in items], height=0.62,
            color=[HEX["coral"] if k in top_services else HEX["muted"]
                   for k, _ in items])
    for y, (_, value) in enumerate(items):
        ax.text(value, y, f"  {fr(value)}", va="center", fontsize=8,
                color=HEX["ink"])
    _clean_axes(ax)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.margins(x=0.2)
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def chart_memory(path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    labels = [f"{fr(n / 1e6, 2 if n < 1e6 else 0)} M\nlignes"
              for n, _ in MEMORY_MEASURES]
    values = [mb for _, mb in MEMORY_MEASURES]
    bars = ax.bar(labels, values, color=[HEX["teal"], HEX["ink"]],
                  width=0.55)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.6,
                f"{fr(value, 1)} Mo", ha="center", fontsize=9,
                color=HEX["ink"], fontweight="bold")
    _clean_axes(ax)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_ylim(0, max(values) * 1.3)
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def chart_pipeline(path: Path) -> Path:
    """Schéma du pipeline en "serpentin", coloré par module."""
    m1, m2, m3, m4 = HEX["teal"], HEX["orange"], HEX["ink"], HEX["coral"]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(-0.95, 4.0)
    ax.axis("off")

    def box(x: float, y: float, title: str, sub: str, color: str,
            w: float = 1.75) -> None:
        ax.add_patch(FancyBboxPatch((x, y), w, 0.95,
                                    boxstyle="round,pad=0.02,rounding_size="
                                    "0.16", fc=color, ec="none"))
        ax.text(x + w / 2, y + 0.6, title, ha="center", color="white",
                fontsize=9.5, fontweight="bold", family="monospace")
        ax.text(x + w / 2, y + 0.25, sub, ha="center", color="white",
                fontsize=8)

    def arrow(a: tuple[float, float], b: tuple[float, float]) -> None:
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>",
                                     mutation_scale=13, lw=1.6,
                                     color=HEX["muted"]))

    top = [("12 Go .log", "fichiers", HEX["muted"]),
           ("yield from", "lecture", m1),
           ("map(clean)", "nettoyage", m2),
           ("filter(keep)", "lignes vides...", m2),
           ("match-case", "str -> dict", m1)]
    for i, (title, sub, color) in enumerate(top):
        box(0.1 + i * 2, 2.9, title, sub, color)
        if i:
            arrow((0.1 + i * 2 - 0.22, 3.37), (0.1 + i * 2 - 0.02, 3.37))
    arrow((9.0, 2.88), (9.0, 2.6))
    row = 1.6
    bottom = [("map(normalize)", "types, casse", m2, 8.1),
              ("filter(accept)", "rejets", m2, 6.1),
              ("for record:", "une seule passe", HEX["ink"], 4.1)]
    for title, sub, color, x in bottom:
        box(x, row, title, sub, color)
    arrow((8.08, row + 0.47), (7.88, row + 0.47))
    arrow((6.08, row + 0.47), (5.88, row + 0.47))
    outs = [("stats.update", "defaultdict, set", m3),
            ("detector.feed", "while / for-else", m3),
            ("check_rules", "*args, **kwargs", m4)]
    for i, (title, sub, color) in enumerate(outs):
        y = row - i * 1.15
        box(0.1, y, title, sub, color, w=2.05)
        arrow((4.08, row + 0.47), (2.2, y + 0.47))
    legend = [("Module 1", m1), ("Module 2", m2), ("Module 3", m3),
              ("Module 4", m4)]
    for i, (name, color) in enumerate(legend):
        ax.add_patch(FancyBboxPatch((4.3 + i * 1.45, -0.62), 0.28, 0.28,
                                    boxstyle="round,pad=0.01", fc=color,
                                    ec="none"))
        ax.text(4.7 + i * 1.45, -0.55, name, fontsize=8.5,
                color=HEX["ink"])
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


# --------------------------------------------------------------- pages
def page_cover(c: Canvas, report: dict[str, Any]) -> None:
    c.setFillColor(INK)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    # fond : de vraies lignes de logs, très estompées
    sample = [
        "2026-10-01T08:15:32.481Z | INFO | api-gateway | 10.0.3.17:51432/TCP"
        " | user=u1042 | event=http_request",
        "FW 2026-10-01T00:20:12.423Z DROP TCP 102.109.77.236 27409 "
        "10.0.100.29 22 DENY-SSH-EXT",
        '{"ts":"2026-10-01T08:15:32Z","lvl":"error","svc":"payment-service"'
        ',"code":502}',
        "2026-10-01T09:34:05.549Z | WARNING | auth-service | "
        "197.9.34.253:40152/TCP | user=admin | event=login_failed",
    ]
    c.setFont(F["Mono"], 7)
    for i in range(70):
        c.setFillColor(Color(1, 1, 1, alpha=0.05 + 0.03 * (i % 3 == 0)))
        c.drawString(-30 + (i * 37) % 90, H - 14 - i * 12,
                     sample[i % len(sample)] * 2)
    # bloc titre
    c.setFillColor(ORANGE)
    c.rect(M, H - 300, 8, 150, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.setFont(F["Semi"], 11)
    c.drawString(M + 24, H - 162, "PROJET FINAL · PYTHON AVANCÉ · ING3")
    c.setFillColor(white)
    c.setFont(F["Head"], 44)
    c.drawString(M + 24, H - 212, "Analyser 12 Go")
    c.drawString(M + 24, H - 256, "de logs sans faire")
    c.setFillColor(ORANGE)
    c.drawString(M + 24, H - 300, "exploser la RAM")
    c.setFillColor(HexColor("#C9CCE6"))
    c.setFont(F["Light"], 13)
    c.drawString(M + 24, H - 330, "Engine de traitement et d'analyse de "
                 "flux de données sécurisé")
    # chiffres clés
    run, brute = report["execution"], report["force_brute"]
    tiles = [(TEAL, fr(run["taille_go"], 1) + " Go", "de logs générés"),
             (ORANGE, millions(report["nettoyage"]["lignes_lues"]),
              "de lignes analysées"),
             (YELLOW, fr(sum(report["alertes_par_regle"].values())),
              "alertes de sécurité"),
             (CORAL, str(brute["nb_comptes_compromis"]),
              "attaquants démasqués")]
    gap, top = 10, H - 400
    w = (W - 2 * M - 3 * gap) / 4
    for i, (color, value, label) in enumerate(tiles):
        x = M + i * (w + gap)
        c.setFillColor(HexColor("#262B52"))
        c.roundRect(x, top - 78, w, 78, 10, fill=1, stroke=0)
        c.setFillColor(color)
        c.roundRect(x, top - 78, 6, 78, 3, fill=1, stroke=0)
        c.setFont(F["Head"], 24)
        c.drawString(x + 16, top - 38, value)
        c.setFillColor(HexColor("#C9CCE6"))
        c.setFont(F["Body"], 9)
        c.drawString(x + 16, top - 58, label)
    # équipe
    c.setFillColor(YELLOW)
    c.setFont(F["Head"], 13)
    c.drawString(M, 190, "L'ÉQUIPE")
    c.setFillColor(white)
    c.setFont(F["Semi"], 12)
    for i, name in enumerate(TEAM):
        c.drawString(M + (i % 2) * 230, 166 - (i // 2) * 20, name)
    c.setFillColor(HexColor("#C9CCE6"))
    c.setFont(F["Body"], 9.5)
    c.drawString(M, 106, TEACHER)
    c.drawString(M, 90, GITHUB_URL)
    c.drawString(M, 74, date.today().strftime("Soutenance · %d/%m/%Y"))
    for i, color in enumerate((ORANGE, YELLOW, TEAL, CORAL)):
        c.setFillColor(color)
        c.rect(i * W / 4, 0, W / 4, 8, fill=1, stroke=0)


def page_challenge(c: Canvas, report: dict[str, Any]) -> None:
    top = header(c, "1", "Le défi et nos données",
                 "Un jeu de données réaliste, varié… et volontairement sale")
    run = report["execution"]
    stats = report["statistiques"]
    top = para(c, "Le sujet : construire en Python une plateforme en ligne "
               "de commande qui <b>ingère, nettoie et analyse</b> des "
               "journaux "
               "de logs volumineux, <b>sans jamais les charger entièrement "
               "en mémoire</b>. Pour la tester, nous avons écrit un "
               "générateur qui simule 30 jours d'activité d'un site "
               "e-commerce et de son infrastructure.", M, top, W - 2 * M,
               style(10.5, leading=15)) - 14
    top = kpi_row(c, top, [
        (TEAL, fr(run["taille_go"], 1) + " Go", "écrits en 75 s par 7 "
         "processus en parallèle"),
        (ORANGE, millions(report["nettoyage"]["lignes_lues"]),
         "lignes réparties en 12 fichiers"),
        (YELLOW, fr(stats["nb_ip_uniques"]), "adresses IP différentes"),
        (CORAL, "11", "services : API, paiement, base de données, VPN…"),
    ])
    top = subtitle(c, "Trois formats de lignes bien structurés", M, top)
    top = terminal(c, M, top, W - 2 * M, [
        ("# applicatif (80 %) : 7 champs séparés par |", HexColor("#7F86B8")),
        ("2026-10-01T08:15:32.481Z | INFO | api-gateway | 10.0.3.17:51432/"
         "TCP | user=u1042 | event=http_request | {...}", white),
        ("# JSON (10 %)", HexColor("#7F86B8")),
        ('{"ts":"2026-10-01T08:15:32Z","lvl":"error","svc":"payment-service",'
         '"client":{"ip":...},"code":502}', TINTS[TEAL]),
        ("# pare-feu (10 %) : champs positionnels", HexColor("#7F86B8")),
        ("FW 2026-10-01T00:20:12.423Z DROP TCP 102.109.77.236 27409 "
         "10.0.100.29 22 DENY-SSH-EXT", YELLOW),
    ], title="data/raw/logs-00-20261001-0000.log") - 16
    col = (W - 2 * M - 16) / 2
    left_top = subtitle(c, "Des données variées", M, top, TEAL)
    x = M
    y = left_top - 16
    for text in ("cycle jour / nuit", "week-ends calmes", "pannes", "DDoS",
                 "déploiements", "disque plein", "force brute",
                 "injections SQL", "XSS", "scans de ports", "botnet",
                 "IPv6"):
        if x + 90 > M + col:
            x, y = M, y - 20
        x = chip(c, x, y, text, TEAL if y > left_top - 40 else INK)
    left_bottom = para(c, "Utilisateurs selon une loi de Zipf, profil "
                       "horaire réaliste, incidents planifiés : les analyses "
                       "ont vraiment quelque chose à trouver.", M, y - 10,
                       col, style(9, color=MUTED, leading=12.5))
    right = M + col + 16
    rt = subtitle(c, "Environ 5 % de lignes abîmées", right, top, CORAL)
    defects = [("err · FATAL · Warning", "réparé"),
               ("USER_1042 · U-1042 · null", "réparé"),
               ("01/10/2026 · epoch · sans fuseau", "réparé"),
               ("{'status':'500'} · requÃªte", "réparé"),
               ("\\x00 · \\x1b[31m · \\ufeff · \\r", "réparé"),
               ("doublons · vides · stack traces", "supprimé"),
               ("999.12.4.1 · 2026-13-45 · tronqué", "rejeté")]
    for text, verdict in defects:
        c.setFillColor(INK)
        c.setFont(F["Mono"], 8)
        c.drawString(right, rt - 10, text)
        color = {"réparé": TEAL, "supprimé": ORANGE}.get(verdict, CORAL)
        chip(c, right + col - 62, rt - 13, verdict, color)
        rt -= 21
    top = subtitle(c, "Comment fonctionne le générateur (generator.py)", M,
                   min(left_bottom, rt) - 16, YELLOW)
    cards = [(TEAL, "Pools", "Populations fixes : 5 000 utilisateurs, "
              "~17 000 IP, 60 attaquants, un botnet. Même graine = mêmes IP "
              "dans tous les fichiers."),
             (ORANGE, "Scénarios", "Pannes, DDoS, déploiements et disque "
              "plein planifiés sur les 30 jours, avec un profil horaire "
              "réaliste."),
             (CORAL, "NoiseInjector", "Abîme ~5 % des lignes : un match-case "
              "choisit le défaut (casse, date, IP, JSON, encodage…)."),
             (INK, "En parallèle", "ProcessPoolExecutor : un processus par "
              "fichier, 12 fichiers écrits en même temps.")]
    gap = 10
    w = (W - 2 * M - 3 * gap) / 4
    for i, (color, title, text) in enumerate(cards):
        info_card(c, M + i * (w + gap), top, w, 104, color, title, text)
    footer(c, 2)


def page_architecture(c: Canvas, figures: Path) -> None:
    top = header(c, "2", "L'architecture",
                 "Une chaîne de générateurs : une ligne entre, une ligne "
                 "sort, "
                 "rien n'est stocké")
    top = image(c, chart_pipeline(figures / "s_pipeline.png"), M, top,
                W - 2 * M) - 10
    top = subtitle(c, "Le pipeline en 8 lignes (main.py)", M, top)
    top = terminal(c, M, top, W - 2 * M, [
        ("lines   = read_sources(files)                # yield from",
         white),
        ("lines   = map(clean_raw_line, lines)        # nettoyage du texte",
         white),
        ("lines   = filter(tracker.keep_line, lines)  # vides, #, traces",
         white),
        ("records = map(parse_line, lines)            # match-case -> dict",
         white),
        ("records = map(normalize_record, records)    # types, casse",
         white),
        ("records = filter(tracker.accept, records)   # rejets", white),
        ("for record in records:                      # RIEN n'est lu avant"
         " cette ligne", YELLOW),
        ("    stats.update(record); detector.feed(record); "
         "check_rules(record)", YELLOW),
    ], size=8.2, title="main.py") - 16
    col = (W - 2 * M - 16) * 0.58
    callout(c, M, top, col,
            "<b>map</b>, <b>filter</b> et <b>yield</b> sont "
            "<b>paresseux</b> : "
            "ils ne calculent rien tant que la boucle <b>for</b> ne demande "
            "pas l'élément suivant. Chaque ligne traverse toute la chaîne, "
            "est comptée, puis oubliée. On ne garde que des compteurs : la "
            "mémoire dépend du nombre d'IP ou d'utilisateurs, <b>pas de la "
            "taille des fichiers</b>.<br/><br/>Le <b>même pipeline</b> "
            "sert au "
            "mode temps réel : seule la source change "
            "(<font name='%s'>follow_log_file</font>, comme "
            "<font name='%s'>tail -f</font>)." % (F["Mono"], F["Mono"]))
    right = M + col + 16
    rt = subtitle(c, "Mémoire mesurée", right, top, TEAL)
    image(c, chart_memory(figures / "s_memory.png"), right, rt,
          W - M - right)
    footer(c, 3)


def page_cleaning(c: Canvas, report: dict[str, Any], figures: Path) -> None:
    top = header(c, "3", "Le grand nettoyage",
                 "map + filter + match-case : réparer tout ce qui peut "
                 "l'être, écarter le reste")
    clean = report["nettoyage"]
    fixes = sum(clean["corrections"].values())
    top = kpi_row(c, top, [
        (TEAL, millions(clean["enregistrements_valides"]), "enregistrements "
         "valides en sortie"),
        (YELLOW, millions(fixes), "corrections appliquées (lignes "
         "sauvées)"),
        (ORANGE, millions(clean["lignes_supprimees"]), "lignes supprimées "
         "(vides, doublons…)"),
        (CORAL, fr(clean["taux_de_rejet_pct"], 1) + " %", "seulement de "
         "pertes au total"),
    ])
    top = subtitle(c, "Avant / après : une vraie ligne passée dans le "
                   "pipeline", M, top)
    dirty = ("01/10/2026 08:15:32 | err | API_GATEWAY | 88.12.34.56:51432 "
             "| user=USER_7 | event=http_request | "
             "{'status':'500','latency_ms':-1}")
    cut = dirty.index("{")
    top = terminal(c, M, top, W - 2 * M, [
        ("# ligne brute, telle qu'elle sort du générateur",
         HexColor("#7F86B8")),
        (dirty[:cut], CORAL), ("    " + dirty[cut:], CORAL)],
        size=7.6, title="entrée") - 6
    rec = normalize_record(parse_line(dirty))
    label = "parse_line  puis  normalize_record"
    c.setFillColor(ORANGE)
    c.setFont(F["Head"], 13)
    c.drawCentredString(W / 2, top - 15, label)
    half = pdfmetrics.stringWidth(label, F["Head"], 13) / 2
    for x in (W / 2 - half - 18, W / 2 + half + 18):   # flèches dessinées
        path = c.beginPath()
        path.moveTo(x - 7, top - 7)
        path.lineTo(x + 7, top - 7)
        path.lineTo(x, top - 17)
        path.close()
        c.drawPath(path, fill=1, stroke=0)
    top -= 26
    rows = [("timestamp", f"{rec['timestamp']}", "date réécrite en ISO, UTC"),
            ("level", rec["level"], "« err » normalisé (match-case)"),
            ("service", rec["service"], "casse et « _ » corrigés"),
            ("connection", str(rec["connection"]), "tuple immuable, "
             "protocole TCP par défaut"),
            ("user", str(rec["user"]), "« USER_7 » ramené à « u7 »"),
            ("payload", str(rec["payload"]), "guillemets et latence "
             "corrigés")]
    box_h = 18 * len(rows) + 16
    c.setFillColor(TINTS[TEAL])
    c.roundRect(M, top - box_h, W - 2 * M, box_h, 8, fill=1, stroke=0)
    y = top - 20
    for key, value, why in rows:
        c.setFillColor(TEAL)
        c.setFont(F["MonoB"], 8.5)
        c.drawString(M + 14, y, key)
        c.setFillColor(INK)
        c.setFont(F["Mono"], 8.5)
        c.drawString(M + 92, y, value[:46])
        c.setFillColor(MUTED)
        c.setFont(F["Body"], 8.5)
        c.drawString(M + 340, y, why)
        y -= 18
    top -= box_h + 16
    col = (W - 2 * M) * 0.56
    top_chart = subtitle(c, "Ce qui a été écarté, et pourquoi", M, top)
    image(c, chart_cleaning(clean, figures / "s_cleaning.png"), M,
          top_chart, col)
    right = M + col + 16
    callout(c, right, top, W - M - right,
            "Chaque décision est <b>comptée par cause</b> : "
            "<font name='%s'>filter</font> reçoit des méthodes "
            "(<font name='%s'>tracker.keep_line</font>, "
            "<font name='%s'>tracker.accept</font>) qui gardent ou écartent "
            "la ligne <b>et</b> notent pourquoi.<br/><br/>Les doublons sont "
            "détectés en comparant à la ligne précédente : un "
            "<font name='%s'>set</font> de 69 M de lignes ferait exploser "
            "la RAM." % (F["Mono"], F["Mono"], F["Mono"], F["Mono"]),
            ORANGE, "Le saviez-vous ?")
    footer(c, 4)


def page_insights(c: Canvas, report: dict[str, Any], figures: Path) -> None:
    top = header(c, "4", "Ce que révèlent les données",
                 "defaultdict, set et frozenset : 68 millions de lignes "
                 "résumées en quelques compteurs")
    stats, ips = report["statistiques"], report["ensembles_ip"]
    top = image(c, chart_timeline(stats, figures / "s_timeline.png"), M, top,
                W - 2 * M) - 14
    top = kpi_row(c, top, [
        (CORAL, fr(ips["blacklist_actives"]), f"IP de la liste noire "
         f"actives sur {fr(ips['taille_blacklist'])} (actives & blacklist)"),
        (YELLOW, fr(ips["blacklist_dormantes"]), "IP listées jamais vues "
         "(blacklist - actives)"),
        (ORANGE, fr(len(stats["scans_de_ports"])), "scanners : 15 ports "
         "visés ou plus"),
        (TEAL, fr(stats["nb_flux_bloques_distincts"]), "flux bloqués "
         "(IP, port, protocole)"),
    ], h=84)
    col = (W - 2 * M - 16) / 2
    b1 = callout(c, M, top, col,
                 "Le <b>tuple</b> (IP, Port, Protocole) est immuable, donc il "
                 "peut servir de <b>clé de dictionnaire</b> : "
                 "<font name='%s'>blocked_flows[(ip, port, proto)] += 1"
                 "</font>. En regroupant ces clés par IP, on repère les "
                 "scans de ports." % F["Mono"], TEAL, "Tuples")
    b2 = callout(c, M + col + 16, top, col,
                 "La liste noire est un <b>frozenset</b> : personne ne peut "
                 "la modifier pendant l'analyse. Les opérations <b>| &amp; - "
                 "^</b> comparent en une ligne les IP actives et les IP "
                 "listées.", INK, "Ensembles")
    top = subtitle(c, "Erreurs par service : les pannes ressortent", M,
                   min(b1, b2) - 16, CORAL)
    image(c, chart_errors(stats, figures / "s_errors.png"), M, top,
          col + 30)
    terminal(c, M + col + 46, top - 4, col - 30, [
        ("match record:", white),
        ('    case {"level": "ERROR" | "CRITICAL",', YELLOW),
        ('          "ip": ip}:', YELLOW),
        ("        self.error_ips.add(ip)", white),
        ("        self.error_timeline[hour] += 1", white),
    ], size=7.6, title="aggregation.py")
    para(c, "Un seul motif <b>match</b> vérifie le niveau, capture l'IP et "
         "alimente un <b>set</b> (IP uniques en erreur) et un "
         "<b>defaultdict</b> (erreurs par heure).", M + col + 46, top - 98,
         col - 30, style(8.8, color=INK, leading=12))
    footer(c, 5)


def page_security(c: Canvas, report: dict[str, Any], figures: Path) -> None:
    top = header(c, "5", "Sécurité : détecter les attaques",
                 "Une fenêtre glissante, un moteur de règles à arguments "
                 "variables, et du temps réel")
    brute, alerts = report["force_brute"], report["alertes_par_regle"]
    col = (W - 2 * M - 16) / 2
    left_top = subtitle(c, "Force brute : la boucle qui tranche", M, top,
                        CORAL)
    y = terminal(c, M, left_top, col, [
        ("for moment, user, ok in tentatives:", white),
        ("    if not ok:", white),
        ("        consecutive += 1", white),
        ("        continue", TEAL),
        ("    if consecutive >= 5 and récent:", white),
        ("        compromis = user", white),
        ("        break           # attaque réussie", CORAL),
        ("    consecutive = 0", white),
        ("else:", YELLOW),
        ('    statut = "bloquée"  # aucun break', YELLOW),
    ], size=8, title="detection.py") - 10
    para(c, "Pendant la lecture, une <b>while</b> purge une fenêtre "
         "glissante de 2 minutes par IP. Le <b>else</b> de la boucle ne "
         "s'exécute que si elle va au bout <b>sans break</b> : l'attaque "
         "a échoué.", M, y, col, style(9.2, color=INK, leading=13))
    right = M + col + 16
    rt = subtitle(c, "Résultat sur les 12 Go", right, top, CORAL)
    tiles = [(CORAL, fr(brute["nb_incidents"]), "IP attaquantes "
              "détectées"),
             (ORANGE, fr(brute["nb_comptes_compromis"]), "ont réussi à "
              "entrer"),
             (YELLOW, fr(alerts.get("elevation_privileges", 0)),
              "élévations de privilèges confirment")]
    for i, (color, value, label) in enumerate(tiles):
        kpi(c, right, rt - i * 66, col, 58, color, value, label)
    top = min(y - 60, rt - 3 * 66) - 4
    top = subtitle(c, "Le moteur de règles : apply_security_rules(*args, "
                   "**kwargs)", M, top)
    chart_bottom = image(c, chart_alerts(alerts, figures / "s_alerts.png"),
                         M, top, col + 10)
    t = terminal(c, right, top, col, [
        ("check = apply_security_rules(", white),
        ("    rule_sql_injection, rule_xss, ...,   # *args", TEAL),
        ("    blacklist=ips, max_latency_ms=5000)  # **kwargs", YELLOW),
        ("for alert in check(record): ...", white),
    ], size=7.8, title="rules.py") - 8
    t = para(c, "La fonction maître <b>renvoie une fonction</b> "
             "(fermeture). Une règle = une fonction ; une règle qui plante "
             "est isolée par <b>try / except / else</b>.", right, t, col,
             style(9, leading=12.5)) - 10
    t = terminal(c, right, t, col, [
        ("$ python main.py live", white),
        ("[live] 2,357 lignes lues, 7 alertes", HexColor("#9DA3C7")),
        ("[HIGH] xss  217.135.14.178 javascript:...", CORAL),
        ("[FORCE BRUTE] 92.112.165.218 : 5 échecs", YELLOW),
    ], size=7.6, title="démo temps réel")
    top = subtitle(c, "9 fonctions de règles, 10 types d'alertes", M,
                   min(chart_bottom, t) - 18, ORANGE)
    rules = [("élévation de privilèges", CORAL), ("exfiltration", CORAL),
             ("injection SQL", ORANGE), ("XSS", ORANGE),
             ("path traversal", ORANGE), ("IP en liste noire", ORANGE),
             ("port sensible exposé", ORANGE), ("outil offensif", YELLOW),
             ("scanner (/.env, /wp-admin)", YELLOW),
             ("requête lente", TEAL)]
    x, y = M, top - 16
    for name, color in rules:
        if x + 120 > W - M:
            x, y = M, y - 21
        x = chip(c, x, y, name, color)
    legend = [("CRITICAL", CORAL), ("HIGH", ORANGE), ("MEDIUM", YELLOW),
              ("LOW", TEAL)]
    lx = M
    for name, color in legend:
        c.setFillColor(color)
        c.circle(lx + 4, y - 22, 4, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont(F["Body"], 8)
        c.drawString(lx + 12, y - 25, name)
        lx += 70
    footer(c, 6)


def page_quality(c: Canvas, report: dict[str, Any]) -> None:
    top = header(c, "6", "Qualité et barème",
                 "Chaque critère, et l'endroit exact où le montrer dans le "
                 "code")
    rows = [("Environnement & livrables", "2", "venv, requirements.txt "
             "(pip freeze), .py uniquement, rapport PDF, Git", TEAL),
            ("Mémoire & générateurs", "4", "yield, yield from, "
             "follow_log_file ; ~19 Mo pour 2 M de lignes", TEAL),
            ("Structures de données", "4", "set, frozenset, defaultdict, "
             "tuple clé de dict, match-case", ORANGE),
            ("Programmation fonctionnelle", "4", "map, filter, lambda, "
             "méthodes passées à filter, fonction renvoyée", ORANGE),
            ("Règles & introspection", "3", "apply_security_rules(*args, "
             "**kwargs), globals() / locals()", CORAL),
            ("Qualité & robustesse", "3", f"PEP 8, mypy 0 erreur, "
             f"{TESTS_COUNT} tests, try/except/else, for-else", INK)]
    for name, points, where, color in rows:
        c.setFillColor(TINTS[color])
        c.roundRect(M, top - 46, W - 2 * M, 46, 8, fill=1, stroke=0)
        c.setFillColor(color)
        c.roundRect(M, top - 46, 6, 46, 3, fill=1, stroke=0)
        check_mark(c, M + 24, top - 23, color)
        c.setFillColor(INK)
        c.setFont(F["Head"], 12.5)
        c.drawString(M + 40, top - 20, name)
        c.setFillColor(MUTED)
        c.setFont(F["Body"], 8.6)
        c.drawString(M + 40, top - 35, where)
        c.setFillColor(color)
        c.setFont(F["Head"], 18)
        c.drawRightString(W - M - 14, top - 30, f"{points} pts")
        top -= 54
    top -= 6
    top = kpi_row(c, top, [
        (TEAL, str(TESTS_COUNT), "tests pytest, tous verts"),
        (ORANGE, "0", "erreur mypy sur code et tests"),
        (YELLOW, "0", "écart PEP 8 (pycodestyle)"),
        (INK, fr(report["execution"]["lignes_par_seconde"]),
         "lignes analysées par seconde"),
    ])
    top = subtitle(c, "En résumé", M, top)
    callout(c, M, top, W - 2 * M,
            "Un moteur qui traite <b>12 Go de logs hétérogènes et "
            "dégradés</b> avec quelques dizaines de mégaoctets de mémoire, "
            "répare l'essentiel des défauts, retrouve les incidents et les "
            "attaques injectés, et fonctionne aussi <b>en temps réel</b>. "
            "Pistes d'amélioration : analyse parallèle par fichier, "
            "séparation des campagnes d'attaque d'une même IP.",
            ORANGE, "Conclusion")
    c.setFillColor(INK)
    c.roundRect(M, 52, W - 2 * M, 44, 10, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.setFont(F["Head"], 13)
    c.drawString(M + 16, 78, "DÉMO")
    c.setFillColor(white)
    c.setFont(F["Mono"], 9)
    c.drawString(M + 70, 78, "python main.py demo     python main.py live "
                 "    python -m pytest")
    c.setFillColor(HexColor("#C9CCE6"))
    c.setFont(F["Body"], 8.5)
    c.drawString(M + 70, 62, "Code et rapport complet : " + GITHUB_URL)
    footer(c, 7)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rapport de synthèse PDF")
    parser.add_argument("--results", type=Path, default=ROOT / "output")
    parser.add_argument("--out", type=Path,
                        default=HERE / "Synthese_soutenance.pdf")
    args = parser.parse_args()
    report = json.loads((args.results / "report.json").read_text("utf-8"))
    figures = HERE / "_figures"
    figures.mkdir(exist_ok=True)
    c = Canvas(str(args.out), pagesize=A4)
    c.setTitle("Synthèse — Engine d'analyse de logs")
    c.setAuthor(", ".join(TEAM))
    page_cover(c, report)
    for draw in (page_challenge, page_architecture, page_cleaning,
                 page_insights, page_security, page_quality):
        c.showPage()
        if draw is page_challenge or draw is page_quality:
            draw(c, report)
        elif draw is page_architecture:
            draw(c, figures)
        else:
            draw(c, report, figures)
    c.save()
    print(f"Synthèse écrite : {args.out}")


if __name__ == "__main__":
    main()
