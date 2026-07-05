"""ingestor/ingest.py — Script global d'ingestion pour le Zomboid Knowledge Engine.

Orchestre l'ensemble du pipeline d'ingestion :
  1. Ingestion de contenu structuré (objets B41/B42 avec métadonnées strictes)
  2. Ingestion de fichiers/répertoires via l'engine multi-format
  3. Batch adaptatif + checkpoints anti-OOM
  4. Validation des métadonnées obligatoires

Usage :
  python -m ingestor.ingest items           # ingérer les données structurées (objets, recettes)
  python -m ingestor.ingest file PATH       # ingestion d'un fichier unique
  python -m ingestor.ingest dir PATH        # ingestion d'un dossier complet
  python -m ingestor.ingest --collections   # afficher les collections existantes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tarfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Generator

# ── Logger ---

from .logger import get_logger

logger = get_logger(__name__)


# ── Configuration par défaut ────────────────────────────────────────────────────

DEFAULT_B41_GAME_PATH = "f:/Games/Steam/steamapps/common/ProjectZomboid"
STAGING_DIR = Path("data/staging")
BATCH_SIZE_DEFAULT = 50        # chunks par batch (adaptatif selon taille mémoire)
MAX_BATCH_BYTES = 10_000_000   # ~10 MB max par batch


# ── Métadonnées strictes ────────────────────────────────────────────────────────

GAME_VERSIONS = frozenset({"b41", "b42"})
VALID_ITEM_TYPES = frozenset({
    "item", "weapon", "food", "drink", "clothing", "tool", "medication",
    "vehicle_part", "ammo", "component", "plant", "meat", "fish",
})

# Champs obligatoires pour toute metadata d'objet PZ
REQUIRED_META_FIELDS = {
    "item_type": str,
    "game_version": str,
    "base_id": str,
}


@dataclass
class MetadataConstraint:
    """Définit les contraintes de métadonnées pour un objet PZ."""
    item_type: str                # item | weapon | food | ...
    game_version: str             # b41 | b42
    base_id: str                  # Base.Axe, Base.Bread, ...
    display_name: str             # "Hatchet"
    description: str              # Description textuelle
    tags: list[str] = field(default_factory=list)
    crafting_category: Optional[str] = None  # weapon | food | clothing | ...
    game_specific: dict[str, Any] = field(default_factory=dict)


def validate_metadata(constraint: MetadataConstraint, meta: dict) -> list[str]:
    """Valide les métadonnées selon le schema strict. Retourne la liste des erreurs."""
    errors: list[str] = []

    for field_name, expected_type in REQUIRED_META_FIELDS.items():
        if field_name not in meta:
            errors.append(f"Champ obligatoire manquant : {field_name}")
        elif not isinstance(meta[field_name], expected_type):
            errors.append(f"{field_name} doit être de type {expected_type.__name__}, "
                         f"got {type(meta[field_name]).__name__}")

    # Validation item_type
    if "item_type" in meta and meta["item_type"] not in VALID_ITEM_TYPES:
        errors.append(f"item_type invalide : {meta['item_type']!r} — attendu dans {VALID_ITEM_TYPES}")

    # Validation game_version
    if "game_version" in meta and meta["game_version"] not in GAME_VERSIONS:
        errors.append(f"game_version invalide : {meta['game_version']!r} — attendu b41|b42")

    return errors


# ── Contenu structuré PZ (objets B41/B42) ──────────────────────────────────────

def get_b41_items() -> list[MetadataConstraint]:
    """Données structurées des objets principaux de la B41 (gameplay core)."""
    return [
        MetadataConstraint(
            item_type="weapon", game_version="b41", base_id="Base.Axe",
            display_name="Axe", description=(
                "Hatchet standard. Outil polyvalent pour couper le bois, "
                "tuer les zombie (50 degats en un coup), et se défendre en combat rapproché. "
                "Se degrade avec l'utilisation. Plus efficace que la machette contre les zombies."
            ),
            tags=["weapon", "melee", "woodcutting", "core"],
            crafting_category="weapon",
            game_specific={
                "damage": 50,
                "durability": 100,
                "weight_kg": 1.27,
                "size": "OneHanded",
                "material": "Metal/Wood",
            },
        ),
        MetadataConstraint(
            item_type="weapon", game_version="b41", base_id="Base.WoodenStick",
            display_name="Wooden Stick", description=(
                "Bâton de bois rudimentaire. Arme de défense basique, facile à fabriquer. "
                "Moins efficace que le hatchet mais toujours mieux que rien. "
                "Peut etre utilisé pour briser les portes."
            ),
            tags=["weapon", "melee", "crafting"],
            crafting_category="weapon",
            game_specific={"damage": 15, "durability": 30, "weight_kg": 0.68},
        ),
        MetadataConstraint(
            item_type="food", game_version="b41", base_id="Base.Bread",
            display_name="Bread", description=(
                "Miche de pain blanche. Nourriture principale restaurant la faim. "
                "Peut etre trouvee dans les supermarches ou fabriquee avec du froment moulue. "
                "Se conserve longtemps si non perime."
            ),
            tags=["food", "crafting", "core"],
            crafting_category="food",
            game_specific={"hunger": 60, "spoils_in_days": 30},
        ),
        MetadataConstraint(
            item_type="food", game_version="b41", base_id="Base.CannedFood",
            display_name="Canned Food", description=(
                "Boite de conserve generique. Nourriture a longue conservation. "
                "Se trouve dans les supermarches, garages et entrepots. "
                "Ne se perime pas — le principal avantage en survie long terme."
            ),
            tags=["food", "non-perishable", "core"],
            crafting_category="food",
            game_specific={"hunger": 50, "spoils_in_days": None},
        ),
        MetadataConstraint(
            item_type="tool", game_version="b41", base_id="Base.SledgeHammer",
            display_name="Sledge Hammer", description=(
                "Masse de démolition. Outil de demolition puissant pour briser les portes, "
                "déblayer les débris et infliger des degats massifs aux zombies (60 degats). "
                "Lent mais redoutable en combat rapproché."
            ),
            tags=["tool", "melee", "demolition"],
            crafting_category="weapon",
            game_specific={"damage": 60, "durability": 200, "weight_kg": 5.0},
        ),
        MetadataConstraint(
            item_type="clothing", game_version="b41", base_id="Base.WoodenShield",
            display_name="Wooden Shield", description=(
                "Bouclier en bois fabrique maison. Protège des dégats de melee et des attaques zombie. "
                "Peut etre fabriqué à l'atelier de menuiserie avec du contre-plaqué."
            ),
            tags=["clothing", "crafting", "defense"],
            crafting_category="clothing",
            game_specific={"block_chance": 0.5, "durability": 30},
        ),
        MetadataConstraint(
            item_type="meat", game_version="b41", base_id="Base.ChickenLegRaw",
            display_name="Raw Chicken Leg", description=(
                "Poule de poulet crue. Nourriture riche en proteine mais dangereuse si consommée crue — "
                "cause la maladie de Lyme a 20% des cas. Toujours cuire avant consommation pour éviter les infections."
            ),
            tags=["meat", "raw_food", "dangerous"],
            crafting_category="food",
            game_specific={"hunger": 30, "disease_chance": 0.2},
        ),
        MetadataConstraint(
            item_type="medication", game_version="b41", base_id="Base.Antibiotics",
            display_name="Antibiotics", description=(
                "Comprimés d'antibiotiques. Traite la maladie de Lyme et les infections des plaies ouvertes. "
                "Essentiel pour survivre aux morsures et griffures zombie."
            ),
            tags=["medication", "survival", "core"],
            crafting_category="medication",
            game_specific={"cures": ["Lyme Disease", "Infected Wound"]},
        ),
    ]


def get_b41_recipes() -> list[MetadataConstraint]:
    """Recettes principales de la B41 (crafting)."""
    return [
        MetadataConstraint(
            item_type="tool", game_version="b41", base_id="Recipe.Hatchet",
            display_name="Hatchet Crafting Recipe", description=(
                "Recette de fabrication du hatchet (hachette) : 2x Metal Sheet + 1x Length of Wood. "
                "Se fabrique à l'atelier de menuiserie. Outil polyvalent essentiel pour la survie."
            ),
            tags=["recipe", "crafting", "weapon"],
            crafting_category="recipe",
            game_specific={
                "ingredients": ["Metal Sheet x2", "Length of Wood x1"],
                "workshop": "Carpentry Bench",
                "time_seconds": 30,
                "skill_required": {"Carpentry": 2},
            },
        ),
        MetadataConstraint(
            item_type="food", game_version="b41", base_id="Recipe.BreadFromWheat",
            display_name="Bread from Wheat Recipe", description=(
                "Recette du pain : froment → meule avec le moulin → farine blanche → fourne a feu de bois. "
                "La chaine de production complète permet de fabriquer un pain durable (30 jours)."
            ),
            tags=["recipe", "food", "production"],
            crafting_category="recipe",
            game_specific={
                "ingredients": ["Base.WheatMill x1 (pour meule)", "Flour x6 (farine blanche)"],
                "fuel_required": True,
                "time_seconds": 60,
            },
        ),
    ]


def get_b41_mechanics() -> list[MetadataConstraint]:
    """Mécaniques de jeu B41 documentees."""
    return [
        MetadataConstraint(
            item_type="item", game_version="b41", base_id="Mechanic.Panic",
            display_name="Panic Mechanic", description=(
                "Mecanique de panique : les zombies entendent les bruits et se regroupent autour du bruit. "
                "Les zombie en état de 'panic' courent plus vite (40% plus rapide). "
                "Les sons attirent les zombie sur une distance proportionnelle a l'intensite du bruit."
            ),
            tags=["mechanic", "combat", "ai"],
            crafting_category=None,
            game_specific={"detection_range": 30.0, "run_speed_boost": 1.4},
        ),
        MetadataConstraint(
            item_type="item", game_version="b41", base_id="Mechanic.DistanceVision",
            display_name="Distance Vision / Hearing Range", description=(
                "Portee de detection des zombie : 30m pour la vue, jusqu'a 150m+ pour l'ouie (bruit fort). "
                "La fumee, les tirs d'arme a feu et les explosifs ont la plus large portee d'attirance."
            ),
            tags=["mechanic", "ai", "stealth"],
            crafting_category=None,
            game_specific={"vision_range": 30.0, "hearing_range": 150.0},
        ),
        MetadataConstraint(
            item_type="item", game_version="b41", base_id="Mechanic.Farming",
            display_name="Farming Mechanic", description=(
                "Mecanique d'agriculture : labourer le sol avec une houe → planter des graines (froment, patates). "
                "Arroser quotidiennement pour la croissance. Recolte en 1-2 jours selon les cultures."
            ),
            tags=["mechanic", "crafting", "food"],
            crafting_category=None,
            game_specific={"water_needed": True, "harvest_time_days": {"wheat": 1, "potato": 1}},
        ),
        MetadataConstraint(
            item_type="item", game_version="b41", base_id="Mechanic.Firecrafting",
            display_name="Fire Crafting Mechanic", description=(
                "Mecanique de feu : allumer un feu avec des allumettes + combustible (bois). "
                "Le feu cuit la nourriture, empeche le froid, repousse les zombies et permet la cuisson en plein air."
            ),
            tags=["mechanic", "crafting", "survival"],
            crafting_category=None,
            game_specific={"fuel_consumption_rate": 0.5, "smoke_attracts_zombies": True},
        ),
    ]


def get_b42_diffs() -> list[MetadataConstraint]:
    """Différences majeures B42 vs B41."""
    return [
        MetadataConstraint(
            item_type="item", game_version="b42", base_id="Mechanic.Multiplayer",
            display_name="Multiplayer Support", description=(
                "Support multijoueur complet en B42 : jusqu'a 16 joueurs en ligne cooperative. "
                "Nouveaux systemes de quetes, de progres et de contenu partage entre sessions."
            ),
            tags=["mechanic", "multiplayer", "core"],
            crafting_category=None,
            game_specific={"max_players": 16, "co_op_enabled": True},
        ),
    ]


# ── Génération de chunks structurés ─────────────────────────────────────────────

async def generate_chunks_for_object(constraint: MetadataConstraint) -> list[dict]:
    """Genere une liste de chunks depuis un objet structuré."""
    game_ver = constraint.game_version
    base_id = constraint.base_id
    item_type = constraint.item_type
    display = constraint.display_name
    desc = constraint.description
    game_data = constraint.game_specific

    # Chunk 1 : fiche objet complete
    metadata = {
        "item_type": constraint.item_type,
        "game_version": constraint.game_version,
        "base_id": constraint.base_id,
        "display_name": constraint.display_name,
        "ingest_source": "structured_data",
        "tags": constraint.tags,
        **(constraint.crafting_category and {"crafting_category": constraint.crafting_category} or {}),
    }
    if game_data:
        for k, v in game_data.items():
            metadata[f"game_{k}"] = v

    chunk_full = {
        "text": f"[{display}] ({base_id})\nType: {item_type} | Version: {game_ver}\n\n{desc}\n\nTags: {', '.join(constraint.tags)}",
        "metadata": metadata,
        "collection": _resolve_collection(constraint),
    }

    # Chunk 2 : données gameplay structurées (si applicable)
    chunks = [chunk_full]
    if game_data and isinstance(game_data, dict):
        chunk_stats = {
            "text": f"[{display}] Stats/Properties:\n" + "\n".join(
                f"  - {k}: {v}" for k, v in game_data.items()
            ),
            "metadata": {**metadata, "data_type": "game_stats"},
            "collection": _resolve_collection(constraint),
        }
        chunks.append(chunk_stats)

    return chunks


def _resolve_collection(constraint: MetadataConstraint) -> str:
    """Resolve la collection ChromaDB cible selon le type d'objet."""
    mapping = {
        "recipe": "pz_recipes",
        "mechanic": "pz_mechanics",
        "tool": "pz_items",
        "weapon": "pz_items",
        "food": "pz_items",
        "clothing": "pz_items",
        "meat": "pz_items",
        "medication": "pz_items",
        "item": "pz_mechanics",  # pour les mécaniques de jeu
    }
    cat = constraint.crafting_category or constraint.item_type
    return mapping.get(cat, "pz_items")


