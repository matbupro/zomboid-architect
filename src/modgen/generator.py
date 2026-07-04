"""generator — Moteur principal de generation de mods Zomboid.

Generateur de mods valide selon la structure PZ (mod.info, media/lua/, etc.).
Utilise Jinja2 pour les templates et cree automatiquement le scaffolding complet.

Usage programmatique :
    config = ModConfig(output_dir=Path("mods"))
    generator = ModGenerator(config)
    spec = ModSpec(name="MonMod", description="Un mod cool")
    manifest = asyncio.run(generator.generate(spec))
    print(f"Mod cree dans : {manifest.output_path}")
"""

from __future__ import annotations

import datetime
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jinja2

from src.governance.logger import get_logger
from src.modgen.config import ModGenConfig, load_modgen_config
from src.modgen.schema import (
    ModFile,
    ModSpec,
    ModType,
    GeneratedModManifest,
    _build_mod_id,
)

logger = get_logger("modgen")


# ---------------------------------------------------------------------------
# Validation des noms de mods (PZ constraints)
# ---------------------------------------------------------------------------

_INVALID_NAME_CHARS = set(r'\/:*?"<>|')


def _validate_name(name: str) -> list[str]:
    """Valide un nom de mod — retourne une liste d'erreurs (vide = ok)."""
    errors: list[str] = []
    if not name or not name.strip():
        errors.append("Le nom du mod ne peut pas etre vide.")
        return errors
    for char in _INVALID_NAME_CHARS:
        if char in name:
            errors.append(f"Le caractere '{char}' n'est pas permis dans un nom de mod.")
            break
    if len(name) > 128:
        errors.append("Le nom du mod ne doit pas depasser 128 caracteres.")
    return errors


def _validate_spec(spec: ModSpec) -> list[str]:
    """Valide une ModSpec — retourne la liste des erreurs (vide = valide)."""
    errors = _validate_name(spec.name)
    if len(spec.description) > 500:
        errors.append("La description ne doit pas depasser 500 caracteres.")
    valid_types = [t.value for t in ModType]
    if spec.mod_type not in valid_types:
        errors.append(f"Type de mod invalide. Types accepts : {valid_types}")
    return errors


# ---------------------------------------------------------------------------
# Moteur principal
# ---------------------------------------------------------------------------


