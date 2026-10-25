import json
import os
import stat

import pytest

from antigravity_mcp import server


def make_agy(tmp_path, body):
    p = tmp_path / "fakeagy"
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in ("AGY_BIN", "AGY_DEFAULT_MODEL", "AGY_TIMEOUT", "AGY_MODE", "AGY_SANDBOX", "AGY_SKIP_PERMISSIONS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(server, "LAST_CONVERSATIONS_PATH", tmp_path / "last.json")


def test_build_command_basic():
    cmd = server.build_command("/x/agy", "hola", "/w", "/l.log", "m1")
    assert cmd == [
        "/x/agy", "--add-dir", "/w", "--log-file", "/l.log", "--model", "m1",
        "--print-timeout", "600s", "-p", "hola",
    ]


def test_build_command_all_flags(monkeypatch):
    monkeypatch.setenv("AGY_SKIP_PERMISSIONS", "true")
    monkeypatch.setenv("AGY_SANDBOX", "true")
    monkeypatch.setenv("AGY_MODE", "plan")
    monkeypatch.setenv("AGY_TIMEOUT", "30")
    cmd = server.build_command("agy", "p", "/w", "/l", None, conversation="abc")
    assert cmd == [
        "agy", "--dangerously-skip-permissions", "--sandbox", "--mode", "plan",
        "--add-dir", "/w", "--log-file", "/l", "--conversation", "abc",
        "--print-timeout", "30s", "-p", "p",
    ]


def test_invalid_mode_ignored(monkeypatch):
    monkeypatch.setenv("AGY_MODE", "bogus")
    assert "--mode" not in server.build_command("agy", "p", "/w", "/l", None)


def test_skip_permissions_only_when_true(monkeypatch):
    monkeypatch.setenv("AGY_SKIP_PERMISSIONS", "yes")
    assert "--dangerously-skip-permissions" not in server.build_command("agy", "p", "/w", "/l", None)


async def test_success_with_session_id(tmp_path, monkeypatch):
    agy = make_agy(tmp_path, 'echo "respuesta: $*" | head -c 20; echo')
    monkeypatch.setenv("AGY_BIN", str(agy))
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "last.json").write_text(json.dumps({os.path.realpath(work): "sess-123"}))
    out = await server.execute_antigravity_task("hola", cwd=str(work))
    assert out.startswith("respuesta:")
    assert "model: gemini-3.8-flash-high | session: sess-123" in out


async def test_session_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(make_agy(tmp_path, "echo ok")))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert "session: desconocida" in out


async def test_follow_up_passes_conversation(tmp_path, monkeypatch):
    agy = make_agy(tmp_path, 'echo "$@"')
    monkeypatch.setenv("AGY_BIN", str(agy))
    out = await server.follow_up_antigravity_task("sess-9", "sigue", cwd=str(tmp_path))
    assert "--conversation sess-9" in out
    assert "--model" not in out


async def test_quota_429_in_log(tmp_path, monkeypatch):
    agy = make_agy(
        tmp_path,
        'while [ $# -gt 0 ]; do [ "$1" = "--log-file" ] && echo "RESOURCE_EXHAUSTED (code 429)" > "$2"; shift; done\necho x\nexit 1',
    )
    monkeypatch.setenv("AGY_BIN", str(agy))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert "429" in out and "cuota" in out.lower()


async def test_transient_429_with_successful_output(tmp_path, monkeypatch):
    agy = make_agy(
        tmp_path,
        'while [ $# -gt 0 ]; do [ "$1" = "--log-file" ] && echo "RESOURCE_EXHAUSTED (code 429)" > "$2"; shift; done\necho respuesta\nexit 0',
    )
    monkeypatch.setenv("AGY_BIN", str(agy))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert out.startswith("respuesta")
    assert "cuota" not in out.lower()


async def test_nonzero_exit_with_stderr_and_auth_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(make_agy(tmp_path, "echo 'not logged in: unauthenticated' >&2\nexit 3")))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert "código de salida 3" in out
    assert "unauthenticated" in out
    assert "ejecuta `agy`" in out


async def test_empty_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(make_agy(tmp_path, "exit 0")))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert "vacío" in out


async def test_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(make_agy(tmp_path, "sleep 30")))
    monkeypatch.setenv("AGY_TIMEOUT", "1")
    monkeypatch.setattr(server, "TIMEOUT_GRACE", 0.5)
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert "tiempo de espera" in out


async def test_invalid_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(make_agy(tmp_path, "echo ok")))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path / "nope"))
    assert "cwd inválido" in out


async def test_empty_task_and_missing_agy(tmp_path, monkeypatch):
    assert "vacía" in await server.execute_antigravity_task("  ")
    monkeypatch.setenv("AGY_BIN", str(tmp_path / "missing"))
    out = await server.execute_antigravity_task("hola", cwd=str(tmp_path))
    assert "no se encontró" in out


async def test_list_models(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(make_agy(tmp_path, r'printf "m1\tModelo Uno\n"')))
    assert "m1 - Modelo Uno" in await server.list_antigravity_models()
