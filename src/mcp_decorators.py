"""safe_tool — Decorateur d'isolation des handlers MCP.

Chaque handler MCP est un point d'entree exterieur non fiable (appels Claude Code, Discord bot, CLI).
Ce decorateur assure que toute erreur interne ne propage jamais vers l'appelant et retourne
toujours une structure de reponse JSON-safe.

Usage:
    from src.mcp_decorators import safe_tool

    @safe_tool(timeout=60)
    def my_mcp_handler(input_data: dict[str, Any]) -> dict[str, Any]:
        return {"result": do_work(input_data)}

L'appelant recevra toujours:
    - success=True + result en cas de succes
    - success=False + error + traceback en cas d'erreur
"""

from __future__ import annotations

import asyncio
import functools
import traceback
from typing import Any, Callable


def safe_tool(
    timeout: float | None = None,
    on_error: Callable[[Exception], str] | None = None,
) -> Callable[[Callable[..., dict]], Callable[..., dict]]:
    """Decorateur qui encapsule un handler MCP avec gestion d'erreur.

    Args:
        timeout: Timeout en secondes (None = pas de timeout). Raise asyncio.TimeoutError si depasse.
        on_error: Custom error formatter. Par defaut, retourne le message d'exception.

    Returns:
        Decorateur qui transforme un handler → dict en un handler resilient → dict safe.
    """
    def decorator(fn: Callable[..., dict]) -> Callable[..., dict]:
        fn_name = fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                result = fn(*args, **kwargs)
                return {"success": True, "result": result}
            except Exception as exc:  # noqa: BLE001
                error_msg = (on_error(exc) if on_error else str(exc))[:2000]
                return {
                    "success": False,
                    "error": error_msg,
                    "traceback": traceback.format_exc()[-3000:],
                    "_tool": fn_name,
                }

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[reportGeneralTypeIssues]
                try:
                    if timeout is not None:
                        result = await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
                    else:
                        result = await fn(*args, **kwargs)
                    return {"success": True, "result": result}
                except asyncio.TimeoutError:  # noqa: PERF203
                    error_msg = f"Timeout après {timeout}s dans {fn_name}"
                    return {
                        "success": False,
                        "error": error_msg[:2000],
                        "traceback": "",
                        "_tool": fn_name,
                    }
                except Exception as exc:  # noqa: BLE001
                    error_msg = (on_error(exc) if on_error else str(exc))[:2000]
                    return {
                        "success": False,
                        "error": error_msg,
                        "traceback": traceback.format_exc()[-3000:],
                        "_tool": fn_name,
                    }

            return async_wrapper  # type: ignore[return-value]

        return wrapper  # type: ignore[return-value]

    return decorator


# =====================================================================
# Exemples d'utilisation
# =====================================================================

if __name__ == "__main__":
    from src.mcp_tools import pz_get_item, pz_search_all

    @safe_tool(timeout=30)
    def run_demo():
        # Test pz_get_item
        print("--- pz_get_item(Base.Axe) ---")
        result = pz_get_item("Base.Axe", game_version="b41")
        print(result)

        print("\n--- pz_search_all('axe') ---")
        results = pz_search_all("how to craft an axe", n_results=3)
        print(results)

    run_demo()
