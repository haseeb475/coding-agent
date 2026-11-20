# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - First public release

### Added
- A provider-independent LLM layer (`agent/providers/`) with a registry and two adapters:
  - `openai`: any OpenAI Chat Completions-compatible API
  - `azure`: Azure OpenAI
- Configuration through `LLM_*` environment variables, validated up front with clear error messages.
- `LLM_EXTRA_HEADERS` for gateways that need extra HTTP headers.
- `python -m agent.cli --mode ask|debug|work`.
- Web UI settings `CODING_AGENT_HOST`, `CODING_AGENT_PORT`, `CODING_AGENT_ALLOW_REMOTE` and `CODING_AGENT_ALLOWED_HOSTS`.
- A test suite (`tests/`) with a local fake OpenAI-compatible server, and GitHub Actions CI.
- `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, and issue and pull request templates.
- Split requirements files: `requirements-bench.txt` (benchmarks) and `requirements-dev.txt` (development).

### Changed
- **Breaking:** the LLM is now configured through provider-neutral `LLM_*` environment variables (see `.env.example`). There is no default endpoint or model, so `LLM_MODEL` must be set.
- The web UI binds to `127.0.0.1` instead of `0.0.0.0`, and hot reload is opt-in (`CODING_AGENT_RELOAD=1`).
- Transient LLM errors are classified by exception type. Streaming requests are retried only before the first token arrives, so streamed text is never duplicated.
- `main.py` imports the benchmark modules lazily, so `--smoke` works without the benchmark dependencies.
- Library code logs through `logging` instead of `print`.

### Fixed
- Long chats stopped saving new messages to history once the context was trimmed.
- The custom benchmark (`--task`, `--benchmark`) never recognised passing tests.
- The pytest error count was always 0.
- SWE-bench patch cleaning dropped source files whose path contained `test_` (e.g. `latest_x.py`). Only files in test directories, or named `test_*.py` or `*_test.py`, are stripped now. This can change benchmark output compared with earlier runs.
- The terminal reconnect hook was never called, and the frontend build failed on strict TypeScript checks.

### Security
- Path containment checks used string prefixes, so a sibling directory such as `proj2` passed as being inside `proj`. They now compare paths properly. This affects tool paths, `ALLOWED_WORKSPACE_ROOTS` and the folder browser.
- Disallowed workspace folders are no longer created before the allowlist check.
- Conversation ids are validated, which closes a path traversal through `conversation_id`.
- `run_command` now matches the program name exactly instead of by prefix, and `env` and `printenv` were removed from the allowlist.
- LLM credentials are removed from the environment of every subprocess the agent starts.
- The web UI rejects foreign `Host` and `Origin` headers and non-JSON POST bodies, which blocks drive-by and DNS-rebinding attacks.
- Chat Markdown is rendered with raw HTML escaped and unsafe URLs removed.
- The terminal forwards only a fixed set of signals.

### Removed
- Course and presentation material and the internal demo script.
- The unused non-streaming `handle_message()` API and other dead code.
