"""Config — chargement .env.unified et settings du bot Discord Zomboid.
Source de vérité : `.env.unified` a la racine du projet (tout le reste a ete supprime).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_env():
    """Charge le fichier .env.unified à la racine du projet (source de vérité unique)."""
    env_file = Path(__file__).parent.parent / ".env.unified"
    if not env_file.exists() or not env_file.is_file():
        raise RuntimeError(
            ".env.unified introuvable. Vérifier qu'il existe à la racine du projet."
        )
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Settings:
    """Configuration centralisée du bot."""

    # Discord
    DISCORD_TOKEN: str
    INTENT_PREFIXES: str = "/"  # Préfixe pour les commandes normales

    # LLM Local (Ollama)
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "llama3.2"
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # LLM Fallback (Claude API)
    CLAUDE_API_KEY: str | None = None
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

    # Pipeline
    LLM_TEMPERATURE: float = 0.7
    MAX_RESPONSE_LENGTH: int = 4000

    # Defaults pour les commandes
    DEFAULT_SYSTEM_PROMPT: str = (
        "Tu es l'assistant Zomboid Knowledge Engine — un moteur de connaissance local, déterministe et sans hallucination sur le jeu Project Zomboid. "
        "Tu aides le joueur avec la survie hardcore, le modding Lua/Java, et les données exactes du jeu. "
        "Règles : aucune hallucination numérique, cite toujours la source des valeurs chiffrées. "
        "Si une donnée n'est pas disponible dans ta base de connaissance, dis-le explicitement au lieu d'inventer."
    )

    # Embedding dimensions (bge-m3 et nomic-embed-text ont 1024 dims)
    EMBEDDING_DIM: int = 1024

    # Canal workspace Discord (nom ou ID)
    WORKSPACE_CHANNEL_NAME: str = "[DESKTOP] WORKSPACE Z-ARCHITECT"
    WORKSPACE_CHANNEL_ID: int | None = None  # Résolu dynamiquement au démarrage
    DISCORD_GUILD_ID: int | None = None      # Serveur Discord cible (optionnel, aide la recherche de canal)

    # Commandes internes (pour sync workspace depuis Docker)
    SYNC_HOOK_URL: str | None = None         # Si un serveur web écoute ici, on POST le rapport
    
    # Generation de mods (Phase 12)
    MOD_OUTPUT_PATH: str = "mods"             # Repertoire de sortie des mods generes

    # Game version (B41/B42) — héritée de src/governance/game_version.py
    PZ_GAME_VERSION: str | None = None         # "b41", "b42", ou None (auto-resolve par VERSION file)


def load_settings() -> Settings:
    """Charge les settings depuis l'environnement ou les valeurs par défaut."""
    _load_env()

    return Settings(
        DISCORD_TOKEN=os.getenv("DISCORD_TOKEN", ""),
        OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", "llama3.2"),
        EMBEDDING_MODEL=os.getenv("ZOMBOID_EMBEDDING_MODEL", "nomic-embed-text"),
        CLAUDE_API_KEY=os.getenv("CLAUDE_API_KEY"),
        CLAUDE_MODEL=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        LLM_TEMPERATURE=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        MAX_RESPONSE_LENGTH=int(os.getenv("MAX_RESPONSE_LENGTH", "4000")),
        WORKSPACE_CHANNEL_NAME=os.getenv("WORKSPACE_CHANNEL_NAME", "[DESKTOP] WORKSPACE Z-ARCHITECT"),
        WORKSPACE_CHANNEL_ID=int(os.getenv("WORKSPACE_CHANNEL_ID")) if os.getenv("WORKSPACE_CHANNEL_ID") else None,
        DISCORD_GUILD_ID=int(os.getenv("DISCORD_GUILD_ID")) if os.getenv("DISCORD_GUILD_ID") else None,
        SYNC_HOOK_URL=os.getenv("SYNC_HOOK_URL"),
        MOD_OUTPUT_PATH=os.getenv("MOD_OUTPUT_PATH", "mods"),
        PZ_GAME_VERSION=os.getenv("PZ_GAME_VERSION") or None,
    )