# ── Backup pre-ingest + rollback ---

_BACKUP_DIR = Path("backups") / "ingest"  # backups de staging avant ingestion

_MAX_STAGING_BACKUPS = 5


def _pre_ingest_backup() -> Optional[Path]:
    """Sauvegarde staging/ AVANT ingestion pour rollback en cas de crash.

    Returns:
        Chemin du snapshot TAR, ou None si staging/ est vide/inexistant.
    """
    if not STAGING_DIR.exists():
        return None

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    snapshot_path = _BACKUP_DIR / f"staging_backup_{stamp}.tar.gz"

    with tarfile.open(snapshot_path, "w:gz") as tar:
        # Ne pas sauvegarder les fichiers de lock ChromaDB
        for root, dirs, files in os.walk(STAGING_DIR):
            for fname in files:
                fpath = Path(root) / fname
                if ".lock" not in fpath.name and "chroma.sqlite3-shm" not in fpath.name:
                    tar.add(fpath, arcname=fpath.relative_to(STAGING_DIR))

    logger.info(f"[Backup] Pre-ingest staging backup: {snapshot_path}")
    _rotate_staging_backups()
    return snapshot_path


def _rollback_from_backup(backup_path: Path) -> None:
    """Restaurer staging/ depuis un backup pre-ingest."""
    if not backup_path.exists():
        logger.warning(f"[Rollback] Backup introuvable: {backup_path}")
        return

    # Nettoyer staging actuel
    for item in STAGING_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)

    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(STAGING_DIR)

    logger.info(f"[Rollback] staging restaure depuis {backup_path.name}")


