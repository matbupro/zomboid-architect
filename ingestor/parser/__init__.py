"""ingestor/parser — Modules de validation et parsing Dual-Field.

Exporte les classes principales :
    - schemas: ItemEntity, RecipeEntity, SchemaValidator (validation Pydantic-like)
    - dual_field: ResilientParser, DualFieldResult (parseur resilient + output dual-field)

Usage :
    from ingestor.parser import SchemaValidator, ResilientParser
    from ingestor.parser.schemas import ItemEntity, RecipeEntity
    from ingestor.parser.dual_field import DualFieldResult
"""

from .schemas import (  # noqa: F401
    ContentType,
    ItemEntity,
    RecipeEntity,
    MechanicEntity,
    SchemaValidator,
    ValidationError,
)
from .dual_field import (  # noqa: F401
    ResilientParser,
    DualFieldResult,
)

__all__ = [
    "ContentType",
    "ItemEntity",
    "RecipeEntity",
    "MechanicEntity",
    "SchemaValidator",
    "ValidationError",
    "ResilientParser",
    "DualFieldResult",
]
