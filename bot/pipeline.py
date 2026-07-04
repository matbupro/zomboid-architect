"""
pipeline — Chaîne de traitement des messages Discord → réponse Zomboid.

Flux :
    message utilisateur
        → router (détecte le type de commande / la collection pertinente)
        → engine.search() ou engine.get_by_id() pour récupérer le contexte Zomboid
        → construction du prompt LLM (contexte JSON brut + question)
        → LLM.complete() (Ollama en priorité, Claude en fallback)
        → retour du texte de réponse
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .engine_client import KnowledgeEngineClient, SearchResult
from .llm_adapter import LLMProvider, OllamaProvider, ClaudeProvider

from src.governance.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PromptResult:
    """Résultat d'une passe du pipeline."""
    raw_context: list[SearchResult]   # Résultats bruts du knowledge engine (JSON brut)
    prompt_text: str                  # Prompt construit pour le LLM
    llm_response: str                 # Réponse du LLM


# ---------------------------------------------------------------------------
# Routing — détection de l'intention et sélection de collections
# ---------------------------------------------------------------------------

COLLECTION_ROUTES = {
    "stats": ["pz_items"],
    "survie": ["pz_mechanics", "pz_items"],
    "recipe": ["pz_recipes", "pz_mechanics"],
    "moddoc": ["pz_lua_api", "pz_java_api"],
    "search": ["pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api"],
}

# Regex patterns pour détection automatique de commandes implicites
PATTERN_ITEM_ID = re.compile(r"(?:stat[s]?|stats?)\s*(?:de\s*)?([A-Z][a-zA-Z]+\.[A-Za-z]+)", re.IGNORECASE)
PATTERN_RECIPE = re.compile(r"(?:recette[es]?\s+(?:pour\s+)?)([A-Z][a-zA-Z]+(?:\s+[A-Za-z]+)?)", re.IGNORECASE)


def detect_intent(message: str) -> tuple[str, str]:
    """Détecte le type de commande et extrait la requête.

    Returns:
        (command_type, query_text)
    """
    msg = message.strip().lower()

    # Slash commands explicites
    if msg.startswith("/stats"):
        return ("stats", message.replace("/stats ", ""))
    if msg.startswith("/survie") or msg.startswith("/help_me_survive"):
        return ("survie", message.replace("/survie ", "").replace("/help_me_survive ", ""))
    if msg.startswith("/recipe"):
        return ("recipe", message.replace("/recipe ", "").lower())
    if msg.startswith("/moddoc") or msg.startswith("/luaapi") or msg.startswith("/javaapi"):
        return ("moddoc", message.replace("/moddoc ", "").replace("/luaapi ", "").replace("/javaapi ", ""))
    if msg.startswith("/search"):
        return ("search", message.replace("/search ", ""))

    # Détection implicite
    match_id = PATTERN_ITEM_ID.search(msg)
    if match_id:
        return ("stats", match_id.group(1))

    if any(kw in msg for kw in ["recette", "craft", "artisanat"]):
        return ("recipe", msg)

    if any(kw in msg for kw in ["moddoc", "lua api", "java api", "modding", "hook"]):
        return ("moddoc", msg)

    # Défaut : recherche libre sur toutes les collections
    return ("search", msg)


# ---------------------------------------------------------------------------
# Context enrichment — requête au knowledge engine
# ---------------------------------------------------------------------------

def enrich_context(
    client: KnowledgeEngineClient,
    command_type: str,
    query_text: str,
    n_results: int = 5,
    game_version: str | None = None,
) -> list[SearchResult]:
    """Récupère le contexte pertinent depuis le knowledge engine.

    Args:
        client: KnowledgeEngineClient instance.
        command_type: Type de commande détecté (stats, survie, etc.).
        query_text: Texte de la requête utilisateur.
        n_results: Nombre maximal de résultats.
        game_version: Optionnel — filtre les résultats par version PZ (b41/b42).
    """
    collections = COLLECTION_ROUTES.get(command_type, ["pz_items"])

    # Pour /stats : essayer d'abord un lookup déterministe par ID
    if command_type == "stats":
        item_id = _extract_item_id(query_text)
        if item_id:
            result = client.get_by_id(item_id, collection="pz_items", game_version=game_version)
            if result:
                return [result]

    # Requête vectorielle sur les collections pertinentes
    results = client.search(
        queries=[(col, query_text) for col in collections],
        n_results=n_results,
        game_version=game_version,
    )
    return results


# ---------------------------------------------------------------------------
# Prompt building — construction du prompt LLM avec contexte JSON brut
# ---------------------------------------------------------------------------

