"""
config — Settings du moteur d'ingestion multi-format.

Variables d'environnement (voir .env.ingestor) :
  CHROMA_HOST         — URL du serveur ChromaDB (défaut: http://host.docker.internal:8000)
  OLLAMA_BASE_URL     — URL du serveur Ollama (défaut: http://host.docker.internal:11434)
  EMBEDDING_MODEL     — modèle d'embedding pour ChromaDB (défaut: nomic-embed-text)
  CLAUDE_API_KEY      — clé API Claude pour descriptions vision (optionnel)
  DATA_ROOT           — racine des données brutes/staging/production (défaut: data/)
  MAX_WEB_DEPTH       — profondeur max de crawl web (défaut: 5)
  MAX_WEB_PAGES       — pages max par seed URL (défaut: 50)
  WEB_RATE_LIMIT      — requêtes web/min (défaut: 30)
  OCR_LANG            — langues OCR (défaut: fra+eng)
  CHUNK_SIZE          — taille des chunks de texte (défaut: 512)
  CHUNK_OVERLAP       — chevauchement des chunks (défaut: 64)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IngestorConfig:
    """Configuration centralisée de l'ingestion."""

    # ChromaDB
    CHROMA_HOST: str = "http://host.docker.internal:8000"

    # Ollama (embedding)
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # Claude vision API (pour descriptions d'images) — optionnel, fallback: OCR seul
    CLAUDE_API_KEY: str | None = None
    CLAUDE_BASE_URL: str = "https://api.anthropic.com/v1/messages"

    # Data paths
    DATA_ROOT: Path = field(default_factory=lambda: Path("data"))
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64

    # Web browsing
    MAX_WEB_DEPTH: int = 5
    MAX_WEB_PAGES: int = 50
    WEB_RATE_LIMIT: int = 30  # requests per minute
    USER_AGENT: str = "Zomboid Knowledge Engine (RAG multi-format)"

    # OCR
    OCR_LANG: str = "fra+eng"

    # Collections ChromaDB
    COLLECTIONS: list[str] = field(default_factory=lambda: [
        "pz_items", "pz_recipes", "pz_mechanics",
        "pz_lua_api", "pz_java_api",  # existantes
        "pz_web_pages",               # nouvelles — web crawling
        "pz_pdfs",                    # nouvelles — documents PDF
        "pz_images",                  # nouvelles — images/OCR
        "pz_videos",                  # nouvelles — vidéos/transcriptions
        "pz_audios",                  # nouvelles — audio transcription
        # Steam/mod collections (auto-crees a l'utilisation)
        "pz_mods",                    # Metadata + description des mods
        "pz_workshop_items",          # Registry workshop (ID, name, author, dates)
        "pz_mod_lua_scripts",         # Scripts Lua extraits des mods/.pbo
        "pz_mod_configs",             # Config files (.bin, .cfg) + contenu d'archives
    ])

    # Steam / Workshop configuration
    STEAM_INSTALL_PATH: str | None = None  # Auto-decouvert via winreg si absent
    GAME_PATH: str | None = None           # Auto-decouvert vers PZ install
    WORKSHOP_CONTENT_ROOT: Path | None = None  # steamapps/workshop/content/1042170
    DEFAULT_STEAMCMD_DIR: str = "steamcmd"
    STEAM_USER: str | None = None   # Pour login SteamCMD (mod downloads)
    STEAM_PASS: str | None = None   # idem

    # Safety / Quarantine
    MAX_RETRIES: int = 3
    QUARANTINE_DIR: str = "quarantine"
    DISK_SPACE_MIN_GB: float = 2.0  # GB min free before each ingest cycle


def load_config() -> IngestorConfig:
    """Charge la config depuis .env.unified (racine du projet) ou les valeurs par défaut."""
    env_file = Path(__file__).parent.parent / ".env.unified"
    if not env_file.exists():
        # fallback : cherche .env à la racine
        for alt in [Path(__file__).parent.parent / ".env", Path(__file__).parent / ".env"]:
            if alt.exists():
                env_file = alt
                break
    if not env_file.exists():
        pass  # aucun fichier trouvé, utiliser les defaults + vraies env vars
    else:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    data_root_raw = os.getenv("DATA_ROOT", "data")
    steam_path = os.getenv("STEAM_INSTALL_PATH")
    game_path_str = os.getenv("GAME_PATH")
    workshop_root_str = os.getenv("WORKSHOP_CONTENT_ROOT")

    return IngestorConfig(
        CHROMA_HOST=os.getenv("CHROMA_HOST", "http://host.docker.internal:8000"),
        OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
        CLAUDE_API_KEY=os.getenv("CLAUDE_API_KEY"),
        CLAUDE_BASE_URL=os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com/v1/messages"),
        DATA_ROOT=Path(data_root_raw),
        CHUNK_SIZE=int(os.getenv("CHUNK_SIZE", "512")),
        CHUNK_OVERLAP=int(os.getenv("CHUNK_OVERLAP", "64")),
        MAX_WEB_DEPTH=int(os.getenv("MAX_WEB_DEPTH", "5")),
        MAX_WEB_PAGES=int(os.getenv("MAX_WEB_PAGES", "50")),
        WEB_RATE_LIMIT=int(os.getenv("WEB_RATE_LIMIT", "30")),
        USER_AGENT=os.getenv("USER_AGENT", "Zomboid Knowledge Engine (RAG multi-format)"),
        OCR_LANG=os.getenv("OCR_LANG", "fra+eng"),
        STEAM_INSTALL_PATH=steam_path or None,
        GAME_PATH=game_path_str or None,
        WORKSHOP_CONTENT_ROOT=Path(workshop_root_str).resolve() if workshop_root_str else None,
        STEAM_USER=os.getenv("STEAM_USER"),
        STEAM_PASS=os.getenv("STEAM_PASS"),
    )
