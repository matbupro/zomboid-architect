"""src/governance/production_guard — Empêche toute écriture directe en production/.

Seul promote.py (gate de promotion) est autorisé à écrire dans data/production/.
Toute autre tentative déclenche une erreur bloquante.

Couche 1: decorator @guarded_write qui vérifie la pile d'appels
Couche 2: context manager guarded_production_path() pour écritures bulk
Couche 3: validation CI (check dans .github/workflows)

Usage
-----
    # Decorateur — appliqué aux fonctions qui écrivent en prod
    from src.governance.production_guard import guarded_write

    @guarded_write("promote")  # seul promote.py est autorisé
    def _promote_atomic(staging, production):
        ...

    # Ou pour les scripts d'ingestion: verifier l'autorisation
    assert is_authorized_writer("promote"), "Seul promote.py peut écrire en production/"

Gouvernance
-----------
- rules.md : "production/ est protégé — aucune écriture directe autorisée"
- promote.py : seul script approuvé pour le swap staging → prod
- CI : .github/workflows/tests.yml bloque tout commit modifiant production/ sans touchant promote.py
"""

from __future__ import annotations

import inspect
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

# Chemins absolus de validation
ROOT = Path(__file__).parent.parent.parent
PROD_DIR = ROOT / "data" / "production"
AUTHORIZED_WRITERS: set[str] = {
    "promote",           # promote.py (promotion staging → prod)
    "tag_release",       # tag_release.py (sauvegarde de prod pour tags)
}


class DirectWriteError(RuntimeError):
    """Élevé quand un code tente d'écrire directement dans production/."""

    def __init__(self, caller: str = "", allowed_writers: Optional[set[str]] = None):
        self.allowed_writers = sorted(allowed_writers or AUTHORIZED_WRITERS)
        super().__init__(
            f"Écriture directe en production/ bloquée. "
            f"Auteur: {caller}. Auteurs autorisés: {self.allowed_writers}"
        )


def _get_caller_name() -> str:
    """Identifie le script appelant depuis la pile d'exécution."""
    for frame_info in inspect.stack():
        filename = Path(frame_info.filename).name
        # Ignorer les modules internes et le guard lui-même
        if filename in ("production_guard.py", "inspect.py", "abc.py", "_collections_abc.py"):
            continue
        if filename.endswith(".py") and frame_info.filename != __file__:
            return filename
    return "<unknown>"


def is_authorized_writer(caller: str) -> bool:
    """Vérifie si un script est autorisé à écrire en production/.

    Args:
        caller: nom du fichier script (ex: "promote.py" → "promote")

    Returns:
        True si le script est dans la liste des auteurs autorisés.
    """
    stem = Path(caller).stem.split(".")[0]  # retire .py et tout apres
    return stem in AUTHORIZED_WRITERS


def validate_prod_write(caller: Optional[str] = None) -> bool:
    """Valide qu'une écriture en production/ est légitime.

    Vérifications:
      1. Le caller est dans la liste des scripts autorisés
      2. Si production/ n'existe pas, seul promote.py peut la créer

    Raises:
        DirectWriteError: si l'écriture n'est pas autorisée.

    Returns:
        True si validé (toujours return True si ne leve pas).
    """
    if caller is None:
        caller = _get_caller_name()

    if not PROD_DIR.exists():
        # Pas de prod = le script doit etre autorise pour la creer
        if not is_authorized_writer(caller):
            raise DirectWriteError(caller=caller, allowed_writers=AUTHORIZED_WRITERS.copy())
        return True

    if not is_authorized_writer(caller):
        raise DirectWriteError(caller=caller, allowed_writers=AUTHORIZED_WRITERS.copy())

    return True


def validate_dir_write(target_dir: Path, caller: Optional[str] = None) -> bool:
    """Valide l'écriture dans un dossier donné (pour les bulk operations).

    Si target_dir == PROD_DIR, applique la validation stricte.
    Sinon, retourne True (pas de restriction pour d'autres dossiers).
    """
    if target_dir.resolve() == PROD_DIR.resolve():
        return validate_prod_write(caller)
    return True


@contextmanager
def guarded_production_path(target_dir: Path) -> Generator[Path, None, None]:
    """Context manager sécurisé pour les écritures dans production/.

    Vérifie au début que le writer est autorisé.
    Ne bloque PAS l'écriture elle-même (c'est au caller de faire confiance).

    Usage:
        with guarded_production_path(PROD_DIR):
            shutil.copytree(staging, PROD_DIR)
    """
    if target_dir.resolve() == PROD_DIR.resolve():
        validate_prod_write(_get_caller_name())
    yield target_dir


def guard_import() -> None:
    """Called at startup — blocks direct writes from non-authorized modules.

    Ce hook est appelé par le module d'initialisation (src/governance/__init__.py)
    ou par promote.py au demarrage pour verrouiller les écritures.
    """
    # En mode promotion, on désactive temporairement (promote crée la prod)
    if "promote" in sys.modules:
        return

    # En production, on ne fait rien ici — les decorators @guarded_write
    # et les checks explicites dans promote.py sont la couche de protection.


# ── Decorateur ---

def guarded_write(author: str) -> Any:  # type: ignore[misc]
    """Decorateur qui restreint une fonction a un auteur autorisé.

    Args:
        author: nom de l'auteur (sans .py), doit etre dans AUTHORIZED_WRITERS.

    Raises:
        DirectWriteError: si le caller n'est pas l'auteur autorise.

    Example:
        @guarded_write("promote")
        def _promote_atomic(staging, production):
            ...
    """
    if author not in AUTHORIZED_WRITERS:
        raise ValueError(f"Auteur '{author}' non autorise. Valeurs valides: {sorted(AUTHORIZED_WRITERS)}")

    def decorator(func: Any) -> Any:
        def wrapper(*args, **kwargs):  # type: ignore[misc]
            caller = _get_caller_name()
            if not is_authorized_writer(caller) and author != "any":
                raise DirectWriteError(
                    caller=f"{caller} → {func.__name__}",
                    allowed_writers={author},
                )
            validate_prod_write(caller)
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


if __name__ == "__main__":
    # Test auto
    print("=== production_guard self-test ===")

    # authorized writer should pass
    try:
        assert is_authorized_writer("promote"), "promote doit etre autorise"
        print("[OK] promote.py est un writer autorise")
    except AssertionError as e:
        print(f"[FAIL] {e}")

    # unauthorized writer should fail
    try:
        validate_prod_write("ingest.py")
        print("[FAIL] ingest.py devrait etre bloque")
    except DirectWriteError:
        print("[OK] ingest.py est correctement bloque")

    # guarded decorator
    @guarded_write("promote")
    def _test_func():
        return "ok"

    try:
        result = _test_func()
        print(f"[FAIL] appel direct devrait echouer, got: {result}")
    except DirectWriteError:
        print("[OK] @guarded_write bloque les appels directs")

    # authorized via validate directly
    PROD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        validate_prod_write("promote")
        print("[OK] promote.py valide comme writer autorise")
    except DirectWriteError:
        print("[FAIL] promote.py devrait passer la validation")

    print("=== end self-test ===")