def _rotate_staging_backups() -> None:
    """Supprimer les snapshots les plus anciens au-dela de _MAX_STAGING_BACKUPS."""
    if not _BACKUP_DIR.exists():
        return
    backups = sorted(_BACKUP_DIR.glob("staging_backup_*.tar.gz"), reverse=True)
    for old in backups[_MAX_STAGING_BACKUPS:]:
        old.unlink(missing_ok=True)
        logger.info(f"[Backup] Rotate out old backup: {old.name}")


# ── Ingestion structurée (cœur de Phase 3) ─────────────────────────────────────

@dataclass
class IngestSummary:
    """Resume d'une operation d'ingestion."""
    objects_ingested: int = 0
    chunks_written: int = 0
    validations_passed: int = 0
    validations_failed: int = 0
    errors: list[str] = field(default_factory=list)
    batches_created: int = 0
    backup_path: Optional[str] = None  # snapshot pre-ingest pour rollback


async def ingest_structured_data(
    items: Optional[list[MetadataConstraint]] = None,
    recipes: Optional[list[MetadataConstraint]] = None,
    mechanics: Optional[list[MetadataConstraint]] = None,
    b42_diffs: Optional[list[MetadataConstraint]] = None,
) -> IngestSummary:
    """Ingest des données structurées PZ dans staging ChromaDB.

    Protection : backup pre-ingest + rollback automatique en cas de crash.
    """
    # ── Pre-ingest backup (rollback safe) ---
    backup_path = _pre_ingest_backup()
    summary = IngestSummary(backup_path=str(backup_path) if backup_path else None)

    try:
        impl_summary = await _ingest_structured_data_impl(items, recipes, mechanics, b42_diffs)
        # Merge inner results into outer summary (conserve backup_path)
        summary.objects_ingested += impl_summary.objects_ingested
        summary.chunks_written += impl_summary.chunks_written
        summary.validations_passed += impl_summary.validations_passed
        summary.validations_failed += impl_summary.validations_failed
        summary.batches_created += impl_summary.batches_created
        summary.errors.extend(impl_summary.errors)
        return summary
    except Exception as exc:
        # Rollback : restaurer staging/ depuis le backup pre-ingest
        if backup_path and backup_path.exists():
            logger.error(
                f"[Ingest] Erreur critique — rollback depuis {backup_path.name}",
                exc_info=True,
            )
            _rollback_from_backup(backup_path)
        summary.errors.append(f"CRASH: {exc}")
        raise


