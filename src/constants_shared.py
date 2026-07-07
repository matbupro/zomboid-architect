"""
Constants et configurations partagées entre les modules du projet.
Ce fichier centralise les types de fichiers, les métadonnées système
et les paramètres de base pour éviter la duplication (DRY).
"""

from typing import Final

# Mapping des extensions vers leurs catégories respectives
# Utilisé par ingestor/engine.py et database/extract_pz.py
FILE_TYPE_MAP: Final[dict[str, str]] = {
    # Textes bruts
    ".txt": "text",
    ".md": "text",
    ".csv": "text",
    ".json": "text",
    ".xml": "xml",
    ".html": "web",
    ".yml": "web",
    ".yaml": "web",
    ".toml": "config_bin",

    # Scripts et fichiers de configuration spécifiques à Project Zomboid
    ".lua": "lua",
    ".pzby": "lua",  # bytecode Lua PZ
    ".tile": "text",
    ".tiles": "text",
    ".lotpack": "text",
    ".lotheader": "text",

    # Médias (Images, Vidéos, Audio)
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".bmp": "image",
    ".webp": "image",
    ".tiff": "image",
    ".tif": "image",
    ".svg": "image",

    # Audio & Vidéo
    ".mp3": "audio",
    ".wav": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".m4a": "audio",
    ".mp4": "video",
    ".avi": "video",
    ".mkv": "video",
    ".webm": "video",

    # Documents et autres
    ".pdf": "pdf",
    ".docx": "docx",
    ".epub": "epub",

    # Assets spécifiques de Project Zomboid
    ".pbo": "pbo",
    ".pbosync": "pbo",

    # Shaders et fichiers techniques
    ".frag": "text",
    ".vert": "text",
    ".gl123": "texture", # Note: à vérifier selon spécification spécifique.
}

# Mappings de types MIME vers les noms des processeurs/collections (Ingestion)
MIME_TO_PROCESSOR_MAP: Final[dict[str, str]] = {
    "text/plain": "text",
    "text/markdown": "text",
    "text/xml": "xml",
    "application/json": "text",
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "audio/mpeg": "audio",
    "video/mp4": "video",
    "application/x-pbo": "pbo",
}
