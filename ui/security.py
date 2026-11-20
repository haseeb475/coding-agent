"""Request guard for the local web UI.

The UI exposes an interactive shell (``/ws/terminal``) and an agent that can
edit files and run commands, and it has no user accounts. It is meant to be
reached only from the local machine. This ASGI middleware blocks the common
ways a *browser* could be abused to reach it anyway:

- DNS rebinding: the ``Host`` header must be a loopback name or an explicitly
  allowed host.
- Cross-site requests: WebSocket handshakes and state-changing requests
  (POST/PUT/PATCH/DELETE) must come from an allowed ``Origin`` (or carry no
  Origin, e.g. curl), and POST/PUT/PATCH bodies must be ``application/json``,
  which a cross-site page cannot send without a CORS preflight.

It is not authentication: anyone who can reach the port directly (other users
on a shared machine, or the network when bound to a non-loopback address) can
still use the UI.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def is_loopback(host: str) -> bool:
    return host.strip("[]").lower() in LOOPBACK_HOSTS


def allowed_hostnames() -> frozenset[str]:
    """Loopback names plus CODING_AGENT_HOST and CODING_AGENT_ALLOWED_HOSTS."""
    hosts = set(LOOPBACK_HOSTS)
    configured = os.environ.get("CODING_AGENT_HOST", "").strip().strip("[]").lower()
    if configured and configured not in ("0.0.0.0", "::"):
        hosts.add(configured)
    extra = os.environ.get("CODING_AGENT_ALLOWED_HOSTS", "")
    hosts.update(h.strip().strip("[]").lower() for h in extra.split(",") if h.strip())
    return frozenset(hosts)


def _hostname(value: str, *, is_url: bool) -> str | None:
    try:
        parts = urlsplit(value if is_url else f"//{value}")
        return parts.hostname  # lowercased, brackets stripped, port removed
    except ValueError:
        return None


def check_request(
    scope_type: str, method: str, headers: dict[str, str], allowed: frozenset[str]
) -> tuple[int, str] | None:
    """Return ``(status, reason)`` if the request must be rejected, else None."""
    host = _hostname(headers.get("host", ""), is_url=False)
    if host not in allowed:
        return 403, f"Host {headers.get('host', '')!r} is not allowed"

    origin = headers.get("origin")
    needs_origin_check = scope_type == "websocket" or method in _UNSAFE_METHODS
    if needs_origin_check and origin is not None:
        if _hostname(origin, is_url=True) not in allowed:
            return 403, f"Origin {origin!r} is not allowed"

    if scope_type == "http" and method in _BODY_METHODS:
        content_type = headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            return 415, "Content-Type must be application/json"
    return None


class LocalRequestGuard:
    """ASGI middleware applying :func:`check_request` to HTTP and WebSocket traffic."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        rejection = check_request(scope["type"], scope.get("method", "GET"), headers, allowed_hostnames())
        if rejection is None:
            await self.app(scope, receive, send)
            return
        status, reason = rejection
        if scope["type"] == "websocket":
            # Closing before accept makes the server answer the handshake with 403.
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        await JSONResponse({"error": reason}, status_code=status)(scope, receive, send)
