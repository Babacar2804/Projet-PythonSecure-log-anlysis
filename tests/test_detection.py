"""Module 3 : détection de force brute."""

from logengine.detection import BruteForceDetector
from tests.helpers import login


def test_ip_suspecte_au_cinquieme_echec() -> None:
    detector = BruteForceDetector(threshold=5, window_seconds=120)
    signals = [detector.feed(login(second)) for second in range(5)]
    assert signals == [None, None, None, None, "suspect"]


def test_succes_apres_attaque_compromis() -> None:
    detector = BruteForceDetector(threshold=5)
    for second in range(6):
        detector.feed(login(second))
    assert detector.feed(login(10, success=True)) == "compromis"
    [incident] = detector.summarize()
    assert incident["statut"] == "COMPROMIS"        # sortie par break
    assert incident["severite"] == "CRITICAL"
    assert incident["compte_compromis"] == "admin"


def test_attaque_sans_succes_bloquee() -> None:
    detector = BruteForceDetector(threshold=5)
    for second in range(8):
        detector.feed(login(second))
    [incident] = detector.summarize()
    assert incident["statut"] == "bloquee"          # clause else du for


def test_echecs_trop_espaces_ignores() -> None:
    # 1 échec toutes les 3 minutes : la boucle while purge la fenêtre
    detector = BruteForceDetector(threshold=5, window_seconds=120)
    for minute in range(0, 30, 3):
        detector.feed(login(0, minute=minute))
    assert detector.summarize() == []


def test_credential_stuffing() -> None:
    detector = BruteForceDetector(threshold=5)
    for second in range(6):
        detector.feed(login(second, user=f"u{second}"))
    [incident] = detector.summarize()
    assert incident["type"] == "credential_stuffing"


def test_ip_de_confiance_ignoree() -> None:
    detector = BruteForceDetector(threshold=5,
                                  whitelist=frozenset({"185.1.2.3"}))
    for second in range(6):
        detector.feed(login(second))
    assert detector.summarize() == []               # continue
