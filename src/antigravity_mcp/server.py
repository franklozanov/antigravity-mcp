"""Servidor MCP (stdio) que ejecuta el CLI local `agy` (Antigravity) como subproceso.

Usa la sesión iniciada en agy (autenticación interna de la cuenta de Antigravity);
no requiere clave de API. stdout es el canal MCP: todos los logs van a stderr.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[antigravity-mcp] %(message)s")
log = logging.getLogger("antigravity-mcp")

DEFAULT_MODEL = "gemini-3.8-flash-high"
DEFAULT_TIMEOUT = 600.0
TIMEOUT_GRACE = 15.0
VALID_MODES = ("accept-edits", "auto", "plan")
STDERR_TAIL_LINES = 20
MAX_STDERR_CHARS = 2000

# Rutas de agy (módulo-nivel para poder sustituirlas en tests).
LAST_CONVERSATIONS_PATH = Path.home() / ".gemini" / "antigravity-cli" / "cache" / "last_conversations.json"
TOKEN_PATH = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"

mcp = FastMCP("Antigravity Bridge")


# --------------------------------------------------------------------------- config
def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def _timeout() -> float:
    try:
        value = float(os.environ.get("AGY_TIMEOUT", "").strip() or DEFAULT_TIMEOUT)
        return value if value > 0 else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def _default_model() -> str:
    return os.environ.get("AGY_DEFAULT_MODEL", "").strip() or DEFAULT_MODEL


def _mode() -> str | None:
    raw = os.environ.get("AGY_MODE", "").strip()
    if not raw:
        return None
    if raw in VALID_MODES:
        return raw
    log.warning("AGY_MODE inválido (%r); se ignora. Valores válidos: %s", raw, ", ".join(VALID_MODES))
    return None


def find_agy() -> str | None:
    """AGY_BIN, luego PATH, luego ~/.local/bin/agy. None si no se encuentra."""
    explicit = os.environ.get("AGY_BIN", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        return None
    found = shutil.which("agy")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "agy"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    return None


def build_command(
    agy: str,
    prompt: str,
    cwd: str,
    log_file: str,
    model: str | None,
    conversation: str | None = None,
) -> list[str]:
    cmd = [agy]
    if _env_bool("AGY_SKIP_PERMISSIONS"):
        cmd.append("--dangerously-skip-permissions")
    if _env_bool("AGY_SANDBOX"):
        cmd.append("--sandbox")
    mode = _mode()
    if mode:
        cmd += ["--mode", mode]
    cmd += ["--add-dir", cwd, "--log-file", log_file]
    if conversation:
        cmd += ["--conversation", conversation]
    if model:
        cmd += ["--model", model]
    cmd += ["--print-timeout", f"{int(_timeout())}s", "-p", prompt]
    return cmd


def read_session_id(cwd: str) -> str | None:
    """Lee el id de la última conversación del cwd. Frágil con concurrencia en el mismo cwd."""
    try:
        data = json.loads(LAST_CONVERSATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value: Any = data.get(os.path.realpath(cwd))
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        for key in ("id", "conversation_id", "conversationId", "cascadeId"):
            v = value.get(key)
            if isinstance(v, str) and v:
                return v
    return None


# --------------------------------------------------------------------------- ejecución
def _check_cwd(cwd: str | None) -> tuple[str | None, str | None]:
    resolved = os.path.realpath(cwd) if cwd else os.getcwd()
    if not os.path.isdir(resolved):
        return None, f"Error: cwd inválido, no existe o no es un directorio: {cwd}"
    return resolved, None


def _tail(text: str) -> str:
    lines = text.strip().splitlines()[-STDERR_TAIL_LINES:]
    out = "\n".join(lines)
    return out[-MAX_STDERR_CHARS:]


def _read_log(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


async def _run_agy(args: list[str], cwd: str, timeout: float) -> tuple[int | None, str, str]:
    """Devuelve (returncode, stdout, stderr); returncode None si venció el tiempo."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return None, "", ""
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


