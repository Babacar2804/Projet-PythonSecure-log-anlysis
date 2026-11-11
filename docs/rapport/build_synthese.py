"""Construit deux PDF de 11 pages avec la même mise en page :

- Synthese_soutenance.pdf : support d'oral pour l'équipe (on peut présenter
  sans notes, tout ce qu'il faut dire est sur le document) ;
- Rapport_final.pdf : la même chose rédigée pour le professeur (pas de
  consignes d'oral, les « questions du jury » deviennent nos choix
  techniques justifiés).

Organisation : une couverture, une page d'ouverture, puis DEUX pages par
module (page A « ce qu'on présente », page B « ce que ça donne » avec les
questions probables du jury), et une page de clôture.

Mise en page dessinée directement sur le canevas reportlab. Tous les
chiffres sont lus dans les résultats de l'analyse (output/report.json).

    python docs/rapport/build_synthese.py
    python docs/rapport/build_synthese.py --results output --out support.pdf
"""

import argparse
import json
import sys
from datetime import datetime
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
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen.canvas import Canvas  # noqa: E402
from reportlab.platypus import Paragraph  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from build_report import (GITHUB_URL, MEMORY_MEASURES,  # noqa: E402
                          SOUTENANCE_DATE, TEACHER, TEAM, TESTS_COUNT)
from logengine.parsing import parse_line  # noqa: E402
from logengine.transform import normalize_record  # noqa: E402

W, H = A4
M = 40                                   # marge
TOTAL_PAGES = 11
INK = HexColor("#1B1F3B")                # bleu nuit
ORANGE = HexColor("#FF7A3D")
TEAL = HexColor("#12B5A6")
YELLOW = HexColor("#FFC94A")
CORAL = HexColor("#EF476F")
PAPER = HexColor("#FFFDF8")
MUTED = HexColor("#5B5F7A")
SOFT = HexColor("#9DA3C7")               # commentaires dans les terminaux
TINTS = {ORANGE: HexColor("#FFEDE3"), TEAL: HexColor("#E2F6F4"),
         YELLOW: HexColor("#FFF6DC"), CORAL: HexColor("#FDE6EB"),
         INK: HexColor("#E7E8F0")}
HEX = {"ink": "#1B1F3B", "orange": "#FF7A3D", "teal": "#12B5A6",
       "yellow": "#FFC94A", "coral": "#EF476F", "muted": "#5B5F7A",
       "grid": "#E4E2DA", "paper": "#FFFDF8"}
# Une couleur par module, la même partout (schéma, pastilles, encadrés)
MODULE_COLORS = {1: TEAL, 2: ORANGE, 3: YELLOW, 4: CORAL}

# Deux versions du même document : le support d'oral (pour l'équipe) et le
# rapport final (pour le professeur). Seules quelques formulations changent.
PROF = False
PROF_TEXT = {
    "Ce qu'on présente, dans l'ordre": "Notre réalisation, étape par étape",
    "QUESTIONS PROBABLES DU JURY": "NOS CHOIX TECHNIQUES, JUSTIFIÉS",
    "Ouverture": "Introduction",
    "AU PROGRAMME": "SOMMAIRE",
    "Qualité, barème et démo": "Qualité et conformité au barème",
    "Chaque critère du barème et l'endroit où le montrer":
        "Chaque critère du barème et l'endroit où il est traité dans le code",
    "DÉMO": "LANCER",
    "PROJET FINAL · PYTHON AVANCÉ · ING3":
        "RAPPORT FINAL · PYTHON AVANCÉ · ING3",
}


def adapt(text: str) -> str:
    """Reformule un texte du support d'oral pour la version professeur."""
    if not PROF:
        return text
    text = PROF_TEXT.get(text, text)
    return (text.replace("ce qu'on présente", "réalisation")
            .replace("Le code à montrer", "Extrait de code"))


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


def code(text: str) -> str:
    """Met un bout de texte en police à chasse fixe dans un paragraphe."""
    return f"<font name='{F['Mono']}'>{text}</font>"


def fr(n: float, decimals: int = 0) -> str:
    """12345.6 -> '12 345,6' (espaces insécables)."""
    return f"{n:,.{decimals}f}".replace(",", "\u00a0").replace(".", ",")


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


def para_height(text: str, width: float, st: ParagraphStyle) -> float:
    return Paragraph(text, st).wrap(width, 2000)[1]


