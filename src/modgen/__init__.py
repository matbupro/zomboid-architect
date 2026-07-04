"""modgen — Generation de mods Project Zomboid par scaffolding.

Moteur complet pour creer des mods valides depuis une description textuelle :
  1. Parse la description (optionnellement via LLM) en ModSpec structuree
  2. Genere le dossier mod complet (mod.info, init.lua, scripts, ...)
  3. Retourne un GeneratedModManifest pointant vers le resultat

Usage minimal :
    from src.modgen import ModGenerator, ModSpec, ModGenConfig
    config = ModGenConfig()
    generator = ModGenerator(config)
    spec = ModSpec(name="MonMod", description="Un mod cool")
    manifest = asyncio.run(generator.generate(spec))
"""

from __future__ import annotations

from src.modgen.config import load_modgen_config, ModGenConfig
from src.modgen.generator import ModGenerator, generate_mod, generate_mod_from_description, zip_mod
from src.modgen.schema import (
    GeneratedModManifest,
    ModFile,
    ModSpec,
    ModType,
)

__all__ = [
    "GeneratedModManifest",
    "ModFile",
    "ModGenConfig",
    "ModGenerator",
    "ModSpec",
    "ModType",
    "generate_mod",
    "generate_mod_from_description",
    "load_modgen_config",
    "zip_mod",
]
