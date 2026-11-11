"""Module 1 — Ingestion : lecture paresseuse (lazy) des fichiers de logs.

Rien n'est chargé entièrement en mémoire : chaque fonction est un
générateur qui fournit UNE ligne à la fois, uniquement quand la boucle
suivante la demande.
"""

import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path


def list_log_files(directory: Path) -> list[Path]:
    """Renvoie les fichiers ``*.log`` d'un dossier, triés par nom (donc par
    date, puisque le nom contient la date de début)."""
    return sorted(directory.glob("*.log"))


def read_log_file(path: Path) -> Iterator[str]:
    """Lit un fichier ligne par ligne, à la demande, grâce à ``yield``.

    - ``errors="replace"`` : un octet invalide en UTF-8 devient "\\ufffd"
      au lieu de faire planter la lecture ; le nettoyage le supprimera.
    - ``newline=""`` : on garde les "\\r" tels quels pour les nettoyer
      nous-mêmes (sinon Python les convertirait sans qu'on le voie).
    """
    with open(path, encoding="utf-8", errors="replace", newline="") as file:
        for line in file:
            yield line


def read_sources(paths: Iterable[Path]) -> Iterator[str]:
    """Enchaîne plusieurs fichiers comme un seul flux, avec ``yield from``.

    ``yield from read_log_file(path)`` délègue au sous-générateur : chaque
    ligne qu'il produit est directement transmise à l'appelant.
    """
    for path in paths:
        try:
            yield from read_log_file(path)
        except (FileNotFoundError, PermissionError) as exc:
            print(f"[ingestion] fichier ignoré ({exc.__class__.__name__}) : "
                  f"{path}", file=sys.stderr)


def with_progress(lines: Iterable[str],
                  every: int = 1_000_000) -> Iterator[str]:
    """Laisse passer les lignes telles quelles en affichant l'avancement.

    C'est un exemple d'étape "transparente" dans une chaîne de générateurs :
    elle ne modifie rien, elle observe le flux.
    """
    started = time.perf_counter()
    count = 0
    for count, line in enumerate(lines, start=1):
        if count % every == 0:
            elapsed = time.perf_counter() - started
            print(f"\r[ingestion] {count:,} lignes lues "
                  f"({count / elapsed:,.0f} lignes/s)", end="",
                  file=sys.stderr, flush=True)
        yield line
    if count >= every:
        print(file=sys.stderr)
