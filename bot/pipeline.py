"""
pipeline — Chaîne de traitement des messages Discord → réponse Zomboid.

Flux :
    message utilisateur
        → router (detecte le type de commande / la collection pertinente)
        → engine.search() ou engine.get_by_id() pour recuperer le contexte Zomboid
        → construction du prompt LLM (contexte JSON brut + question)
        → LLM.complete() (Ollama en priorite, Claude en fallback)
        → retour du texte de reponse

Gestion d'erreurs unifiee :
    - Les erreurs LLM sont capturees et converties en messages utilisateur clairs
    - Le circuit-breaker dans llm_adapter.py evite les tentatives repetees sur un
      provider en erreur, permettant le fallback automatique au second provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .engine_client import KnowledgeEngineClient, SearchResult
from .llm_adapter import LLMProvider, OllamaProvider, ClaudeProvider, LLMError, CircuitBreakerOpen

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Messages d'erreur unifies pour l'utilisateur (jamais de tech-dump)
# ---------------------------------------------------------------------------

LLM_ERROR_MESSAGES: dict[str, str] = {
    "timeout": (
        "⏱ La reponse du modele a expire. Merci de reessayer dans quelques instants."
    ),
    "unavailable": (
        "🔌 Le modele LLM est temporairement inaccessible. Tentative du fallback..."
    ),
    "rate_limit": (
        "⚠️ La limite d'appels API a ete atteinte. Veuillez recommencer plus tard."
    ),
    "unknown": (
        "❌ Une erreur inattendue s'est produite lors de la generation de la reponse."
    ),
}


@dataclass
class PromptResult:
    """Résultat d'une passe du pipeline."""
    raw_context: list[SearchResult]   # Resultats bruts du knowledge engine (JSON brut)
    prompt_text: str                  # Prompt construit pour le LLM
    llm_response: str                 # Reponse du LLM


# ---------------------------------------------------------------------------
# Routing — detection de l'intention et selection de collections
# ---------------------------------------------------------------------------

COLLECTION_ROUTES = {
    "stats": ["pz_items"],
    "survie": ["pz_mechanics", "pz_items"],
    "recipe": ["pz_recipes", "pz_mechanics"],
    "moddoc": ["pz_lua_api", "pz_java_api"],
    "search": ["pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api"],
}

# Regex patterns pour detection automatique de commandes implicites
PATTERN_ITEM_ID = re.compile(r"(?:stat[s]?|stats?)\s*(?:de\s*)?([A-Z][a-zA-Z]+\.[A-Za-z]+)", re.IGNORECASE)
PATTERN_RECIPE = re.compile(r"(?:recette[es]?\s+(?:pour\s+)?)([A-Z][a-zA-Z]+(?:\s+[A-Za-z]+)?)", re.IGNORECASE)


def detect_intent(message: str) -> tuple[str, str]:
    """Detecte le type de commande et extrait la requete.

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

    # Detection implicite
    match_id = PATTERN_ITEM_ID.search(msg)
    if match_id:
        return ("stats", match_id.group(1))

    if any(kw in msg for kw in ["recette", "craft", "artisanat"]):
        return ("recipe", msg)

    if any(kw in msg for kw in ["moddoc", "lua api", "java api", "modding", "hook"]):
        return ("moddoc", msg)

    # Defaut : recherche libre sur toutes les collections
    return ("search", msg)


# ---------------------------------------------------------------------------
# Context enrichment — requete au knowledge engine
# ---------------------------------------------------------------------------

def enrich_context(
    client: KnowledgeEngineClient,
    command_type: str,
    query_text: str,
    n_results: int = 5,
    game_version: str | None = None,
) -> list[SearchResult]:
    """Recupere le contexte pertinent depuis le knowledge engine.

    Args:
        client: KnowledgeEngineClient instance.
        command_type: Type de commande detecte (stats, survie, etc.).
        query_text: Texte de la requete utilisateur.
        n_results: Nombre maximal de resultats.
        game_version: Optionnel — filtre les resultats par version PZ (b41/b42).
    """
    collections = COLLECTION_ROUTES.get(command_type, ["pz_items"])

    # Pour /stats : essayer d'abord un lookup deterministe par ID
    if command_type == "stats":
        item_id = _extract_item_id(query_text)
        if item_id:
            result = client.get_by_id(item_id, collection="pz_items", game_version=game_version)
            if result:
                return [result]

    # Requete vectorielle sur les collections pertinentes
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
    - Le Systeme (regles de l'assistant)
    - Le contexte JSON brut du knowledge engine (non reformule)
    - La question de l'utilisateur
    """
    # Section contexte : valeurs exactes du knowledge engine
    context_sections = []
    for item in context:
        section = f"--- [{item.collection}] ID:{item.id} ---\n"
        # Champ JSON brut (metadonnees exactes)
        if item.metadata_:
            section += f"JSON_BRUT:\n{json_dumps_safe(item.metadata_)}\n"
        # Champ prose (description lisible)
        if item.prose:
            section += f"PROSE:\n{item.prose}\n"
        context_sections.append(section)

    context_text = "\n".join(context_sections) if context_sections else "(Aucune donnee trouvee dans le knowledge engine)"

    # Format du prompt
    parts = [system_prompt, ""]

    if command_type == "stats":
        parts.append(f"""Donnees exactes de l'objet :
{context_text}

Question : {question}

Reponds avec les stats precises. N'invente jamais de valeurs chiffrées.""")
    elif command_type == "survie":
        parts.append(f"""Donnees mecaniques pertinentes :
{context_text}

Scénario du joueur : {question}

Donne un conseil de survie precis base sur ces donnees.""")
    elif command_type == "recipe":
        parts.append(f"""Donnees recettes :
{context_text}

Recette demandée : {question}

Liste les ingrédients exacts et l'étape de craft si disponible.""")
    elif command_type == "moddoc":
        parts.append(f"""Documentation API pertinente :
{context_text}

Question sur le modding : {question}

Reponds avec la documentation technique exacte.""")
    else:  # search
        parts.append(f"""Donnees trouvees :
{context_text}

Question : {question}

Synthétise une reponse utile basee sur les donnees ci-dessus.""")

    return "\n".join(parts)