def header(c: Canvas, badge: str, title: str, kicker: str,
           color: Color = ORANGE, label: str = "") -> float:
    """Bandeau de page ; renvoie l'ordonnée où commence le contenu."""
    title, kicker, label = adapt(title), adapt(kicker), adapt(label)
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(INK)
    c.rect(0, H - 92, W, 92, fill=1, stroke=0)
    c.setFillColor(color)
    c.circle(M + 24, H - 46, 24, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(F["Head"], 21)
    c.drawCentredString(M + 24, H - 53.5, badge)
    if label:
        c.setFillColor(color)
        c.setFont(F["Semi"], 9)
        c.drawString(M + 62, H - 26, label.upper())
    c.setFillColor(white)
    c.setFont(F["Head"], 24)
    c.drawString(M + 62, H - 48, title)
    c.setFillColor(YELLOW if color != YELLOW else white)
    c.setFont(F["Semi"], 10)
    c.drawString(M + 62, H - 67, kicker)
    for i, stripe in enumerate((ORANGE, YELLOW, TEAL, CORAL)):
        c.setFillColor(stripe)
        c.rect(i * W / 4, H - 97, W / 4, 5, fill=1, stroke=0)
    return H - 116


def footer(c: Canvas, page: int) -> None:
    c.setFillColor(MUTED)
    c.setFont(F["Body"], 8)
    kind = "rapport final" if PROF else "support de soutenance"
    c.drawString(M, 22, "Engine d'analyse de logs sécurisé · Python ING3 · "
                 f"{kind} · {SOUTENANCE_DATE}")
    c.setFillColor(INK)
    c.roundRect(W - M - 50, 15, 50, 18, 9, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont(F["Semi"], 8.5)
    c.drawCentredString(W - M - 25, 21, f"{page} / {TOTAL_PAGES}")


def subtitle(c: Canvas, text: str, x: float, top: float,
             color: Color = ORANGE) -> float:
    c.setFillColor(color)
    c.rect(x, top - 13, 4, 14, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(F["Head"], 13.5)
    c.drawString(x + 11, top - 11, adapt(text))
    return top - 22


def kpi(c: Canvas, x: float, top: float, w: float, h: float, color: Color,
        value: str, label: str) -> None:
    c.setFillColor(TINTS[color])
    c.roundRect(x, top - h, w, h, 10, fill=1, stroke=0)
    c.setFillColor(color)
    c.roundRect(x, top - 7, w, 7, 3, fill=1, stroke=0)
    c.rect(x, top - 7, w, 3, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(F["Head"], 21)
    c.drawString(x + 12, top - 34, value)
    para(c, label, x + 12, top - 41, w - 20, style(8.3, "Semi", MUTED, 10.2))


def kpi_row(c: Canvas, top: float, items: list[tuple[Color, str, str]],
            h: float = 68, x: float = M, width: float = W - 2 * M) -> float:
    gap = 10
    w = (width - gap * (len(items) - 1)) / len(items)
    for i, (color, value, label) in enumerate(items):
        kpi(c, x + i * (w + gap), top, w, h, color, value, label)
    return top - h - 14


def terminal(c: Canvas, x: float, top: float, w: float,
             lines: list[tuple[str, Color]], size: float = 7.6,
             title: str = "") -> float:
    """Bloc façon terminal (fond sombre, police à chasse fixe)."""
    line_h = size * 1.45
    h = 22 + line_h * len(lines) + 8
    c.setFillColor(INK)
    c.roundRect(x, top - h, w, h, 8, fill=1, stroke=0)
    for i, dot in enumerate((CORAL, YELLOW, TEAL)):
        c.setFillColor(dot)
        c.circle(x + 12 + i * 11, top - 11, 3.3, fill=1, stroke=0)
    if title:
        c.setFillColor(SOFT)
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
            color: Color = TEAL, title: str = "À retenir",
            size: float = 9.4) -> float:
    st = style(size, "Body", INK, size * 1.4)
    ph = para_height(text, w - 34, st)
    h = ph + 32
    c.setFillColor(TINTS[color])
    c.roundRect(x, top - h, w, h, 8, fill=1, stroke=0)
    c.setFillColor(color)
    c.roundRect(x, top - h, 6, h, 3, fill=1, stroke=0)
    c.setFillColor(INK if color == YELLOW else color)
    c.setFont(F["Head"], 10.5)
    c.drawString(x + 18, top - 16, title.upper())
    para(c, text, x + 18, top - 23, w - 34, st)
    return top - h


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
    reader = ImageReader(str(path))
    iw, ih = reader.getSize()
    h = w * ih / iw
    c.drawImage(reader, x, top - h, w, h, mask="auto")
    return top - h


def check_mark(c: Canvas, x: float, y: float, color: Color = TEAL) -> None:
    c.setFillColor(color)
    c.circle(x, y, 7, fill=1, stroke=0)
    c.setStrokeColor(white if color != YELLOW else INK)
    c.setLineWidth(1.8)
    path = c.beginPath()
    path.moveTo(x - 3.2, y + 0.2)
    path.lineTo(x - 0.8, y - 2.6)
    path.lineTo(x + 3.6, y + 2.8)
    c.drawPath(path, stroke=1, fill=0)


def requirements(c: Canvas, items: list[str], top: float,
                 color: Color) -> float:
    """Encadré « ce que demande l'énoncé », avec une coche par exigence."""
    st = style(9.3, leading=12.4)
    width = W - 2 * M - 46
    heights = [para_height(item, width, st) for item in items]
    h = 30 + sum(heights) + 6 * len(items)
    c.setFillColor(white)
    c.setStrokeColor(TINTS[color] if color != YELLOW else YELLOW)
    c.setLineWidth(1.4)
    c.roundRect(M, top - h, W - 2 * M, h, 8, fill=1, stroke=1)
    c.setFillColor(MUTED)
    c.setFont(F["Head"], 10)
    c.drawString(M + 14, top - 16, "CE QUE DEMANDE L'ÉNONCÉ")
    y = top - 26
    for item, ph in zip(items, heights):
        check_mark(c, M + 22, y - 6.5, color)
        para(c, item, M + 36, y, width, st)
        y -= ph + 6
    return top - h - 14


def steps(c: Canvas, items: list[tuple[str, str]], top: float,
          color: Color, x: float = M, width: float = W - 2 * M) -> float:
    """Points à présenter, numérotés dans l'ordre où on les dit."""
    st = style(10.4, leading=14.4)
    y = top
    for i, (lead, text) in enumerate(items, start=1):
        c.setFillColor(color)
        c.circle(x + 12, y - 11, 12, fill=1, stroke=0)
        c.setFillColor(INK if color == YELLOW else white)
        c.setFont(F["Head"], 13)
        c.drawCentredString(x + 12, y - 15.6, str(i))
        bottom = para(c, f"<b>{lead}</b> — {text}", x + 33, y - 1,
                      width - 33, st)
        y = min(bottom, y - 24) - 10
    return y - 4


def questions(c: Canvas, items: list[tuple[str, str]], top: float,
              color: Color, x: float = M,
              width: float = W - 2 * M) -> float:
    """Encadré « questions probables du jury » avec les réponses."""
    st_q = style(9.4, "Bold", INK, 12.4)
    st_a = style(9.0, color=MUTED, leading=12.2)
    inner = width - 50
    blocks = [(para_height(q, inner, st_q), para_height(a, inner, st_a))
              for q, a in items]
    h = 32 + sum(hq + ha + 9 for hq, ha in blocks)
    c.setFillColor(INK)
    c.roundRect(x, top - h, width, h, 10, fill=1, stroke=0)
    c.setFillColor(color)
    c.setFont(F["Head"], 11)
    c.drawString(x + 16, top - 18, adapt("QUESTIONS PROBABLES DU JURY"))
    y = top - 30
    for (question, answer), (hq, ha) in zip(items, blocks):
        c.setFillColor(color)
        c.roundRect(x + 14, y - 13, 20, 14, 4, fill=1, stroke=0)
        c.setFillColor(INK if color == YELLOW else white)
        c.setFont(F["Head"], 9)
        c.drawCentredString(x + 24, y - 9.5, "?" if PROF else "Q")
        para(c, question, x + 42, y, inner, style(9.4, "Bold", white, 12.4))
        para(c, answer, x + 42, y - hq - 1, inner,
             style(9.0, color=HexColor("#C9CCE6"), leading=12.2))
        y -= hq + ha + 9
    return top - h - 12


def transition(c: Canvas, text: str, color: Color) -> None:
    """Bandeau du bas : la phrase qui fait le lien avec la partie suivante.

    Uniquement dans le support d'oral : c'est une aide pour l'orateur.
    """
    if PROF:
        return
    c.setFillColor(TINTS[color])
    c.roundRect(M, 44, W - 2 * M, 30, 15, fill=1, stroke=0)
    c.setFillColor(color if color != YELLOW else INK)
    c.setFont(F["Head"], 10)
    c.drawString(M + 14, 55, "TRANSITION")
    c.setFillColor(INK)
    c.setFont(F["Body"], 9.2)
    c.drawString(M + 92, 55, text)


# ----------------------------------------------------------- graphiques
def _clean_axes(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=8.5, length=0)
    ax.set_facecolor("none")


def _save(fig, path: Path) -> Path:
    fig.savefig(path, dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def chart_timeline(stats: dict[str, Any], path: Path) -> Path:
    timeline = stats["chronologie_par_heure"]
    errors = stats["erreurs_par_heure"]
    hours = [datetime.fromisoformat(h) for h in timeline]
    volume = list(timeline.values())
    err = [errors.get(h, 0) for h in timeline]
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(10, 4.2), sharex=True,
        gridspec_kw={"height_ratios": [1, 1.15], "hspace": 0.3})
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
    return _save(fig, path)


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
    fig, ax = plt.subplots(figsize=(5.0, 3.9))
    ax.barh([t[0] for t in items], [t[1] for t in items],
            color=[t[2] for t in items], height=0.62)
    for y, (_, value, _) in enumerate(items):
        ax.text(value, y, f"  {fr(value)}", va="center", fontsize=8,
                color=HEX["ink"])
    _clean_axes(ax)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.margins(x=0.25)
    handles = [plt.Rectangle((0, 0), 1, 1, color=HEX["orange"]),
               plt.Rectangle((0, 0), 1, 1, color=HEX["coral"])]
    ax.legend(handles, ["supprimé avant parsing", "rejeté après contrôle"],
              loc="lower right", frameon=False, fontsize=8)
    return _save(fig, path)


def chart_alerts(alerts: dict[str, int], path: Path) -> Path:
    critical = {"elevation_privileges", "exfiltration_donnees"}
    items = sorted(alerts.items(), key=lambda kv: kv[1])
    names = [k.replace("_", " ") for k, _ in items]
    values = [v for _, v in items]
    colors = [HEX["coral"] if k in critical else HEX["orange"]
              for k, _ in items]
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
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
    return _save(fig, path)


def chart_memory(path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
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
    return _save(fig, path)


def chart_pipeline(path: Path) -> Path:
    """Schéma du pipeline en "serpentin", coloré par module."""
    m1, m2, m3, m4 = HEX["teal"], HEX["orange"], HEX["yellow"], HEX["coral"]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(-0.95, 4.0)
    ax.axis("off")

    def box(x: float, y: float, title: str, sub: str, color: str,
            w: float = 1.75) -> None:
        ink = HEX["ink"] if color == HEX["yellow"] else "white"
        ax.add_patch(FancyBboxPatch((x, y), w, 0.95,
                                    boxstyle="round,pad=0.02,rounding_size="
                                    "0.16", fc=color, ec="none"))
        ax.text(x + w / 2, y + 0.6, title, ha="center", color=ink,
                fontsize=9.5, fontweight="bold", family="monospace")
        ax.text(x + w / 2, y + 0.25, sub, ha="center", color=ink,
                fontsize=8)

    def arrow(a: tuple[float, float], b: tuple[float, float]) -> None:
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>",
                                     mutation_scale=13, lw=1.6,
                                     color=HEX["muted"]))

    top = [("12 Go .log", "fichiers", HEX["muted"]),
           ("yield from", "lecture", m1),
           ("map(clean)", "nettoyage", m2),
           ("filter(keep)", "lignes vides...", m2),
           ("match-case", "str -> dict", m2)]
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
    return _save(fig, path)


# ---------------------------------------------------------------- pages
def page_cover(c: Canvas, report: dict[str, Any]) -> None:
    c.setFillColor(INK)
    c.rect(0, 0, W, H, fill=1, stroke=0)
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
    for i in range(70):                  # de vraies lignes de logs en fond
        c.setFillColor(Color(1, 1, 1, alpha=0.05 + 0.03 * (i % 3 == 0)))
        c.drawString(-30 + (i * 37) % 90, H - 14 - i * 12,
                     sample[i % len(sample)] * 2)
    c.setFillColor(ORANGE)
    c.rect(M, H - 300, 8, 150, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.setFont(F["Semi"], 11)
    c.drawString(M + 24, H - 162,
                 adapt("PROJET FINAL · PYTHON AVANCÉ · ING3"))
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
    # plan de la présentation : un module = une couleur
    c.setFillColor(YELLOW)
    c.setFont(F["Head"], 13)
    c.drawString(M, H - 520, adapt("AU PROGRAMME"))
    plan = [(1, "Ingestion & générateurs"), (2, "Pipeline fonctionnel"),
            (3, "Agrégation & détection"), (4, "Règles & introspection")]
    for i, (number, name) in enumerate(plan):
        x = M + i * (w + gap)
        color = MODULE_COLORS[number]
        c.setFillColor(color)
        c.circle(x + 12, H - 548, 12, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont(F["Head"], 13)
        c.drawCentredString(x + 12, H - 552.5, str(number))
        c.setFillColor(white)
        c.setFont(F["Semi"], 9.5)
        c.drawString(x + 30, H - 545, f"Module {number}")
        c.setFillColor(HexColor("#C9CCE6"))
        c.setFont(F["Body"], 8.5)
        c.drawString(x + 30, H - 557, name)
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
    c.drawString(M, 74, f"Soutenance · {SOUTENANCE_DATE}")
    for i, color in enumerate((ORANGE, YELLOW, TEAL, CORAL)):
        c.setFillColor(color)
        c.rect(i * W / 4, 0, W / 4, 8, fill=1, stroke=0)


def page_overview(c: Canvas, report: dict[str, Any], figures: Path) -> None:
    top = header(c, "0", "Le projet en bref",
                 "Le sujet, nos données et le chemin d'une ligne de log",
                 YELLOW, "Ouverture")
    run, stats = report["execution"], report["statistiques"]
    top = para(c, "<b>Le sujet</b> — une plateforme en ligne de commande qui "
               "<b>ingère, nettoie et analyse</b> des journaux de logs "
               "volumineux <b>sans jamais les charger entièrement en "
               "mémoire</b>. Pour l'éprouver, notre générateur simule 30 "
               "jours d'activité d'un site e-commerce : 11 services, des "
               "pannes, un DDoS, des attaques, et ~5 % de lignes "
               "volontairement abîmées.", M, top, W - 2 * M,
               style(10.2, leading=14.2)) - 12
    top = kpi_row(c, top, [
        (TEAL, fr(run["taille_go"], 1) + " Go", "générés en 75 s par 7 "
         "processus"),
        (ORANGE, millions(report["nettoyage"]["lignes_lues"]),
         "lignes dans 12 fichiers"),
        (YELLOW, fr(stats["nb_ip_uniques"]), "adresses IP différentes"),
        (CORAL, fr(run["duree_s"] / 60, 0) + " min", "pour tout analyser, "
         "en une seule passe"),
    ])
    top = subtitle(c, "Trois formats de lignes bien structurés", M, top,
                   YELLOW)
    top = terminal(c, M, top, W - 2 * M, [
        ("# applicatif (80 %) : 7 champs séparés par |", SOFT),
        ("2026-10-01T08:15:32.481Z | INFO | api-gateway | 10.0.3.17:51432/"
         "TCP | user=u1042 | event=http_request | {...}", white),
        ("# JSON (10 %)", SOFT),
        ('{"ts":"2026-10-01T08:15:32Z","lvl":"error","svc":"payment-service",'
         '"client":{"ip":...},"code":502}', TINTS[TEAL]),
        ("# pare-feu (10 %) : champs positionnels", SOFT),
        ("FW 2026-10-01T00:20:12.423Z DROP TCP 102.109.77.236 27409 "
         "10.0.100.29 22 DENY-SSH-EXT", YELLOW),
    ], title="data/raw/logs-00-20261001-0000.log") - 14
    top = subtitle(c, "Le chemin d'une ligne : chaque couleur = un module",
                   M, top, YELLOW)
    image(c, chart_pipeline(figures / "s_pipeline.png"), M + 20, top - 2,
          W - 2 * M - 40)
    transition(c, "Tout commence par la lecture des fichiers, sans les "
               "charger en mémoire  →  Module 1", TEAL)
    footer(c, 2)


# ---------------------------------------------------------- module 1
def page_module1_a(c: Canvas) -> None:
    color = MODULE_COLORS[1]
    # (pas de guillemets échappés dans les {} d'une f-string en Python 3.11)
    replace_arg = code('errors="replace"')
    newline_arg = code('newline=""')
    carriage = code("\\r")
    top = header(c, "1", "Ingestion & générateurs",
                 "Lire 12 Go une ligne à la fois : yield, yield from, "
                 "parsing en dictionnaires", color, "Module 1 · ce qu'on "
                 "présente")
    top = requirements(c, [
        f"Un générateur basé sur {code('yield')} pour lire un fichier de "
        "logs ligne par ligne, à la demande.",
        f"Un sous-générateur qui lit plusieurs fichiers successifs avec "
        f"{code('yield from')}.",
        "Chaque ligne parsée en dictionnaire avec des types variés : "
        "horodatage, niveau, IP, utilisateur, payload JSON ou chaîne brute.",
        "Des tuples pour les métadonnées fixes : (IP, Port, Protocole).",
    ], top, color)
    top = subtitle(c, "Ce qu'on présente, dans l'ordre", M, top, color)
    top = steps(c, [
        ("Le problème", "12 Go et 69 millions de lignes ne tiennent pas en "
         f"mémoire. On ne lit donc jamais un fichier en entier : pas de "
         f"{code('read()')}, pas de {code('readlines()')}."),
        ("yield", f"{code('read_log_file')} renvoie une ligne puis se met en "
         "pause ; elle reprend au même endroit quand la boucle demande la "
         f"suivante. Le {code('with')} garde le fichier ouvert jusqu'au "
         "bout."),
        ("yield from", f"{code('read_sources')} enchaîne les 12 fichiers "
         "comme un seul flux ; un fichier manquant est signalé puis ignoré "
         f"({code('try / except')})."),
        ("Robustesse", f"{replace_arg} : un octet invalide ne fait pas "
         f"planter la lecture ; {newline_arg} garde les {carriage} pour "
         "qu'on les nettoie nous-mêmes."),
        ("Dictionnaire typé", "chaque ligne devient un "
         f"{code('LogRecord')} ({code('TypedDict')}) : {code('datetime')}, "
         "niveau, service, IP, utilisateur, payload JSON ou texte brut."),
        ("Tuple", f"la connexion est stockée dans le tuple immuable "
         f"{code('(IP, Port, Protocole)')} : on ne peut pas la modifier par "
         "erreur, et elle peut servir de clé (exploité au module 3)."),
    ], top, color)
    top = subtitle(c, "Le code à montrer (logengine/ingestion.py)", M, top,
                   color)
    terminal(c, M, top, W - 2 * M, [
        ("def read_log_file(path: Path) -> Iterator[str]:", white),
        ('    with open(path, encoding="utf-8", errors="replace", '
         'newline="") as file:', white),
        ("        for line in file:", white),
        ("            yield line          # pause : une seule ligne en "
         "mémoire", YELLOW),
        ("", white),
        ("def read_sources(paths: Iterable[Path]) -> Iterator[str]:", white),
        ("    for path in paths:", white),
        ("        try:", white),
        ("            yield from read_log_file(path)   # délègue au "
         "sous-générateur", YELLOW),
        ("        except (FileNotFoundError, PermissionError) as exc:",
         white),
        ('            print(f"fichier ignoré : {path}", file=sys.stderr)',
         SOFT),
    ], size=8, title="ingestion.py")
    footer(c, 3)


def page_module1_b(c: Canvas, report: dict[str, Any], figures: Path,
                   audit: dict[str, Any] | None) -> None:
    color = MODULE_COLORS[1]
    records_size = next((row["taille_octets"] for row in
                         (audit or {}).get("locales", [])
                         if row["nom"] == "records"), None)
    top = header(c, "1", "Ingestion : ce que ça donne",
                 "La preuve par la mémoire, et le bonus temps réel",
                 color, "Module 1 · résultats")
    run = report["execution"]
    top = kpi_row(c, top, [
        (TEAL, millions(report["nettoyage"]["lignes_lues"]), "lignes lues "
         "une à une"),
        (INK, fr(run["lignes_par_seconde"]), "lignes par seconde"),
        (YELLOW, fr(MEMORY_MEASURES[-1][1], 1) + " Mo", "de pic mémoire "
         "pour 2 M de lignes"),
        (ORANGE, f"{records_size} o" if records_size else "—",
         f"taille de l'objet {code('records')} (audit)"),
    ])
    col = (W - 2 * M - 16) * 0.5
    left_top = subtitle(c, "La mémoire ne suit pas le volume", M, top,
                        color)
    image(c, chart_memory(figures / "s_memory.png"), M + 10, left_top,
          col - 30)
    right = M + col + 16
    rt = subtitle(c, "Bonus : le temps réel", right, top, color)
    rt = terminal(c, right, rt, W - M - right, [
        ("while time.monotonic() < deadline:", white),
        ("    chunk = file.readline()", white),
        ("    if not chunk:               # rien de neuf", SOFT),
        ("        time.sleep(0.2)", white),
        ("        continue", TEAL),
        ("    pending += chunk", white),
        ('    if not pending.endswith("\\n"):', white),
        ("        continue                # ligne incomplète", SOFT),
        ("    yield pending", YELLOW),
        ('    pending = ""', white),
    ], size=7.7, title="follow_log_file (tail -f)") - 6
    para(c, f"Générateur <b>infini</b> : il attend au lieu de s'arrêter. "
         f"{code('python main.py live')} l'utilise avec <b>le même "
         "pipeline</b> que les fichiers.", right, rt, W - M - right,
         style(9, leading=12.4))
    top = min(left_top - 175, rt - 52)
    top = questions(c, [
        ("Pourquoi un générateur plutôt qu'une liste ?",
         "Une liste garde tous les éléments en mémoire en même temps : 12 Go "
         "feraient planter le programme. Le générateur produit une ligne à "
         "la demande, puis l'oublie."),
        ("Quelle différence entre yield et return ?",
         "return termine la fonction. yield la met en pause en gardant son "
         "état : elle reprend juste après, à l'appel suivant."),
        ("Et si on écrivait list(records) ?",
         "Toutes les lignes seraient chargées en RAM. Et un générateur ne se "
         "parcourt qu'une fois : une deuxième boucle ne trouverait rien."),
        ("Comment prouvez-vous que la RAM ne sature pas ?",
         f"Avec tracemalloc : {fr(MEMORY_MEASURES[0][1], 1)} Mo pour "
         f"{fr(MEMORY_MEASURES[0][0])} lignes, "
         f"{fr(MEMORY_MEASURES[1][1], 1)} Mo pour 2 M : sept fois plus de "
         "données, à peine 1,5 fois plus de mémoire."),
        ("Pourquoi un tuple pour la connexion ?",
         "Immuable, donc protégé ; hashable, donc utilisable comme clé de "
         "dictionnaire ou dans un set (une liste ne l'est pas)."),
    ], top, color)
    transition(c, "Les lignes arrivent une par une : il faut maintenant les "
               "nettoyer et les comprendre  →  Module 2", ORANGE)
    footer(c, 4)


# ---------------------------------------------------------- module 2
def page_module2_a(c: Canvas) -> None:
    color = MODULE_COLORS[2]
    fw_pattern = code('"FW", …, *rule')
    warn_case = code('case "WARN" | "WRN"')
    top = header(c, "2", "Pipeline fonctionnel",
                 "filter, map, lambda et match-case : nettoyer et "
                 "structurer chaque ligne", color, "Module 2 · ce qu'on "
                 "présente")
    top = requirements(c, [
        f"{code('filter()')} avec des {code('lambda')} pour exclure les "
        f"requêtes invalides et les entrées vides ({code('filter(None, …)')} "
        "ou prédicats).",
        f"{code('map()')} pour appliquer une fonction de normalisation à "
        "chaque enregistrement (chaînes, casse, formats).",
        f"Le {code('match-case')} au lieu des {code('if-elif-else')} pour "
        "router selon le format : chaîne brute, dictionnaire, tuple de "
        "connexion.",
    ], top, color)
    top = subtitle(c, "Ce qu'on présente, dans l'ordre", M, top, color)
    top = steps(c, [
        ("Une chaîne construite sans rien lire", f"chaque {code('map')} / "
         f"{code('filter')} enveloppe l'itérateur précédent ; rien ne "
         f"circule avant la boucle {code('for')}."),
        ("map(clean_raw_line)", "retire espaces, \\r, codes couleur et "
         f"caractères invisibles ; {code('isprintable()')} évite ce travail "
         "sur les 95 % de lignes déjà propres."),
        ("filter et ses prédicats", f"{code('filter(tracker.keep_line)')} "
         "supprime vides, commentaires et stack traces <b>en comptant la "
         f"cause</b> ; {code('filter(None, …)')} vide la liste noire de ses "
         f"lignes vides ; une {code('lambda')} filtre par niveau."),
        ("match-case", f"{code('parse_line')} reconnaît la <b>forme</b> : un "
         f"dict JSON (motif imbriqué), un tuple pare-feu ({fw_pattern}), "
         "sinon une chaîne applicative."),
        ("map(normalize_record)", f"niveaux ({warn_case}), utilisateurs "
         "(regex), 5 formats de dates, IP validées, JSON et encodage "
         "réparés."),
        ("filter(tracker.accept)", "écarte seulement l'inexploitable (IP ou "
         "date impossible, ligne tronquée) et note la raison."),
    ], top, color)
    top = subtitle(c, "Le code à montrer (parsing.py + main.py)", M, top,
                   color)
    terminal(c, M, top, W - 2 * M, [
        ("match decode_line(line):", white),
        ('    case {"ts": ts, "lvl": str(level), "svc": str(service),',
         YELLOW),
        ('          "client": {"ip": ip, "port": port, "proto": proto}, '
         '**rest}:', YELLOW),
        ("        ...                                 # dictionnaire JSON",
         SOFT),
        ('    case ("FW", ts, action, proto, src_ip, src_port, dst_ip, '
         'dst_port, *rule):', TINTS[TEAL]),
        ("        ...                                 # tuple pare-feu",
         SOFT),
        ("    case str() as text:", white),
        ("        return _parse_app_line(text)        # chaîne brute", SOFT),
        ("", white),
        ("records = map(normalize_record, map(parse_line, lines))", white),
        ("records = filter(tracker.accept, records)", white),
        ('records = filter(lambda r: LEVEL_RANK[r["level"]] >= min_rank, '
         'records)', white),
    ], size=7.7, title="parsing.py · main.py")
    footer(c, 5)


def page_module2_b(c: Canvas, report: dict[str, Any], figures: Path) -> None:
    color = MODULE_COLORS[2]
    top = header(c, "2", "Nettoyage : ce que ça donne",
                 "Réparer tout ce qui peut l'être, écarter le reste, et "
                 "compter chaque décision", color, "Module 2 · résultats")
    clean = report["nettoyage"]
    fixes = sum(clean["corrections"].values())
    top = kpi_row(c, top, [
        (TEAL, millions(clean["enregistrements_valides"]), "enregistrements "
         "valides"),
        (YELLOW, millions(fixes), "corrections : lignes sauvées"),
        (ORANGE, millions(clean["lignes_supprimees"]
                          + clean["enregistrements_rejetes"]),
         "lignes écartées"),
        (CORAL, fr(clean["taux_de_rejet_pct"], 1) + " %", "seulement de "
         "pertes"),
    ])
    dirty = ("01/10/2026 08:15:32 | err | API_GATEWAY | 88.12.34.56:51432 "
             "| user=USER_7 | event=http_request | "
             "{'status':'500','latency_ms':-1}")
    cut = dirty.index("{")
    top = subtitle(c, "Avant / après : une vraie ligne passée dans notre "
                   "code", M, top, color)
    top = terminal(c, M, top, W - 2 * M, [
        (dirty[:cut], CORAL), ("    " + dirty[cut:], CORAL)],
        size=7.6, title="entrée sale") - 4
    rec = normalize_record(parse_line(dirty))
    rows = [("timestamp", f"{rec['timestamp']}", "date réécrite en ISO, UTC"),
            ("level", rec["level"], "« err » normalisé (match-case)"),
            ("service", rec["service"], "casse et « _ » corrigés"),
            ("connection", str(rec["connection"]), "tuple, TCP par défaut"),
            ("user", str(rec["user"]), "« USER_7 » ramené à « u7 »"),
            ("payload", str(rec["payload"]), "guillemets et latence "
             "corrigés")]
    box_h = 16 * len(rows) + 14
    c.setFillColor(TINTS[TEAL])
    c.roundRect(M, top - box_h, W - 2 * M, box_h, 8, fill=1, stroke=0)
    y = top - 17
    for key, value, why in rows:
        c.setFillColor(TEAL)
        c.setFont(F["MonoB"], 8.4)
        c.drawString(M + 14, y, key)
        c.setFillColor(INK)
        c.setFont(F["Mono"], 8.4)
        c.drawString(M + 92, y, value[:46])
        c.setFillColor(MUTED)
        c.setFont(F["Body"], 8.4)
        c.drawString(M + 345, y, why)
        y -= 16
    top -= box_h + 12
    col = (W - 2 * M - 14) * 0.43
    image(c, chart_cleaning(clean, figures / "s_cleaning.png"), M, top,
          col)
    questions(c, [
        ("Pourquoi match-case plutôt que if / elif ?",
         "On décrit la forme attendue (clés, longueur, types) et on capture "
         "les valeurs en même temps, au lieu d'enchaîner isinstance, len et "
         "des extractions à la main."),
        ("À quoi sert filter(None, …) ?",
         "Il ne garde que les éléments « vrais » : les chaînes vides "
         "disparaissent."),
        ("Pourquoi passer une méthode à filter ?",
         "Une fonction est un objet : tracker.accept décide de garder la "
         "ligne ET compte la cause du rejet."),
        ("Réparer ou rejeter, comment décidez-vous ?",
         "Récupérable (casse, format) : on corrige. Impossible (IP 999.x, "
         "13e mois) : on rejette et on note pourquoi."),
    ], top, color, x=M + col + 14, width=W - 2 * M - col - 14)
    transition(c, "Les données sont propres et typées : on peut les compter "
               "et y chercher des attaques  →  Module 3", YELLOW)
    footer(c, 6)


# ---------------------------------------------------------- module 3
def page_module3_a(c: Canvas, report: dict[str, Any]) -> None:
    color = MODULE_COLORS[3]
    flows_code = code("blocked_flows[(ip, port, proto)] += 1")
    top = header(c, "3", "Agrégation & détection",
                 "set, frozenset, defaultdict, et une boucle qui démasque "
                 "la force brute", color, "Module 3 · ce qu'on présente")
    top = requirements(c, [
        f"Un {code('set')} des IP uniques ayant généré des erreurs.",
        f"Les opérations {code('| & - ^')} entre la liste noire "
        f"({code('frozenset')} immuable) et les IP actives.",
        f"{code('defaultdict')} pour compter par catégorie ou par "
        f"utilisateur sans {code('KeyError')}.",
        f"Une détection de force brute combinant {code('while')} et "
        f"{code('for')}, avec {code('break')}, {code('continue')} et la "
        f"clause {code('else')} des boucles.",
    ], top, color)
    top = subtitle(c, "Ce qu'on présente, dans l'ordre", M, top, color)
    top = steps(c, [
        ("Une seule passe", f"pour chaque ligne, {code('stats.update')} met "
         "à jour des compteurs : on ne garde jamais les lignes elles-mêmes."),
        ("defaultdict", f"{code('compteur[cle] += 1')} crée le 0 tout seul, "
         "donc jamais de KeyError ; version imbriquée service → niveau, et "
         f"{code('defaultdict(set)')} IP → ports."),
        ("set et frozenset", f"{code('error_ips.add(ip)')} ignore les "
         "doublons : on obtient directement les IP uniques. La liste noire "
         "est un frozenset : personne ne peut la modifier pendant "
         "l'analyse."),
        ("Le tuple comme clé", f"{flows_code} compte les flux bloqués ; "
         "regroupés par IP, ils révèlent les scans de ports."),
        ("Force brute", f"une {code('deque')} garde les échecs des 2 "
         f"dernières minutes par IP ; un {code('while')} retire les trop "
         f"anciens ; à la fin, une boucle {code('for')} tranche (code "
         "ci-dessous)."),
    ], top, color)
    col = (W - 2 * M - 16) / 2
    left = subtitle(c, "Le code à montrer (detection.py)", M, top, color)
    terminal(c, M, left, col + 30, [
        ("for moment, user, ok in suspect_events:", white),
        ("    if not ok:", white),
        ("        consecutive += 1", white),
        ("        continue           # échec suivant", TEAL),
        ("    if consecutive >= 5 and récent:", white),
        ("        compromis = user", white),
        ("        break              # attaque réussie", CORAL),
        ("    consecutive = 0", white),
        ("else:", YELLOW),
        ('    statut = "bloquée"     # aucun break', YELLOW),
    ], size=7.9, title="summarize()")
    right = M + col + 46
    rt = subtitle(c, "Les opérations d'ensembles", right, top, color)
    ips = report["ensembles_ip"]
    rows = [("actives | bl", "toutes les IP connues",
             ips["union_actives_blacklist"]),
            ("actives & bl", "listées et actives", ips["blacklist_actives"]),
            ("erreurs & bl", "listées, en erreur",
             ips["blacklist_en_erreur"]),
            ("actives - bl", "actives non listées",
             ips["actives_non_listees"]),
            ("bl - actives", "listées jamais vues",
             ips["blacklist_dormantes"]),
            ("actives ^ bl", "dans l'un OU l'autre",
             ips["difference_symetrique"])]
    y = rt - 4
    for i, (op, meaning, value) in enumerate(rows):
        if i % 2 == 0:
            c.setFillColor(TINTS[YELLOW])
            c.rect(right, y - 18, W - M - right, 20, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont(F["MonoB"], 8.6)
        c.drawString(right + 6, y - 12, op)
        c.setFont(F["Body"], 8.6)
        c.setFillColor(MUTED)
        c.drawString(right + 82, y - 12, meaning)
        c.setFillColor(INK)
        c.setFont(F["Head"], 10)
        c.drawRightString(W - M - 6, y - 12.5, fr(value))
        y -= 20
    footer(c, 7)


def page_module3_b(c: Canvas, report: dict[str, Any], figures: Path) -> None:
    color = MODULE_COLORS[3]
    top = header(c, "3", "Agrégation : ce que ça donne",
                 "68 millions de lignes résumées en quelques compteurs",
                 color, "Module 3 · résultats")
    stats, ips = report["statistiques"], report["ensembles_ip"]
    brute, alerts = report["force_brute"], report["alertes_par_regle"]
    top = image(c, chart_timeline(stats, figures / "s_timeline.png"), M, top,
                W - 2 * M) - 10
    top = kpi_row(c, top, [
        (CORAL, fr(ips["blacklist_actives"]), f"IP en liste noire actives "
         f"sur {fr(ips['taille_blacklist'])}"),
        (ORANGE, fr(len(stats["scans_de_ports"])), "scanners (15 ports "
         "visés ou plus)"),
        (YELLOW, fr(brute["nb_incidents"]), "IP en force brute"),
        (TEAL, fr(brute["nb_comptes_compromis"]), f"ont réussi, confirmé "
         f"par {fr(alerts.get('elevation_privileges', 0))} élévations"),
    ])
    questions(c, [
        ("Pourquoi un frozenset pour la liste noire ?",
         "Elle ne doit pas changer pendant l'analyse ; un frozenset ne peut "
         "pas être modifié, et le test « ip in blacklist » reste "
         "instantané."),
        ("Set ou defaultdict, quelle différence ?",
         "Le set répond à « quelles IP ? » (unicité), le defaultdict à "
         "« combien de fois ? » (comptage)."),
        ("À quoi sert le else d'une boucle for ?",
         "Il s'exécute seulement si la boucle va au bout sans break : "
         "aucune connexion n'a réussi, l'attaque a échoué."),
        ("Pourquoi une deque pour la fenêtre ?",
         "On ajoute à droite et on retire à gauche en temps constant : "
         "c'est fait pour une fenêtre glissante."),
        ("Pourquoi 60 attaquants mais 48 réussites ?",
         "Les incidents sont regroupés par IP sur les 30 jours ; les "
         "élévations de privilèges confirment indépendamment les "
         "connexions réussies."),
    ], top, color)
    transition(c, "On sait compter et détecter : reste à rendre la sécurité "
               "configurable et observable  →  Module 4", CORAL)
    footer(c, 8)


# ---------------------------------------------------------- module 4
def page_module4_a(c: Canvas) -> None:
    color = MODULE_COLORS[4]
    top = header(c, "4", "Règles & introspection",
                 "apply_security_rules(*args, **kwargs), des fonctions "
                 "comme objets, et globals() / locals()", color,
                 "Module 4 · ce qu'on présente")
    top = requirements(c, [
        f"Une fonction maître {code('apply_security_rules(*args, **kwargs)')}"
        " : un nombre variable de fonctions de sécurité en "
        f"{code('*args')}, une configuration dynamique en "
        f"{code('**kwargs')}.",
        "Les fonctions manipulées comme des objets de première classe "
        "(passées en argument à d'autres fonctions).",
        f"Un audit qui inspecte l'exécution avec {code('globals()')} et "
        f"{code('locals()')} et exporte un rapport des variables.",
    ], top, color)
    top = subtitle(c, "Ce qu'on présente, dans l'ordre", M, top, color)
    top = steps(c, [
        ("Une règle = une fonction", f"{code('rule(record, **config)')} "
         "renvoie une alerte ou None. Nous en avons 9 : injection SQL, XSS, "
         "liste noire, port exposé…"),
        ("*args et **kwargs", f"{code('*args')} regroupe les règles dans un "
         f"<b>tuple</b>, {code('**kwargs')} la configuration dans un "
         f"<b>dict</b> ; à l'appel, {code('*DEFAULT_RULES')} « déballe » le "
         "tuple."),
        ("Une fonction qui renvoie une fonction", "on prépare le moteur une "
         f"seule fois ({code('filter')} + {code('lambda')} retire les règles "
         f"désactivées) et on récupère {code('check(record)')}, appelée sur "
         "chaque ligne. C'est une <b>fermeture</b>."),
        ("Robustesse", "une règle qui plante est isolée par "
         f"{code('try / except / else')} ; un argument qui n'est pas une "
         f"fonction lève {code('TypeError')}."),
        ("Introspection", f"{code('main.py')} appelle "
         f"{code('export_audit_report(path, globals(), locals())')} : chaque "
         "variable est décrite (type, taille, aperçu) dans audit.json."),
    ], top, color)
    top = subtitle(c, "Le code à montrer (logengine/rules.py)", M, top,
                   color)
    terminal(c, M, top, W - 2 * M, [
        ("def apply_security_rules(*args: Rule, **kwargs: Any) -> "
         "RuleChecker:", white),
        ("    for rule in args:", white),
        ("        if not callable(rule):", white),
        ('            raise TypeError("une règle doit être une fonction")',
         SOFT),
        ('    disabled = kwargs.get("disabled", ())', white),
        ("    active = tuple(filter(lambda rule: rule.__name__ not in "
         "disabled, args))", YELLOW),
        ("", white),
        ("    def check(record: LogRecord) -> list[Alert]:", TINTS[TEAL]),
        ("        alerts = []", white),
        ("        for rule in active:", white),
        ("            try:", white),
        ("                alert = rule(record, **kwargs)    # on "
         "retransmet **kwargs", YELLOW),
        ("            except Exception as exc:", white),
        ('                print(f"{rule.__name__} a échoué")', SOFT),
        ("            else:", white),
        ("                if alert is not None: alerts.append(alert)",
         white),
        ("        return alerts", white),
        ("    return check                                   # la fonction "
         "elle-même", CORAL),
    ], size=7.6, title="rules.py")
    footer(c, 9)


def page_module4_b(c: Canvas, report: dict[str, Any], figures: Path,
                   audit: dict[str, Any] | None) -> None:
    color = MODULE_COLORS[4]
    top = header(c, "4", "Règles : ce que ça donne",
                 "Des alertes sur 12 Go, un audit de l'exécution, et la "
                 "démo en direct", color, "Module 4 · résultats")
    alerts = report["alertes_par_regle"]
    col = (W - 2 * M - 16) * 0.5
    left = subtitle(c, f"{fr(sum(alerts.values()))} alertes par règle", M,
                    top, color)
    left = image(c, chart_alerts(alerts, figures / "s_alerts.png"), M, left,
                 col)
    right = M + col + 16
    rt = subtitle(c, "Extrait d'audit.json (locals())", right, top, color)
    if audit:
        wanted = ("check_rules", "blacklist", "stats", "records")
        rows = [r for r in audit["locales"] if r["nom"] in wanted]
        for i, row in enumerate(rows):
            if i % 2 == 0:
                c.setFillColor(TINTS[CORAL])
                c.rect(right, rt - 30, W - M - right, 30, fill=1, stroke=0)
            c.setFillColor(INK)
            c.setFont(F["MonoB"], 8.5)
            c.drawString(right + 6, rt - 12, row["nom"])
            c.setFillColor(MUTED)
            c.setFont(F["Body"], 8.2)
            c.drawRightString(W - M - 6, rt - 12,
                              f"{row['type']} · {fr(row['taille_octets'])} "
                              "octets")
            c.setFont(F["Mono"], 7)
            c.drawString(right + 6, rt - 24, row["apercu"][:52])
            rt -= 30
    rt = para(c, f"{code('records')} ne pèse que quelques dizaines "
              "d'octets : c'est un itérateur, il ne contient pas les "
              "données.", right, rt - 6, W - M - right,
              style(8.6, color=MUTED, leading=11.6)) - 10
    rt = terminal(c, right, rt, W - M - right, [
        ("$ python main.py live", white),
        ("[live] 2,357 lignes lues, 7 alertes", SOFT),
        ("[HIGH] xss  217.135.14.178 javascript:..", CORAL),
        ("[FORCE BRUTE] 92.112.165.218 : 5 échecs", YELLOW),
    ], size=7.4, title="démo temps réel")
    top = min(left, rt) - 10
    questions(c, [
        ("Quelle différence entre *args et **kwargs ?",
         "*args rassemble les arguments positionnels dans un tuple, "
         "**kwargs les arguments nommés dans un dict."),
        ("Pourquoi apply_security_rules renvoie-t-elle une fonction ?",
         "*args ne contient que des règles, pas la ligne à analyser : on "
         "prépare le moteur une fois, puis check(record) tourne sur "
         "69 M de lignes."),
        ("Qu'est-ce qu'une fermeture (closure) ?",
         "Une fonction interne qui garde accès aux variables de la fonction "
         "qui l'a créée (ici active et kwargs), même après sa fin."),
        ("Pourquoi globals() / locals() sont-ils appelés dans main.py ?",
         "Appelés dans audit.py, ils décriraient le module d'audit, pas le "
         "programme qu'on veut inspecter."),
        ("Comment ajouter une nouvelle règle ?",
         "Écrire def rule_x(record, **config) et l'ajouter à DEFAULT_RULES. "
         "Rien d'autre à changer."),
    ], top, color)
    transition(c, "Le moteur est complet : place au bilan qualité et à la "
               "démonstration  →  Conclusion", INK)
    footer(c, 10)


# ---------------------------------------------------------- clôture
def page_closing(c: Canvas, report: dict[str, Any]) -> None:
    top = header(c, "5", "Qualité, barème et démo",
                 "Chaque critère du barème et l'endroit où le montrer",
                 YELLOW, "Conclusion")
    rows = [("Environnement & livrables", "2", "venv, requirements.txt "
             "(dépendances directes), scripts .py uniquement, rapport PDF, "
             "Git", INK),
            ("Mémoire & générateurs", "4", "yield, yield from, "
             "follow_log_file · ~19 Mo pour 2 M de lignes", TEAL),
            ("Structures de données", "4", "set, frozenset, defaultdict, "
             "tuple clé de dict, match-case", ORANGE),
            ("Programmation fonctionnelle", "4", "map, filter, lambda, "
             "méthodes passées à filter, fonction renvoyée", ORANGE),
            ("Règles & introspection", "3", "apply_security_rules(*args, "
             "**kwargs), globals() / locals()", CORAL),
            ("Qualité & robustesse", "3", f"PEP 8, mypy 0 erreur, "
             f"{TESTS_COUNT} tests, try/except/else, for-else", YELLOW)]
    for name, points, where, color in rows:
        c.setFillColor(TINTS[color])
        c.roundRect(M, top - 42, W - 2 * M, 42, 8, fill=1, stroke=0)
        c.setFillColor(color)
        c.roundRect(M, top - 42, 6, 42, 3, fill=1, stroke=0)
        check_mark(c, M + 24, top - 21, color)
        c.setFillColor(INK)
        c.setFont(F["Head"], 12)
        c.drawString(M + 40, top - 18, name)
        c.setFillColor(MUTED)
        c.setFont(F["Body"], 8.5)
        c.drawString(M + 40, top - 32, where)
        c.setFillColor(INK if color == YELLOW else color)
        c.setFont(F["Head"], 17)
        c.drawRightString(W - M - 14, top - 27, f"{points} pts")
        top -= 49
    top -= 4
    top = kpi_row(c, top, [
        (TEAL, str(TESTS_COUNT), "tests pytest, tous verts"),
        (ORANGE, "0", "erreur mypy (code et tests)"),
        (YELLOW, "0", "écart PEP 8 (pycodestyle)"),
        (CORAL, "17 min", "pour analyser les 12 Go"),
    ])
    top = callout(c, M, top, W - 2 * M,
                  "Un moteur qui traite <b>12 Go de logs hétérogènes et "
                  "dégradés</b> avec quelques dizaines de mégaoctets de "
                  "mémoire, répare l'essentiel des défauts, retrouve les "
                  "incidents et les attaques injectés, et fonctionne aussi "
                  "<b>en temps réel</b>.", ORANGE, "En une phrase") - 10
    callout(c, M, top, W - 2 * M,
            "<b>Analyse parallèle</b> (un processus par fichier, puis fusion "
            "des compteurs) pour diviser le temps par 5 ou 6 ; "
            "<b>séparer les campagnes</b> d'une même IP attaquante ; "
            "<b>rattacher les stack traces</b> à la ligne d'erreur qui les "
            "précède.", TEAL, "Pour aller plus loin")
    c.setFillColor(INK)
    c.roundRect(M, 44, W - 2 * M, 50, 10, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.setFont(F["Head"], 13)
    label = adapt("DÉMO")
    c.drawString(M + 16, 72, label)
    text_x = M + 30 + pdfmetrics.stringWidth(label, F["Head"], 13)
    c.setFillColor(white)
    c.setFont(F["Mono"], 9)
    c.drawString(text_x, 72, "python main.py demo     python main.py live "
                 "    python -m pytest")
    c.setFillColor(HexColor("#C9CCE6"))
    c.setFont(F["Body"], 8.5)
    c.drawString(text_x, 56, "Code complet : " + GITHUB_URL)
    footer(c, 11)


def build(out: Path, report: dict[str, Any], audit: dict[str, Any] | None,
          figures: Path) -> None:
    """Dessine les 11 pages dans ``out`` (selon la valeur de PROF)."""
    c = Canvas(str(out), pagesize=A4)
    kind = "Rapport final" if PROF else "Support de soutenance"
    c.setTitle(f"{kind} — Engine d'analyse de logs")
    c.setAuthor(", ".join(TEAM))
    pages = [
        lambda: page_cover(c, report),
        lambda: page_overview(c, report, figures),
        lambda: page_module1_a(c),
        lambda: page_module1_b(c, report, figures, audit),
        lambda: page_module2_a(c),
        lambda: page_module2_b(c, report, figures),
        lambda: page_module3_a(c, report),
        lambda: page_module3_b(c, report, figures),
        lambda: page_module4_a(c),
        lambda: page_module4_b(c, report, figures, audit),
        lambda: page_closing(c, report),
    ]
    for index, draw in enumerate(pages):
        if index:
            c.showPage()
        draw()
    c.save()
    print(f"{kind} écrit : {out} ({len(pages)} pages)")


def main() -> None:
    global PROF
    parser = argparse.ArgumentParser(
        description="Support de soutenance et rapport final (PDF)")
    parser.add_argument("--results", type=Path, default=ROOT / "output")
    args = parser.parse_args()
    report = json.loads((args.results / "report.json").read_text("utf-8"))
    audit_path = args.results / "audit.json"
    audit = json.loads(audit_path.read_text("utf-8")) \
        if audit_path.exists() else None
    figures = HERE / "_figures"
    figures.mkdir(exist_ok=True)
    for prof, name in ((False, "Synthese_soutenance.pdf"),
                       (True, "Rapport_final.pdf")):
        PROF = prof
        build(HERE / name, report, audit, figures)


if __name__ == "__main__":
    main()