class ModGenerator:
    """Genere un dossier mod Project Zomboid valide a partir d'une ModSpec.

    Crée automatiquement la structure complete :
        mod_root/
            mod.info          (manifest JSON)
            ZomboidModDescriptor.txt (Steam Workshop metadata)
            README.md         (documentation auto-generée)
            media/lua/client/  (scripts clients)
            media/lua/shared/  (code shared)
            media/lua/server/  (scripts serveur)

    Les scripts sont remplis via templates Jinja2 predefinis.
    """

    def __init__(self, config: ModGenConfig | None = None) -> None:
        """Initialise le generateur avec sa configuration.

        Args:
            config: Configuration du generateur. Defaut charge depuis .env + valeurs par defaut.
        """
        from src.modgen.config import load_modgen_config  # lazy import

        self._config = config or load_modgen_config()
        self._templates_dir = self._config.templates_path

        # Charge l'environment Jinja2
        loader = jinja2.FileSystemLoader(str(self._templates_dir))
        self._env: jinja2.Environment = jinja2.Environment(
            loader=loader,
            autoescape=self._config.template_autoescape,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # Ajoute les filtres personnalisés
        self._env.globals["lower"] = lambda x: str(x).lower()

    # -- Propriétés de configuration accessible ---

    @property
    def config(self) -> ModGenConfig:
        return self._config

    @property
    def templates_dir(self) -> Path:
        return self._templates_dir

    # -- Méthodes publiques --

    async def generate(self, spec: ModSpec) -> GeneratedModManifest:
        """Genere un dossier mod complet a partir d'une specification.

        Args:
            spec: Specification haute-niveau du mod (nom, type, scripts, …).

        Returns:
            GeneratedModManifest avec le chemin absolu du dossier cree.

        Raises:
            ValueError: Si la spec ne passe pas la validation.
        """
        # Validation
        errors = _validate_spec(spec)
        if errors:
            raise ValueError("Validation echouée :\n" + "\n".join(f"  - {e}" for e in errors))

        # Construit l'ID canonique du mod
        mod_id = _build_mod_id(spec.name, spec.mod_type)
        output_dir = self._config.output_path / mod_id

        # Crée la structure de dossiers
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Creation du dossier mod : %s", output_dir)

        # Récupère le chemin relatif des scripts (media/lua/<script_dir>/)
        script_dir_rel = f"scripts/{spec.script_dir}" if spec.script_dir else "scripts"

        # Collecte TOUS les fichiers a écrire
        all_files: list[ModFile] = []

        # mod.info (généré dynamiquement, pas template)
        mod_info_content = self._render_mod_info(spec)
        all_files.append(ModFile("mod.info", mod_info_content))

        # ZomboidModDescriptor.txt
        descriptor_content = self._env.get_template("ZomboidModDescriptor.txt.j2").render(
            spec=spec,
            tags_csv=", ".join(spec.tags),
        )
        all_files.append(ModFile("ZomboidModDescriptor.txt", descriptor_content))

        # README.md
        readme_content = self._env.get_template("README.md.j2").render(
            spec=spec,
            tags_csv=", ".join(spec.tags),
        )
        all_files.append(ModFile("README.md", readme_content))

        # init.lua (template)
        # Quand script_dir est vide, le dossier de scripts est juste "scripts/" (pas "scripts/scripts/")
        init_script_dir = f"{script_dir_rel}/" if spec.script_dir else "scripts/"
        init_lua_content = self._env.get_template("init.lua.j2").render(
            spec=spec,
            script_dir=init_script_dir,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            client_scripts=spec.client_scripts or [],
        )
        all_files.append(ModFile(f"media/lua/client/{script_dir_rel}/init.lua", init_lua_content))

        # Squelette media/ (dossiers vides si aucun script)
        for sub in ["client", "shared", "server"]:
            (output_dir / "media" / "lua" / sub).mkdir(parents=True, exist_ok=True)

        # --- Ajout des scripts par type ---
        script_files = self._generate_script_files(spec, script_dir_rel)
        all_files.extend(script_files)

        # Ecrit tous les fichiers
        file_count = 0
        for mod_file in all_files:
            full_path = output_dir / mod_file.relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(mod_file.content, encoding="utf-8")
            file_count += 1

        logger.info("Mod '%s' genere — %d ecrits, %d scripts", spec.name, file_count, len(all_files))

        return GeneratedModManifest(
            id=mod_id,
            name=spec.name,
            output_path=output_dir,
            spec=spec,
            file_count=file_count,
        )

    def _render_mod_info(self, spec: ModSpec) -> str:
        """Genere le contenu JSON de mod.info."""
        # Prepare tags array for JSON
        tags_list = json.dumps(spec.tags) if spec.tags else "[]"

        content = self._env.get_template("mod.info.j2").render(
            spec=spec,
            script_dir=f"scripts/{spec.script_dir}/" if spec.script_dir else "scripts/",
            tags_json=tags_list,
        )
        # Validate generated JSON
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("mod.info JSON invalide : %s", exc)
            raise

        return content

    def _generate_script_files(
        self, spec: ModSpec, script_dir_rel: str
    ) -> list[ModFile]:
        """Genere les fichiers de scripts Lua (client, shared, server)."""
        files: list[ModFile] = []

        # Scripts clients (template client_script.lua.j2)
        for i, script_name in enumerate(spec.client_scripts or []):
            feature_data = spec.features[i] if spec.features and i < len(spec.features) else None
            features_json = json.dumps(feature_data, ensure_ascii=False) if feature_data else "[]"
            content = self._env.get_template("client_script.lua.j2").render(
                mod_name=spec.name,
                script_dir=script_dir_rel,
                script_name=script_name.replace(".lua", ""),
                description=spec.description or f"Client script for {spec.name}",
                features_json=features_json,
            )
            files.append(ModFile(f"media/lua/client/{script_dir_rel}/{script_name}", content))

        # Scripts shared (template shared_script.lua.j2)
        for i, script_name in enumerate(spec.shared_scripts or []):
            feature_data = spec.features[i] if spec.features and i < len(spec.features) else None
            features_json = json.dumps(feature_data, ensure_ascii=False) if feature_data else "[]"
            content = self._env.get_template("shared_script.lua.j2").render(
                mod_name=spec.name,
                script_dir=script_dir_rel,
                script_name=script_name.replace(".lua", ""),
                features_json=features_json,
            )
            files.append(ModFile(f"media/lua/shared/{script_dir_rel}/{script_name}", content))

        # Scripts serveur (template server_script.lua.j2)
        for i, script_name in enumerate(spec.server_scripts or []):
            feature_data = spec.features[i] if spec.features and i < len(spec.features) else None
            features_json = json.dumps(feature_data, ensure_ascii=False) if feature_data else "[]"
            content = self._env.get_template("server_script.lua.j2").render(
                mod_name=spec.name,
                script_dir=script_dir_rel,
                script_name=script_name.replace(".lua", ""),
                features_json=features_json,
            )
            files.append(ModFile(f"media/lua/server/{script_dir_rel}/{script_name}", content))

        return files

    def validate_spec(self, spec: ModSpec) -> list[str]:
        """Valide une specification et retourne la liste des erreurs."""
        return _validate_spec(spec)

    @classmethod
    def fill_from_description(cls, description: str, mod_type: ModType = ModType.ITEM) -> ModSpec:
        """Genere automatiquement un ModSpec a partir d'une description textuelle.

        Utilise le LLM (via config optionnelle) pour structurer la description en fields.
        Sans LLM configuré, cree une spec minimaliste avec les champs par defaut.

        Args:
            description: Description naturelle haute-niveau.
            mod_type: Type du mod.

        Returns:
            ModSpec pre-rempli avec le nom extrait et la description parsee.
        """
        # Extraction simple de nom depuis description si pas explicitement donne
        name = description.strip()[:64]  # Utiliser description comme nom par defaut
        return ModSpec(
            name=name,
            description=description,
            mod_type=mod_type,
            author="Zomboid Architect",
        )

    def list_templates(self) -> list[str]:
        """Retourne la liste des templates disponibles."""
        return self._env.list_templates()


# ---------------------------------------------------------------------------
# Fonction de commodité — generation rapide sans configuration explicite
# ---------------------------------------------------------------------------


async def generate_mod(
    spec: ModSpec,
    output_dir: Path | None = None,
    templates_path: Path | None = None,
) -> GeneratedModManifest:
    """Fonction quick-generate : cree un mod avec la config par defaut.

    Args:
        spec: Specification du mod.
        output_dir: Chemin de sortie (defaut: mods/).
        templates_path: Chemin des templates (defaut: src/modgen/templates/).

    Returns:
        GeneratedModManifest du mod cree.
    """
    from src.modgen.config import load_modgen_config  # lazy import

    config_kwargs = {}
    if output_dir is not None:
        config_kwargs["output_path"] = output_dir
    if templates_path is not None:
        config_kwargs["templates_path"] = templates_path

    config = load_modgen_config(**config_kwargs)
    generator = ModGenerator(config)
    return await generator.generate(spec)


async def generate_mod_from_description(
    description: str,
    mod_type: str = "item",
    name: str | None = None,
    author: str | None = None,
    output_dir: Path | None = None,
) -> GeneratedModManifest:
    """Genere un mod a partir d'une description textuelle courte.

    C'est l'equivalent CLI : python -m src.modgen generate "Une epée en acier"

    Args:
        description: Description haute-niveau (ex: "Ajouter une arme avec 50 degats").
        mod_type: Type du mod (item, feature, ui, script, zombie, vehicle).
        name: Nom explicite (defaut : extrait de la description).
        author: Auteur (defaut: Zomboid Architect).
        output_dir: Repertoire de sortie.

    Returns:
        GeneratedModManifest du mod cree.
    """
    # Resolution du type
    try:
        mt = ModType(mod_type)
    except ValueError:
        available = [t.value for t in ModType]
        raise ValueError(f"Type '{mod_type}' invalide. Types accepts : {available}")

    spec = ModSpec(
        name=name or description.strip()[:64],
        description=description,
        author=author or "Zomboid Architect",
        mod_type=mt,
    )
    return await generate_mod(spec, output_dir=output_dir)


async def zip_mod(manifest: GeneratedModManifest) -> Path:
    """Compresse un mod genere en un fichier ZIP.

    Args:
        manifest: Manifest du mod genere (retour de ModGenerator.generate).

    Returns:
        Chemin du fichier ZIP cree dans le meme dossier que output_dir.
    """
    zip_path = manifest.mod_root.parent / f"{manifest.id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(manifest.mod_root):
            for file in files:
                filepath = Path(root) / file
                arcname = filepath.relative_to(manifest.mod_root.parent)
                zf.write(filepath, arcname)
    logger.info("ZIP cree : %s (%d fichiers)", zip_path, manifest.file_count)
    return zip_path
