"""
wikijson — Processeur d'ingestion du PZ Data Drive (Wiki.json / données structurées).

Parse le fichier JSON brut fourni par le data drive officiel de Project Zomboid
(TheIndoor/PZ-wiki-data ou equivalent) et genere des chunks categorises
pour injection dans les collections StorageBackend.

Formats supportes :
  1. Fichier unique (Wiki.json, ~60Mo) — tous les types dans un seul JSON
     Clusters attendus: items, recipes, mobs, crops, skills, weather, maps, ...
  2. Dossier avec fichiers separes (items.json, recipes.json, mobs.json, ...)
  3. URL distante (raw.githubusercontent.com/.../Wiki.json)

Usage :
    from ingestor.processors.wikijson import WikiJsonProcessor
    proc = WikiJsonProcessor("/path/to/wiki/data")
    result = await proc.extract()
    # result.chunks → chunkes par category → storage_writer.write_chunks_to_storage(...)

Mappage des types PZ vers collections :
    items       → pz_items
    recipes     → pz_recipes
    mobs        → pz_mechanics (category='mob')
    crops       → pz_items (subcategory='crop' / pz_mechanics)
    skills      → pz_mechanics (category='skill')
    weather     → pz_mechanics (category='weather')
    maps        → pz_mechanics (category='map')
    building    → pz_items (subcategory='building_material' / pz_recipes)
    vehicles    → pz_items (subcategory='vehicle')
    achievements→ pz_mechanics (category='achievement')
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.governance.logger import get_logger

from .base import Processor, Chunk, ExtractionResult

logger = get_logger(__name__)


# =============================================================================
# Mappage types PZ → collections StorageBackend
# =============================================================================

TYPE_TO_COLLECTION = {
    "items": "pz_items",
    "recipes": "pz_recipes",
    "mobs": "pz_mechanics",
    "crops": "pz_mechanics",
    "skills": "pz_mechanics",
    "weather": "pz_mechanics",
    "maps": "pz_web_pages",
    "building": "pz_items",
    "vehicles": "pz_items",
    "achievements": "pz_mechanics",
    "poi": "pz_web_pages",
    "traps": "pz_items",
    "weapons_melee": "pz_items",
    "weapons_firearms": "pz_items",
    "ammunition": "pz_items",
    "clothing": "pz_items",
    "food": "pz_items",
    "medication": "pz_items",
    "tools": "pz_items",
    "electronics": "pz_items",
    "containers": "pz_items",
    "furniture": "pz_items",
}

# Keys attendues dans le JSON du data drive
# (le processor est tolerant — il detecte les types par keys presentes)
EXPECTED_KEYS = frozenset([
    "items", "recipes", "mobs", "crops", "skills",
    "weather", "maps", "building", "vehicles", "achievements",
])


# =============================================================================
# Parsing interne — normalise chaque type PZ en chunks structurés
# =============================================================================

def _normalize_item(item_data: Any, key: str) -> Chunk:
    """Normalise une definition d'item PZ en chunk lisible."""
    if not isinstance(item_data, dict):
        return None

    lines = []
    lines.append(f"Item: {key}")

    # Fields communs a tous les items PZ
    common_fields = [
        "Name", "displayName", "display_name", "name",
        "Weight", "weight",
        "Type", "type",
        "Categories", "categories", "category",
        "SubCategory", "sub_category", "subcategory",
        "Description", "description", "desc",
        "Icon", "icon",
        "ConditionMax", "condition_max", "conditionmax",
    ]

    for field in common_fields:
        val = item_data.get(field) or item_data.get(field.lower()) or item_data.get(field.title())
        if val is not None:
            lines.append(f"  {field}: {val}")

    # Champs specifiques aux armes
    if any(k in item_data for k in ("DamageTiers", "damage_tiers", "DamageTier1", "DamageTire")):
        damage = item_data.get("DamageTiers") or item_data.get("damage_tiers") or {}
        if isinstance(damage, (list, dict)):
            lines.append(f"  DamageTiers: {json.dumps(damage)}")

    # Champs nutritionnels (food)
    nutrition_fields = ["Calories", "protein", "Protein", "vitamin", "Vitamin",
                        "mineral", "Mineral", "water", "Water"]
    nutrition = {k: item_data.get(k) for k in nutrition_fields if item_data.get(k)}
    if nutrition:
        lines.append(f"  Nutrition: {json.dumps(nutrition)}")

    # Resistance layers (clothing/armor)
    resistance_keys = ["blunt", "cut", "scratch", "tear", "Blunt", "Cut"]
    resistances = {k: item_data.get(k) for k in resistance_keys if item_data.get(k)}
    if resistances:
        lines.append(f"  DamageResistance: {json.dumps(resistances)}")

    # Conditions de la meta
    meta = {"type": "item", "key": key}
    content_text = "\n".join(lines)

    return Chunk(
        text=content_text,
        index=0,
        start_offset=0,
        metadata={**meta, "fields_count": len(item_data)},
    )


