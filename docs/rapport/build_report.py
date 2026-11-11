"""Construit le rapport final PDF à partir des résultats de l'analyse.

Utilisation (après ``python main.py analyze``) :
    python docs/rapport/build_report.py
    python docs/rapport/build_report.py --results output --out rapport.pdf

Les chiffres, tableaux et graphiques sont lus dans le dossier de résultats
(report.json, incidents.csv, audit.json, charts/*.png) : relancer le script
après une nouvelle analyse met tout le rapport à jour.
"""

import argparse
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# À COMPLÉTER PAR L'ÉQUIPE, puis relancer le script
TEAM = ["NAYME Yanis", "GUEYE Babacar Mansour", "CLABAU Brandon",
        "LYOUBI Mehdi"]
SCHOOL = "Niveau ING3"
TEACHER = "Enseignant : JOUD HANAY"
GITHUB_URL = "https://github.com/Babacar2804/Projet-PythonSecure-log-anlysis"
# Mesures faites avec `python main.py analyze --trace-memory --limit N`
MEMORY_MEASURES = [(290_699, 12.5), (2_000_000, 18.9)]
TESTS_COUNT = 75        # résultat de `python -m pytest`
SOUTENANCE_DATE = "12/11/2026"
# ---------------------------------------------------------------------------

INK = colors.HexColor("#0b0b0b")
MUTED = colors.HexColor("#52514e")
ACCENT = colors.HexColor("#2a78d6")
LIGHT = colors.HexColor("#eef4fc")
CODE_BG = colors.HexColor("#f4f3f0")
GRID = colors.HexColor("#d9d8d3")


# ------------------------------------------------------------------ polices
def register_fonts() -> tuple[str, str, str, str]:
    """Segoe UI / Consolas sous Windows, sinon polices intégrées."""
    candidates = {
        "Body": ["segoeui.ttf", "DejaVuSans.ttf"],
        "Body-Bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf"],
        "Body-Italic": ["segoeuii.ttf", "DejaVuSans-Oblique.ttf"],
        "Mono": ["consola.ttf", "DejaVuSansMono.ttf"],
    }
    folders = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/"
                                              "dejavu"),
               Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    found = {}
    for name, files in candidates.items():
        for folder in folders:
            for file in files:
                if (folder / file).exists():
                    pdfmetrics.registerFont(TTFont(name, str(folder / file)))
                    found[name] = name
                    break
            if name in found:
                break
    if len(found) < 4:
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold",
                                  italic="Body-Italic",
                                  boldItalic="Body-Bold")
    return "Body", "Body-Bold", "Body-Italic", "Mono"


BODY, BOLD, ITALIC, MONO = register_fonts()

STYLES = {
    "title": ParagraphStyle("title", fontName=BOLD, fontSize=26, leading=32,
                            textColor=INK, alignment=TA_CENTER),
    "subtitle": ParagraphStyle("subtitle", fontName=BODY, fontSize=14,
                               leading=20, textColor=MUTED,
                               alignment=TA_CENTER),
    "cover": ParagraphStyle("cover", fontName=BODY, fontSize=11, leading=16,
                            textColor=INK, alignment=TA_CENTER),
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=17, leading=22,
                         textColor=ACCENT, spaceBefore=6, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=12.5, leading=17,
                         textColor=INK, spaceBefore=10, spaceAfter=5),
    "body": ParagraphStyle("body", fontName=BODY, fontSize=10, leading=14.5,
                           textColor=INK, spaceAfter=6),
    "bullet": ParagraphStyle("bullet", fontName=BODY, fontSize=10,
                             leading=14.5, textColor=INK, leftIndent=14,
                             bulletIndent=4, spaceAfter=2),
    "caption": ParagraphStyle("caption", fontName=ITALIC, fontSize=8.5,
                              leading=11, textColor=MUTED,
                              alignment=TA_CENTER, spaceAfter=10),
    "cell": ParagraphStyle("cell", fontName=BODY, fontSize=8.5, leading=11,
                           textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName=BOLD, fontSize=8.5, leading=11,
                            textColor=colors.white),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=7.8, leading=10,
                           textColor=INK, backColor=CODE_BG, borderPadding=6,
                           leftIndent=6, rightIndent=6, spaceBefore=4,
                           spaceAfter=10),
    "toc1": ParagraphStyle("toc1", fontName=BODY, fontSize=11, leading=18,
                           textColor=INK),
    "kpi_value": ParagraphStyle("kpi_value", fontName=BOLD, fontSize=16,
                                leading=20, textColor=ACCENT,
                                alignment=TA_CENTER),
    "kpi_label": ParagraphStyle("kpi_label", fontName=BODY, fontSize=8,
                                leading=10, textColor=MUTED,
                                alignment=TA_CENTER),
}


def fmt(n: float) -> str:
    """12345678 -> '12 345 678' (espace insécable fine)."""
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}".replace(",", "\u00a0").replace(".", ",")
    return f"{int(n):,}".replace(",", "\u00a0")


def go(size: float) -> str:
    """12.04 -> '12,0 Go'."""
    return f"{size:.1f}".replace(".", ",") + "\u00a0Go"


# ------------------------------------------------------------- composants
class Report(SimpleDocTemplate):
    """Document qui alimente le sommaire avec les titres de niveau 1."""

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            text = flowable.getPlainText()
            key = f"h1-{self.seq.nextf('h1')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0)
            self.notify("TOCEntry", (0, text, self.page, key))


def h1(text: str) -> list:
    return [CondPageBreak(6 * cm), Paragraph(text, STYLES["h1"])]


def h2(text: str) -> Paragraph:
    return Paragraph(text, STYLES["h2"])


def p(text: str) -> Paragraph:
    return Paragraph(text, STYLES["body"])


def bullets(items: list[str]) -> list:
    return [Paragraph(item, STYLES["bullet"], bulletText="•")
            for item in items]


def code(text: str) -> Preformatted:
    return Preformatted(text.strip("\n"), STYLES["code"])


def figure(path: Path, caption: str, width: float = 16) -> list:
    if not path.exists():
        return [p(f"<i>(graphique manquant : {escape(path.name)})</i>")]
    img = Image(str(path))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width * cm
    img.drawHeight = width * cm * ratio
    return [KeepTogether([img, Paragraph(caption, STYLES["caption"])])]


def table(rows: list[list], widths: list[float], header: bool = True,
          zebra: bool = True) -> Table:
    data = []
    for i, row in enumerate(rows):
        style = STYLES["cellb"] if header and i == 0 else STYLES["cell"]
        data.append([cell if not isinstance(cell, str)
                     else Paragraph(cell, style) for cell in row])
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1)
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), ACCENT))
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                commands.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(commands))
    return t


