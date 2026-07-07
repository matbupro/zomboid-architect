"""config — Settings du module de génération de mods.

Charge la configuration depuis l'environnement (.env) ou les valeurs par défaut.
Suit le même pattern que bot/config.py et ingestor/config.py (dataclass + load_config()).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Types de mods disponibles (liste simple en module-level pour éviter import circulaire)
_MOD_TYPES = ["item", "feature", "ui", "script", "zombie", "vehicle"]


@dataclass
class ModGenConfig:
    """Configuration centralisée du moteur de génération de mods."""

    # Output path — ou placer les mods générés
    output_path: Path = field(default_factory=lambda: Path("mods"))

    # Template directory — ou trouver les templates Jinja2
    templates_path: Path = field(
        default_factory=lambda: Path(__file__).parent / "templates"
    )

    # Valeurs par défaut pour les champs des mods générés
    default_author: str = "Zomboid Architect"
    default_game_version: str = "Build42"
    default_script_dir: str = ""  # vide = scripts racine

    # Types de mods supportes (synchronise avec src.modgen.schema.ModType)
    supported_types: list[str] = field(default_factory=lambda: list(_MOD_TYPES))

    # Auto-escape pour Jinja2
    template_autoescape: bool = True


def load_modgen_config(**overrides: object) -> ModGenConfig:
    """Charge la configuration depuis l'environnement ou les valeurs par défaut.

    Args:
        **overrides: Valeurs explicites qui surchargent les variables d'environnement.

    Returns:
        ModGenConfig chargé depuis .env > overrides > default values.
    """
    kwargs = {}
    for key in ("output_path", "templates_path", "default_author", "default_game_version", "default_script_dir"):
        env_key = f"MOD_{key.upper()}"
        val = overrides.get(key, os.getenv(env_key))
        if val is not None:
            kwargs[key] = Path(val) if key in ("output_path", "templates_path") else val
    return ModGenConfig(**kwargs)
