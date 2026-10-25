# antigravity-mcp

Servidor MCP (FastMCP, stdio) que ejecuta el CLI local `agy` (Antigravity) como subproceso. Usa la autenticación interna de tu cuenta de Antigravity: no necesita clave de API ni genera cobro del API de Gemini.

## Requisitos

- Python 3.10 o superior.
- `agy` instalado y con la sesión iniciada (ejecuta `agy` una vez y accede a tu cuenta).

## Herramientas

- `execute_antigravity_task(task_description, model_name?, cwd?)`: ejecuta una tarea. Devuelve la respuesta y un pie `[antigravity-mcp] model: ... | session: ...`.
- `follow_up_antigravity_task(session_id, message, cwd?)`: continúa una conversación (`--conversation`).
- `list_antigravity_models()`: lista los ids de `agy models`.

## Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `AGY_BIN` | `agy` del PATH, o `~/.local/bin/agy` | Ruta al binario |
| `AGY_DEFAULT_MODEL` | `gemini-3.8-flash-high` | Modelo por defecto |
| `AGY_TIMEOUT` | `600` | Segundos máximos por tarea |
| `AGY_MODE` | (vacío) | `accept-edits`, `auto` o `plan`; otro valor se ignora con aviso |
| `AGY_SANDBOX` | `false` | `true` pasa `--sandbox` |
| `AGY_SKIP_PERMISSIONS` | `false` | Solo `true` pasa `--dangerously-skip-permissions` |

## Instalación local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Integración con Claude Code

```bash
claude mcp add antigravity-bridge -e AGY_BIN=/ruta/absoluta/a/agy -- \
  uvx --from git+https://github.com/franklozanov/antigravity-mcp.git antigravity-mcp
```

Usa una ruta absoluta en `AGY_BIN` (`which agy` la da): las aplicaciones gráficas suelen tener un PATH reducido y no encuentran `agy`.

Alternativa con pipx:

```bash
pipx install git+https://github.com/franklozanov/antigravity-mcp.git
claude mcp add antigravity-bridge -e AGY_BIN=/ruta/absoluta/a/agy -- antigravity-mcp
```

## Seguridad

`AGY_SKIP_PERMISSIONS=true` permite que agy ejecute comandos y edite archivos sin pedir confirmación. Actívalo solo en directorios y con tareas de confianza; considera combinarlo con `AGY_SANDBOX=true`.

## Limitaciones

El id de sesión no sale por stdout: se lee después de la ejecución de `~/.gemini/antigravity-cli/cache/last_conversations.json`, por la ruta real del `cwd`. Si hay dos ejecuciones simultáneas en el mismo `cwd`, el id podría corresponder a la otra; usa directorios distintos para tareas en paralelo.
