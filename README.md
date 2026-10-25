# antigravity-mcp

Servidor MCP (FastMCP, transporte stdio) que permite a Claude enviar tareas a un API de Antigravity mediante la herramienta `execute_antigravity_task`.

## Requisitos

- Python 3.10 o superior
- Una clave de API de Antigravity

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `ANTIGRAVITY_API_KEY` | Sí | Clave enviada como `Authorization: Bearer`. Nunca se imprime. |
| `ANTIGRAVITY_API_URL` | Sí en la práctica | Endpoint del API. El valor por defecto es un marcador (`https://api.antigravity.example/v1/tasks`): hay que apuntarlo al endpoint real. |
| `ANTIGRAVITY_DEFAULT_MODEL` | No | Modelo usado cuando la llamada no indica uno distinto de `gemini-1.5-flash`. |
| `ANTIGRAVITY_TIMEOUT` | No | Tiempo de espera en segundos (por defecto 120). |

## Instalación local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # y completa los valores
antigravity-mcp
```

No subas el archivo `.env` al repositorio (ya está en `.gitignore`).

## Integración con Claude

Cuando el repositorio sea público:

```bash
claude mcp add antigravity-bridge \
  -e ANTIGRAVITY_API_KEY=tu_clave \
  -e ANTIGRAVITY_API_URL=https://tu-endpoint \
  -- uvx --from git+https://github.com/TU_USUARIO_GITHUB/antigravity-mcp.git antigravity-mcp
```

Alternativa con pipx:

```bash
claude mcp add antigravity-bridge \
  -e ANTIGRAVITY_API_KEY=tu_clave \
  -- pipx run --spec git+https://github.com/TU_USUARIO_GITHUB/antigravity-mcp.git antigravity-mcp
```

Las variables también pueden venir de un `.env` en el directorio de trabajo o de variables globales del sistema.

## Ajustar al API real

El endpoint y el contrato JSON (cuerpo `{"model", "task"}` y campos de respuesta como `result`, `output` o `text`) son supuestos: ajústalos en `src/antigravity_mcp/server.py`.
