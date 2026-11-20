"""A minimal OpenAI-compatible Chat Completions server for tests.

Implements just enough of the wire format used by the ``openai`` SDK:

- ``POST /v1/chat/completions`` with Bearer auth (OpenAI-style)
- ``POST /openai/deployments/{deployment}/chat/completions?api-version=...``
  with ``api-key`` header auth (Azure-style)

Responses are scripted per test via ``FakeServer.script``; each scripted item
is either a dict ``{"content": str, "tool_calls": [{"name", "arguments"}]}``
or an int HTTP status code to fail with.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

VALID_KEY = "test-key"


class FakeServer:
    def __init__(self):
        self.app = FastAPI()
        self.requests: list[dict] = []
        self.script: list = []
        self._register_routes()
        self.port = _free_port()
        self._server = None
        self._thread = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def root_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def reset(self):
        self.requests.clear()
        self.script.clear()

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self):
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("fake server did not start")
            time.sleep(0.05)

    def stop(self):
        if self._server:
            self._server.should_exit = True
            self._thread.join(timeout=5)

    # ── routes ───────────────────────────────────────────────────────────

    def _register_routes(self):
        @self.app.post("/v1/chat/completions")
        async def openai_style(request: Request):
            auth = request.headers.get("authorization", "")
            return await self._handle(request, auth == f"Bearer {VALID_KEY}", flavor="openai")

        @self.app.post("/openai/deployments/{deployment}/chat/completions")
        async def azure_style(deployment: str, request: Request):
            ok = request.headers.get("api-key") == VALID_KEY and "api-version" in request.query_params
            return await self._handle(request, ok, flavor="azure", deployment=deployment)

    async def _handle(self, request: Request, authorized: bool, **meta):
        body = await request.json()
        self.requests.append({"body": body, "headers": dict(request.headers),
                              "query": dict(request.query_params), **meta})
        if not authorized:
            return _error(401, "Incorrect API key provided.", "invalid_api_key")

        item = self.script.pop(0) if self.script else {"content": "connection ok"}
        if isinstance(item, int):
            return _error(item, f"simulated status {item}", "server_error")

        model = body.get("model", "")
        if body.get("stream"):
            return StreamingResponse(_sse(item, model), media_type="text/event-stream")
        return JSONResponse(_completion(item, model))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _error(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "code": code}},
        status_code=status,
    )


def _tool_calls(item: dict) -> list[dict]:
    return [
        {"id": f"call_{i}", "type": "function",
         "function": {"name": tc["name"], "arguments": json.dumps(tc.get("arguments", {}))}}
        for i, tc in enumerate(item.get("tool_calls", []))
    ]


def _completion(item: dict, model: str) -> dict:
    message = {"role": "assistant", "content": item.get("content")}
    calls = _tool_calls(item)
    if calls:
        message["tool_calls"] = calls
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
    }


def _chunk(delta: dict, model: str, finish=None) -> str:
    payload = {
        "id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse(item: dict, model: str):
    content = item.get("content") or ""
    for i in range(0, len(content), 4):  # split text into several deltas
        yield _chunk({"role": "assistant", "content": content[i:i + 4]}, model)
    for i, call in enumerate(_tool_calls(item)):
        args = call["function"]["arguments"]
        half = len(args) // 2
        yield _chunk({"tool_calls": [{"index": i, "id": call["id"], "type": "function",
                                      "function": {"name": call["function"]["name"], "arguments": args[:half]}}]},
                     model)
        yield _chunk({"tool_calls": [{"index": i, "function": {"arguments": args[half:]}}]}, model)
    yield _chunk({}, model, finish="tool_calls" if item.get("tool_calls") else "stop")
    usage = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0, "model": model,
             "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
    yield f"data: {json.dumps(usage)}\n\n"
    yield "data: [DONE]\n\n"
