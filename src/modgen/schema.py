"""schema — Schema de specification d'un mod Zomboid.

Dataclasses centrales representant une specification haute-niveau
d'un mod a generer : ModSpec (contenu) et ModConfig (configuration).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Types de mods supportes
# ---------------------------------------------------------------------------


class ModType(str, Enum):
    """Types de mods supportes par le generateur.

    Chaque type correspond a un schema PZ different :
      item  — Nouvel objet (arme, outil, vetement)
      feature — Nouvelle mecanique de jeu (crafting, combat…)
      ui    — Interface personnalisée
      script — Script general
      zombie — Nouvel ennemi / behavior zombie
      vehicle — Nouvel vehicule
    """

    ITEM = "item"
    FEATURE = "feature"
    UI = "ui"
    SCRIPT = "script"
    ZOMBIE = "zombie"
    VEHICLE = "vehicle"


# ---------------------------------------------------------------------------
# Fichier individuel du mod
# ---------------------------------------------------------------------------


@dataclass
class ModFile:
    """Fichier unique a ecrire dans le mod final."""

    relative_path: str      # Chemin relatif au root du mod (ex: media/lua/client/MyMod.lua)
    content: str            # Contenu texte du fichier
    is_template: bool = False  # True si contenu est un template Jinja2 a render


# ---------------------------------------------------------------------------
# Specification haute-niveau
# ---------------------------------------------------------------------------


@dataclass
class ModSpec:
    """Specification haute-niveau d'un mod a generer.

    Peut etre fourni directement par l'utilisateur ou genere automatiquement
    par le LLM a partir d'une description naturelle (ex: "Ajouter une arme avec 50 degats").

    Args:
        name: Nom affiche du mod (obligatoire).
        description: Description courte du mod.
        author: Auteur par defaut ("Zomboid Architect").
        mod_type: Type de mod, defaut ITEM.
        script_dir: Dossier de scripts dans media/lua/ (defaut "scripts").
        min_game_version: Version minimale compatible (defaut "Build42").
        multiplayer: Compatible multiplayer (defaut True).
        singleplayer: Compatible singleplayer (defaut True).
        files: Fichiers manuels a inclure.
        client_scripts: Listes de scripts Lua clients a generer automatiquement.
        shared_scripts: Listes de scripts Lua shared a generer.
        server_scripts: Listes de scripts Lua serveur a generer.
        features: Fonctionnalites detaillees ({name, type, stats, …}).
        tags: Tags Steam Workshop separes par virgule.
    """

    name: str
    description: str = ""
    author: str = "Zomboid Architect"
    mod_type: ModType = ModType.ITEM
    script_dir: str = "scripts"
    min_game_version: str = "Build42"
    multiplayer: bool = True
    singleplayer: bool = True
    files: list[ModFile] = field(default_factory=list)
    client_scripts: list[str] = field(default_factory=list)
    shared_scripts: list[str] = field(default_factory=list)
    server_scripts: list[str] = field(default_factory=list)
    features: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Nettoyer les champs apres creation."""
        # Convertir les string tags en liste (si CSV passe manuellement)
        if self.tags and isinstance(self.tags, str):
            self.tags = [t.strip() for t in self.tags.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Manifest du mod genere
# ---------------------------------------------------------------------------


@dataclass
class GeneratedModManifest:
    """Represente un mod genere sur le disque."""

    id: str                       # ID canonique (sans espaces ni caracteres speciaux)
    name: str                     # Nom du mod
    output_path: Path             # Chemin absolu du dossier genere
    spec: ModSpec                 # Spec d'origine
    created_at: float = field(default_factory=time.time)
    file_count: int = 0           # Nombre de fichiers ecrits

    @property
    def mod_root(self) -> Path:
        """Alias vers output_path."""
        return self.output_path


def _build_mod_id(name: str, mod_type: ModType) -> str:
    """Construit un ID unique canonique pour un mod.

    Format : modgen_<slug>_<short_uuid>
    Exemple : modgen_custom_weapon_a1b2c3d4
    """
    slug = name.strip().lower().replace(" ", "_")
    # Garder uniquement caracteres alphanumeriques et underscores
    clean = "".join(c for c in slug if c.isalnum() or c == "_")
    short_uuid = uuid.uuid4().hex[:8]
    return f"modgen_{clean}_{short_uuid}"
