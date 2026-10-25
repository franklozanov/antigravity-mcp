"""Servidor MCP (stdio) que reenvía tareas a un API de Antigravity.

stdout es el canal MCP: todos los logs van a stderr.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[antigravity-mcp] %(message)s")
log = logging.getLogger("antigravity-mcp")

# Marcador: hay que apuntarlo al endpoint real (ver README).
DEFAULT_API_URL = "https://api.antigravity.example/v1/tasks"
FALLBACK_MODEL = "gemini-1.5-flash"
MAX_ERROR_BODY = 500

mcp = FastMCP("Antigravity Bridge")


def _timeout() -> float:
    try:
        value = float(os.environ.get("ANTIGRAVITY_TIMEOUT", "120"))
        return value if value > 0 else 120.0
    except ValueError:
        return 120.0


def _extract_text(data: Any) -> str:
    """Busca el texto de resultado en campos habituales; si no, devuelve el JSON."""
    if isinstance(data, dict):
        for key in ("result", "output", "text", "response", "content", "message"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def execute_antigravity_task(task_description: str, model_name: str = FALLBACK_MODEL) -> str:
    """Envía una tarea al API de Antigravity y devuelve su resultado.

    Args:
        task_description: Descripción completa de la tarea a ejecutar.
        model_name: Modelo a usar (por defecto gemini-1.5-flash). Si se deja el
            valor por defecto y existe ANTIGRAVITY_DEFAULT_MODEL, se usa ese.
    """
    if not task_description or not task_description.strip():
        return "Error: la descripción de la tarea está vacía."

    api_key = os.environ.get("ANTIGRAVITY_API_KEY", "").strip()
    if not api_key:
        return "Error: falta ANTIGRAVITY_API_KEY en el entorno del servidor."

    url = os.environ.get("ANTIGRAVITY_API_URL", "").strip() or DEFAULT_API_URL
    default_model = os.environ.get("ANTIGRAVITY_DEFAULT_MODEL", "").strip()
    model = default_model if (default_model and model_name == FALLBACK_MODEL) else model_name

    # Contrato JSON supuesto: ajústalo al API real.
    payload = {"model": model, "task": task_description}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=_timeout())
        response.raise_for_status()
    except httpx.TimeoutException:
        return f"Error: tiempo de espera agotado ({_timeout():g} s) al llamar al API de Antigravity."
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:MAX_ERROR_BODY]
        return f"Error HTTP {exc.response.status_code} del API de Antigravity: {body}"
    except httpx.HTTPError as exc:
        return f"Error de red al llamar al API de Antigravity: {type(exc).__name__}"

    try:
        data = response.json()
    except ValueError:
        return f"Error: la respuesta del API no es JSON válido: {response.text[:MAX_ERROR_BODY]}"

    return _extract_text(data)


def main() -> None:
    if not os.environ.get("ANTIGRAVITY_API_KEY", "").strip():
        print(
            "Error: falta la variable de entorno ANTIGRAVITY_API_KEY.\n"
            "Defínela en un archivo .env (ver .env.example), en el entorno, o con "
            "`claude mcp add ... -e ANTIGRAVITY_API_KEY=...`.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not os.environ.get("ANTIGRAVITY_API_URL", "").strip():
        log.warning("ANTIGRAVITY_API_URL no definida; se usa el marcador %s", DEFAULT_API_URL)
    mcp.run()


if __name__ == "__main__":
    main()
