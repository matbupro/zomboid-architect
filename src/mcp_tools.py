"""MCP Tools — declarations pour Claude Code / Anthropic SDK.

Expose les fonctions appelables par Claude Code comme outils MCP (Model Context Protocol).
Chaque outil est une fonction Python standard avec un docstring de description qui sert de schema JSON Schema.

Usage:
    from src.mcp_tools import pz_get_item, pz_generate_mod_template, pz_search_all

    # Via Anthropic SDK tool_use:
    client.messages.create(
        model="claude-sonnet-5",
        messages=[...],
        tools=[
            {"name": "pz_get_item", "description": "...", "input_schema": {...}},
            {"name": "pz_generate_mod_template", ...},
        ],
    )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent


# =====================================================================
# pz_get_item — Lookup deterministe par ID Zomboid
# =====================================================================

def pz_get_item(
    item_id: str,
    collection: str = "pz_items",
    game_version: str | None = None,
) -> dict[str, Any]:
    """Lookup deterministic d'un objet Project Zomboid par son identifiant.

    Retourne les stats exactes de l'objet (dommages, durabilite, poids, etc.)
    sans recherche vectorielle. Utilise pour des reponses 100% precisees sur les donnees du jeu.

    Args:
        item_id: Identifiant deterministe (ex: "Base.Axe", "Recipe.Hatchet")
        collection: Collection du stockage vectoriel cible ("pz_items" par defaut)
        game_version: Version cible du jeu ("b41", "b42", ou None pour toutes)

    Returns:
        Dict avec les donnees de l'objet, ou {"error": "..."} si non trouve.
    """
    from src.governance.logger import get_logger
    from src.retrieval import get_production_client  # type: ignore[misc]

    logger = get_logger("mcp.pz_get_item")

    try:
        client = get_production_client()  # type: ignore[assignment]
        result = client.get_by_id(item_id, collection=collection, game_version=game_version)
        if result is None:
            return {"error": f"Objet non trouve: {item_id} dans {collection}"}
        return {
            "id": result.id,
            "collection": result.collection,
            "prose": result.prose,
            "metadata": result.metadata_,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("pz_get_item(%s) error: %s", item_id, exc)
        return {"error": f"Erreur technique lors de la récupération (ID: {item_id}): {str(exc)}"}


# =====================================================================
# pz_search_all — Recherche semantique libre sur toutes les collections
# =====================================================================

def pz_search_all(
    query: str,
    n_results: int = 5,
    game_version: str | None = None,
) -> dict[str, Any]:
    """Recherche semantique libre sur le knowledge engine.

    Cherche dans pz_items, pz_recipes et pz_mechanics simultanement.
    Utilise l'embedding pour trouver les resultats les plus pertinents.

    Args:
        query: Requete en langage naturel (ex: "comment faire une hache")
        n_results: Nombre de resultats a retourner (max 20)
        game_version: Filtre par version du jeu ("b41", "b42", ou None)

    Returns:
        Dict avec les resultats tries par pertinence.
    """
    from src.governance.logger import get_logger
    from src.retrieval import get_production_client  # type: ignore[misc]

    logger = get_logger("mcp.pz_search_all")

    try:
        client = get_production_client()  # type: ignore[assignment]
        collections = [c for c in client.list_collections()]
        results = client.query(
            queries=[(c, query) for c in collections],
            n_results=min(n_results, 20),
            game_version=game_version,
        )
        return {
            "query": query,
            "results": [
                {
                    "id": r.id,
                    "collection": r.collection,
                    "prose": r.prose[:500],
                    "metadata": r.metadata_,
                }
                for r in results
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("pz_search_all(%s) error: %s", query, exc)
        return {"error": f"Erreur technique lors de la recherche (Query: {query}): {str(exc)}"}


# =====================================================================
# pz_generate_mod_template — Generation de mod Project Zomboid
# =====================================================================

def pz_generate_mod_template(
    description: str,
    mod_name: str | None = None,
    features: list[str] | None = None,
) -> dict[str, Any]:
    """Genere un mod Project Zomboid a partir d'une description textuelle.

    Cree automatiquement la structure de dossier valide PZ avec:
    - mod.info (manifest JSON)
    - init.lua (point d'entrée)
    - media/lua/shared/ (scripts Lua partages)
    - media/lua/client/ ou server/ (code client/server)
    - ZomboidModDescriptor.txt (descriptor Steam Workshop)

    Args:
        description: Description haute-niveau du mod (ex: "Ajouter une epée avec 45 degats")
        mod_name: Nom du mod (optionnel, auto-extrait si absent)
        features: Liste de fonctionnalites souhaitees (optionnelle)

    Returns:
        Dict avec les chemins des fichiers generes et le manifest du mod.
    """
    from pathlib import Path as P
    from src.modgen import generate_mod_from_description  # type: ignore[import-not-found]

    output_dir = PROJECT_ROOT / "mods"
    output_dir.mkdir(exist_ok=True)

    try:
        # Parse the description via LLM-powered generator
        manifest = generate_mod_from_description(
            description=description,
            mod_type="item",  # peut etre ameliore avec LLM pour deteecter le type
            name=mod_name,
            author="Zomboid Architect",
            output_dir=P(str(output_dir)),
        )

        files_list = []
        for f in sorted(manifest.mod_root.rglob("*")):
            if f.is_file():
                rel = f.relative_to(manifest.output_path)
                files_list.append(str(rel))

        return {
            "mod_id": manifest.id,
            "mod_name": manifest.name,
            "output_path": str(manifest.output_path),
            "file_count": manifest.file_count,
            "files": files_list,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Erreur de generation du mod: {exc}", "description": description}


# =====================================================================
# Ressources Markdown fixes (prompts systemiques)
# =====================================================================

def pz_get_mechanic(mechanic_id: str) -> dict[str, Any]:
    """Recupere les donnees d'une mecanique de jeu Project Zomboid.

    Ex: "Mechanic.Panic", "Mechanic.DistanceVision", "Mechanic.Farming"

    Args:
        mechanic_id: Identifiant de la mecanique (ex: "Mechanic.Panic")
    """
    from src.retrieval import get_production_client  # type: ignore[misc]

    try:
        client = get_production_client()  # type: ignore[assignment]
        result = client.get_by_id(mechanic_id, collection="pz_mechanics")
        if result is None:
            return {"error": f"Mecanique non trouvee: {mechanic_id}"}
        return {
            "id": result.id,
            "prose": result.prose,
            "metadata": result.metadata_,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def pz_get_recipe(recipe_id: str) -> dict[str, Any]:
    """Recupere les details de fabrication d'un objet Project Zomboid.

    Ex: "Recipe.Hatchet", "Recipe.BreadFromWheat"

    Args:
        recipe_id: Identifiant de la recette
    """
    from src.retrieval import get_production_client  # type: ignore[misc]

    try:
        client = get_production_client()  # type: ignore[assignment]
        result = client.get_by_id(recipe_id, collection="pz_recipes")
        if result is None:
            return {"error": f"Recette non trouvee: {recipe_id}"}
        return {
            "id": result.id,
            "prose": result.prose,
            "metadata": result.metadata_,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def pz_get_moddoc(api_name: str) -> dict[str, Any]:
    """Recherche de documentation modding Lua/Java pour Project Zomboid.

    Ex: "IsoPlayer", "crafting", "ZomboidModDescriptor"

    Args:
        api_name: Nom de l'API ou fonction recherchee
    """
    from src.retrieval import get_production_client  # type: ignore[misc]

    try:
        client = get_production_client()  # type: ignore[assignment]
        results = client.query(
            queries=[("pz_lua_api", api_name), ("pz_java_api", api_name)],
            n_results=5,
        )
        return {
            "query": api_name,
            "results": [
                {"id": r.id, "prose": r.prose[:1000], "metadata": r.metadata_}
                for r in results
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def pz_get_guide(guide_id: str) -> dict[str, Any]:
    """Recupere un guide de connaissance structure (ex: lua_debug_guide).

    Ce guide provient d'une collection specialisee 'pz_guides'.
    Supporte l'ID exact ou une recherche par nom de fichier.

    Args:
        guide_id: Identifiant du guide (ex: 'lua_decode_guide')
    """
    from src.retrieval import get_production_client  # type: ignore[misc]
    from types import SimpleNamespace

    try:
        client = get_production_client()  # type: ignore[assignment]
        # 1. Tentative par ID exact
        result = client.get_by_id(guide_id, collection="pz_guides")

        # 2. Fallback : Recherche semantique si l'ID exact echoue (pour gerer les prefixes de chemin)
        if result is None:
            search_results = client.query("pz_guides", guide_id, n_results=1)
            chunks = search_results.get("chunks", [])
            if chunks:
                chunk = chunks[0]
                # On reconstruit un objet compatible
                result = SimpleNamespace(
                    id=chunk["id"],
                    prose=chunk["prose"],
                    metadata_=chunk["metadata"]
                )

        if result is None:
            return {"error": f"Guide non trouve: {guide_id}"}

        return {
            "id": result.id,
            "prose": result.prose,
            "metadata": result.metadata_,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}



# =====================================================================
# Export public
# =====================================================================

__all__ = [
    "pz_get_item",
    "pz_search_all",
    "pz_generate_mod_template",
    "pz_get_mechanic",
    "pz_get_recipe",
    "pz_get_moddoc",
    "pz_get_guide",
]