async def _ingest_structured_data_impl(
    items: Optional[list[MetadataConstraint]] = None,
    recipes: Optional[list[MetadataConstraint]] = None,
    mechanics: Optional[list[MetadataConstraint]] = None,
    b42_diffs: Optional[list[MetadataConstraint]] = None,
) -> IngestSummary:
    """Implementation interne de ingest_structured_data (sans gestion d'erreurs)."""
    summary = IngestSummary()
    objects: list[MetadataConstraint] = []
    if items:
        objects.extend(items)
    if recipes:
        objects.extend(recipes)
    if mechanics:
        objects.extend(mechanics)
    if b42_diffs:
        objects.extend(b42_diffs)

    # Collecter tous les chunks à ingérer en batches anti-OOM
    batch_chunks: list[tuple[dict, str]] = []  # (chunk_data, collection)
    current_batch_bytes = 0

    for obj in objects:
        # Validation stricte des metadata
        meta = {
            "item_type": obj.item_type,
            "game_version": obj.game_version,
            "base_id": obj.base_id,
            "display_name": obj.display_name,
            "ingest_source": "structured_data",
            "tags": obj.tags,
        }
        if obj.crafting_category:
            meta["crafting_category"] = obj.crafting_category

        errs = validate_metadata(obj, meta)
        if errs:
            summary.validations_failed += 1
            summary.errors.append(f"Validation échouée pour {obj.base_id}: {errs}")
            continue

        # Générer les chunks
        chunks_data = await generate_chunks_for_object(obj)
        for chunk in chunks_data:
            # Vérifier si le batch est trop gros
            chunk_size = len(chunk["text"]) + 512  # buffer metadata
            if current_batch_bytes + chunk_size > MAX_BATCH_BYTES and batch_chunks:
                summary.batches_created += 1
                written = await _flush_batch(batch_chunks)
                summary.chunks_written += written
                summary.validations_passed += written
                batch_chunks.clear()
                current_batch_bytes = 0

            batch_chunks.append((chunk, _resolve_collection(obj)))
            current_batch_bytes += chunk_size
            summary.objects_ingested += 1

    # Flush le dernier batch
    if batch_chunks:
        summary.batches_created += 1
        written = await _flush_batch(batch_chunks)
        summary.chunks_written += written
        summary.validations_passed += written

    return summary


