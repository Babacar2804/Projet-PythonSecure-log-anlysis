"""Module 4 — Audit par introspection avec ``globals()`` et ``locals()``.

- ``globals()`` : dictionnaire des noms définis au niveau du module
  (imports, fonctions, constantes...).
- ``locals()``  : dictionnaire des variables locales de la fonction en
  cours d'exécution, au moment de l'appel.

On les reçoit en paramètre (c'est l'appelant qui fait ``globals()`` /
``locals()``, sinon on inspecterait la portée de ce module-ci).
"""

import json
import reprlib
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

# reprlib limite la taille des aperçus : faire repr() d'un dict de 15 000
# IP produirait une chaîne énorme, reprlib s'arrête après quelques éléments.
_short = reprlib.Repr()
_short.maxstring = 80
_short.maxother = 80
_short.maxlist = _short.maxdict = _short.maxset = 5


def describe_scope(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Décrit chaque variable d'une portée : nom, type, taille, aperçu."""
    rows = []
    for name, value in sorted(scope.items()):
        if name.startswith("__"):           # __name__, __doc__, ...
            continue
        if isinstance(value, types.ModuleType):
            kind = "module"
        elif callable(value):
            kind = "fonction/classe"
        else:
            kind = "donnée"
        rows.append({
            "nom": name,
            "categorie": kind,
            "type": type(value).__name__,
            # getsizeof = taille de l'objet lui-même (pas de son contenu)
            "taille_octets": sys.getsizeof(value),
            "longueur": len(value) if hasattr(value, "__len__") and
            not isinstance(value, type) else None,
            "apercu": _short.repr(value),
        })
    return rows


def export_audit_report(path: Path, global_scope: dict[str, Any],
                        local_scope: dict[str, Any],
                        **extra: Any) -> dict[str, Any]:
    """Écrit le rapport d'audit au format JSON et le renvoie."""
    report = {
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "nb_globales": len(global_scope),
        "nb_locales": len(local_scope),
        "globales": describe_scope(global_scope),
        "locales": describe_scope(local_scope),
        **extra,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False, default=str)
    return report