def kpis(items: list[tuple[str, str]]) -> Table:
    """Rangée de chiffres clés."""
    cells = [[Paragraph(value, STYLES["kpi_value"]),
              Paragraph(label, STYLES["kpi_label"])] for value, label in items]
    t = Table([cells], colWidths=[16 * cm / len(items)] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0, colors.white),
        ("LINEAFTER", (0, 0), (-2, -1), 2, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def on_page(canvas, doc) -> None:
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont(BODY, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(2 * cm, 1.2 * cm,
                      "Engine de traitement et d'analyse de logs")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(GRID)
    canvas.line(2 * cm, 1.55 * cm, A4[0] - 2 * cm, 1.55 * cm)
    canvas.restoreState()


# -------------------------------------------------------------- schémas
def draw_pipeline(path: Path) -> Path:
    """Schéma de l'architecture du pipeline (dessiné avec matplotlib)."""
    steps = [
        ("Fichiers .log (12 Go)", "data/raw/*.log", "#e8e7e3"),
        ("read_sources / read_log_file", "yield from / yield", "#cde2fb"),
        ("map(clean_raw_line)", "espaces, ANSI, invisibles", "#cde2fb"),
        ("filter(tracker.keep_line)", "vides, commentaires, traces",
         "#cde2fb"),
        ("drop_consecutive_duplicates", "doublons (yield)", "#cde2fb"),
        ("map(parse_line)", "str -> dict, match-case", "#cde2fb"),
        ("map(normalize_record)", "types et valeurs canoniques", "#cde2fb"),
        ("filter(tracker.accept)", "rejet des invalides", "#cde2fb"),
    ]
    consumers = [
        ("stats.update()", "defaultdict, set"),
        ("detector.feed()", "fenêtre glissante"),
        ("check_rules(record)", "*args, **kwargs"),
    ]
    fig, ax = plt.subplots(figsize=(10, 7.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 11.6)
    ax.axis("off")
    x, w, h = 0.4, 5.0, 0.9
    for i, (title, sub, color) in enumerate(steps):
        y = 10.5 - i * 1.25
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,"
                                    "rounding_size=0.12", fc=color,
                                    ec="#8a8984", lw=0.8))
        ax.text(x + 0.2, y + 0.58, title, fontsize=10.5, weight="bold",
                color="#0b0b0b", family="monospace")
        ax.text(x + 0.2, y + 0.2, sub, fontsize=9, color="#52514e")
        if i:
            ax.add_patch(FancyArrowPatch((x + w / 2, y + h + 0.35),
                                         (x + w / 2, y + h), arrowstyle="-|>",
                                         mutation_scale=12, color="#52514e"))
    # boucle for unique
    loop_y = 10.5 - (len(steps) - 1) * 1.25 + h / 2
    ax.add_patch(FancyBboxPatch((6.3, 1.0), 3.3, 4.7, boxstyle="round,pad=0."
                                "02,rounding_size=0.15", fc="#fcfcfb",
                                ec="#2a78d6", lw=1.4, ls="--"))
    ax.text(7.95, 5.35, "for record in records:", ha="center", fontsize=10,
            weight="bold", family="monospace", color="#2a78d6")
    ax.text(7.95, 5.0, "une seule passe", ha="center", fontsize=8.5,
            color="#52514e")
    for j, (title, sub) in enumerate(consumers):
        y = 3.9 - j * 1.25
        ax.add_patch(FancyBboxPatch((6.55, y), 2.8, 0.9, boxstyle="round,pad="
                                    "0.02,rounding_size=0.1", fc="#d9f2e8",
                                    ec="#8a8984", lw=0.8))
        ax.text(7.95, y + 0.55, title, ha="center", fontsize=9.5,
                weight="bold", family="monospace")
        ax.text(7.95, y + 0.18, sub, ha="center", fontsize=8.5,
                color="#52514e")
    ax.add_patch(FancyArrowPatch((x + w, loop_y), (6.3, loop_y),
                                 arrowstyle="-|>", mutation_scale=14,
                                 color="#2a78d6", lw=1.4))
    ax.text(7.95, 0.45, "report.json · alerts.csv · incidents.csv · "
            "charts/*.png", ha="center", fontsize=8.5, color="#52514e")
    ax.add_patch(FancyArrowPatch((7.95, 1.0), (7.95, 0.7), arrowstyle="-|>",
                                 mutation_scale=12, color="#52514e"))
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)
    return path


def draw_memory(path: Path) -> Path:
    """Pic mémoire mesuré en fonction du nombre de lignes."""
    lines = [m[0] for m in MEMORY_MEASURES]
    peaks = [m[1] for m in MEMORY_MEASURES]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    labels = [f"{fmt(n)} lignes" for n in lines]
    bars = ax.bar(labels, peaks, width=0.45, color="#2a78d6")
    for bar, value in zip(bars, peaks):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.4,
                f"{value:.1f} Mo".replace(".", ","), ha="center",
                fontsize=10, color="#0b0b0b")
    ax.set_ylim(0, max(peaks) * 1.35)
    ax.set_ylabel("Pic mémoire Python (Mo)", color="#52514e")
    ax.set_title("7 fois plus de lignes, seulement 1,5 fois plus de mémoire",
                 loc="left", fontsize=11)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors="#52514e")
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)
    return path


# -------------------------------------------------------------- contenu
def cover(story: list, report: dict) -> None:
    run = report["execution"]
    story += [
        Spacer(1, 4.5 * cm),
        Paragraph("Engine de traitement et d'analyse", STYLES["title"]),
        Paragraph("de flux de données sécurisé", STYLES["title"]),
        Spacer(1, 0.6 * cm),
        Paragraph("Rapport de projet final — Python avancé",
                  STYLES["subtitle"]),
        Spacer(1, 1.6 * cm),
        kpis([(go(run["taille_go"]), "de logs analysés"),
              (fmt(report["nettoyage"]["lignes_lues"]), "lignes lues"),
              (fmt(sum(report["alertes_par_regle"].values())),
               "alertes de sécurité"),
              (str(report["force_brute"]["nb_comptes_compromis"]),
               "IP attaquantes ayant compromis un compte")]),
        Spacer(1, 2.4 * cm),
        Paragraph("<b>Équipe</b>", STYLES["cover"]),
        *[Paragraph(name, STYLES["cover"]) for name in TEAM],
        Spacer(1, 0.8 * cm),
        Paragraph(f"{SCHOOL} · {TEACHER}", STYLES["cover"]),
        Paragraph(f"Dépôt : {escape(GITHUB_URL)}", STYLES["cover"]),
        Paragraph(f"Soutenance du {SOUTENANCE_DATE}", STYLES["cover"]),
        PageBreak(),
    ]