def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Rend les metadata compatibles ChromaDB (str/int/float/bool/list/None uniquement)."""
    sanitized: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            sanitized[k] = v
        elif isinstance(v, list):
            # Conserver les lists de types primitives
            if all(isinstance(x, (str, int, float, bool)) for x in v):
                sanitized[k] = v
            else:
                sanitized[k] = json.dumps(v, ensure_ascii=False)
        else:
            # Dict ou autre type → sérialiser en JSON
            sanitized[k] = json.dumps(v, ensure_ascii=False)
    return sanitized


async def _flush_batch(
    batch_chunks: list[tuple[dict, str]],
) -> int:
    """Ecrire un batch de chunks dans ChromaDB (un seul appel par collection)."""
    from .processors.base import Chunk
    from .storage.chroma_writer import ChromaWriter

    # Group by target collection — chaque collection requiert un appel separate
    by_collection: dict[str, list[dict]] = {}
    for chunk_data, collection in batch_chunks:
        by_collection.setdefault(collection, []).append(chunk_data)

    success_count = 0
    writer_ = ChromaWriter()
    for target_col, chunk_datas in by_collection.items():
        chunks_list: list[Chunk] = []
        metas_per_chunk: list[dict[str, Any]] = []
        for idx_local, cd in enumerate(chunk_datas):
            meta = _sanitize_metadata(cd.get("metadata", {}))
            meta["batch_id"] = str(uuid.uuid4())[:8]
            chunks_list.append(Chunk(text=cd["text"], index=idx_local, start_offset=0, metadata=meta))
            metas_per_chunk.append(meta)

        ok = await writer_.write_chunks_to_chroma(
            chunks=chunks_list,
            source="structured://ingest.py",
            content_type="application/json",
            collection=target_col,
            metadata={"ingest_batch": "auto"},
        )
        if ok:
            success_count += len(chunks_list)

    return success_count


# ── CLI ──────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:  # noqa: F821
    parser = argparse.ArgumentParser(
        prog="python -m ingestor.ingest",
        description="Zomboid Knowledge Engine — Ingestion globale (données structurées + fichiers)",
    )
    sub = parser.add_subparsers(dest="command")

    # Commande: items (données structurées)
    p_items = sub.add_parser("items", help="Ingerer les donnees structurees B41/B42")
    p_items.add_argument("--b41", action="store_true", help="Ingerer uniquement les données B41")
    p_items.add_argument("--b42", action="store_true", help="Ingerer uniquement les differencies B42")

    # Commande: file
    p_file = sub.add_parser("file", help="Ingerer un fichier unique")
    p_file.add_argument("path", type=Path, help="Chemin du fichier a ingerer")
    p_file.add_argument("--collection", default=None, help="Collection ChromaDB cible")

    # Commande: dir
    p_dir = sub.add_parser("dir", help="Ingerer un dossier complet")
    p_dir.add_argument("path", type=Path, help="Chemin du dossier a ingerer")
    p_dir.add_argument("--recursive", action="store_true", default=True)

    # Commande: collections
    sub.add_parser("collections", help="Afficher les collections ChromaDB existantes")

    # Arguments globaux
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT,
                        help=f"Nombre de chunks par batch (defaut: {BATCH_SIZE_DEFAULT})")
    parser.add_argument("--verbose", "-v", action="store_true")

    return parser


async def _cmd_items(args: argparse.Namespace) -> IngestSummary:
    """Execution de la commande 'items'."""
    items = get_b41_items()
    recipes = get_b41_recipes()
    mechanics = get_b41_mechanics()

    if args.b42:
        b42_diffs = get_b42_diffs()
        summary = await ingest_structured_data(items=[], recipes=[], mechanics=[], b42_diffs=b42_diffs)
    else:
        b42_diffs = get_b42_diffs() if args.b42 else []
        summary = await ingest_structured_data(items, recipes, mechanics, b42_diffs)

    # Affichage resume
    print(f"\n{'='*60}")
    print("Ingestion structurée — Resume")
    print(f"{'='*60}")
    print(f"  Objets analyses : {summary.objects_ingested}")
    print(f"  Chunks ecrits   : {summary.chunks_written}")
    print(f"  Batches creees  : {summary.batches_created}")
    print(f"  Validations OK  : {summary.validations_passed}")
    if summary.validations_failed:
        print(f"  Echecs validation: {summary.validations_failed}")
    if summary.errors:
        for e in summary.errors[:5]:
            print(f"    ! {e}")
    print(f"{'='*60}\n")

    return summary


async def _cmd_file(args: argparse.Namespace) -> None:
    """Execution de la commande 'file'."""
    from .engine import IngestionEngine, detect_type
    from .config import load_config
    from .storage.chroma_writer import write_chunks_to_chroma

    config = load_config()
    engine = IngestionEngine(config)
    result = await engine.ingest(str(args.path))

    collection = args.collection or "pz_items"
    if result.collection:
        collection = result.collection

    print(f"\n{'='*60}")
    print(f"Ingestion fichier : {args.path.name}")
    print(f"  Chunks    : {len(result.chunks)}")
    print(f"  Mots      : {result.word_count}")
    print(f"  Collection: {collection}")

    if result.chunks:
        collection_map = {
            "text": "pz_items",
            "pdf": "pz_pdfs",
            "image": "pz_images",
            "video": "pz_videos",
            "audio": "pz_audios",
            "docx": "pz_docx",
            "epub": "pz_epub",
        }
        content_type, processor_key = detect_type(args.path)
        target_col = args.collection or collection_map.get(processor_key, "pz_items")

        ok = await write_chunks_to_chroma(
            chunks=result.chunks,
            source=str(args.path),
            content_type=content_type,
            collection=target_col,
            metadata={"ingest_source": "cli_file", "game_version": "b41"},
        )
        print(f"  ChromaDB  : {'OK' if ok else 'ECHEC'}")


async def _cmd_dir(args: argparse.Namespace) -> None:
    """Execution de la commande 'dir'."""
    from .engine import IngestionEngine
    from .config import load_config

    config = load_config()
    engine = IngestionEngine(config)
    results = await engine.ingest_directory(str(args.path), recursive=args.recursive)

    total_chunks = sum(len(r.chunks) for r in results)
    total_words = sum(r.word_count for r in results)
    print(f"\n{'='*60}")
    print(f"Ingestion dossier : {args.path}")
    print(f"  Fichiers traites: {len(results)}")
    print(f"  Total chunks    : {total_chunks}")
    print(f"  Total mots      : {total_words}")


async def _cmd_collections() -> None:
    """Afficher les collections existantes."""
    from .storage.chroma_writer import ChromaWriter

    writer = ChromaWriter()
    collections = await writer.list_collections()
    print(f"\n{'='*60}")
    print("Collections ChromaDB disponibles :")
    for col in sorted(collections):
        try:
            count = await writer.count_collection(col)
            print(f"  {col:<30} ({count} docs)")
        except Exception:
            print(f"  {col:<30} (non accessible)")


async def main_cmd(argv: Optional[list[str]] = None) -> int:
    """Point d'entrée CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "items":
        await _cmd_items(args)
        return 0

    elif args.command == "file":
        await _cmd_file(args)
        return 0

    elif args.command == "dir":
        await _cmd_dir(args)
        return 0

    elif args.command == "collections":
        await _cmd_collections()
        return 0

    return 1


if __name__ == "__main__":
    import argparse
    sys.exit(asyncio.run(main_cmd()))
