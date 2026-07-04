"""config — Settings du module de generation de mods.

Charge la configuration depuis l'environnement (.env) ou les valeurs par defaut.
Suit le meme pattern que bot/config.py et ingestor/config.py (dataclass + load_config()).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Types de mods disponibles (liste simple en module-level pour eviter import circulaire)
_MOD_TYPES = ["item", "feature", "ui", "script", "zombie", "vehicle"]


@dataclass
class ModGenConfig:
    """Configuration centralisee du moteur de generation de mods."""

    # Output path — ou placer les mods generes
    output_path: Path = field(default_factory=lambda: Path("mods"))

    # Template directory — ou trouver les templates Jinja2
    templates_path: Path = field(
        default_factory=lambda: Path(__file__).parent / "templates"
    )

    # Valeurs par defaut pour les champs des mods generes
    default_author: str = "Zomboid Architect"
    default_game_version: str = "Build42"
    default_script_dir: str = ""  # vide = scripts racine

    # Types de mods supportes (synchronise avec src.modgen.schema.ModType)
    supported_types: list[str] = field(default_factory=lambda: list(_MOD_TYPES))

    # Auto-escape pour Jinja2
    template_autoescape: bool = True


def load_modgen_config(**overrides: object) -> ModGenConfig:
    """Charge la configuration depuis l'environnement ou les valeurs par defaut.

    Args:
        **overrides: Valeurs explicites qui surchargent les variables d'environnement.

    Returns:
        ModGenConfig charge depuis .env > overrides > default values.
    """
    kwargs = {}
    for key in ("output_path", "templates_path", "default_author", "default_game_version", "default_script_dir"):
        env_key = f"MOD_{key.upper()}"
        val = overrides.get(key, os.getenv(env_key))
        if val is not None:
            kwargs[key] = Path(val) if key in ("output_path", "templates_path") else val
    return ModGenConfig(**kwargs)
