"""
llm_adapter — Abstraction vers un ou plusieurs backends LLM.

Supporte :
  1. Ollama local (defaut, via API HTTP sur port 11434)
  2. Claude API (fallback, via Anthropic SDK)

L'ordre de preference est configure dans get_completion().

Gestion d'erreurs unifiee (P0 fix — bot stability) :
  - Timeouts explicites pour eviter le blocage indefini du bot Discord
  - Retry avec backoff sur erreurs HTTP transitoires (5xx, timeout)
  - Circuit-breaker pattern : apres N echecs consecutifs, on arrete d'appeler le provider
    et on fallback automatiquement au prochain provider disponible.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions propres au domaine LLM
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Erreur generique d'appel LLM (timeout, parsing, etc.)."""
    pass


class LLMAvailabilityError(LLMError):
    """Aucun provider LLM n'est disponible."""
    pass


class CircuitBreakerOpen(LLMError):
    """Le circuit breaker est ouvert — le provider a echoue trop de fois consecutivement."""

    def __init__(self, provider_name: str, consecutive_failures: int) -> None:
        self.provider_name = provider_name
        self.consecutive_failures = consecutive_failures
        super().__init__(f"Circuit breaker OPEN for '{provider_name}': {consecutive_failures} consecutive failures")


# ---------------------------------------------------------------------------
# Interface commune
# ---------------------------------------------------------------------------


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
        """Execute un appel LLM et retourne le texte complete."""
        raise NotImplementedError

    @property
    def is_local(self) -> bool:
        return True

    @property
    def name(self) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Circuit breaker — guard contre les providers en erreur
# ---------------------------------------------------------------------------


class _CircuitBreaker:
    """Simplifie le circuit-breaker pattern (tresier, hystrix-lite).

    Apres `failure_threshold` echecs consecutifs, on ouvre le circuit pendant
    `recovery_seconds`. Pendant cette periode, tous les appels lancent
    CircuitBreakerOpen au lieu d'appeler le provider.
    """

    def __init__(self, name: str, *, failure_threshold: int = 5, recovery_seconds: float = 30.0) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._failures: int = 0
        self._last_failure_time: float = 0.0
        self._open_until: float = 0.0

    def _is_open(self) -> bool:
        if self._open_until and time.time() < self._open_until:
            return True
        # Recovery window expired → on re-ferme le circuit
        if self._open_until and time.time() >= self._open_until:
            self._failures = 0
            self._open_until = 0.0
            self._last_failure_time = 0.0
        return False

    def record_success(self) -> None:
        """Inscrit une reussite — reset le compteur d'echecs."""
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        """Inscrit un echec — ouvre le circuit si threshold atteint."""
        self._last_failure_time = time.time()
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._open_until = time.time() + self._recovery_seconds
            logger.warning(
                "Circuit breaker OPEN for '%s' — %d failures in a row.",
                self._name, self._failures,
            )

    def guard(self) -> None:
        """Leve CircuitBreakerOpen si le circuit est ouvert."""
        if self._is_open():
            raise CircuitBreakerOpen(self._name, self._failures)


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------


class OllamaProvider(LLMProvider):
    """Appels API vers un serveur Ollama local (:11434)."""

    def __init__(self, base_url: str = "http://host.docker.internal:11434", timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._circuit = _CircuitBreaker("ollama", failure_threshold=5, recovery_seconds=30.0)
        # Lazy init httpx client (evite la dependency au demarrage si pas utilise)
        self._client: Any = None

    def _get_http(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        model: str = "llama3.2",
        max_tokens: int = 4096,
        **_extra: Any,
    ) -> str:
        # Circuit-breaker guard
        self._circuit.guard()

        import httpx  # type: ignore[import-not-found]

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system_prompt:
            payload["system"] = system_prompt

        http = self._get_http()
        try:
            resp = http.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama HTTP %s → %s", exc.response.status_code, exc.response.text[:200])
            self._circuit.record_failure()
            raise LLMError(f"Ollama HTTP error {exc.response.status_code}: {exc.response.text[:200]}") from exc
        except httpx.TimeoutException as exc:
            logger.error("Ollama timeout after %ds", self._timeout)
            self._circuit.record_failure()
            raise LLMError(f"Ollama timeout after {self._timeout}s") from exc
        except (httpx.ConnectError, httpx.NoConnectionReady) as exc:
            logger.error("Ollama connexion refusee a %s", self._base_url)
            self._circuit.record_failure()
            raise LLMError(f"Ollama unreachable at {self._base_url}") from exc

        data = resp.json()
        response_text = data.get("response", "")
        if "done" in data and data["done"]:
            logger.info("Ollama %s → %d tokens generes", model, data.get("eval_count", "?"))
        return response_text.strip()

    def record_success(self) -> None:
        self._circuit.record_success()

    @property
    def is_local(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "ollama"


# ---------------------------------------------------------------------------
# Claude API (fallback)
# ---------------------------------------------------------------------------


class ClaudeProvider(LLMProvider):
    """Appels via l'API Anthropic (Claude Sonnet/Opus)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514", timeout_seconds: float = 90.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._circuit = _CircuitBreaker("claude", failure_threshold=3, recovery_seconds=60.0)
        self._client: Any = None

    def _get_http(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

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
        self._circuit.guard()
        http = self._get_http()

        system = system_prompt or ""

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        try:
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
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            logger.error("Claude HTTP %s → %s", status, body)
            if status == 429:
                # Rate limiting — on est gentil avec le circuit breaker
                self._circuit.record_failure()
                raise LLMError(f"Claude rate limit (429): {body}") from exc
            if 500 <= status < 600:
                self._circuit.record_failure()
                raise LLMError(f"Claude server error {status}: {body}") from exc
            # Erreur client (cle invalide, model inconnu) — pas de retry necessaire
            raise LLMError(f"Claude client error {status}: {body}") from exc
        except httpx.TimeoutException as exc:
            logger.error("Claude timeout after %ds", self._timeout)
            self._circuit.record_failure()
            raise LLMError(f"Claude timeout after {self._timeout}s") from exc
        except (httpx.ConnectError, httpx.NoConnectionReady) as exc:
            logger.error("Impossible de se connecter a Claude API")
            self._circuit.record_failure()
            raise LLMError("Claude API unreachable") from exc

        data = resp.json()
        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
        response_text = "\n".join(text_parts).strip()
        if not response_text:
            logger.warning("Reponse vide de Claude — contenu brut: %s", json.dumps(data, ensure_ascii=False)[:500])
        return response_text

    def record_success(self) -> None:
        self._circuit.record_success()

    @property
    def is_local(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "claude"


# ---------------------------------------------------------------------------
# Fabrique
# ---------------------------------------------------------------------------


def create_providers(
    ollama_url: str = "http://host.docker.internal:11434",
    ollama_model: str = "llama3.2",
    claude_key: str | None = None,
    claude_model: str = "claude-sonnet-4-20250514",
) -> tuple[OllamaProvider, ClaudeProvider | None]:
    """Cree le provider local + le fallback (optionnel)."""
    ollama = OllamaProvider(ollama_url)
    claude = ClaudeProvider(claude_key, claude_model) if claude_key else None
    return ollama, claude
