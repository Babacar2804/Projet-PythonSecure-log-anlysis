"""Module 1 : lecture paresseuse (yield, yield from, suivi en direct)."""

import inspect
from pathlib import Path

from logengine.ingestion import follow_log_file, read_log_file, read_sources


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="")
    return path


def test_read_log_file_est_un_generateur(tmp_path: Path) -> None:
    path = write(tmp_path / "a.log", "l1\nl2\n")
    lines = read_log_file(path)
    assert inspect.isgenerator(lines)       # rien n'est encore lu
    assert next(lines) == "l1\n"            # une ligne à la demande
    assert list(lines) == ["l2\n"]


def test_read_sources_enchaine_les_fichiers(tmp_path: Path) -> None:
    a = write(tmp_path / "a.log", "a1\na2\n")
    b = write(tmp_path / "b.log", "b1\n")
    assert list(read_sources([a, b])) == ["a1\n", "a2\n", "b1\n"]


def test_read_sources_ignore_un_fichier_manquant(tmp_path: Path) -> None:
    a = write(tmp_path / "a.log", "a1\n")
    assert list(read_sources([tmp_path / "absent.log", a])) == ["a1\n"]


def test_octet_invalide_ne_fait_pas_planter(tmp_path: Path) -> None:
    path = tmp_path / "bad.log"
    path.write_bytes(b"ok \xff\xfe fin\n")
    assert list(read_log_file(path)) == ["ok �� fin\n"]


def test_follow_livre_les_lignes_completes(tmp_path: Path) -> None:
    path = write(tmp_path / "live.log", "l1\nl2\n")
    lines = list(follow_log_file(path, poll_interval=0.01, stop_after=0.3,
                                 from_start=True))
    assert lines == ["l1\n", "l2\n"]


def test_follow_attend_la_fin_de_ligne(tmp_path: Path) -> None:
    # Une ligne sans "\n" est en cours d'écriture : elle n'est pas livrée
    path = write(tmp_path / "live.log", "complete\nmoitie de lig")
    lines = list(follow_log_file(path, poll_interval=0.01, stop_after=0.3,
                                 from_start=True))
    assert lines == ["complete\n"]