async def _execute(prompt: str, model: str | None, cwd: str | None, conversation: str | None) -> str:
    resolved, err = _check_cwd(cwd)
    if err or resolved is None:
        return err or "Error: cwd inválido."
    agy = find_agy()
    if not agy:
        return (
            "Error: no se encontró el CLI `agy`. Define AGY_BIN con la ruta absoluta "
            "(`which agy`) o instala Antigravity."
        )

    fd, log_path = tempfile.mkstemp(prefix="agy-mcp-", suffix=".log")
    os.close(fd)
    try:
        cmd = build_command(agy, prompt, resolved, log_path, model, conversation)
        timeout = _timeout()
        try:
            code, stdout, stderr = await _run_agy(cmd, resolved, timeout + TIMEOUT_GRACE)
        except OSError as exc:
            return f"Error: no se pudo ejecutar agy ({exc})."
        if code is None:
            return f"Error: tiempo de espera agotado ({timeout:g} s); se detuvo el proceso de agy."

        log_text = _read_log(log_path)
        combined = f"{stderr}\n{log_text}"
        failed = code != 0 or not stdout.strip()
        # Un 429 en el log con salida correcta es un reintento interno de agy, no un fallo.
        if failed and ("RESOURCE_EXHAUSTED" in combined or "code 429" in combined):
            return (
                "Error: cuota de Antigravity agotada (RESOURCE_EXHAUSTED, código 429). "
                "Espera a que se restablezca o cambia de modelo."
            )
        if code != 0:
            msg = f"Error: agy terminó con código de salida {code}."
            tail = _tail(stderr)
            if tail:
                msg += f"\nstderr (últimas líneas):\n{tail}"
            if any(w in stderr.lower() for w in ("login", "auth", "unauthenticated")):
                msg += "\nPosible falta de sesión: ejecuta `agy` una vez para iniciar sesión."
            return msg
        if not stdout.strip():
            return "Error: agy no devolvió salida (stdout vacío)."

        session = read_session_id(resolved) or "desconocida"
        used_model = model or ("(el de la conversación)" if conversation else _default_model())
        return f"{stdout.strip()}\n\n[antigravity-mcp] model: {used_model} | session: {session}"
    finally:
        try:
            os.unlink(log_path)
        except OSError:
            pass


# --------------------------------------------------------------------------- tools
@mcp.tool()
async def execute_antigravity_task(
    task_description: str, model_name: str | None = None, cwd: str | None = None
) -> str:
    """Ejecuta una tarea con el CLI local agy (Antigravity) y devuelve su respuesta.

    Args:
        task_description: Descripción completa de la tarea.
        model_name: Id de modelo de `agy models` (por defecto AGY_DEFAULT_MODEL).
        cwd: Directorio de trabajo (por defecto el del servidor). Debe existir.
    """
    if not task_description or not task_description.strip():
        return "Error: la descripción de la tarea está vacía."
    model = (model_name or "").strip() or _default_model()
    return await _execute(task_description, model, cwd, None)


@mcp.tool()
async def follow_up_antigravity_task(session_id: str, message: str, cwd: str | None = None) -> str:
    """Continúa una conversación previa de agy con su session id.

    Args:
        session_id: Id devuelto en el pie `session:` de una respuesta anterior.
        message: Mensaje de seguimiento.
        cwd: Mismo directorio de trabajo de la conversación original.
    """
    if not message or not message.strip():
        return "Error: el mensaje está vacío."
    if not session_id or not session_id.strip():
        return "Error: falta el session_id."
    return await _execute(message, None, cwd, session_id.strip())


@mcp.tool()
async def list_antigravity_models() -> str:
    """Lista los modelos disponibles en agy (id y nombre)."""
    agy = find_agy()
    if not agy:
        return "Error: no se encontró el CLI `agy`. Define AGY_BIN con la ruta absoluta."
    try:
        code, out, err = await _run_agy([agy, "models"], os.getcwd(), 60)
    except OSError as exc:
        return f"Error: no se pudo ejecutar agy ({exc})."
    if code is None:
        return "Error: tiempo de espera agotado al listar modelos."
    if code != 0:
        return f"Error: `agy models` terminó con código {code}.\n{_tail(err)}"
    lines = []
    for line in out.strip().splitlines():
        parts = line.split("\t", 1)
        lines.append(f"{parts[0]} - {parts[1]}" if len(parts) == 2 else line)
    return "\n".join(lines) or "Error: agy no devolvió modelos."


def main() -> None:
    if not find_agy():
        print(
            "[antigravity-mcp] Error: no se encontró el CLI `agy`. "
            "Instálalo o define AGY_BIN con su ruta absoluta (`which agy`).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not TOKEN_PATH.exists():
        log.warning("No se encontró el token de Antigravity: inicia sesión ejecutando `agy`.")
    mcp.run()


if __name__ == "__main__":
    main()
