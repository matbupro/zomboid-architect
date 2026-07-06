"""parser/schemas — Validations Pydantic pour les entites PZ.

Schémas de validation stricts pour chaque type d'entite ingérée.
Le parseur renvoie des dicts ; ces schémas garantissent leur validité
avant écriture en ChromaDB.

Exemples :
    from ingestor.parser.schemas import ItemSchema, RecipeSchema

    item = ItemSchema(**parsed_dict)  # raises ValidationError on mismatch
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class ContentType(Enum):
    """Categories de contenu extraites depuis les fichiers sources."""
    ITEM       = "item"
    RECIPE     = "recipe"
    TRAIT      = "trait"
    PROFESSION = "profession"
    SKILL      = "skill"
    MOODLE     = "moodle"
    MECHANIC   = "mechanic"
    LUA_API    = "lua_api"
    JAVA_API   = "java_api"
    UNKNOWN    = "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Schema de validation — item
# ──────────────────────────────────────────────────────────────────────────────


class ItemEntity:
    """Entite validatee d'un objet/item PZ.

    L'ID suit le format PZ : `Namespace.ClassName` (ex: Base.Axe, Item.Flashlight)
    avec validation stricte de pattern.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        try:
            self.id = self._validate_id(data.get("id", ""))
        except ValueError as exc:
            raise ValidationError("item", "id", str(exc)) from exc
        self.type = str(data.get("type", "unknown")).strip()
        self.display_name = str(data.get("displayname", "") or data.get("DisplayName", "")).strip() or None
        self.category = str(data.get("category", "")).strip() or None
        self.weight: float | None = None
        try:
            self.weight = float(data["weight"]) if "weight" in data else None
        except (ValueError, TypeError):
            self.weight = None
        self.attributes: dict[str, str] = {}
        for k, v in data.items():
            if k.startswith("attr_"):
                self.attributes[k[5:]] = str(v)

    @staticmethod
    def _validate_id(raw: str) -> str:
        """Valide le format d'ID PZ : Namespace.ClassName (PascalCase)."""
        raw = raw.strip()
        if not raw:
            raise ValueError("Item ID cannot be empty")
        # Pattern : une lettre majuscule suivie de lettres, un point, puis une autre lettre majuscule + lettres
        pattern = r"^[A-Z][a-zA-Z]+\.[A-Z][a-zA-Z]+$"
        if not re.match(pattern, raw):
            raise ValueError(
                f"Invalid item ID format: '{raw}' (expected 'Namespace.ClassName', e.g. 'Base.Axe')"
            )
        return raw


# ──────────────────────────────────────────────────────────────────────────────
# Schema de validation — recipe
# ──────────────────────────────────────────────────────────────────────────────


class RecipeEntity:
    """Entite validatee d'une recette PZ."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.name = str(data.get("name", "")).strip()
        if not self.name:
            raise ValidationError("recipe", "name", "Recipe name cannot be empty")
        self.result = str(data.get("result", "")).strip()
        if not self.result:
            raise ValidationError("recipe", "result", "Recipe result cannot be empty")
        self.category = str(data.get("category", "")).strip() or None

        # Ingredients — au moins un requis
        raw_ingredients = data.get("ingredients", [])
        self.ingredients: list[dict[str, str]] = []
        for ing in raw_ingredients:
            if isinstance(ing, dict):
                item = str(ing.get("item", "")).strip()
                count = int(ing.get("count", 1)) if ing.get("count") else 1
                if item and count > 0:
                    self.ingredients.append({"item": item, "count": count})
            elif isinstance(ing, str):
                self.ingredients.append({"item": ing.strip(), "count": 1})

        if not self.ingredients:
            raise ValidationError("recipe", "ingredients", f"Recipe '{self.name}' requires at least one ingredient")

        # Skills requis
        raw_skills = data.get("skills", [])
        self.skills_required: list[dict[str, str]] = []
        for skill in raw_skills:
            if isinstance(skill, dict):
                name = str(skill.get("skill", "")).strip()
                level = str(skill.get("level", "1")).strip()
                if name:
                    self.skills_required.append({"skill": name, "level": level})

    @property
    def ingredient_summary(self) -> str:
        parts = []
        for ing in self.ingredients:
            parts.append(f"{ing['count']}x {ing['item']}")
        return ", ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Schema de validation — mechanic
# ──────────────────────────────────────────────────────────────────────────────


class MechanicEntity:
    """Entite validatee d'une mécanique PZ (format markdown)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.title = str(data.get("title", "")).strip()
        if not self.title:
            raise ValueError("Mechanic title cannot be empty")
        self.content = str(data.get("content", "")).strip()
        self.metadata: dict[str, Any] = data.get("metadata", {})


# ──────────────────────────────────────────────────────────────────────────────
# Validator — facade unifiee
# ──────────────────────────────────────────────────────────────────────────────


class ValidationError(Exception):
    """Erreur de validation d'entite PZ."""

    def __init__(self, entity_type: str, field: str, message: str) -> None:
        self.entity_type = entity_type
        self.field = field
        self.message = message
        super().__init__(f"[{entity_type}] {field}: {message}")


class SchemaValidator:
    """Validateur d'entites PZ avec cascade de fallback."""

    VALIDATORS: dict[ContentType, type] = {
        ContentType.ITEM: ItemEntity,
        ContentType.RECIPE: RecipeEntity,
    }

    @classmethod
    def validate(cls, data: dict[str, Any], content_type: ContentType) -> Any:
        """Valide un dict selon son type de contenu.

        Raises:
            ValidationError: si la donnee ne correspond pas au schema.
        """
        validator_cls = cls.VALIDATORS.get(content_type)
        if validator_cls is None:
            raise ValidationError(
                content_type.value, "type",
                f"No validator for ContentType.{content_type.name}"
            )

        try:
            return validator_cls(data)
        except ValueError as exc:
            raise ValidationError(
                content_type.value, "data", str(exc)
            ) from exc

    @classmethod
    def validate_batch(cls, chunks: list[dict[str, Any]]) -> list[tuple[Any, bool]]:
        """Valide un lot de chunks et retourne [(entite_validee, success)]."""
        results: list[tuple[Any, bool]] = []
        for chunk in chunks:
            ct = ContentType(chunk.get("type", "unknown"))
            try:
                entity = cls.validate(chunk.get("metadata", {}), ct)
                results.append((entity, True))
            except ValidationError:
                results.append((chunk.get("metadata", {}), False))
        return results


# ──────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ──────────────────────────────────────────────────────────────────────────────

def validate_item(data: dict[str, Any]) -> ItemEntity:
    """Valide un dict d'item. Shortcut."""
    return ItemEntity(data)


def validate_recipe(data: dict[str, Any]) -> RecipeEntity:
    """Valide un dict de recipe. Shortcut."""
    return RecipeEntity(data)