def build_prompt(
    context: list[SearchResult],
    question: str,
    command_type: str,
    system_prompt: str,
) -> str:
    """Construit le prompt complet pour le LLM.

    Inclut :
    - Le système (règles de l'assistant)
    - Le contexte JSON brut du knowledge engine (non reformulé)
    - La question de l'utilisateur
    """
    # Section contexte : valeurs exactes du knowledge engine
    context_sections = []
    for item in context:
        section = f"--- [{item.collection}] ID:{item.id} ---\n"
        # Champ JSON brut (métadonnées exactes)
        if item.metadata_:
            section += f"JSON_BRUT:\n{json_dumps_safe(item.metadata_)}\n"
        # Champ prose (description lisible)
        if item.prose:
            section += f"PROSE:\n{item.prose}\n"
        context_sections.append(section)

    context_text = "\n".join(context_sections) if context_sections else "(Aucune donnée trouvée dans le knowledge engine)"

    # Format du prompt
    parts = [system_prompt, ""]

    if command_type == "stats":
        parts.append(f"""Données exactes de l'objet :
{context_text}

Question : {question}

Réponds avec les stats précises. N'invente jamais de valeurs chiffrées.""")
    elif command_type == "survie":
        parts.append(f"""Données mécaniques pertinentes :
{context_text}

Scénario du joueur : {question}

Donne un conseil de survie précis basé sur ces données.""")
    elif command_type == "recipe":
        parts.append(f"""Données recettes :
{context_text}

Recette demandée : {question}

Liste les ingrédients exacts et l'étape de craft si disponible.""")
    elif command_type == "moddoc":
        parts.append(f"""Documentation API pertinente :
{context_text}

Question sur le modding : {question}

Réponds avec la documentation technique exacte.""")
    else:  # search
        parts.append(f"""Données trouvées :
{context_text}

Question : {question}

Synthétise une réponse utile basée sur les données ci-dessus.""")

    return "\n".join(parts)


def format_context_for_display(context: list[SearchResult]) -> str:
    """Formate le contexte pour affichage dans Discord (embed ou message)."""
    lines = []
    for item in context[:3]:  # Max 3 résultats affichés
        lines.append(f"### [{item.collection}] {item.id}")
        if item.prose:
            lines.append(item.prose[:500])
        if item.metadata_:
            meta_str = json_dumps_safe(item.metadata_)
            if len(meta_str) > 400:
                meta_str = meta_str[:400] + "..."
            lines.append(f"```json\n{meta_str}\n```")
        lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM execution — appel du LLM (Ollama → Claude fallback)
# ---------------------------------------------------------------------------

def execute_llm(
    llm: LLMProvider,
    prompt_text: str,
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Exécute le LLM et retourne la réponse textuelle."""
    response = llm.complete(
        prompt=prompt_text,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.strip()


# ---------------------------------------------------------------------------
# Pipeline complet — point d'entrée public
# ---------------------------------------------------------------------------

async def process_message(
    message: str,
    *,
    engine: KnowledgeEngineClient,
    llm: LLMProvider,
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    n_results: int = 5,
    game_version: str | None = None,
) -> PromptResult:
    """Pipeline complet : message Discord → recherche engine → prompt → LLM → réponse.

    Args:
        message: Message utilisateur brut.
        engine: KnowledgeEngineClient instance.
        llm: LLMProvider instance (Ollama/Claude).
        system_prompt: Prompt système de l'assistant.
        temperature: Température du LLM [0.0-1.0].
        max_tokens: Limite de tokens pour la réponse.
        n_results: Nombre maximal de résultats du moteur de recherche.
        game_version: Optionnel — filtre les requêtes par version PZ (b41/b42).
            La valeur est résolue automatiquement depuis ``src/governance/game_version``
            si ``None`` est passé explicitement.
    """
    # 1. Router l'intention
    command_type, query_text = detect_intent(message)

    # 2. Enrichir le contexte (avec filtre version si spécifié)
    context = enrich_context(engine, command_type, query_text, n_results=n_results, game_version=game_version)
    logger.info("Message → commande=%s, query=%q, results=%d", command_type, query_text, len(context))

    # 3. Construire le prompt
    prompt_text = build_prompt(context, query_text, command_type, system_prompt)

    # 4. Exécuter le LLM
    response = execute_llm(llm, prompt_text, system_prompt, temperature, max_tokens)

    return PromptResult(
        raw_context=context,
        prompt_text=prompt_text,
        llm_response=response,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def json_dumps_safe(obj: Any) -> str:
    """ sérialise en JSON avec fallback."""
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(obj)


def _extract_item_id(text: str) -> str | None:
    """Extrait un identifiant de type 'Base.Axe' du texte utilisateur."""
    match = re.search(r"([A-Z][a-zA-Z]+\.[A-Za-z]+)", text)
    return match.group(1) if match else None
