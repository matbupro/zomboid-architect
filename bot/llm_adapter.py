"""
llm_adapter — Abstraction vers un ou plusieurs backends LLM.

Supporte :
  1. Ollama local (défaut, via API HTTP sur port 11434)
  2. Claude API (fallback, via Anthropic SDK)

L'ordre de préférence est configuré dans get_completion().
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMProvider:
    """Interface commune pour tous les backends LLM."""

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **extra_kwargs: Any,
    ) -> str:
        """Exécute un appel LLM et retourne le texte completé."""
        raise NotImplementedError

    @property
    def is_local(self) -> bool:
        return True

    @property
    def name(self) -> str:
        raise NotImplementedError


# ============================================================
# Ollama (local)
# ============================================================

class OllamaProvider(LLMProvider):
    """Appels API vers un serveur Ollama local (:11434)."""

    def __init__(self, base_url: str = "http://host.docker.internal:11434"):
        self._base_url = base_url.rstrip("/")
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError:
            httpx = None  # type: ignore[name-defined]
        self._http = httpx or None

    def _get_http(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(timeout=120.0)
        return self._http

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        model: str = "llama3.2",
        max_tokens: int = 4096,
        **_extra: Any,
    ) -> str:
        http = self._get_http()
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system_prompt:
            payload["system"] = system_prompt

        resp = http.post(f"{self._base_url}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

        response_text = data.get("response", "")
        if "done" in data and data["done"]:
            logger.info("Ollama %s → %d tokens générés", model, data.get("eval_count", "?"))
        return response_text.strip()

    @property
    def is_local(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "ollama"


# ============================================================
# Claude API (fallback)
# ============================================================

class ClaudeProvider(LLMProvider):
    """Appels via l'API Anthropic (Claude Sonnet/Opus)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._api_key = api_key
        self._model = model
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError:
            httpx = None  # type: ignore[name-defined]
        self._http = httpx or None

    def _get_http(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(timeout=120.0)
        return self._http

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        model: str | None = None,
        max_tokens: int = 4096,
        **_extra: Any,
    ) -> str:
        model = model or self._model
        http = self._get_http()
        system = system_prompt or ""

        # Construire le message utilisateur en incluant le contexte LLM brut
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        resp = http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
        return "\n".join(text_parts).strip()

    @property
    def is_local(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "claude"


# ============================================================
# Fabrique
# ============================================================

def create_providers(
    ollama_url: str = "http://host.docker.internal:11434",
    ollama_model: str = "llama3.2",
    claude_key: str | None = None,
    claude_model: str = "claude-sonnet-4-20250514",
) -> tuple[OllamaProvider, ClaudeProvider | None]:
    """Crée le provider local + le fallback (optionnel)."""
    ollama = OllamaProvider(ollama_url)
    claude = ClaudeProvider(claude_key, claude_model) if claude_key else None
    return ollama, claude