def build_story(results: Path, charts: Path, tmp: Path) -> list:
    report = json.loads((results / "report.json").read_text("utf-8"))
    run, clean = report["execution"], report["nettoyage"]
    stats, ips = report["statistiques"], report["ensembles_ip"]
    brute, alerts = report["force_brute"], report["alertes_par_regle"]
    audit_path = results / "audit.json"
    audit = json.loads(audit_path.read_text("utf-8")) \
        if audit_path.exists() else None
    incidents = []
    if (results / "incidents.csv").exists():
        with open(results / "incidents.csv", encoding="utf-8") as file:
            incidents = list(csv.DictReader(file))

    story: list = []
    cover(story, report)

    toc = TableOfContents()
    toc.levelStyles = [STYLES["toc1"]]
    toc_title = ParagraphStyle("toc_title", parent=STYLES["h1"])
    story += [Paragraph("Sommaire", toc_title), toc, PageBreak()]

    # 1. Introduction ------------------------------------------------------
    total_lines = clean["lignes_lues"]
    story += h1("1. Introduction et objectifs")
    story += [
        p("L'objectif du projet est de concevoir une plateforme en ligne de "
          "commande capable d'<b>ingérer, nettoyer, transformer et analyser "
          "des journaux de logs système et réseau volumineux</b>, sans jamais "
          "charger les fichiers entiers en mémoire vive."),
        p(f"Pour l'éprouver, nous avons aussi écrit un <b>générateur</b> qui "
          f"produit un jeu de données réaliste de <b>"
          f"{go(run['taille_go'])}</b>"
          f" ({fmt(total_lines)} lignes réparties en "
          f"{len(run['fichiers'])} fichiers). Conformément aux consignes, "
          "ces logs sont variés (11 services, 3 formats, des incidents et "
          "des attaques simulés) et volontairement abîmés pour nécessiter un "
          "nettoyage poussé."),
        p("Le rapport suit le cheminement des données : leur génération, "
          "l'architecture du pipeline, puis les quatre modules du cahier des "
          "charges, illustrés par les résultats obtenus sur le jeu complet."),
    ]
    story += bullets([
        "<b>Module 1</b> — ingestion par générateurs (<font name='%s'>yield"
        "</font>, <font name='%s'>yield from</font>), suivi d'un flux en "
        "temps réel et parsing en dictionnaires ;" % (MONO, MONO),
        "<b>Module 2</b> — pipeline fonctionnel (<font name='%s'>map</font>, "
        "<font name='%s'>filter</font>, <font name='%s'>lambda</font>) et "
        "routage par <font name='%s'>match-case</font> ;"
        % (MONO, MONO, MONO, MONO),
        "<b>Module 3</b> — agrégation (<font name='%s'>set</font>, "
        "<font name='%s'>frozenset</font>, <font name='%s'>defaultdict</font>)"
        " et détection de force brute ;" % (MONO, MONO, MONO),
        "<b>Module 4</b> — moteur de règles (<font name='%s'>*args</font>, "
        "<font name='%s'>**kwargs</font>) et audit par introspection." %
        (MONO, MONO),
    ])

    # 2. Environnement ------------------------------------------------------
    story += h1("2. Environnement et organisation du projet")
    story += [
        h2("2.1 Environnement virtuel et dépendances"),
        p("Le projet s'exécute dans un environnement virtuel <font name='%s'>"
          "venv</font> isolé. Le fichier <font name='%s'>requirements.txt"
          "</font> liste les dépendances directes avec des plages de "
          "versions (compatibles Python 3.10 et plus) : <font name='%s'>"
          "pip install -r requirements.txt</font> reconstruit "
          "l'environnement. Le moteur lui-même n'utilise que la bibliothèque "
          "standard ; matplotlib sert aux graphiques, reportlab à produire "
          "ce rapport, pytest et mypy à vérifier le code." %
          (MONO, MONO, MONO)),
        code("python -m venv .venv\n"
             ".venv\\Scripts\\activate          # Windows\n"
             "pip install -r requirements.txt\n\n"
             "python main.py demo                     # test + analyse\n"
             "python main.py generate --size-gb 12    # jeu de 12 Go\n"
             "python main.py analyze                  # analyse complète\n"
             "python main.py analyze --limit 2000000 --level ERROR\n"
             "python main.py live --duration 60       # temps réel\n\n"
             "python -m pytest                        # 75 tests\n"
             "python -m mypy                          # typage"),
        h2("2.2 Structure en package"),
        p("Le code est organisé en package Python (<font name='%s'>logengine"
          "</font>), un fichier par responsabilité. Le point d'entrée <font "
          "name='%s'>main.py</font> pilote l'ensemble via quatre commandes. "
          "Aucun notebook n'est utilisé. Le code est versionné avec Git et "
          "partagé sur GitHub ; les données générées en sont exclues par le "
          "<font name='%s'>.gitignore</font>." % (MONO, MONO, MONO)),
        table([
            ["Fichier", "Rôle", "Module"],
            ["main.py",
             "CLI : generate, analyze, demo, live ; construit le pipeline",
             "—"],
            ["generator.py", "Génère le jeu de données (multiprocessus) et "
             "le flux temps réel", "—"],
            ["ingestion.py", "Lecture paresseuse des fichiers, suivi en "
             "direct", "1"],
            ["parsing.py", "Ligne brute → dictionnaire, routage match-case",
             "1 et 2"],
            ["transform.py", "Nettoyage, normalisation, suivi qualité", "2"],
            ["aggregation.py", "Compteurs, ensembles, liste noire", "3"],
            ["detection.py", "Détection de force brute", "3"],
            ["rules.py", "Moteur de règles de sécurité", "4"],
            ["audit.py", "Introspection globals() / locals()", "4"],
            ["report.py", "Exports JSON / CSV et graphiques", "—"],
            ["tests/", "75 tests pytest, un fichier par module", "tous"],
        ], [3.6, 10.4, 2]),
    ]

    # 3. Jeu de données ----------------------------------------------------
    story += h1("3. Le jeu de données généré")
    story += [
        p(f"Le générateur produit {go(run['taille_go'])} de logs couvrant "
          f"la période du {stats['periode']['debut'][:10]} au "
          f"{stats['periode']['fin'][:10]}. Chaque fichier couvre une tranche "
          "de temps (comme une rotation de logs) et est écrit par un "
          "processus séparé (<font name='%s'>ProcessPoolExecutor</font>) : "
          "les 12 Go ont été produits en 75 secondes avec 7 processus."
          % MONO),
        h2("3.1 Trois formats de lignes bien structurés"),
        p("<b>Format applicatif</b> (~80 %) : sept champs séparés par "
          "« | ». Le dernier est un payload JSON ou une chaîne brute."),
        code("2026-10-01T08:15:32.481Z | INFO | api-gateway | "
             "10.0.3.17:51432/TCP | user=u1042\n"
             "  | event=http_request | {\"method\":\"GET\",\"path\":"
             "\"/api/v1/products\",\"status\":200,\"latency_ms\":43,...}\n"
             "2026-10-01T08:15:33.017Z | WARNING | db-cluster | "
             "10.0.100.21:6772/TCP | user=svc_db\n"
             "  | event=query_slow | requête lente (2350 ms) sur la table "
             "orders"),
        p("<b>Format JSON</b> (~10 %, services de paiement et "
          "utilisateurs) :"),
        code("{\"ts\":\"2026-10-01T08:15:32.481Z\",\"lvl\":\"error\",\"svc\":"
             "\"payment-service\",\n \"client\":{\"ip\":\"95.5.28.176\","
             "\"port\":443,\"proto\":\"TCP\"},\"user\":\"u9\",\n \"event\":"
             "\"payment_failed\",\"code\":502,\"msg\":\"bank gateway error\","
             "\"amount\":14.7,...}"),
        p("<b>Format pare-feu</b> (~10 %) : champs positionnels séparés par "
          "des espaces, qui forment naturellement un tuple de connexion."),
        code("FW 2026-10-01T00:20:12.423Z DROP TCP 102.109.77.236 27409 "
             "10.0.100.29 22 DENY-SSH-EXT"),
        h2("3.2 Des données variées"),
    ]
    story += bullets([
        "11 services, 5 000 utilisateurs (distribution de Zipf : quelques "
        "comptes très actifs), environ 17 000 adresses IP (internes, bureau, "
        "publiques, IPv6) ;",
        "un profil d'activité réaliste : creux la nuit, pics vers 10 h et "
        "15 h, trafic réduit de 40 % le week-end ;",
        "des scénarios planifiés : <b>pannes</b> de services, attaques "
        "<b>DDoS</b> par un botnet de 400 IP, <b>déploiements</b> "
        "quotidiens, <b>disque</b> qui se remplit jusqu'à saturation ;",
        "des attaques : <b>force brute</b> (dont certaines réussissent, "
        "suivies d'une élévation de privilèges et d'un export de données), "
        "<b>credential stuffing</b>, <b>scans de ports</b>, <b>injections "
        "SQL</b>, <b>XSS</b>, <b>path traversal</b>, outils offensifs ;",
        "une liste noire d'IP (fichier lui aussi imparfait) mêlant attaquants "
        "connus et IP qui n'apparaissent jamais dans les logs.",
    ])
    story += [
        h2("3.3 Des défauts injectés pour un nettoyage poussé"),
        p("Environ 5 % des lignes sont volontairement abîmées. Certains "
          "défauts sont <b>réparables</b>, d'autres imposent un <b>rejet</b> "
          ": c'est ce que le pipeline doit distinguer."),
        table([
            ["Défaut injecté", "Exemple", "Traitement"],
            ["Espaces, tabulations, \\r", "<font name='%s'>\"  \\t2026-…  "
             "\\r\"</font>" % MONO, "réparé"],
            ["Caractères invisibles, octets invalides, BOM",
             "<font name='%s'>\\x00, \\xff, \\ufeff</font>" % MONO, "réparé"],
            ["Codes couleur de terminal", "<font name='%s'>\\x1b[31mERROR"
             "\\x1b[0m</font>" % MONO, "réparé"],
            ["Casse des niveaux / services", "err, Warning, FATAL, "
             "API_GATEWAY", "réparé"],
            ["Format des utilisateurs", "U-1042, USER_1042, user-01042, null",
             "réparé → u1042 / anonyme"],
            ["Autres formats de date", "01/10/2026 08:15:32, epoch, virgule",
             "réparé"],
            ["JSON entre guillemets simples, nombres en texte",
             "{'status': '200'}", "réparé"],
            ["Encodage cassé", "requÃªte", "réparé → requête"],
            ["Latence absurde", "-1, NaN, \"slow\"", "valeur neutralisée"],
            ["Lignes vides, commentaires, stack traces, doublons", "",
             "supprimé"],
            ["Date impossible", "2026-13-45T25:61:00Z", "rejeté"],
            ["IP ou port impossible", "999.12.4.1, 10.0.0, port 99999",
             "rejeté"],
            ["Ligne tronquée, champ manquant, JSON incomplet", "", "rejeté"],
        ], [5.6, 6.2, 4.2]),
    ]

    # 4. Architecture -------------------------------------------------------
    story += h1("4. Architecture du pipeline")
    story += [
        p("Le cœur du projet est une <b>chaîne de traitements paresseux</b>. "
          "<font name='%s'>map()</font>, <font name='%s'>filter()</font> et "
          "les fonctions contenant <font name='%s'>yield</font> ne calculent "
          "rien tant qu'on ne leur demande pas l'élément suivant." %
          (MONO, MONO, MONO)),
    ]
    story += figure(draw_pipeline(tmp / "pipeline.png"),
                    "Figure 1 — Architecture du pipeline : de la lecture du "
                    "disque jusqu'aux résultats.", width=15.5)
    story += [
        p("Dans <font name='%s'>main.py</font>, la construction du pipeline "
          "ne lit aucune donnée : chaque instruction enveloppe l'itérateur "
          "précédent. C'est la boucle <font name='%s'>for</font> finale qui "
          "« tire » les lignes une à une à travers toute la chaîne. Une ligne "
          "est lue, nettoyée, découpée, normalisée, comptée, puis oubliée."
          % (MONO, MONO)),
        code("lines   = read_sources(files)                  # yield from\n"
             "lines   = map(clean_raw_line, lines)          # nettoyage\n"
             "lines   = filter(tracker.keep_line, lines)    # vides, #...\n"
             "lines   = drop_consecutive_duplicates(lines, tracker)\n"
             "records = map(parse_line, lines)              # str -> dict\n"
             "records = map(normalize_record, records)      # types, casse\n"
             "records = filter(tracker.accept, records)     # rejets\n"
             "records = filter(lambda r: LEVEL_RANK[r[\"level\"]] >= min_rank,"
             " records)\n\n"
             "for record in records:                        # une passe\n"
             "    stats.update(record)\n"
             "    detector.feed(record)\n"
             "    for alert in check_rules(record):  "
             "# check_rules = apply_security_rules(...)\n"
             "        alert_writer.writerow(alert)"),
        p("Comme un générateur ne se parcourt qu'une fois, tous les calculs "
          "(statistiques, détection, règles) sont faits <b>dans la même "
          "passe</b>. On ne conserve que des compteurs et des ensembles de "
          "taille bornée, jamais les lignes."),
    ]

    # 5. Module 1 -----------------------------------------------------------
    story += h1("5. Module 1 — Ingestion et parsing")
    story += [
        h2("5.1 Lecture paresseuse avec yield et yield from"),
        code("def read_log_file(path: Path) -> Iterator[str]:\n"
             "    with open(path, encoding=\"utf-8\", errors=\"replace\", "
             "newline=\"\") as file:\n"
             "        for line in file:\n"
             "            yield line\n\n"
             "def read_sources(paths: Iterable[Path]) -> Iterator[str]:\n"
             "    for path in paths:\n"
             "        try:\n"
             "            yield from read_log_file(path)\n"
             "        except (FileNotFoundError, PermissionError) as exc:\n"
             "            print(f\"fichier ignoré : {path}\", "
             "file=sys.stderr)"),
        p("<font name='%s'>yield</font> suspend la fonction et renvoie une "
          "ligne ; elle reprend au même endroit à l'appel suivant. <font "
          "name='%s'>yield from</font> délègue à un sous-générateur : les "
          "fichiers successifs forment un flux unique. <font name='%s'>"
          "errors=\"replace\"</font> évite qu'un octet invalide ne fasse "
          "planter la lecture ; le caractère de remplacement est ensuite "
          "supprimé par le nettoyage." % (MONO, MONO, MONO)),
        h2("5.2 Modélisation en dictionnaire et tuple de connexion"),
        p("Chaque ligne devient un dictionnaire typé (<font name='%s'>"
          "TypedDict LogRecord</font>) : horodatage (<font name='%s'>datetime"
          "</font>), niveau, service, IP, utilisateur, évènement, payload "
          "(dict JSON ou chaîne brute), ainsi que deux listes <font name='%s'>"
          "errors</font> et <font name='%s'>fixes</font> qui tracent le "
          "nettoyage. Les métadonnées fixes de la connexion sont stockées "
          "dans un <b>tuple immuable</b> <font name='%s'>(IP, Port, "
          "Protocole)</font> : il ne peut pas être modifié par erreur et, "
          "étant hachable, il peut servir de clé de dictionnaire ou "
          "d'élément d'ensemble (voir 7.2)." %
          (MONO, MONO, MONO, MONO, MONO)),
        h2("5.3 Traitement en temps réel"),
        p("Le moteur sait aussi analyser un flux <b>en direct</b>. <font "
          "name='%s'>follow_log_file</font> est un générateur infini qui suit "
          "un fichier en train de grossir, comme <font name='%s'>tail -f"
          "</font> : quand il n'y a rien de nouveau, il attend au lieu de "
          "s'arrêter, et il n'émet une ligne qu'une fois son <font name='%s'>"
          "\\n</font> final écrit." % (MONO, MONO, MONO)),
        code("while deadline is None or time.monotonic() < deadline:\n"
             "    chunk = file.readline()\n"
             "    if not chunk:                   # rien de nouveau\n"
             "        time.sleep(poll_interval)\n"
             "        continue\n"
             "    pending += chunk\n"
             "    if not pending.endswith(\"\\n\"):  # ligne incomplète\n"
             "        continue\n"
             "    yield pending\n"
             "    pending = \"\""),
        p("La commande <font name='%s'>python main.py live</font> lance dans "
          "un <font name='%s'>thread</font> un « serveur » simulé qui écrit "
          "environ 200 lignes par seconde, pendant que le programme principal "
          "suit le fichier. Les lignes passent par <b>exactement le même "
          "pipeline</b> que les archives (<font name='%s'>build_pipeline"
          "</font>) : seule la source change. Extrait d'une exécution :" %
          (MONO, MONO, MONO)),
        code("[live] 1,571 lignes lues, 1,547 valides, 1 alertes\n"
             "  [HIGH    ] path_traversal   213.67.29.14    "
             "/download?file=..%2f..%2fetc%2fshadow\n"
             "  [HIGH    ] ip_blacklistee   92.112.165.218  "
             "login_failed depuis une IP en liste noire\n"
             "  [FORCE BRUTE] 92.112.165.218 : 5 échecs en moins de 2 min\n"
             "  [HIGH    ] xss              217.135.14.178  "
             "/profile?name=javascript:alert(document.cookie)\n"
             "=== Bilan temps réel : 7,065 lignes, 6,956 valides, "
             "1 IP suspectes ==="),
    ]

    # 6. Module 2 -----------------------------------------------------------
    story += h1("6. Module 2 — Transformation et nettoyage")
    story += [
        h2("6.1 Routage par Structural Pattern Matching"),
        p("Plutôt qu'une cascade de <font name='%s'>if/elif</font>, <font "
          "name='%s'>parse_line</font> décrit la <b>forme</b> attendue de "
          "chaque format. La ligne est d'abord décodée en dict (JSON), en "
          "tuple (pare-feu) ou laissée en chaîne, puis routée :" %
          (MONO, MONO)),
        code("match decode_line(line):\n"
             "    case {\"ts\": timestamp, \"lvl\": str(level), \"svc\": "
             "str(service),\n"
             "          \"client\": {\"ip\": ip, \"port\": port, \"proto\": "
             "protocol}, **rest}:\n"
             "        ...                                   # dictionnaire\n"
             "    case (\"FW\", timestamp, action, protocol, src_ip, "
             "src_port,\n"
             "          dst_ip, dst_port, *rule):\n"
             "        ...                                   # tuple de "
             "connexion\n"
             "    case tuple():\n"
             "        return _rejected(line, \"pare_feu_incomplet\")\n"
             "    case str() as text if text.startswith(\"{\"):\n"
             "        return _rejected(line, \"json_invalide\")\n"
             "    case str() as text:\n"
             "        return _parse_app_line(text)          # chaîne brute"),
        p("Un motif dict vérifie la présence des clés (même imbriquées) ; un "
          "motif tuple vérifie la longueur et le premier élément ; <font "
          "name='%s'>str(level)</font> contrôle le type et capture la valeur. "
          "Le même mécanisme remplace les longs <font name='%s'>if</font> de "
          "normalisation des niveaux :" % (MONO, MONO)),
        code("match value.strip().upper():\n"
             "    case \"WARNING\" | \"WARN\" | \"WRN\":\n"
             "        return \"WARNING\"\n"
             "    case \"CRITICAL\" | \"CRIT\" | \"FATAL\" | \"EMERG\":\n"
             "        return \"CRITICAL\""),
        h2("6.2 Programmation fonctionnelle : map, filter, lambda"),
        p("<font name='%s'>map(clean_raw_line, lines)</font> applique la "
          "même fonction de nettoyage à chaque ligne. <font name='%s'>filter"
          "</font> reçoit des <b>méthodes</b> comme prédicats (<font name="
          "'%s'>tracker.keep_line</font>, <font name='%s'>tracker.accept"
          "</font>) : elles décident de garder ou non l'élément et comptent "
          "au passage la cause de chaque suppression. Des <font name='%s'>"
          "lambda</font> servent aux filtres de la ligne de commande et aux "
          "tris, et <font name='%s'>filter(None, …)</font> élimine les lignes "
          "vides de la liste noire." % (MONO, MONO, MONO, MONO, MONO, MONO)),
        h2("6.3 Résultats du nettoyage"),
        kpis([(fmt(clean["lignes_lues"]), "lignes lues"),
              (fmt(clean["lignes_supprimees"]), "supprimées"),
              (fmt(clean["enregistrements_rejetes"]), "rejetées"),
              (f"{clean['taux_de_rejet_pct']} %".replace(".", ","),
               "taux de perte")]),
        Spacer(1, 0.3 * cm),
    ]
    story += figure(charts / "06_nettoyage.png",
                    "Figure 2 — Lignes supprimées avant parsing et "
                    "enregistrements rejetés, par cause.", width=14)
    story += figure(charts / "07_corrections.png",
                    "Figure 3 — Corrections appliquées : ces lignes étaient "
                    "abîmées mais ont pu être récupérées.", width=14)
    fixed = sum(clean["corrections"].values())
    story += [p(f"Au total, <b>{fmt(fixed)} corrections</b> ont été "
                "appliquées. La grande majorité des défauts est donc "
                "réparée plutôt que perdue ; seules les lignes réellement "
                "inexploitables (date ou IP impossibles, ligne tronquée) "
                "sont écartées. Des exemples réels de chaque cause sont "
                "conservés dans <font name='%s'>rejected_samples.txt</font>."
                % MONO)]

    # 7. Module 3 -----------------------------------------------------------
    story += h1("7. Module 3 — Agrégation et analyse")
    levels = stats["par_niveau"]
    story += [
        h2("7.1 Accumulation avec defaultdict"),
        p("<font name='%s'>LogStatistics</font> accumule toutes les "
          "statistiques en une passe. <font name='%s'>defaultdict(int)</font> "
          "crée automatiquement la valeur 0 pour une clé absente : <font "
          "name='%s'>compteur[cle] += 1</font> ne lève jamais de <font name="
          "'%s'>KeyError</font>. Des variantes imbriquées (<font name='%s'>"
          "defaultdict(lambda: defaultdict(int))</font> pour service → niveau"
          ", <font name='%s'>defaultdict(set)</font> pour IP → ports bloqués) "
          "complètent l'analyse." % (MONO, MONO, MONO, MONO, MONO, MONO)),
        kpis([(fmt(stats["total_valides"]), "logs valides"),
              (fmt(stats["nb_ip_uniques"]), "IP uniques"),
              (fmt(stats["nb_utilisateurs_uniques"]), "utilisateurs"),
              (fmt(levels.get("ERROR", 0) + levels.get("CRITICAL", 0)),
               "erreurs")]),
        Spacer(1, 0.3 * cm),
    ]
    story += figure(charts / "01_chronologie.png",
                    "Figure 4 — Volume de logs et d'erreurs par heure. On "
                    "distingue le cycle jour/nuit, les week-ends plus calmes "
                    "et les pics d'erreurs des pannes simulées.")
    story += figure(charts / "03_heures.png",
                    "Figure 5 — Trafic selon l'heure de la journée (UTC).",
                    width=14)
    story += figure(charts / "02_niveaux.png",
                    "Figure 6 — Répartition par niveau de sévérité (échelle "
                    "logarithmique).", width=12)
    story += figure(charts / "04_erreurs_par_service.png",
                    "Figure 7 — Erreurs par service : les services touchés "
                    "par les pannes ressortent nettement.", width=14)
    story += figure(charts / "05_codes_http.png",
                    "Figure 8 — Codes de réponse HTTP.", width=13)
    story += figure(charts / "09_latences.png",
                    "Figure 9 — Distribution des temps de réponse.",
                    width=14)

    story += [
        h2("7.2 Ensembles : IP uniques et liste noire"),
        p("Les IP ayant généré des erreurs sont collectées dans un <font "
          "name='%s'>set</font> : les doublons sont ignorés automatiquement. "
          "La liste noire est chargée dans un <font name='%s'>frozenset"
          "</font>, immuable, pour qu'elle ne puisse pas être modifiée "
          "pendant l'analyse. Les opérations ensemblistes donnent :" %
          (MONO, MONO)),
        table([
            ["Opération", "Signification", "Nombre d'IP"],
            ["actives | blacklist", "union : toutes les IP connues",
             fmt(ips["union_actives_blacklist"])],
            ["actives &amp; blacklist", "IP listées réellement actives",
             fmt(ips["blacklist_actives"])],
            ["erreurs &amp; blacklist",
             "IP listées qui provoquent des erreurs",
             fmt(ips["blacklist_en_erreur"])],
            ["actives - blacklist", "IP actives absentes de la liste",
             fmt(ips["actives_non_listees"])],
            ["blacklist - actives", "IP listées jamais vues (liste à "
             "mettre à jour)", fmt(ips["blacklist_dormantes"])],
            ["actives ^ blacklist", "différence symétrique",
             fmt(ips["difference_symetrique"])],
        ], [4.2, 8.6, 3.2]),
        Spacer(1, 0.3 * cm),
        p(f"Sur {fmt(ips['taille_blacklist'])} IP en liste noire, "
          f"<b>{fmt(ips['blacklist_actives'])}</b> sont actives dans nos "
          "logs : ce sont précisément les attaquants et machines du botnet "
          "injectés par le générateur, ce qui valide la chaîne complète."),
    ]
    flows = stats.get("top_flux_bloques", [])
    if flows:
        protocols = stats.get("par_protocole", {})
        story += [
            h2("7.3 Tuples de connexion : flux bloqués et scans de ports"),
            p("Le tuple <font name='%s'>(IP, Port, Protocole)</font> est "
              "exploité de trois façons. Il est d'abord <b>déballé</b> "
              "(<font name='%s'>ip, _, protocol = record[\"connection\"]"
              "</font>) pour compter les protocoles : %s. Ensuite, pour "
              "chaque blocage du pare-feu, le tuple (IP source, port visé, "
              "protocole) sert de <b>clé de dictionnaire</b> — ce qui n'est "
              "possible que parce qu'il est immuable. %s flux distincts ont "
              "été comptés ; les plus fréquents :" % (
                  MONO, MONO,
                  ", ".join(f"{fmt(n)} {name}" for name, n in sorted(
                      protocols.items(), key=lambda kv: -kv[1])),
                  fmt(stats.get("nb_flux_bloques_distincts", 0)))),
            code("self.blocked_flows[(ip, port, protocol)] += 1\n\n"
                 "for ip, port, _protocol in self.blocked_flows:   "
                 "# déballage\n"
                 "    ports_by_ip[ip].add(port)                    "
                 "# defaultdict(set)"),
            table([["IP source", "Port visé", "Protocole", "Blocages"]] +
                  [[f["ip"], str(f["port"]), f["protocole"],
                    fmt(f["blocages"])] for f in flows[:8]],
                  [5.0, 3.0, 3.5, 4.5]),
            Spacer(1, 0.3 * cm),
        ]
    scanners = stats.get("scans_de_ports", {})
    if scanners:
        story += [p(f"Enfin, en regroupant ces clés par IP (<font name='%s'>"
                    f"defaultdict(set)</font>), on repère <b>{len(scanners)}"
                    " IP</b> ayant tenté au moins 15 ports différents : des "
                    "<b>scans de ports</b>. Dans <font name='%s'>"
                    "rule_exposed_port</font>, un même <font name='%s'>match"
                    "</font> combine un motif dictionnaire et un motif tuple "
                    "(<font name='%s'>{\"connection\": (str(ip), _, \"TCP\"), "
                    "...}</font>)." % (MONO, MONO, MONO, MONO))]

    story += [
        h2("7.4 Détection de force brute"),
        p("Pendant la lecture, <font name='%s'>feed()</font> maintient pour "
          "chaque IP une <b>fenêtre glissante</b> des échecs des 120 "
          "dernières secondes (une <font name='%s'>deque</font>). Une boucle "
          "<font name='%s'>while</font> retire les échecs trop anciens ; au "
          "5<super>e</super> échec dans la fenêtre, l'IP devient suspecte."
          % (MONO, MONO, MONO)),
        code("window.append((moment, user))\n"
             "while window and moment - window[0][0] > self.window:\n"
             "    window.popleft()\n"
             "if suspect is None and len(window) >= self.threshold:\n"
             "    self._suspects[ip] = {...}"),
        p("À la fin, <font name='%s'>summarize()</font> rejoue les tentatives "
          "de chaque suspect avec <font name='%s'>for</font>, <font name='%s'>"
          "continue</font>, <font name='%s'>break</font> et la clause <font "
          "name='%s'>else</font> de la boucle :" %
          (MONO, MONO, MONO, MONO, MONO)),
        code("for moment, user, success in suspect[\"events\"]:\n"
             "    if not success:\n"
             "        consecutive += 1\n"
             "        last_failure = moment\n"
             "        continue                  # échec : tentative suivante\n"
             "    if consecutive >= self.threshold and "
             "moment - last_failure <= self.window:\n"
             "        compromised_at, compromised_user = moment, user\n"
             "        break                     # succès après X échecs : "
             "COMPROMIS\n"
             "    consecutive = 0\n"
             "else:\n"
             "    status = \"bloquee\"          # boucle complète sans break"),
        p("Le <font name='%s'>else</font> ne s'exécute que si la boucle "
          "est allée au bout <b>sans</b> <font name='%s'>break</font> : le "
          "cycle de détection est complet et aucune connexion n'a abouti, "
          "l'attaque a donc échoué." % (MONO, MONO)),
        p("Les incidents sont regroupés <b>par IP</b> : une même IP qui "
          "attaque plusieurs fois sur la période forme un seul incident "
          "(d'où le nombre élevé d'échecs et de comptes ciblés). Les "
          f"{fmt(alerts.get('elevation_privileges', 0))} alertes "
          "d'élévation de privilèges du moteur de règles confirment, de "
          "façon indépendante, les connexions réussies après une attaque."),
        kpis([(fmt(brute["nb_incidents"]), "IP suspectes"),
              (fmt(brute["nb_comptes_compromis"]), "IP ayant réussi"),
              (fmt(sum(1 for i in incidents
                       if i["type"] == "credential_stuffing")),
               "credential stuffing")]),
        Spacer(1, 0.3 * cm),
    ]
    top = [i for i in incidents if i["statut"] == "COMPROMIS"][:6] or \
        incidents[:6]
    if top:
        story += [table(
            [["IP", "Statut", "Type", "Échecs", "Comptes ciblés",
              "Compte compromis"]] +
            [[i["ip"], i["statut"], i["type"].replace("_", " "),
              fmt(int(i["echecs"])), i["utilisateurs_cibles"],
              i["compte_compromis"] or "—"] for i in top],
            [3.0, 2.4, 3.2, 1.7, 2.4, 3.3]),
            Paragraph("Tableau — Exemples d'incidents détectés "
                      "(incidents.csv).", STYLES["caption"])]

    # 8. Module 4 -----------------------------------------------------------
    story += h1("8. Module 4 — Moteur de règles et introspection")
    story += [
        h2("8.1 Une fonction maître à arguments variables"),
        p("Une règle est une simple fonction <font name='%s'>regle(record, "
          "**config)</font> qui renvoie une alerte ou <font name='%s'>None"
          "</font>. La fonction maître a exactement la signature demandée, "
          "<font name='%s'>apply_security_rules(*args, **kwargs)</font> : "
          "<font name='%s'>*args</font> regroupe un nombre variable de "
          "règles dans un tuple, <font name='%s'>**kwargs</font> la "
          "configuration dans un dict. Comme l'enregistrement à analyser ne "
          "fait pas partie de ces arguments, elle <b>fabrique et renvoie une "
          "fonction</b> <font name='%s'>check(record)</font>, préparée une "
          "seule fois puis appelée sur chaque ligne :" %
          (MONO, MONO, MONO, MONO, MONO, MONO)),
        code("def apply_security_rules(*args, **kwargs):\n"
             "    for rule in args:\n"
             "        if not callable(rule):\n"
             "            raise TypeError(...)\n"
             "    disabled = kwargs.get(\"disabled\", ())\n"
             "    active = tuple(filter(lambda rule: rule.__name__ not in "
             "disabled, args))\n\n"
             "    def check(record):\n"
             "        alerts = []\n"
             "        for rule in active:\n"
             "            try:\n"
             "                alert = rule(record, **kwargs)\n"
             "            except Exception as exc:\n"
             "                print(f\"{rule.__name__} a échoué : "
             "{exc!r}\")\n"
             "            else:\n"
             "                if alert is not None:\n"
             "                    alerts.append(alert)\n"
             "        return alerts\n\n"
             "    return check\n\n"
             "check_rules = apply_security_rules(*DEFAULT_RULES, "
             "blacklist=blacklist,\n"
             "                                   max_latency_ms=5000)\n"
             "alerts = check_rules(record)"),
        p("Les fonctions sont manipulées comme des <b>objets de première "
          "classe</b> : rangées dans un tuple, passées en argument, "
          "<b>renvoyées</b> par une autre fonction, identifiées par <font "
          "name='%s'>__name__</font>. <font name='%s'>check</font> garde "
          "accès à <font name='%s'>active</font> et <font name='%s'>kwargs"
          "</font> après la fin de la fonction maître : c'est une "
          "<b>fermeture</b> (closure). Ajouter une règle revient à écrire une "
          "fonction ; une règle qui plante est isolée par le <font name='%s'>"
          "try / except / else</font> et n'arrête pas le moteur." %
          (MONO, MONO, MONO, MONO, MONO)),
        table([
            ["Règle", "Détecte", "Alertes"],
            *[[name.replace("_", " "), desc, fmt(alerts.get(name, 0))]
              for name, desc in [
                  ("sql_injection", "' OR '1'='1, UNION SELECT, DROP TABLE"),
                  ("xss", "&lt;script&gt;, onerror=, javascript:"),
                  ("path_traversal", "../../etc/passwd, win.ini"),
                  ("scanner_probe", "/.env, /wp-admin, /.git/config"),
                  ("outil_offensif", "sqlmap, Nikto, Hydra, masscan"),
                  ("ip_blacklistee", "trafic d'une IP en liste noire"),
                  ("elevation_privileges", "passage d'un compte en admin"),
                  ("exfiltration_donnees", "export massif de données"),
                  ("requete_lente", "latence &gt; 5 000 ms"),
                  ("port_sensible_expose", "port 22/3389/5432 ouvert sur "
                   "Internet"),
              ]],
        ], [4.2, 8.8, 3.0]),
        Spacer(1, 0.3 * cm),
    ]
    story += figure(charts / "08_alertes.png",
                    "Figure 10 — Nombre d'alertes par règle de sécurité.",
                    width=14)
    story += [
        h2("8.2 Audit par introspection : globals() et locals()"),
        p("À la fin de l'analyse, <font name='%s'>main.py</font> appelle "
          "<font name='%s'>export_audit_report(path, globals(), locals())"
          "</font>. Le module d'audit décrit chaque variable (catégorie, "
          "type, taille, aperçu limité par <font name='%s'>reprlib</font>) "
          "et écrit <font name='%s'>audit.json</font>. C'est l'appelant qui "
          "fournit les portées : appelées dans <font name='%s'>audit.py"
          "</font>, elles décriraient le module d'audit lui-même." %
          (MONO, MONO, MONO, MONO, MONO)),
    ]
    if audit:
        wanted = ("stats", "detector", "blacklist", "lines", "records",
                  "tracker", "check_rules")
        rows = [r for r in audit["locales"] if r["nom"] in wanted]
        story += [table(
            [["Variable locale", "Type", "Taille (octets)", "Aperçu"]] +
            [[r["nom"], r["type"], fmt(r["taille_octets"]),
              escape(r["apercu"][:60])] for r in rows],
            [3.0, 3.4, 2.6, 7.0]),
            Paragraph(f"Tableau — Extrait de audit.json ({audit['nb_locales']}"
                      f" variables locales, {audit['nb_globales']} globales)."
                      " Les itérateurs lines et records ne pèsent que "
                      "quelques dizaines d'octets : ils ne contiennent pas "
                      "les données.", STYLES["caption"])]

    # 9. Performances -------------------------------------------------------
    story += h1("9. Performances et mémoire")
    story += [
        kpis([(go(run["taille_go"]), "analysés"),
              (f"{run['duree_s'] / 60:.0f} min", "durée de l'analyse"),
              (fmt(run["lignes_par_seconde"]), "lignes / seconde"),
              ("75 s", "génération (7 processus)")]),
        Spacer(1, 0.3 * cm),
        p("La mémoire a été mesurée avec <font name='%s'>tracemalloc</font> "
          "(option <font name='%s'>--trace-memory</font>). Le pic dépend du "
          "nombre de clés distinctes (IP, utilisateurs, heures), qui est "
          "borné, et non de la taille des fichiers :" % (MONO, MONO)),
    ]
    story += figure(draw_memory(tmp / "memory.png"),
                    "Figure 11 — Pic mémoire Python mesuré selon le nombre de "
                    "lignes traitées.", width=13)
    story += [p("Plusieurs choix vont dans ce sens : dédoublonnage par "
                "comparaison avec la seule ligne précédente (un <font name="
                "'%s'>set</font> de 60 millions de lignes occuperait "
                "plusieurs Go), alertes écrites au fil de l'eau dans un CSV "
                "plutôt que gardées en liste, cache <font name='%s'>"
                "lru_cache</font> pour la validation des IP (nombre d'IP "
                "distinctes limité), et raccourci <font name='%s'>"
                "isprintable()</font> qui évite le nettoyage coûteux sur les "
                "lignes déjà propres." % (MONO, MONO, MONO))]

    # 10. Qualité -----------------------------------------------------------
    story += h1("10. Qualité du code et robustesse")
    story += bullets([
        "<b>PEP 8</b> : vérifié avec <font name='%s'>pycodestyle</font>, "
        "aucune erreur." % MONO,
        "<b>Typage vérifié</b> : annotations sur toutes les fonctions, "
        "<font name='%s'>TypedDict</font> pour les enregistrements et les "
        "alertes, alias <font name='%s'>Connection = tuple[str, int, str]"
        "</font>. <font name='%s'>mypy</font> contrôle tout le projet "
        "(code et tests) : <b>0 erreur</b>. Il avait relevé 6 imprécisions "
        "réelles, corrigées (par exemple une variable pouvant valoir "
        "<font name='%s'>None</font>)." % (MONO, MONO, MONO, MONO),
        "<b>Tests automatiques</b> : <b>%d tests pytest</b>, un fichier par "
        "module : réparation des lignes sales, motifs <font name='%s'>match"
        "</font>, opérations ensemblistes, sortie par <font name='%s'>break"
        "</font> ou par le <font name='%s'>else</font> de la boucle de "
        "détection, transmission des <font name='%s'>**kwargs</font> aux "
        "règles, isolation d'une règle défaillante, suivi temps réel, et un "
        "test de bout en bout qui génère un jeu de données puis exécute tout "
        "le pipeline." % (TESTS_COUNT, MONO, MONO, MONO, MONO),
        "<b>Exceptions</b> : aucune donnée sale ne fait planter le pipeline ; "
        "<font name='%s'>try / except / else</font> dans le moteur de "
        "règles, gestion des fichiers manquants à l'ingestion, <font name="
        "'%s'>ValueError</font> gérées pour les dates et les IP." %
        (MONO, MONO),
        "<b>Clauses else des boucles</b> : dans la détection de force brute "
        "et dans l'histogramme des latences.",
        "<b>Reproductibilité</b> : générateur à graine fixe (<font name='%s'>"
        "--seed</font>), environnement figé par <font name='%s'>"
        "requirements.txt</font>, historique Git." % (MONO, MONO),
    ])

    # 11. Limites ------------------------------------------------------------
    story += h1("11. Limites et améliorations possibles")
    story += bullets([
        f"<b>Analyse parallèle</b> : l'analyse tourne sur un seul processus "
        f"({run['duree_s'] / 60:.0f} min pour {go(run['taille_go'])}). "
        "Traiter chaque fichier dans un processus puis fusionner les "
        "compteurs diviserait ce temps par 5 à 6 sur 8 cœurs, au prix "
        "d'attaques coupées entre deux fichiers.",
        "<b>Campagnes d'attaque</b> : une IP qui attaque plusieurs fois sur "
        "30 jours produit un seul incident ; on pourrait les séparer par "
        "période d'inactivité.",
        "<b>Doublons</b> : seuls les doublons consécutifs sont détectés.",
        "<b>Stack traces</b> : elles sont supprimées ; elles pourraient être "
        "rattachées à la ligne d'erreur qui les précède.",
    ])

    # 12. Conclusion ---------------------------------------------------------
    story += h1("12. Conclusion")
    story += [
        p(f"Le moteur traite {go(run['taille_go'])} de logs "
          "hétérogènes et volontairement dégradés avec une "
          "empreinte mémoire de quelques dizaines de mégaoctets, grâce à une "
          "chaîne de générateurs et de fonctions d'ordre supérieur. Le "
          f"nettoyage récupère l'essentiel des lignes abîmées ({fmt(fixed)} "
          "corrections) et n'écarte que les lignes inexploitables, en "
          "documentant chaque cause."),
        p(f"L'analyse retrouve les phénomènes injectés : cycle d'activité, "
          f"pannes, DDoS, {fmt(ips['blacklist_actives'])} IP de la liste "
          f"noire actives, {fmt(brute['nb_incidents'])} IP menant des "
          f"attaques par force brute dont {brute['nb_comptes_compromis']} "
          "ont réussi, ainsi que les injections et les scans. Le moteur de "
          "règles et l'audit par introspection rendent l'ensemble extensible "
          "et observable."),
        p("Ce projet nous a permis de mettre en pratique les notions du "
          "cours (générateurs, programmation fonctionnelle, structures de "
          "données, pattern matching, arguments variables, introspection) "
          "sur un cas réaliste où la contrainte de volume impose de bien les "
          "utiliser."),
    ]
    return story


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère le rapport PDF")
    parser.add_argument("--results", type=Path, default=ROOT / "output")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "docs" / "rapport" /
                        "Rapport_projet_logs.pdf")
    args = parser.parse_args()
    charts = args.results / "charts"
    tmp = args.out.parent / "_figures"
    tmp.mkdir(parents=True, exist_ok=True)
    doc = Report(str(args.out), pagesize=A4, leftMargin=2.5 * cm,
                 rightMargin=2.5 * cm, topMargin=2 * cm, bottomMargin=2.2 * cm,
                 title="Engine de traitement et d'analyse de logs",
                 author=", ".join(TEAM))
    doc.multiBuild(build_story(args.results, charts, tmp),
                   onFirstPage=on_page, onLaterPages=on_page)
    print(f"Rapport écrit : {args.out}")


if __name__ == "__main__":
    main()