def format_context_for_display(context: list[SearchResult]) -> str:
    """Formate le contexte pour affichage dans Discord (embed ou message)."""
    lines = []
    for item in context[:3]:  # Max 3 resultats affiches
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
    """Execute le LLM et retourne la reponse textuelle.

    Capture les erreurs LLM (timeout, circuit-breaker, etc.) et les convertit
    en messages utilisateurs clairs au lieu de crasher le pipeline.

    Args:
        llm: Provider LLM utilise (Ollama ou Claude).
        prompt_text: Prompt a envoyer au modele.
        system_prompt: Instructions du systeme.
        temperature: Temperature [0.0-1.0].
        max_tokens: Limite de tokens.

    Returns:
        Reponse textuelle, ou un message d'erreur si l'appel echoue.
    """
    try:
        response = llm.complete(
            prompt=prompt_text,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.strip()
    except LLMError as exc:
        logger.warning("LLM error from %s: %s", llm.name, exc)
        # Choisir le message utilisateur adapte au type d'erreur
        msg_key = "unknown"
        if "timeout" in str(exc).lower():
            msg_key = "timeout"
        elif "unavailable" in str(exc).lower() or "unreachable" in str(exc).lower():
            msg_key = "unavailable"
        elif "rate limit" in str(exc).lower():
            msg_key = "rate_limit"
        return LLM_ERROR_MESSAGES.get(msg_key, LLM_ERROR_MESSAGES["unknown"])


# ---------------------------------------------------------------------------
# Pipeline complet — point d'entree public
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
    """Pipeline complet : message Discord → recherche engine → prompt → LLM → reponse.

    Les erreurs LLM sont capturees et converties en messages utilisateur clairs
    sans crasher le bot Discord.

    Args:
        message: Message utilisateur brut.
        engine: KnowledgeEngineClient instance.
        llm: LLMProvider instance (Ollama/Claude).
        system_prompt: Prompt Systeme de l'assistant.
        temperature: Temperature du LLM [0.0-1.0].
        max_tokens: Limite de tokens pour la reponse.
        n_results: Nombre maximal de resultats du moteur de recherche.
        game_version: Optionnel — filtre les requêtes par version PZ (b41/b42).
            La valeur est resolue automatiquement depuis ``src/governance/game_version``
            si ``None`` est passe explicitement.
    """
    # 1. Router l'intention
    command_type, query_text = detect_intent(message)

    # 2. Enrichir le contexte (avec filtre version si specifie)
    context = enrich_context(engine, command_type, query_text, n_results=n_results, game_version=game_version)
    logger.info("Message → commande=%s, query=%q, results=%d", command_type, query_text, len(context))

    # 3. Construire le prompt
    prompt_text = build_prompt(context, query_text, command_type, system_prompt)

    # 4. Executer le LLM (avec capture d'erreurs unifiée)
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
    """ serialise en JSON avec fallback."""
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(obj)


def _extract_item_id(text: str) -> str | None:
    """Extrait un identifiant de type 'Base.Axe' du texte utilisateur."""
    match = re.search(r"([A-Z][a-zA-Z]+\.[A-Za-z]+)", text)
    return match.group(1) if match else None
