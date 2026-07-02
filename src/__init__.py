"""src -- Packages transversaux du projet Zomboid Knowledge Engine.

Ce package expose deux sous-modules :
  - governance: parser, game_version, logger, lock, worker (gouvernance)
  - retrieval:   interface ChromaDB (query_staging, query_production)
"""

from __future__ import annotations

__all__ = ["governance", "retrieval"]
