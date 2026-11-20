import os
import sys

import pytest

from agent.filesystem import FileSystem
from agent.history import InvalidConversationId, load_conversation, validate_conversation_id
from agent.tools import _command_program, _resolve_path, run_command
from execution.sandbox import safe_subprocess_env
from ui.security import allowed_hostnames, check_request
from ui.session import browse_directory, validate_workspace

# ── Path containment ─────────────────────────────────────────────────────────


@pytest.fixture
def sibling_dirs(tmp_path):
    ws = tmp_path / "proj"
    sibling = tmp_path / "proj2"
    ws.mkdir()
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret")
    return ws, sibling


def test_tool_paths_cannot_escape_to_sibling_prefix(sibling_dirs):
    ws, _ = sibling_dirs
    with pytest.raises(ValueError, match="escapes"):
        _resolve_path(ws, "../proj2/secret.txt")
    with pytest.raises(ValueError, match="escapes"):
        FileSystem(ws).resolve("../proj2/secret.txt")
    assert _resolve_path(ws, "sub/file.py") == (ws / "sub" / "file.py").resolve()


def test_tool_paths_reject_git_dir(tmp_path):
    with pytest.raises(ValueError, match=".git"):
        _resolve_path(tmp_path, ".git/config")


def test_workspace_allowlist_uses_path_semantics(sibling_dirs, monkeypatch):
    ws, sibling = sibling_dirs
    monkeypatch.setenv("ALLOWED_WORKSPACE_ROOTS", str(ws))
    assert validate_workspace(str(ws)) == ws.resolve()
    with pytest.raises(ValueError, match="not allowed"):
        validate_workspace(str(sibling))


def test_disallowed_workspace_is_not_created(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("ALLOWED_WORKSPACE_ROOTS", str(allowed))
    target = tmp_path / "elsewhere" / "new"
    with pytest.raises(ValueError, match="not allowed"):
        validate_workspace(str(target), create=True)
    assert not target.exists()
    created = validate_workspace(str(allowed / "new"), create=True)
    assert created.is_dir()


def test_browse_only_shows_paths_towards_allowed_roots(sibling_dirs, monkeypatch):
    ws, _ = sibling_dirs
    monkeypatch.setenv("ALLOWED_WORKSPACE_ROOTS", str(ws))
    listing = browse_directory(str(ws.parent))
    assert [e["name"] for e in listing["entries"]] == ["proj"]


# ── Conversation ids ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("conv_id", ["../../etc/x", "a/b", "..", "", "x" * 65, "a.b"])
def test_invalid_conversation_ids_rejected(conv_id, tmp_path):
    with pytest.raises(InvalidConversationId):
        validate_conversation_id(conv_id)
    with pytest.raises(InvalidConversationId):
        load_conversation(tmp_path, conv_id)


@pytest.mark.parametrize("conv_id", [
    "0123456789abcdef0123456789abcdef", "default",
    "sess-1716-abc123xyz", "123e4567-e89b-42d3-a456-426614174000",
])
def test_valid_conversation_ids(conv_id):
    assert validate_conversation_id(conv_id) == conv_id


# ── run_command ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("command,program", [
    ("python -m pytest", "python"),
    ("/usr/bin/python3 x.py", "python3"),
    ("  git status", "git"),
    ("C:/Python/python.exe -V", "python"),
    ("/venv/bin/python3.12 -V", "python3"),
    ("pip3.11 install x", "pip3"),
    ("typeset -p", "typeset"),
    ("", ""),
])
def test_command_program(command, program):
    assert _command_program(command) == program


@pytest.mark.parametrize("command", ["printenv", "env", "typeset -p", "pythonx", "curl http://x", "rm -rf ."])
def test_run_command_rejects_unlisted_programs(command, tmp_path):
    assert run_command(tmp_path, command).startswith("Error:")


def test_run_command_does_not_leak_llm_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "leaky-secret")
    out = run_command(tmp_path, f'"{sys.executable}" -c "import os; print(os.environ.get(\'LLM_API_KEY\'))"')
    assert "leaky-secret" not in out
    assert "None" in out


def test_safe_subprocess_env_strips_credentials(monkeypatch):
    for name in ("LLM_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.setenv(name, "secret")
    env = safe_subprocess_env()
    assert not {"LLM_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"} & env.keys()
    assert env.get("PATH") == os.environ.get("PATH")


# ── Web UI request guard ─────────────────────────────────────────────────────

ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})


@pytest.mark.parametrize("scope,method,headers,expected", [
    ("http", "GET", {"host": "localhost:8000"}, None),
    ("http", "GET", {"host": "[::1]:8000"}, None),
    ("http", "GET", {"host": "evil.example:8000"}, 403),  # DNS rebinding
    ("http", "POST", {"host": "127.0.0.1:8000", "content-type": "application/json"}, None),
    ("http", "POST", {"host": "127.0.0.1:8000", "content-type": "text/plain"}, 415),
    ("http", "POST", {"host": "localhost:8000", "origin": "http://evil.example",
                      "content-type": "application/json"}, 403),
    ("http", "POST", {"host": "localhost:8000", "origin": "http://localhost:5173",
                      "content-type": "application/json; charset=utf-8"}, None),
    ("http", "DELETE", {"host": "localhost:8000", "origin": "null"}, 403),
    ("http", "GET", {"host": "localhost:8000", "origin": "http://evil.example"}, None),
    ("websocket", "GET", {"host": "localhost:8000", "origin": "http://evil.example"}, 403),
    ("websocket", "GET", {"host": "localhost:8000", "origin": "http://127.0.0.1:8000"}, None),
])
def test_check_request(scope, method, headers, expected):
    result = check_request(scope, method, headers, ALLOWED)
    assert (result[0] if result else None) == expected


def test_allowed_hostnames_from_env(monkeypatch):
    monkeypatch.setenv("CODING_AGENT_HOST", "0.0.0.0")
    monkeypatch.setenv("CODING_AGENT_ALLOWED_HOSTS", "devbox.lan, 10.0.0.5")
    hosts = allowed_hostnames()
    assert {"devbox.lan", "10.0.0.5", "localhost"} <= hosts
    assert "0.0.0.0" not in hosts


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from ui.app import app

    return TestClient(app, base_url="http://localhost:8000")


def test_ui_guard_end_to_end(client, tmp_path):
    assert client.get("/api/workspace/default").status_code == 200
    assert client.get("/api/workspace/default", headers={"host": "evil.example"}).status_code == 403
    assert client.post("/api/conversations", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    r = client.post("/api/conversations", json={"workspace": str(tmp_path)},
                    headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/conversations", json={"workspace": str(tmp_path)},
                    headers={"origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_ui_rejects_bad_conversation_id(client, tmp_path):
    r = client.get("/api/conversations/..%2F..%2Fx", params={"workspace": str(tmp_path)})
    assert r.status_code in (400, 404)
    r = client.post("/api/chat", json={"message": "hi", "workspace": str(tmp_path),
                                       "conversation_id": "../../escape"})
    assert r.status_code == 400
    assert not (tmp_path.parent / "escape.json").exists()


def test_ui_terminal_websocket_rejects_foreign_origin(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/terminal?session_id=t", headers={"origin": "http://evil.example"}):
            pass