def _normalize_recipe(recipe_data: Any, key: str) -> Chunk | None:
    """Normalise une definition de recette PZ en chunk."""
    if not isinstance(recipe_data, dict):
        return None

    lines = []
    lines.append(f"Recipe: {key}")

    # Fields communs recettes
    recipe_fields = [
        ("Name", "name"),
        ("Result", "result", "result_item", "resultItem"),
        ("Time", "time", "duration"),
        ("Category", "category", "categories"),
        ("Ingredients", "ingredients", "ingredient_items"),
        ("SkillRequired", "skill_required", "required_skill"),
        ("ToolsRequired", "tools_required", "required_tools"),
    ]

    for field_pairs in recipe_fields:
        val = None
        for fp in field_pairs:
            if item := recipe_data.get(fp):
                val = item
                break
        if val is not None:
            lines.append(f"  {field_pairs[0]}: {json.dumps(val)}")

    # Special: processing tiers (campfire → brick oven → gas stove → microwave)
    progressions = recipe_data.get("CrossCookProgression") or recipe_data.get(
        "cross_cook_progression") or recipe_data.get("processing_tiers")
    if progressions:
        lines.append(f"  ProcessingTiers: {json.dumps(progressions)}")

    return Chunk(
        text="\n".join(lines),
        index=0,
        start_offset=0,
        metadata={"type": "recipe", "key": key, "fields_count": len(recipe_data)},
    )


def _normalize_mob(mob_data: Any, key: str) -> Chunk | None:
    """Normalise une definition de mob/zombie PZ en chunk."""
    if not isinstance(mob_data, dict):
        return None

    lines = []
    lines.append(f"Mob: {key}")

    mob_fields = [
        ("Name", "name", "displayName", "display_name"),
        ("HP", "hp", "health", "HealthPoints"),
        ("Speed", "speed", "MovementSpeed", "movement_speed"),
        ("Damage", "damage", "BaseDamage", "base_damage"),
        ("Behavior", "behavior", "behaviour", "AI", "ai_type"),
        ("SpawnBiomes", "spawn_biomes", "biome_spawn", "biomes"),
        ("XP", "xp", "Experience", "experience"),
        ("DetectionRadius", "detection_radius", "detect_radius"),
    ]

    for field_pairs in mob_fields:
        val = None
        for fp in field_pairs:
            if v := mob_data.get(fp):
                val = v
                break
        if val is not None:
            lines.append(f"  {field_pairs[0]}: {val}")

    # Drops — souvent une liste ou dict
    drops = mob_data.get("Drops") or mob_data.get("drops", {})
    if drops:
        lines.append(f"  Drops: {json.dumps(drops)}")

    return Chunk(
        text="\n".join(lines),
        index=0,
        start_offset=0,
        metadata={"type": "mob", "key": key, "fields_count": len(mob_data)},
    )


def _normalize_generic(data: Any, key: str, category_type: str) -> Chunk | None:
    """Normalise n'importe quelle donnée PZ (skills, weather, maps, ...) en chunk."""
    if not isinstance(data, dict):
        return None

    lines = []
    lines.append(f"{category_type}: {key}")

    for subkey, value in data.items():
        # Skip internal meta keys
        if subkey.startswith("_"):
            continue
        # Pour les valeurs simples: afficher directement
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"  {subkey}: {value}")
        else:
            # Pour les collections/composés: dump JSON sur une ligne
            lines.append(f"  {subkey}: {json.dumps(value)[:200]}")

    return Chunk(
        text="\n".join(lines),
        index=0,
        start_offset=0,
        metadata={"type": category_type, "key": key, "fields_count": len(data)},
    )


# =============================================================================
# Chargement des données — fichier unique ou dossier multi-fichiers
# =============================================================================

def _load_wiki_data(source: str) -> dict[str, Any]:
    """Charge les donnees du PZ Data Drive depuis un fichier local ou une URL.

    Detection automatique :
    - Si source est un fichier .json existant → parse direct
    - Si source est un dossier → charge tous les .json separes par nom
    - Si source est une URL → wget → parse

    Returns:
        Dict {category_name: {item_key: item_data}} — structure normalisee.
    """
    parsed = urlparse(source)
    is_url = bool(parsed.scheme) and bool(parsed.netloc)

    if is_url:
        logger.info("Chargement du data drive depuis URL : %s", source)
        import httpx
        resp = httpx.get(source, timeout=60.0)
        resp.raise_for_status()
        raw = resp.json()
        return {"_url": source, **raw}

    path = Path(source)

    if path.is_file() and path.suffix.lower() == ".json":
        logger.info("Chargement Wiki.json depuis : %s (%d Ko)", path.name, path.stat().st_size // 1024)
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {"_file": str(path), **raw}

    if path.is_dir():
        logger.info("Chargement des data drives depuis dossier : %s", path)
        result: dict[str, Any] = {}
        json_files = sorted(path.glob("*.json"))
        for jf in json_files:
            key = jf.stem.lower().rstrip("s")  # items.json → item
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                result[key] = data
        return {"_dir": str(path), **result}

    raise FileNotFoundError(f"Source inexistante : {source}")


# =============================================================================
# Processor principal
# =============================================================================

class WikiJsonProcessor(Processor):
    """Processeur du PZ Data Drive (Wiki.json / donnees structurées).

    Parse le JSON brut fourni par TheIndoor/PZ-wiki-data (ou equivalent)
    et genere des chunks categorises pour injection dans StorageBackend.

    S4-c : chunking optimal — split automatique si entity trop grande,
    cross-references en metadata, max_chunk_size configurable.

    Usage :
        proc = WikiJsonProcessor("/path/to/pz-wiki-data")
        result = await proc.extract()
        # result.chunks → [Chunk(...)] avec metadata {"type": "items|recipes|mobs|..."}
    """

    def __init__(self, config, source: str = "", *, max_chunk_words: int = 800, **kwargs):
        super().__init__(config, **kwargs)
        self._source = source
        self._loaded_data: dict[str, Any] | None = None
        # S4-c : parametre chunking (800 mots ≈ ~2500 chars avec tokens embedding)
        self.max_chunk_words = max_chunk_words

    async def extract(self, source: str | None = None) -> ExtractionResult:
        """Extrait et normalise les donnees du PZ Data Drive en chunks.

        Args:
            source: Chemin vers le fichier/folder Wiki.json ou l'URL.
                   Si absent, utilise self._source (defini au __init__).

        Returns:
            ExtractionResult avec chunks categorises et metadata complètes.
        """
        start_time = time.time()
        src = source or self._source

        if not src:
            raise ValueError("WikiJsonProcessor: aucune source fournie")

        # Chargement des donnees (memoisation)
        data = await asyncio.get_event_loop().run_in_executor(None, _load_wiki_data, src)

        all_chunks: list[Chunk] = []
        collection_map: dict[str, set[str]] = {}  # track unique keys per collection

        for category_name, items in data.items():
            # Skip internal metadata keys
            if category_name.startswith("_"):
                continue

            collection = TYPE_TO_COLLECTION.get(category_name, "pz_web_pages")

            # Detecter si c'est un dict {key: data} ou une liste [data]
            if not isinstance(items, dict):
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    items = {str(i): item for i, item in enumerate(items)}
                else:
                    continue

            logger.debug("Processing category '%s' (%d entries) → collection '%s'",
                         category_name, len(items), collection)

            # Mapper chaque entry a son normalizer selon le type
            chunk_fn = self._get_normalizer(category_name)
            for key, item_data in items.items():
                try:
                    chunk = chunk_fn(item_data, key)
                    if chunk is None:
                        continue

                    # S4-c : ajout cross-references en metadata (recipes → items)
                    refs = self._add_cross_references(category_name, item_data, key)
                    if refs:
                        chunk.metadata["cross_refs"] = refs

                    # S4-c : split automatique des chunks excessifs
                    sub_chunks = self._split_large_chunk(chunk, category_name)

                    # Determiner la sous-collection (subcategory) pour les items
                    subcollection = collection
                    if category_name == "items":
                        # Classifier l'item par ses properties
                        item_type = self._classify_item(item_data)
                        subcollection_map = {
                            "weapon_melee": "pz_items",
                            "weapon_firearm": "pz_items",
                            "food": "pz_items",
                            "clothing": "pz_items",
                            "tool": "pz_items",
                            "vehicle": "pz_items",
                            "building_material": "pz_items",
                        }
                        subcollection = subcollection_map.get(item_type, collection)

                    for sc in sub_chunks:
                        all_chunks.append(sc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Erreur processing %s/%s : %s", category_name, key, exc)

        extraction_time_ms = (time.time() - start_time) * 1000
        word_count = sum(len(c.text.split()) for c in all_chunks)

        return ExtractionResult(
            chunks=all_chunks,
            collection="pz_items",  # default — override par caller
            source=src,
            content_type="application/json",
            file_hash=self.compute_hash(json.dumps(data, sort_keys=True)),
            word_count=word_count,
            extraction_time_ms=extraction_time_ms,
            metadata={
                "processor": "wikijson",
                "source_data_size": len(json.dumps(data)) if isinstance(data, (dict, list)) else 0,
                "categories_processed": [k for k in data.keys() if not k.startswith("_")],
                "total_entries": sum(
                    len(v) for v in data.values()
                    if isinstance(v, dict) and len(v) > 0 and not isinstance(next(iter(v)), dict)
                ),
            },
        )

    def _get_normalizer(self, category: str):
        """Retourne la function de normalisation selon la category."""
        normalizers = {
            "items": _normalize_item,
            "recipes": _normalize_recipe,
            "mobs": _normalize_mob,
        }
        # Default pour les autres types → normaliseur generique
        if category in normalizers:
            return normalizers[category]

        fallback_type = {
            "crops": "crop",
            "skills": "skill",
            "weather": "weather",
            "maps": "map",
            "building": "building",
            "vehicles": "vehicle",
            "achievements": "achievement",
            "poi": "poi",
        }.get(category, category)

        return lambda data, key: _normalize_generic(data, key, fallback_type)

    def _classify_item(self, item_data: dict) -> str:
        """Classifie un item par son type pour le routing de collection."""
        item_type = (item_data.get("Type") or item_data.get("type") or "").lower()
        if "weapon" in item_type or "melee" in item_type:
            return "weapon_melee" if "melee" in item_type else "weapon_firearm"
        if "food" in item_type or "canned" in item_type:
            return "food"
        if "clothing" in item_type or "armor" in item_type:
            return "clothing"
        if "vehicle" in item_type:
            return "vehicle"
        if "building" in item_type:
            return "building_material"
        return "generic"

    # S4-c : split sémantique automatique + cross-references


    def _split_large_chunk(self, chunk: Chunk, category_name: str) -> list[Chunk]:
        """Splitte un chunk excessif en sous-chunks sémantiques.

        Utilise les separators logiques (`---`, `###`) comme breakpoints naturels
        pour preserver le sens de chaque sous-chunk.

        S4-c : chaque sub-chunk garde le header contextuel (nom + type) et
        reste ≤ max_chunk_words mots.
        """
        text = chunk.text
        if len(text.split()) <= self.max_chunk_words:
            return [chunk]  # Pas besoin de splitter

        # Tenter de splitter par `---` ou `###` comme sections logiques
        sections = [s.strip() for s in re.split(r'\n-{3,}|\n#{2,}\s', text) if s.strip()]

        if len(sections) <= 1:
            # Fallback : splitter par paragraphes (lignes vides)
            sections = [s.strip() for s in re.split(r'\n\n+', text) if s.strip()]

        # Extrait le header contextuel (premieres lignes avec nom + type)
        header_lines = []
        remaining_sections: list[str] = []
        found_header_end = False
        for sec in sections:
            if not found_header_end and (sec.startswith("Item:") or sec.startswith("Recipe:")
                                         or sec.startswith("Mob:") or "Key:" in sec):
                header_lines.append(sec)
            else:
                found_header_end = True
                remaining_sections.append(sec)

        # Si pas de header detecte, prendre les 2 premieres sections comme header
        if not header_lines and remaining_sections:
            header_lines = [remaining_sections.pop(0)]

        header_ctx = "\n".join(header_lines) + "\n\n" if header_lines else ""

        sub_chunks: list[Chunk] = []
        current_text_parts: list[str] = []
        current_word_count = 0

        for i, section in enumerate(remaining_sections):
            section_words = len(section.split())

            if current_word_count + section_words > self.max_chunk_words and current_text_parts:
                # Flush le chunk courant
                full_text = header_ctx + "\n".join(current_text_parts)
                sub_chunks.append(Chunk(
                    text=full_text,
                    index=i - len(current_text_parts),
                    start_offset=0,
                    metadata={**chunk.metadata, "_split_sub": True, "_max_words": self.max_chunk_words},
                ))
                current_text_parts = []
                current_word_count = 0

            current_text_parts.append(section)
            current_word_count += section_words

        # Flush le dernier chunk
        if current_text_parts:
            full_text = header_ctx + "\n".join(current_text_parts)
            sub_chunks.append(Chunk(
                text=full_text,
                index=len(remaining_sections) - len(current_text_parts),
                start_offset=0,
                metadata={**chunk.metadata, "_split_sub": True, "_max_words": self.max_chunk_words},
            ))

        return sub_chunks if sub_chunks else [chunk]

    def _add_cross_references(self, category_name: str, item_data: dict, key: str) -> dict[str, Any]:
        """Ajoute les cross-references en metadata pour recipes → items.

        S4-c : quand on trouve des ingredients dans une recipe, on inclut
        les keys des items references pour permettre la recherche inverse.
        """
        refs: dict[str, Any] = {}

        if category_name == "recipes":
            # Chercher les fields d'ingredients possibles
            for ing_field in ("Ingredients", "ingredients", "ingredient_items", "required_components"):
                ings = item_data.get(ing_field)
                if ings and isinstance(ings, list):
                    ref_keys = []
                    for ing in ings:
                        if isinstance(ing, dict):
                            ref_keys.append(ing.get("Item") or ing.get("item") or ing.get("key", ""))
                        elif isinstance(ing, str):
                            ref_keys.append(ing)
                    if ref_keys:
                        refs["ingredient_refs"] = [k for k in ref_keys if k]
                elif ings and isinstance(ings, dict):
                    # Format {item_key: quantity}
                    refs["ingredient_refs"] = list(ings.keys())

            # Referencer result item
            for res_field in ("Result", "result", "result_item", "resultItem"):
                res = item_data.get(res_field)
                if res:
                    if isinstance(res, str):
                        refs["result_ref"] = res
                    elif isinstance(res, dict):
                        refs["result_ref"] = res.get("Item") or res.get("item") or res.get("key", "")

        return refs
